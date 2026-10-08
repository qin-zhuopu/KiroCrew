"""Tests for the ai-studio requirement pages (ACP-2015 step 2, ACP-2104 step 4).

The read layer shells out to ``jc fe reqdoc``, so nothing here may depend on a
real ``jc`` being installed: every test points ``AI_STUDIO_REQDOC_CMD`` at a
fake command written into tmp_path. The fake speaks the same JSON envelope as
the real CLI (``{"success":true,"data":{...}}``) and the one failure the layer
must tolerate — render's ``BusinessError``/exit-20 on an unqualified graph.

Step 4 (直改 + 开始开发) added the two writes, and they are tested as what they
are: an optimistic-concurrency refusal on the DOCUMENT's hash, and a re-judged
start that refuses on the GRAPH's hash. Neither may touch the graph file — the
graph has exactly one writer (the 需求会话), which is why the tests assert the
json is byte-identical after a direct edit.

Store/route fixture shape is copied from test_ai_studio_projects.py: point
``KIROCREW_HOME`` at tmp_path and mount ``register_routes`` with
``is_app_enabled`` patched.
"""

from __future__ import annotations

import json
import os
import sys

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from kiro_crew.apps.builtins.ai_studio.backend import (
    projects,
    reqsession,
    requirements,
    routes,
)

