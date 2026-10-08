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
    jirasync,
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


# ── ACP-2085-S6：先拆任务、后开发，Jira 跟着流转 ───────────────────────────
#
# The scheduler's half of the Jira story. A real :mod:`jirasync` call is a
# subprocess against an internal Jira, so the seam is the module's own functions
# (:meth:`DevRun._jira` looks them up by name on the module at call time, which
# is exactly what makes monkeypatching them the test's whole lever here).


@pytest.fixture(autouse=True)
def no_ambient_jira(monkeypatch):
    """Never let the deployment's own ``AI_STUDIO_JIRA_*`` settings reach a test.

    A gateway host that syncs Jira has these set, and an unset-vs-set reading
    here is the difference between a test that plans 4 nodes and one that forks
    a real ``jc`` and files real issues (testing-conventions: a test may not
    touch the host or spawn a real child).
    """
    for name in (
        "AI_STUDIO_JIRA_CMD",
        "AI_STUDIO_JIRA_PROJECT",
        "AI_STUDIO_JIRA_BROWSE",
        "AI_STUDIO_JIRA_DOING",
        "AI_STUDIO_JIRA_DONE",
    ):
        monkeypatch.delenv(name, raising=False)


class JiraSpy:
    """The five command-shaped functions of :mod:`jirasync`, recorded.

    ``fail`` switches every call to the "command broke" answer (``(None, text)``
    / a non-empty error) without touching the scheduler: that is scenario 8,
    where the round must still run to completion and only the node's
    ``jiraError`` carries the reason.
    """

    def __init__(self) -> None:
        self.parent_calls = 0
        self.created: list[tuple[str, str, str]] = []
        self.transitions: list[tuple[str, str]] = []
        self.comments: list[tuple[str, str]] = []
        self.fail = False
        self._next = 9001

    def install(self, monkeypatch) -> "JiraSpy":
        monkeypatch.setattr(jirasync, "ensure_parent_checked", self._parent)
        monkeypatch.setattr(jirasync, "create_task_checked", self._create)
        monkeypatch.setattr(jirasync, "transition_checked", self._transition)
        monkeypatch.setattr(jirasync, "comment_checked", self._comment)
        return self

    def _parent(self, _project: dict[str, Any]) -> tuple[str | None, str]:
        self.parent_calls += 1
        if self.fail:
            return None, "jc 连不上 jira"
        return "ACP-8000", ""

    def _create(self, parent: str, title: str, code: str) -> tuple[str | None, str]:
        self.created.append((parent, title, code))
        if self.fail:
            return None, "建单失败"
        self._next += 1
        return f"ACP-{self._next}", ""

    def _transition(self, key: str, to: str) -> str:
        self.transitions.append((key, to))
        return "流转不动" if self.fail else ""

    def _comment(self, key: str, text: str) -> str:
        self.comments.append((key, text))
        return "评论失败" if self.fail else ""


@pytest.fixture()
def jira(monkeypatch) -> JiraSpy:
    """A spying Jira behind the run (env stays unset: the spy replaces the
    functions themselves, so nothing here can fork a subprocess)."""
    spy = JiraSpy().install(monkeypatch)
    monkeypatch.delenv(devdag.TRUST_ENV, raising=False)
    return spy


def _nodes_by_key(dag: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(n["jiraKey"]): n for n in dag["nodes"]}


@pytest.mark.asyncio
async def test_plan_creates_one_issue_per_task_and_runs_nothing(ws: Path, jira: JiraSpy):
    """5：plan → runState=planned、四个节点都有 Jira 号和链接，且一个节点都没跑。

    「没开始跑」断的是 dispatcher 一次没被调 + 状态文件里没有 running：拆任务和
    开工必须两件事，否则这个按钮就只是〔开始开发〕换了个名字。
    """
    h = Harness(ws)
    dag = await h.run.plan(PAGES)

    assert dag["runState"] == "planned"
    assert [n["jiraKey"] for n in dag["nodes"]] == IDS
    for node in dag["nodes"]:
        assert node["state"] == "queued"
        assert node["jira"]
        assert node["jira"] not in (node["jiraKey"], None)
        assert node["jiraUrl"] == f"https://jira.jereh.cn/browse/{node['jira']}"
        assert node.get("jiraError", "") == ""
    assert dag["jiraParent"] == "ACP-8000"
    assert dag["jiraParentUrl"] == "https://jira.jereh.cn/browse/ACP-8000"
    # 父单一次，子单四个，标题就是任务标题
    assert jira.parent_calls == 1
    assert [t for _p, t, _c in jira.created] == [
        devplan.task_title(p, k) for p in PAGES for k in ("api", "web")
    ]
    assert {c for *_x, c in jira.created} == {"p0101"}
    # 没派活：没有会话，看板上一行都没动
    assert h.calls == []
    assert h.state._slots == {}
    assert h.run.get()["runState"] == "planned"


