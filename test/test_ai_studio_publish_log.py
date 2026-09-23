"""Tests for the ai-studio release-job log endpoint (T4, §〇-2 后台日志流).

The log source is an append-only ``<jobId>.log`` beside the job json, so the
stream is durable file state (T3's executor swap keeps the collection). The
route speaks SSE in both cases: a running job's frames grow with the file
until the job leaves ``running``, a finished job replays the whole log in one
final frame and closes. Same posture as test_ai_studio_publish_trigger.py:
bare aiohttp app, ``is_app_enabled`` monkeypatched, ``KIROCREW_HOME`` at
tmp_path.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from kiro_crew.apps.builtins.ai_studio.backend import deploy, projects, publish, routes


@pytest.fixture(autouse=True)
def stub_deployer(monkeypatch):
    """No real child in these tests either: the T3 executor tests live in
    test_ai_studio_publish_executor.py."""

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


@pytest.fixture()
def project(home):
    return projects.create_project("CRM", "")


def _make_app(monkeypatch, enabled=True):
    monkeypatch.setattr(routes, "is_app_enabled", lambda _name: enabled)
    app = web.Application()
    routes.register_routes(app)
    return app


def _sse_frames(raw: bytes) -> list[dict]:
    """Parse the ``data:`` frames of one SSE response body."""
    out = []
    for chunk in raw.decode("utf-8").split("\n\n"):
        chunk = chunk.strip()
        if chunk.startswith("data: "):
            out.append(json.loads(chunk[len("data: ") :]))
    return out


def _collect_frames(resp) -> asyncio.Queue:
    """Read the open SSE body frame by frame into a queue (the running-job
    tests sample mid-stream instead of draining to EOF)."""
    queue: asyncio.Queue = asyncio.Queue()

    async def _reader() -> None:
        try:
            async for line in resp.content:
                text = line.decode("utf-8").strip()
                if text.startswith("data: "):
                    await queue.put(json.loads(text[len("data: ") :]))
        except (ConnectionResetError, asyncio.CancelledError):
            pass

    asyncio.get_running_loop().create_task(_reader())
    return queue


# ---------------------------------------------------------------------------
# store: the log lives beside the job, written by the executor
# ---------------------------------------------------------------------------


def test_executor_writes_the_job_log(home, project):
    pid = project["id"]
    job = publish.record_job(pid, version="v1", form="full", commit_hash="abc123")

    publish._execute_job(projects.projects_root() / pid, job, operator="dev")

    log = publish.read_job_log(pid, job["id"])
    assert "v1" in log
    assert "abc123" in log
    assert publish.LOG_DONE_MARKER in log


def test_failed_executor_writes_the_failed_marker(home, project, monkeypatch):
    pid = project["id"]
    job = publish.record_job(pid, version="v1", form="full", commit_hash="abc123")

    # _project_dir inside the executor's store calls still resolve, so the
    # failure is forced at the record write: an unwritable job id is not
    # reachable, so monkeypatch record_release instead.
    def _boom(*args, **kwargs):
        raise publish.PublishError("disk full", "store_write_failed", 503)

    monkeypatch.setattr(publish, "record_release", _boom)

    result = publish._execute_job(projects.projects_root() / pid, job, operator="dev")

    assert result["status"] == "failed"
    assert "disk full" in result["reason"]
    assert publish.LOG_FAILED_MARKER in publish.read_job_log(pid, job["id"])
    assert publish.get_job(pid, job["id"])["status"] == "failed"


def test_job_log_snapshot_rejects_unknown_id(home, project):
    with pytest.raises(publish.PublishError) as exc:
        publish.job_log_snapshot(project["id"], "job-nope")
    assert exc.value.code == "job_not_found"
    assert exc.value.status == 404


def test_job_log_rejects_path_traversal(home, project):
    pid = project["id"]
    assert publish.get_job(pid, "../escape") is None
    assert publish.read_job_log(pid, "../../secret") == ""
    assert publish.get_job(pid, "") is None


def test_log_suffix_does_not_pollute_the_job_listing(home, project):
    pid = project["id"]
    job = publish.record_job(pid, version="v1", form="full", commit_hash="abc")
    publish.append_job_log(pid, job["id"], "hello")
    assert [j["id"] for j in publish.list_jobs(pid)] == [job["id"]]


# ---------------------------------------------------------------------------
# route: finished job replays the full log, unknown id answers the contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_finished_job_returns_full_log(home, monkeypatch, project):
    pid = project["id"]
    job = publish.record_job(pid, version="v1", form="full", commit_hash="abc123")
    publish.append_job_log(pid, job["id"], "第一步")
    publish.append_job_log(pid, job["id"], publish.LOG_DONE_MARKER)
    publish.update_job_status(pid, job["id"], "success")

    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        resp = await client.get(f"/api/apps/ai-studio/publish/{job['id']}/log?project={pid}")
        assert resp.status == 200
        assert resp.content_type == "text/event-stream"
        frames = _sse_frames(await resp.read())

    assert frames[-1]["done"] is True
    assert frames[-1]["status"] == "success"
    lines = [ln for frame in frames for ln in frame["lines"]]
    # each line is timestamped ("[stamp] message"); the message is the tail
    assert [ln.rsplit("] ", 1)[-1] for ln in lines] == [
        "第一步",
        publish.LOG_DONE_MARKER,
    ]


@pytest.mark.asyncio
async def test_route_unknown_deployment_id_404(home, monkeypatch, project):
    pid = project["id"]

    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        resp = await client.get(f"/api/apps/ai-studio/publish/job-nope/log?project={pid}")
        assert resp.status == 404
        body = await resp.json()
        assert body["code"] == "job_not_found"
        assert "error" in body


@pytest.mark.asyncio
async def test_route_disabled_app_is_forbidden(home, monkeypatch, project):
    async with TestClient(TestServer(_make_app(monkeypatch, enabled=False))) as client:
        resp = await client.get(f"/api/apps/ai-studio/publish/job-x/log?project={project['id']}")
        assert resp.status == 403
        assert (await resp.json())["code"] == "app_disabled"


# ---------------------------------------------------------------------------
# route: a running job streams, frames grow, final frame carries the marker
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_running_job_streams_until_done(home, monkeypatch, project):
    pid = project["id"]
    job = publish.record_job(pid, version="v2", form="full", commit_hash="def456")
    publish.append_job_log(pid, job["id"], "开始发布 v2")

    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        resp = await client.get(f"/api/apps/ai-studio/publish/{job['id']}/log?project={pid}")
        assert resp.status == 200
        queue = _collect_frames(resp)

        first = await asyncio.wait_for(queue.get(), timeout=5)
        assert first["done"] is False
        assert [ln.rsplit("] ", 1)[-1] for ln in first["lines"]] == ["开始发布 v2"]

        # the executor appends while the stream is open; the next frames grow
        await asyncio.to_thread(publish.append_job_log, pid, job["id"], "构建中")
        second = await asyncio.wait_for(queue.get(), timeout=5)
        assert [ln.rsplit("] ", 1)[-1] for ln in second["lines"]] == ["构建中"]

        await asyncio.to_thread(publish.update_job_status, pid, job["id"], "success")
        final = await asyncio.wait_for(queue.get(), timeout=5)
        assert final["done"] is True
        assert final["status"] == "success"

        # EOF right after the done frame
        tail = await asyncio.wait_for(resp.content.read(), timeout=5)
        assert tail == b""
