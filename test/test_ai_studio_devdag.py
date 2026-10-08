"""Tests for the AI Studio dev-run scheduler (ACP-2085-S4 step 2).

Every outer world sits behind an injected seam — the turn dispatcher, ``git``,
the clock — and the dashboard session layer is a fake state object, because a
real :func:`devdag.dispatch_and_read` would spawn an ACP harness and let an
agent write code into a real repo (testing-conventions: no test may spawn a
real child or touch the host). The loop's own trust grant is monkeypatched —
what the loop tests own is *whether* and *how often* it happens (that is what
``AI_STUDIO_DEV_TRUST`` decides) — while :func:`devdag.grant_trust` itself is
asserted against the dashboard's real trust branch further down.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from kiro_crew.apps.builtins.ai_studio.backend import (
    devdag,
    devplan,
    projects,
    requirements,
    routes,
)

PAGES = ["设备点检记录", "备件台账"]
IDS = ["设备点检记录:api", "设备点检记录:web", "备件台账:api", "备件台账:web"]
SLOT_NAMES = [f"ai-studio-dev-p0101-{i + 1}" for i in range(4)]


class FakeSlot:
    """A slot that records every attribute assignment it receives.

    ``_ChatSlot.unattended`` is a read-only property on the real class
    (``dashboard/state.py:4251``, derived from ``_app``), so "does not set
    unattended" can only be pinned by watching assignments — a fake carrying a
    plain ``unattended`` field would keep passing even if the code assigned to
    it (which on the real slot raises AttributeError mid-run).
    """

    _RECORDED_SKIP = frozenset({"key", "messages", "assigned"})

    def __init__(self, key: str) -> None:
        object.__setattr__(self, "key", key)
        object.__setattr__(self, "messages", [])
        object.__setattr__(self, "assigned", [])
        self.project = ""
        self.title = ""

    def __setattr__(self, name: str, value: Any) -> None:
        if name not in self._RECORDED_SKIP:
            self.assigned.append(name)
        object.__setattr__(self, name, value)


class FakeSessions:
    def __init__(self) -> None:
        self.policies: dict[str, str] = {}

    def set_approval_policy(self, key: str, policy: str) -> None:
        self.policies[key] = policy


class FakeState:
    def __init__(self) -> None:
        self._slots: dict[str, FakeSlot] = {}
        self.sessions = FakeSessions()

    def get_or_create_slot(self, name: str = "", app: str = "", **_kw: Any) -> FakeSlot:
        existing = self._slots.get(name)
        if existing is not None:
            return existing
        slot = FakeSlot(name)
        slot._app = app
        self._slots[name] = slot
        return slot


class FakeGit:
    """HEAD that advances whenever a turn "commits"."""

    def __init__(self) -> None:
        self.head = "c0"
        self.commits = 0

    def __call__(self) -> str:
        return self.head

    def commit(self) -> None:
        self.commits += 1
        self.head = f"c{self.commits}"


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    req = tmp_path / requirements.REQ_DIR
    req.mkdir(parents=True)
    for page in PAGES:
        (req / f"{page}.json").write_text(
            json.dumps({"page": page}, ensure_ascii=False), encoding="utf-8"
        )
    return tmp_path


class Harness:
    """One DevRun plus the fakes it drives, and the knobs a test flips."""

    def __init__(self, ws: Path) -> None:
        self.state = FakeState()
        self.git = FakeGit()
        self.calls: list[tuple[str, str]] = []
        # node title -> reply text; default 完成
        self.replies: dict[str, str] = {}
        # slot keys whose turn commits nothing
        self.no_commit: set[str] = set()
        self.dispatcher_block: asyncio.Event | None = None

        async def dispatch(_state: Any, slot: Any, prompt: str) -> str:
            self.calls.append((str(slot.key), prompt))
            if self.dispatcher_block is not None:
                await self.dispatcher_block.wait()
            if str(slot.key) not in self.no_commit:
                self.git.commit()
            return self.replies.get(str(slot.title), "完成")

        self.run = devdag.DevRun(
            self.state,
            {"id": "p0101", "name": "设备管理"},
            ws,
            dispatcher=dispatch,
            git=self.git,
            clock=lambda: 100.0,
        )

    async def finish(self) -> None:
        assert self.run._loop_task is not None
        await self.run._loop_task


@pytest.fixture()
def h(ws: Path, monkeypatch) -> Harness:
    monkeypatch.delenv(devdag.TRUST_ENV, raising=False)
    return Harness(ws)


@pytest.mark.asyncio
async def test_four_nodes_run_in_plan_order_and_the_run_completes(h: Harness):
    started = await h.run.start(PAGES)
    assert started["phase"] == "full"
    assert started["runId"]
    await h.finish()

    dag = h.run.get()
    assert dag["runState"] == "done"
    assert [n["jiraKey"] for n in dag["nodes"]] == IDS
    assert [n["state"] for n in dag["nodes"]] == ["done"] * 4
    # one session per task, in plan order
    assert [key for key, _ in h.calls] == SLOT_NAMES
    for slot in h.state._slots.values():
        assert slot.project == str(h.run.ws)
        assert slot.title.startswith("开发：")
        # 不设 unattended：那套会把批准静默掉，这里只走「信任会话」一条路
        assert "unattended" not in slot.assigned
    # the board and the agent read the same prompt
    assert h.calls[0][1] == devplan.task_prompt("设备点检记录", "api")
    assert h.calls[1][1] == devplan.task_prompt("设备点检记录", "web")
    # AI_STUDIO_DEV_TRUST unset → the trust path never ran
    assert h.state.sessions.policies == {}
    for node in dag["nodes"]:
        assert node["endCommit"] != node["startCommit"]


@pytest.mark.asyncio
async def test_second_start_while_running_is_refused_with_409(h: Harness):
    h.dispatcher_block = asyncio.Event()
    await h.run.start(PAGES)
    with pytest.raises(devdag.DevDagError) as exc:
        await h.run.start(PAGES)
    assert (exc.value.code, exc.value.status) == ("run_active", 409)
    # still one run, and the refusal wrote nothing
    assert h.run.get()["runState"] == "running"
    h.dispatcher_block.set()
    await h.finish()
    assert h.run.get()["runState"] == "done"


@pytest.mark.asyncio
async def test_a_node_that_commits_nothing_fails_and_stops_the_run(h: Harness):
    h.no_commit = {SLOT_NAMES[1]}
    await h.run.start(PAGES)
    await h.finish()

    dag = h.run.get()
    assert dag["runState"] == "failed"
    # 不许假全绿：后继保持排队
    assert [n["state"] for n in dag["nodes"]] == ["done", "failed", "queued", "queued"]
    assert dag["nodes"][1]["message"] == "回复说完成了，但没有新提交"
    assert len(h.calls) == 2


@pytest.mark.asyncio
async def test_restart_after_failure_resumes_from_the_failed_node(h: Harness):
    h.no_commit = {SLOT_NAMES[1]}
    await h.run.start(PAGES)
    await h.finish()
    assert h.run.get()["runState"] == "failed"
    assert [key for key, _ in h.calls] == SLOT_NAMES[:2]

    h.no_commit = set()
    await h.run.start(PAGES)
    await h.finish()

    dag = h.run.get()
    assert dag["runState"] == "done"
    assert [n["state"] for n in dag["nodes"]] == ["done"] * 4
    # slot names are per node index, so this list says exactly which nodes ran:
    # node 1 is still done and was never dispatched a second time, while node 2
    # (the failed one) ran again.
    assert [key for key, _ in h.calls] == [
        SLOT_NAMES[0],
        SLOT_NAMES[1],  # round 1: node 2 fails for want of a commit
        SLOT_NAMES[1],
        SLOT_NAMES[2],
        SLOT_NAMES[3],  # round 2: resumes AT node 2
    ]


@pytest.mark.asyncio
async def test_trust_grant_follows_the_env_switch(ws: Path, monkeypatch):
    grants: list[str] = []
    monkeypatch.setattr(devdag, "grant_trust", lambda _s, slot: grants.append(str(slot.key)))

    monkeypatch.delenv(devdag.TRUST_ENV, raising=False)
    off = Harness(ws)
    await off.run.start(PAGES)
    await off.finish()
    assert grants == []

    monkeypatch.setenv(devdag.TRUST_ENV, "1")
    on = Harness(ws)
    await on.run.start(PAGES)
    await on.finish()
    assert grants == SLOT_NAMES


@pytest.mark.asyncio
async def test_a_failure_reply_becomes_the_node_message(h: Harness):
    h.replies["开发：设备点检记录：前端页面"] = "我先看一下\n失败：单测没过"
    await h.run.start(PAGES)
    await h.finish()

    dag = h.run.get()
    assert dag["runState"] == "failed"
    assert [n["state"] for n in dag["nodes"]] == ["done", "failed", "queued", "queued"]
    assert dag["nodes"][1]["message"] == "失败：单测没过"


@pytest.mark.asyncio
async def test_a_timed_out_turn_fails_with_the_timeout_message(h: Harness):
    async def hang(_state: Any, _slot: Any, _prompt: str) -> str:
        raise devdag._TurnTimeout()

    h.run._dispatch = hang  # type: ignore[method-assign]
    await h.run.start(PAGES)
    await h.finish()

    dag = h.run.get()
    assert dag["runState"] == "failed"
    assert dag["nodes"][0]["state"] == "failed"
    assert dag["nodes"][0]["message"] == "超时"
    assert [n["state"] for n in dag["nodes"][1:]] == ["queued"] * 3


def test_get_without_a_state_file_is_idle(ws: Path):
    run = devdag.DevRun(FakeState(), {"id": "p"}, ws, git=lambda: "c", clock=lambda: 1.0)
    assert run.get() == {"runState": "idle", "nodes": []}
    assert run.log_lines(10) == []


@pytest.mark.asyncio
async def test_a_running_file_with_no_loop_in_this_process_reads_as_failed(ws: Path, h: Harness):
    """The gateway restarted mid-run: the file says running, nothing is running.

    The loop is parked INSIDE node 1's turn (``dispatcher_block``) so the file
    genuinely holds ``runState=running`` with a node in ``running`` — that is the
    exact shape a restart leaves behind — and then this process stops owning the
    task, which is all a restart means for the state file.
    """
    h.dispatcher_block = asyncio.Event()
    await h.run.start(PAGES)
    for _ in range(20):
        if h.run._data()["nodes"][0]["state"] == "running":
            break
        await asyncio.sleep(0)
    assert h.run.get()["runState"] == "running"

    parked = h.run._loop_task
    assert parked is not None
    h.run._loop_task = None  # this process does not own the loop any more
    try:
        dag = h.run.get()
        assert dag["runState"] == "failed"
        assert dag["nodes"][0]["state"] == "failed"
        assert dag["nodes"][0]["message"] == "网关重启，中断"
        # the never-started successors stay queued: they were not interrupted
        assert [n["state"] for n in dag["nodes"][1:]] == ["queued"] * 3
        # durable, not a per-read guess: a brand-new DevRun on the same workspace
        # (what the gateway builds after a restart) reads the same verdict
        assert devdag.DevRun(FakeState(), {}, ws, git=lambda: "c").get()["runState"] == "failed"
    finally:
        h.dispatcher_block.set()
        parked.cancel()
        with pytest.raises(asyncio.CancelledError):
            await parked


def test_log_appends_one_line_per_event(h: Harness):
    h.run._log("node start", IDS[0])
    h.run._log("done commit=c1", IDS[0])
    assert events(h.run, 100) == [
        f"node start {IDS[0]}",
        f"done commit=c1 {IDS[0]}",
    ]
    # ?lines=N asks for the N most recent, oldest first
    assert events(h.run, 1) == [f"done commit=c1 {IDS[0]}"]


def events(run: devdag.DevRun, lines: int) -> list[str]:
    """Log lines minus their leading timestamp (the clock is faked, so the
    timestamp is a constant the assertions above do not care about)."""
    return [ln.split(" ", 1)[1] for ln in run.log_lines(lines)]


@pytest.mark.asyncio
async def test_a_loop_exception_lands_in_the_state_file(ws: Path, monkeypatch):
    """A crash inside the loop must not leave the board spinning.

    Awaiting the task is NOT the assertion: ``_run_safe`` consumes the
    exception on purpose (an unretrieved task error is invisible in a running
    gateway). The assertion is the state file, which only the guard writes.
    """

    async def boom() -> None:
        raise RuntimeError("loop blew up")

    h = Harness(ws)
    monkeypatch.delenv(devdag.TRUST_ENV, raising=False)
    h.run._loop = boom  # type: ignore[method-assign]
    await h.run.start(PAGES)
    await h.finish()
    assert h.run.get()["runState"] == "failed"
    assert any("loop crashed" in ln for ln in h.run.log_lines(100))


# ---------------------------------------------------------------------------
# the 信任会话 grant: the same three things the dashboard's trust branch does
# ---------------------------------------------------------------------------


class SelSpy:
    """The SEL singleton, replaced so the test asserts the audit instead of writing one."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def log_api_access(self, **kw: Any) -> None:
        self.calls.append(kw)


