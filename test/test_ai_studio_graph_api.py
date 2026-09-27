"""Tests for the ai-studio graph API (ACP-847, BGDD PoC T3).

Three real endpoints over one bundled real requirement graph
(``kg-sem-poc/requirement-graph/v0``, knowledge-doc-upload-v1):

- GET  /api/apps/ai-studio/graph                       → StudioGraph wire shape
- POST /api/apps/ai-studio/projects/{id}/freeze        → 201, duplicate → 409
- POST /api/apps/ai-studio/projects/{id}/regen         → graph→doc draft

Store tests drive ``graph.py`` directly with KIROCREW_HOME at tmp_path;
route tests mount ``register_routes`` with ``is_app_enabled`` monkey-patched,
the same shape test_ai_studio_projects.py uses.
"""
from __future__ import annotations

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from kiro_crew.apps.builtins.ai_studio.backend import graph, projects, routes


@pytest.fixture()
def home(tmp_path, monkeypatch):
    h = tmp_path / "crew"
    h.mkdir()
    monkeypatch.setenv("KIROCREW_HOME", str(h))
    return h


def _make_app(monkeypatch, enabled=True):
    monkeypatch.setattr(routes, "is_app_enabled", lambda _name: enabled)
    app = web.Application()
    routes.register_routes(app)
    return app


# ---------------------------------------------------------------------------
# mapping: requirement-graph/v0 → StudioGraph
# ---------------------------------------------------------------------------


def test_bundled_graph_loads_and_validates():
    doc = graph.load_graph()
    assert doc["schema"] == "kg-sem-poc/requirement-graph/v0"
    assert len(doc["acceptanceScenarios"]) >= 5


def test_mapping_shape_kinds_and_edges():
    studio = graph.to_studio_graph(graph.load_graph())
    kinds = {n["kind"] for n in studio["nodes"]}
    assert kinds == {"requirement", "doc", "module"}  # nothing outside the wire's union
    assert sum(1 for n in studio["nodes"] if n["kind"] == "requirement") >= 5
    assert {e["kind"] for e in studio["edges"]} == {"depends", "trace"}
    ids = {n["id"] for n in studio["nodes"]}
    assert all(e["from"] in ids and e["to"] in ids for e in studio["edges"])
    assert all(n["id"] and n["label"] for n in studio["nodes"])


def test_load_graph_rejects_foreign_json(tmp_path, monkeypatch):
    # a bundle that isn't a requirement graph is refused by load_graph's
    # schema guard, not half-mapped: point the resolver at a stub file and
    # let the real load path run.
    stub = tmp_path / "foreign.json"
    stub.write_text('{"graphType": "something-else"}', encoding="utf-8")
    monkeypatch.setattr(graph, "bundled_graph_path", lambda name="x": stub)
    with pytest.raises(graph.GraphError) as exc:
        graph.load_graph("foreign")
    assert exc.value.code == "graph_schema_mismatch"


def test_load_graph_rejects_path_names():
    for forged in ("../etc/passwd", "a/b", "", ".", ".."):
        with pytest.raises(graph.GraphError) as exc:
            graph.load_graph(forged)
        assert exc.value.code == "invalid_graph_name"


# ---------------------------------------------------------------------------
# freeze store: 201 then 409
# ---------------------------------------------------------------------------


def test_freeze_store_duplicate_raises(home):
    record = projects.create_project("g", "")
    pid = record["id"]
    rec = graph.freeze(pid, "v1", "requirements.md", "首轮")
    assert rec["version"] == "v1" and rec["docName"] == "requirements.md"
    assert rec["generatedFrom"] == "knowledge-doc-upload-v1"  # 追溯钉到具体图谱
    with pytest.raises(graph.FreezeError) as exc:
        graph.freeze(pid, "v1", "requirements.md")
    assert exc.value.code == "already_frozen" and exc.value.status == 409
    # a different version label is a fresh freeze
    graph.freeze(pid, "v2", "requirements.md")
    versions = [f["version"] for f in graph.list_freezes(pid)]
    assert set(versions) == {"v1", "v2"}


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_graph_disabled_403(home, monkeypatch):
    async with TestClient(TestServer(_make_app(monkeypatch, enabled=False))) as client:
        resp = await client.get("/api/apps/ai-studio/graph")
        assert resp.status == 403
        assert (await resp.json())["code"] == "app_disabled"


