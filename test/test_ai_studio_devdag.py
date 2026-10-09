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
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from kiro_crew.apps.builtins.ai_studio.backend import (
    accept,
    devdag,
    devplan,
    gitpush,
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

    def at(self, _path: Any) -> str:
        """One HEAD for everything — the shape a serial round has anyway.

        Serial runs write code in the main directory, so ``git_at`` and ``git``
        are the same answer there. A fake without this method would make every
        serial test drive a run that dies at the first ``worktree add`` and
        report it as a scheduler bug.
        """
        return self.head

    def commit(self) -> None:
        self.commits += 1
        self.head = f"c{self.commits}"


class PerDirGit(FakeGit):
    """HEAD per directory: what ``git_at`` exists for (ACP-2207).

    The whole point of the parallel shape is that a node commits on ITS branch,
    so the main directory's HEAD does not move while it works. A single global
    counter would hand every node a "changed" HEAD and the delivery check
    (``endCommit != startCommit``) would pass without the code ever having to
    look at the right directory — a fixture that cannot fail is worse than none.
    """

    def __init__(self) -> None:
        super().__init__()
        self.heads: dict[str, str] = {}
        self.commit_log: list[tuple[str, str]] = []  # (dir, commit) in order
        self.merges: list[tuple[str, str]] = []  # (branch, commit) in order

    def at(self, path: Any) -> str:
        return self.heads.get(str(path), self.head)

    def add_worktree(self, path: Any) -> None:
        """A new worktree starts at the main HEAD — that is what "从当前 HEAD 拉" is."""
        self.heads.setdefault(str(path), self.head)

    def commit_at(self, path: Any) -> str:
        self.commits += 1
        self.heads[str(path)] = f"c{self.commits}"
        self.commit_log.append((str(path), f"c{self.commits}"))
        return self.heads[str(path)]

    def merge(self, branch: str) -> str:
        self.commits += 1
        self.head = f"m{self.commits}"
        self.merges.append((branch, self.head))
        return self.head


class FakeWorktrees:
    """The four git operations a parallel node needs, as pure bookkeeping.

    ``devdag`` calls these as module-level functions, which is the seam
    monkeypatching uses. They stand in for ``git worktree add/merge/remove/list``
    — real ones would need a real repo, real branches and a real index.lock,
    and a test that forks git ten times per case is a slow test that still
    cannot say which directory it watched (testing-conventions: no host state).
    """

    def __init__(self, ws: Path, git: PerDirGit) -> None:
        self.ws = Path(ws)
        self.git = git
        self.added: list[tuple[str, str, str]] = []  # (path, branch, base)
        self.merged: list[tuple[str, str]] = []  # (branch, node key)
        self.removed: list[str] = []
        self.listed = 0
        # branch -> conflict file names to report instead of merging
        self.conflicts: dict[str, tuple[str, ...]] = {}
        self.excludes = 0
        # set by a test that wants to know whether the merge happened inside the
        # scheduler's own serialisation lock (see ``worktree_merge``)
        self.merge_lock_held: Callable[[], bool] | None = None
        self.lock_held_at_merge: list[bool] = []
        # one ordered timeline shared with the harness: who started, who was
        # handed a directory, who was merged — the sequence IS the assertion
        self.timeline: list[str] = []
        # what the outside world looked like from INSIDE a git call (see below)
        self.probe: Callable[[], dict[str, str]] | None = None
        self.states_at_add: list[tuple[str, dict[str, str]]] = []
        # the main directory's HEAD at the moment each worktree was built
        self.mains_at_add: list[tuple[str, str]] = []

    def install(self, monkeypatch) -> "FakeWorktrees":
        for name in (
            "ensure_local_exclude",
            "worktree_list",
            "worktree_reusable",
            "worktree_add",
            "worktree_merge",
            "worktree_remove",
        ):
            monkeypatch.setattr(devdag, name, getattr(self, name))
        return self

    def ensure_local_exclude(self, _repo: Path) -> None:
        self.excludes += 1

    def worktree_list(self, _repo: Path) -> dict[str, str]:
        self.listed += 1
        return {path: branch for path, branch, _base in self.added}

    def worktree_reusable(self, _repo: Path, path: Path, branch: str) -> bool:
        return any(p == str(path) and b == branch for p, b, _base in self.added)

    def worktree_add(self, _repo: Path, path: Path, branch: str, base: str) -> None:
        self.added.append((str(path), branch, base))
        self.git.add_worktree(path)
        self.mains_at_add.append((branch, self.git.head))
        self.timeline.append(f"add:{branch}")
        # Read the file from where a real ``git worktree add`` is: this is the
        # moment AFTER the scheduler handed this node out and BEFORE its
        # coroutine writes anything else. A node the file still calls ``queued``
        # here is one the board would show as not-started while seconds go by
        # building its directory — and ``running`` in the file is the ONLY thing
        # a second 〔开始开发〕 checks before opening a competing loop.
        if self.probe is not None:
            self.states_at_add.append((branch, self.probe()))

    def worktree_merge(self, _repo: Path, branch: str, label: str) -> None:
        # git's index holds ONE writer, so two nodes that both finished must not
        # merge at the same instant; the scheduler serialises that with a lock.
        # This fake is the only place that moment is observable, so it asks the
        # lock itself: "was it held while git was called?" A single answer proves
        # the merge is inside the critical section, which is the whole property —
        # no timing an overlap, no grace period that passes by luck on an idle box.
        if self.merge_lock_held is not None:
            self.lock_held_at_merge.append(self.merge_lock_held())
        if branch in self.conflicts:
            self.timeline.append(f"conflict:{branch}")
            raise devdag.GitOpError(
                f"merge {branch}: CONFLICT (content): Merge conflict", self.conflicts[branch]
            )
        self.merged.append((branch, label))
        self.git.merge(branch)
        self.timeline.append(f"merge:{branch}")

    def worktree_remove(self, _repo: Path, path: Path) -> None:
        self.removed.append(str(path))
        self.timeline.append(f"remove:{Path(path).name}")


@pytest.fixture(autouse=True)
def serial_by_default(monkeypatch):
    """Pin the pre-ACP-2207 tests to the shape they were written against.

    The module default is 2, so without this every one of those cases would
    suddenly get a worktree directory, a merge and a different session cwd —
    the failures would read like the scheduler went bad rather than like the
    shape changed. The default itself is pinned by its own test below, the
    parallel shape by the cases at the foot of this file.
    """
    monkeypatch.setenv(devdag.PARALLEL_ENV, "1")


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
    """One DevRun plus the fakes it drives, and the knobs a test flips.

    ``parallel=True`` switches the fixture onto the ACP-2207 shape: the git fake
    starts answering per directory (so a node's commit lands in ITS worktree,
    not on the main HEAD) and the worktree calls become fakes too. A turn then
    commits where its own session is sitting, which is the only way a test can
    observe that two nodes were given two directories.
    """

    def __init__(self, ws: Path, *, parallel: bool = False) -> None:
        self.state = FakeState()
        self.git = PerDirGit() if parallel else FakeGit()
        self.worktrees = FakeWorktrees(ws, self.git) if parallel else None
        self.calls: list[tuple[str, str]] = []
        # node title -> reply text; default 完成
        self.replies: dict[str, str] = {}
        # slot keys whose turn commits nothing
        self.no_commit: set[str] = set()
        self.dispatcher_block: asyncio.Event | None = None
        # slot key -> an Event the test sets to let that node's turn finish.
        # Parallel tests need this: "did B start while A was still working" can
        # only be asked if a turn can be held open on purpose.
        self.gates: dict[str, asyncio.Event] = {}
        # slot keys in the order their turns were entered
        self.gate_order: list[str] = []

        async def dispatch(_state: Any, slot: Any, prompt: str) -> str:
            key = str(slot.key)
            self.calls.append((key, prompt))
            if self.worktrees is not None:
                self.worktrees.timeline.append(f"start:{key}")
            gate = self.gates.get(key)
            if gate is not None:
                await gate.wait()
            if self.dispatcher_block is not None:
                await self.dispatcher_block.wait()
            if key not in self.no_commit:
                # commit where this session is sitting: a shared HEAD would let
                # the delivery check pass even when the cwd was the wrong one
                if self.worktrees is not None:
                    self.git.commit_at(str(slot.project))
                else:
                    self.git.commit()
            return self.replies.get(str(slot.title), "完成")

        self.run = devdag.DevRun(
            self.state,
            {"id": "p0101", "name": "设备管理"},
            ws,
            dispatcher=dispatch,
            git=self.git,
            git_at=self.git.at,
            clock=lambda: 100.0,
        )

    def install_worktrees(self, monkeypatch, env: str = "2") -> FakeWorktrees:
        """Put this harness on the parallel path (env + the four git fakes)."""
        assert self.worktrees is not None, "Harness(ws, parallel=True) first"
        monkeypatch.setenv(devdag.PARALLEL_ENV, env)
        fake = self.worktrees.install(monkeypatch)
        # the fake asks the real lock object, so the answer is the scheduler's
        # actual critical section and not a copy of the code's own claim
        fake.merge_lock_held = self.run._merge_lock.locked
        return fake

    @property
    def cwds(self) -> list[tuple[str, str]]:
        """(slot key, the directory its session was opened on) per dispatch.

        Read off the slot rather than recorded in the dispatcher, because
        ``slot.project`` IS the cwd the harness would run in (``chat_runner``
        takes it from there) — that is the fact the assertion is about.
        """
        return [(str(s.key), str(s.project)) for s in self.state._slots.values()]

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
        ("post", "/accept/fix"),
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


# ── ACP-2210：验收没过 → 让助手修 → 自动再验收 ─────────────────────────────
#
# A red acceptance used to be a dead end on the board. These cover the four
# things the ticket names: the refusal, the appended node and its prompt, the
# automatic re-acceptance, and the three-repair ceiling.


def failed_record(n_fail: int = 2, ordinal: int = 1) -> dict[str, Any]:
    """A failed acceptance record shaped like accept.run_accept's output."""
    results = [
        {
            "id": f"pnpm test:unit{k}",
            "ok": k >= n_fail,
            "tail": "FAIL" if k < n_fail else "",
            "logPath": f".ai-studio/accept/acc-{ordinal}-{k}.log",
        }
        for k in range(3)
    ]
    return {
        "id": f"acc-{ordinal}",
        "phase": "full",
        "result": "failed",
        "voided": False,
        "results": results,
        "requirementVersion": "a:h1",
        "commitHash": "c9",
        "at": "2026-10-10T11:00:00Z",
    }


class FakeReAccept:
    """The acceptance runner as ``_re_accept_after_fix`` sees it.

    Patched onto the module as a function: the loop imports the module inside the
    call, so a module-attribute lookup at call time is what the monkeypatch aims
    at.
    """

    def __init__(self, result: str = "failed") -> None:
        self.result = result
        self.seen: list[tuple[Path, dict[str, Any]]] = []
        # runState on disk while each call ran
        self.file_states: list[str] = []

    def __call__(self, ws: Path, state: dict[str, Any], **_kw: Any) -> dict[str, Any]:
        self.seen.append((ws, dict(state)))
        # what the STATE FILE said at the moment acceptance ran, read fresh off
        # disk rather than from the argument the caller chose to hand us
        raw = devdag._read(devdag._state_path(ws)) or {}
        self.file_states.append(str(raw.get("runState") or ""))
        return {"id": "acc-new", "result": self.result, "voided": False}


@pytest.fixture(autouse=True)
def no_real_acceptance_subprocess(monkeypatch):
    """No test in this file may fork the workspace's ``pnpm``.

    A finished fix node runs acceptance, and a test that lets that call through
    unpatched would spawn a minutes-long real child (testing-conventions). Fail
    loudly at the subprocess seam instead.
    """

    def _never(*_a: Any, **_kw: Any) -> tuple[int, str]:
        raise AssertionError("a test reached the real acceptance subprocess")

    monkeypatch.setattr(accept, "_run_cmd", _never)


@pytest.fixture()
def re_accept(monkeypatch):
    """A spy acceptance runner, installed for the test."""
    fake = FakeReAccept()
    monkeypatch.setattr(accept, "run_accept", fake)
    return fake


@pytest.mark.asyncio
async def test_fix_refuses_a_round_that_is_not_done_and_a_record_that_passed(
    h: Harness, re_accept: FakeReAccept
):
    # nothing has ever run: there is no board to append a repair to
    with pytest.raises(devdag.DevDagError) as exc:
        await h.run.fix(failed_record())
    assert (exc.value.code, exc.value.status) == ("nothing_to_fix", 409)

    await h.run.start(PAGES)
    await h.finish()
    assert h.run.get()["runState"] == "done"

    # a PASSED record is not a thing to fix, even on a done round
    passed = failed_record(n_fail=0)
    passed["result"] = "passed"
    with pytest.raises(devdag.DevDagError) as exc:
        await h.run.fix(passed)
    assert (exc.value.code, exc.value.status) == ("nothing_to_fix", 409)
    # the refusals wrote nothing: still the four planned nodes, still done
    dag = h.run.get()
    assert dag["runState"] == "done"
    assert [n["jiraKey"] for n in dag["nodes"]] == IDS
    assert h.calls and len(h.calls) == 4

    # a RUNNING round is refused too — mid-flight the loop's nodes are its progress
    h.dispatcher_block = asyncio.Event()
    await h.run.fix(failed_record())
    with pytest.raises(devdag.DevDagError) as exc:
        await h.run.fix(failed_record())
    assert (exc.value.code, exc.value.status) == ("nothing_to_fix", 409)
    h.dispatcher_block.set()
    await h.finish()


@pytest.mark.asyncio
async def test_fix_appends_one_node_and_its_prompt_carries_the_log_paths(
    h: Harness, re_accept: FakeReAccept
):
    await h.run.start(PAGES)
    await h.finish()

    started = await h.run.fix(failed_record())
    assert started["phase"] == "full"
    await h.finish()

    dag = h.run.get()
    # appended at the END of the list, no dependencies, and the four real tasks
    # are untouched (their commits and Jira numbers are the record of what shipped)
    assert [n["jiraKey"] for n in dag["nodes"]] == IDS + ["fix:1"]
    fix = dag["nodes"][-1]
    assert fix["kind"] == "fix"
    assert fix["title"] == "修复验收失败（第 1 次）"
    assert fix["dependsOn"] == []
    assert fix["state"] == "done"
    assert dag["runState"] == "done"

    # the fix turn is the fifth dispatch, and its prompt points at the outputs
    assert len(h.calls) == 5
    prompt = h.calls[-1][1]
    assert ".ai-studio/accept/acc-1-0.log" in prompt
    assert ".ai-studio/accept/acc-1-1.log" in prompt
    # only the FAILING commands are named, and the passing one is not
    assert "pnpm test:unit2" not in prompt
    assert "平台验收没通过" in prompt
    assert "fix: 验收失败修复（第 1 次）" in prompt
    # the ticket's wording, verbatim
    assert (
        "可以单独运行失败的那几个测试文件来确认（一次只跑一个文件），不许运行全量测试、e2e 或开发服务器。"
        in prompt
    )
    assert "最后一句只回复：完成 或 失败：<原因>。" in prompt


@pytest.mark.asyncio
async def test_a_finished_fix_re_runs_acceptance(h: Harness, monkeypatch):
    fake = FakeReAccept("passed")
    monkeypatch.setattr(accept, "run_accept", fake)
    await h.run.start(PAGES)
    await h.finish()
    assert fake.seen == []  # a normal round never re-accepts by itself

    await h.run.fix(failed_record())
    await h.finish()

    assert len(fake.seen) == 1
    ws, state = fake.seen[0]
    # called with THIS workspace, and the state it was handed says the dev is
    # done — that is run_accept's own precondition, so anything else is a 409
    assert ws == h.run.ws
    assert state["runState"] == "done"
    assert [n["jiraKey"] for n in state["nodes"]][-1] == "fix:1"
    assert "re-accept result=passed" in "\n".join(h.run.log_lines(50))


@pytest.mark.asyncio
async def test_a_start_is_refused_while_the_post_fix_acceptance_runs(h: Harness, monkeypatch):
    # The state file stays `running` for the minutes the automatic acceptance
    # takes. Written the other way (file to `done`, then run), the board would
    # report done with a live loop attached, and 开始开发's own guard
    # (`runState == running`) would let a SECOND loop start over the same
    # workspace while the checks are still running in it.
    inside = threading.Event()
    release = threading.Event()
    fake = FakeReAccept("passed")

    def slow_accept(ws: Path, state: dict[str, Any], **_kw: Any) -> dict[str, Any]:
        inside.set()
        release.wait(timeout=10)
        return fake(ws, state)

    monkeypatch.setattr(accept, "run_accept", slow_accept)
    await h.run.start(PAGES)
    await h.finish()
    await h.run.fix(failed_record())

    # hold the loop at the instant acceptance is in flight (it runs on a thread,
    # so this is a real handshake and not a guessed number of awaits)
    await asyncio.to_thread(inside.wait, 10)
    dag = h.run.get()
    assert dag["runState"] == "running"
    with pytest.raises(devdag.DevDagError) as exc:
        await h.run.start(PAGES)
    assert (exc.value.code, exc.value.status) == ("run_active", 409)
    # the row the board shows IS a finished repair, so 「开发中」 beside a row of ✓s
    # is the accepted half of this trade — documented on the method
    assert dag["nodes"][-1]["state"] == "done"

    release.set()
    await h.finish()
    assert h.run.get()["runState"] == "done"
    assert fake.file_states == ["running"]


@pytest.mark.asyncio
async def test_a_broken_acceptance_run_does_not_unwrite_the_fix(h: Harness, monkeypatch):
    # the fix committed; acceptance failing to RUN is a bookkeeping failure, and
    # flipping the node to failed would throw away real delivered work
    def boom(_ws: Path, _state: dict[str, Any], **_kw: Any) -> dict[str, Any]:
        raise OSError("read-only file system")

    monkeypatch.setattr(accept, "run_accept", boom)
    await h.run.start(PAGES)
    await h.finish()
    await h.run.fix(failed_record())
    await h.finish()

    dag = h.run.get()
    assert dag["runState"] == "done"
    assert dag["nodes"][-1]["state"] == "done"
    assert "re-accept failed: OSError" in "\n".join(h.run.log_lines(50))


@pytest.mark.asyncio
async def test_the_third_fix_is_the_last_one(h: Harness, re_accept: FakeReAccept):
    await h.run.start(PAGES)
    await h.finish()

    for ordinal in (1, 2, 3):
        await h.run.fix(failed_record(ordinal=ordinal))
        await h.finish()

    dag = h.run.get()
    assert [n["jiraKey"] for n in dag["nodes"]][-3:] == ["fix:1", "fix:2", "fix:3"]
    assert h.run.fix_attempts() == 3

    # the fourth is refused: three repairs and still red is not a code problem
    with pytest.raises(devdag.DevDagError) as exc:
        await h.run.fix(failed_record(ordinal=4))
    assert (exc.value.code, exc.value.status) == ("fix_limit", 409)
    assert h.run.fix_attempts() == 3
    assert [n["jiraKey"] for n in h.run.get()["nodes"]][-3:] == ["fix:1", "fix:2", "fix:3"]


@pytest.mark.asyncio
async def test_a_fix_files_its_own_jira_issue_under_the_same_parent(
    ws: Path, jira: JiraSpy, re_accept: FakeReAccept
):
    git = FakeGit()
    run = devdag.DevRun(
        FakeState(),
        {"id": "p0101", "name": "设备管理", "jiraParent": "ACP-8000"},
        ws,
        # ONE git for both seams: the dispatcher "commits" and the scheduler reads
        # HEAD, and a second FakeGit would report an unchanged HEAD forever, which
        # is the 「回复说完成了，但没有新提交」 failure — every node would fail and
        # the round would never reach `done`, which is what fix() requires.
        dispatcher=_completing_dispatch(git),
        git=git,
        clock=lambda: 100.0,
    )
    await run.plan(PAGES)
    created_before = len(jira.created)
    await run.start(PAGES)
    await run._loop_task
    assert len(jira.created) == created_before  # start reuses plan's issues

    await run.fix(failed_record())
    await run._loop_task

    # one new sub-issue, under the SAME parent, and the board carries its key
    assert len(jira.created) == created_before + 1
    parent, title, _code = jira.created[-1]
    assert (parent, title) == ("ACP-8000", "修复验收失败（第 1 次）")
    node = run.get()["nodes"][-1]
    assert node["jira"] == f"ACP-{jira._next}"
    assert node["jiraUrl"].endswith(f"/{node['jira']}")
    # and it gets closed like any delivered task, not left 进行中
    assert (node["jira"], jirasync.done_state()) in jira.transitions


def _completing_dispatch(git: FakeGit):
    async def dispatch(_state: Any, _slot: Any, _prompt: str) -> str:
        git.commit()
        return "完成"

    return dispatch


@pytest.mark.asyncio
async def test_a_fix_prompt_survives_a_restart(ws: Path, monkeypatch):
    # the failing commands live on the NODE, not only in the prompt that was sent:
    # a gateway restart between the crash and 从失败处继续 must not send a fix
    # request with no evidence attached
    monkeypatch.setattr(accept, "run_accept", FakeReAccept())
    state = FakeState()
    git = FakeGit()
    prompts: list[str] = []

    async def dispatch(_state: Any, _slot: Any, prompt: str) -> str:
        prompts.append(prompt)
        git.commit()
        return "完成"

    run = devdag.DevRun(
        state, {"id": "p0101"}, ws, dispatcher=dispatch, git=git, clock=lambda: 100.0
    )
    await run.start(PAGES)
    await run._loop_task
    await run.fix(failed_record())
    await run._loop_task

    # a NEW object over the same workspace, like a restarted gateway
    again = devdag.DevRun(state, {"id": "p0101"}, ws, dispatcher=dispatch, git=git)
    node = again.get()["nodes"][-1]
    assert node["acceptCmds"] == [
        {"id": "pnpm test:unit0", "logPath": ".ai-studio/accept/acc-1-0.log"},
        {"id": "pnpm test:unit1", "logPath": ".ai-studio/accept/acc-1-1.log"},
    ]
    prompt = again._prompt_for(node)
    assert ".ai-studio/accept/acc-1-1.log" in prompt


@pytest.fixture(autouse=True)
def no_real_gitpush(monkeypatch):
    """No test here may fork a real ``git push`` (ACP-2218).

    Every round that reaches ``done`` now pushes its branch, so without this the
    pre-2218 cases would each spawn real git against a tmp directory that is not a
    repo — a real child per test, and an answer that depends on whether the tmp
    path happens to sit inside someone's repository (testing-conventions). The
    default fake succeeds and records, so a test that does not care about pushing
    still does not have to think about it; the three cases that DO care flip
    :attr:`PushSpy.ok` or read :attr:`PushSpy.calls`.
    """
    spy = PushSpy()
    monkeypatch.setattr(gitpush, "push_branch", spy)
    return spy


class PushSpy:
    """``gitpush.push_branch`` as the scheduler sees it: calls counted, result chosen.

    它**不复读真措辞**。早先它写的是「推送 develop：成功」，于是下面那几条断言
    测的是「替身写了替身会写的字」—— 真模块哪天改了措辞，这里照样全绿。现在它只
    写一个别的代码不可能产生的标记，断言因此是**管线**：传进来的那个 ``log`` 回调
    确实落到 ``dev-run.log``。措辞本身由 ``test_ai_studio_gitpush.py`` 钉住。
    """

    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.calls: list[Path] = []

    def __call__(self, ws: Path, log: Callable[[str], None]) -> bool:
        # the workspace is the argument under test too: pushing a node's worktree
        # instead of the main directory would ship a branch missing its merge
        self.calls.append(Path(ws))
        log(f"[push-spy] n={len(self.calls)} ok={self.ok}")
        return self.ok


@pytest.mark.asyncio
async def test_a_finished_round_pushes_the_branch_once(ws: Path, h: Harness, no_real_gitpush):
    """整轮 done ⇒ 推一次，推的是**主目录**，且它写的日志进了 ``dev-run.log``。

    断「一次」而不是「至少一次」：每个节点跑完都推一遍会把同一个提交推 N 遍（远端
    每次都要协商一遍 ref），而看板上看不出来。断的是 ``ws`` 而不是某个 worktree：
    并行节点的合并全在主目录完成，推 ``dev/*`` 会少掉那个合并节点。
    """
    await h.run.start(PAGES)
    await h.finish()

    assert h.run.get()["runState"] == "done"
    assert no_real_gitpush.calls == [ws]
    assert "[push-spy] n=1 ok=True" in "\n".join(h.run.log_lines(50))


@pytest.mark.asyncio
async def test_a_failed_round_pushes_nothing(h: Harness, no_real_gitpush):
    """failed ⇒ 一次都不推。

    半轮代码推上去，别人 clone 下来拿到的是「编译不过的 develop」，而看板上明明写的
    是失败。这一条也是「不推」唯一的证据：failed 的路径上没有任何别的信号会说话。
    """
    h.no_commit.add(SLOT_NAMES[1])
    await h.run.start(PAGES)
    await h.finish()

    assert h.run.get()["runState"] == "failed"
    assert no_real_gitpush.calls == []
    assert "[push-spy]" not in "\n".join(h.run.log_lines(50))


@pytest.mark.asyncio
async def test_a_refused_push_does_not_change_the_round(h: Harness, no_real_gitpush):
    """推不出去（fork 没配凭据是常态）：整轮还是 done，节点一个都不改判。

    推分支是记账，不是开发本身：代码已经提交在工作区里，看板上的「完成」是 git 的
    事实。因为远端不可达就把这一轮判失败，会让人重跑一轮已经交付完的活。
    """
    no_real_gitpush.ok = False
    await h.run.start(PAGES)
    await h.finish()

    dag = h.run.get()
    assert dag["runState"] == "done"
    assert [n["state"] for n in dag["nodes"]] == ["done"] * 4
    assert "[push-spy] n=1 ok=False" in "\n".join(h.run.log_lines(50))


@pytest.mark.asyncio
async def test_a_fix_pushes_before_the_re_acceptance(
    h: Harness, monkeypatch, no_real_gitpush: "PushSpy"
):
    """修复节点跑完：先推分支，再自动验收。

    顺序是这一条的全部内容，所以让验收替身在被调用的那一刻回头读日志：它跑起来时
    日志里必须已经有那一行推送。反过来写（验收之后再推）在这里会红 —— 而那种写法
    真的有代价：验收要几分钟，期间网关重启会把这一轮判成中断，那时已经提交的修复还
    只活在本地。

    这一轮因此推**两次**（再验收前一次、收口 done 时一次），是刻意的：前一次可能因
    为远端抖动没成，收口那一次就是它的重试，而「已经 up-to-date」的重复推送 git 只
    回一句话。省下它要在循环里多带一个「我推过了」的布尔，那才是新的事实来源。
    """
    seen_push: list[int] = []

    def spy_accept(_ws: Path, _state: dict[str, Any], **_kw: Any) -> dict[str, Any]:
        seen_push.append(len(no_real_gitpush.calls))
        return {"id": "acc-new", "result": "passed", "voided": False}

    monkeypatch.setattr(accept, "run_accept", spy_accept)
    await h.run.start(PAGES)
    await h.finish()
    assert len(no_real_gitpush.calls) == 1  # the plain round pushed once

    await h.run.fix(failed_record())
    await h.finish()

    # 验收那一刻已经推过（1 = 普通轮那一次，2 = 修复后这一次；0 才是修好了没推）
    assert seen_push == [2], "re-acceptance ran before the fix was pushed"
    assert len(no_real_gitpush.calls) == 3


@pytest.mark.asyncio
async def test_fix_limit_matches_the_boards_copy():
    # the board hides its button at the same number the backend refuses at; a
    # drifted constant here is a click that 409s, which is what the notice says
    assert devdag.FIX_LIMIT == 3


@pytest.mark.asyncio
async def test_a_new_round_drops_the_old_repairs_and_the_ceiling_with_them(
    h: Harness, re_accept: FakeReAccept
):
    # 「连续 3 次」 counts repairs of ONE acceptance. If the repair rows outlived
    # the round, a project that had repaired three times would never be offered a
    # fix again — for the rest of its life, whatever the new acceptance says.
    await h.run.start(PAGES)
    await h.finish()
    for ordinal in (1, 2, 3):
        await h.run.fix(failed_record(ordinal=ordinal))
        await h.finish()
    assert h.run.fix_attempts() == 3

    # re-developing (the board's 开始开发 on a done round) is a new round
    await h.run.start(PAGES)
    await h.finish()
    dag = h.run.get()
    assert dag["runState"] == "done"
    assert [n["jiraKey"] for n in dag["nodes"]] == IDS
    assert h.run.fix_attempts() == 0
    # and the button is offered again
    await h.run.fix(failed_record())
    await h.finish()
    assert [n["jiraKey"] for n in h.run.get()["nodes"]][-1] == "fix:1"


@pytest.mark.asyncio
async def test_resuming_a_failed_round_keeps_its_repair(h: Harness, re_accept: FakeReAccept):
    # the other half of the same rule: 从失败处继续 must NOT drop the repair it is
    # continuing — a half-done repair is exactly what that button is for
    await h.run.start(PAGES)
    await h.finish()
    h.no_commit = {"ai-studio-dev-p0101-5"}  # the fix node's own slot
    await h.run.fix(failed_record())
    await h.finish()

    dag = h.run.get()
    assert dag["runState"] == "failed"
    assert dag["nodes"][-1]["jiraKey"] == "fix:1"
    assert dag["nodes"][-1]["state"] == "failed"

    h.no_commit = set()
    await h.run.start(PAGES)
    await h.finish()
    after = h.run.get()
    # the task rows were not re-run (they are done and this is a resume), the
    # repair was, and its ordinal did not restart at 1
    assert [n["jiraKey"] for n in after["nodes"]] == IDS + ["fix:1"]
    assert after["nodes"][-1]["state"] == "done"
    assert h.run.fix_attempts() == 1


@pytest.mark.asyncio
async def test_a_re_split_drops_repairs_and_never_voids_their_issues(
    ws: Path, jira: JiraSpy, re_accept: FakeReAccept
):
    # A repair row is not a page. Carrying it into a re-split would make
    # _pages_of() report "fix" as one of the pages (so every later split thinks
    # the page set changed and rebuilds the plan and its issues) and would offer
    # to void an issue that recorded real delivered work.
    git = FakeGit()
    run = devdag.DevRun(
        FakeState(),
        {"id": "p0101", "name": "设备管理", "jiraParent": "ACP-8000"},
        ws,
        dispatcher=_completing_dispatch(git),
        git=git,
        clock=lambda: 100.0,
    )
    await run.plan(PAGES)
    await run.start(PAGES)
    await run._loop_task
    await run.fix(failed_record())
    await run._loop_task
    assert run.fix_attempts() == 1
    repair_issue = run.get()["nodes"][-1]["jira"]
    voided_before = len(jira.comments)

    # a page was added, so this split really rebuilds
    (ws / requirements.REQ_DIR / "设备报废.json").write_text(
        json.dumps({"page": "设备报废"}, ensure_ascii=False), encoding="utf-8"
    )
    await run.plan(PAGES + ["设备报废"])
    after = run.get()
    keys = [str(n["jiraKey"]) for n in after["nodes"]]
    assert "fix:1" not in keys
    assert "fix" not in devdag._pages_of(after["nodes"])
    # the repair's own issue is left alone: it is delivered work, not a dropped task
    assert repair_issue
    assert [k for k, _text in jira.comments[voided_before:]] != [repair_issue]
    assert all(k != repair_issue for k, _text in jira.comments[voided_before:])


# ── ACP-2207：独立任务并行，各占一个 worktree，跑完在主目录合并 ──────────────
#
# The scheduler's other half. Two things make these cases unlike the ones above:
# HEAD is answered PER DIRECTORY (a parallel node commits on its own branch, so
# the main directory does not move until the merge — a single counter would let
# the delivery check pass without the code ever reading the right directory),
# and turns are held open with events, because "did B start while A was still
# working" is a question about an interleaving that no sequential fixture can
# answer by accident.


def _par_harness(ws: Path, monkeypatch, *, env: str = "2") -> Harness:
    """A harness on the parallel path: env set, git and worktrees faked."""
    monkeypatch.delenv(devdag.TRUST_ENV, raising=False)
    h = Harness(ws, parallel=True)
    h.install_worktrees(monkeypatch, env)
    return h


async def _wait_until(detail: str, predicate: Callable[[], bool]) -> None:
    """Wait in real time for a parallel node to get that far; fail loudly if it doesn't.

    A parallel node reaches its dispatcher through three thread-pool round trips
    (the local exclude, the reuse check, ``worktree add``), i.e. milliseconds of
    real latency. ``asyncio.sleep(0)`` yields but does not advance the clock, so
    a loop of 50 such yields is over in microseconds and the node has not moved
    — the pre-2207 tests could get away with that because a serial node needs
    no subprocess to start. Two seconds of 5 ms ticks, with the failure named,
    keeps this a bounded wait instead of a hang (testing-conventions: a test
    that can block forever is a lost run, not a failed test).
    """
    for _ in range(400):
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError(f"timed out waiting for: {detail}")


def _git(repo: Path, *args: str) -> str:
    """一条真 git（只有那三条真 git 的用例用：它们验的正是 git 自己怎么看这棵树）。

    仓库是 tmp 目录，作者信息就地配死 —— 不读部署机的 ``~/.gitconfig``，否则换台
    机器（或 CI 容器里没有 user.email）就报「请告诉我你是谁」。
    """
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, f"git {' '.join(args)}: {proc.stdout}{proc.stderr}"
    return (proc.stdout or "").strip()


def test_the_default_parallelism_is_two_and_the_env_says_otherwise(monkeypatch):
    """默认 2；``AI_STUDIO_DEV_PARALLEL`` 改写它；读不懂的退回默认，上限 8。

    「0 / 负数 / 非数字退回 2 而不是 1」是有立场的一条：读成 1 等于「配置写错了 ⇒
    悄悄变串行」，那是把一次没人察觉的性能改动塞进一次拼写错误里。

    读空默认值这一半必须先把环境清空：本文件有个 autouse 夹具为了保住改造前那
    三十来条断言的形状，把 ``AI_STUDIO_DEV_PARALLEL`` 钉成了 1 —— 不摘掉它，这条
    测的是「夹具设的值」，永远测不到模块的默认值。
    """
    monkeypatch.delenv(devdag.PARALLEL_ENV, raising=False)
    assert devdag.parallel_limit("") == 2
    assert devdag.parallel_limit(None) == 2
    assert devdag.parallel_limit("3") == 3
    assert devdag.parallel_limit(" 4 ") == 4
    assert devdag.parallel_limit("1") == 1
    assert devdag.parallel_limit("0") == 2
    assert devdag.parallel_limit("-3") == 2
    assert devdag.parallel_limit("two") == 2
    assert devdag.parallel_limit("99") == devdag.MAX_PARALLEL
    monkeypatch.setenv(devdag.PARALLEL_ENV, "3")
    assert devdag.parallel_limit(None) == 3
    # 显式传值和读环境是两件事：传了就不看环境（部署上默认值要能被单测/调用方指定）
    assert devdag.parallel_limit("5") == 5


def test_a_task_id_becomes_a_branch_and_a_node_index_a_directory():
    """分支名与 worktree 路径的算法（派工单写死的两条命名）。

    中文名原样保留是刻意的：把它一起换成短横线会让「设备点检记录:api」和「备件台
    账:api」塌成同一条分支，而两个并行节点共用一条分支就是共用工作 —— 正是这一单
    要消灭的事。目录按**节点序号**，和看板上第几行、会话名是同一个序号。
    """
    assert devdag.branch_name("设备点检记录:api") == "dev/设备点检记录-api"
    assert devdag.branch_name("My_Page:web") == "dev/my-page-web"
    assert devdag.branch_name("") == "dev/node"
    assert devdag.worktree_path(Path("/ws"), 0) == Path("/ws/.ai-studio/wt/1")
    assert devdag.worktree_path(Path("/ws"), 3) == Path("/ws/.ai-studio/wt/4")


def test_the_worktree_tree_is_excluded_locally_never_in_the_repo(tmp_path: Path):
    """第二棵树在本地忽略掉，且不改 ``.gitignore``（不改被跟踪的文件）。

    模板的 ``.gitignore`` 里没有 ``.ai-studio/``：不加这条，主目录的 ``git status``
    会多出整份代码的副本，助手一句 ``git add -A`` 就能把另一个节点的现场当成自己的
    成果提交。写 ``.git/info/exclude`` 而非常规忽略文件：那是本地账本，不进版本库、
    不进发布包，也不会把主目录改脏（改脏了每次合并前都得先 stash）。

    这条验的是 git 自己怎么看这棵树，所以 fork 真 git —— 替身只会重复代码里已经
    写着的那个结论。仓库在 tmp 目录里就地 init，作者信息也就地配死，不读部署机的
    ``~/.gitconfig``。
    """
    repo = tmp_path / "ws"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "test")
    (repo / "a.txt").write_text("a", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "init")

    devdag.ensure_local_exclude(repo)
    devdag.ensure_local_exclude(repo)  # 幂等：不重复追加

    exclude = devdag._git_dir(repo) / "info" / "exclude"
    assert exclude.read_text(encoding="utf-8").count(devdag._LOCAL_EXCLUDE_ENTRY) == 1
    (repo / devdag.WORKTREE_SUBDIR / "1" / "src").mkdir(parents=True)
    (repo / devdag.WORKTREE_SUBDIR / "1" / "src" / "app.tsx").write_text("x", encoding="utf-8")
    # 只挡 worktree 那一格：需求文档（``docs/需求图谱``）是同目录里要进仓的事实源。
    # 逐项列（``--untracked-files=all``）而不是看默认输出 —— git 会把整个未跟踪目录
    # 折成一行 ``?? docs/``，路径名压根不出现。
    (repo / requirements.REQ_DIR).mkdir(parents=True, exist_ok=True)
    (repo / requirements.REQ_DIR / "设备点检记录.json").write_text("{}", encoding="utf-8")
    status = _git(repo, "-c", "core.quotePath=false", "status", "--porcelain", "-uall")
    assert devdag.WORKTREE_SUBDIR not in status
    assert f"{requirements.REQ_DIR}/设备点检记录.json" in status
    # 没碰任何被跟踪的文件，也没往仓里加规则
    assert _git(repo, "ls-files") == "a.txt"