@pytest.fixture()
def sel_spy(monkeypatch):
    import kiro_crew.sel as sel_module

    spy = SelSpy()
    monkeypatch.setattr(sel_module, "sel", lambda: spy)
    return spy


def test_grant_trust_does_what_the_web_trust_button_does(sel_spy: SelSpy):
    """The ticket's 「照它调」, asserted rather than asserted-about.

    ``dashboard.chat_handlers.api_chat_mode``'s ``mode == "trust"`` branch
    (:11769) is the web 〔信任会话〕 button, and :func:`devdag.grant_trust` is a
    copy of its three durable effects: every slot on the SAME session gets
    ``_trust``, ``sessions.set_approval_policy(key, "auto")`` (what subagents
    read — the in-memory set alone does not reach them), and one SEL audit line.
    A regression here silently puts an approval prompt back in front of the
    serial queue, where it wedges the whole run until the per-turn timeout.
    """
    from kiro_crew.dashboard.chat_utils import effective_session_key

    state = FakeState()
    mine = state.get_or_create_slot(name="ai-studio-dev-p0101-1", app="ai-studio")
    sharing = state.get_or_create_slot(name="web:1234", app="")
    sharing.linked_session_key = effective_session_key(mine)  # same session, other slot
    other = state.get_or_create_slot(name="web:9999", app="")

    devdag.grant_trust(state, mine)

    assert mine._trust is True and sharing._trust is True
    assert not hasattr(other, "_trust")
    key = effective_session_key(mine)
    assert state.sessions.policies == {key: "auto"}
    assert len(sel_spy.calls) == 1
    audit = sel_spy.calls[0]
    assert audit["operation"] == "mode_change:trust" and audit["outcome"] == "enabled"
    assert audit["caller"] == "ai-studio:dev"


