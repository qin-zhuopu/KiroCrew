"""Tests for ``kirocrew studio`` —— 只测命令行这一层（ACP-2231）.

契约只有三件：**打的是哪条**（方法 + 路径）、**后台的状态码变成什么退出码**、
**stdout 是不是纯 JSON**。所以传输那一条（``_urlopen``）整条换掉，一个真请求都不
发；后台为什么拒（验收没过、正在部署）是 :mod:`test_ai_studio_prod_version` 的事，
这里只验那句 reason 有没有原样到 stderr。

两条容易被漏掉、但都会「测试绿而线上坏」的性质也钉在这里：

* 换 token 的凭据**只递本机环回**：``--gateway`` 指到别的机器时递本机 secret 是外泄；
* ``--gateway`` 写在主命令上还是子命令上**都算数**（argparse 用子解析器的默认值覆盖
  namespace，写错成一个普通默认值就会静默丢掉主命令上那一个）。
"""

from __future__ import annotations

import argparse
import io
import json
import urllib.error
import urllib.parse
import urllib.request

import pytest

from kiro_crew import cli_studio

BASE = "http://127.0.0.1:6790"
MINT = "/api/token/local"


class FakeResponse(io.BytesIO):
    """最小的一条响应：``read()`` + ``status``，够 :func:`_read_json` 用。"""

    def __init__(self, payload: object, status: int = 200, raw: bytes | None = None) -> None:
        body = raw if raw is not None else json.dumps(payload, ensure_ascii=False).encode()
        super().__init__(body)
        self.status = status

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class Transport:
    """假 ``_urlopen``：记录每一次请求，按 URL 前缀决定回什么。

    ``replies`` 是 ``URL 片段 -> 响应``，命中第一个包含该片段的路径 —— 换 token 那条
    和业务那条要回不同的东西，用片段分最省事，也最接近「它在打哪一条」这句话。
    """

    def __init__(self, **replies: object) -> None:
        self.replies: list[tuple[str, object]] = list(replies.items())
        self.calls: list[tuple[str, str, dict[str, str]]] = []
        self.sockets: list[str | None] = []

    def __call__(self, req: urllib.request.Request, socket_path: str | None = None):
        url = req.full_url
        self.calls.append((str(req.get_method()), url, dict(req.header_items())))
        self.sockets.append(socket_path)
        for fragment, reply in self.replies:
            if fragment in url:
                if isinstance(reply, Exception):
                    raise reply
                assert isinstance(reply, FakeResponse)
                return reply
        return FakeResponse({"detail": "not routed in this fake", "url": url}, status=599)

    def path_of(self, index: int = -1) -> str:
        return urllib.parse.urlsplit(self.calls[index][1]).path

    def query_of(self, index: int = -1) -> dict[str, str]:
        return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.calls[index][1]).query))


@pytest.fixture()
def wired(monkeypatch):
    """把三条对外接缝都换掉：传输、本机 secret、网关 socket 路径。

    后两条必须换：真去读 ``.local_secret`` 会读到跑测试那台机器上真的网关凭据（有就
    带、没有就不带，断言随之摇摆），真去算 socket 路径会 import ``dashboard.urls``
    那条不便宜的链子。
    """
    monkeypatch.setattr(cli_studio, "_local_secret", lambda port: "local-secret")
    monkeypatch.setattr(cli_studio, "_gateway_socket", lambda url: "/tmp/gw.sock")
    return monkeypatch


def _args(**fields: object) -> argparse.Namespace:
    """一条 ``kirocrew studio`` 的参数（``gateway=None`` = 没给这个选项）。"""
    return argparse.Namespace(**fields)


def _exec(capsys, monkeypatch, transport: Transport, **fields: object) -> tuple[int, str, str]:
    """跑一次命令，回 ``(退出码, stdout, stderr)``。"""
    monkeypatch.setattr(cli_studio, "_urlopen", transport)
    rc = cli_studio.studio_cmd(_args(**{"gateway": None, **fields}))
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