@pytest.mark.asyncio
async def test_plan_twice_with_the_same_pages_creates_no_second_batch(ws: Path, jira: JiraSpy):
    """页面集合没变 = 原样返回：再点〔拆分任务〕不长出第二套 Jira 子单。"""
    h = Harness(ws)
    first = await h.run.plan(PAGES)
    created = list(jira.created)
    again = await h.run.plan(PAGES)

    assert [n["jira"] for n in again["nodes"]] == [n["jira"] for n in first["nodes"]]
    assert jira.created == created
    assert jira.parent_calls == 1


@pytest.mark.asyncio
async def test_plan_with_new_pages_keeps_done_work_and_voids_the_rest(ws: Path, jira: JiraSpy):
    """页面集合变了：done 的节点连号带提交一起留下，被挤掉的没做完的老单作废。

    「作废」是评论 + 置完成两件事，都断：只评论 = 单子还挂在待办里；只流转 = Jira
    里没人知道它为什么完成了。方向是**减页**（加页不会挤掉任何任务，也就没有作废）。
    """
    h = Harness(ws)
    await h.run.plan(PAGES)
    old_keys = [n["jira"] for n in h.run.get()["nodes"]]
    # 手动记两行已交付（真跑一轮要 40 分钟，这里要验的是搬不搬、作废谁）：
    # 第一页的 api 还在新计划里，第二页的 api 会随页一起掉出去。
    stored = h.run._data()
    for index in (0, 2):
        stored["nodes"][index]["state"] = "done"
        stored["nodes"][index]["endCommit"] = f"abc{index}234567890"
    h.run._save(stored)

    dag = await h.run.plan([PAGES[0]])

    by_key = _nodes_by_key(dag)
    assert by_key[IDS[0]]["state"] == "done"
    assert by_key[IDS[0]]["endCommit"] == "abc0234567890"
    assert by_key[IDS[0]]["jira"] == old_keys[0], "已交付的任务不许重开单"
    # 掉出去的那一页：交付过的行留在看板上（代码已经提交在工作区里了）
    assert by_key[IDS[2]]["state"] == "done"
    assert by_key[IDS[2]]["jira"] == old_keys[2]
    # 没交付又不要了的那一张（第二页 web）：评论 + 置完成
    assert jira.comments == [(old_keys[3], "计划已重做，此单作废")]
    assert jira.transitions == [(old_keys[3], jirasync.done_state())]
    # 一次都不重开单：留下的行用的还是原来的号（作废那一张已从看板移除）
    assert sorted(n["jira"] for n in dag["nodes"]) == sorted(old_keys[:3])
    assert [n["jiraKey"] for n in dag["nodes"]] == [IDS[0], IDS[1], IDS[2]]


@pytest.mark.asyncio
async def test_planned_survives_a_restart_unlike_running(ws: Path, jira: JiraSpy):
    """网关重启后 ``planned`` 不许被孤儿判断判成失败（planned 不是在跑）。"""
    h = Harness(ws)
    await h.run.plan(PAGES)
    assert h.run._loop_task is None  # plan 不起循环，这就是「重启后」的形态

    fresh = devdag.DevRun(FakeState(), {"id": "p0101"}, ws, git=lambda: "c")
    dag = fresh.get()
    assert dag["runState"] == "planned"
    assert [n["state"] for n in dag["nodes"]] == ["queued"] * 4
    # 父单链接是读的时候算的：一个新 DevRun、连项目记录都没带，照样给得出
    assert dag["jiraParentUrl"] == "https://jira.jereh.cn/browse/ACP-8000"