def test_grant_trust_survives_a_slot_it_cannot_key_and_a_dead_audit(ws: Path, monkeypatch):
    """The grant is the point; a broken audit trail must not walk it back.

    A slot whose session key cannot be computed sits in the same dict — it must
    not stop the grant — and a SEL failure is logged, not raised: a run that
    got its approvals opened but reports failure is the more dangerous of the
    two readings.
    """
    import kiro_crew.sel as sel_module

    state = FakeState()
    slot = state.get_or_create_slot(name="ai-studio-dev-p0101-1", app="ai-studio")
    state._slots["junk"] = object()  # no .key at all: effective_session_key raises

    def boom(**_kw: Any) -> None:
        raise RuntimeError("sel down")

    monkeypatch.setattr(sel_module, "sel", lambda: type("X", (), {"log_api_access": boom})())
    devdag.grant_trust(state, slot)
    assert slot._trust is True
    assert state.sessions.policies[f"dashboard:{slot.key}"] == "auto"


# ---------------------------------------------------------------------------
# the five routes (ACP-2085-S4 §4)


class FakeRun:
    """Stands in for :class:`devdag.DevRun` at the seam the routes use."""

    def __init__(self, state: dict[str, Any] | None = None, error: Exception | None = None) -> None:
        self._state = {"runState": "idle", "nodes": []} if state is None else state
        self.error = error
        self.started: list[list[str]] = []
        self.log_requests: list[int] = []

    def get(self) -> dict[str, Any]:
        return self._state

    async def start(self, pages: list[str]) -> dict[str, Any]:
        self.started.append(pages)
        if self.error is not None:
            raise self.error
        return {"runId": "dev-1", "phase": "full"}

    def log_lines(self, lines: int) -> list[str]:
        self.log_requests.append(lines)
        return ["… start dev-1", "… node start 设备点检记录:api"]