def _fresh_repo(tmp_path: Path, name: str = "设备台账.txt") -> Path:
    """tmp 目录里一个能提交的最小仓库，里面有一个中文名的文件（那两条验 git 本身的用例共用）。

    作者信息就地配死 —— 不读部署机的 ``~/.gitconfig``，否则换台机器（或 CI 容器里
    没有 user.email）就报「请告诉我你是谁」。文件名故意是中文：这一单的任务名就是
    中文，路径能不能原样回显正是这两条要问的事。
    """
    repo = tmp_path / "ws"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "test")
    (repo / name).write_text("基线版本\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def test_worktree_add_reuses_an_existing_branch_without_reading_git_words(
    tmp_path: Path, monkeypatch
):
    """续跑同一轮：分支已经在，``-b`` 那条必然失败，直接检出那一条必须顶上。

    真 git，因为这一条验的就是 git 自己的现场 —— 替身只会重复代码里写着的结论。

    判据是**退出码**，不是 git 那句话。这台机器的 ``LANG=zh_CN.utf8``，实测
    ``worktree add -b`` 撞见已有分支回的是 ``fatal: 一个名为 'dev/x' 的分支已经存在``。
    旧写法 ``if "already exists" in out`` 在英文 CI 上过、在中文部署机上永远不成立，
    于是「目录被清掉了、分支还在，点重试」这一类续跑 100% 报「建 worktree 失败」。
    所以这条故意注入中文 locale：它验的正是「git 换任何一门语言说话，续跑照样起得来」。

    现场是「目录没了但分支还在」，不是「同一个分支开两个目录」—— 后者 git 直接拒
    （``already used by worktree at ...``，一条分支同时只能有一个检出），那是 git 的
    规矩不是本模块该绕的东西。真失败也照样要报：给一个不存在的基点，两条命令都不成。
    """
    monkeypatch.setenv("LC_ALL", "zh_CN.UTF-8")
    repo = _fresh_repo(tmp_path)
    first = repo / devdag.WORKTREE_SUBDIR / "1"
    devdag.worktree_add(repo, first, "dev/x", "HEAD")
    assert devdag.worktree_list(repo)[str(first)] == "dev/x"

    # 现场被清掉（人手工删的、或上一轮收掉了 worktree），分支留在仓里
    devdag.worktree_remove(repo, first)
    assert str(first) not in devdag.worktree_list(repo)

    second = repo / devdag.WORKTREE_SUBDIR / "2"
    devdag.worktree_add(repo, second, "dev/x", "HEAD")  # 旧写法在这里抛
    assert devdag.worktree_list(repo)[str(second)] == "dev/x"

    # 真失败：基点不存在，两条命令都不会成 —— 报的是 git 原文（给人看，不参与判断）
    with pytest.raises(devdag.GitOpError):
        devdag.worktree_add(repo, repo / devdag.WORKTREE_SUBDIR / "3", "dev/y", "no-such-base")