@pytest.mark.asyncio
async def test_start_after_plan_runs_the_planned_nodes_and_transitions_jira(
    ws: Path, jira: JiraSpy
):
    """6：plan 后 start → 节点依次 running/done，transition 依次被调，done 有评论。

    每个节点都是「先流转到进行中、干完再流转到完成 + 评论提交号」，所以顺序是这一
    条测试的全部内容 —— 反过来（先评论后流转）在 Jira 里看不出这一条何时开工。
    """
    h = Harness(ws)
    await h.run.plan(PAGES)
    keys = [n["jira"] for n in h.run.get()["nodes"]]
    jira.transitions.clear()

    await h.run.start(PAGES)
    await h.finish()

    dag = h.run.get()
    assert dag["runState"] == "done"
    assert [n["state"] for n in dag["nodes"]] == ["done"] * 4
    # 一次没重建：跑的是拆好的那份计划
    assert [n["jira"] for n in dag["nodes"]] == keys
    assert len(jira.created) == 4
    doing, done = jirasync.doing_state(), jirasync.done_state()
    expected: list[tuple[str, str]] = []
    for key in keys:
        expected += [(key, doing), (key, done)]
    assert jira.transitions == expected
    # done 的评论带自己那一节点的提交号（FakeGit 每提交一次头前进一步：c1…c4）
    assert [t for _k, t in jira.comments] == [f"完成，提交 c{i + 1}" for i in range(4)]
    assert [k for k, _t in jira.comments] == keys
    # 跑完照样带得上父单链接
    assert dag["jiraParentUrl"] == "https://jira.jereh.cn/browse/ACP-8000"


@pytest.mark.asyncio
async def test_start_without_a_plan_still_runs_the_old_way(ws: Path, jira: JiraSpy):
    """老行为不变：没有计划直接 start = 自动 plan 一次再跑完。"""
    h = Harness(ws)
    await h.run.start(PAGES)
    await h.finish()
    dag = h.run.get()
    assert dag["runState"] == "done"
    assert [n["state"] for n in dag["nodes"]] == ["done"] * 4
    assert len(jira.created) == 4
    assert h.calls and [k for k, _ in h.calls] == SLOT_NAMES


@pytest.mark.asyncio
async def test_a_failed_node_is_commented_never_closed(ws: Path, jira: JiraSpy):
    """7：失败节点评论「失败：…」，但状态没被流转成完成。

    Jira 里它就该还挂在「进行中」—— 这条活确实没干完。把失败流转成完成会让 Jira
    的看板比这块板更假，而后者才是那一轮实际跑了什么的记录。
    """
    h = Harness(ws)
    h.replies["开发：设备点检记录：前端页面"] = "我先看一下\n失败：单测没过"
    await h.run.plan(PAGES)
    keys = [n["jira"] for n in h.run.get()["nodes"]]
    jira.comments.clear()
    jira.transitions.clear()

    await h.run.start(PAGES)
    await h.finish()

    dag = h.run.get()
    assert dag["runState"] == "failed"
    by_key = _nodes_by_key(dag)
    failed_key = keys[1]
    assert by_key[IDS[1]]["state"] == "failed"
    # 失败节点的评论：原文一句话，挂在它自己那张单上
    fails = [(k, c) for k, c in jira.comments if c.startswith("失败：")]
    assert fails == [(failed_key, "失败：单测没过")]
    # 失败的那一张：只有「进行中」，从来没有「完成」
    assert (failed_key, jirasync.doing_state()) in jira.transitions
    assert (failed_key, jirasync.done_state()) not in jira.transitions
    # 它前面那一张是完整的：进行中 + 完成 + 一条提交号评论
    assert (keys[0], jirasync.done_state()) in jira.transitions
    assert [k for k, c in jira.comments if c.startswith("完成，提交")] == [keys[0]]
    # 后继一个都没派，也就一张单都没流转
    assert not any(k == keys[2] for k, _ in jira.transitions)
    assert by_key[IDS[2]]["state"] == "queued"