def verdicts(*pairs: tuple[str, str]) -> list[dict[str, Any]]:
    return [
        {
            "page": page,
            "verdict": verdict,
            "missingCount": 0,
            "graphHash": "0" * 16,
            "updatedAt": "2026-10-08T10:00:00+08:00",
        }
        for page, verdict in pairs
    ]


@pytest.fixture()
def route_env(tmp_path, monkeypatch):
    """A real project record whose workspace is a tmp dir, and the route app.

    Real on purpose down to ``projects.get_project``: the workspace the run
    writes into is resolved from ``project.json`` by the route itself, so
    pointing that at tmp_path is what makes ``.ai-studio/`` land in the test.
    """
    home = tmp_path / "crew"
    home.mkdir()
    monkeypatch.setenv("KIROCREW_HOME", str(home))
    # the per-gateway DevRun cache is a process global: a test that fills it must
    # not hand its instance to the next one
    monkeypatch.setattr(routes, "_DEV_RUNS", {})
    ws = tmp_path / "ws"
    (ws / requirements.REQ_DIR).mkdir(parents=True)
    record = projects.create_project("设备管理", "")
    path = projects.projects_root() / record["id"] / "project.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["workspaceDir"] = str(ws)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    app = web.Application()
    app["state"] = FakeState()  # a dev task IS a chat session: the route needs a state
    monkeypatch.setattr(routes, "is_app_enabled", lambda _name: True)
    routes.register_routes(app)
    return record["id"], ws, app


