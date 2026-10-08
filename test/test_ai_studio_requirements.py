"""Tests for the ai-studio read-only requirement pages (ACP-2015 step 2).

The read layer shells out to ``jc fe reqdoc``, so nothing here may depend on a
real ``jc`` being installed: every test points ``AI_STUDIO_REQDOC_CMD`` at a
fake command written into tmp_path. The fake speaks the same JSON envelope as
the real CLI (``{"success":true,"data":{...}}``) and the one failure the layer
must tolerate — render's ``BusinessError``/exit-20 on an unqualified graph.

Store/route fixture shape is copied from test_ai_studio_projects.py: point
``KIROCREW_HOME`` at tmp_path and mount ``register_routes`` with
``is_app_enabled`` patched.
"""

from __future__ import annotations

import json
import sys

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from kiro_crew.apps.builtins.ai_studio.backend import projects, requirements, routes

#: The fake CLI's whole vocabulary. ``check`` derives its verdict from whether
#: the graph's ``goal`` still says 待定; ``render`` returns a one-line document.
_FAKE_REQDOC = """
import json, sys

argv = sys.argv[1:]
sub = argv[0]
args = argv[1:]
path = None
skip = False
for a in args:
    if skip:
        skip = False
        continue
    if a == "--frame":
        skip = True
        continue
    if a.startswith("--"):
        continue
    path = a

graph = json.load(open(path, encoding="utf-8"))


def out(payload):
    print(json.dumps({"success": True, "version": "fake", "data": payload}, ensure_ascii=False))


if sub == "check":
    goal = graph.get("goal")
    pending = "待定" in json.dumps(goal, ensure_ascii=False)
    out({
        "file": path,
        "version": 34,
        "verdict": "不齐" if pending else "全齐",
        "errors": [],
        "missing": ["有待定"] if pending else [],
        "tiers": {"api": [], "ui": [], "parts": []},
        "warnings": [],
    })
elif sub == "render":
    title = (graph.get("page") or {}).get("title") or ""
    out({"file": path, "verdict": "全齐", "markdown": "# 需求：" + title})
else:
    print(json.dumps({"success": False, "errorType": "ParameterError", "message": "bad sub"}))
    raise SystemExit(10)
"""


@pytest.fixture()
def home(tmp_path, monkeypatch):
    h = tmp_path / "crew"
    h.mkdir()
    monkeypatch.setenv("KIROCREW_HOME", str(h))
    return h


@pytest.fixture()
def reqdoc(home, tmp_path, monkeypatch):
    """The fake command wired in as the reqdoc CLI, plus a workspace holding
    one qualified page. Returns the workspace."""
    script = tmp_path / "fake_reqdoc.py"
    script.write_text(_FAKE_REQDOC, encoding="utf-8")
    monkeypatch.setenv("AI_STUDIO_REQDOC_CMD", f"{sys.executable} {script}")
    monkeypatch.delenv("AI_STUDIO_REQDOC_FRAME", raising=False)
    ws = tmp_path / "ws"
    (ws / requirements.REQ_DIR).mkdir(parents=True)
    _write_graph(ws, "设备清单", "设备清单")
    return ws


def _write_graph(ws, name: str, title: str, goal: str = "能维护设备台账") -> None:
    (ws / requirements.REQ_DIR / f"{name}.json").write_text(
        json.dumps({"goal": goal, "page": {"title": title}}, ensure_ascii=False),
        encoding="utf-8",
    )


def _make_app(monkeypatch, enabled=True):
    monkeypatch.setattr(routes, "is_app_enabled", lambda _name: enabled)
    app = web.Application()
    routes.register_routes(app)
    return app


# ---------------------------------------------------------------------------
# read layer
# ---------------------------------------------------------------------------


def test_list_empty_when_no_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_STUDIO_REQDOC_CMD", "/nonexistent/cmd")
    assert requirements.list_pages(tmp_path / "nope") == []


def test_list_two_pages_sorted(reqdoc):
    _write_graph(reqdoc, "设备点检记录", "设备点检记录")
    # written last but sorts second by name; mtime proves updatedAt is the file's
    (reqdoc / requirements.REQ_DIR / "设备点检记录.json").touch()

    pages = requirements.list_pages(reqdoc)

    assert [p["page"] for p in pages] == ["设备清单", "设备点检记录"]
    assert [p["verdict"] for p in pages] == ["全齐", "全齐"]
    assert all(p["missingCount"] == 0 for p in pages)
    assert all(len(p["graphHash"]) == 16 for p in pages)
    assert all(p["updatedAt"].endswith("Z") for p in pages)