@pytest.mark.asyncio
async def test_the_run_completes_when_every_jira_call_fails(ws: Path, jira: JiraSpy):
    """8：Jira 命令全失败，开发照样跑完；每个节点带上错误原文。

    这是整层「失败不抛」的收口测试：Jira 只是记账，记账坏了却把开发停住，是本末
    倒置。断言的是**跑完**（4 个节点全 done、循环正常收口）+ 原因在 ``jiraError``
    上看得见，而不是「没报错」。
    """
    h = Harness(ws)
    jira.fail = True
    plan = await h.run.plan(PAGES)
    assert plan["runState"] == "planned"
    for node in plan["nodes"]:
        assert node["jira"] == ""
        assert node["jiraError"] == "建单失败" or node["jiraError"] == "jc 连不上 jira"

    await h.run.start(PAGES)
    await h.finish()

    dag = h.run.get()
    assert dag["runState"] == "done"
    assert [n["state"] for n in dag["nodes"]] == ["done"] * 4
    # 没号就别去调流转/评论：那只会往 jiraError 上再糊几条看不懂的报错
    assert jira.transitions == []
    assert jira.comments == []


@pytest.mark.asyncio
async def test_a_jira_error_on_a_later_call_lands_on_the_node(ws: Path, jira: JiraSpy):
    """建单成了、流转坏了：号还在（链接照样点得开），原因记到节点上。"""
    h = Harness(ws)
    await h.run.plan(PAGES)
    keys = [n["jira"] for n in h.run.get()["nodes"]]
    jira.fail = True

    await h.run.start(PAGES)
    await h.finish()

    dag = h.run.get()
    assert [n["state"] for n in dag["nodes"]] == ["done"] * 4
    for index, node in enumerate(dag["nodes"]):
        assert node["jira"] == keys[index]
        assert node["jiraError"] == "流转不动"


@pytest.mark.asyncio
async def test_plan_while_running_is_refused_with_409(ws: Path, jira: JiraSpy):
    """9：running 时 plan → 409 run_active，且一份在跑的计划没被改写。"""
    h = Harness(ws)
    h.dispatcher_block = asyncio.Event()
    await h.run.start(PAGES)
    with pytest.raises(devdag.DevDagError) as exc:
        await h.run.plan(PAGES)
    assert (exc.value.code, exc.value.status) == ("run_active", 409)
    assert h.run.get()["runState"] == "running"
    h.dispatcher_block.set()
    await h.finish()
    assert h.run.get()["runState"] == "done"


@pytest.mark.asyncio
async def test_unset_jira_leaves_the_board_clean(ws: Path, monkeypatch):
    """没配 Jira（``AI_STUDIO_JIRA_CMD`` 没设）：节点上没有 jiraError 灰字。

    autouse 的 ``no_ambient_jira`` 已经把环境清干净了，所以这一条走的就是真函数
    ——「可选配置没开」和「配置坏了」在看板上必须是两种长相，否则每个没接 Jira 的
    部署都会看见四个节点挂着一行报错。
    """
    monkeypatch.delenv("AI_STUDIO_JIRA_CMD", raising=False)
    h = Harness(ws)
    dag = await h.run.plan(PAGES)
    assert dag["runState"] == "planned"
    for node in dag["nodes"]:
        assert node["jira"] == ""
        assert node["jiraUrl"] == ""
        assert "jiraError" not in node or node["jiraError"] == ""
    assert "jiraParent" not in dag


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
        self.planned: list[list[str]] = []
        self.log_requests: list[int] = []

    def get(self) -> dict[str, Any]:
        return self._state

    async def start(self, pages: list[str]) -> dict[str, Any]:
        self.started.append(pages)
        if self.error is not None:
            raise self.error
        return {"runId": "dev-1", "phase": "full"}

    async def plan(self, pages: list[str]) -> dict[str, Any]:
        self.planned.append(pages)
        if self.error is not None:
            raise self.error
        return {"runState": "planned", "nodes": [], "jiraParent": "ACP-8000"}

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
async def test_dev_plan_route_splits_the_same_pages_the_verdicts_allow(route_env, monkeypatch):
    """POST dev/plan：页规则与 dev/start 完全一致，且不碰 start（拆 ≠ 跑）。"""
    pid, _ws, app = route_env
    monkeypatch.setattr(
        requirements,
        "list_pages",
        lambda _ws: verdicts(("设备点检记录", "全齐"), ("备件台账", "不齐")),
    )
    fake = FakeRun()
    monkeypatch.setattr(routes, "_dev_run_for", lambda *a, **k: fake)
    async with TestClient(TestServer(app)) as client:
        r = await client.post(f"/api/apps/ai-studio/projects/{pid}/dev/plan", json={})
        assert r.status == 201
        body = await r.json()
        # 返回的就是 plan 自己那份状态：看板拿它直接画，不用猜形状
        assert body["runState"] == "planned"
        assert body["jiraParent"] == "ACP-8000"

        r = await client.post(
            f"/api/apps/ai-studio/projects/{pid}/dev/plan", json={"pages": ["设备点检记录"]}
        )
        assert r.status == 201

        # 指名一个不齐的页 = 422，并把页名说全（和 dev/start 同一条判定）
        r = await client.post(
            f"/api/apps/ai-studio/projects/{pid}/dev/plan",
            json={"pages": ["设备点检记录", "备件台账"]},
        )
        assert r.status == 422
        assert (await r.json())["code"] == "not_ready"

        r = await client.post(f"/api/apps/ai-studio/projects/{pid}/dev/plan", json={})
        assert r.status == 201

    # 三次都只拆到那一页（省略 pages = 判定允许的页；不齐的页永远进不来）
    assert fake.planned == [["设备点检记录"]] * 3
    # 拆任务不启动任何一轮：这一条是「先拆后开」在路由层的边界
    assert fake.started == []