@pytest.mark.asyncio
async def test_dev_start_route_schedules_exactly_the_pages_the_verdicts_allow(
    route_env, monkeypatch
):
    pid, _ws, app = route_env
    monkeypatch.setattr(
        requirements,
        "list_pages",
        lambda _ws: verdicts(
            ("设备点检记录", "全齐"), ("备件台账", "可以开工但有已知缺口"), ("设备维修记录", "不齐")
        ),
    )
    fake = FakeRun()
    monkeypatch.setattr(routes, "_dev_run_for", lambda *a, **k: fake)
    async with TestClient(TestServer(app)) as client:
        r = await client.post(f"/api/apps/ai-studio/projects/{pid}/dev/start", json={})
        assert r.status == 202
        assert await r.json() == {"runId": "dev-1", "phase": "full"}
    # a 可以开工但有已知缺口 page carries a RECORDED gap, not a blocker; 齐否 is
    # the only gate. An unqualified page is never scheduled by omission either.
    assert fake.started == [["设备点检记录", "备件台账"]]


@pytest.mark.asyncio
async def test_dev_start_route_refuses_an_unready_or_unknown_page(route_env, monkeypatch):
    pid, _ws, app = route_env
    monkeypatch.setattr(
        requirements,
        "list_pages",
        lambda _ws: verdicts(("设备点检记录", "不齐"), ("备件台账", "不齐")),
    )
    fake = FakeRun()
    monkeypatch.setattr(routes, "_dev_run_for", lambda *a, **k: fake)
    async with TestClient(TestServer(app)) as client:
        # named pages are an explicit choice, so 422 says which ones — the board
        # marks them all in one pass instead of one round trip per page
        r = await client.post(
            f"/api/apps/ai-studio/projects/{pid}/dev/start",
            json={"pages": ["设备点检记录", "备件台账"]},
        )
        assert r.status == 422
        body = await r.json()
        assert body["code"] == "not_ready"
        assert "设备点检记录" in body["error"] and "备件台账" in body["error"]

        r = await client.post(
            f"/api/apps/ai-studio/projects/{pid}/dev/start", json={"pages": ["不存在的页"]}
        )
        assert r.status == 404
        assert (await r.json())["code"] == "page_not_found"

        # a workspace whose graph is empty has no task to schedule: starting a run
        # over zero nodes would answer 202 and do nothing
        monkeypatch.setattr(requirements, "list_pages", lambda _ws: [])
        r = await client.post(f"/api/apps/ai-studio/projects/{pid}/dev/start", json={})
        assert r.status == 422
        assert (await r.json())["code"] == "no_pages"

        r = await client.post("/api/apps/ai-studio/projects/p-nope/dev/start", json={})
        assert r.status == 404
        assert (await r.json())["code"] == "project_not_found"
    assert fake.started == []