def test_get_page_ok(reqdoc):
    page = requirements.get_page(reqdoc, "设备清单")

    assert page["page"] == "设备清单"
    assert page["markdown"].startswith("# 需求：")
    assert len(page["graphHash"]) == 16
    assert page["devState"] == "editing"
    assert page["stale"] is False
    assert page["verdict"] == "全齐"
    assert page["graph"]["page"]["title"] == "设备清单"
    assert page["tiers"] == {"api": [], "ui": [], "parts": []}


def test_get_page_not_ready(reqdoc):
    _write_graph(reqdoc, "设备清单", "设备清单", goal="报表口径待定")

    page = requirements.get_page(reqdoc, "设备清单")

    assert page["verdict"] == "不齐"
    assert page["missing"] == ["有待定"]


def test_get_page_traversal_404(reqdoc):
    for bad in ("../x", "a/b", "a\\b", ".hidden", "", "..", "x.json/../../etc/passwd"):
        with pytest.raises(requirements.RequirementError) as exc:
            requirements.get_page(reqdoc, bad)
        assert exc.value.code == "page_not_found"
        assert exc.value.status == 404

    with pytest.raises(requirements.RequirementError) as exc:
        requirements.get_page(reqdoc, "no-such-page")
    assert (exc.value.code, exc.value.status) == ("page_not_found", 404)


def test_cmd_unavailable_503(reqdoc, monkeypatch):
    monkeypatch.setenv("AI_STUDIO_REQDOC_CMD", "/nonexistent/cmd")

    with pytest.raises(requirements.RequirementError) as exc:
        requirements.get_page(reqdoc, "设备清单")
    assert exc.value.code == "reqdoc_cmd_unavailable"
    assert exc.value.status == 503


def test_workspace_dir_override(tmp_path, monkeypatch, reqdoc):
    # project.json's workspaceDir points at another tree: that is where the
    # graphs are read from, never the project's own directory.
    record = projects.create_project("设备管理", "")
    project_path = projects.projects_root() / record["id"]
    data = json.loads((project_path / "project.json").read_text(encoding="utf-8"))
    data["workspaceDir"] = str(reqdoc)
    (project_path / "project.json").write_text(json.dumps(data), encoding="utf-8")

    record = projects.get_project(record["id"])
    resolved = requirements.workspace_dir(record, project_path)

    assert resolved == reqdoc
    assert [p["page"] for p in requirements.list_pages(resolved)] == ["设备清单"]

    # a workspaceDir that is relative or missing falls back to the project dir
    assert requirements.workspace_dir({}, project_path) == project_path
    assert requirements.workspace_dir({"workspaceDir": "ws"}, project_path) == project_path
    assert (
        requirements.workspace_dir({"workspaceDir": str(tmp_path / "gone")}, project_path)
        == project_path
    )


def test_graph_hash_is_stable(reqdoc):
    path = reqdoc / requirements.REQ_DIR / "设备清单.json"
    first = requirements.graph_hash(path)
    assert first == requirements.graph_hash(path)
    assert len(first) == 16

    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert requirements.graph_hash(path) != first


