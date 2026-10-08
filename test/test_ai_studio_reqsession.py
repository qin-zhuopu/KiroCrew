"""Tests for the ai-studio requirement session (ACP-2085 S2, RFC §9.3).

Nothing here may start a real session: ``state`` is a fake that records the
``get_or_create_slot`` call and hands back a slot whose attributes are plain
writable fields, and ``dispatch`` is an injected recorder — the one seam a real
``_run_chat`` would be reached through. What a fake cannot fake is the contract
this unit exists to hold: the slot is scoped at the workspace, titled
需求：〈名〉, stays ATTENDED, and the opening prompt goes out exactly once.

Store/route fixture shape is copied from test_ai_studio_requirements.py: point
``KIROCREW_HOME`` at tmp_path and mount ``register_routes`` with
``is_app_enabled`` patched.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from kiro_crew.apps.builtins.ai_studio.backend import projects, reqsession, routes


@pytest.fixture()
def home(tmp_path, monkeypatch):
    h = tmp_path / "crew"
    h.mkdir()
    monkeypatch.setenv("KIROCREW_HOME", str(h))
    return h


class FakeSlot:
    """A slot the module can do anything to: every attribute is a plain field."""

    def __init__(self, key: str):
        self.key = key
        self.title = ""
        self.project = ""
        self.running = False
        self.appended: list[tuple[str, str]] = []

    def append(self, role, content, **_kw):
        self.appended.append((role, content))


class FakeState:
    """Records the calls ``ensure_req_session`` makes; owns its slots by key."""

    def __init__(self):
        self.slots: dict[str, FakeSlot] = {}
        self.create_calls: list[dict] = []
        self.titles_pushed: list[tuple[str, str]] = []
        self.slots_pushed = 0

    def get_or_create_slot(self, **kw):
        self.create_calls.append(kw)
        key = kw.get("name") or "slot"
        return self.slots.setdefault(key, FakeSlot(key))

    def push_slot_title(self, key, title):
        self.titles_pushed.append((key, title))

    def push_slots_update(self):
        self.slots_pushed += 1


def _recording_dispatch():
    """A dispatch stand-in plus the list it records ``(slotKey, message)`` into."""
    calls: list[tuple[str, str]] = []

    def _dispatch(_state, slot, message):
        calls.append((slot.key, message))
        return None

    return _dispatch, calls


def _make_project(project_id: str, name: str, workspace=None) -> dict:
    """A project record on disk with a caller-chosen id.

    ``projects.create_project`` mints its own id from the name plus a timestamp,
    which the route tests do not want: this unit's key is derived from the id, so
    the assertions need a known one. The file is the store's own shape.
    """
    record: dict = {"id": project_id, "name": name, "description": "", "createdAt": 1.0}
    if workspace is not None:
        record["workspaceDir"] = str(workspace)
    directory = projects.projects_root() / project_id
    directory.mkdir(parents=True)
    (directory / "project.json").write_text(json.dumps(record, ensure_ascii=False), "utf-8")
    return record


# ---------------------------------------------------------------------------
# slot_key / first_prompt
# ---------------------------------------------------------------------------


def test_slot_key():
    assert reqsession.slot_key("sbgl") == "ai-studio-req-sbgl"
    assert reqsession.slot_key("p261008-151745") == "ai-studio-req-p261008-151745"


def test_first_prompt_wording(tmp_path):
    agent = tmp_path / reqsession.WRITER_AGENT_FILE
    agent.parent.mkdir(parents=True)
    agent.write_text("# writer", encoding="utf-8")

    text = reqsession.first_prompt({"name": "设备管理"}, tmp_path)

    assert text == (
        f"你在工作区「设备管理」（目录 {tmp_path}）。"
        "先完整读 .claude/agents/requirement-writer.md，之后完全按它工作。\n"
        "需求图谱放 docs/需求图谱/，需求标准在 docs/需求标准/。现在先问我这次要做什么页面。"
    )


def test_first_prompt_without_agent_file(tmp_path):
    text = reqsession.first_prompt({"name": "设备管理"}, tmp_path)

    assert "这个工作区缺少写需求助手" in text
    assert "先完整读 .claude/agents/requirement-writer.md" not in text


# ---------------------------------------------------------------------------
# ensure_req_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_call_scopes_and_opens(home, tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    project = _make_project("sbgl", "设备管理")
    state = FakeState()
    dispatch, calls = _recording_dispatch()

    result = await reqsession.ensure_req_session(state, project, ws, dispatch=dispatch)

    assert result["created"] is True
    key = reqsession.slot_key("sbgl")
    assert result["slotKey"] == key
    # created through the app-scoped path, so the slot never surfaces in the
    # main chat sidebar and this app's later reads pass the cross-app deny
    assert state.create_calls == [{"name": key, "app": "ai-studio"}]
    slot = state.slots[key]
    assert slot.project == str(ws)
    assert slot.title == "需求：设备管理"
    assert state.titles_pushed == [(key, "需求：设备管理")]
    # 需求会话是前台会话：`unattended` 是 _ChatSlot 的只读属性，本模块一个字都不写它
    # （写它 = 给会话下 180 秒批准毒咒，见 dashboard/state.py:approval_timeout_for）
    assert "unattended" not in vars(slot)
    assert not getattr(slot, "unattended", False)
    # the opening prompt went out once, verbatim
    assert calls == [(key, reqsession.first_prompt(project, ws))]
    # and the record now says so
    assert projects.get_project("sbgl")["reqSessionStarted"] is True


@pytest.mark.asyncio
async def test_second_call_is_silent(home, tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    project = _make_project("sbgl", "设备管理")
    state = FakeState()
    dispatch, calls = _recording_dispatch()

    first = await reqsession.ensure_req_session(state, project, ws, dispatch=dispatch)
    again = await reqsession.ensure_req_session(state, project, ws, dispatch=dispatch)

    assert first["created"] is True
    assert again == {"slotKey": first["slotKey"], "created": False}
    assert len(calls) == 1
    assert len(state.slots) == 1
    # the flag is durable: a session reopened after a gateway restart — from a
    # freshly-read project record — is still not a first session
    marked = projects.get_project("sbgl")
    assert marked["reqSessionStarted"] is True
    third = await reqsession.ensure_req_session(state, marked, ws, dispatch=dispatch)
    assert third["created"] is False
    assert len(calls) == 1


def test_update_project_merges(home):
    # update_project is this module's own writer (projects.py has no update
    # entry): it must merge, not replace, and leave readable json behind.
    record = projects.create_project("设备管理", "描述")

    updated = reqsession.update_project(record["id"], reqSessionStarted=True)

    data = json.loads((projects.projects_root() / record["id"] / "project.json").read_text())
    assert updated["reqSessionStarted"] is True
    assert data["reqSessionStarted"] is True
    assert data["name"] == "设备管理"
    assert data["description"] == "描述"
    assert data["id"] == record["id"]
    # no temp litter left in the store by the atomic write
    assert sorted(p.name for p in (projects.projects_root() / record["id"]).iterdir()) == [
        "docs",
        "project.json",
    ]


def test_update_project_missing_is_404(home):
    with pytest.raises(reqsession.ReqSessionError) as exc:
        reqsession.update_project("gone", reqSessionStarted=True)
    assert (exc.value.code, exc.value.status) == ("project_not_found", 404)


@pytest.mark.asyncio
async def test_unmarked_existing_slot_still_opens_once(home, tmp_path):
    # A slot some other path created under our key is adopted and scoped; the
    # first prompt still goes out exactly once, because `created` keys on the
    # project record, not on whether this call minted the slot.
    ws = tmp_path / "ws"
    ws.mkdir()
    project = _make_project("sbgl", "设备管理")
    state = FakeState()
    preexisting = state.get_or_create_slot(name=reqsession.slot_key("sbgl"))
    dispatch, calls = _recording_dispatch()

    first = await reqsession.ensure_req_session(state, project, ws, dispatch=dispatch)
    second = await reqsession.ensure_req_session(
        state, projects.get_project("sbgl"), ws, dispatch=dispatch
    )

    assert (first["created"], second["created"]) == (True, False)
    assert preexisting.project == str(ws)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_concurrent_opens_send_the_prompt_once(home, tmp_path):
    # The live run showed the assistant asking the same question TWICE. The
    # mount effect fires twice (React StrictMode in dev, a retry on a slow first
    # paint in prod), so two POSTs of the SAME project are in flight together,
    # both read project.json before either writes `reqSessionStarted`, and the
    # persisted flag cannot tell them apart — the window is a real await.
    ws = tmp_path / "ws"
    ws.mkdir()
    project = _make_project("sbgl", "设备管理")
    state = FakeState()
    dispatch, calls = _recording_dispatch()

    results = await asyncio.gather(
        reqsession.ensure_req_session(state, project, ws, dispatch=dispatch),
        reqsession.ensure_req_session(state, project, ws, dispatch=dispatch),
    )

    assert sorted(r["created"] for r in results) == [False, True]
    assert len(calls) == 1
    assert {r["slotKey"] for r in results} == {reqsession.slot_key("sbgl")}
    # the loser still records the prompt as sent, so a third open stays silent
    assert projects.get_project("sbgl")["reqSessionStarted"] is True
    # and the in-flight mark is not left behind to poison the next restart-free open
    assert reqsession._starting == set()


@pytest.mark.asyncio
async def test_missing_project_record_is_404(home, tmp_path):
    state = FakeState()
    dispatch, _calls = _recording_dispatch()

    with pytest.raises(reqsession.ReqSessionError) as exc:
        await reqsession.ensure_req_session(
            state, {"id": "gone", "name": "gone"}, tmp_path, dispatch=dispatch
        )
    assert (exc.value.code, exc.value.status) == ("project_not_found", 404)


# ---------------------------------------------------------------------------
# route
# ---------------------------------------------------------------------------


def _make_app(monkeypatch, enabled=True, state=None):
    monkeypatch.setattr(routes, "is_app_enabled", lambda _name: enabled)
    app = web.Application()
    app["state"] = state if state is not None else FakeState()
    routes.register_routes(app)
    return app


@pytest.mark.asyncio
async def test_route_opens_the_session(home, monkeypatch, tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    project = _make_project("sbgl", "设备管理", workspace=ws)
    state = FakeState()
    dispatch, calls = _recording_dispatch()
    monkeypatch.setattr(reqsession, "_dispatch_turn", dispatch)
    assert project["id"] == "sbgl"

    async with TestClient(TestServer(_make_app(monkeypatch, state=state))) as client:
        resp = await client.post("/api/apps/ai-studio/projects/sbgl/req-session")
        assert resp.status == 200
        body = await resp.json()
        assert body == {"slotKey": "ai-studio-req-sbgl", "created": True}
        assert state.slots["ai-studio-req-sbgl"].project == str(ws)
        assert state.slots["ai-studio-req-sbgl"].title == "需求：设备管理"
        assert len(calls) == 1

        # idempotent: the second call is a re-mount, not a second opening prompt
        resp = await client.post("/api/apps/ai-studio/projects/sbgl/req-session")
        assert resp.status == 200
        assert await resp.json() == {"slotKey": body["slotKey"], "created": False}
        assert len(calls) == 1


@pytest.mark.asyncio
async def test_route_errors(home, monkeypatch, tmp_path):
    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        resp = await client.post("/api/apps/ai-studio/projects/no-such/req-session")
        assert resp.status == 404
        assert (await resp.json())["code"] == "project_not_found"

        # the project exists but its recorded workspace does not: opening a
        # session there would chat about requirements it can neither read nor
        # write, so it is a 409 before a slot is created at all
        _make_project("sbgl", "设备管理", workspace=tmp_path / "gone")
        resp = await client.post("/api/apps/ai-studio/projects/sbgl/req-session")
        assert resp.status == 409
        assert (await resp.json())["code"] == "workspace_missing"


@pytest.mark.asyncio
async def test_route_disabled_403(home, monkeypatch):
    async with TestClient(TestServer(_make_app(monkeypatch, enabled=False))) as client:
        resp = await client.post("/api/apps/ai-studio/projects/sbgl/req-session")
        assert resp.status == 403
        assert (await resp.json())["code"] == "app_disabled"