@pytest.mark.asyncio
async def test_dev_start_route_maps_the_run_refusal_and_the_missing_state(route_env, monkeypatch):
    pid, _ws, app = route_env
    monkeypatch.setattr(requirements, "list_pages", lambda _ws: verdicts(("设备点检记录", "全齐")))
    monkeypatch.setattr(
        routes,
        "_dev_run_for",
        lambda *a, **k: FakeRun(error=devdag.DevDagError("already running", "run_active", 409)),
    )
    async with TestClient(TestServer(app)) as client:
        r = await client.post(f"/api/apps/ai-studio/projects/{pid}/dev/start", json={})
        assert r.status == 409
        assert await r.json() == {"error": "already running", "code": "run_active"}

    # without a chat state there is nothing to open a session on; saying 503 beats
    # starting a run whose first node can never start
    app_without_state = web.Application()
    monkeypatch.setattr(routes, "is_app_enabled", lambda _name: True)
    routes.register_routes(app_without_state)
    async with TestClient(TestServer(app_without_state)) as client:
        r = await client.post(f"/api/apps/ai-studio/projects/{pid}/dev/start", json={})
        assert r.status == 503
        assert (await r.json())["code"] == "state_unavailable"


@pytest.mark.asyncio
async def test_dev_dag_and_log_routes_pass_state_and_log_through(route_env, monkeypatch):
    pid, _ws, app = route_env
    state = {
        "runId": "dev-1",
        "phase": "full",
        "runState": "running",
        "nodes": [{"jiraKey": "设备点检记录:api", "state": "done", "message": ""}],
    }
    fake = FakeRun(state=state)
    monkeypatch.setattr(routes, "_dev_run_for", lambda *a, **k: fake)
    async with TestClient(TestServer(app)) as client:
        r = await client.get(f"/api/apps/ai-studio/projects/{pid}/dev/dag")
        assert r.status == 200
        # verbatim: the board's 3s poll and the failure-resume path both read this
        assert await r.json() == state

        r = await client.get(f"/api/apps/ai-studio/projects/{pid}/dev/log?lines=7")
        assert r.status == 200 and len((await r.json())["lines"]) == 2

        r = await client.get(f"/api/apps/ai-studio/projects/{pid}/dev/log?lines=abc")
        assert r.status == 200
    # a garbage lines= degrades to the route's own default, not to a 500
    assert fake.log_requests == [7, 100]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "m,path",
    [
        ("post", "/dev/start"),
        ("get", "/dev/dag"),
        ("get", "/dev/log"),
        ("post", "/accept/run"),
        ("get", "/accept/records"),
    ],
)
async def test_every_dev_route_is_closed_while_the_app_is_disabled(tmp_path, monkeypatch, m, path):
    home = tmp_path / "crew"
    home.mkdir()
    monkeypatch.setenv("KIROCREW_HOME", str(home))
    record = projects.create_project("设备管理", "")
    app = web.Application()
    app["state"] = FakeState()
    monkeypatch.setattr(routes, "is_app_enabled", lambda _name: False)
    routes.register_routes(app)
    async with TestClient(TestServer(app)) as client:
        r = await getattr(client, m)(f"/api/apps/ai-studio/projects/{record['id']}{path}")
        assert r.status == 403
        assert (await r.json())["code"] == "app_disabled"