#: The fake CLI's whole vocabulary. ``check`` derives its verdict from whether
#: the graph's ``goal`` still says 待定; ``render`` returns a one-line document.
_FAKE_REQDOC = """
import datetime, json, sys

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
    # The real `jc fe reqdoc render` stamps 生成时间：<ISO> into line 2 of every
    # document (reqstd-v34/render.js `generatedAt`), so two renders of ONE graph
    # differ. A fake that omitted it hid the bug that made 〔保存〕 always 409
    # (docHash moved on every 5s poll) — the fake has to be as volatile as the
    # thing it stands in for.
    # Shape mirrors the real line 2 (`…再重新生成。生成时间：<ISO>`): the stamp is the
    # tail of a CONTENT line, so stripping it leaves that line readable instead of
    # leaving a dangling marker behind.
    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    out({
        "file": path,
        "verdict": "全齐",
        "markdown": "# 需求：" + title + "\\n> 需求标准 fake。生成时间：" + stamp,
    })
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
        # the wire copy is the fake's document MINUS the render stamp: the route
        # hands out the stable text, so a client that echoes it back on save is
        # echoing exactly what the next save will be compared against
        assert page["markdown"] == "# 需求：设备清单\n> 需求标准 fake。"
        assert "生成时间" not in page["markdown"]
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


# ---------------------------------------------------------------------------
# 直改（ACP-2104，RFC §7 B5 / §9.4）
# ---------------------------------------------------------------------------


def _ledger(ws, name: str = requirements.DIRECT_EDITS_FILE) -> list[dict]:
    path = ws / name
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_doc_hash():
    assert requirements.doc_hash("") == requirements.doc_hash(None)
    assert len(requirements.doc_hash("# 需求")) == 16
    assert requirements.doc_hash("# 需求") == requirements.doc_hash("# 需求")
    assert requirements.doc_hash("# 需求") != requirements.doc_hash("# 需求 ")


def test_doc_hash_survives_the_render_stamp(reqdoc):
    # `jc fe reqdoc render` stamps 生成时间：<ISO> into every document, so two
    # reads of an UNCHANGED graph rendered different text. That made docHash —
    # the optimistic-concurrency token 〔保存〕 sends as baseDocHash — change on
    # every 5s poll, so a direct edit could never land: the first save 409'd
    # against a hash the page had already forgotten (found by the ACP-2104 live
    # run, not by any test, until the fake started stamping too).
    first = requirements.get_page(reqdoc, "设备清单")
    second = requirements.get_page(reqdoc, "设备清单")

    assert "生成时间" not in first["markdown"]
    assert first["markdown"] == second["markdown"]
    assert first["docHash"] == second["docHash"]
    # and the consequence that mattered: a save against the FIRST read still works
    result = requirements.direct_edit(
        reqdoc, "设备清单", first["docHash"], second["markdown"] + "\n备注：真跑加的"
    )
    assert result["changed"] is True
    # the stamp never reaches the session as a change the user did not make
    assert "生成时间" not in result["diff"]


def test_direct_edit_records_the_diff(reqdoc):
    # The doc is a VIEW of the graph, so a direct edit is a change REQUEST: the
    # ledger row and the diff are its whole product, and the graph file must come
    # out byte-identical (the 需求会话 is the graph's only writer).
    before = requirements.get_page(reqdoc, "设备清单")
    graph_path = reqdoc / requirements.REQ_DIR / "设备清单.json"
    graph_bytes = graph_path.read_bytes()

    # the fake renders one line ("# 需求：<title>"), and note WITHOUT a trailing
    # newline: the diff must not glue that last line to the added one
    new_markdown = before["markdown"] + "\n\n备注：删除按钮要二次确认"
    result = requirements.direct_edit(reqdoc, "设备清单", before["docHash"], new_markdown)

    assert result["changed"] is True
    assert result["pending"] is True
    assert result["diff"].startswith("--- ")
    assert "+备注：删除按钮要二次确认" in result["diff"]
    # the unchanged first line stays CONTEXT: without the missing trailing newline
    # patched in, difflib sees "…设备清单" != "…设备清单\n" and reports a deletion
    # the user never made
    assert "-# 需求" not in result["diff"]
    assert graph_path.read_bytes() == graph_bytes

    rows = _ledger(reqdoc)
    assert len(rows) == 1
    assert rows[0]["baseDocHash"] == before["docHash"]
    assert rows[0]["diff"] == result["diff"]
    assert rows[0]["at"].endswith("Z")


def test_direct_edit_rejects_a_stale_base_hash(reqdoc):
    # The assistant landed a change while the editor held the old view: saving on
    # top of it would silently undo the assistant, so nothing is recorded.
    before = requirements.get_page(reqdoc, "设备清单")
    _write_graph(reqdoc, "设备清单", "设备清单（助手改过标题）")

    with pytest.raises(requirements.RequirementError) as exc:
        requirements.direct_edit(reqdoc, "设备清单", before["docHash"], "# 我的改动")
    assert (exc.value.code, exc.value.status) == ("doc_changed", 409)
    assert str(exc.value) == "文档已被别人改过，请刷新"
    assert _ledger(reqdoc) == []


def test_direct_edit_identical_text_is_not_a_change(reqdoc):
    # A no-op save must NOT append: a row with an empty diff would pin the bar at
    # 「改动待落回需求」 forever, because no graph write can ever clear it.
    page = requirements.get_page(reqdoc, "设备清单")

    assert requirements.direct_edit(reqdoc, "设备清单", page["docHash"], page["markdown"]) == {
        "changed": False
    }
    assert _ledger(reqdoc) == []


def test_pending_edit_clears_when_the_graph_moves(reqdoc):
    page = requirements.get_page(reqdoc, "设备清单")
    assert page["pendingEdit"] is False

    requirements.direct_edit(reqdoc, "设备清单", page["docHash"], page["markdown"] + "\n新增一条\n")
    assert requirements.get_page(reqdoc, "设备清单")["pendingEdit"] is True

    # the assistant landing the change IS a rewrite of the graph file, so its
    # mtime jumps past the ledger row and the sentence clears itself
    graph_path = reqdoc / requirements.REQ_DIR / "设备清单.json"
    os.utime(graph_path)
    assert requirements.get_page(reqdoc, "设备清单")["pendingEdit"] is False


def test_pending_edit_survives_a_broken_ledger_line(reqdoc):
    page = requirements.get_page(reqdoc, "设备清单")
    requirements.direct_edit(reqdoc, "设备清单", page["docHash"], page["markdown"] + "\n新增一条\n")
    ledger = reqdoc / requirements.DIRECT_EDITS_FILE
    ledger.write_text(ledger.read_text(encoding="utf-8") + "{not json\n", encoding="utf-8")

    assert requirements.get_page(reqdoc, "设备清单")["pendingEdit"] is True


# ---------------------------------------------------------------------------
# 开始开发（ACP-2104，RFC §6 R2/R3、§9.4）
# ---------------------------------------------------------------------------


def test_start_records_the_request(reqdoc):
    page = requirements.get_page(reqdoc, "设备清单")

    result = requirements.start(reqdoc, "设备清单", page["graphHash"])

    assert result == {
        "ok": True,
        "page": "设备清单",
        "graphHash": page["graphHash"],
        "verdict": "全齐",
    }
    rows = _ledger(reqdoc, requirements.START_REQUESTS_FILE)
    assert len(rows) == 1
    assert rows[0]["graphHash"] == page["graphHash"]
    assert rows[0]["page"] == "设备清单"
    assert rows[0]["verdict"] == "全齐"
    # R2: the recorded hash is the hash the on-the-spot check used, i.e. the file's
    assert rows[0]["graphHash"] == requirements.graph_hash(
        reqdoc / requirements.REQ_DIR / "设备清单.json"
    )


def test_start_rejects_a_stale_graph_hash(reqdoc):
    page = requirements.get_page(reqdoc, "设备清单")
    _write_graph(reqdoc, "设备清单", "设备清单", goal="报表口径待定")

    with pytest.raises(requirements.RequirementError) as exc:
        requirements.start(reqdoc, "设备清单", page["graphHash"])
    assert (exc.value.code, exc.value.status) == ("graph_changed", 409)
    assert str(exc.value) == "需求刚刚变了"
    assert _ledger(reqdoc, requirements.START_REQUESTS_FILE) == []


def test_start_refuses_an_unqualified_graph_with_its_gaps(reqdoc):
    # 422 carries the verdict and the gaps (RFC §10 验收 11): the frontend must be
    # able to redraw the bar from the refusal it got, not from what it displayed.
    _write_graph(reqdoc, "设备清单", "设备清单", goal="报表口径待定")
    page = requirements.get_page(reqdoc, "设备清单")
    assert page["verdict"] == "不齐"

    with pytest.raises(requirements.RequirementError) as exc:
        requirements.start(reqdoc, "设备清单", page["graphHash"])
    err = exc.value
    assert (err.code, err.status) == ("not_ready", 422)
    assert str(err) == "需求不齐"
    assert err.details == {"verdict": "不齐", "missing": ["有待定"]}
    assert _ledger(reqdoc, requirements.START_REQUESTS_FILE) == []


def test_dev_state_tracks_the_graph(reqdoc):
    first = requirements.get_page(reqdoc, "设备清单")
    assert (first["devState"], first["changedAfterStart"]) == ("editing", False)

    requirements.start(reqdoc, "设备清单", first["graphHash"])
    started = requirements.get_page(reqdoc, "设备清单")
    assert (started["devState"], started["changedAfterStart"]) == ("started", False)

    # R3: the graph moved after the start request → back to editing with the
    # void marker, and the record itself stays in the ledger
    _write_graph(reqdoc, "设备清单", "设备清单", goal="换个目标")
    changed = requirements.get_page(reqdoc, "设备清单")
    assert (changed["devState"], changed["changedAfterStart"]) == ("editing", True)
    assert len(_ledger(reqdoc, requirements.START_REQUESTS_FILE)) == 1

    # re-starting on the new hash clears the marker
    requirements.start(reqdoc, "设备清单", changed["graphHash"])
    again = requirements.get_page(reqdoc, "设备清单")
    assert (again["devState"], again["changedAfterStart"]) == ("started", False)


def test_dev_state_ignores_other_pages(reqdoc):
    # The ledger is one file for the whole workspace, so the page filter is the
    # only thing separating two pages' states: starting 设备点检记录 must leave
    # 设备清单 reading as never-started.
    _write_graph(reqdoc, "设备点检记录", "设备点检记录")
    other = requirements.get_page(reqdoc, "设备点检记录")
    requirements.start(reqdoc, "设备点检记录", other["graphHash"])

    assert len(_ledger(reqdoc, requirements.START_REQUESTS_FILE)) == 1
    assert requirements.get_page(reqdoc, "设备清单")["devState"] == "editing"
    assert requirements.get_page(reqdoc, "设备点检记录")["devState"] == "started"


def test_dev_state_tolerates_a_broken_ledger(reqdoc):
    # The ledger is append-only JSONL that a human could hand-edit, so a broken
    # line is skipped, not fatal — and a row whose `at` cannot be read loses the
    # ordering race to a real timestamp (`_parse_iso` reads it as the earliest),
    # which is the conservative direction: an unverifiable record must not
    # out-rank a verifiable one and pretend to be the newest start.
    page = requirements.get_page(reqdoc, "设备清单")
    ledger = reqdoc / requirements.START_REQUESTS_FILE
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(
        "{坏行\n"
        + json.dumps({"at": "not-a-date", "page": "设备清单", "graphHash": "0" * 16})
        + "\n"
        + json.dumps(
            {"at": "2026-10-09T01:00:00Z", "page": "设备清单", "graphHash": page["graphHash"]}
        )
        + "\n",
        encoding="utf-8",
    )

    assert requirements.get_page(reqdoc, "设备清单")["devState"] == "started"

    # and the other way round: the unverifiable row loses, so the real record
    # (whose hash is stale) decides → editing + void marker
    ledger.write_text(
        json.dumps({"at": "2026-10-09T01:00:00Z", "page": "设备清单", "graphHash": "0" * 16})
        + "\n"
        + json.dumps({"at": "not-a-date", "page": "设备清单", "graphHash": page["graphHash"]})
        + "\n",
        encoding="utf-8",
    )
    changed = requirements.get_page(reqdoc, "设备清单")
    assert (changed["devState"], changed["changedAfterStart"]) == ("editing", True)


def test_start_page_missing_is_404(reqdoc):
    with pytest.raises(requirements.RequirementError) as exc:
        requirements.start(reqdoc, "nope", "x" * 16)
    assert (exc.value.code, exc.value.status) == ("page_not_found", 404)


# ---------------------------------------------------------------------------
# 两条写路由（ACP-2104）
# ---------------------------------------------------------------------------


#: the app's mounted prefix, spelled once because eight routes below hang off it
_P = "/api/apps/ai-studio/projects"


@pytest.fixture()
def notices(monkeypatch):
    """``reqsession.send_to_req_session`` replaced by a recorder.

    A fake rather than a real session: opening one spawns a CLI child, and this
    route's contract is only that the notice goes out ONCE with the diff in it —
    what the session then does with it is ACP-2089's tested ground.
    """
    calls: list[tuple[str, str]] = []

    async def _send(state, project, ws, text):
        calls.append((str(project.get("id")), str(text)))
        return {"slotKey": f"ai-studio-req-{project.get('id')}", "created": False}

    monkeypatch.setattr(reqsession, "send_to_req_session", _send)
    return calls


def _make_state_app(monkeypatch, enabled=True):
    monkeypatch.setattr(routes, "is_app_enabled", lambda _name: enabled)
    app = web.Application()
    app["state"] = object()  # the recorder above never touches it
    routes.register_routes(app)
    return app


@pytest.mark.asyncio
async def test_route_direct_edit(home, monkeypatch, reqdoc, notices):
    async with TestClient(TestServer(_make_state_app(monkeypatch))) as client:
        resp = await client.post(
            "/api/apps/ai-studio/projects", json={"name": "device", "description": ""}
        )
        pid = (await resp.json())["project"]["id"]
        _point_workspace_at(pid, reqdoc)

        page = await (await client.get(f"{_P}/{pid}/requirements/设备清单")).json()
        resp = await client.post(
            f"{_P}/{pid}/requirements/设备清单/direct-edit",
            json={
                "baseDocHash": page["docHash"],
                "markdown": page["markdown"] + "\n\n新增一条备注",
            },
        )
        assert resp.status == 200
        body = await resp.json()
        assert body["changed"] is True and body["pending"] is True

        # the notice went to the session exactly once and carries the diff (验收 9)
        assert len(notices) == 1
        assert notices[0][0] == pid
        assert "设备清单" in notices[0][1]
        assert "+新增一条备注" in notices[0][1]
        assert notices[0][1].startswith("用户在网页上直接改了需求页「设备清单」的文档")
        assert "落不进去的地方问我" in notices[0][1]

        # …and the page now reads as pending, which is what greys 开始开发 (B5)
        after = await (await client.get(f"{_P}/{pid}/requirements/设备清单")).json()
        assert after["pendingEdit"] is True

        # an identical save is a 200 no-op and tells the assistant nothing new
        resp = await client.post(
            f"{_P}/{pid}/requirements/设备清单/direct-edit",
            json={"baseDocHash": after["docHash"], "markdown": after["markdown"]},
        )
        assert resp.status == 200
        assert await resp.json() == {"changed": False}
        assert len(notices) == 1


@pytest.mark.asyncio
async def test_route_direct_edit_stale_hash_409(home, monkeypatch, reqdoc, notices):
    async with TestClient(TestServer(_make_state_app(monkeypatch))) as client:
        resp = await client.post(
            "/api/apps/ai-studio/projects", json={"name": "device", "description": ""}
        )
        pid = (await resp.json())["project"]["id"]
        _point_workspace_at(pid, reqdoc)
        stale = await (await client.get(f"{_P}/{pid}/requirements/设备清单")).json()
        # the assistant lands its own change: the editor is still holding the read
        # above, so its docHash is now the stale one
        _write_graph(reqdoc, "设备清单", "设备清单（助手落回过）")

        resp = await client.post(
            f"{_P}/{pid}/requirements/设备清单/direct-edit",
            json={"baseDocHash": stale["docHash"], "markdown": "# 我的改动"},
        )
        assert resp.status == 409
        body = await resp.json()
        assert body["code"] == "doc_changed"
        # the UI shows this sentence verbatim (RFC §8), so it is contract, not prose
        assert body["error"] == "文档已被别人改过，请刷新"
        assert notices == []

        resp = await client.post(
            f"{_P}/{pid}/requirements/设备清单/direct-edit", json={"markdown": "x"}
        )
        assert resp.status == 400
        assert (await resp.json())["code"] == "base_doc_hash_required"

        resp = await client.post(
            f"{_P}/no-such/requirements/设备清单/direct-edit",
            json={"baseDocHash": "0" * 16, "markdown": "x"},
        )
        assert resp.status == 404


@pytest.mark.asyncio
async def test_route_start(home, monkeypatch, reqdoc, tmp_path):
    async with TestClient(TestServer(_make_state_app(monkeypatch))) as client:
        resp = await client.post(
            "/api/apps/ai-studio/projects", json={"name": "device", "description": ""}
        )
        pid = (await resp.json())["project"]["id"]
        _point_workspace_at(pid, reqdoc)
        page = await (await client.get(f"{_P}/{pid}/requirements/设备清单")).json()

        resp = await client.post(
            f"{_P}/{pid}/requirements/设备清单/start", json={"graphHash": page["graphHash"]}
        )
        assert resp.status == 200
        body = await resp.json()
        assert body["ok"] is True
        assert body["graphHash"] == page["graphHash"]
        assert body["verdict"] == "全齐"
        rows = _ledger(reqdoc, requirements.START_REQUESTS_FILE)
        assert len(rows) == 1 and rows[0]["graphHash"] == page["graphHash"]

        started = await (await client.get(f"{_P}/{pid}/requirements/设备清单")).json()
        assert started["devState"] == "started"

        # 验收 11: a stale hash is refused with zero records written
        resp = await client.post(
            f"{_P}/{pid}/requirements/设备清单/start", json={"graphHash": "0" * 16}
        )
        assert resp.status == 409
        assert (await resp.json())["code"] == "graph_changed"

        resp = await client.post(f"{_P}/{pid}/requirements/设备清单/start", json={})
        assert resp.status == 400
        assert (await resp.json())["code"] == "graph_hash_required"

        resp = await client.post(f"{_P}/no-such/requirements/x/start", json={"graphHash": "a"})
        assert resp.status == 404


@pytest.mark.asyncio
async def test_route_start_not_ready_422_carries_the_gaps(home, monkeypatch, reqdoc):
    async with TestClient(TestServer(_make_state_app(monkeypatch))) as client:
        resp = await client.post(
            "/api/apps/ai-studio/projects", json={"name": "device", "description": ""}
        )
        pid = (await resp.json())["project"]["id"]
        _point_workspace_at(pid, reqdoc)
        _write_graph(reqdoc, "设备清单", "设备清单", goal="报表口径待定")
        page = await (await client.get(f"{_P}/{pid}/requirements/设备清单")).json()
        assert page["verdict"] == "不齐"

        resp = await client.post(
            f"{_P}/{pid}/requirements/设备清单/start", json={"graphHash": page["graphHash"]}
        )
        assert resp.status == 422
        body = await resp.json()
        assert body["code"] == "not_ready"
        assert body["verdict"] == "不齐"
        assert body["missing"] == ["有待定"]
        assert _ledger(reqdoc, requirements.START_REQUESTS_FILE) == []


@pytest.mark.asyncio
async def test_route_writes_disabled_403(home, monkeypatch):
    async with TestClient(TestServer(_make_state_app(monkeypatch, enabled=False))) as client:
        for path in ("direct-edit", "start"):
            resp = await client.post(f"{_P}/p/requirements/设备清单/{path}", json={})
            assert resp.status == 403
            assert (await resp.json())["code"] == "app_disabled"


class _Slot:
    def __init__(self, key):
        self.key, self.title, self.project, self.running = key, "", "", False
        self.appended: list[tuple[str, str]] = []

    def append(self, role, content, **_kw):
        self.appended.append((role, content))


class _State:
    """Just enough of the dashboard's slot registry for ``send_to_req_session``."""

    def __init__(self):
        self.slots: dict[str, _Slot] = {}

    def get_or_create_slot(self, **kw):
        key = kw.get("name") or "slot"
        return self.slots.setdefault(key, _Slot(key))


