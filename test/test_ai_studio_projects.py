"""Tests for the ai-studio project store and its HTTP routes.

The store is plain sync file I/O under ``config_dir()``, so the store tests
drive it with nothing but ``KIROCREW_HOME`` pointed at tmp_path (config_dir
re-resolves per call — that is what makes this cheap). The route tests mount
``register_routes`` on a bare aiohttp app with ``is_app_enabled`` monkey-
patched, the same shape test_ai_backend_routes_coverage.py uses for its
builtins.
"""
from __future__ import annotations

import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from kiro_crew.apps.builtins.ai_studio.backend import projects, routes


@pytest.fixture()
def home(tmp_path, monkeypatch):
    h = tmp_path / "crew"
    h.mkdir()
    monkeypatch.setenv("KIROCREW_HOME", str(h))
    return h


# ---------------------------------------------------------------------------
# store
# ---------------------------------------------------------------------------


def test_create_then_list_and_get(home):
    record = projects.create_project("商机雷达", "追踪商机转化")
    assert record["name"] == "商机雷达"
    assert record["id"]  # slug may be empty for pure CJK; timestamp suffix carries it

    listed = projects.list_projects()
    assert [p["id"] for p in listed] == [record["id"]]

    got = projects.get_project(record["id"])
    assert got == record

    docs = projects.list_docs(record["id"])
    assert [d["name"] for d in docs] == ["requirements.md", "ui-spec.md", "workflow.md"]
    # the seed templates interpolate the create request
    req = next(d for d in docs if d["name"] == "requirements.md")
    assert "商机雷达" in req["content"]
    assert "追踪商机转化" in req["content"]


def test_list_newest_first(home):
    first = projects.create_project("a", "")
    second = projects.create_project("b", "")
    # same-second creates share a timestamp suffix... force ordering explicitly
    pj = projects.projects_root() / first["id"] / "project.json"
    data = json.loads(pj.read_text(encoding="utf-8"))
    data["createdAt"] += 1000
    pj.write_text(json.dumps(data), encoding="utf-8")
    assert [p["id"] for p in projects.list_projects()] == [first["id"], second["id"]]


def test_stray_directory_is_not_a_project(home):
    (projects.projects_root() / "half-built").mkdir(parents=True)
    assert projects.list_projects() == []
    assert projects.get_project("half-built") is None


def test_corrupt_project_json_reads_as_absence(home):
    record = projects.create_project("ok", "")
    bad = projects.projects_root() / "broken"
    bad.mkdir()
    (bad / "project.json").write_text("{not json", encoding="utf-8")
    assert [p["id"] for p in projects.list_projects()] == [record["id"]]
    assert projects.get_project("broken") is None


def test_get_project_rejects_traversal_ids(home):
    projects.create_project("ok", "")
    for forged in ("../..", "..", ".", "a/b", "a\\b", ""):
        assert projects.get_project(forged) is None


def test_create_requires_name(home):
    with pytest.raises(projects.ProjectError) as exc:
        projects.create_project("   ", "")
    assert exc.value.code == "name_required"
    assert exc.value.status == 400


def test_create_caps_name(home):
    with pytest.raises(projects.ProjectError) as exc:
        projects.create_project("n" * (projects.MAX_NAME_LEN + 1), "")
    assert exc.value.code == "name_too_long"


def test_save_doc_roundtrip_and_validation(home):
    record = projects.create_project("ok", "")
    doc = projects.save_doc(record["id"], "notes.md", "# notes\n")
    assert doc == {"name": "notes.md", "content": "# notes\n"}
    assert projects.save_doc(record["id"], "notes.md", "v2")["content"] == "v2"
    names = [d["name"] for d in projects.list_docs(record["id"])]
    assert "notes.md" in names

    for bad in ("../evil.md", "sub/x.md", ".hidden.md", "run.sh", ""):
        with pytest.raises(projects.ProjectError) as exc:
            projects.save_doc(record["id"], bad, "x")
        assert exc.value.code == "invalid_doc_name"

    with pytest.raises(projects.ProjectError) as exc:
        projects.save_doc("nope", "a.md", "x")
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
async def test_routes_disabled_app_403(home, monkeypatch):
    async with TestClient(TestServer(_make_app(monkeypatch, enabled=False))) as client:
        resp = await client.get("/api/apps/ai-studio/projects")
        assert resp.status == 403
        assert (await resp.json())["code"] == "app_disabled"


@pytest.mark.asyncio
async def test_routes_create_list_get_save(home, monkeypatch):
    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        resp = await client.post(
            "/api/apps/ai-studio/projects",
            json={"name": "示例项目", "description": "描述"},
        )
        assert resp.status == 201
        record = (await resp.json())["project"]

        resp = await client.get("/api/apps/ai-studio/projects")
        assert [p["id"] for p in (await resp.json())["projects"]] == [record["id"]]

        resp = await client.get(f"/api/apps/ai-studio/projects/{record['id']}")
        body = await resp.json()
        assert body["project"]["id"] == record["id"]
        assert [d["name"] for d in body["docs"]] == [
            "requirements.md",
            "ui-spec.md",
            "workflow.md",
        ]

        resp = await client.post(
            f"/api/apps/ai-studio/projects/{record['id']}/docs",
            json={"name": "requirements.md", "content": "# changed"},
        )
        assert resp.status == 200
        assert (await resp.json())["doc"]["content"] == "# changed"

        resp = await client.get(f"/api/apps/ai-studio/projects/{record['id']}")
        docs = (await resp.json())["docs"]
        assert next(d for d in docs if d["name"] == "requirements.md")["content"] == "# changed"


@pytest.mark.asyncio
async def test_routes_errors(home, monkeypatch):
    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        resp = await client.post("/api/apps/ai-studio/projects", json={"name": ""})
        assert resp.status == 400
        assert (await resp.json())["code"] == "name_required"

        resp = await client.post(
            "/api/apps/ai-studio/projects", json={"name": "x", "description": 5}
        )
        assert resp.status == 400

        resp = await client.get("/api/apps/ai-studio/projects/missing")
        assert resp.status == 404
        assert (await resp.json())["code"] == "project_not_found"

        resp = await client.post(
            "/api/apps/ai-studio/projects/missing/docs",
            json={"name": "a.md", "content": ""},
        )
        assert resp.status == 404