@pytest.mark.asyncio
async def test_an_interrupted_node_resumes_alone_and_the_run_completes(ws: Path, monkeypatch):
    """Acceptance 4's second half: interrupt, then resume — that one node only.

    The injected crash sits BETWEEN the turn committing code and the board
    writing the node down, which is exactly what a gateway restart leaves: the
    code is on disk, the board still believes the node is mid-flight. So the
    assertions are about the sessions, not about the board agreeing with reality
    — the first round dispatches ONE turn and dies with that node still
    ``running``, and the second round re-dispatches exactly that node and then
    walks the rest, so the turn count is 1 + 4 and the slot names say which node
    each of them was.
    """
    monkeypatch.delenv(devdag.TRUST_ENV, raising=False)
    state = FakeState()
    git = FakeGit()
    turns: list[str] = []

    async def dispatch(_state: Any, slot: Any, prompt: str) -> str:
        turns.append(f"{slot.key}|{prompt}")
        git.commit()
        return "完成"

    run = devdag.DevRun(
        state,
        {"id": "p0101", "name": "设备管理"},
        ws,
        dispatcher=dispatch,
        git=git,
        clock=lambda: 100.0,
        fail_point=f"after-dispatch:{IDS[0]}",
    )
    first = await run.start(PAGES)
    # the injected crash escapes the loop and is swallowed by the wrapper, which
    # is what a restart looks like from the outside: the task ends, the file does
    # not know why
    await run._loop_task

    broken = run.get()
    assert broken["runState"] == "failed"
    # the interrupted node is failed with a reason, its successor never ran
    assert [n["state"] for n in broken["nodes"]] == ["failed", "queued", "queued", "queued"]
    assert broken["nodes"][0]["message"] == "网关重启，中断"
    # the code really did land before the crash: the turn dispatched and committed
    assert len(turns) == 1
    assert broken["nodes"][0]["endCommit"] == ""

    run.fail_point = ""
    second = await run.start(PAGES)
    await run._loop_task

    dag = run.get()
    assert dag["runState"] == "done"
    assert [n["state"] for n in dag["nodes"]] == ["done"] * 4
    # the interrupted node is the ONLY one dispatched twice: slot 1 got a second
    # turn, every other slot got exactly one
    assert [t.split("|")[0] for t in turns] == [
        SLOT_NAMES[0],  # round 1, interrupted after its commit
        SLOT_NAMES[0],  # resumed here
        SLOT_NAMES[1],
        SLOT_NAMES[2],
        SLOT_NAMES[3],
    ]
    assert [t.split("|")[1] for t in turns][1:] == [
        devplan.task_prompt(PAGES[0], "api"),
        devplan.task_prompt(PAGES[0], "web"),
        devplan.task_prompt(PAGES[1], "api"),
        devplan.task_prompt(PAGES[1], "web"),
    ]
    # the node identities survive the resume: one row per task, not one per attempt
    assert [n["jiraKey"] for n in dag["nodes"]] == IDS
    assert first["phase"] == second["phase"] == "full"