# ---------------------------------------------------------------------------
# 1. 三条子命令 → 三条路径
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action,method,path",
    [
        ("version", "POST", "/api/apps/ai-studio/projects/p1/prod-server/version"),
        ("release", "POST", "/api/apps/ai-studio/projects/p1/prod-server/deploy"),
        ("status", "GET", "/api/apps/ai-studio/projects/p1/prod-server"),
    ],
)
def test_each_subcommand_hits_its_route(capsys, wired, action, method, path):
    """子命令 → 后台路由的对应关系就是这一单的全部契约，逐条钉住。

    ``release`` 打的是 ``deploy``：〔确认发布〕= 升版 + 发布 = 现有那一条，命令行不许
    另发明一个「只发布不升版」的东西（后台也没有这个语义）。
    """
    transport = Transport(
        **{MINT: FakeResponse({"token": "tok-1"}), path: FakeResponse({"ok": True})}
    )
    rc, out, err = _exec(capsys, wired, transport, studio_action=action, project="p1")
    assert rc == 0, err
    assert (transport.calls[0][0], transport.path_of(0)) == ("GET", MINT)
    assert (transport.calls[1][0], transport.path_of(1)) == (method, path)
    assert json.loads(out) == {"ok": True}


def test_project_id_is_url_encoded(capsys, wired):
    """项目 id 原样进不了路径：``a/b`` 会变成另一条路由，``..`` 会爬到别的资源上。"""
    transport = Transport(
        **{MINT: FakeResponse({"token": "t"}), "prod-server": FakeResponse({"ok": True})}
    )
    rc, _out, err = _exec(capsys, wired, transport, studio_action="status", project="a/b")
    assert rc == 0, err
    # 路径里只该有一段（编码后是 a%2Fb），断言的是「没多出一个 segment」
    assert transport.path_of(-1) == "/api/apps/ai-studio/projects/a%2Fb/prod-server"


def test_success_prints_only_json(capsys, wired):
    """stdout 是纯 JSON：它要被 ``json.loads`` 直接吃，一句提示都不许混进去。"""
    body = {"version": "v3", "commit": "c" * 40, "reused": False}
    transport = Transport(
        **{MINT: FakeResponse({"token": "t"}), "prod-server/version": FakeResponse(body)}
    )
    rc, out, err = _exec(capsys, wired, transport, studio_action="version", project="p1")
    assert rc == 0, err
    assert json.loads(out) == body
    assert err == ""


# ---------------------------------------------------------------------------
# 2. 后台的拒绝 → 退出码 1 + stderr 那句原文
# ---------------------------------------------------------------------------


def test_backend_refusal_is_exit_1_with_its_message(capsys, wired):
    """409 not_accepted：退出码 1，stderr 带后台那句原文，stdout 一个字节都没有。"""
    transport = Transport(
        **{
            MINT: FakeResponse({"token": "t"}),
            "prod-server/version": FakeResponse(
                {
                    "error": "先通过验收（最新一次验收要通过，且之后没有新提交）",
                    "code": "not_accepted",
                },
                status=409,
            ),
        }
    )
    rc, out, err = _exec(capsys, wired, transport, studio_action="version", project="p1")
    assert rc == 1
    assert out == ""
    assert "先通过验收" in err
    # code 也带出来：界面按 error 说话，脚本按 code 分支
    assert "not_accepted" in err


def test_transport_failure_is_exit_1(capsys, wired):
    """没人应答：退出码 1，且把**打的地址**写进原因（打错 --gateway 与网关死了长一样）。"""
    # 每一次请求都抛「没人应答」：换 token 与业务请求两条都抛，走到哪一步都是同一个结论
    transport = Transport(**{"": urllib.error.URLError("connection refused")})
    rc, out, err = _exec(capsys, wired, transport, studio_action="status", project="p1")
    assert rc == 1
    assert out == ""
    assert BASE in err or "prod-server" in err


