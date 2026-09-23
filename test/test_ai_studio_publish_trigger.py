"""Tests for the ai-studio publish trigger (B2) and its job state machine.

Same posture as test_ai_studio_publish_records.py: the store runs on plain
sync file I/O under ``KIROCREW_HOME``, the route on a bare aiohttp app with
``is_app_enabled`` monkeypatched, and the project directory is a throwaway
git repo so version tags can carry form annotations. The minimal executor
completes synchronously, so every trigger lands in a terminal state — the
assertions here pin the idempotency, the 409 and the record-field semantics
that survive T3's real-executor takeover unchanged.
"""

from __future__ import annotations

import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from kiro_crew.apps.builtins.ai_studio.backend import deploy, projects, publish, routes


@pytest.fixture(autouse=True)
def stub_deployer(monkeypatch):
    """The executor's stage seam, stubbed: no test here may spawn a real
    child (testing-conventions). The T3 executor tests live in
    test_ai_studio_publish_executor.py; these tests pin the trigger
    semantics, which are indifferent to HOW the stages run."""

    class _Stub(deploy.Deployer):
        def build(self, project_dir, version, form, log):
            return project_dir / "publish" / "artifacts" / version

        def stop_old(self, project_dir, log):
            return None

        def start_new(self, project_dir, spec, log):
            return deploy.InstanceHandle(
                pid=4242, start_time=None, port=8080, url=spec.url, version=spec.version
            )

    monkeypatch.setattr(publish, "_DEPLOYER", _Stub())


@pytest.fixture()
def home(tmp_path, monkeypatch):
    h = tmp_path / "crew"
    h.mkdir()
    monkeypatch.setenv("KIROCREW_HOME", str(h))
    return h


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


@pytest.fixture()
def project(home):
    record = projects.create_project("CRM", "")
    project_dir = projects.projects_root() / record["id"]
    _git(project_dir, "init", "-q")
    _git(project_dir, "config", "user.email", "t@example.com")
    _git(project_dir, "config", "user.name", "t")
    return record


def _commit_version(project_id, version, annotation):
    """One tagged version: the dev commit + the form-carrying tag (owner
    拍板: hash = git commit + git tag)."""
    project_dir = projects.projects_root() / project_id
    (project_dir / "marker.txt").write_text(version, encoding="utf-8")
    _git(project_dir, "add", ".")
    _git(project_dir, "commit", "-q", "-m", f"version {version}")
    _git(project_dir, "tag", "-a", version, "-m", annotation)
    return _head_hash(project_dir)


def _write_task_md(project_id, task_id):
    project_dir = projects.projects_root() / project_id
    tasks_dir = project_dir / "tasks"
    tasks_dir.mkdir(exist_ok=True)
    (tasks_dir / f"{task_id}.md").write_text(f"# {task_id}\n", encoding="utf-8")


def _commit_requirements(project_id, content="# requirements\n"):
    """Commit the requirements doc so the project holds a frozen version."""
    projects.save_doc(project_id, "requirements.md", content)


# ---------------------------------------------------------------------------
# store-level trigger
# ---------------------------------------------------------------------------


def test_first_publish_creates_job_and_success_record(home, project):
    pid = project["id"]
    commit = _commit_version(pid, "v1", "完整版")
    _write_task_md(pid, "ACP-700")
    _write_task_md(pid, "ACP-701")
    _commit_requirements(pid)

    result = publish.trigger_publish(pid, "v1", commit)

    assert result["idempotent"] is False
    assert result["status"] == "success"
    assert result["commitHash"] == commit

    jobs = publish.list_jobs(pid)
    assert len(jobs) == 1 and jobs[0]["status"] == "success"
    assert result["deploymentId"] == jobs[0]["id"]

    record = publish.latest_release(pid)
    assert record is not None
    assert record["deploymentId"] == result["deploymentId"]
    assert record["commitHash"] == commit
    assert record["form"] == "full"
    assert record["jiraTaskIds"] == ["ACP-700", "ACP-701"]
    assert record["requirementVersion"]  # the frozen requirements stamp
    assert record["url"] == f"v1-crm-{publish.DEFAULT_OPERATOR}.gb10.jereh-pe.cn"


def test_same_hash_as_latest_is_idempotent(home, project):
    pid = project["id"]
    commit = _commit_version(pid, "v1", "完整版")
    first = publish.trigger_publish(pid, "v1", commit)

    again = publish.trigger_publish(pid, "v1", commit)

    # D2: no new deployment, no new record, no new job
    assert again["idempotent"] is True
    assert again["deploymentId"] == first["deploymentId"]
    assert len(publish.list_release_records(pid)) == 1
    assert len(publish.list_jobs(pid)) == 1


def test_older_published_hash_republishes(home, project):
    pid = project["id"]
    old = _commit_version(pid, "v1", "完整版")
    publish.trigger_publish(pid, "v1", old)
    new = _commit_version(pid, "v2", "完整版")
    publish.trigger_publish(pid, "v2", new)

    # D3: an older, previously published hash is a normal (rollback-style)
    # re-publish, not an idempotent hit
    rollback = publish.trigger_publish(pid, "v1", old)
    assert rollback["idempotent"] is False
    assert rollback["status"] == "success"
    assert len(publish.list_jobs(pid)) == 3
    assert publish.latest_release(pid)["commitHash"] == old