@pytest.mark.asyncio
async def test_route_graph_returns_studio_graph(home, monkeypatch):
    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        resp = await client.get("/api/apps/ai-studio/graph")
        assert resp.status == 200
        body = await resp.json()
        assert body["graphId"]
        g = body["graph"]
        assert sum(1 for n in g["nodes"] if n["kind"] == "requirement") >= 5
        assert {n["kind"] for n in g["nodes"]} == {"requirement", "doc", "module"}
        assert {e["kind"] for e in g["edges"]} == {"depends", "trace"}

        resp = await client.get("/api/apps/ai-studio/graph?graph=no-such-graph")
        assert resp.status == 404
        assert (await resp.json())["code"] == "graph_not_found"


@pytest.mark.asyncio
async def test_route_freeze_then_duplicate_409(home, monkeypatch):
    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        resp = await client.post("/api/apps/ai-studio/projects", json={"name": "冻结", "description": ""})
        pid = (await resp.json())["project"]["id"]

        resp = await client.post(
            f"/api/apps/ai-studio/projects/{pid}/freeze",
            json={"version": "v1", "docName": "requirements.md", "notes": "首个基线"},
        )
        assert resp.status == 201
        rec = (await resp.json())["freeze"]
        assert rec["version"] == "v1" and rec["notes"] == "首个基线"

        resp = await client.post(
            f"/api/apps/ai-studio/projects/{pid}/freeze",
            json={"version": "v1", "docName": "requirements.md"},
        )
        assert resp.status == 409
        assert (await resp.json())["code"] == "already_frozen"

        resp = await client.get(f"/api/apps/ai-studio/projects/{pid}/freezes")
        assert [f["version"] for f in (await resp.json())["freezes"]] == ["v1"]

        # missing fields and missing project keep the literal-status contract
        resp = await client.post(f"/api/apps/ai-studio/projects/{pid}/freeze", json={})
        assert resp.status == 400
        resp = await client.post(
            "/api/apps/ai-studio/projects/missing/freeze",
            json={"version": "v1", "docName": "a.md"},
        )
        assert resp.status == 404
        assert (await resp.json())["code"] == "project_not_found"


@pytest.mark.asyncio
async def test_route_regen_writes_traceable_draft(home, monkeypatch):
    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        resp = await client.post("/api/apps/ai-studio/projects", json={"name": "再生成", "description": ""})
        pid = (await resp.json())["project"]["id"]

        resp = await client.post(
            f"/api/apps/ai-studio/projects/{pid}/regen",
            json={"docName": "requirements.md"},
        )
        assert resp.status == 201
        body = await resp.json()
        assert body["doc"] == "requirements.md"
        assert body["generatedFrom"]  # 追溯到具体图谱生成

        # the draft really landed in the project's draft store…
        resp = await client.get(f"/api/apps/ai-studio/projects/{pid}/drafts")
        drafts = (await resp.json())["drafts"]
        draft = next(d for d in drafts if d["name"] == "requirements.md")
        assert draft["content"] == body["content"]

        # …and every sentence-bearing id in it came from the graph
        doc = graph.load_graph()
        assert doc["graphId"] in draft["content"]
        for sc in doc["acceptanceScenarios"]:
            assert f"id={sc['id']}" in draft["content"]

        resp = await client.post("/api/apps/ai-studio/projects/missing/regen", json={})
        assert resp.status == 404
        assert (await resp.json())["code"] == "project_not_found"
