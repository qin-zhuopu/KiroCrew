"""Tests for the ai-studio publish store and its two query endpoints.

The store reuses ``projects.py``'s posture (plain sync file I/O under
``KIROCREW_HOME``, routes on a bare aiohttp app with ``is_app_enabled``
monkeypatched), so the fixtures mirror test_ai_studio_projects.py. The B1
form judgment reads the project directory's git tags, so those tests build a
real throwaway git repo in the project directory.
"""
from __future__ import annotations

import subprocess

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from kiro_crew.apps.builtins.ai_studio.backend import projects, publish, routes


@pytest.fixture()
def home(tmp_path, monkeypatch):
    h = tmp_path / "crew"
    h.mkdir()
    monkeypatch.setenv("KIROCREW_HOME", str(h))
    return h


def _git(project_dir, *args):
    subprocess.run(
        ["git", "-C", str(project_dir), *args],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )


@pytest.fixture()
def project(home):
    """A project whose directory is a git repository (dev commits and the
    version tags land there — the store reads form from those tags)."""
    record = projects.create_project("发布工程", "")
    project_dir = projects.projects_root() / record["id"]
    _git(project_dir, "init", "-q")
    _git(project_dir, "config", "user.email", "t@example.com")
    _git(project_dir, "config", "user.name", "t")
    return record


def _tag_version(project_id, version, message):
    project_dir = projects.projects_root() / project_id
    (project_dir / "marker.txt").write_text(version, encoding="utf-8")
    _git(project_dir, "add", ".")
    _git(project_dir, "commit", "-q", "-m", f"version {version}")
    _git(project_dir, "tag", "-a", version, "-m", message)


# ---------------------------------------------------------------------------
# store: release records
# ---------------------------------------------------------------------------


def _record_kwargs(version="v3", commit="abc1234", form="full"):
    return {
        "version": version,
        "commit_hash": commit,
        "form": form,
        "requirement_version": "req-20260923-01",
        "jira_task_ids": ["ACP-700", "ACP-701"],
        "url": f"{version}-crm-14409.gb10.jereh-pe.cn",
        "deployment_id": f"dep-{version}",
    }


def test_record_and_list_release_records(home, project):
    pid = project["id"]
    first = publish.record_release(pid, **_record_kwargs("v1"))
    second = publish.record_release(pid, **_record_kwargs("v2", commit="def5678"))

    records = publish.list_release_records(pid)
    assert [r["version"] for r in records] == ["v2", "v1"]  # newest first
    assert records[0] == second and records[1] == first

    # B3 fields ride on every record
    for r in records:
        assert r["form"] in ("full", "demo")
        assert r["requirementVersion"] == "req-20260923-01"
        assert r["jiraTaskIds"] == ["ACP-700", "ACP-701"]
        assert r["status"] == "success"
        assert r["url"] == f"{r['version']}-crm-14409.gb10.jereh-pe.cn"
        assert r["commitHash"] and r["deploymentId"]

    with pytest.raises(publish.PublishError) as exc:
        publish.list_release_records("nope")
    assert exc.value.code == "project_not_found"


def test_latest_release_reads_only_success(home, project):
    pid = project["id"]
    assert publish.latest_release(pid) is None  # no record = 未发布
    publish.record_release(pid, **_record_kwargs("v1"))
    publish.record_release(
        pid, **{**_record_kwargs("v2", commit="bad"), "status": "failed"}
    )
    latest = publish.latest_release(pid)
    assert latest is not None and latest["commitHash"] == "abc1234"


def test_corrupt_record_file_is_skipped(home, project):
    pid = project["id"]
    publish.record_release(pid, **_record_kwargs("v1"))
    records_dir = projects.projects_root() / pid / "publish" / "records"
    (records_dir / "broken.json").write_text("{not json", encoding="utf-8")
    assert [r["version"] for r in publish.list_release_records(pid)] == ["v1"]


# ---------------------------------------------------------------------------
# store: release-jobs (a different concept — never merged with releases)
# ---------------------------------------------------------------------------


def test_job_lifecycle_lists_newest_first(home, project):
    pid = project["id"]
    job = publish.record_job(pid, version="v1", form="full")
    assert job["status"] == "running"
    later = publish.record_job(pid, version="v2", form="demo")

    assert [j["id"] for j in publish.list_jobs(pid)] == [later["id"], job["id"]]

    done = publish.update_job_status(pid, job["id"], "success")
    assert done is not None and done["status"] == "success"
    assert publish.update_job_status(pid, "job-missing", "failed") is None
    # a forged id names no job rather than traversing
    assert publish.update_job_status(pid, "../../evil", "failed") is None

    with pytest.raises(publish.PublishError) as exc:
        publish.list_jobs("nope")
    assert exc.value.code == "project_not_found"


