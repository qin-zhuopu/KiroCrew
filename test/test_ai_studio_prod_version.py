"""Tests for ``ProdServer.cut_version`` —— 只升版不发布.

同一个注入替身骨架（``test_ai_studio_prodserver`` 那套 World）：单测里一个真 git、
真进程、真端口都不起。这里只测「升版」这一条路径独有的东西：

* 三道闸门（部署在跑 / 没过验收 / 代码没变）与 deploy 同源；
* 升版**不碰进程**：不起孩子、不构建、不申请端口、不挂网关 conf、不写状态文件；
* tag + 推 tag + 台账各一次，且「先推分支再推标签」的顺序与 deploy 成功路径一致；
* git / 台账失败只写日志（口径同 :meth:`ProdServer._succeed`）；
* 升完版再点 deploy 必须**沿用**这个版本号（台账判断，ACP-2219），这是「先升版再
  发布」与「直接确认发布」结果一致的机制，所以用真台账端到端跑通才算数。
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from kiro_crew.apps.builtins.ai_studio.backend import (
    devserver,
    prodserver,
    projects,
    publish,
    routes,
)

STABLE = "eqp-14409.gb10.jereh-pe.cn"
HEAD = "a" * 40


@pytest.fixture()
def home(tmp_path, monkeypatch):
    h = tmp_path / "crew"
    h.mkdir()
    monkeypatch.setenv("KIROCREW_HOME", str(h))
    monkeypatch.setenv("KIROCREW_STAFF_ID", "14409")
    # 进程内缓存是进程全局：填了它的测试不许把它递给下一个测试
    monkeypatch.setattr(prodserver, "_SERVERS", {})
    return h


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    root.mkdir(parents=True)
    monkeypatch.setenv("KIROCREW_STAFF_ID", "14409")
    monkeypatch.setenv("AI_STUDIO_GATEWAY_CONF_DIR", str(tmp_path / "confd"))
    monkeypatch.delenv("AI_STUDIO_DEV_DOMAIN_SUFFIX", raising=False)
    monkeypatch.delenv("AI_STUDIO_GATEWAY_UPSTREAM", raising=False)
    return root


class World:
    """deploy 那套替身的同款，但孩子/构建/端口/网关四样只做一件事：**raise**。

    升版用不上它们，所以任何一次调用都是 ``cut_version`` 越界的证据。把它们写成
    「一碰就炸」而不是计数器，是因为计数器要在每个断言里再数一遍，漏一项就漏一个
    越界；炸在案发现场，报错里带的就是那一步的名字。
    """

    def __init__(
        self,
        monkeypatch,
        *,
        git_code: int = 0,
        push_code: int | None = None,
        branch_push_code: int = 0,
        fail_release: bool = False,
        head: str = HEAD,
    ) -> None:
        self.head = head
        self.servers: list[prodserver.ProdServer] = []
        self.spawned: list[list[str]] = []
        self.builds: list[list[str]] = []
        self.claimed: list[tuple[int, str]] = []
        self.gateway_ops: list[tuple[str, str]] = []
        self.git_calls: list[list[str]] = []
        self.git_code = git_code
        # 打标签和推标签分开给：常态是本地 tag 打得成、远端推不出去（个人仓没配
        # 凭据），两件事混在一个码里就分不清「哪一步只写日志」。
        self.push_code = git_code if push_code is None else push_code
        self.branch_push_code = branch_push_code
        self.releases: list[dict[str, Any]] = []
        self.fail_release = fail_release
        monkeypatch.setattr(devserver.platform_compat, "pid_exists", lambda p: False)

    # -- seams -----------------------------------------------------------

    def runner(self, cmd, cwd, env, log_path) -> int:
        self.spawned.append(list(cmd))
        raise AssertionError("升版不许起进程")

    def builder(self, cmd, cwd, env, log_path, timeout_s):
        self.builds.append(list(cmd))
        raise AssertionError("升版不许构建")

    def prober(self, url: str) -> int:
        raise AssertionError("升版不许探网址")

    class _Ports:
        def __init__(self, world: "World") -> None:
            self.world = world

        def free(self, port: int) -> bool:
            return True

        def claim(self, port: int, owner: str) -> None:
            self.world.claimed.append((port, owner))
            raise AssertionError("升版不许申请端口")

        def release(self, port: int) -> None:
            pass

    class _Gateway:
        def __init__(self, world: "World") -> None:
            self.world = world

        def write(self, path, text) -> None:
            self.world.gateway_ops.append(("write", str(path)))
            raise AssertionError("升版不许挂网关 conf")

        def remove(self, path) -> None:
            self.world.gateway_ops.append(("remove", str(path)))

    def git(self, argv: list[str]) -> tuple[int, str]:
        self.git_calls.append(list(argv))
        if argv[:2] == ["rev-parse", "--abbrev-ref"]:
            return 0, "develop\n"
        if argv[0] == "rev-parse":
            return 0, self.head + "\n"
        if argv[0] == "push":
            if len(argv) > 2 and str(argv[2]).startswith("HEAD:"):
                return self.branch_push_code, "branch push rejected: read-only fork"
            return self.push_code, "push rejected: remote fork has no credentials"
        if argv[0] == "tag":
            return self.git_code, "" if self.git_code == 0 else "tag already exists"
        return 0, ""

    def pushes(self, refspec_prefix: str = "") -> list[list[str]]:
        return [
            call
            for call in self.git_calls
            if call[:2] == ["push", "origin"] and " ".join(call[2:]).startswith(refspec_prefix)
        ]

    def git_verbs(self) -> list[str]:
        return [call[0] for call in self.git_calls]

    def recorder(self, project_id: str, **kwargs: Any) -> dict:
        if self.fail_release:
            raise RuntimeError("release store is read-only")
        self.releases.append({"project_id": project_id, **kwargs})
        return {"version": kwargs.get("version")}

    def make(self, ws, project: dict | None = None) -> prodserver.ProdServer:
        server = prodserver.ProdServer(
            ws,
            project if project is not None else {"id": "p1", "code": "eqp"},
            runner=self.runner,
            prober=self.prober,
            ports=self._Ports(self),
            gateway=self._Gateway(self),
            builder=self.builder,
            git=self.git,
            recorder=self.recorder,
            nap=lambda s: None,
        )
        self.servers.append(server)
        return server

    def accept(self, ws, *, result: str = "passed", **fields: Any) -> dict:
        record = {
            "id": fields.pop("id", "acc-1"),
            "result": result,
            "voided": fields.pop("voided", False),
            "commitHash": fields.pop("commitHash", HEAD),
            "requirementVersion": fields.pop("requirementVersion", "req-3"),
            "at": fields.pop("at", "2026-10-10T00:00:00Z"),
            **fields,
        }
        directory = ws / ".ai-studio" / "accept"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{record['id']}.json").write_text(
            json.dumps(record, ensure_ascii=False), encoding="utf-8"
        )
        return record


# ---------------------------------------------------------------------------
# 1. 闸门
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["none", "failed", "voided", "new_commit"])
def test_cut_version_gate_rejects_without_touching_anything(ws, monkeypatch, kind):
    """验收闸门与 deploy 同源同词：409 not_accepted，且一条 git 都不许跑。

    「一条 git 都没跑」是有牙齿的断言：升版本质是打 tag，若它先动手再验闸门，仓库
    里就多了一个指向没过验收代码的标签，而它一旦被推出去就删不干净了。
    """
    world = World(monkeypatch)
    if kind == "failed":
        world.accept(ws, result="failed")
    elif kind == "voided":
        world.accept(ws, voided=True)
    elif kind == "new_commit":
        world.accept(ws, commitHash="b" * 40)
    server = world.make(ws)

    with pytest.raises(prodserver.ProdServerError) as exc:
        server.cut_version()
    assert exc.value.code == "not_accepted"
    assert exc.value.status == 409
    # 只许读（rev-parse 拿 HEAD 是算版本号的必要一步），一枚 tag 都不许多打
    assert [c[0] for c in world.git_calls if c[0] in ("tag", "push")] == []
    assert not server.state_path.exists(), "升版不许写状态文件"


def test_bad_code_is_400_before_the_gate(ws, monkeypatch):
    """没配代号的项目拿 400 代号不合规，而不是先被验收弹 409（同 deploy 的顺序）。"""
    world = World(monkeypatch)
    server = world.make(ws, {"id": "p1", "code": "not a code"})
    with pytest.raises(prodserver.ProdServerError) as exc:
        server.cut_version()
    assert (exc.value.code, exc.value.status) == ("bad_code", 400)


def test_cut_version_during_a_deploy_is_409(ws, monkeypatch):
    """部署在跑时不许插一个 tag：那个提交正被构建到一半。

    判据是 :meth:`status`（状态文件 + 活线程 + 探活的合成人），不是「有没有别的
    请求」：升版与 deploy 必须问同一个事实，否则命令行可以在界面正部署时插进去。
    """
    world = World(monkeypatch)
    world.accept(ws)
    server = world.make(ws)
    server._write_state(state="deploying")
    server._busy_gen = 1

    with pytest.raises(prodserver.ProdServerError) as exc:
        server.cut_version()
    assert (exc.value.code, exc.value.status) == ("already_deploying", 409)
    assert [c[0] for c in world.git_calls if c[0] in ("tag", "push")] == []
    # 拒过之后那句 deploying 还在：升版不许把别人的部署判死
    assert server._read_state()["state"] == "deploying"


# ---------------------------------------------------------------------------
# 2. 正常升版：先推分支 → 打 tag → 推 tag → 记台账，进程一样不碰
# ---------------------------------------------------------------------------


def test_cut_version_tags_and_records_without_touching_processes(ws, monkeypatch):
    world = World(monkeypatch)
    world.accept(ws)
    server = world.make(ws)

    result = server.cut_version()
    assert result == {"version": "v1", "commit": HEAD, "reused": False}

    # 顺序就是这一单的契约：读 HEAD → 问当前分支 → 推分支（ACP-2218：只推过标签的
    # 个人仓 clone 出来是空工作区）→ 打 tag → 推 tag
    assert world.git_verbs() == ["rev-parse", "rev-parse", "push", "tag", "push"]
    assert world.pushes("HEAD:") == [["push", "origin", "HEAD:develop"]]
    tag_index = world.git_verbs().index("tag")
    assert world.git_calls[tag_index][:3] == ["tag", "-a", "v1"]
    assert world.pushes("v1") == [["push", "origin", "v1"]]
    assert world.git_calls.index(world.pushes("HEAD:")[0]) < tag_index

    # 台账一次，指向正式固定网址；deployment_id 是空串 —— 没有部署就不编一个假 id
    assert len(world.releases) == 1
    release = world.releases[0]
    assert release["version"] == "v1"
    assert release["commit_hash"] == HEAD
    assert release["url"] == f"https://{STABLE}/"
    assert release["deployment_id"] == ""

    # 进程侧一无所有：状态文件没落盘，孩子/构建/端口/网关连一次都没被叫到
    assert not server.state_path.exists()
    assert world.spawned == []
    assert world.builds == []
    assert world.claimed == []
    assert world.gateway_ops == []
    log = server.log_path.read_text(encoding="utf-8")
    assert "升版：v1" in log and "未发布" in log


def test_tag_push_failure_still_cuts(ws, monkeypatch):
    """推标签被拒（个人仓没配凭据是常态）只写日志：本地的号已经向上，远端是台账的事。"""
    world = World(monkeypatch, push_code=128)
    world.accept(ws)
    server = world.make(ws)

    assert server.cut_version()["version"] == "v1"
    # tag 打成、推不出去：不打 tag 就不该往下推，所以推这一步必须存在过
    assert world.git_verbs().count("tag") == 1
    assert world.pushes("v1") == [["push", "origin", "v1"]]
    assert len(world.releases) == 1
    log = server.log_path.read_text(encoding="utf-8")
    assert "推 tag 失败" in log and "打 tag 失败" not in log


def test_tag_creation_failure_still_cuts(ws, monkeypatch):
    """打 tag 也失败（同名 tag 已存在是常见的那一种）时，台账照记、命令照成。

    与 :meth:`_succeed` 同口径：台账是给人看的账，不是服务的运行时依赖；这里没有
    「服务」可保，代价是多升一版，不是把命令行报成崩溃。
    """
    world = World(monkeypatch, git_code=1)
    world.accept(ws)
    server = world.make(ws)

    assert server.cut_version()["version"] == "v1"
    assert world.pushes("v1") == [], "tag 没打成就不许推它"
    assert len(world.releases) == 1
    assert "打 tag 失败" in server.log_path.read_text(encoding="utf-8")


def test_release_ledger_failure_still_cuts(ws, monkeypatch):
    """台账写不进去也不许炸。代价如实写在日志里：tag 已在而台账没有，下一次 deploy
    查不到这条记录会再升一版 —— 多升一版是这一条的代价，把命令报成崩溃不是。"""
    world = World(monkeypatch, fail_release=True)
    world.accept(ws)
    server = world.make(ws)

    assert server.cut_version()["version"] == "v1"
    assert world.git_verbs().count("tag") == 1
    assert "发布记录没记上" in server.log_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 3. 代码没变：reused=True，什么都不做
# ---------------------------------------------------------------------------


def test_cut_version_on_unchanged_code_is_a_no_op(home, ws, monkeypatch):
    """台账最新那条就记在 HEAD 上 → reused，不推、不打 tag、不记第二条。

    台账用真的（``publish.record_release``）：「什么都不做」的判据来自台账本身，
    假 recorder 怎么接都能过，真存储接错了这条就红。
    """
    world = World(monkeypatch)
    project = projects.create_project("equipment", "", code="eqp")
    _point_workspace_at(project["id"], ws)
    world.accept(ws)
    publish.record_release(
        project["id"],
        version="v1",
        commit_hash=HEAD,
        form="full",
        requirement_version="req-3",
        jira_task_ids=[],
        url=f"https://{STABLE}/",
        deployment_id="dep-old",
    )
    server = world.make(ws, project)

    assert server.cut_version() == {"version": "v1", "commit": HEAD, "reused": True}
    # rev-parse 除外：读 HEAD 就是判据本身
    assert [c for c in world.git_calls if c[0] != "rev-parse"] == []
    assert world.releases == []
    assert [r["version"] for r in publish.list_release_records(project["id"])] == ["v1"]
    assert "已经存在" in server.log_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 4. 升完版再发布：deploy 必须沿用这个版本号（两条路殊途同归的机制）
# ---------------------------------------------------------------------------


class DeployWorld(World):
    """把「进程那几件东西」换回能用的替身：这一条要真跑一次 deploy 的七步。"""

    def __init__(self, monkeypatch) -> None:
        super().__init__(monkeypatch)
        self._next_pid = 7000
        self.alive: dict[int, bool] = {}
        self.gateway_written: dict[str, str] = {}
        monkeypatch.setattr(
            devserver.platform_compat, "pid_exists", lambda p: bool(self.alive.get(p))
        )
        monkeypatch.setattr(devserver.platform_compat, "process_start_time", lambda p: "tok")
        monkeypatch.setattr(devserver.platform_compat, "kill_process_tree", lambda p, s: None)

    def runner(self, cmd, cwd, env, log_path) -> int:
        self._next_pid += 1
        self.alive[self._next_pid] = True
        self.spawned.append(list(cmd))
        return self._next_pid

    def builder(self, cmd, cwd, env, log_path, timeout_s):
        self.builds.append(list(cmd))
        return 0, "built ok"

    def prober(self, url: str) -> int:
        return 200

    class _Ports(World._Ports):
        def claim(self, port: int, owner: str) -> None:
            self.world.claimed.append((port, owner))

    class _Gateway(World._Gateway):
        def write(self, path, text) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            self.world.gateway_ops.append(("write", str(path)))
            self.world.gateway_written[str(path)] = text

    def recorder(self, project_id: str, **kwargs: Any) -> dict:
        # write-through：deploy 要不要沿用版本号，读的就是这份存储
        self.releases.append({"project_id": project_id, **kwargs})
        return publish.record_release(project_id, **kwargs)

    def make(self, ws, project=None):
        server = super().make(ws, project)

        def inline(generation, label, domains, record, reuse_version):
            # 七步在 deploy() 里同步跑完，测试不等线程
            server._deploy(generation, label, domains, record, reuse_version)

        server._start_deploy = inline  # type: ignore[method-assign]
        return server


def test_deploy_after_a_cut_reuses_the_cut_version(home, ws, monkeypatch):
    """cut → deploy 的终态 == 直接 deploy：同一个版本号、一个 tag、一条台账。

    端到端 + 真台账：deploy 沿用版本号靠的是「最新那条台账的 commit == HEAD」，而
    这条记录正是 cut_version 写的。假 recorder 接不上台账，_version_plan 永远看不
    到升版的痕迹，这条测试就退化成什么都没测。
    """
    world = DeployWorld(monkeypatch)
    project = projects.create_project("equipment", "", code="eqp")
    _point_workspace_at(project["id"], ws)
    world.accept(ws)
    server = world.make(ws, project)

    cut = server.cut_version()
    assert cut["reused"] is False
    # 升版只动 git 与台账：这时正式网址上跑的还是旧的一套（或者什么都没有）
    assert world.spawned == []

    view = server.deploy()
    assert view["state"] == "running"
    assert view["version"] == "v1", "deploy 必须沿用刚升的号，而不是再 +1"
    assert view["versionUrl"] == f"https://v1-{STABLE}/"
    assert len(world.spawned) == 2

    rows = publish.list_release_records(project["id"])
    assert [r["version"] for r in rows] == ["v1"]
    assert world.git_verbs().count("tag") == 1
    assert world.pushes("v1") == [["push", "origin", "v1"]]

    # 换了代码才升下一版。中间睡一下：台账按 ts 倒序取最新，两次写入撞在同一个浮点
    # 数上时「最新那条」就成了目录顺序的巧合，沿用的判据会被搅浑
    time.sleep(0.01)
    world.head = "c" * 40
    world.accept(ws, id="acc-2", at="2026-10-11T00:00:00Z", commitHash=world.head)
    world.spawned.clear()
    assert server.deploy()["version"] == "v2"


# ---------------------------------------------------------------------------
# 5. 路由层
# ---------------------------------------------------------------------------


def _make_app(monkeypatch, enabled=True):
    monkeypatch.setattr(routes, "is_app_enabled", lambda _name: enabled)
    app = web.Application()
    routes.register_routes(app)
    return app


def _point_workspace_at(project_id: str, workspace, code: str | None = "eqp") -> None:
    path = projects.projects_root() / project_id / "project.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["workspaceDir"] = str(workspace)
    if code is not None:
        data["code"] = code
    path.write_text(json.dumps(data), encoding="utf-8")


async def _create(client) -> str:
    resp = await client.post(
        "/api/apps/ai-studio/projects", json={"name": "equipment", "description": ""}
    )
    assert resp.status == 201
    return (await resp.json())["project"]["id"]


def _stub_cut(monkeypatch, *, result: dict | None = None, error: Exception | None = None):
    """路由层只测「前置 → cut_version → 状态码」，升版本身的对错在上面钉过了。

    替身挂在 ``prod_server_for`` 上而不是绕过它：路由拿到的是「这个项目的工作区
    对应的那台服务器」，这一层的契约就是它把 project + ws 交对了对象。
    """
    calls: list[str] = []

    class Cutter:
        def cut_version(self) -> dict:
            calls.append("cut")
            if error is not None:
                raise error
            return (
                result if result is not None else {"version": "v1", "commit": HEAD, "reused": False}
            )

    monkeypatch.setattr(prodserver, "prod_server_for", lambda project, workspace: Cutter())
    return calls


@pytest.mark.asyncio
async def test_version_route_returns_the_cut_result(home, ws, monkeypatch):
    calls = _stub_cut(monkeypatch)
    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        pid = await _create(client)
        resp = await client.post(f"/api/apps/ai-studio/projects/{pid}/prod-server/version")
        assert resp.status == 200
        assert await resp.json() == {"version": "v1", "commit": HEAD, "reused": False}
        assert calls == ["cut"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,code,message",
    [
        (409, "not_accepted", prodserver.NOT_ACCEPTED),
        (409, "already_deploying", "部署正在进行中"),
        (400, "bad_code", "代号不合规：not a code"),
    ],
)
async def test_version_route_maps_gate_errors(home, ws, monkeypatch, status, code, message):
    """409/400 原样透传：命令行的退出码与界面的提示都靠这一个 code。

    拆成三条参数化而不是一个循环：项目 id 带秒级时间戳，同一个秒里连建三个同名项目
    会撞 id 拿到 503，循环里那两句「本应测 code 映射」的断言就变成在测建单。
    """
    _stub_cut(monkeypatch, error=prodserver.ProdServerError(message, code, status))
    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        pid = await _create(client)
        resp = await client.post(f"/api/apps/ai-studio/projects/{pid}/prod-server/version")
        assert resp.status == status
        body = await resp.json()
        assert body["code"] == code
        # 那句中文原文也要原样到得了前端：换 token 失败之类的事，界面靠它说清是哪一条
        assert body["error"] == message


@pytest.mark.asyncio
async def test_version_route_unknown_project_is_404(home, ws, monkeypatch):
    _stub_cut(monkeypatch)
    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        resp = await client.post("/api/apps/ai-studio/projects/nope/prod-server/version")
        assert resp.status == 404
        assert (await resp.json())["code"] == "project_not_found"


@pytest.mark.asyncio
async def test_version_route_is_gated_with_the_app(home, ws, monkeypatch):
    """app 关掉时新路由和其他 prod-server 路由一样 403 —— ``_require_enabled`` 不许漏挂。"""
    _stub_cut(monkeypatch)
    async with TestClient(TestServer(_make_app(monkeypatch, enabled=False))) as client:
        resp = await client.post("/api/apps/ai-studio/projects/p1/prod-server/version")
        assert resp.status == 403
        assert (await resp.json())["code"] == "app_disabled"