def test_conflict_names_survive_a_chinese_locale_and_a_chinese_filename(
    tmp_path: Path, monkeypatch
):
    """冲突文件名单要原样可读：不 parse 报错文案，中文路径不被转成八进制。

    merge 的输出按 locale 换语言（本机实测「冲突（添加/添加）：合并冲突于 f.txt」），
    从里面正则抓文件名会在任何非英文机器上抓空；所以名单来自
    ``diff --name-only --diff-filter=U``。而这条命令默认把非 ASCII 路径转义，实测
    ``设备台账.txt`` 出来是 ``"\\350\\256\\276..."`` —— 看板上那句「合并冲突：<文件>」
    就等于没写。两处都得对，故三条断言都在。locale 用中文，且这条**故意**用中文。

    两条线必须**真的分叉**才谈得上冲突：先开 worktree，再让主目录和分支各改同一个
    文件一次。只动分支那一边，``merge --no-ff`` 只是补一个合并节点，不冲突（第一版
    就把顺序写反了，于是 ``pytest.raises`` 收不到异常）。
    """
    monkeypatch.setenv("LC_ALL", "zh_CN.UTF-8")
    name = "设备台账.txt"
    repo = _fresh_repo(tmp_path, name)
    # worktree 开在仓库**外面**：开在里面 git 会当它是嵌入式仓库并提示 submodule
    other = tmp_path / "wt"
    devdag.worktree_add(repo, other, "dev/conflict", "HEAD")

    (repo / name).write_text("主目录这一版\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "main touched it")
    (other / name).write_text("任务这一版\n", encoding="utf-8")
    _git(other, "add", "-A")
    _git(other, "commit", "-q", "-m", "the branch touched it too")

    with pytest.raises(devdag.GitOpError) as got:
        devdag.worktree_merge(repo, "dev/conflict", "设备点检记录:api")
    assert got.value.conflict_files == (name,)
    assert name in str(got.value)
    # 主目录退回合并之前：不留半合并状态给别人（下一个节点的 merge 会撞上去）
    assert _git(repo, "status", "--porcelain") == ""


@pytest.mark.asyncio
async def test_two_pages_dispatch_both_api_nodes_at_once(ws: Path, monkeypatch):
    """并行度 2 + 两页四节点：第一轮同时派出两个 api 节点，各占一个目录。

    节点 1 和 3 是两页的 api（互不依赖），2 和 4 是各自的 web。两个 gate 各自按住
    一个会话，所以「同时」不是调度器碰巧跑得快，而是它在两个会话都没结束的时候
    就把两个都派了出去。三件事叠在一起才成立：两个会话都被派出、它们的 cwd 是
    **两条不同**的路径、而第三个节点在两个 gate 放开之前根本没开始。少断一条都会
    放过一种假并行：只看调用列表会放过串行，只看路径不同会放过「串行但换了目录」。
    """
    h = _par_harness(ws, monkeypatch)
    api_slots = (SLOT_NAMES[0], SLOT_NAMES[2])
    h.gates = {slot: asyncio.Event() for slot in api_slots}

    await h.run.start(PAGES)
    await _wait_until("both api sessions dispatched", lambda: len(h.calls) >= 2)

    mid = h.run.get()
    assert sorted(key for key, _ in h.calls) == sorted(api_slots)
    assert [n["state"] for n in mid["nodes"]] == ["running", "queued", "running", "queued"]
    # 会话的 cwd 就是它自己的工作区，两条不同路径（07 §四-1 的实测路径口径）
    cwds = {slot: str(h.state._slots[slot].project) for slot in api_slots}
    assert cwds[api_slots[0]] != cwds[api_slots[1]]
    assert sorted(cwds.values()) == sorted(
        [str(devdag.worktree_path(ws, 0)), str(devdag.worktree_path(ws, 2))]
    )
    # 看板上的进行中节点看得见这个目录（前端 testid 的数据源）
    by_key = _nodes_by_key(mid)
    assert by_key[IDS[0]]["worktree"] == str(devdag.worktree_path(ws, 0))
    assert by_key[IDS[2]]["worktree"] == str(devdag.worktree_path(ws, 2))
    assert by_key[IDS[0]]["branch"] == devdag.branch_name(IDS[0])
    # 都从主目录当时的 HEAD 拉的
    assert [b for _p, _b, b in h.worktrees.added] == ["c0", "c0"]
    # 第二棵树不会把主目录搞脏，靠的是开工前先补那一条本地忽略
    assert h.worktrees.excludes == 2
    # 没跑的那两个还没有目录
    assert h.run._data()["nodes"][1]["worktree"] == ""

    for slot in api_slots:
        h.gates[slot].set()
    await h.finish()

    dag = h.run.get()
    assert dag["runState"] == "done"
    assert [n["state"] for n in dag["nodes"]] == ["done"] * 4
    # 一个任务一个合并（--no-ff：看板上第几行 = git 图里第几个合并）
    assert sorted(b for b, _k in h.worktrees.merged) == sorted(devdag.branch_name(k) for k in IDS)
    # 每次合并都在串行闸里面：git 的 index 只容得下一个写者，两个并行节点同时
    # merge 只有一个能成，另一个会撞 index.lock 被判失败（替身不报这个错，所以
    # 只能直接问那把闸当时是不是锁着的）
    assert len(h.worktrees.lock_held_at_merge) == 4
    assert all(h.worktrees.lock_held_at_merge)
    # 合干净了就收掉（07 §四-4：不许目录爆炸，条目数 ≤ 并行度峰值）
    assert sorted(h.worktrees.removed) == sorted(str(devdag.worktree_path(ws, i)) for i in range(4))
    for node in dag["nodes"]:
        assert node["worktree"] == ""
        assert node["endCommit"] != node["startCommit"]


@pytest.mark.asyncio
async def test_a_web_node_waits_for_its_own_api_merge_then_starts_from_it(ws: Path, monkeypatch):
    """web 节点在自己的 api **合进主目录之后**才开始，且从合并之后的 HEAD 拉。

    并行度放到 4 是为了让「不等」变得可能：不守依赖的话四个节点会一起派出去，前端
    调的接口还躺在别人的分支上。所以断的是时间线顺序，不是最终状态 —— 最终状态在
    两种跑偏下都是一片绿。
    """
    h = _par_harness(ws, monkeypatch, env="4")
    await h.run.start(PAGES)
    await h.finish()

    tl = h.worktrees.timeline
    bases = {branch: base for _path, branch, base in h.worktrees.added}
    # 合并落地的顺序（并行度 4 时两个 api 谁先合是调度决定的，所以不能按序号写死）
    merge_order = [head for _branch, head in h.git.merges]
    merged_head = dict(h.git.merges)
    for api_index, web_index in ((0, 1), (2, 3)):
        api_branch = devdag.branch_name(IDS[api_index])
        # 自己那一个 api 合并之前，它的 web 会话一次都没进过 dispatch
        assert tl.index(f"merge:{api_branch}") < tl.index(f"start:{SLOT_NAMES[web_index]}"), tl
        # web 的 worktree 拉的是**合并之后**的主目录 HEAD，不是轮次开始那一刻的 c0
        # —— 从 c0 拉等于在需求文档上重写，接口一行都没有。晚于自己那个 api 的合并
        # 即可：期间若兄弟的合并也落了地，那一部分代码 web 也一起拿到，是对的。
        base = bases[devdag.branch_name(IDS[web_index])]
        assert base in merge_order, bases
        assert merge_order.index(base) >= merge_order.index(merged_head[api_branch]), bases
    # 两个 api 谁都不等谁，各自从轮次开始时的 HEAD 拉
    assert [bases[devdag.branch_name(k)] for k in IDS[::2]] == ["c0", "c0"]
    assert h.run.get()["runState"] == "done"


@pytest.mark.asyncio
async def test_a_merge_conflict_fails_that_node_and_keeps_its_worktree(ws: Path, monkeypatch):
    """合并冲突 → 该节点 failed，原因「合并冲突：<文件>」，worktree 留着。

    先只放开那个会冲突的节点，等它判完再放开兄弟 —— 顺序不钉住的话，兄弟节点跑完
    后循环会顺手派下一批，「后继有没有被派」就变成看调度运气了。三个后遗都断：后
    续节点不再派（没合进去的接口，前端拿什么调）；在跑的兄弟不被取消，各归各的状
    态；目录不回收 —— 现场就在 ``.ai-studio/wt/<序号>``，人 cd 进去看得完，而「保留
    worktree 供人看」是派工单写死的。
    """
    h = _par_harness(ws, monkeypatch)
    conflict_branch = devdag.branch_name(IDS[0])
    h.worktrees.conflicts[conflict_branch] = ("src/api/device.ts", "src/db.ts")
    jira = JiraSpy().install(monkeypatch)
    h.gates = {SLOT_NAMES[0]: asyncio.Event(), SLOT_NAMES[2]: asyncio.Event()}

    await h.run.start(PAGES)
    h.gates[SLOT_NAMES[0]].set()  # the conflicting one goes first
    await _wait_until(
        "the conflicting node judged failed", lambda: h.run._data()["nodes"][0]["state"] == "failed"
    )
    h.gates[SLOT_NAMES[2]].set()
    await h.finish()

    dag = h.run.get()
    by_key = _nodes_by_key(dag)
    assert dag["runState"] == "failed"
    assert by_key[IDS[0]]["state"] == "failed"
    assert by_key[IDS[0]]["message"] == "合并冲突：src/api/device.ts、src/db.ts"
    # 现场留着：这一格还写着路径，目录也没被回收
    assert by_key[IDS[0]]["worktree"] == str(devdag.worktree_path(ws, 0))
    assert str(devdag.worktree_path(ws, 0)) not in h.worktrees.removed
    # 后继永远排不进来，一次都没派
    assert by_key[IDS[1]]["state"] == "queued"
    assert SLOT_NAMES[1] not in [key for key, _ in h.calls]
    # 兄弟节点照跑完（不取消正在写代码的会话），但整轮仍是 failed
    assert by_key[IDS[2]]["state"] == "done"
    assert by_key[IDS[3]]["state"] == "queued"
    # 失败的那张单子只评论、不流转成完成（Jira 里它就该还挂在「进行中」）。
    # 断的是**那一张**的流转记录：兄弟节点跑完了，它自己的单子照流转，所以「全部
    # transitions 里没有 done」会把正常行为也算成 bug。
    failed_issue = by_key[IDS[0]]["jira"]
    assert jirasync.done_state() not in [to for key, to in jira.transitions if key == failed_issue]
    assert any("合并冲突" in text for key, text in jira.comments if key == failed_issue)
    # 主目录没被写坏：兄弟的合并照常进得去
    assert devdag.branch_name(IDS[2]) in [b for b, _ in h.worktrees.merged]


@pytest.mark.asyncio
async def test_parallel_one_runs_in_the_main_directory_with_no_worktree(ws: Path, monkeypatch):
    """``AI_STUDIO_DEV_PARALLEL=1`` 退回串行：一个 worktree 都不建，一次跑一个。

    这条是「可回退」的凭据，不是一个开关的名字。断的是**一次都没调** worktree 相
    关函数、会话的 cwd 就是主目录、顺序回到计划顺序 —— 出问题时把环境变量设成 1
    就能拿到改造前的行为，这比加一个「禁用并行」的开关值钱。
    """
    h = _par_harness(ws, monkeypatch, env="1")
    await h.run.start(PAGES)
    await h.finish()

    dag = h.run.get()
    assert dag["runState"] == "done"
    assert h.worktrees.added == []
    assert h.worktrees.merged == []
    assert h.worktrees.excludes == 0
    assert [key for key, _ in h.calls] == SLOT_NAMES
    for slot in h.state._slots.values():
        assert str(slot.project) == str(ws)
    for node in dag["nodes"]:
        assert node["worktree"] == ""


@pytest.mark.asyncio
async def test_the_file_never_shows_a_node_queued_while_its_dir_is_built(ws: Path, monkeypatch):
    """派出去就落盘 running：建 worktree 的那一刻，状态文件里它已经是 running。

    要钉的是「决定派它」和「文件说它在跑」之间不许有时间差。这个差有多长不由代码
    决定，由 ``git worktree add`` 决定 —— 真实工作区里几秒。差之内的崩溃会被
    :meth:`get` 的孤儿改判读成什么，取决于文件里写了什么：写着 running ⇒「网关重启，
    中断」，重试这一个节点（对）；写着 queued ⇒ 它从没开始过，可盘上已经多了一条分支
    和一个目录（更糟，而且没人知道）。所以在**建目录的那一刻**读盘（真 git 也就是这
    个时机），读到的必须已经是 running。
    """
    h = _par_harness(ws, monkeypatch)
    h.worktrees.probe = lambda: {str(n["jiraKey"]): str(n["state"]) for n in h.run._data()["nodes"]}

    await h.run.start(PAGES)
    await h.finish()

    assert len(h.worktrees.states_at_add) == 4
    for branch, states in h.worktrees.states_at_add:
        key = next(k for k in IDS if devdag.branch_name(k) == branch)
        assert states[key] == "running", (branch, states)
    assert h.run.get()["runState"] == "done"


@pytest.mark.asyncio
async def test_a_second_start_cannot_slip_in_between_two_dispatches(ws: Path, monkeypatch):
    """两个节点都在跑时再点〔开始开发〕= 409，且一个字节都没改。

    互斥靠的是文件里的 ``runState=running``（:meth:`start` 读盘判的就是它），不是内存
    里的循环对象 —— 网关重启之后内存什么都没有，文件还在。并行让这一条更值得单独测
    一次：在跑的对象从 1 个变成 limit 个，而派工之间的窗口是新的（串行时循环全程只有
    一个节点在跑，没有「刚派完一个还剩名额」的时刻）。挡不住的后果是两个循环、两套
    worktree、同一个 ``.git``。
    """
    h = _par_harness(ws, monkeypatch)
    h.gates = {SLOT_NAMES[0]: asyncio.Event(), SLOT_NAMES[2]: asyncio.Event()}
    await h.run.start(PAGES)
    await _wait_until("both api sessions dispatched", lambda: len(h.calls) >= 2)
    before = h.run._data()
    assert [n["state"] for n in before["nodes"]] == ["running", "queued", "running", "queued"]

    with pytest.raises(devdag.DevDagError) as exc:
        await h.run.start(PAGES)
    assert (exc.value.code, exc.value.status) == ("run_active", 409)
    assert h.run._data()["nodes"] == before["nodes"]

    for gate in h.gates.values():
        gate.set()
    await h.finish()
    assert h.run.get()["runState"] == "done"
    # 挡下来的那一次没有留下第二个循环：一个任务一次会话，一个合并
    assert [key for key, _ in h.calls].count(SLOT_NAMES[0]) == 1
    assert len(h.worktrees.merged) == 4
