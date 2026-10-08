"""Tests for the AI Studio dev-server control (ACP-2060, RFC §9.6).

Nothing here may spawn a real child, bind a real port, or touch the real
gateway: the whole outer world sits behind the injected seams (``runner``,
``prober``, ``ports``, ``gateway``, ``installer``, ``sleep``), which is the same
reasoning that keeps :mod:`deploy`'s unit tests off real processes
(testing-conventions). The launch chain runs synchronously through
:meth:`DevServer._start_launch`, so no test waits on a thread, and
``platform_compat``'s process probes and killer are monkeypatched onto the world
the test is holding — the OS call lives behind that seam on purpose.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from kiro_crew.apps.builtins.ai_studio.backend import devserver, projects, routes

DOMAIN = "eqp-14409-dev.gb10.jereh-pe.cn"


@pytest.fixture()
def home(tmp_path, monkeypatch):
    h = tmp_path / "crew"
    h.mkdir()
    monkeypatch.setenv("KIROCREW_HOME", str(h))
    monkeypatch.setenv("KIROCREW_STAFF_ID", "14409")
    # the process-wide DevServer cache is a process global: a test that fills it
    # must not hand a live server to the next one
    monkeypatch.setattr(devserver, "_SERVERS", {})
    return h


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    """A workspace that already has node_modules (so no install), conf dir writable."""
    root = tmp_path / "ws"
    (root / "node_modules").mkdir(parents=True)
    monkeypatch.setenv("KIROCREW_STAFF_ID", "14409")
    monkeypatch.setenv("AI_STUDIO_GATEWAY_CONF_DIR", str(tmp_path / "confd"))
    monkeypatch.delenv("AI_STUDIO_DEV_DOMAIN_SUFFIX", raising=False)
    monkeypatch.delenv("AI_STUDIO_GATEWAY_UPSTREAM", raising=False)
    return root


# ---------------------------------------------------------------------------
# the fakes
# ---------------------------------------------------------------------------


class FakeGateway:
    """Records the conf it wrote; ``fail`` stands in for nginx rejecting it."""

    def __init__(self, fail: bool = False) -> None:
        self.written: dict[str, str] = {}
        self.reloads = 0
        self.fail = fail

    def write(self, path: Path, text: str) -> None:
        if self.fail:
            raise RuntimeError("nginx: configuration file /etc/nginx/nginx.conf test failed")
        self.written[str(path)] = text
        self.reloads += 1

    def remove(self, path: str) -> None:
        self.written.pop(str(path), None)
        self.reloads += 1


class FakePorts:
    def __init__(self, busy: tuple[int, ...] = (), fail_free: bool = False) -> None:
        self.busy = set(busy)
        self.fail_free = fail_free
        self.claimed: list[tuple[int, str]] = []
        self.released: list[int] = []

    def free(self, port: int) -> bool:
        if self.fail_free:
            raise RuntimeError("resreg db is locked")
        return port not in self.busy

    def claim(self, port: int, owner: str) -> None:
        self.claimed.append((port, owner))

    def release(self, port: int) -> None:
        self.released.append(port)


class World:
    """The seams plus the process table the kill path drives.

    ``monkeypatch`` comes in through the constructor because the process probes
    are process globals: raw assignment would leak them into the next test on
    another worker (flake class 4).
    """

    def __init__(
        self,
        monkeypatch,
        *,
        fail_at: str | None = None,
        codes: list[Any] | None = None,
        ports: FakePorts | None = None,
        gateway: FakeGateway | None = None,
    ) -> None:
        self.fail_at = fail_at
        self.spawned: list[dict[str, Any]] = []
        self.codes = codes if codes is not None else [200] * 60
        self.probes = 0
        self.alive: dict[int, bool] = {}
        self.signals: list[tuple[int, int]] = []
        self.sleeps: list[float] = []
        self.installs: list[Path] = []
        self.ports = ports if ports is not None else FakePorts()
        self.gateway = gateway if gateway is not None else FakeGateway()
        monkeypatch.setattr(
            devserver.platform_compat, "pid_exists", lambda p: bool(self.alive.get(p))
        )
        monkeypatch.setattr(devserver.platform_compat, "process_start_time", lambda p: "tok")
        monkeypatch.setattr(devserver.platform_compat, "kill_process_tree", self.kill)

    def runner(self, cmd: list[str], cwd: Path, env: dict, log_path: Path) -> int:
        if self.fail_at == "spawn" or (
            self.fail_at == "spawn_api" and any("@webapp-template/api" in c for c in cmd)
        ):
            raise RuntimeError(f"命令不存在：{cmd[0]}")
        pid = 4000 + len(self.spawned)
        self.spawned.append({"cmd": cmd, "env": env, "cwd": cwd, "log": log_path, "pid": pid})
        self.alive[pid] = True
        return pid

    def prober(self, url: str) -> int:
        code = self.codes[min(self.probes, len(self.codes) - 1)]
        self.probes += 1
        if isinstance(code, str):
            raise RuntimeError(code)
        return code

    def installer(self, ws: Path, env: dict, log_path: Path) -> int:
        self.installs.append(ws)
        return 1 if self.fail_at == "install" else 0

    def kill(self, pid: int, sig: int) -> bool:
        self.signals.append((pid, sig))
        self.alive[pid] = False
        return True

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def server(self, ws: Path, project: dict, **extra: Any) -> devserver.DevServer:
        class SyncServer(devserver.DevServer):
            """Run the launch chain inline: assertions need it finished, and a
            thread here would be a wall-clock race (flake class 2)."""

            def _start_launch(self, generation: int, domain: str) -> None:
                self._launch(generation, domain)

        return SyncServer(
            ws,
            project,
            runner=self.runner,
            prober=self.prober,
            ports=self.ports,
            gateway=self.gateway,
            installer=self.installer,
            sleep=self.sleep,
            **extra,
        )


def _project(**extra: Any) -> dict:
    return {"id": "p1", "code": "eqp", "name": "设备管理", **extra}


def _conf_path(tmp_root: Path) -> Path:
    return tmp_root / "confd" / "ais-eqp-14409.conf"


def _written_names(world: World) -> list[str]:
    return sorted(Path(k).name for k in world.gateway.written)


# ---------------------------------------------------------------------------
# 1. the domain rules (§9.6 域名规则), verbatim
# ---------------------------------------------------------------------------


def test_dev_domain_code_and_staff():
    assert devserver.dev_domain({"code": "eqp"}, "14409") == DOMAIN
    # no code → the project id is the label
    assert devserver.dev_domain({"id": "p261008-151745"}, "14409") == (
        "p261008-151745-14409-dev.gb10.jereh-pe.cn"
    )
    # an upper-case code is lower-cased, not rejected
    assert devserver.dev_domain({"code": "EQP"}, "14409") == DOMAIN
    # code wins over id
    assert devserver.dev_domain({"code": "eqp", "id": "p1"}, "14409") == DOMAIN


def test_dev_domain_rejects_bad_code():
    for bad in ("设备", "a", "-x", "x-", "e" * 41, "eq p", "eq_p"):
        with pytest.raises(devserver.DevServerError) as exc:
            devserver.dev_domain({"code": bad}, "14409")
        assert (exc.value.code, exc.value.status) == ("bad_code", 400), bad
        assert str(exc.value) == f"代号不合规：{bad}"
    # no code and no id is still a bad code, and the message names what it saw
    with pytest.raises(devserver.DevServerError) as exc:
        devserver.dev_domain({}, "14409")
    assert (exc.value.code, exc.value.status) == ("bad_code", 400)


def test_dev_domain_requires_staff_id():
    for missing in ("", None, "   "):
        with pytest.raises(devserver.DevServerError) as exc:
            devserver.dev_domain({"code": "eqp"}, missing)
        assert (exc.value.code, exc.value.status) == ("no_staff_id", 400)
        assert str(exc.value) == "没有工号：请设置 KIROCREW_STAFF_ID"
    # a staff id that is not [a-z0-9]+ is the same refusal — the segment goes
    # into a DNS name, so a space or a slash cannot be let through
    for bad in ("a b", "14409/01", "工号"):
        with pytest.raises(devserver.DevServerError) as exc:
            devserver.dev_domain({"code": "eqp"}, bad)
        assert (exc.value.code, exc.value.status) == ("no_staff_id", 400), bad


def test_dev_domain_suffix_is_configurable(monkeypatch):
    monkeypatch.setenv("AI_STUDIO_DEV_DOMAIN_SUFFIX", "-dev.example.test")
    assert devserver.dev_domain({"code": "eqp"}, "14409") == "eqp-14409-dev.example.test"


# ---------------------------------------------------------------------------
# 2. the nginx server block
# ---------------------------------------------------------------------------


def test_gateway_conf_is_a_complete_server_block():
    conf = devserver.gateway_conf(DOMAIN, 6801, "10.244.2.1")
    assert "server_name eqp-14409-dev.gb10.jereh-pe.cn;" in conf
    assert "proxy_pass http://10.244.2.1:6801;" in conf
    assert "Upgrade" in conf and 'Connection "upgrade"' in conf
    assert "listen 80;" in conf
    assert "proxy_set_header Host $host;" in conf
    assert "proxy_read_timeout 300s;" in conf


def test_gateway_env_reads(monkeypatch, tmp_path):
    monkeypatch.delenv("AI_STUDIO_GATEWAY_CONF_DIR", raising=False)
    monkeypatch.delenv("AI_STUDIO_GATEWAY_RELOAD_CMD", raising=False)
    monkeypatch.delenv("AI_STUDIO_GATEWAY_UPSTREAM", raising=False)
    assert devserver.gateway_upstream() == "10.244.2.1"
    assert devserver.gateway_conf_dir() == Path.home() / "docker" / "web-gateways" / "conf.d"
    assert devserver.gateway_reload_cmd() == [
        "docker",
        "exec",
        "web-gateways",
        "nginx",
        "-s",
        "reload",
    ]

    monkeypatch.setenv("AI_STUDIO_GATEWAY_CONF_DIR", str(tmp_path / "cd"))
    monkeypatch.setenv("AI_STUDIO_GATEWAY_RELOAD_CMD", "docker exec my-gw nginx -s reload")
    monkeypatch.setenv("AI_STUDIO_GATEWAY_UPSTREAM", "172.17.0.1")
    assert devserver.gateway_conf_dir() == tmp_path / "cd"
    assert devserver.gateway_reload_cmd() == ["docker", "exec", "my-gw", "nginx", "-s", "reload"]
    assert devserver.gateway_upstream() == "172.17.0.1"


# ---------------------------------------------------------------------------
# 3. the launch plan
# ---------------------------------------------------------------------------


def test_launch_plan_defaults(ws):
    plan = devserver.launch_plan(ws, 6801, 6800, DOMAIN)
    assert [p["name"] for p in plan] == ["启动后端", "启动前端"]
    api, web_ = plan
    assert api["cmd"] == ["pnpm", "--filter", "@webapp-template/api", "dev"]
    assert api["env"]["PORT"] == "6800"
    assert api["env"]["DWS_BIN_PATH"] == str(ws / "e2e" / "dws-mock" / "dws")
    assert web_["cmd"] == ["pnpm", "--filter", "@webapp-template/web", "dev"]
    assert web_["env"]["PORT"] == "6801"
    assert web_["env"]["VITE_PROXY_TARGET"] == "http://127.0.0.1:6800"
    assert web_["env"]["__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS"] == DOMAIN


def test_launch_plan_follows_workspace_json(ws):
    (ws / ".ai-studio").mkdir()
    (ws / ".ai-studio" / "workspace.json").write_text(
        json.dumps(
            {
                "dev": {
                    "web": {"cmd": "pnpm run dev -- --host", "portEnv": "PORT"},
                    "api": {"cmd": "node server.js", "portEnv": "PORT"},
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    plan = devserver.launch_plan(ws, 6801, 6800, DOMAIN)
    assert [p["cmd"] for p in plan] == [
        ["node", "server.js"],
        ["pnpm", "run", "dev", "--", "--host"],
    ]
    # the port env is still ours: the contract is that the plan carries the ports
    assert [p["env"]["PORT"] for p in plan] == ["6800", "6801"]


def test_launch_plan_ignores_broken_workspace_json(ws):
    (ws / ".ai-studio").mkdir()
    for broken in ("{not json", '{"dev": 3}', '{"dev": {"web": {"cmd": ""}}}'):
        (ws / ".ai-studio" / "workspace.json").write_text(broken, encoding="utf-8")
        plan = devserver.launch_plan(ws, 6801, 6800, DOMAIN)
        assert [p["cmd"][-1] for p in plan] == ["dev", "dev"], broken


# ---------------------------------------------------------------------------
# 4. the child environment
# ---------------------------------------------------------------------------


def test_child_env_strips_secrets_and_proxy(monkeypatch):
    for key in (
        "ANTHROPIC_API_KEY",
        "KIROCREW_HOME",
        "CLAUDE_CODE_SOMETHING",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
    ):
        monkeypatch.setenv(key, "secret")
    monkeypatch.setenv("PATH", "/usr/bin")
    env = devserver.child_env({"PORT": "6801"})
    for key in (
        "ANTHROPIC_API_KEY",
        "KIROCREW_HOME",
        "CLAUDE_CODE_SOMETHING",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
    ):
        assert key not in env, key
    assert env["PORT"] == "6801"
    assert env["PATH"] == "/usr/bin"


# ---------------------------------------------------------------------------
# 5. the success chain
# ---------------------------------------------------------------------------


def test_start_success(ws, monkeypatch):
    world = World(monkeypatch)
    server = world.server(ws, _project())

    view = server.start()
    assert view["state"] == "starting"
    assert view["url"] == f"https://{DOMAIN}/"
    assert view["failedStep"] is None

    status = server.status()
    assert status["state"] == "running"
    assert status["url"] == f"https://{DOMAIN}/"
    assert status["ports"] == {"web": 6801, "api": 6800}
    assert [c["env"]["PORT"] for c in world.spawned] == ["6800", "6801"]
    assert {c["cwd"] for c in world.spawned} == {ws}
    assert all(c["log"] == server.log_path for c in world.spawned)
    assert world.installs == []  # node_modules exists: no install step
    assert _written_names(world) == ["ais-eqp-14409.conf"]
    assert world.gateway.reloads == 1
    assert DOMAIN in world.gateway.written[str(_conf_path(ws.parent))]
    assert world.ports.claimed == [(6800, "ai-studio-p1"), (6801, "ai-studio-p1")]
    assert world.ports.released == []


def test_start_installs_when_node_modules_missing(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    root.mkdir()
    monkeypatch.setenv("KIROCREW_STAFF_ID", "14409")
    monkeypatch.setenv("AI_STUDIO_GATEWAY_CONF_DIR", str(tmp_path / "confd"))
    world = World(monkeypatch)
    server = world.server(root, _project())
    server.start()
    assert world.installs == [root]
    assert server.status()["state"] == "running"


def test_start_skips_port_already_claimed(ws, monkeypatch):
    world = World(monkeypatch, ports=FakePorts(busy=(6800,)))
    server = world.server(ws, _project())
    server.start()
    assert [p for p, _ in world.ports.claimed] == [6801, 6802]
    assert [c["env"]["PORT"] for c in world.spawned] == ["6801", "6802"]


# ---------------------------------------------------------------------------
# 6~8. failure paths roll back
# ---------------------------------------------------------------------------


def test_install_failure_marks_the_step(ws, monkeypatch):
    (ws / "node_modules").rmdir()  # the install step only runs without it
    world = World(monkeypatch, fail_at="install")
    server = world.server(ws, _project())
    server.start()
    status = server.status()
    assert status["state"] == "failed"
    assert status["failedStep"] == "装依赖"
    assert status["message"] == "装依赖失败：退出码 1，见开发服务器日志"
    assert world.spawned == []
    assert _written_names(world) == []


def test_backend_command_failure_releases_ports_and_writes_no_conf(ws, monkeypatch):
    world = World(monkeypatch, fail_at="spawn_api")
    server = world.server(ws, _project())

    server.start()

    status = server.status()
    assert status["state"] == "failed"
    assert status["failedStep"] == "启动后端"
    assert "命令不存在" in str(status["message"])
    assert world.ports.released == [6800, 6801]
    assert _written_names(world) == []
    assert world.gateway.reloads == 0
    assert world.signals == []  # nothing was up, so nothing to kill


def test_probe_timeout_kills_and_removes_conf(ws, monkeypatch):
    world = World(monkeypatch, codes=[502] * 60)
    server = world.server(ws, _project(), probe_timeout_s=4)

    server.start()

    status = server.status()
    assert status["state"] == "failed"
    assert status["failedStep"] == "检查网址"
    assert status["message"] == "检查网址失败：4 秒内网址没通"
    # two children, both SIGTERM-ed
    assert sorted({pid for pid, _ in world.signals}) == [4000, 4001]
    assert all(sig == devserver.platform_compat.SIGTERM for _, sig in world.signals)
    # the conf went in and came back out
    assert world.gateway.reloads == 2
    assert _written_names(world) == []
    assert world.ports.released == [6800, 6801]
    # the loop is bounded by rounds, not by a wall clock (class 2/5)
    assert world.sleeps == [2.0, 2.0]


def test_gateway_reload_failure_is_a_step_failure(ws, monkeypatch):
    world = World(monkeypatch, gateway=FakeGateway(fail=True))
    server = world.server(ws, _project())

    server.start()

    status = server.status()
    assert status["state"] == "failed"
    assert status["failedStep"] == "挂网址"
    assert "nginx" in str(status["message"])
    assert sorted({pid for pid, _ in world.signals}) == [4000, 4001]
    assert world.ports.released == [6800, 6801]


def test_port_registry_failure_is_a_step_failure(ws, monkeypatch):
    world = World(monkeypatch, ports=FakePorts(fail_free=True))
    server = world.server(ws, _project())

    server.start()

    status = server.status()
    assert status["state"] == "failed"
    assert status["failedStep"] == "申请端口"
    assert world.spawned == []


def test_no_free_port_in_the_range(ws, monkeypatch):
    busy = tuple(range(devserver.PORT_RANGE[0], devserver.PORT_RANGE[1] + 1))
    world = World(monkeypatch, ports=FakePorts(busy=busy))
    server = world.server(ws, _project())

    server.start()

    status = server.status()
    assert (status["failedStep"], status["ports"]) == ("申请端口", {"web": None, "api": None})


# ---------------------------------------------------------------------------
# 9~10. stop and the recomputed status
# ---------------------------------------------------------------------------


def test_stop_kills_drops_conf_and_releases_ports(ws, monkeypatch):
    world = World(monkeypatch)
    server = world.server(ws, _project())
    server.start()
    world.signals.clear()

    view = server.stop()

    assert view["state"] == "stopped"
    assert sorted({pid for pid, _ in world.signals}) == [4000, 4001]
    assert _written_names(world) == []
    assert world.ports.released == [6800, 6801]
    assert server.status()["state"] == "stopped"


def test_stop_when_not_running_is_409(ws, monkeypatch):
    world = World(monkeypatch)
    server = world.server(ws, _project())
    with pytest.raises(devserver.DevServerError) as exc:
        server.stop()
    assert (exc.value.code, exc.value.status) == ("not_running", 409)


def test_stop_clears_a_broken_but_live_server(ws, monkeypatch):
    """The 409 must not be the answer to a broken server — that is a leak.

    Residue as it was found on 2026-10-08: the gateway was restarted mid-launch,
    so no rollback ran, and the workspace was left holding two live processes, two
    claimed ports and a mounted conf — while the URL answered 403 (vite 5.4
    rejecting an unknown Host). That state reads ``stopped``, because ``stopped``
    only means "the URL is not 200", so a stop() that asked status() answered 409
    and nothing in the UI could ever kill it. The ports are the scarcest thing in
    the 6800~6999 range, so the answer has to be "cleaned", not "not running".
    """
    world = World(monkeypatch, codes=[403] * 60)
    server = world.server(ws, _project())
    for pid in (5001, 5002):
        world.alive[pid] = True
    server._write_state(
        state="stopped",
        url=f"https://{DOMAIN}/",
        domain=DOMAIN,
        procs=[
            {"name": "前端", "pid": 5001, "startTime": "tok"},
            {"name": "后端", "pid": 5002, "startTime": "tok"},
        ],
        pid=5001,
        ports={"web": 6801, "api": 6800},
    )
    conf = server.conf_path(DOMAIN)
    world.gateway.write(conf, "# mounted before the gateway died\n")

    assert server.status()["state"] == "stopped"  # the leak: broken, and unreadable as broken

    view = server.stop()

    assert view["state"] == "stopped"
    assert sorted({pid for pid, _ in world.signals}) == [5001, 5002]
    assert _written_names(world) == []
    assert world.ports.released == [6800, 6801]
    # the state file no longer points at pids we just killed, so a later 409 is honest
    assert server._read_state()["procs"] == []


def test_stop_releases_ports_when_the_processes_are_already_gone(ws, monkeypatch):
    """Ports and conf are their own resources: dead children do not cancel them.

    The rollback path releases what it claimed, but a gateway that died mid-launch
    leaves the claims behind with no thread to undo them — that is the residue the
    next start has to be able to clear with one click.
    """
    world = World(monkeypatch)
    server = world.server(ws, _project())
    server.start()
    for pid in list(world.alive):
        world.alive[pid] = False  # killed by hand, or the gateway died with them

    server.stop()

    assert world.ports.released == [6800, 6801]
    assert _written_names(world) == []


def test_start_twice_is_409(ws, monkeypatch):
    world = World(monkeypatch)
    server = world.server(ws, _project())
    server.start()
    with pytest.raises(devserver.DevServerError) as exc:
        server.start()
    assert (exc.value.code, exc.value.status) == ("already_running", 409)
    # the refusal spawned nothing: one backend + one frontend, not four
    assert len(world.spawned) == 2


def test_bad_domain_start_spawns_nothing(ws, monkeypatch):
    world = World(monkeypatch)
    server = world.server(ws, {"id": "p1", "code": "设备管理"})
    with pytest.raises(devserver.DevServerError) as exc:
        server.start()
    assert (exc.value.code, exc.value.status) == ("bad_code", 400)
    assert world.spawned == []
    assert world.ports.claimed == []


def test_bad_code_is_checked_before_the_running_check(ws, monkeypatch):
    # a running server with a since-broken code still answers 409: what it is
    # running is what it is running, and 400 would tell the UI to try again
    world = World(monkeypatch)
    server = world.server(ws, _project())
    server.start()
    server.project = {"id": "p1", "code": "设备"}
    with pytest.raises(devserver.DevServerError) as exc:
        server.start()
    assert exc.value.code == "already_running"


def test_status_running_with_dead_pid_is_not_running(ws, monkeypatch):
    world = World(monkeypatch)
    server = world.server(ws, _project())
    server.start()
    assert server.status()["state"] == "running"

    world.alive[4001] = False  # someone killed the frontend by hand

    assert server.status()["state"] == "stopped"


def test_status_stale_starting_file_is_stopped(ws, monkeypatch):
    """A state file that says starting with no thread behind it is a lie the
    gateway left behind: report stopped so the button is clickable again."""
    world = World(monkeypatch)
    server = world.server(ws, _project())
    server.state_path.parent.mkdir(parents=True, exist_ok=True)
    server.state_path.write_text(
        json.dumps({"state": "starting", "url": f"https://{DOMAIN}/"}), encoding="utf-8"
    )
    assert server.status()["state"] == "stopped"


def test_status_starting_while_launching(ws, monkeypatch):
    world = World(monkeypatch)
    server = world.server(ws, _project())
    server._write_state(state="starting", url=f"https://{DOMAIN}/", ports={})
    server._busy_gen = 1
    assert server.status()["state"] == "starting"


def test_status_failed_is_sticky_until_next_start(ws, monkeypatch):
    (ws / "node_modules").rmdir()  # the install step only runs without it
    world = World(monkeypatch, fail_at="install")
    server = world.server(ws, _project())
    server.start()
    assert server.status()["state"] == "failed"
    assert server.status()["failedStep"] == "装依赖"


def test_status_unknown_state_is_stopped(ws, monkeypatch):
    world = World(monkeypatch)
    server = world.server(ws, _project())
    server.state_path.parent.mkdir(parents=True, exist_ok=True)
    server.state_path.write_text('{"state": "whatever"}', encoding="utf-8")
    assert server.status()["state"] == "stopped"
    server.state_path.write_text("{not json", encoding="utf-8")
    assert server.status()["state"] == "stopped"


# ---------------------------------------------------------------------------
# log tail
# ---------------------------------------------------------------------------


def test_log_tail(ws, monkeypatch):
    world = World(monkeypatch)
    server = world.server(ws, _project())
    assert server.log_tail(5) == []  # no log yet is an empty list
    server.log_path.parent.mkdir(parents=True, exist_ok=True)
    server.log_path.write_text("\n".join(f"line {i}" for i in range(120)) + "\n", encoding="utf-8")
    assert len(server.log_tail(50)) == 50
    assert server.log_tail(50)[-1] == "line 119"
    assert server.log_tail(0) == server.log_tail(50)  # a junk ?lines= is the default
    assert server.log_tail(10**6) == server.log_tail(50)  # capped, not a whole-file read


# ---------------------------------------------------------------------------
# the real gateway object: file in, reload out (still no docker, still no nginx)
# ---------------------------------------------------------------------------


class FakeProc:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def test_nginx_gateway_writes_and_reloads(monkeypatch, tmp_path):
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        return FakeProc(0)

    monkeypatch.setattr(devserver.subprocess, "run", fake_run)
    monkeypatch.setenv("AI_STUDIO_GATEWAY_RELOAD_CMD", "docker exec web-gateways nginx -s reload")
    target = tmp_path / "ais-eqp-14409.conf"
    gw = devserver.NginxGateway()
    gw.write(target, "server {\n}\n")
    assert target.read_text(encoding="utf-8") == "server {\n}\n"
    assert calls == [["docker", "exec", "web-gateways", "nginx", "-s", "reload"]]
    gw.remove(target)
    assert not target.exists()
    assert len(calls) == 2
    gw.remove(target)  # already gone: silent, and no pointless reload
    assert len(calls) == 2


def test_nginx_gateway_reload_failure_raises(monkeypatch, tmp_path):
    def fake_run(argv, **kwargs):
        return FakeProc(1, stderr="nginx: [emerg] host not found")

    monkeypatch.setattr(devserver.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError) as exc:
        devserver.NginxGateway().write(tmp_path / "a.conf", "x")
    assert "host not found" in str(exc.value)


def test_resreg_free_checks_bind_first(monkeypatch):
    # no resreg on PATH: a bindable port is free, an unbindable one is not
    monkeypatch.setattr(devserver.shutil, "which", lambda _n: None)
    monkeypatch.setattr(devserver, "_port_bindable", lambda p: p == 6800)
    ports = devserver.ResregPorts("p1")
    assert ports.free(6800) is True
    assert ports.free(6801) is False
    # without the registry, claim/release are no-ops rather than errors
    ports.claim(6800, "ai-studio-p1")
    ports.release(6800)


def test_resreg_check_drives_free(monkeypatch):
    monkeypatch.setattr(devserver.shutil, "which", lambda _n: "/usr/bin/resreg")
    seen: list[list[str]] = []

    def fake_run(argv, **kwargs):
        seen.append(list(argv))
        return FakeProc(0 if argv[-1] == "6801" else 1)

    monkeypatch.setattr(devserver, "_port_bindable", lambda _p: True)
    monkeypatch.setattr(devserver.subprocess, "run", fake_run)
    ports = devserver.ResregPorts("p1")
    assert ports.free(6800) is False
    assert ports.free(6801) is True
    assert seen[0][:2] == ["resreg", "check"]


# ---------------------------------------------------------------------------
# 11. routes
# ---------------------------------------------------------------------------


def _make_app(monkeypatch, enabled=True):
    monkeypatch.setattr(routes, "is_app_enabled", lambda _name: enabled)
    app = web.Application()
    routes.register_routes(app)
    return app


def _point_workspace_at(project_id: str, ws: Path, code: str | None = "eqp") -> None:
    path = projects.projects_root() / project_id / "project.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["workspaceDir"] = str(ws)
    if code is not None:
        data["code"] = code
    path.write_text(json.dumps(data), encoding="utf-8")


async def _create(client, name: str = "equipment") -> str:
    resp = await client.post("/api/apps/ai-studio/projects", json={"name": name, "description": ""})
    assert resp.status == 201
    return (await resp.json())["project"]["id"]


def _stub_world(monkeypatch, world: World, ws: Path) -> None:
    """Route tests drive the same fakes: no real child behind an HTTP call."""
    real = devserver.DevServer

    class SyncServer(real):
        def _start_launch(self, generation: int, domain: str) -> None:
            self._launch(generation, domain)

    def _build(project, workspace):
        server = SyncServer(
            workspace,
            project,
            runner=world.runner,
            prober=world.prober,
            ports=world.ports,
            gateway=world.gateway,
            installer=world.installer,
            sleep=world.sleep,
        )
        devserver._SERVERS[f"{project.get('id')}\x00{workspace}"] = server
        return server

    monkeypatch.setattr(devserver, "dev_server_for", _build)


@pytest.mark.asyncio
async def test_route_get_status(home, ws, monkeypatch):
    world = World(monkeypatch)
    _stub_world(monkeypatch, world, ws)
    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        pid = await _create(client)
        _point_workspace_at(pid, ws)

        resp = await client.get(f"/api/apps/ai-studio/projects/{pid}/dev-server")
        assert resp.status == 200
        body = await resp.json()
        assert body["state"] == "stopped"
        assert body["ports"] == {"web": None, "api": None}

        resp = await client.get("/api/apps/ai-studio/projects/nope/dev-server")
        assert resp.status == 404
        assert (await resp.json())["code"] == "project_not_found"


@pytest.mark.asyncio
async def test_route_start_stop(home, ws, monkeypatch):
    world = World(monkeypatch)
    _stub_world(monkeypatch, world, ws)
    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        pid = await _create(client)
        _point_workspace_at(pid, ws)

        resp = await client.post(f"/api/apps/ai-studio/projects/{pid}/dev-server/start")
        assert resp.status == 202
        body = await resp.json()
        assert body["state"] == "starting"
        assert body["url"] == f"https://{DOMAIN}/"

        resp = await client.get(f"/api/apps/ai-studio/projects/{pid}/dev-server")
        assert (await resp.json())["state"] == "running"

        # a second click is 409 already_running, not a second set of processes
        resp = await client.post(f"/api/apps/ai-studio/projects/{pid}/dev-server/start")
        assert resp.status == 409
        assert (await resp.json())["code"] == "already_running"
        assert len(world.spawned) == 2

        resp = await client.post(f"/api/apps/ai-studio/projects/{pid}/dev-server/stop")
        assert resp.status == 200
        assert (await resp.json())["state"] == "stopped"

        resp = await client.post(f"/api/apps/ai-studio/projects/{pid}/dev-server/stop")
        assert resp.status == 409
        assert (await resp.json())["code"] == "not_running"


@pytest.mark.asyncio
async def test_route_start_bad_code_400(home, ws, monkeypatch):
    world = World(monkeypatch)
    _stub_world(monkeypatch, world, ws)
    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        pid = await _create(client)
        _point_workspace_at(pid, ws, code="设备管理")

        resp = await client.post(f"/api/apps/ai-studio/projects/{pid}/dev-server/start")
        assert resp.status == 400
        body = await resp.json()
        assert body["code"] == "bad_code"
        assert body["error"] == "代号不合规：设备管理"
        assert world.spawned == []


@pytest.mark.asyncio
async def test_route_start_no_staff_400(home, ws, monkeypatch):
    world = World(monkeypatch)
    _stub_world(monkeypatch, world, ws)
    monkeypatch.delenv("KIROCREW_STAFF_ID")
    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        pid = await _create(client)
        _point_workspace_at(pid, ws)

        resp = await client.post(f"/api/apps/ai-studio/projects/{pid}/dev-server/start")
        assert resp.status == 400
        assert (await resp.json())["code"] == "no_staff_id"
        assert world.spawned == []


@pytest.mark.asyncio
async def test_route_log(home, ws, monkeypatch):
    world = World(monkeypatch)
    _stub_world(monkeypatch, world, ws)
    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        pid = await _create(client)
        _point_workspace_at(pid, ws)

        resp = await client.get(f"/api/apps/ai-studio/projects/{pid}/dev-server/log")
        assert resp.status == 200
        assert (await resp.json())["lines"] == []

        (ws / ".ai-studio").mkdir(exist_ok=True)
        (ws / ".ai-studio" / "dev-server.log").write_text(
            "vite ready\nError: listen EADDRINUSE 6801\n", encoding="utf-8"
        )
        resp = await client.get(f"/api/apps/ai-studio/projects/{pid}/dev-server/log?lines=1")
        assert (await resp.json())["lines"] == ["Error: listen EADDRINUSE 6801"]
        resp = await client.get(f"/api/apps/ai-studio/projects/{pid}/dev-server/log?lines=junk")
        assert len((await resp.json())["lines"]) == 2


@pytest.mark.asyncio
async def test_route_disabled_403(home, monkeypatch):
    async with TestClient(TestServer(_make_app(monkeypatch, enabled=False))) as client:
        for path, verb in (
            ("/api/apps/ai-studio/projects/p/dev-server", "get"),
            ("/api/apps/ai-studio/projects/p/dev-server/start", "post"),
            ("/api/apps/ai-studio/projects/p/dev-server/stop", "post"),
            ("/api/apps/ai-studio/projects/p/dev-server/log", "get"),
        ):
            resp = await getattr(client, verb)(path)
            assert resp.status == 403, path
            assert (await resp.json())["code"] == "app_disabled", path


@pytest.mark.asyncio
async def test_dev_server_for_is_cached(home, ws, monkeypatch):
    # the cache is what makes a second poll see its own launch: a fresh object
    # per request would report `starting` as `stopped` and allow a second spawn
    project = _project()
    first = devserver.dev_server_for(project, ws)
    assert devserver.dev_server_for(project, ws) is first
    assert devserver.dev_server_for(project, ws.parent / "other") is not first
