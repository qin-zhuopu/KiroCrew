"""Tests for the AI Studio production-server deploy flow (ACP-2085-S5).

Nothing here spawns a real child, binds a real port, talks to the gateway, or
runs git: the whole outer world sits behind the injected seams (``runner``,
``prober``, ``ports``, ``gateway``, ``builder``, ``git``, ``recorder``), and
:meth:`ProdServer._start_deploy` is overridden to run the seven steps inline so
no test waits on a thread — the same discipline as
``test/test_ai_studio_devserver.py`` (testing-conventions).
``platform_compat``'s process probes are monkeypatched onto the world the test
holds, because they are process globals and raw assignment would leak them to
the next test on another worker.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from kiro_crew.apps.builtins.ai_studio.backend import (
    devserver,
    prodserver,
    projects,
    routes,
)

STABLE = "eqp-14409.gb10.jereh-pe.cn"
VERSIONED = "v1-eqp-14409.gb10.jereh-pe.cn"
HEAD = "a" * 40


@pytest.fixture()
def home(tmp_path, monkeypatch):
    h = tmp_path / "crew"
    h.mkdir()
    monkeypatch.setenv("KIROCREW_HOME", str(h))
    monkeypatch.setenv("KIROCREW_STAFF_ID", "14409")
    # the process-wide cache is a process global: a test that fills it must not
    # hand a live server to the next one
    monkeypatch.setattr(prodserver, "_SERVERS", {})
    return h


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    """A workspace plus a writable conf dir and no suffix/upstream overrides."""
    root = tmp_path / "ws"
    root.mkdir(parents=True)
    monkeypatch.setenv("KIROCREW_STAFF_ID", "14409")
    monkeypatch.setenv("AI_STUDIO_GATEWAY_CONF_DIR", str(tmp_path / "confd"))
    monkeypatch.delenv("AI_STUDIO_DEV_DOMAIN_SUFFIX", raising=False)
    monkeypatch.delenv("AI_STUDIO_GATEWAY_UPSTREAM", raising=False)
    return root


# ---------------------------------------------------------------------------
# the fakes
# ---------------------------------------------------------------------------


class Park:
    """Halts a background deploy inside the build step until the test lets go.

    Only one test needs a deploy that is genuinely still running: the one that
    clicks 部署 a second time. Determinism beats hoping the thread is slow.
    """

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.let_go = threading.Event()


class FakeGateway:
    """Writes the conf to the (temp) directory for real and records the text.

    ``remove`` must be a real unlink: ``stop()`` decides whether there is
    anything to clean by asking ``conf.exists()``, so a fake that only keeps a
    dict would report a deployed server as 「没在运行」 and 409 the stop button.
    ``fail`` stands in for nginx rejecting the config.
    """

    def __init__(self, fail: bool = False) -> None:
        self.written: dict[str, str] = {}
        self.ops: list[tuple[str, str]] = []
        self.reloads = 0
        self.fail = fail

    def write(self, path: Path, text: str) -> None:
        if self.fail:
            raise RuntimeError("nginx: configuration test failed")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        self.written[str(path)] = text
        self.ops.append(("write", str(path)))
        self.reloads += 1

    def remove(self, path) -> None:
        self.written.pop(str(path), None)
        self.ops.append(("remove", str(path)))
        self.reloads += 1
        try:
            Path(path).unlink()
        except FileNotFoundError:
            pass


class FakePorts:
    def __init__(self, busy: tuple[int, ...] = ()) -> None:
        self.busy = set(busy)
        self.claimed: list[tuple[int, str]] = []
        self.released: list[int] = []

    def free(self, port: int) -> bool:
        return port not in self.busy

    def claim(self, port: int, owner: str) -> None:
        self.claimed.append((port, owner))

    def release(self, port: int) -> None:
        self.released.append(port)


class World:
    """Every seam plus the process table the kill path drives.

    ``codes`` drives 「检查网址」: the first entry is the first probe. The
    deploy loop counts rounds (not wall clock), so ``[502, 200]`` means the
    second round passes deterministically.
    """

    def __init__(
        self,
        monkeypatch,
        *,
        codes: list[Any] | None = None,
        build_code: int = 0,
        build_tail: str = "built ok",
        git_code: int = 0,
        push_code: int | None = None,
        branch_push_code: int = 0,
        ports: FakePorts | None = None,
        gateway: FakeGateway | None = None,
        fail_release: bool = False,
        real_ledger: bool = False,
        head: str = HEAD,
    ) -> None:
        self.block: Park | None = None
        self.real_ledger = real_ledger
        # 工作区当前的提交。版本号沿用与否看它（ACP-2219），所以「换了代码再部署」
        # 那种用例改这个数 + 补一条对得上它的验收记录，而不是另造一套假 git
        self.head = head
        # inline = the seven steps run inside deploy(). Only the test that needs a
        # deploy still in flight clears it, and then parks it in the build step.
        self.inline = True
        self.servers: list[prodserver.ProdServer] = []
        # monotonic: a test that clears `spawned` between two deploys must not
        # hand the second one the first one's pids
        self._next_pid = 4000
        self.codes = codes if codes is not None else [200] * 60
        self.probes = 0
        self.spawned: list[dict[str, Any]] = []
        self.alive: dict[int, bool] = {}
        self.signals: list[tuple[int, int]] = []
        self.sleeps: list[float] = []
        self.builds: list[dict[str, Any]] = []
        self.build_code = build_code
        self.build_tail = build_tail
        self.git_calls: list[list[str]] = []
        self.git_code = git_code
        self.push_code = git_code if push_code is None else push_code
        # 推分支（ACP-2218）与推标签是两条 push，成败分开给：默认推分支成功，好让
        # 「推标签被拒」那几条老断言说的还是推标签那一件事
        self.branch_push_code = branch_push_code
        self.releases: list[dict[str, Any]] = []
        self.fail_release = fail_release
        self.ports = ports if ports is not None else FakePorts()
        self.gateway = gateway if gateway is not None else FakeGateway()
        monkeypatch.setattr(
            devserver.platform_compat, "pid_exists", lambda p: bool(self.alive.get(p))
        )
        monkeypatch.setattr(devserver.platform_compat, "process_start_time", lambda p: "tok")
        monkeypatch.setattr(devserver.platform_compat, "kill_process_tree", self.kill)

    # -- seams -----------------------------------------------------------

    def runner(self, cmd: list[str], cwd: Path, env: dict, log_path: Path) -> int:
        # a monotonic counter, not len(spawned): a test that clears the record
        # between two deploys must not hand the second one the first one's pids
        self._next_pid += 1
        pid = self._next_pid
        self.spawned.append(
            {"pid": pid, "cmd": list(cmd), "cwd": cwd, "env": dict(env), "log": log_path}
        )
        self.alive[pid] = True
        return pid

    def prober(self, url: str) -> int:
        index = min(self.probes, len(self.codes) - 1)
        self.probes += 1
        code = self.codes[index]
        if isinstance(code, Exception):
            raise code
        return int(code)

    def builder(self, cmd, cwd, env, log_path, timeout_s) -> tuple[int, str]:
        self.builds.append({"cmd": list(cmd), "cwd": cwd, "env": dict(env), "timeout_s": timeout_s})
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("ab") as handle:
            handle.write((" ".join(cmd) + "\n").encode("utf-8"))
        if self.block is not None:
            # park the deploy mid-build so a test can click again while it runs
            self.block.entered.set()
            self.block.let_go.wait(10)
        return self.build_code, self.build_tail

    def git(self, argv: list[str]) -> tuple[int, str]:
        self.git_calls.append(list(argv))
        if argv[:2] == ["rev-parse", "--abbrev-ref"]:
            # 推分支前要问一次「当前在哪个分支」（ACP-2218）。答 develop 而不是
            # 那 40 位 sha：断言里看得见分支名，才知道推的是分支不是标签
            return 0, "develop\n"
        if argv[0] == "rev-parse":
            return 0, self.head + "\n"
        if argv[0] == "push":
            if len(argv) > 2 and str(argv[2]).startswith("HEAD:"):
                return self.branch_push_code, "branch push rejected: read-only fork"
            return self.push_code, "push rejected: remote fork has no credentials"
        return self.git_code, "" if self.git_code == 0 else "tag already exists"

    def pushes(self, refspec_prefix: str = "") -> list[list[str]]:
        """所有 ``push origin …``，可按 refspec 前缀筛（分支推的是 ``HEAD:<分支>``）。"""
        return [
            call
            for call in self.git_calls
            if call[:2] == ["push", "origin"] and " ".join(call[2:]).startswith(refspec_prefix)
        ]

    def recorder(self, project_id: str, **kwargs: Any) -> dict:
        if self.fail_release:
            raise RuntimeError("release store is read-only")
        self.releases.append({"project_id": project_id, **kwargs})
        if self.real_ledger:
            # write through to the real store: a test that asserts the NEXT
            # version must be driven by the rows the PREVIOUS deploy actually
            # wrote, or it would pass with the counter wired to anything
            from kiro_crew.apps.builtins.ai_studio.backend import publish

            return publish.record_release(project_id, **kwargs)
        return {"version": kwargs.get("version")}

    def kill(self, pid: int, sig: int) -> None:
        self.signals.append((pid, sig))
        self.alive[pid] = False

    def git_verbs(self) -> list[str]:
        return [call[0] for call in self.git_calls]

    # -- the deploy under test -------------------------------------------

    def server_class(self):
        """A ProdServer subclass that may run the seven steps inline.

        Overriding ``_start_deploy`` is the only change: with ``inline`` set the
        steps finish before ``deploy()`` returns, so no test polls a thread. One
        test clears the flag to get a deploy that is genuinely still running.
        """
        world = self

        class SyncServer(prodserver.ProdServer):
            def _start_deploy(self, generation, label, domains, record, reuse_version) -> None:
                if world.inline:
                    self._deploy(generation, label, domains, record, reuse_version)
                else:
                    super()._start_deploy(generation, label, domains, record, reuse_version)

        return SyncServer

    def make(self, ws: Path, project: dict | None = None) -> prodserver.ProdServer:
        server = self.server_class()(
            ws,
            project if project is not None else {"id": "p1", "code": "eqp"},
            runner=self.runner,
            prober=self.prober,
            ports=self.ports,
            gateway=self.gateway,
            builder=self.builder,
            git=self.git,
            recorder=self.recorder,
            nap=self.sleeps.append,
        )
        self.servers.append(server)
        return server

    def release_parked(self, timeout: float = 10.0) -> None:
        """Let a parked deploy run out and wait for it.

        The parked thread writes into this test's temp home; leaving it alive
        past the fixture's teardown is a race with the directory going away.
        ``_busy_gen`` is the deploy thread's own「我在跑」flag (it clears it in a
        finally), so it is what 「finished」 means here.
        """
        if self.block is not None:
            self.block.let_go.set()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if all(server._busy_gen == 0 for server in self.servers):
                return
            time.sleep(0.01)
        raise AssertionError("parked deploy thread never finished")

    # -- acceptance record -----------------------------------------------

    def accept(self, ws: Path, *, result: str = "passed", **fields: Any) -> dict:
        """Write one acceptance record (the gate reads the newest by ``at``)."""
        record = {
            "id": fields.pop("id", "acc-1"),
            "result": result,
            "voided": fields.pop("voided", False),
            "commitHash": fields.pop("commitHash", HEAD),
            "requirementVersion": fields.pop("requirementVersion", "req-3"),
            "at": fields.pop("at", "2026-10-09T00:00:00Z"),
            **fields,
        }
        directory = ws / ".ai-studio" / "accept"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{record['id']}.json").write_text(
            json.dumps(record, ensure_ascii=False), encoding="utf-8"
        )
        return record


@pytest.fixture()
def traced(monkeypatch):
    """Record the step names written to the state file, then a 「发布」 marker.

    The seven-step order is the acceptance criterion, and the only place it is
    observable is the ``step`` field of the state file. Wrapping ``_step``
    captures it without touching the flow; the marker appended after
    ``deploy()`` returns lets a test assert the tag/push/recorder calls landed
    *after* 检查网址, not during it.
    """
    seen: list[str] = []
    original = prodserver.ProdServer._step

    def spy(self, generation, step):
        seen.append(step)
        return original(self, generation, step)

    monkeypatch.setattr(prodserver.ProdServer, "_step", spy)
    return seen


# ---------------------------------------------------------------------------
# 1. 域名
# ---------------------------------------------------------------------------


def test_prod_domains_pair():
    stable, versioned = prodserver.prod_domains({"code": "eqp"}, "14409", "v1")
    assert stable == STABLE
    assert versioned == VERSIONED
    # the stable URL is the versioned one minus its label: one suffix, two names
    assert stable in versioned


def test_prod_domains_rejects_bad_version():
    """A dot would split the DNS label in two, a space would break the conf line."""
    for bad in ("v1.0", "1", "v", "v1-beta", "v 1", "", "  ", "V1.0"):
        with pytest.raises(prodserver.ProdServerError) as exc:
            prodserver.prod_domains({"code": "eqp"}, "14409", bad)
        assert exc.value.code == "bad_version"
        assert exc.value.status == 400
    # case is normalised, not rejected: the version is machine-generated (v<N>)
    assert prodserver.prod_domains({"code": "eqp"}, "14409", "V2")[1] == "v2-" + STABLE


def test_prod_domains_rejects_bad_code():
    with pytest.raises(prodserver.ProdServerError) as exc:
        prodserver.prod_domains({"code": "eq p!"}, "14409", "v1")
    assert exc.value.code == "bad_code"
    assert exc.value.status == 400


def test_prod_domains_requires_staff_id():
    with pytest.raises(prodserver.ProdServerError) as exc:
        prodserver.prod_domains({"code": "eqp"}, "", "v1")
    assert exc.value.code == "no_staff_id"
    assert exc.value.status == 400


def test_prod_conf_stem_is_separate_from_dev():
    # deleting the dev conf must never reach the prod one of the same project
    assert prodserver.prod_conf_stem("eqp-14409") == "ais-prod-eqp-14409"
    assert prodserver.prod_conf_stem("eqp-14409") != devserver.conf_stem(
        "eqp-14409-dev.gb10.jereh-pe.cn"
    )


# ---------------------------------------------------------------------------
# 2. 网关 conf
# ---------------------------------------------------------------------------


def test_gateway_conf_two_has_both_names_and_ws_headers():
    text = prodserver.gateway_conf_two((STABLE, VERSIONED), 7001, "127.0.0.1")
    assert f"server_name {STABLE} {VERSIONED};" in text
    assert "proxy_pass http://127.0.0.1:7001;" in text
    assert "Upgrade $http_upgrade" in text
    assert 'Connection "upgrade"' in text


# ---------------------------------------------------------------------------
# 3. 验收闸门：三种不通过都是 409，且一个字节都不写
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["none", "failed", "voided", "new_commit"])
def test_deploy_gate_rejects_without_writing_state(ws, monkeypatch, kind):
    world = World(monkeypatch)
    if kind == "failed":
        world.accept(ws, result="failed")
    elif kind == "voided":
        world.accept(ws, voided=True)
    elif kind == "new_commit":
        world.accept(ws, commitHash="b" * 40)
    server = world.make(ws)

    with pytest.raises(prodserver.ProdServerError) as exc:
        server.deploy()
    assert exc.value.code == "not_accepted"
    assert exc.value.status == 409
    assert not server.state_path.exists(), "the gate must not write a state file"
    assert world.spawned == []
    assert world.builds == []
    assert world.ports.claimed == []


def test_deploy_gate_uses_the_newest_record(ws, monkeypatch):
    """``list_records`` is newest-first: a later failed run voids an earlier pass."""
    world = World(monkeypatch)
    world.accept(ws, id="acc-old", result="passed", at="2026-10-01T00:00:00Z")
    world.accept(ws, id="acc-new", result="failed", at="2026-10-08T00:00:00Z")
    with pytest.raises(prodserver.ProdServerError) as exc:
        world.make(ws).deploy()
    assert exc.value.code == "not_accepted"


# ---------------------------------------------------------------------------
# 4. 成功部署：七步顺序 + running + tag + 发布记录
# ---------------------------------------------------------------------------


def test_deploy_success_runs_seven_steps_in_order(ws, monkeypatch, traced):
    world = World(monkeypatch)
    world.accept(ws)
    server = world.make(ws)

    view = server.deploy()
    traced.append("发布")
    assert traced == list(prodserver.STEPS) + ["发布"]

    assert view["state"] == "running"
    assert view["url"] == f"https://{STABLE}/"
    assert view["versionUrl"] == f"https://{VERSIONED}/"
    assert view["version"] == "v1"
    assert view["commit"] == HEAD
    assert view["deployedAt"]
    assert view["failedStep"] is None
    assert view["message"] is None

    # three build commands, each capped, all logged to the workspace log
    assert [b["cmd"] for b in world.builds] == [list(c) for c in prodserver.DEFAULT_BUILD_CMDS]
    assert {b["cwd"] for b in world.builds} == {ws}
    assert {b["timeout_s"] for b in world.builds} == {900.0}

    # two children, api first, prod database, separate ports in the prod range
    assert len(world.spawned) == 2
    api, web_child = world.spawned
    assert api["cmd"] == ["pnpm", "start:api"]
    assert api["env"]["APP_DB_PATH"] == str(ws / ".ai-studio" / "prod" / "app.db")
    assert api["env"]["DWS_BIN_PATH"] == str(ws / "e2e" / "dws-mock" / "dws")
    assert web_child["cmd"][:2] == ["pnpm", "--filter"]
    assert web_child["env"]["VITE_PROXY_TARGET"] == f"http://127.0.0.1:{api['env']['PORT']}"
    assert api["env"]["PORT"] != web_child["env"]["PORT"]
    assert all(
        prodserver.PORT_RANGE[0] <= int(c["env"]["PORT"]) <= prodserver.PORT_RANGE[1]
        for c in world.spawned
    )

    # the conf carries both names and is keyed by the prod stem
    conf = server.conf_path("eqp-14409")
    assert str(conf) in world.gateway.written
    assert world.gateway.written[str(conf)].count("server_name") == 1
    assert STABLE in world.gateway.written[str(conf)]

    # tagged, and the release ledger got exactly one row pointing at the stable
    # URL. Indexed by verb, not position: the gate reads HEAD and _succeed reads
    # it again for the record, so the count of rev-parse calls is not the point.
    assert world.git_verbs().count("tag") == 1
    tag_index = world.git_verbs().index("tag")
    assert world.git_calls[tag_index][:3] == ["tag", "-a", "v1"]
    assert world.git_calls[tag_index + 1] == ["push", "origin", "v1"]
    # 两条 push：分支（ACP-2218，refspec 是 HEAD:<当前分支>）在前，标签在后。
    # 「先推分支再推标签」是这一单的全部原因 —— 只推标签的仓里 develop 一动不动。
    assert world.git_verbs().count("push") == 2
    branch_pushes = world.pushes("HEAD:")
    tag_pushes = [c for c in world.pushes() if c not in branch_pushes]
    assert branch_pushes == [["push", "origin", "HEAD:develop"]]
    assert tag_pushes == [["push", "origin", "v1"]]
    assert world.git_calls.index(branch_pushes[0]) < tag_index
    assert len(world.releases) == 1
    release = world.releases[0]
    assert release["project_id"] == "p1"
    assert release["url"] == f"https://{STABLE}/"
    assert release["form"] == "full"
    assert release["version"] == "v1"
    assert release["requirement_version"] == "req-3"
    assert release["deployment_id"] == server._read_state()["deploymentId"]

    # and the recomputed status agrees with what deploy() returned
    assert server.status()["state"] == "running"


def test_deploy_reads_custom_cmds_from_workspace(ws, monkeypatch):
    world = World(monkeypatch)
    world.accept(ws)
    studio = ws / ".ai-studio"
    studio.mkdir(parents=True, exist_ok=True)  # the acceptance record made it already
    (studio / "workspace.json").write_text(
        json.dumps(
            {
                "prod": {
                    "build": ["make build", "make assets"],
                    "api": {"cmd": "gunicorn app:app"},
                    "web": {"cmd": "node server.js"},
                }
            }
        ),
        encoding="utf-8",
    )
    server = world.make(ws)
    assert [c for c in prodserver.build_cmds(ws)] == [["make", "build"], ["make", "assets"]]
    server.deploy()
    assert [c["cmd"] for c in world.spawned] == [["gunicorn", "app:app"], ["node", "server.js"]]
    # ports are still injected through the dev portEnv convention
    assert all("PORT" in c["env"] for c in world.spawned)


# ---------------------------------------------------------------------------
# 5. 第二次部署：旧进程组被杀、旧 conf 删、版本 v2
# ---------------------------------------------------------------------------


def test_second_deploy_stops_the_old_one_and_bumps_version(home, ws, monkeypatch, traced):
    # a real project + the real release ledger (the recorder writes through): v2
    # must come from the v1 row the FIRST deploy actually wrote, not from a
    # counter the test nudged
    from kiro_crew.apps.builtins.ai_studio.backend import publish

    world = World(monkeypatch, real_ledger=True)
    project = projects.create_project("equipment", "", code="eqp")
    _point_workspace_at(project["id"], ws)
    world.accept(ws)
    server = world.make(ws, project)
    first = server.deploy()
    assert first["version"] == "v1"
    assert [r["version"] for r in publish.list_release_records(project["id"])] == ["v1"]
    old_pids = [c["pid"] for c in world.spawned]
    conf = str(server.conf_path("eqp-14409"))
    old_ports = devserver.stored_ports(server._read_state())
    ops_before = len(world.gateway.ops)
    assert old_ports and conf in world.gateway.written

    # 第二次部署前先换提交：同一份代码重复点部署不升版（ACP-2219，见
    # test_redeploying_the_same_head_keeps_the_version），这条要的是「代码变了才
    # 升版」，所以 HEAD 与新验收记录都得挪
    world.head = "b" * 40
    world.accept(ws, id="acc-2", at="2026-10-10T00:00:00Z", commitHash=world.head)

    world.spawned.clear()
    second = server.deploy()
    assert second["version"] == "v2"
    assert second["versionUrl"] == f"https://v2-{STABLE}/"
    assert [r["version"] for r in world.releases] == ["v1", "v2"]
    assert [r["version"] for r in publish.list_release_records(project["id"])] == ["v2", "v1"]
    assert all(r["url"] == f"https://{STABLE}/" for r in world.releases)

    # the old process groups were signalled, not just forgotten
    for pid in old_pids:
        assert (pid, devserver.platform_compat.SIGTERM) in world.signals
    # the old conf was removed before the new one was written: the gateway sees
    # remove-then-write, so a reload in between never serves a half-replaced site
    assert world.gateway.ops[ops_before] == ("remove", conf)
    assert world.gateway.ops.index(("remove", conf)) < len(world.gateway.ops) - 1
    assert world.gateway.written[conf].startswith("# AI Studio 正式服务器")
    assert f"v2-{STABLE}" in world.gateway.written[conf]
    # old ports released; the new deploy claimed its own pair
    assert world.ports.released == old_ports
    assert len(world.ports.claimed) == 4


def test_version_counts_the_release_ledger(ws, monkeypatch, home):
    """v<N> is not typed by a human: N = the release ledger's row count + 1.

    Driven through the real store (a project in the isolated home + real
    records), because the interesting property is the join to the ledger — a
    fake counter would pass with the counter wired to anything at all.
    """
    from kiro_crew.apps.builtins.ai_studio.backend import publish

    world = World(monkeypatch)
    project = projects.create_project("equipment", "", code="eqp")
    _point_workspace_at(project["id"], ws)
    world.accept(ws)
    server = world.make(ws, {"id": project["id"], "code": "eqp"})
    assert server.deploy()["version"] == "v1"  # empty ledger
    publish.record_release(
        project["id"],
        # 另一份代码的记录（不是 HEAD）：同提交的最新记录会被**沿用**版本号
        # （ACP-2219），这条测的是「新提交按台账条数 +1」，两件事别搅在一起
        version="v1",
        commit_hash="b" * 40,
        form="full",
        requirement_version="req-3",
        jira_task_ids=[],
        url=f"https://{STABLE}/",
        deployment_id="dep-test",
    )
    world.spawned.clear()
    assert server.deploy()["version"] == "v2"


def test_redeploying_the_same_head_keeps_the_version(home, ws, monkeypatch):
    """同一份代码重复点部署：沿用版本号、不打 tag、不新增记录，实例照常重启。

    实战（ACP-2219）：设备管理同一份代码连点 5 次，v3~v7 五个标签五条台账。用户点
    〔重新部署〕要的是重启，不是给同一份代码发一个新身份。台账用真的
    （``real_ledger``）：「没多记一条」只有对着真存储断言才算数，假计数器怎么接都过。
    """
    from kiro_crew.apps.builtins.ai_studio.backend import publish

    world = World(monkeypatch, real_ledger=True)
    project = projects.create_project("equipment", "", code="eqp")
    _point_workspace_at(project["id"], ws)
    world.accept(ws)
    server = world.make(ws, project)
    assert server.deploy()["version"] == "v1"
    old_pids = [c["pid"] for c in world.spawned]

    world.spawned.clear()
    second = server.deploy()
    assert second["state"] == "running"
    assert second["version"] == "v1"
    assert second["versionUrl"] == f"https://v1-{STABLE}/"
    assert second["commit"] == HEAD
    # 台账一条、tag 一个、标签推一次 —— 这一单的全部内容
    assert [r["version"] for r in publish.list_release_records(project["id"])] == ["v1"]
    assert [r["version"] for r in world.releases] == ["v1"]
    assert world.git_verbs().count("tag") == 1
    assert world.pushes("v1") == [["push", "origin", "v1"]]
    # 实例是真重启的：旧进程组被信号杀过，这次起的两个孩子 pid 全新
    for pid in old_pids:
        assert (pid, devserver.platform_compat.SIGTERM) in world.signals
    assert len(world.spawned) == 2
    assert {c["pid"] for c in world.spawned}.isdisjoint(old_pids)
    log = server.log_path.read_text(encoding="utf-8")
    assert "代码没变，沿用版本 v1" in log
    # 代码没变≠代码不推：上一次的推送可能因为没凭据失败过，这次照样补一次
    assert world.pushes("HEAD:") == [
        ["push", "origin", "HEAD:develop"],
        ["push", "origin", "HEAD:develop"],
    ]

    # 台账没长条数 → 换了代码是 v2 而不是 v3（否则「沿用」只是把升版往后推一格）
    world.head = "c" * 40
    world.accept(ws, id="acc-2", at="2026-10-10T00:00:00Z", commitHash=world.head)
    world.spawned.clear()
    assert server.deploy()["version"] == "v2"


def test_a_reused_version_must_still_be_a_tag_name(home, ws, monkeypatch):
    """台账是磁盘上的旧文件：里面一个 ``v1.0`` 不许把部署变成 400 起不来。

    沿用来的版本号照样要过 :func:`prod_domains` 那道 ``v<N>`` 校验（它同时是 DNS
    标签的守卫），照字面沿用坏值，用户拿到的是「版本号不合规：v1.0」—— 按钮一个
    都点不动，直到有人去手改台账。退回按条数 +1：部署照常跑，代价只是这一版升个号。
    """
    from kiro_crew.apps.builtins.ai_studio.backend import publish

    world = World(monkeypatch)
    project = projects.create_project("equipment", "", code="eqp")
    _point_workspace_at(project["id"], ws)
    publish.record_release(
        project["id"],
        version="v1.0",
        commit_hash=HEAD,
        form="full",
        requirement_version="req-3",
        jira_task_ids=[],
        url=f"https://{STABLE}/",
        deployment_id="dep-legacy",
    )
    server = world.make(ws, {"id": project["id"], "code": "eqp"})
    assert server._version_plan(HEAD) == ("v2", False)
    # 真跑一遍才算数：坏台账下按钮还能点，跑起来的是 v2
    world.accept(ws)
    assert server.deploy()["version"] == "v2"


# ---------------------------------------------------------------------------
# 6. 构建失败：不起进程、不挂网址
# ---------------------------------------------------------------------------


def test_build_failure_marks_the_step_and_spawns_nothing(ws, monkeypatch, traced):
    world = World(monkeypatch, build_code=2, build_tail="Module not found: './App'")
    world.accept(ws)
    server = world.make(ws)

    server.deploy()
    assert traced == list(prodserver.STEPS[:2])  # stopped dead at 构建
    view = server._read_state()  # status() probes the net for a failed row's URL
    assert view["state"] == "failed"
    assert view["failedStep"] == "构建"
    assert view["message"].startswith("构建失败：")
    assert "退出码 2" in view["message"]
    assert world.spawned == []
    assert world.gateway.written == {}
    assert world.ports.claimed == []
    assert world.git_calls == [["rev-parse", "HEAD"]]  # only the gate's HEAD read
    assert world.releases == []


# ---------------------------------------------------------------------------
# 7. 检查网址不通：回滚本次新起的东西，并写明旧实例已停
# ---------------------------------------------------------------------------


def test_probe_timeout_rolls_back_this_deploy(ws, monkeypatch, traced):
    world = World(monkeypatch, codes=[502] * 200)
    world.accept(ws)
    server = world.make(ws)

    server.deploy()
    assert traced == list(prodserver.STEPS)
    view = server._read_state()
    assert view["state"] == "failed"
    assert view["failedStep"] == "检查网址"
    # a first deploy never had an old instance, so the message must not claim one
    assert "旧实例已停" not in view["message"]

    # everything this deploy started is undone: children, conf, ports
    for child in world.spawned:
        assert world.alive[child["pid"]] is False
    assert world.gateway.written == {}
    assert world.ports.released == [p for p, _ in world.ports.claimed]
    assert world.releases == []
    assert world.git_calls == [["rev-parse", "HEAD"]]


def test_probe_timeout_after_a_live_deploy_says_the_old_one_is_gone(ws, monkeypatch):
    """The rollback only re-launches this deploy's children; the old instance is
    already dead by then, and a message that hides that sends the operator to
    look for a running site that stopped minutes ago."""
    world = World(monkeypatch)
    world.accept(ws)
    server = world.make(ws)
    server.deploy()

    world.codes = [502] * 200
    server.deploy()
    view = server._read_state()
    assert view["state"] == "failed"
    assert view["failedStep"] == "检查网址"
    assert view["message"].endswith("旧实例已停）")
    assert world.gateway.written == {}


def test_probe_rounds_are_bounded(ws, monkeypatch):
    """60 rounds of 2s — a wedged domain may not spin the thread forever."""
    world = World(monkeypatch, codes=[502] * 500)
    world.accept(ws)
    world.make(ws).deploy()
    assert world.probes == 60


def test_probe_success_checks_the_children_too(ws, monkeypatch):
    """200 but the children died: that is a failure, not a running server."""
    world = World(monkeypatch, codes=[200])
    world.accept(ws)
    real_runner = world.runner

    def runner(cmd, cwd, env, log_path) -> int:
        pid = real_runner(cmd, cwd, env, log_path)
        world.alive[pid] = False  # it exited straight away
        return pid

    server = world.make(ws)
    server._runner = runner
    server.deploy()
    view = server._read_state()
    assert view["failedStep"] == "检查网址"
    assert "进程已退出" in view["message"]


# ---------------------------------------------------------------------------
# 8. 打 tag / 推 tag / 记台账失败：部署照样算成功
# ---------------------------------------------------------------------------


def test_tag_push_failure_keeps_the_deploy_running(ws, monkeypatch):
    world = World(monkeypatch, push_code=1)
    world.accept(ws)
    server = world.make(ws)
    server.deploy()
    assert server.status()["state"] == "running"
    assert len(world.releases) == 1  # the ledger still got its row
    log = server.log_path.read_text(encoding="utf-8")
    assert "推 tag 失败" in log
    assert "no credentials" in log


def test_tag_creation_failure_still_deploys(ws, monkeypatch):
    world = World(monkeypatch, git_code=1)
    world.accept(ws)
    server = world.make(ws)
    server.deploy()
    assert server.status()["state"] == "running"
    assert "打 tag 失败" in server.log_path.read_text(encoding="utf-8")
    # a tag that could not be created must not be pushed
    assert world.git_verbs().count("tag") == 1
    # 只剩推分支那一条 push：标签没打成就不该推它，而分支推的是代码不是标签，
    # 打 tag 失败与它无关（ACP-2218）
    assert world.pushes() == [["push", "origin", "HEAD:develop"]]


def test_branch_push_failure_keeps_the_deploy_running(ws, monkeypatch):
    """推分支失败（远端只读、没凭据）：部署照样算成功，日志留原文。

    和推标签失败同一条取舍 —— 网址已经通了。这一条断言的是**不要因为推不上代码
    就把一套跑着的正式服务器报成失败**，那会引导人去点停止。
    """
    world = World(monkeypatch, branch_push_code=1)
    world.accept(ws)
    server = world.make(ws)
    server.deploy()
    assert server.status()["state"] == "running"
    log = server.log_path.read_text(encoding="utf-8")
    assert "推送 develop：失败" in log
    assert "read-only fork" in log
    # 分支没推成也不挡住打 tag：版本号是这一版的身份，与远端可达无关
    assert world.git_verbs().count("tag") == 1
    assert world.pushes("v1") == [["push", "origin", "v1"]]
    assert len(world.releases) == 1


def test_release_ledger_failure_keeps_the_deploy_running(ws, monkeypatch):
    world = World(monkeypatch, fail_release=True)
    world.accept(ws)
    server = world.make(ws)
    server.deploy()
    assert server.status()["state"] == "running"
    assert "发布记录没记上" in server.log_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 9. 停止
# ---------------------------------------------------------------------------


def test_stop_kills_conf_and_ports(ws, monkeypatch):
    world = World(monkeypatch)
    world.accept(ws)
    server = world.make(ws)
    server.deploy()
    pids = [c["pid"] for c in world.spawned]
    conf = str(server.conf_path("eqp-14409"))

    view = server.stop()
    assert view["state"] == "stopped"
    for pid in pids:
        assert (pid, devserver.platform_compat.SIGTERM) in world.signals
        assert world.alive[pid] is False
    assert conf not in world.gateway.written
    assert world.ports.released == [p for p, _ in world.ports.claimed]
    state = server._read_state()
    assert state["procs"] == [] and state["ports"] == {}


def test_stop_on_nothing_running_is_409(ws, monkeypatch):
    world = World(monkeypatch)
    with pytest.raises(prodserver.ProdServerError) as exc:
        world.make(ws).stop()
    assert exc.value.code == "not_running"
    assert exc.value.status == 409


def test_failed_deploy_leaves_nothing_to_stop(ws, monkeypatch):
    """A rolled-back deploy is genuinely stopped: its own children, conf and
    ports are gone, so 停止 has nothing left to clean and says 409 rather than
    pretending to have killed something already dead."""
    world = World(monkeypatch, build_code=1)
    world.accept(ws)
    server = world.make(ws)
    server.deploy()  # fails at 构建, nothing spawned
    with pytest.raises(prodserver.ProdServerError) as exc:
        server.stop()
    assert exc.value.code == "not_running"

    world2 = World(monkeypatch, codes=[502] * 200)
    world2.accept(ws)
    server2 = world2.make(ws)
    server2.deploy()  # fails at 检查网址 — the rollback takes its own mess back
    state = server2._read_state()
    assert state["procs"] == [] and state["ports"] == {}
    assert not server2.conf_path("eqp-14409").exists()
    with pytest.raises(prodserver.ProdServerError) as exc:
        server2.stop()
    assert exc.value.code == "not_running"


def test_stop_clears_a_leaked_row(ws, monkeypatch):
    """「网址没通」不等于「没在运行」：状态里记着的活进程 / 端口 / conf 清得掉。

    The scenario a gateway restart leaves behind: a `deploying` row nobody owns
    any more, its children still up, its conf still on disk. `status()` calls it
    stopped (the URL does not answer), so a stop that keyed on the state string
    would 409 and the leak would be unclearable from the UI.
    """
    world = World(monkeypatch)
    world.accept(ws)
    server = world.make(ws)
    server.deploy()
    world.servers.clear()  # the process that owned the deploy thread is gone
    conf = server.conf_path("eqp-14409")
    assert conf.exists()
    state = server._read_state()
    state.update({"state": "deploying", "step": "检查网址"})
    server.state_path.write_text(json.dumps(state), encoding="utf-8")
    # nobody owns the deploying row AND the URL no longer answers: stopped, not
    # 「正式运行中」 — a green dot on a dead site is worse than a grey one
    world.codes = [502]
    world.probes = 0
    assert server.status()["state"] == "stopped"

    pids = [one["pid"] for one in state["procs"]]
    assert server.stop()["state"] == "stopped"
    for pid in pids:
        assert (pid, devserver.platform_compat.SIGTERM) in world.signals
    assert not conf.exists()


def test_status_reports_stopped_when_the_children_died(ws, monkeypatch):
    world = World(monkeypatch)
    world.accept(ws)
    server = world.make(ws)
    server.deploy()
    for child in world.spawned:
        world.alive[child["pid"]] = False
    assert server.status()["state"] == "stopped"


def test_status_reports_stopped_when_the_url_stops_answering(ws, monkeypatch):
    world = World(monkeypatch)
    world.accept(ws)
    server = world.make(ws)
    server.deploy()
    world.codes = [502]
    assert server.status()["state"] == "stopped"


def test_state_file_is_replaced_never_written_in_place(ws, monkeypatch):
    """状态文件必须整份换掉（rename），不许原地写。

    部署线程每进一步写一次，界面每 2 秒读一次，两者不在一个线程。原地
    ``write_text`` 不是原子的：读到一半就是截断的 JSON，容错成 ``{}``，于是
    「部署好了」在界面上闪一下变「已停止」。写临时文件 + rename 才原子。
    """
    replaced: list[Any] = []
    real_replace = os.replace

    def spy(src, dst, *args, **kwargs):
        replaced.append((str(src), str(dst)))
        return real_replace(src, dst, *args, **kwargs)

    world = World(monkeypatch)
    world.accept(ws)
    server = world.make(ws)
    monkeypatch.setattr(prodserver.os, "replace", spy)
    server.deploy()
    # 每一步都换一次（部署状态 + 每步 + 成功），一次原地写都没有
    assert len(replaced) >= len(prodserver.STEPS)
    assert all(dst == str(server.state_path) for _, dst in replaced)
    assert all(not src.endswith("/prod-server.json") for src, _ in replaced)
    # 临时文件不许留在盘上：它是过程，不是产物
    assert list(server.state_path.parent.glob("*.tmp")) == []


def test_a_poller_never_reads_a_state_without_a_state(ws, monkeypatch):
    """部署全程，任何一次读状态文件都读得出「是什么状态」。

    上面那条钉住做法，这条钉住症状：截断的文件会被容错成 ``{}``，界面把它读成
    「已停止」。轮询线程一边跑一边读，出现一次读不出状态就是红。
    """
    world = World(monkeypatch)
    world.accept(ws)
    world.inline = False  # 真的并发：主线程轮询，子线程部署
    server = world.make(ws)
    done = threading.Event()
    blanks: list[Any] = []

    def poll() -> None:
        while not done.is_set():
            # 文件还不存在 = 部署没开始，不算；存在却读不出状态 = 读到了截断的一半
            if not server.state_path.exists():
                continue
            state = server._read_state().get("state")
            if state not in prodserver.STATES:
                blanks.append(state)
                return

    reader = threading.Thread(target=poll, daemon=True)
    reader.start()
    try:
        server.deploy()
        world.release_parked()
    finally:
        done.set()
        reader.join(10)
    assert blanks == []
    assert server.status()["state"] == "running"


def test_log_tail_returns_the_tail(ws, monkeypatch):
    world = World(monkeypatch)
    world.accept(ws)
    server = world.make(ws)
    server.deploy()
    lines = server.log_tail(3)
    assert len(lines) == 3
    assert server.log_tail(0)  # a silly request still gets the default, not nothing
    assert server.log_tail(80)


def test_launch_plan_ports_are_the_web_preview_port(ws, monkeypatch):
    plan = prodserver.launch_plan(Path("/ws"), 7001, 7000, (STABLE, VERSIONED))
    assert [e["name"] for e in plan] == ["启动后端", "启动前端"]
    api, web_entry = plan
    assert api["env"]["PORT"] == "7000"
    assert web_entry["env"]["PORT"] == "7001"
    assert STABLE in web_entry["env"]["__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS"]
    assert "--strictPort" in web_entry["cmd"]
    # 实战（2026-10-10）：`pnpm --filter X preview -- --port N` 里的 `--` 会被原样传给 vite，
    # vite 当成「参数到此为止」，于是 --port 被忽略、落到默认 4173，正式网址永远不通。
    assert "--" not in web_entry["cmd"]
    assert web_entry["cmd"][web_entry["cmd"].index("--port") + 1] == "7001"


# ---------------------------------------------------------------------------
# 10. 路由层
# ---------------------------------------------------------------------------


def _make_app(monkeypatch, enabled=True):
    monkeypatch.setattr(routes, "is_app_enabled", lambda _name: enabled)
    app = web.Application()
    routes.register_routes(app)
    return app


def _point_workspace_at(project_id: str, workspace: Path, code: str | None = "eqp") -> None:
    path = projects.projects_root() / project_id / "project.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["workspaceDir"] = str(workspace)
    if code is not None:
        data["code"] = code
    path.write_text(json.dumps(data), encoding="utf-8")


async def _create(client, name: str = "equipment") -> str:
    resp = await client.post("/api/apps/ai-studio/projects", json={"name": name, "description": ""})
    assert resp.status == 201
    return (await resp.json())["project"]["id"]


def _stub_world(monkeypatch, world: World, workspace: Path) -> None:
    """Route tests drive the same fakes: no real child behind an HTTP call.

    The cache is honoured, not bypassed. That is not plumbing: 「部署中」 lives on
    the object (``_busy_gen``), so a per-request instance would let a second
    click during a running deploy start a SECOND set of processes — which is the
    exact failure the real ``prod_server_for`` exists to prevent, and a fake that
    ignored it would test nothing about it.
    """

    def _build(project, workspace_):
        key = f"{project.get('id')}\x00{workspace_}"
        server = prodserver._SERVERS.get(key)
        if server is None:
            server = world.server_class()(
                workspace_,
                project,
                runner=world.runner,
                prober=world.prober,
                ports=world.ports,
                gateway=world.gateway,
                builder=world.builder,
                git=world.git,
                recorder=world.recorder,
                nap=world.sleeps.append,
            )
            world.servers.append(server)
            prodserver._SERVERS[key] = server
        else:
            server.project = project
        return server

    monkeypatch.setattr(prodserver, "prod_server_for", _build)


@pytest.mark.asyncio
async def test_prod_route_get_and_unknown_project(home, ws, monkeypatch):
    world = World(monkeypatch)
    _stub_world(monkeypatch, world, ws)
    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        pid = await _create(client)
        _point_workspace_at(pid, ws)

        resp = await client.get(f"/api/apps/ai-studio/projects/{pid}/prod-server")
        assert resp.status == 200
        body = await resp.json()
        assert body["state"] == "stopped"
        assert body["ports"] == {"web": None, "api": None}

        resp = await client.get("/api/apps/ai-studio/projects/nope/prod-server")
        assert resp.status == 404
        assert (await resp.json())["code"] == "project_not_found"


@pytest.mark.asyncio
async def test_prod_route_deploy_gate_is_409_then_202(home, ws, monkeypatch):
    world = World(monkeypatch)
    _stub_world(monkeypatch, world, ws)
    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        pid = await _create(client)
        _point_workspace_at(pid, ws)

        resp = await client.post(f"/api/apps/ai-studio/projects/{pid}/prod-server/deploy")
        assert resp.status == 409
        body = await resp.json()
        assert body["code"] == "not_accepted"
        assert "先通过验收" in body["error"]

        world.accept(ws)
        resp = await client.post(f"/api/apps/ai-studio/projects/{pid}/prod-server/deploy")
        assert resp.status == 202
        body = await resp.json()
        assert body["state"] == "running"
        assert body["url"] == f"https://{STABLE}/"
        assert body["version"] == "v1"

        # 重新部署 while it is up is allowed — 停旧实例 is step 3 of the flow, and
        # refusing here would make the panel's own 「重新部署」 button need a 先停止.
        # This one stays in flight (real background thread, parked mid-build).
        world.inline = False
        world.block = Park()
        request = asyncio.ensure_future(
            client.post(f"/api/apps/ai-studio/projects/{pid}/prod-server/deploy")
        )
        try:
            await asyncio.wait_for(asyncio.to_thread(world.block.entered.wait, 10), 10)
            resp = await asyncio.wait_for(request, 10)
            assert resp.status == 202
            body = await resp.json()
            assert body["state"] == "deploying"

            # a second click DURING a deploy is the refusal
            resp = await client.post(f"/api/apps/ai-studio/projects/{pid}/prod-server/deploy")
            assert resp.status == 409
            assert (await resp.json())["code"] == "already_deploying"
        finally:
            world.release_parked()


@pytest.mark.asyncio
async def test_prod_route_bad_code_is_400_not_409(home, ws, monkeypatch):
    """A project with no usable code is a 400: fixing the code is what unblocks it."""
    world = World(monkeypatch)
    _stub_world(monkeypatch, world, ws)
    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        pid = await _create(client)
        _point_workspace_at(pid, ws, code="not a code")
        world.accept(ws)  # acceptance is fine; the domain is what fails

        resp = await client.post(f"/api/apps/ai-studio/projects/{pid}/prod-server/deploy")
        assert resp.status == 400
        assert (await resp.json())["code"] == "bad_code"


@pytest.mark.asyncio
async def test_prod_route_stop_and_log(home, ws, monkeypatch):
    world = World(monkeypatch)
    _stub_world(monkeypatch, world, ws)
    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        pid = await _create(client)
        _point_workspace_at(pid, ws)

        resp = await client.post(f"/api/apps/ai-studio/projects/{pid}/prod-server/stop")
        assert resp.status == 409
        assert (await resp.json())["code"] == "not_running"

        world.accept(ws)
        await client.post(f"/api/apps/ai-studio/projects/{pid}/prod-server/deploy")
        resp = await client.get(f"/api/apps/ai-studio/projects/{pid}/prod-server/log?lines=3")
        assert resp.status == 200
        assert len((await resp.json())["lines"]) == 3

        resp = await client.post(f"/api/apps/ai-studio/projects/{pid}/prod-server/stop")
        assert resp.status == 200
        assert (await resp.json())["state"] == "stopped"


@pytest.mark.asyncio
async def test_prod_routes_are_gated_with_the_app(home, ws, monkeypatch):
    """``_require_enabled`` answers 403 app_disabled — the same refusal the dev
    server's four routes give, so a disabled app looks identical from outside."""
    async with TestClient(TestServer(_make_app(monkeypatch, enabled=False))) as client:
        for path, verb in (
            ("/api/apps/ai-studio/projects/p1/prod-server", "get"),
            ("/api/apps/ai-studio/projects/p1/prod-server/deploy", "post"),
            ("/api/apps/ai-studio/projects/p1/prod-server/stop", "post"),
            ("/api/apps/ai-studio/projects/p1/prod-server/log", "get"),
        ):
            resp = await getattr(client, verb)(path)
            assert resp.status == 403, path
            assert (await resp.json())["code"] == "app_disabled", path


# ---------------------------------------------------------------------------
# 11. 进程内缓存：轮询必须问到一个知道自己正在部署的对象
# ---------------------------------------------------------------------------


def test_prod_server_for_is_cached_per_project_and_workspace(tmp_path):
    prodserver._SERVERS.clear()
    try:
        one = prodserver.prod_server_for({"id": "p1"}, tmp_path)
        assert prodserver.prod_server_for({"id": "p1"}, tmp_path) is one
        assert prodserver.prod_server_for({"id": "p2"}, tmp_path) is not one
        assert prodserver.prod_server_for({"id": "p1"}, tmp_path / "other") is not one
    finally:
        prodserver._SERVERS.clear()