def test_non_json_body_is_shown(capsys, wired):
    """不是 JSON 的响应体原样进 stderr：挡在网关前面的东西回一段 HTML 时，那是唯一线索。"""
    transport = Transport(
        **{
            MINT: FakeResponse({"token": "t"}),
            "prod-server": FakeResponse(None, 502, raw=b"<html>bad gateway</html>"),
        }
    )
    rc, _out, err = _exec(capsys, wired, transport, studio_action="status", project="p1")
    assert rc == 1
    assert "bad gateway" in err


def test_usage_error_is_exit_2(capsys, wired):
    """自己的用法错（地址写歪）是 2，和「后台拒了」的 1 分开：脚本要能分辨谁的错。"""
    transport = Transport()
    rc, out, err = _exec(
        capsys,
        wired,
        transport,
        studio_action="status",
        project="p1",
        gateway="127.0.0.1:6790",
    )
    assert rc == 2
    assert out == ""
    assert transport.calls == []


# ---------------------------------------------------------------------------
# 3. 网关地址的三级来源
# ---------------------------------------------------------------------------


def test_gateway_flag_wins(capsys, wired):
    transport = Transport(
        **{MINT: FakeResponse({"token": "t"}), "prod-server": FakeResponse({"ok": True})}
    )
    rc, _out, err = _exec(
        capsys,
        wired,
        transport,
        studio_action="status",
        project="p1",
        gateway="http://127.0.0.1:7777/",
    )
    assert rc == 0, err
    assert transport.calls[-1][1].startswith("http://127.0.0.1:7777/api/apps/")
    # 结尾多写的斜杠不许变成 ``//api``：那是一条后台没有的路由
    assert "//api" not in transport.calls[-1][1]


def test_gateway_env_is_the_second_source(capsys, wired, monkeypatch):
    monkeypatch.setenv("KIROCREW_GATEWAY_URL", "http://127.0.0.1:8888")
    transport = Transport(
        **{MINT: FakeResponse({"token": "t"}), "prod-server": FakeResponse({"ok": True})}
    )
    rc, _out, err = _exec(capsys, wired, transport, studio_action="status", project="p1")
    assert rc == 0, err
    assert transport.calls[-1][1].startswith("http://127.0.0.1:8888/api/apps/")


def test_gateway_default_when_nothing_is_given(capsys, wired, monkeypatch):
    monkeypatch.delenv("KIROCREW_GATEWAY_URL", raising=False)
    transport = Transport(
        **{MINT: FakeResponse({"token": "t"}), "prod-server": FakeResponse({"ok": True})}
    )
    rc, _out, err = _exec(capsys, wired, transport, studio_action="status", project="p1")
    assert rc == 0, err
    assert transport.calls[-1][1].startswith(BASE + "/api/apps/")


def test_parser_accepts_gateway_before_and_after_the_subcommand():
    """``studio --gateway X status p`` 与 ``studio status p --gateway X`` 都要算数。

    后者是人的手感，而 argparse 会用**子解析器**的默认值覆盖 namespace 里同一个 dest：
    子命令上那一位若给成普通默认值，主命令上写的地址会被静默丢掉，命令行打到默认端口
    上去 —— 测试跑的是解析器本体，不是我对 argparse 的记忆。
    """
    parser = argparse.ArgumentParser(prog="kirocrew")
    sub = parser.add_subparsers(dest="command")
    cli_studio.register_studio_parser(sub)
    before = parser.parse_args(["studio", "--gateway", "http://a:1", "status", "p1"])
    after = parser.parse_args(["studio", "status", "p1", "--gateway", "http://a:2"])
    plain = parser.parse_args(["studio", "status", "p1"])
    assert before.gateway == "http://a:1"
    assert after.gateway == "http://a:2"
    assert plain.gateway is None


# ---------------------------------------------------------------------------
# 4. 凭据只递本机
# ---------------------------------------------------------------------------