# ---------------------------------------------------------------------------
# B1: form judgment from the git tag annotation
# ---------------------------------------------------------------------------


def test_preview_reads_tag_annotation(home, project):
    pid = project["id"]
    _tag_version(pid, "v1", "完整版：全量功能验收通过")
    _tag_version(pid, "v2", "demo: only the demo flow passed")

    assert publish.preview_version(pid, "v1") == {
        "form": "full",
        "reason": "完整版通过验收（git tag 标注为完整版）",
    }
    verdict = publish.preview_version(pid, "v2")
    assert verdict["form"] == "demo"
    assert "完整版未通过验收" in verdict["reason"]


def test_preview_rejects_missing_tag_and_missing_annotation(home, project):
    pid = project["id"]
    # no tag at all
    rejected = publish.preview_version(pid, "v9")
    assert rejected["form"] == "rejected"
    assert rejected["reason"]  # reason is never empty — the row renders it
    assert "验收未通过" in rejected["reason"]

    # a lightweight-style tag whose annotation names neither form
    project_dir = projects.projects_root() / pid
    (project_dir / "marker.txt").write_text("x", encoding="utf-8")
    _git(project_dir, "add", ".")
    _git(project_dir, "commit", "-q", "-m", "no annotation")
    _git(project_dir, "tag", "-a", "v3", "-m", "chore: release notes without a form")
    verdict = publish.preview_version(pid, "v3")
    assert verdict["form"] == "rejected"
    assert "验收未通过" in verdict["reason"]


def test_preview_without_a_git_repo_is_rejected(home):
    # a project directory that is not a git repository yet: no tags can
    # exist, which reads as a verdict, not an error
    record = projects.create_project("无仓库", "")
    verdict = publish.preview_version(record["id"], "v1")
    assert verdict == {
        "form": "rejected",
        "reason": "验收未通过：版本 v1 无 git tag 标注",
    }


def test_preview_validates_version(home, project):
    for bad in ("", "../v1", "a/b", "v1 v2", "x" * 81):
        with pytest.raises(publish.PublishError) as exc:
            publish.preview_version(project["id"], bad)
        assert exc.value.code == "invalid_version"
        assert exc.value.status == 400
    with pytest.raises(publish.PublishError) as exc:
        publish.preview_version("nope", "v1")
    assert exc.value.code == "project_not_found"


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------


def _make_app(monkeypatch, enabled=True):
    monkeypatch.setattr(routes, "is_app_enabled", lambda _name: enabled)
    app = web.Application()
    routes.register_routes(app)
    return app


@pytest.mark.asyncio
async def test_routes_publish_records_and_preview(home, monkeypatch, project):
    pid = project["id"]
    _tag_version(pid, "v1", "完整版")
    publish.record_release(pid, **_record_kwargs("v1"))

    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        resp = await client.get(f"/api/apps/ai-studio/publish/records?project={pid}")
        assert resp.status == 200
        records = (await resp.json())["records"]
        assert len(records) == 1
        assert records[0]["version"] == "v1"
        assert records[0]["status"] == "success"
        assert records[0]["jiraTaskIds"]

        resp = await client.get(f"/api/apps/ai-studio/publish/preview?project={pid}&version=v1")
        assert resp.status == 200
        body = await resp.json()
        assert body["form"] == "full"
        assert body["reason"]

        # a rejected form is a 200 verdict, not an error
        resp = await client.get(f"/api/apps/ai-studio/publish/preview?project={pid}&version=vmissing")
        assert resp.status == 200
        assert (await resp.json())["form"] == "rejected"


@pytest.mark.asyncio
async def test_routes_publish_errors(home, monkeypatch, project):
    pid = project["id"]
    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        resp = await client.get("/api/apps/ai-studio/publish/records")
        assert resp.status == 404
        assert (await resp.json())["code"] == "project_not_found"

        resp = await client.get(f"/api/apps/ai-studio/publish/preview?project={pid}&version=")
        assert resp.status == 400
        assert (await resp.json())["code"] == "invalid_version"

    monkeypatch.setattr(routes, "is_app_enabled", lambda _name: False)
    async with TestClient(TestServer(_make_app(monkeypatch, enabled=False))) as client:
        resp = await client.get(f"/api/apps/ai-studio/publish/records?project={pid}")
        assert resp.status == 403
        assert (await resp.json())["code"] == "app_disabled"
