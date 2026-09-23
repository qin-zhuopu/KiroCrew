"""Tests for the T3 release executor: build → stop-old → start-new.

The chain runs behind :class:`deploy.Deployer`, so the log-order and
failure-path assertions stub it (a unit test never spawns a real child —
testing-conventions); the real ``ProcessDeployer`` stage is exercised
against ``platform_compat`` probes and killers that are monkeypatched, which
is exactly the seam the OS call lives behind (platform-compat: os.kill is
not a liveness probe on Windows).
"""

from __future__ import annotations

import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from kiro_crew.apps.builtins.ai_studio.backend import deploy, projects, publish, routes


@pytest.fixture()
def home(tmp_path, monkeypatch):
    h = tmp_path / "crew"
    h.mkdir()
    monkeypatch.setenv("KIROCREW_HOME", str(h))
    return h


@pytest.fixture()
def project(home):
    record = projects.create_project("CRM", "")
    project_dir = projects.projects_root() / record["id"]
    _git(project_dir, "init", "-q")
    _git(project_dir, "config", "user.email", "t@example.com")
    _git(project_dir, "config", "user.name", "t")
    return record


def _git(project_dir, *args):
    import subprocess

    subprocess.run(
        ["git", "-C", str(project_dir), *args],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )


def _head_hash(project_dir):
    import subprocess

    proc = subprocess.run(
        ["git", "-C", str(project_dir), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    return proc.stdout.strip()


def _commit_version(project_id, version, annotation):
    project_dir = projects.projects_root() / project_id
    (project_dir / "marker.txt").write_text(version, encoding="utf-8")
    _git(project_dir, "add", ".")
    _git(project_dir, "commit", "-q", "-m", f"version {version}")
    _git(project_dir, "tag", "-a", version, "-m", annotation)
    return _head_hash(project_dir)


class RecordingDeployer(deploy.Deployer):
    """A stub that records the stage order and can fail any stage."""

    def __init__(self, fail_stage: str | None = None) -> None:
        self.stages: list[str] = []
        self.fail_stage = fail_stage

    def build(self, project_dir, version, form, log):
        if self.fail_stage == "build":
            raise deploy.DeployError("构建命令退出码 1：no such file")
        self.stages.append("build")
        return project_dir / "publish" / "artifacts" / version

    def stop_old(self, project_dir, log):
        if self.fail_stage == "stop":
            raise deploy.DeployError("旧实例未退出")
        self.stages.append("stop")
        log("停止旧实例 v0")
        return {"version": "v0"}

    def start_new(self, project_dir, spec, log):
        if self.fail_stage == "start":
            raise deploy.DeployError("端口被占用")
        self.stages.append("start")
        log("新实例已启动：pid 4242，端口 8080")
        return deploy.InstanceHandle(
            pid=4242, start_time=None, port=8080, url=spec.url, version=spec.version
        )


@pytest.fixture()
def executor(project):
    def _make(fail_stage: str | None = None) -> RecordingDeployer:
        d = RecordingDeployer(fail_stage)
        return d

    return _make


# ---------------------------------------------------------------------------
# success chain: log order pins the §四 sequence
# ---------------------------------------------------------------------------


def test_success_chain_log_order(home, project, executor):
    pid = project["id"]
    job = publish.record_job(pid, version="v1", form="full", commit_hash="abc123")
    d = executor()

    result = publish._execute_job(projects.projects_root() / pid, job, operator="1001", deployer=d)

    assert result["status"] == "success"
    assert d.stages == ["build", "stop", "start"]
    lines = [ln.rsplit("] ", 1)[-1] for ln in publish.read_job_log(pid, job["id"]).splitlines()]
    assert lines[0].startswith("开始发布 v1")
    build_idx = lines.index("开始构建 v1")
    stop_idx = lines.index("停止旧实例 v0")
    assert "构建完成" in lines[build_idx + 1]
    start_idx = lines.index("新实例已启动：pid 4242，端口 8080")
    url_idx = lines.index(f"发布地址 {publish.publish_url(pid, 'v1', '1001')}（pid 4242）")
    assert lines[-1] == publish.LOG_DONE_MARKER
    assert build_idx < stop_idx < start_idx < url_idx < len(lines) - 1
    assert publish.get_job(pid, job["id"])["status"] == "success"
    # the release record (the outward fact) lands only after the chain ran
    record = publish.latest_release(pid)
    assert record is not None and record["url"] == publish.publish_url(pid, "v1", "1001")


def test_success_chain_records_the_instance_state(home, project):
    """The single-instance fact is durable state: instance.json carries the
    pinned identity the NEXT publish stops."""
    pid = project["id"]
    project_dir = projects.projects_root() / pid
    d = deploy.ProcessDeployer()
    d._write_instance(project_dir, deploy.InstanceHandle(4242, "123", 8080, "u", "v1"))

    state = d._read_instance(project_dir)
    assert state["pid"] == 4242 and state["startTime"] == "123"


# ---------------------------------------------------------------------------
# failure paths: a build failure never touches the old instance
# ---------------------------------------------------------------------------


def test_build_failure_keeps_the_old_instance_and_fails_the_job(home, project, executor):
    pid = project["id"]
    job = publish.record_job(pid, version="v1", form="full", commit_hash="abc123")
    d = executor(fail_stage="build")

    result = publish._execute_job(projects.projects_root() / pid, job, operator="1001", deployer=d)

    assert result["status"] == "failed"
    assert "构建失败" in result["reason"]
    assert d.stages == []  # stop/start never ran: the old instance still serves
    log = publish.read_job_log(pid, job["id"])
    assert publish.LOG_FAILED_MARKER in log
    assert "no such file" in log
    assert publish.LOG_DONE_MARKER not in log
    assert publish.get_job(pid, job["id"])["status"] == "failed"
    assert publish.latest_release(pid) is None  # a failed job produces nothing outward


def test_start_failure_after_stop_fails_the_job_without_a_record(home, project, executor):
    pid = project["id"]
    job = publish.record_job(pid, version="v1", form="full", commit_hash="abc123")
    d = executor(fail_stage="start")

    result = publish._execute_job(projects.projects_root() / pid, job, operator="1001", deployer=d)

    assert result["status"] == "failed"
    assert d.stages == ["build", "stop"]  # the chain got as far as the replacement
    log = publish.read_job_log(pid, job["id"])
    assert "启动失败" in log
    assert publish.LOG_DONE_MARKER not in log
    assert publish.latest_release(pid) is None


# ---------------------------------------------------------------------------
# ProcessDeployer.stop_old: the single-instance replacement semantics
# ---------------------------------------------------------------------------


def test_stop_old_kills_only_the_pinned_identity(home, project, monkeypatch):
    pid = project["id"]
    project_dir = projects.projects_root() / pid
    calls: list[tuple[str, tuple]] = []
    alive = {"pid": 5000}

    monkeypatch.setattr(
        deploy.platform_compat, "pid_exists", lambda p: alive["pid"] == p, raising=False
    )
    monkeypatch.setattr(
        deploy.platform_compat,
        "kill_process_tree_pinned",
        lambda p, t: calls.append(("pinned", (p, t))) or alive.__setitem__("pid", None),
        raising=False,
    )
    monkeypatch.setattr(
        deploy.platform_compat,
        "kill_process_tree",
        lambda p: calls.append(("plain", (p,))) or True,
        raising=False,
    )

    d = deploy.ProcessDeployer()
    d._write_instance(project_dir, deploy.InstanceHandle(5000, "start-token", 8080, "u", "v0"))
    stopped = d.stop_old(project_dir, lambda _m: None)

    assert stopped["pid"] == 5000
    assert calls == [("pinned", (5000, "start-token"))]  # pinned, never a bare kill
    assert d._instance_path(project_dir).exists() is False  # the slot is free


def test_stop_old_with_no_state_file_is_a_no_op(home, project):
    pid = project["id"]
    logs: list[str] = []
    stopped = deploy.ProcessDeployer().stop_old(projects.projects_root() / pid, logs.append)
    assert stopped is None
    assert logs == ["无正在运行的旧实例"]


def test_stop_old_with_recycled_pid_signature_declines(home, project, monkeypatch):
    """A pid that no longer exists (or whose identity changed) is already
    gone: no signal is sent and the slot is released."""
    pid = project["id"]
    project_dir = projects.projects_root() / pid
    monkeypatch.setattr(deploy.platform_compat, "pid_exists", lambda p: False, raising=False)

    def _boom(*args):
        raise AssertionError("must not signal a dead pid")

    monkeypatch.setattr(deploy.platform_compat, "kill_process_tree_pinned", _boom, raising=False)
    monkeypatch.setattr(deploy.platform_compat, "kill_process_tree", _boom, raising=False)

    d = deploy.ProcessDeployer()
    d._write_instance(project_dir, deploy.InstanceHandle(6000, "stale", 8080, "u", "v0"))
    assert d.stop_old(project_dir, lambda _m: None) is not None
    assert d._instance_path(project_dir).exists() is False


# ---------------------------------------------------------------------------
# the URL template (08 §〇), verbatim
# ---------------------------------------------------------------------------


def test_publish_url_matches_the_domain_template_verbatim(home, project):
    pid = project["id"]
    assert publish.publish_url(pid, "v1.2", "1001") == "v1.2-crm-1001.gb10.jereh-pe.cn"
    assert publish.URL_TEMPLATE == "{version}-{app}-{operator}.gb10.jereh-pe.cn"


def test_publish_url_operator_segment_is_dns_safe(home, project):
    pid = project["id"]
    assert publish.publish_url(pid, "v1", "zhang san/01") == "v1-crm-zhang-san-01.gb10.jereh-pe.cn"
    assert publish.publish_url(pid, "v1", "") == "v1-crm-dev.gb10.jereh-pe.cn"


# ---------------------------------------------------------------------------
# the HTTP layer hands the JWT ``sub`` to the executor (dev: no verify)
# ---------------------------------------------------------------------------


def _make_app(monkeypatch, enabled=True):
    monkeypatch.setattr(routes, "is_app_enabled", lambda _name: enabled)
    app = web.Application()
    routes.register_routes(app)
    return app


def _jwt(sub: str) -> str:
    import base64

    payload = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).decode().rstrip("=")
    return f"aaa.{payload}.bbb"  # signature ignored in dev, per owner 拍板


@pytest.mark.asyncio
async def test_route_publish_uses_the_jwt_sub_as_operator(home, monkeypatch, project):
    pid = project["id"]
    commit = _commit_version(pid, "v1", "完整版")
    captured: dict[str, str] = {}

    class _Capture(deploy.Deployer):
        def build(self, project_dir, version, form, log):
            return project_dir / "publish" / "artifacts" / version

        def stop_old(self, project_dir, log):
            return None

        def start_new(self, project_dir, spec, log):
            captured["url"] = spec.url
            return deploy.InstanceHandle(
                pid=1, start_time=None, port=8080, url=spec.url, version=spec.version
            )

    monkeypatch.setattr(publish, "_DEPLOYER", _Capture())

    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        resp = await client.post(
            "/api/apps/ai-studio/publish",
            json={"project": pid, "version": "v1", "commitHash": commit},
            headers={"Authorization": f"Bearer {_jwt('1001')}"},
        )
        assert resp.status == 201

    assert captured["url"] == "v1-crm-1001.gb10.jereh-pe.cn"


@pytest.mark.asyncio
async def test_route_publish_without_identity_falls_back_to_dev(home, monkeypatch, project):
    pid = project["id"]
    commit = _commit_version(pid, "v1", "完整版")
    captured: dict[str, str] = {}

    class _Capture(deploy.Deployer):
        def build(self, project_dir, version, form, log):
            return project_dir / "publish" / "artifacts" / version

        def stop_old(self, project_dir, log):
            return None

        def start_new(self, project_dir, spec, log):
            captured["url"] = spec.url
            return deploy.InstanceHandle(
                pid=1, start_time=None, port=8080, url=spec.url, version=spec.version
            )

    monkeypatch.setattr(publish, "_DEPLOYER", _Capture())

    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        resp = await client.post(
            "/api/apps/ai-studio/publish",
            json={"project": pid, "version": "v1", "commitHash": commit},
        )
        assert resp.status == 201

    assert captured["url"] == "v1-crm-dev.gb10.jereh-pe.cn"