def test_local_secret_mints_a_token_and_presents_it(capsys, wired):
    """本机：secret → ``/api/token/local`` → 业务请求带 ``?token=``（那些路由不认 secret）。"""
    transport = Transport(
        **{MINT: FakeResponse({"token": "tok-9"}), "prod-server": FakeResponse({"ok": True})}
    )
    rc, _out, err = _exec(capsys, wired, transport, studio_action="status", project="p1")
    assert rc == 0, err
    assert transport.calls[0][2].get("X-local-secret") == "local-secret"
    assert transport.query_of(-1)["token"] == "tok-9"
    # 凭据走 header 而不是 query：secret 进 URL 会落进访问日志
    assert "local-secret" not in transport.calls[1][1]


def test_non_loopback_gateway_gets_no_local_secret(capsys, wired, monkeypatch):
    """``--gateway`` 指向别的机器：本机那份 secret 对它毫无意义，递过去就是外泄。"""
    seen: list[str] = []
    monkeypatch.setattr(cli_studio, "_local_secret", lambda port: seen.append("read") or "s")
    transport = Transport(**{"prod-server": FakeResponse({"ok": True})})
    rc, _out, err = _exec(
        capsys,
        wired,
        transport,
        studio_action="status",
        project="p1",
        gateway="http://10.0.0.9:6790",
    )
    assert rc == 0, err
    assert seen == []
    assert transport.calls[0][1].endswith("/prod-server")
    assert not any("X-local-secret" in dict(c[2]) for c in transport.calls)


def test_failed_mint_still_sends_the_request(capsys, wired):
    """换 token 失败不是终局：业务请求照打，网关的 401/403 比命令行猜一句更准。"""
    transport = Transport(
        **{
            MINT: urllib.error.URLError("nobody on the port"),
            "prod-server": FakeResponse({"state": "running"}),
        }
    )
    rc, out, err = _exec(capsys, wired, transport, studio_action="status", project="p1")
    assert rc == 0
    assert json.loads(out)["state"] == "running"
    # 也不能一声不吭：否则操作者只看到一个 401，而真原因是 secret 没读到
    assert "token" in err.lower()


def test_missing_local_secret_sends_no_mint(capsys, wired, monkeypatch):
    """本机没有 secret（网关没起 / 全新数据目录）就一次都不试，直接打业务请求。"""
    monkeypatch.setattr(cli_studio, "_local_secret", lambda port: "")
    transport = Transport(**{"prod-server": FakeResponse({"ok": True})})
    rc, _out, err = _exec(capsys, wired, transport, studio_action="status", project="p1")
    assert rc == 0, err
    assert [c[1] for c in transport.calls] == [BASE + "/api/apps/ai-studio/projects/p1/prod-server"]


def test_unix_socket_is_preferred_for_loopback(capsys, wired):
    """本机走网关那条 0600 的 socket：网关能用 SO_PEERCRED 验对端，TCP 口谁都能 bind。"""
    transport = Transport(
        **{MINT: FakeResponse({"token": "t"}), "prod-server": FakeResponse({"ok": True})}
    )
    rc, _out, err = _exec(capsys, wired, transport, studio_action="status", project="p1")
    assert rc == 0, err
    assert transport.sockets == ["/tmp/gw.sock", "/tmp/gw.sock"]


# ---------------------------------------------------------------------------
# 5. 挂进 kirocrew 命令
# ---------------------------------------------------------------------------


def test_studio_is_a_real_subcommand():
    """命令挂上了顶层解析器，且默认子命令缺参数时 argparse 自己就拒（不是 KeyError）。"""
    parser = argparse.ArgumentParser(prog="kirocrew")
    sub = parser.add_subparsers(dest="command")
    cli_studio.register_studio_parser(sub)
    parsed = parser.parse_args(["studio", "version", "p1"])
    assert parsed.command == "studio" and parsed.studio_action == "version"
    with pytest.raises(SystemExit):
        parser.parse_args(["studio"])


def test_studio_appears_in_the_cli_help():
    """``cli_help`` 的清单与注册的命令必须一一对应（test_cli_help 钉的是集合相等）。"""
    from kiro_crew import cli_help

    assert "studio" in cli_help.SUMMARIES