@pytest.mark.asyncio
async def test_direct_edit_notice_never_overtakes_the_opening_prompt(home, tmp_path):
    # The live order is real: the owner can edit the doc in the middle column
    # BEFORE the left column ever opened the session. Sending the diff straight at
    # the slot would land it ahead of 「现在先问我这次要做什么页面」, and the writer
    # would answer a diff it has no frame for. Going through ensure_req_session
    # fixes the order — and re-sends the prompt never (the record's flag).
    ws = tmp_path / "ws"
    ws.mkdir()
    directory = projects.projects_root() / "sbgl"
    directory.mkdir(parents=True)
    (directory / "project.json").write_text(
        json.dumps({"id": "sbgl", "name": "设备管理", "workspaceDir": str(ws)}, ensure_ascii=False),
        encoding="utf-8",
    )
    project = projects.get_project("sbgl")
    state = _State()
    sent: list[tuple[str, str]] = []

    def _dispatch(_state, slot, message):
        sent.append((slot.key, message))

    first = await reqsession.send_to_req_session(
        state, project, ws, "第一条通知", dispatch=_dispatch
    )
    again = await reqsession.send_to_req_session(
        state, project, ws, "第二条通知", dispatch=_dispatch
    )

    key = reqsession.slot_key("sbgl")
    assert first == {"slotKey": key, "created": True}
    assert again == {"slotKey": key, "created": False}
    assert [m for k, m in sent] == [
        reqsession.first_prompt(project, ws),
        "第一条通知",
        "第二条通知",
    ]
    assert {k for k, _ in sent} == {key}
    # the notice never appends to the slot itself — _dispatch_turn owns that, and it
    # is the piece that queues a message while the session is busy
    assert state.slots[key].appended == []


def test_edit_notice_carries_the_page_and_the_whole_diff():
    text = reqsession.edit_notice("设备分类", "--- a\n+++ b\n@@ -1 +1 @@\n-旧\n+新\n")

    assert text == (
        "用户在网页上直接改了需求页「设备分类」的文档，改动如下（diff）。"
        "请把这些改动落回 docs/需求图谱/设备分类.json，落不进去的地方问我。\n"
        "--- a\n+++ b\n@@ -1 +1 @@\n-旧\n+新\n"
    )