def test_never_published_hash_is_not_idempotent(home, project):
    pid = project["id"]
    v1 = _commit_version(pid, "v1", "完整版")
    publish.trigger_publish(pid, "v1", v1)
    v2 = _commit_version(pid, "v2", "完整版")

    result = publish.trigger_publish(pid, "v2", v2)

    assert result["idempotent"] is False
    assert len(publish.list_jobs(pid)) == 2


def test_rejected_form_refuses_the_trigger(home, project):
    pid = project["id"]
    commit = _commit_version(pid, "v1", "chore: no form annotation")
    with pytest.raises(publish.PublishError) as exc:
        publish.trigger_publish(pid, "v1", commit)
    assert exc.value.code == "form_rejected"
    assert exc.value.status == 400
    assert publish.list_jobs(pid) == []


def test_trigger_validates_inputs(home, project):
    for version, commit in (("../v1", "abc"), ("", "abc"), ("v1", ""), ("v1", "x" * 81)):
        with pytest.raises(publish.PublishError) as exc:
            publish.trigger_publish(project["id"], version, commit)
        assert exc.value.status == 400
    with pytest.raises(publish.PublishError) as exc:
        publish.trigger_publish("nope", "v1", "abc")
    assert exc.value.code == "project_not_found"


def test_failed_job_does_not_become_the_latest_release(home, project):
    pid = project["id"]
    v1 = _commit_version(pid, "v1", "完整版")
    publish.trigger_publish(pid, "v1", v1)

    # A job that ends failed (T3's real executor writes this state on a
    # build/port failure) produces no outward record: the latest success
    # hash stays v1, so a v1 re-trigger stays idempotent
    job = publish.record_job(pid, version="v1", form="full", commit_hash=v1)
    publish.update_job_status(pid, job["id"], "failed")
    assert publish.latest_release(pid)["commitHash"] == v1
    assert publish.trigger_publish(pid, "v1", v1)["idempotent"] is True


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------


def _make_app(monkeypatch, enabled=True):
    monkeypatch.setattr(routes, "is_app_enabled", lambda _name: enabled)
    app = web.Application()
    routes.register_routes(app)
    return app


@pytest.mark.asyncio
async def test_route_publish_idempotent_and_new(home, monkeypatch, project):
    pid = project["id"]
    commit = _commit_version(pid, "v1", "完整版")

    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        resp = await client.post(
            "/api/apps/ai-studio/publish",
            data=json.dumps({"project": pid, "version": "v1", "commitHash": commit}),
        )
        assert resp.status == 201
        first = await resp.json()
        assert first["idempotent"] is False
        assert first["deploymentId"]

        resp = await client.post(
            "/api/apps/ai-studio/publish",
            data=json.dumps({"project": pid, "version": "v1", "commitHash": commit}),
        )
        assert resp.status == 200
        again = await resp.json()
        assert again["idempotent"] is True
        assert again["deploymentId"] == first["deploymentId"]

        # B3 fields readable right after the trigger
        resp = await client.get(f"/api/apps/ai-studio/publish/records?project={pid}")
        records = (await resp.json())["records"]
        assert len(records) == 1
        assert records[0]["form"] == "full"
        assert records[0]["status"] == "success"
        assert records[0]["url"].endswith(".gb10.jereh-pe.cn")


@pytest.mark.asyncio
async def test_route_publish_errors(home, monkeypatch, project):
    pid = project["id"]
    commit = _commit_version(pid, "v1", "完整版")

    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        resp = await client.post(
            "/api/apps/ai-studio/publish",
            data=json.dumps({"project": "nope", "version": "v1", "commitHash": commit}),
        )
        assert resp.status == 404

        resp = await client.post(
            "/api/apps/ai-studio/publish",
            data=json.dumps({"project": pid, "version": "v1"}),
        )
        assert resp.status == 400
        assert (await resp.json())["code"] == "invalid_commit_hash"

    monkeypatch.setattr(routes, "is_app_enabled", lambda _name: False)
    async with TestClient(TestServer(_make_app(monkeypatch, enabled=False))) as client:
        resp = await client.post(
            "/api/apps/ai-studio/publish",
            data=json.dumps({"project": pid, "version": "v1", "commitHash": commit}),
        )
        assert resp.status == 403
        assert (await resp.json())["code"] == "app_disabled"


@pytest.mark.asyncio
async def test_route_publish_in_progress_conflicts(home, monkeypatch, project):
    """A same-hash job already running answers 409 (B2 并发), without a
    second running job appearing."""
    pid = project["id"]
    commit = _commit_version(pid, "v1", "完整版")
    running = publish.record_job(pid, version="v1", form="full", commit_hash=commit)

    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        resp = await client.post(
            "/api/apps/ai-studio/publish",
            data=json.dumps({"project": pid, "version": "v1", "commitHash": commit}),
        )
        assert resp.status == 409
        assert (await resp.json())["code"] == "publish_in_progress"

    assert [j["id"] for j in publish.list_jobs(pid)] == [running["id"]]

    # a DIFFERENT hash still publishes while v1 runs (the conflict keys on
    # the hash, not on "any job running")
    v2 = _commit_version(pid, "v2", "完整版")
    assert publish.trigger_publish(pid, "v2", v2)["idempotent"] is False