@pytest.mark.asyncio
async def test_dev_plan_route_maps_a_running_refusal_and_an_empty_workspace(route_env, monkeypatch):
    pid, _ws, app = route_env
    monkeypatch.setattr(requirements, "list_pages", lambda _ws: verdicts(("设备点检记录", "全齐")))
    monkeypatch.setattr(
        routes,
        "_dev_run_for",
        lambda *a, **k: FakeRun(error=devdag.DevDagError("already running", "run_active", 409)),
    )
    async with TestClient(TestServer(app)) as client:
        r = await client.post(f"/api/apps/ai-studio/projects/{pid}/dev/plan", json={})
        assert r.status == 409
        assert await r.json() == {"error": "already running", "code": "run_active"}

        # 一个能开工的页都没有：拆不出任务，201 + 空列表是假成功
        monkeypatch.setattr(requirements, "list_pages", lambda _ws: [])
        fake = FakeRun()
        monkeypatch.setattr(routes, "_dev_run_for", lambda *a, **k: fake)
        r = await client.post(f"/api/apps/ai-studio/projects/{pid}/dev/plan", json={})
        assert r.status == 422
        assert (await r.json())["code"] == "no_pages"
    assert fake.planned == []


@pytest.mark.asyncio
async def test_dev_dag_route_adds_the_parent_link_from_the_record(route_env, monkeypatch):
    """GET dev/dag 带得上 jiraParent／jiraParentUrl，哪怕状态文件里还没有。

    ``ensure_parent`` 是把号写进 ``project.json`` 的那个人，而 ``DevRun`` 对象在网关
    里活得更久 —— 所以路由是从**新读的记录**里补这个字段的，不是从缓存的那份。
    """
    pid, _ws, app = route_env
    record_path = projects.projects_root() / pid / "project.json"
    data = json.loads(record_path.read_text(encoding="utf-8"))
    data["jiraParent"] = "ACP-7777"
    record_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(routes, "_dev_run_for", lambda *a, **k: FakeRun())
    async with TestClient(TestServer(app)) as client:
        r = await client.get(f"/api/apps/ai-studio/projects/{pid}/dev/dag")
        assert r.status == 200
        body = await r.json()
        assert body["jiraParent"] == "ACP-7777"
        assert body["jiraParentUrl"] == "https://jira.jereh.cn/browse/ACP-7777"

        # 状态文件自己带的号优先（那一轮实际用的就是它）
        monkeypatch.setattr(
            routes,
            "_dev_run_for",
            lambda *a, **k: FakeRun({"runState": "planned", "nodes": [], "jiraParent": "ACP-1"}),
        )
        r = await client.get(f"/api/apps/ai-studio/projects/{pid}/dev/dag")
        body = await r.json()
        assert body["jiraParent"] == "ACP-1"
        assert body["jiraParentUrl"] == "https://jira.jereh.cn/browse/ACP-1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "m,path",
    [
        ("post", "/dev/plan"),
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