def test_invalid_graph_json_422(reqdoc):
    (reqdoc / requirements.REQ_DIR / "坏页.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(requirements.RequirementError) as exc:
        requirements.get_page(reqdoc, "坏页")
    assert (exc.value.code, exc.value.status) == ("graph_invalid_json", 422)


def test_render_refusal_yields_no_markdown(reqdoc, tmp_path, monkeypatch):
    # The real CLI refuses to render an unqualified graph with
    # BusinessError/exit 20; that is a verdict, not a 502.
    script = tmp_path / "fake_render_refuses.py"
    script.write_text(
        "import json, sys\n"
        "graph = json.load(open([a for a in sys.argv[2:] if not a.startswith('--')][-1],"
        " encoding='utf-8'))\n"
        'pending = "待定" in json.dumps(graph.get("goal"), ensure_ascii=False)\n'
        "if sys.argv[1] == 'check':\n"
        '    print(json.dumps({"success": True, "data": {"verdict": "不齐" if pending else "全齐",'
        ' "errors": [], "missing": ["有待定"] if pending else [],'
        ' "tiers": {"api": [], "ui": [], "parts": []}}}, ensure_ascii=False))\n'
        "elif pending:\n"
        '    print(json.dumps({"success": False, "errorType": "BusinessError",'
        ' "message": "需求图谱不合格，没生成文档（1 处）"}, ensure_ascii=False))\n'
        "    raise SystemExit(20)\n"
        "else:\n"
        '    print(json.dumps({"success": True, "data": {"markdown": "# 需求"}}))\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("AI_STUDIO_REQDOC_CMD", f"{sys.executable} {script}")
    _write_graph(reqdoc, "待定页", "待定页", goal="口径待定")

    page = requirements.get_page(reqdoc, "待定页")

    assert page["markdown"] is None
    assert page["verdict"] == "不齐"


def test_reqdoc_cmd_and_frame_flag(monkeypatch):
    monkeypatch.delenv("AI_STUDIO_REQDOC_CMD", raising=False)
    assert requirements.reqdoc_cmd() == ["jc", "fe", "reqdoc"]
    monkeypatch.setenv("AI_STUDIO_REQDOC_CMD", "my-reqdoc --json")
    assert requirements.reqdoc_cmd() == ["my-reqdoc", "--json"]

    monkeypatch.delenv("AI_STUDIO_REQDOC_FRAME", raising=False)
    assert requirements._frame_args() == []
    monkeypatch.setenv("AI_STUDIO_REQDOC_FRAME", "/tmp/frame")
    assert requirements._frame_args() == ["--frame", "/tmp/frame"]


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_routes_get_requirements(home, monkeypatch, reqdoc, tmp_path):
    _write_graph(reqdoc, "设备点检记录", "设备点检记录")
    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        resp = await client.post(
            "/api/apps/ai-studio/projects",
            json={"name": "设备管理（演示）", "description": ""},
        )
        pid = (await resp.json())["project"]["id"]
        _point_workspace_at(pid, reqdoc)

        resp = await client.get(f"/api/apps/ai-studio/projects/{pid}/requirements")
        assert resp.status == 200
        body = await resp.json()
        assert [p["page"] for p in body["pages"]] == ["设备清单", "设备点检记录"]
        assert [p["verdict"] for p in body["pages"]] == ["全齐", "全齐"]

        resp = await client.get(f"/api/apps/ai-studio/projects/{pid}/requirements/设备清单")
        assert resp.status == 200
        page = await resp.json()
        assert page["markdown"] == "# 需求：设备清单"
        assert page["devState"] == "editing"

        # no docs/需求图谱 yet is an empty list, not a 404. The name is ASCII on
        # purpose: a pure-CJK name slugs to an empty fragment, so both ids would
        # be `p<second>` and the second create inside the same second would
        # collide on the directory (a 503 from create_project, not our bug).
        resp = await client.post(
            "/api/apps/ai-studio/projects", json={"name": "empty", "description": ""}
        )
        empty_pid = (await resp.json())["project"]["id"]
        resp = await client.get(f"/api/apps/ai-studio/projects/{empty_pid}/requirements")
        assert resp.status == 200
        assert (await resp.json())["pages"] == []

        resp = await client.get("/api/apps/ai-studio/projects/no-such-project/requirements")
        assert resp.status == 404
        assert (await resp.json())["code"] == "project_not_found"

        resp = await client.get("/api/apps/ai-studio/projects/no-such-project/requirements/x")
        assert resp.status == 404
        assert (await resp.json())["code"] == "project_not_found"

        resp = await client.get(f"/api/apps/ai-studio/projects/{pid}/requirements/..%2Fx")
        assert resp.status in (400, 404)


@pytest.mark.asyncio
async def test_routes_requirements_error_mapping(home, monkeypatch, reqdoc):
    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        resp = await client.post(
            "/api/apps/ai-studio/projects", json={"name": "设备管理", "description": ""}
        )
        pid = (await resp.json())["project"]["id"]
        _point_workspace_at(pid, reqdoc)

        resp = await client.get(f"/api/apps/ai-studio/projects/{pid}/requirements/nope")
        assert resp.status == 404
        assert (await resp.json())["code"] == "page_not_found"

        monkeypatch.setenv("AI_STUDIO_REQDOC_CMD", "/nonexistent/cmd")
        resp = await client.get(f"/api/apps/ai-studio/projects/{pid}/requirements")
        assert resp.status == 503
        assert (await resp.json())["code"] == "reqdoc_cmd_unavailable"


def _point_workspace_at(project_id: str, ws) -> None:
    path = projects.projects_root() / project_id / "project.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["workspaceDir"] = str(ws)
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.mark.asyncio
async def test_routes_requirements_disabled_403(home, monkeypatch):
    async with TestClient(TestServer(_make_app(monkeypatch, enabled=False))) as client:
        resp = await client.get("/api/apps/ai-studio/projects/p/requirements")
        assert resp.status == 403
        assert (await resp.json())["code"] == "app_disabled"
