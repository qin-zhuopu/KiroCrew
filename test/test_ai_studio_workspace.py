"""Tests for the AI Studio workspace derive (ACP-2085, RFC §9.1).

Nothing here may run ``jc``, reach the network, or start a real process: the
derive command, the retry push and the dev server all sit behind the injected
seams (``runner`` / ``pusher`` / ``devserver_factory``), and the two real
subprocess helpers are tested against a monkeypatched ``subprocess.run`` — the
same shape :mod:`test_ai_studio_devserver` uses for the gateway object. The job
runs synchronously in these tests; the thread belongs to the route layer, and a
test that waited on it would be a wall-clock race (testing-conventions class 2).
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from kiro_crew.apps.builtins.ai_studio.backend import (
    devserver,
    projects,
    routes,
    workspace,
)

OK_DATA = {"target": "/x/sbgl", "personalRepo": "https://bitbucket/jereh/sbgl.git"}


@pytest.fixture()
def home(tmp_path, monkeypatch):
    h = tmp_path / "crew"
    h.mkdir()
    monkeypatch.setenv("KIROCREW_HOME", str(h))
    monkeypatch.setenv("KIROCREW_STAFF_ID", "14409")
    monkeypatch.setenv("AI_STUDIO_WORKSPACES_ROOT", str(tmp_path / "workspaces"))
    monkeypatch.delenv("AI_STUDIO_WORKSPACE_CMD", raising=False)
    monkeypatch.delenv("AI_STUDIO_WORKSPACE_TEMPLATE", raising=False)
    # the process-wide job registry is a process global: a test that fills it
    # must not hand a running id to the next one
    monkeypatch.setattr(workspace, "_JOBS", set())
    return h


# ---------------------------------------------------------------------------
# the fakes
# ---------------------------------------------------------------------------


class FakeDerive:
    """The derive command as a stub: returns ``data`` or raises WorkspaceError."""

    def __init__(self, *, data: dict | None = None, fail: str | None = None) -> None:
        self.data = OK_DATA if data is None else data
        self.fail = fail
        self.calls: list[tuple[list[str], Path]] = []

    def __call__(self, cmd: list[str], log_path: Path) -> dict[str, Any]:
        self.calls.append((cmd, log_path))
        if self.fail is not None:
            raise workspace.WorkspaceError(self.fail, "derive_failed", 502)
        return dict(self.data)


class FakePush:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], log_path: Path) -> bool:
        self.calls.append(cmd)
        return self.ok


class FakeServer:
    """Stands in for :class:`devserver.DevServer` — records that start ran."""

    def __init__(self, ws: Path, project: dict, *, fail: str | None = None) -> None:
        self.ws = ws
        self.project = project
        self.fail = fail
        self.starts = 0

    def start(self) -> dict:
        self.starts += 1
        if self.fail is not None:
            raise devserver.DevServerError(self.fail, "no_staff_id", 400)
        return {"state": "starting"}


class FakeDevServers:
    def __init__(self, *, fail: str | None = None) -> None:
        self.fail = fail
        self.built: list[FakeServer] = []
        self.by_ws: dict[str, FakeServer] = {}

    def __call__(self, project: dict, ws: Path) -> FakeServer:
        server = FakeServer(ws, project, fail=self.fail)
        self.built.append(server)
        self.by_ws[str(ws)] = server
        return server


def _job(
    project_id: str,
    derive: FakeDerive | None = None,
    dev: FakeDevServers | None = None,
    push: FakePush | None = None,
) -> workspace.WorkspaceJob:
    return workspace.WorkspaceJob(
        project_id,
        runner=derive or FakeDerive(),
        pusher=push or FakePush(),
        devserver_factory=dev or FakeDevServers(),
    )


def _create(name: str = "设备管理", code: str = "sbgl", **extra: Any) -> dict:
    return projects.create_project(name, "设备点检", code, **extra)


def _record(project_id: str) -> dict:
    record = projects.get_project(project_id)
    assert record is not None
    return record


def _states(record: dict) -> list[tuple[str, str]]:
    return [(s["name"], s["state"]) for s in record["steps"]]


def _git_ws(tmp_path: Path) -> Path:
    """A workspace directory that looks like an already-cloned repo."""
    ws = tmp_path / "workspaces" / "sbgl"
    (ws / ".git").mkdir(parents=True)
    return ws


# ---------------------------------------------------------------------------
# 1. the 代号 rule
# ---------------------------------------------------------------------------


def test_check_code_accepts_lowercase_codes():
    for good in ("sbgl", "eqp", "a1b", "a-b", "a" * 24, "device-mgmt-2026"):
        assert workspace.check_code(good) == good


def test_check_code_rejects_everything_else():
    for bad in ("SBGL", "a", "a1", "ab", "1abc", "设备", "e" * 25, "-ab", "ab-", "", "a b", "a_b"):
        with pytest.raises(workspace.WorkspaceError) as exc:
            workspace.check_code(bad)
        assert (exc.value.code, exc.value.status) == ("bad_code", 400), bad
        assert str(exc.value) == f"代号不合规：{bad}"


def test_workspaces_root_default_and_override(monkeypatch, tmp_path):
    monkeypatch.delenv("AI_STUDIO_WORKSPACES_ROOT", raising=False)
    assert workspace.workspaces_root() == Path("/workspaces")
    monkeypatch.setenv("AI_STUDIO_WORKSPACES_ROOT", str(tmp_path / "ws"))
    assert workspace.workspaces_root() == tmp_path / "ws"


# ---------------------------------------------------------------------------
# 2. the derive command
# ---------------------------------------------------------------------------


def test_derive_cmd_default(monkeypatch):
    monkeypatch.delenv("AI_STUDIO_WORKSPACE_CMD", raising=False)
    cmd = workspace.derive_cmd("https://x/tpl.git", "sbgl", "14409", Path("/workspaces"))
    assert cmd == [
        "jc",
        "webapp",
        "init",
        "https://x/tpl.git",
        "--name",
        "sbgl",
        "--uid",
        "14409",
        "--base",
        "/workspaces",
        "--no-init-sessions",
        "--depth",
        "all",
    ]


def test_derive_cmd_env_override_substitutes_placeholders(monkeypatch):
    monkeypatch.setenv("AI_STUDIO_WORKSPACE_CMD", "sh -c 'echo {template} {code} {uid} {base}'")
    cmd = workspace.derive_cmd("https://x/tpl.git", "sbgl", "14409", Path("/w"))
    assert cmd[0] == "sh"
    assert cmd[-1] == "echo https://x/tpl.git sbgl 14409 /w"


def test_derive_cmd_substitutes_glued_placeholder(monkeypatch):
    monkeypatch.setenv("AI_STUDIO_WORKSPACE_CMD", "mytool --base={base} --id={code}")
    assert workspace.derive_cmd("t", "sbgl", "1", Path("/w")) == [
        "mytool",
        "--base=/w",
        "--id=sbgl",
    ]


def test_derive_cmd_env_empty_falls_back(monkeypatch):
    monkeypatch.setenv("AI_STUDIO_WORKSPACE_CMD", "   ")
    assert workspace.derive_cmd("t", "sbgl", "1", Path("/w"))[0] == "jc"


def test_child_env_strips_model_secrets(monkeypatch):
    for key in ("ANTHROPIC_API_KEY", "KIROCREW_HOME", "CLAUDE_CODE_X"):
        monkeypatch.setenv(key, "secret")
    monkeypatch.setenv("PATH", "/usr/bin")
    env = workspace.child_env({"A": "1"})
    for key in ("ANTHROPIC_API_KEY", "KIROCREW_HOME", "CLAUDE_CODE_X"):
        assert key not in env, key
    assert env["A"] == "1" and env["PATH"] == "/usr/bin"


# ---------------------------------------------------------------------------
# 3. run_derive: the real subprocess helper (patched, never a real child)
# ---------------------------------------------------------------------------


class FakeProc:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def test_run_derive_reads_last_envelope(tmp_path, monkeypatch):
    written: list[str] = []

    def fake_run(argv, **kwargs):
        written.append(" ".join(argv))
        assert kwargs["env"]["PATH"]  # secrets stripped, PATH kept
        return FakeProc(stdout="cloning…\n" + json.dumps({"success": True, "data": OK_DATA}) + "\n")

    monkeypatch.setattr(workspace.subprocess, "run", fake_run)
    log = tmp_path / "workspace.log"
    data = workspace.run_derive(["jc", "webapp", "init"], log)
    assert data == OK_DATA
    assert "cloning…" in log.read_text(encoding="utf-8")


def test_run_derive_failure_envelope(tmp_path, monkeypatch):
    monkeypatch.setattr(
        workspace.subprocess,
        "run",
        lambda argv, **kw: FakeProc(
            stdout=json.dumps({"success": False, "message": "create-repo: 401"})
        ),
    )
    with pytest.raises(workspace.WorkspaceError) as exc:
        workspace.run_derive(["jc"], tmp_path / "workspace.log")
    assert (exc.value.code, exc.value.status) == ("derive_failed", 502)
    assert str(exc.value) == "create-repo: 401"


def test_run_derive_missing_command(tmp_path, monkeypatch):
    def missing(argv, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", argv[0])

    monkeypatch.setattr(workspace.subprocess, "run", missing)
    log = tmp_path / "workspace.log"
    with pytest.raises(workspace.WorkspaceError) as exc:
        workspace.run_derive(["jc"], log)
    assert (exc.value.code, exc.value.status) == ("workspace_cmd_unavailable", 503)
    assert "jc" in log.read_text(encoding="utf-8")


def test_run_derive_timeout(tmp_path, monkeypatch):
    def timeout(argv, **kwargs):
        raise workspace.subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(workspace.subprocess, "run", timeout)
    with pytest.raises(workspace.WorkspaceError) as exc:
        workspace.run_derive(["jc"], tmp_path / "workspace.log")
    assert (exc.value.code, exc.value.status) == ("derive_timeout", 504)


def test_run_derive_no_envelope(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace.subprocess, "run", lambda argv, **kw: FakeProc(stdout="ok\n"))
    with pytest.raises(workspace.WorkspaceError) as exc:
        workspace.run_derive(["jc"], tmp_path / "workspace.log")
    assert exc.value.code == "derive_failed"


def test_run_push_reports_exit_code(tmp_path, monkeypatch):
    log = tmp_path / "workspace.log"
    monkeypatch.setattr(
        workspace.subprocess, "run", lambda argv, **kw: FakeProc(stderr="rejected", returncode=1)
    )
    assert workspace.run_push(["git", "push"], log) is False
    assert "rejected" in log.read_text(encoding="utf-8")
    monkeypatch.setattr(workspace.subprocess, "run", lambda argv, **kw: FakeProc(stdout="ok"))
    assert workspace.run_push(["git", "push"], log) is True


def test_run_push_unrunnable(tmp_path, monkeypatch):
    def missing(argv, **kwargs):
        raise OSError("no git on PATH")

    monkeypatch.setattr(workspace.subprocess, "run", missing)
    log = tmp_path / "workspace.log"
    assert workspace.run_push(["git", "push"], log) is False
    assert "no git on PATH" in log.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 4. the job: the success chain
# ---------------------------------------------------------------------------


def test_job_success(home, tmp_path):
    record = _create()
    assert record["id"] == "sbgl"
    derive, dev = FakeDerive(), FakeDevServers()
    _job("sbgl", derive, dev).run()

    got = _record("sbgl")
    assert got["status"] == "ready"
    assert _states(got) == [
        ("克隆模板", "done"),
        ("建个人仓", "done"),
        ("推送", "done"),
        ("启动开发服务器", "done"),
    ]
    assert got["workspaceDir"] == OK_DATA["target"]
    assert got["repoUrl"] == OK_DATA["personalRepo"]
    assert got["failedStep"] is None and got["message"] is None
    # the command got the root and the code, not the project id
    cmd = derive.calls[0][0]
    assert cmd[:3] == ["jc", "webapp", "init"]
    assert cmd[cmd.index("--name") + 1] == "sbgl"
    assert cmd[cmd.index("--uid") + 1] == "14409"
    assert cmd[cmd.index("--base") + 1] == str(tmp_path / "workspaces")
    # the log lives next to project.json, so a failed clone can still be read
    assert derive.calls[0][1] == projects.projects_root() / "sbgl" / "workspace.log"
    # the dev server was handed the workspace dir and the project (with its code,
    # which is what makes the domain <代号>-<工号>-dev.…)
    assert [s.starts for s in dev.built] == [1]
    assert dev.built[0].ws == Path(OK_DATA["target"])
    assert dev.built[0].project["code"] == "sbgl"


def test_job_start_step_only_calls_start(home, tmp_path):
    """「启动开发服务器」这一步 start 一返回就算 done，不等网址通。"""
    record = _create()
    assert record["status"] == "creating"
    dev = FakeDevServers()
    _job(record["id"], FakeDerive(), dev).run()
    assert _record(record["id"])["status"] == "ready"


# ---------------------------------------------------------------------------
# 5. the job: failure paths, verbatim messages
# ---------------------------------------------------------------------------


def test_job_failure_blames_the_named_step(home, tmp_path):
    _create()
    derive = FakeDerive(fail="create-repo: 401")
    dev = FakeDevServers()
    with pytest.raises(workspace.WorkspaceError):
        _job("sbgl", derive, dev).run()

    got = _record("sbgl")
    assert got["status"] == "failed"
    assert got["failedStep"] == "建个人仓"
    assert _states(got) == [
        ("克隆模板", "done"),
        ("建个人仓", "failed"),
        ("推送", "pending"),
        ("启动开发服务器", "pending"),
    ]
    # RFC §8 的原文格式，错误原文一字不改
    assert got["message"] == "建个人仓失败：create-repo: 401"
    step = next(s for s in got["steps"] if s["name"] == "建个人仓")
    assert step["message"] == "建个人仓失败：create-repo: 401"
    assert dev.built == []  # a failed derive never starts a server


def test_job_failure_blames_clone_on_the_word_clone(home):
    _create()
    with pytest.raises(workspace.WorkspaceError):
        _job("sbgl", FakeDerive(fail="fatal: clone of … failed")).run()
    got = _record("sbgl")
    assert got["failedStep"] == "克隆模板"
    assert got["message"] == "克隆模板失败：fatal: clone of … failed"


def test_job_failure_without_a_keyword_blames_push(home):
    _create()
    with pytest.raises(workspace.WorkspaceError):
        _job("sbgl", FakeDerive(fail="Permission denied (publickey)")).run()
    assert _record("sbgl")["failedStep"] == "推送"


def test_job_missing_command_is_recorded(home):
    """命令不存在（真 run_derive 会抛 503）：failed + 那句原因原文。"""
    _create()

    def missing(cmd, log_path):
        raise workspace.WorkspaceError("派生命令不存在：jc", "workspace_cmd_unavailable", 503)

    with pytest.raises(workspace.WorkspaceError) as exc:
        workspace.WorkspaceJob("sbgl", runner=missing, devserver_factory=FakeDevServers()).run()
    assert (exc.value.code, exc.value.status) == ("workspace_cmd_unavailable", 503)
    got = _record("sbgl")
    assert got["status"] == "failed"
    assert got["message"] == "克隆模板失败：派生命令不存在：jc"


def test_job_dev_server_refusal_is_a_step_failure(home, tmp_path):
    """建好了但起服务被拒（没工号）：第四步红，错误原文是 devserver 那句。"""
    ws = tmp_path / "workspaces" / "sbgl"
    ws.mkdir(parents=True)
    _create()
    dev = FakeDevServers(fail="没有工号：请设置 KIROCREW_STAFF_ID")
    with pytest.raises(devserver.DevServerError):
        _job("sbgl", FakeDerive(data={"target": str(ws), "personalRepo": "r"}), dev).run()
    got = _record("sbgl")
    assert (got["status"], got["failedStep"]) == ("failed", "启动开发服务器")
    assert got["message"] == "启动开发服务器失败：没有工号：请设置 KIROCREW_STAFF_ID"
    assert _states(got)[:3] == [("克隆模板", "done"), ("建个人仓", "done"), ("推送", "done")]


def test_job_crash_never_leaves_creating(home, monkeypatch):
    """工厂整个炸了：状态必须落 failed，不能留一个永远转圈的 creating。"""
    _create()

    def boom(project, ws):
        raise RuntimeError("disk gone")

    job = workspace.WorkspaceJob("sbgl", runner=FakeDerive(), devserver_factory=boom)
    with pytest.raises(RuntimeError):
        job.run()
    got = _record("sbgl")
    assert got["status"] == "failed"
    assert got["failedStep"] == "启动开发服务器"
    assert "disk gone" in str(got["message"])


# ---------------------------------------------------------------------------
# 6. retry
# ---------------------------------------------------------------------------


def _fail_the_derive(home, *, target: str | None = None) -> dict:
    _create()
    data = dict(OK_DATA)
    if target is not None:
        data["target"] = target
    with pytest.raises(workspace.WorkspaceError):
        _job("sbgl", FakeDerive(fail="create-repo: 401"), FakeDevServers()).run()
    if target is not None:
        projects.update_project("sbgl", workspaceDir=target)
    return _record("sbgl")


def test_retry_after_failure_pushes_not_clones(home, tmp_path):
    ws = _git_ws(tmp_path)
    _fail_the_derive(home, target=str(ws))
    assert _record("sbgl")["status"] == "failed"

    derive, push, dev = FakeDerive(), FakePush(), FakeDevServers()
    workspace.WorkspaceJob("sbgl", runner=derive, pusher=push, devserver_factory=dev).retry()

    assert derive.calls == []  # 不重新克隆
    assert len(push.calls) == 1 and push.calls[0][:2] == ["sh", "-c"]
    assert "push -u origin develop" in push.calls[0][2] and "--unshallow" in push.calls[0][2]
    got = _record("sbgl")
    assert got["status"] == "ready"
    assert [s["state"] for s in got["steps"]] == ["done", "done", "done", "done"]
    assert [s.starts for s in dev.built] == [1]


def test_retry_reruns_the_command_when_no_repo(home):
    """目录不是 Git 仓（上次克隆到一半）：整条命令重跑。"""
    _fail_the_derive(home)
    derive, push, dev = FakeDerive(), FakePush(), FakeDevServers()
    workspace.WorkspaceJob("sbgl", runner=derive, pusher=push, devserver_factory=dev).retry()
    assert len(derive.calls) == 1
    assert push.calls == []
    assert _record("sbgl")["status"] == "ready"


def test_retry_push_failure_stays_failed(home, tmp_path):
    ws = _git_ws(tmp_path)
    _fail_the_derive(home, target=str(ws))
    push = FakePush(ok=False)
    with pytest.raises(workspace.WorkspaceError):
        workspace.WorkspaceJob("sbgl", runner=FakeDerive(), pusher=push).retry()
    got = _record("sbgl")
    assert (got["status"], got["failedStep"]) == ("failed", "推送")
    assert got["message"].startswith("推送失败：")


def test_retry_when_not_failed_is_409(home):
    _create()
    with pytest.raises(workspace.WorkspaceError) as exc:
        workspace.WorkspaceJob("sbgl", runner=FakeDerive()).retry()
    assert (exc.value.code, exc.value.status) == ("not_failed", 409)
    # the refusal did not touch the record
    assert _record("sbgl")["status"] == "creating"


def test_retry_of_a_ready_project_is_409(home):
    _create()
    _job("sbgl").run()
    with pytest.raises(workspace.WorkspaceError) as exc:
        _job("sbgl").retry()
    assert exc.value.code == "not_failed"


# ---------------------------------------------------------------------------
# 7. the store: create with a code
# ---------------------------------------------------------------------------


def test_create_with_code_skips_seed_docs(home):
    record = _create()
    assert record["id"] == "sbgl"
    assert record["code"] == "sbgl"
    assert record["status"] == "creating"
    assert record["template"] == workspace.DEFAULT_TEMPLATE_URL
    assert [s["name"] for s in record["steps"]] == list(workspace.STEPS)
    assert [s["state"] for s in record["steps"]] == ["pending"] * 4
    project_dir = projects.projects_root() / "sbgl"
    assert not (project_dir / "docs").exists()  # 文档来自模板，不写种子
    assert list(project_dir.iterdir()) == [project_dir / "project.json"]


def test_create_with_code_honours_template(home):
    record = _create(template="https://x/other.git")
    assert record["template"] == "https://x/other.git"


def test_create_duplicate_code_is_409(home):
    _create()
    with pytest.raises(projects.ProjectError) as exc:
        projects.create_project("另一个", "", "sbgl")
    assert (exc.value.code, exc.value.status) == ("code_taken", 409)
    assert str(exc.value) == "代号已被占用"
    # the loser wrote no directory
    assert [p["id"] for p in projects.list_projects()] == ["sbgl"]


def test_create_rejects_bad_code(home):
    with pytest.raises(workspace.WorkspaceError) as exc:
        projects.create_project("n", "", "SBGL")
    assert (exc.value.code, exc.value.status) == ("bad_code", 400)
    assert projects.list_projects() == []


def test_create_without_code_is_unchanged(home):
    record = projects.create_project("商机雷达", "追踪商机")
    assert record["id"].startswith("p")  # 纯中文名 slug 为空，时间戳担起唯一性
    assert projects.create_project("CRM", "")["id"].startswith("crm-p")
    assert "code" not in record and "status" not in record and "steps" not in record
    assert [d["name"] for d in projects.list_docs(record["id"])] == [
        "requirements.md",
        "ui-spec.md",
        "workflow.md",
    ]


def test_update_project_merges_and_is_atomic(home):
    _create()
    got = projects.update_project("sbgl", status="ready", steps=[])
    assert got["status"] == "ready" and got["code"] == "sbgl"
    assert not list((projects.projects_root() / "sbgl").glob("*.tmp"))
    with pytest.raises(projects.ProjectError) as exc:
        projects.update_project("nope", status="ready")
    assert (exc.value.code, exc.value.status) == ("project_not_found", 404)


def test_workspace_log_tail(home):
    _create()
    assert workspace.log_tail("sbgl") == []
    workspace.log_path_for("sbgl").write_text(
        "\n".join(f"line {i}" for i in range(120)) + "\n", encoding="utf-8"
    )
    assert workspace.log_tail("sbgl", 5) == [f"line {i}" for i in range(115, 120)]
    # a junk ?lines= is the default, not a whole-file read
    assert len(workspace.log_tail("sbgl", 0)) == 80
    assert len(workspace.log_tail("sbgl", 10**6)) == 80


# ---------------------------------------------------------------------------
# 8. routes
# ---------------------------------------------------------------------------


def _make_app(monkeypatch, enabled=True):
    monkeypatch.setattr(routes, "is_app_enabled", lambda _name: enabled)
    app = web.Application()
    routes.register_routes(app)
    return app


def _stub_jobs(monkeypatch, *, record: dict | None = None) -> list[tuple[str, bool]]:
    """Replace the thread starter: an HTTP test must not spawn a derive thread.

    The route's contract is ``201 + status=creating`` and nothing about what the
    thread did, so the stub records what was asked to run (id, retry?) and — when
    given ``record`` — writes the end state the real job would have written, so a
    later GET in the same test reads a plausible record instead of the fresh one.
    """
    started: list[tuple[str, bool]] = []

    def _start(project_id: str, *, job=None, retry: bool = False) -> None:
        started.append((project_id, retry))
        if record is not None:
            projects.update_project(project_id, **record)

    monkeypatch.setattr(workspace, "start_job", _start)
    return started


@pytest.mark.asyncio
async def test_route_create_with_code_is_201_creating(home, monkeypatch):
    started = _stub_jobs(monkeypatch)
    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        resp = await client.post(
            "/api/apps/ai-studio/projects",
            json={"name": "设备管理", "description": "点检", "code": "sbgl"},
        )
        assert resp.status == 201
        project = (await resp.json())["project"]
        assert project["id"] == "sbgl"
        assert project["status"] == "creating"
        assert [s["state"] for s in project["steps"]] == ["pending"] * 4
        # the job was asked to run exactly once, not retried
        assert started == [("sbgl", False)]

        # the record carries the progress fields the dialog polls
        resp = await client.get("/api/apps/ai-studio/projects/sbgl")
        body = await resp.json()
        assert body["project"]["status"] == "creating"
        assert [s["name"] for s in body["project"]["steps"]] == list(workspace.STEPS)

        resp = await client.get("/api/apps/ai-studio/projects")
        listed = await resp.json()
        assert [p["id"] for p in listed["projects"]] == ["sbgl"]
        assert listed["projects"][0]["status"] == "creating"
        # the 工号 rides on the list read: the dialog shows it read-only (A2)
        assert listed["staffId"] == "14409"


@pytest.mark.asyncio
async def test_route_create_without_code_is_unchanged(home, monkeypatch):
    started = _stub_jobs(monkeypatch)
    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        resp = await client.post(
            "/api/apps/ai-studio/projects", json={"name": "a", "description": "b"}
        )
        assert resp.status == 201
        assert "status" not in (await resp.json())["project"]
        # no code, no derive thread — the plain project path
        assert started == []


@pytest.mark.asyncio
async def test_route_create_bad_code_400(home, monkeypatch):
    started = _stub_jobs(monkeypatch)
    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        resp = await client.post(
            "/api/apps/ai-studio/projects", json={"name": "a", "description": "", "code": "SBGL"}
        )
        assert resp.status == 400
        assert (await resp.json())["code"] == "bad_code"
        assert projects.list_projects() == []
        assert started == []


@pytest.mark.asyncio
async def test_route_create_duplicate_code_409(home, monkeypatch):
    _stub_jobs(monkeypatch)
    _create()
    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        resp = await client.post(
            "/api/apps/ai-studio/projects", json={"name": "b", "description": "", "code": "sbgl"}
        )
        assert resp.status == 409
        body = await resp.json()
        assert body["code"] == "code_taken"
        assert body["error"] == "代号已被占用"


@pytest.mark.asyncio
async def test_route_retry(home, monkeypatch):
    started = _stub_jobs(monkeypatch)
    _create()
    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        # creating is not failed: the dialog must not be able to retry it
        resp = await client.post("/api/apps/ai-studio/projects/sbgl/retry")
        assert resp.status == 409
        assert (await resp.json())["code"] == "not_failed"
        assert started == []

        projects.update_project("sbgl", status="failed", failedStep="建个人仓")
        resp = await client.post("/api/apps/ai-studio/projects/sbgl/retry")
        assert resp.status == 202
        assert started == [("sbgl", True)]

        resp = await client.post("/api/apps/ai-studio/projects/nope/retry")
        assert resp.status == 404


@pytest.mark.asyncio
async def test_route_workspace_log(home, monkeypatch):
    _stub_jobs(monkeypatch)
    _create()
    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        resp = await client.get("/api/apps/ai-studio/projects/sbgl/workspace-log")
        assert resp.status == 200
        assert (await resp.json())["lines"] == []

        workspace.log_path_for("sbgl").write_text(
            "Cloning into 'sbgl'…\nfatal: could not read Remote 'origin'\n", encoding="utf-8"
        )
        resp = await client.get("/api/apps/ai-studio/projects/sbgl/workspace-log?lines=1")
        assert (await resp.json())["lines"] == ["fatal: could not read Remote 'origin'"]
        resp = await client.get("/api/apps/ai-studio/projects/sbgl/workspace-log?lines=junk")
        assert len((await resp.json())["lines"]) == 2

        resp = await client.get("/api/apps/ai-studio/projects/nope/workspace-log")
        assert resp.status == 404


@pytest.mark.asyncio
async def test_route_start_job_reuses_one_thread(home):
    """The real starter is what dedupes: a double click must not clone twice.

    The job body blocks on an event so the second call lands while the first is
    still running — that is the window the guard exists for. No stdlib patching:
    `threading.Thread` is a process global and a stub on it leaks into whatever
    the same xdist worker runs next.
    """
    entered = threading.Event()
    release = threading.Event()
    ran: list[str] = []

    class Blocking(_NoopJob):
        def run(self) -> None:
            ran.append(self.project_id)
            entered.set()
            release.wait(5)

    workspace.start_job("sbgl", job=Blocking("sbgl"))
    assert entered.wait(5)
    workspace.start_job("sbgl", job=Blocking("sbgl"))
    assert ran == ["sbgl"]
    release.set()


class _NoopJob:
    def __init__(self, project_id: str) -> None:
        self.project_id = project_id

    def run(self) -> None:
        pass

    def retry(self) -> None:
        pass


def test_start_job_releases_the_id(home):
    """线程跑完要把 id 放回去，否则这个项目这辈子都再也重试不动了。"""
    entered = threading.Event()

    class Noting(_NoopJob):
        def run(self) -> None:
            assert workspace.job_running("sbgl")
            entered.set()

    workspace.start_job("sbgl", job=Noting("sbgl"))
    assert entered.wait(5)
    # the discard happens in the thread's finally, so give it a bounded moment
    deadline = time.monotonic() + 5
    while workspace.job_running("sbgl") and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not workspace.job_running("sbgl")



# ---- 实战-1 卡点（2026-10-09）：浅克隆推不到新建的空仓库 --------------------------


def test_default_derive_cmd_clones_full_history(monkeypatch):
    monkeypatch.delenv("AI_STUDIO_WORKSPACE_CMD", raising=False)
    cmd = workspace.derive_cmd("https://x/tpl.git", "sbgl", "14409", Path("/w"))
    assert cmd[-2:] == ["--depth", "all"]


def _git(*args, cwd=None):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def test_retry_push_unshallows_from_template_before_push(tmp_path):
    # 模板：两次提交；工作区：depth 1 浅克隆后 origin 换成一个空的裸仓库（= 新建的个人仓）
    tpl = tmp_path / "tpl"
    tpl.mkdir()
    _git("init", "-q", "-b", "master", cwd=tpl)
    for i in range(2):
        (tpl / f"f{i}.txt").write_text(str(i))
        _git("add", ".", cwd=tpl)
        _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", f"c{i}", cwd=tpl)
    personal = tmp_path / "personal.git"
    _git("init", "-q", "--bare", str(personal))
    personal_cfg = personal / "config"
    personal_cfg.write_text(personal_cfg.read_text() + "[receive]\n\tshallowUpdate = false\n")
    ws = tmp_path / "ws"
    _git("clone", "-q", "--depth", "1", f"file://{tpl}", str(ws))
    _git("remote", "set-url", "origin", str(personal), cwd=ws)
    _git("checkout", "-q", "-b", "develop", cwd=ws)

    plain = subprocess.run(workspace.push_cmd(ws), capture_output=True, text=True)
    assert plain.returncode != 0 and "shallow" in (plain.stderr + plain.stdout)

    fixed = subprocess.run(workspace.push_cmd(ws, f"file://{tpl}"), capture_output=True, text=True)
    assert fixed.returncode == 0, fixed.stderr
    log = subprocess.run(["git", "--git-dir", str(personal), "log", "--oneline", "develop"], capture_output=True, text=True)
    assert len(log.stdout.strip().splitlines()) == 2



def test_repo_url_read_from_real_jc_envelope_shape(home):
    # 真 jc webapp init 的 personalRepo 是对象，不是字符串（实战实测，之前 repoUrl 一直是空）
    data = {"target": "/x/sbgl", "personalRepo": {"project": "~14409", "name": "sbgl", "url": "https://h/scm/~14409/sbgl.git", "status": "created"}}
    _create()
    workspace.WorkspaceJob("sbgl", runner=FakeDerive(data=data), pusher=FakePush(), devserver_factory=FakeDevServers()).run()
    assert _record("sbgl")["repoUrl"] == "https://h/scm/~14409/sbgl.git"



def test_template_pages_are_baseline_and_skipped_when_dev_names_no_pages(tmp_path, monkeypatch):
    # 实战：不点名拆出了模板全部 21 页；复制时已有的页是做好的，只开发新页
    from kiro_crew.apps.builtins.ai_studio.backend import requirements, routes

    req = tmp_path / "docs" / "需求图谱"
    req.mkdir(parents=True)
    (req / "报价单.json").write_text("{}")
    workspace.write_baseline_pages(tmp_path)
    (req / "设备清单.json").write_text("{}")
    workspace.write_baseline_pages(tmp_path)  # 已有记录不覆盖
    assert routes.baseline_pages(tmp_path) == {"报价单"}

    monkeypatch.setattr(requirements, "list_pages", lambda ws: [
        {"page": "报价单", "verdict": "全齐"}, {"page": "设备清单", "verdict": "全齐"}])
    assert routes._resolve_dev_pages(tmp_path, None) == ["设备清单"]
    assert routes._resolve_dev_pages(tmp_path, ["报价单"]) == ["报价单"]  # 点名照做
