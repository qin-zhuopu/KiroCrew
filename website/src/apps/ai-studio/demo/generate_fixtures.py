#!/usr/bin/env python3
"""Generate the AI Studio demo fixtures and step scripts.

The demo replays a business-event state machine (docs/guides/
ai-studio-demo-methodology.md); every step carries a complete, replayable
state snapshot — no reverse computation. A version row's unified diff MUST be
byte-identical to what the real backend returns (`projects.list_versions`
computes it with `difflib.unified_diff`), and a JS re-implementation of
difflib would drift. So the snapshots are generated HERE — same difflib, same
`previous`/`current` labels as the store — and emitted as literal JSON the
browser only reads.

This file is the single source of truth for the demo's documents and
timelines. Edit the model below, then re-run:

    python3 website/src/apps/ai-studio/demo/generate_fixtures.py

It rewrites `fixtures/*.json` and `steps/*.json` deterministically, so a
re-run with an unchanged model is a no-op and a changed model is a
reviewable diff.
"""

from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
STEPS = HERE / "steps"


def unified_diff(old: str, new: str) -> str:
    """The store's diff computation verbatim (projects._unified_diff)."""
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile="previous",
            tofile="current",
        )
    )


class Doc:
    """One document's committed content plus its version trail (oldest first).

    `commit` appends a full-text snapshot like the store's `save_doc`: row N
    diffs against row N-1, the first row against the empty baseline (so it
    reads as wholly added).
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.committed = ""
        self.seen: list[tuple[int, str]] = []
        self._prev = ""

    def seed(self, content: str, ts: int) -> None:
        self.commit(content, ts)

    def commit(self, content: str, ts: int) -> None:
        if content == self._prev:
            return  # the store dedupes a same-content re-commit
        self.committed = content
        self.seen.append((ts, content))
        self._prev = content

    def rows(self) -> list[dict[str, Any]]:
        out = []
        prev = ""
        for ts, content in self.seen:
            out.append({"name": f"{ts}.md", "time": ts, "diff": unified_diff(prev, content)})
            prev = content
        return list(reversed(out))  # newest first, as the API returns


class Project:
    def __init__(self, pid: str, name: str, description: str, created: int) -> None:
        self.id = pid
        self.name = name
        self.description = description
        self.created = created
        self.docs: dict[str, Doc] = {}

    def doc(self, name: str) -> Doc:
        return self.docs.setdefault(name, Doc(name))

    def snapshot(
        self,
        focus: str,
        buffer: str,
        drafts: list[tuple[int, str]],
        graph: "dict[str, Any] | None" = None,
        graph_delta: "dict[str, list[str]] | None" = None,
        release: "dict[str, Any] | None" = None,
        generated_files: "list[dict[str, str]] | None" = None,
        generated_from: "str | None" = None,
    ) -> dict[str, Any]:
        """One replayable state: every doc's committed content, the focused
        doc's editor buffer, and its draft records (newest first). `graph`
        (ACP-729) carries the requirement graph as the snapshot froze it;
        `graph_delta` names what this snapshot's STORY added — the step
        generator cross-checks it against the previous snapshot, so the
        "new in this commit" highlight is a derived fact, never a wish.
        `release` + `generated_files` (ACP-730) carry a cut version and the
        code it generated; `generated_from` names the snapshot whose
        graphDelta those files must trace back to, so "generated code matches
        the graph change" is checked against data, not asserted in prose."""
        snap: dict[str, Any] = {
            "project": {
                "id": self.id,
                "name": self.name,
                "description": self.description,
                "createdAt": self.created,
            },
            "focusDoc": focus,
            "buffer": buffer,
            "docs": [{"name": d.name, "content": d.committed} for d in self.docs.values()],
            "draftVersions": [
                {"name": focus, "time": ts, "content": c} for ts, c in reversed(drafts)
            ],
            "versions": {d.name: d.rows() for d in self.docs.values()},
        }
        if graph is not None:
            snap["graph"] = graph
            if graph_delta is not None:
                snap["graphDelta"] = graph_delta
        if release is not None:
            snap["release"] = release
        if generated_files is not None:
            snap["generatedFiles"] = generated_files
            # the audit anchor: which snapshot's graphDelta these files must
            # trace back to. Carried in the fixture so a future reader sees
            # the claim, and check_codegen() below proves it.
            if generated_from is not None:
                snap["generatedFrom"] = generated_from
        return snap


# ---------------------------------------------------------------------------
# The demo world: three projects, three states of the editor trio
# (dates fixed — a fixture is a recording, not a clock read).
# ---------------------------------------------------------------------------

T0 = 1758600000  # 2026-09-23 00:00 UTC-ish; stable across runs

# ---- main line: 会员积分系统 (committed twice, then edited & committed) ----

main = Project("demo-membership-points", "会员积分系统", "签到、消费返积分、积分兑换闭环", T0)
req = main.doc("requirements.md")
main.doc("workflow.md").seed(
    "# 会员积分系统 流程设计\n\n## 阶段划分\n\n"
    "| 阶段 | 负责人 | 产出 |\n| --- | --- | --- |\n| 需求确认 | 产品 | requirements.md |\n\n"
    "## 流转规则\n\n- 积分规则变更需产品与运营双确认\n",
    T0,
)
main.doc("ui-spec.md").seed("# 会员积分系统 界面设计\n\n## 页面清单\n\n- 积分中心页\n- 兑换记录页\n", T0)

REQ_V1 = """# 会员积分系统 需求说明

> 签到、消费返积分、积分兑换闭环

## 目标

- 上线积分中心页，支持签到与消费返积分

## 范围

- 包含：积分获取、积分兑换、积分过期提醒
- 不包含：积分转赠

## 验收标准

- [ ] 每日签到 +5 积分
- [ ] 消费 1 元返 1 积分
"""

REQ_V2 = REQ_V1.replace(
    "- [ ] 消费 1 元返 1 积分\n",
    "- [ ] 消费 1 元返 1 积分\n- [ ] 积分满 100 可兑换 5 元优惠券\n",
)

REQ_EDIT = REQ_V2.replace(
    "- [ ] 积分满 100 可兑换 5 元优惠券\n",
    "- [ ] 积分满 100 可兑换 5 元优惠券\n- [ ] 优惠券 7 天内有效，过期自动退回积分\n",
).replace(
    "- 不包含：积分转赠\n",
    "- 不包含：积分转赠、积分抵现\n",
)

req.seed(REQ_V1, T0 - 2 * 86400)   # v1 committed two days ago
req.commit(REQ_V2, T0 - 86400)     # v1.5 committed yesterday
# then: user edits REQ_V2 -> REQ_EDIT (the main line replays this), autosaves,
# and finally commits REQ_EDIT (v3). The step models mutate a live Doc below.

# ---- the requirement graph the commits feed (ACP-729) -----------------------
# Shaped exactly like StudioGraph in studioApi.ts. GRAPH_BEFORE is the state
# after v2 (the story's starting graph); GRAPH_AFTER is what the v3 commit fed
# back in — the v3 lines added 「优惠券 7 天内有效」 and the 「积分抵现」
# exclusion, so exactly two requirement nodes and their doc/module edges are
# new. The generator refuses a delta that is not the true set difference.

def _node(nid: str, label: str, kind: str, doc: "str | None" = None) -> dict[str, Any]:
    n: dict[str, Any] = {"id": nid, "label": label, "kind": kind}
    if doc is not None:
        n["doc"] = doc
    return n

def _edge(frm: str, to: str, kind: str) -> dict[str, str]:
    return {"from": frm, "to": to, "kind": kind}

GRAPH_BEFORE: dict[str, Any] = {
    "nodes": [
        _node("req-signin", "每日签到返积分", "requirement", "requirements.md"),
        _node("req-consume", "消费返积分", "requirement", "requirements.md"),
        _node("req-redeem", "积分兑换优惠券", "requirement", "requirements.md"),
        _node("doc-requirements", "requirements.md", "doc"),
        _node("doc-workflow", "workflow.md", "doc"),
        _node("mod-points-center", "积分中心模块", "module"),
    ],
    "edges": [
        _edge("req-signin", "doc-requirements", "trace"),
        _edge("req-consume", "doc-requirements", "trace"),
        _edge("req-redeem", "doc-requirements", "trace"),
        _edge("req-signin", "mod-points-center", "depends"),
        _edge("req-redeem", "mod-points-center", "depends"),
    ],
}

GRAPH_AFTER: dict[str, Any] = {
    "nodes": GRAPH_BEFORE["nodes"] + [
        _node("req-coupon-expiry", "优惠券 7 天有效期", "requirement", "requirements.md"),
        _node("req-no-cash-offset", "积分不可抵现", "requirement", "requirements.md"),
    ],
    "edges": GRAPH_BEFORE["edges"] + [
        _edge("req-coupon-expiry", "doc-requirements", "trace"),
        _edge("req-no-cash-offset", "doc-requirements", "trace"),
        _edge("req-coupon-expiry", "mod-points-center", "depends"),
        _edge("req-no-cash-offset", "mod-points-center", "depends"),
    ],
}

# ---- the release and the code it generated (ACP-730) ------------------------
# v3 froze the two lines the story typed, and the graph grew the two matching
# requirement nodes (main-009's delta). The release generates code FOR those
# two requirements — every file's derivedFrom is a subset of that delta, so
# the release's whole output traces back to the commit's own graph change.
# The story's endpoint: 需求 → 图谱 → 代码.

RELEASE_V3: dict[str, Any] = {
    "version": "v3",
    "time": T0 + 172800 + 1800,
    "notes": "冻结 v3：优惠券有效期与积分抵现排除项",
}

GENERATED_FILES: list[dict[str, Any]] = [
    {
        "path": "points/coupon.py",
        "language": "python",
        "derivedFrom": ["req-coupon-expiry"],
        "content": (
            "# generated from 需求图谱 · 优惠券 7 天有效期\n"
            "from datetime import timedelta\n"
            "\n"
            "COUPON_TTL = timedelta(days=7)\n"
            "\n"
            "def is_expired(coupon, now):\n"
            "    return now - coupon.issued_at > COUPON_TTL\n"
        ),
    },
    {
        "path": "points/refund.py",
        "language": "python",
        "derivedFrom": ["req-coupon-expiry"],
        "content": (
            "# generated from 需求图谱 · 优惠券 7 天有效期\n"
            "from points.coupon import is_expired\n"
            "\n"
            "def settle_expired(coupon, now):\n"
            "    if not is_expired(coupon, now):\n"
            "        return 0\n"
            "    refund_points(coupon.cost_points)  # 过期自动退回积分\n"
            "    return coupon.cost_points\n"
        ),
    },
    {
        "path": "points/pay.py",
        "language": "python",
        "derivedFrom": ["req-no-cash-offset"],
        "content": (
            "# generated from 需求图谱 · 积分不可抵现\n"
            "PAYMENT_METHODS = (\"cash\", \"card\")  # 不含 points：积分抵现不在范围\n"
        ),
    },
    {
        "path": "points/schema.sql",
        "language": "sql",
        "derivedFrom": ["req-coupon-expiry", "req-no-cash-offset"],
        "content": (
            "-- generated from 需求图谱 · 优惠券 7 天有效期 / 积分不可抵现\n"
            "CREATE TABLE coupon (\n"
            "    id INTEGER PRIMARY KEY,\n"
            "    cost_points INTEGER NOT NULL,\n"
            "    issued_at TIMESTAMP NOT NULL,\n"
            "    expires_at TIMESTAMP AS (issued_at + INTERVAL 7 DAY)\n"
            ");\n"
        ),
    },
]

# ---- branch A: App 官网改版 (half-done draft, restore branch) ---------------

site = Project("demo-website-revamp", "App 官网改版", "品牌升级：官网首屏与信息架构重做", T0 - 3 * 86400)
site_req = site.doc("requirements.md")
site.doc("ui-spec.md").seed("# App 官网改版 界面设计\n\n## 页面清单\n\n- 首页（新品牌视觉）\n- 下载引导页\n", T0 - 3 * 86400)

SITE_V1 = """# App 官网改版 需求说明

> 品牌升级：官网首屏与信息架构重做

## 目标

- 首屏传达新品牌视觉
- 下载入口一屏可见

## 范围

- 包含：首页、产品页、下载页
- 不包含：后台管理系统
"""

SITE_D1 = SITE_V1 + "\n## 草稿：首屏文案\n\n- 主标题候选 A：让协作更自然\n"
SITE_D2 = SITE_V1 + "\n## 草稿：首屏文案\n\n- 主标题候选 B：把团队装进口袋\n- 副标题：随时随地，与 AI 协作\n"

site_req.seed(SITE_V1, T0 - 3 * 86400)

# ---- branch B: 空项目示例 (seed docs only — everything grey) -----------------

empty = Project("demo-empty-project", "空项目示例", "刚创建、从未编辑过的项目", T0 - 86400)
empty.doc("requirements.md").committed = (
    "# 空项目示例 需求说明\n\n> 刚创建、从未编辑过的项目\n\n"
    "## 目标\n\n- （待补充：这个项目要解决什么问题）\n"
)
empty.doc("workflow.md").committed = "# 空项目示例 流程设计\n\n## 阶段划分\n\n- （待补充）\n"
empty.doc("ui-spec.md").committed = "# 空项目示例 界面设计\n\n## 页面清单\n\n- （待补充：页面与入口）\n"


# ---------------------------------------------------------------------------
# Snapshots — one per step. Building them walks the state machine once, in
# the order the script replays it; each step then OWNS its snapshot (next =
# load state n+1, prev = load state n-1 — never recompute).
# ---------------------------------------------------------------------------

SNAPS: dict[str, dict[str, Any]] = {}


def add(key: str, snap: dict[str, Any]) -> None:
    assert key not in SNAPS
    SNAPS[key] = snap


# main line -------------------------------------------------------------------
# main-001..003: nothing touched yet (the trail already holds v1, v2). The
# main line carries its requirement graph in EVERY snapshot (ACP-729): the
# panel is part of this world from the first frame, stable at six nodes until
# the commit feeds the story's only graph change (main-009).
add("main-001", main.snapshot("requirements.md", REQ_V2, [], graph=GRAPH_BEFORE))
add("main-002", main.snapshot("requirements.md", REQ_V2, [], graph=GRAPH_BEFORE))
add("main-003", main.snapshot("requirements.md", REQ_V2, [], graph=GRAPH_BEFORE))
# main-004: the user appended two lines. ACP-728: the FIRST uncommitted
# change lands its draft record immediately (the debounce only covers
# subsequent input), so a dirty buffer never rides with an empty history —
# the invariant the store now guarantees and every dirty snapshot carries.
add("main-004", main.snapshot("requirements.md", REQ_EDIT, [(T0 + 172800, REQ_EDIT)], graph=GRAPH_BEFORE))
# main-005: idling past the debounce adds nothing (dedupe: identical to the
# newest record). The record count is the state; the step only opens the
# panel that reads it.
add("main-005", main.snapshot("requirements.md", REQ_EDIT, [(T0 + 172800, REQ_EDIT)], graph=GRAPH_BEFORE))
# main-006/007: same state; the steps only change what the overlay opens.
add("main-006", main.snapshot("requirements.md", REQ_EDIT, [(T0 + 172800, REQ_EDIT)], graph=GRAPH_BEFORE))
add("main-007", main.snapshot("requirements.md", REQ_EDIT, [(T0 + 172800, REQ_EDIT)], graph=GRAPH_BEFORE))
# main-008: the commit. The store moved the buffer into docs/ and versions/
# (v3) and deleted the drafts — the snapshot below shows exactly that.
req.commit(REQ_EDIT, T0 + 172800)
add("main-008", main.snapshot("requirements.md", REQ_EDIT, [], graph=GRAPH_BEFORE))
# main-009: the graph the commit fed (ACP-729 — the loop closes where it
# started: the commit's whole purpose is to update the requirement graph).
# The delta is exactly what the v3 lines talk about: two new requirement
# nodes, each tracing to the doc that produced them.
add(
    "main-009",
    main.snapshot(
        "requirements.md",
        REQ_EDIT,
        [],
        graph=GRAPH_AFTER,
        graph_delta={
            "nodes": ["req-coupon-expiry", "req-no-cash-offset"],
            "edges": [
                "req-coupon-expiry->doc-requirements",
                "req-no-cash-offset->doc-requirements",
                "req-coupon-expiry->mod-points-center",
                "req-no-cash-offset->mod-points-center",
            ],
        },
    ),
)
# main-010: the release cut from v3 and the code it generated from the graph
# (ACP-730 — the journey's endpoint: 需求 → 图谱 → 代码). The graph stands at
# GRAPH_AFTER (no new delta — the release reads the graph, it does not grow
# it); the release carries v3, and the four generated files each name which
# requirement node they implement. generatedFrom="main-009" pins that every
# file traces to main-009's graph delta — checked at generation, never in
# prose. This is one landed snapshot: the finished generation is the frame,
# not a fake timer counting up inside a business component (§6).
add(
    "main-010",
    main.snapshot(
        "requirements.md",
        REQ_EDIT,
        [],
        graph=GRAPH_AFTER,
        release=RELEASE_V3,
        generated_files=GENERATED_FILES,
        generated_from="main-009",
    ),
)

# branch A --------------------------------------------------------------------
# The honest chain (same rhythm as the main line): enter clean → type draft
# A → autosave it → extend to draft B → autosave → open history → pick the
# OLDER record and restore → the restored text is recorded as a third entry
# (dedupe only compares against the newest record, and the newest was B).
add("alt1-001", site.snapshot("requirements.md", SITE_V1, []))
# alt1-002: candidate A typed — and under ACP-728 its record landed the
# moment the buffer first changed (immediate first save, the debounce only
# covers the input after it). alt1-003 is the same state with the panel
# opened: idling past the debounce adds nothing (dedupe).
add("alt1-002", site.snapshot("requirements.md", SITE_D1, [(T0 + 1800, SITE_D1)]))
add("alt1-003", site.snapshot("requirements.md", SITE_D1, [(T0 + 1800, SITE_D1)]))
# alt1-004: candidate B — again the record lands with the change itself
# (each demo step re-enters through the snapshot load, so the typed buffer
# is a first change: immediate save). alt1-005 is the same state with the
# panel open; idling dedupes.
add("alt1-004", site.snapshot("requirements.md", SITE_D2, [(T0 + 1800, SITE_D1), (T0 + 3600, SITE_D2)]))
add("alt1-005", site.snapshot("requirements.md", SITE_D2, [(T0 + 1800, SITE_D1), (T0 + 3600, SITE_D2)]))
# the restore lands on the older record's text — an edit, not a commit, so
# the two records stand and the baseline is unmoved.
add("alt1-006", site.snapshot("requirements.md", SITE_D1, [(T0 + 1800, SITE_D1), (T0 + 3600, SITE_D2)]))
add(
    "alt1-007",
    site.snapshot(
        "requirements.md",
        SITE_D1,
        [(T0 + 1800, SITE_D1), (T0 + 3600, SITE_D2), (T0 + 7200, SITE_D1)],
    ),
)

# branch B --------------------------------------------------------------------
# Everything grey, three explanations of the same frozen state.
add("alt2-001", empty.snapshot("requirements.md", empty.docs["requirements.md"].committed, []))
add("alt2-002", empty.snapshot("requirements.md", empty.docs["requirements.md"].committed, []))
add("alt2-003", empty.snapshot("requirements.md", empty.docs["requirements.md"].committed, []))


# ---------------------------------------------------------------------------
# Step scripts. before/after are DERIVED from the snapshots, so a script can
# never claim a state its fixture does not carry (the assertion list the
# Playwright spec checks is literally this derivation).
# ---------------------------------------------------------------------------


def derive(snap: dict[str, Any]) -> dict[str, Any]:
    focus = snap["focusDoc"]
    committed = next(d["content"] for d in snap["docs"] if d["name"] == focus)
    dirty = snap["buffer"] != committed
    drafts = len(snap["draftVersions"])
    versions = len(snap["versions"][focus])
    state: dict[str, Any] = {
        "doc": focus,
        "dirty": dirty,
        "diffIcon": "active" if dirty else "gray",
        "draftRecords": drafts,
        "historyIcon": "list" if drafts else "gray",
        "versions": versions,
        "versionsIcon": "list" if versions else "gray",
    }
    # the graph vocabulary (ACP-729) only exists for worlds that carry a
    # graph: a snapshot without one keeps speaking the seven fields above.
    if "graph" in snap:
        state["graphNodes"] = len(snap["graph"]["nodes"])
        state["graphAddedNodes"] = len(snap.get("graphDelta", {}).get("nodes", []))
        # the release vocabulary (ACP-730) rides the same gate: the release
        # story lives wherever there is a graph to cut from, so every step of
        # that world states released/generatedFiles (false/0 until the cut).
        state["released"] = snap.get("release") is not None
        state["generatedFiles"] = len(snap.get("generatedFiles", []))
    return state


# ---------------------------------------------------------------------------
# The seven-field acceptance structure (T10 / ACP-732)
# ---------------------------------------------------------------------------
# 出处：《AI-Coding 平台-验收文档》(raw/AI-Coding平台-验收文档.zip) 的统一步骤
# 结构——从哪里开始 → 用户做什么 → 去了哪里 → 用户看到什么 → 页面有什么变化 →
# 后台发生什么 → 怎样算通过。其中「页面有什么变化」就是既有的 before/after
# 状态迁移（三件套字段保留），其余六字段全部由派生数据拼装，不手写第二份
# 事实：startFrom 由 before 观测派生，userAction=现有事件，goesTo=高亮目标
# 的视图名，userSees=现有提示文案，backendFact 由前后快照的观测差派生，
# passCriteria 由 after 观测逐项生成（预检逐条校验，剧本测试逐条消费）。
TARGET_VIEW: dict[str, str] = {
    "doc_editor": "文档编辑器",
    "version_view": "版本历史里的版本详情",
    "diff_btn": "工具栏的 diff 图标",
    "draft_history_list": "修改历史面板",
    "diff_dialog": "红绿 diff 弹窗",
    "commit_summary": "顶栏的待提交汇总",
    "version_history_list": "版本历史面板",
    "graph_view": "页底需求图谱面板",
    "codegen_view": "发版徽章与生成代码面板",
    "toolbar_trio": "工具栏三图标",
}
OBS_LABELS: dict[str, str] = {
    "dirty": "编辑器脏态（有未提交修改）",
    "draftRecords": "草稿记录数",
    "versions": "已提交版本数",
    "diffDisabled": "diff 图标置灰",
    "historyDisabled": "修改历史图标置灰",
    "graphNodes": "图谱节点总数",
    "graphAddedNodes": "本次新增图谱节点数",
    "released": "已发版",
    "generatedFiles": "生成代码文件数",
}
# the observable reading of a declared state — exactly the keys the script
# test's readState() mirrors, so a criterion is always checkable on the DOM
OBS_FIELDS = list(OBS_LABELS)
ICON_LABELS = {"gray": "灰", "active": "亮", "list": "列表"}


def observables(state: dict[str, Any]) -> dict[str, Any]:
    """Map a derived state (icon vocabulary) onto the observable reading the
    test compares against (disabled flags). Mirrors demoScript.test.tsx's
    declared() — keep the two in lockstep."""
    out: dict[str, Any] = {
        "dirty": state["dirty"],
        "draftRecords": state["draftRecords"],
        "versions": state["versions"],
        "diffDisabled": state["diffIcon"] == "gray",
        "historyDisabled": state["historyIcon"] == "gray",
    }
    if "graphNodes" in state:
        out["graphNodes"] = state["graphNodes"]
        out["graphAddedNodes"] = state["graphAddedNodes"]
        out["released"] = state["released"]
        out["generatedFiles"] = state["generatedFiles"]
    return out


def _fmt(v: Any) -> str:
    if isinstance(v, bool):
        return "是" if v else "否"
    return ICON_LABELS.get(v, str(v))  # type: ignore[arg-type]


def derive_backend_fact(fixture: str, before: dict[str, Any], after: dict[str, Any]) -> str:
    """「后台发生什么」= the snapshot layer's own difference, sentence-cased.
    Derived, so it can never claim a record count the states do not hold."""
    ob, oa = observables(before), observables(after)
    # worlds without the graph vocabulary simply do not speak those fields
    fields = [k for k in OBS_FIELDS if k in ob and k in oa]
    parts = [f"{OBS_LABELS[k]} {_fmt(ob[k])}→{_fmt(oa[k])}" for k in fields if ob[k] != oa[k]]
    if not parts:
        return f"后台（快照 {fixture}）：状态层无变化，仅展示层落位"
    return f"后台（快照 {fixture}）：" + "；".join(parts)


def derive_pass_criteria(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    """「怎样算通过」= this step's assertion list, generated from the after
    observation. Criteria are the observables the step actually moved; a step
    that moves nothing (entering a clean project) passes on the core reading,
    so the list is never empty and every entry is checkable on the real DOM."""
    ob, oa = observables(before), observables(after)
    fields = [k for k in OBS_FIELDS if k in ob and k in oa]
    changed = [k for k in fields if ob[k] != oa[k]]
    if not changed:
        changed = ["dirty", "draftRecords", "versions"]
    return [{"field": k, "eq": oa[k], "note": OBS_LABELS[k]} for k in changed]


def check_seven(sid: str, st: dict[str, Any]) -> None:
    """Schema precheck (T10): every step carries all six authored/derived
    fields non-empty, at least one pass criterion, and every criterion names
    a field in the observable vocabulary AND equals the after observation —
    fail-fast at generation, naming the field."""
    for f in ("startFrom", "userAction", "goesTo", "userSees", "backendFact"):
        v = st.get(f)
        assert isinstance(v, str) and v.strip(), f"{sid}: 七字段缺 {f} 或为空"
    pcs = st.get("passCriteria")
    assert isinstance(pcs, list) and len(pcs) >= 1, f"{sid}: passCriteria 至少 1 条"
    oa = observables(st["after"])
    for c in pcs:
        assert c["field"] in OBS_FIELDS, f"{sid}: passCriteria 字段 {c['field']!r} 不在观测词表"
        assert c["eq"] == oa[c["field"]], (
            f"{sid}: passCriteria {c['field']}={c['eq']!r} 与 after 观测 {oa[c['field']]!r} 不一致"
        )


def step(
    sid: str,
    title: str,
    fixture: str,
    event: str,
    target: str,
    hint: str,
    open_locators: list[str] | None = None,
    branch: str | None = None,
    prev: str | None = None,
    after_fix: str | None = None,
    release_phases: "list[str] | None" = None,
    goes_to: str | None = None,
) -> dict[str, Any]:
    """One script step. `fixture` is the state the step LANDS on (after);
    `prev` is the one it starts from — the script can never claim a before
    its chain does not carry, because before(k) is derived from fixture(k-1).

    `after_fix` serves the live-act steps (main-8's real commit click): the
    step ENTERS on `fixture` but its `open` acts perform the business event
    for real, landing on `after_fix`'s state — declared, not invented: the
    next snapshot in the chain is exactly where the real click goes.
    """
    snap = SNAPS[fixture]
    before = derive(SNAPS[prev]) if prev else derive(snap)
    after = derive(SNAPS[after_fix]) if after_fix else derive(snap)
    # ACP-728 cross-check — the store now guarantees dirty ⇒ at least one
    # autosave record, so no step (its before OR its after) may claim a lit
    # diff over an empty history. A snapshot that violates it is a broken
    # model: fix the fixture, never the assertion.
    for label, st in (("before", before), ("after", after)):
        if st["dirty"] and st["draftRecords"] == 0:
            raise AssertionError(
                f"{sid}.{label}: dirty diff with 0 draft records violates the "
                "dirty⇒has-records invariant (ACP-728) — seed the snapshot"
            )
    # ACP-729 cross-check — a step that DECLARES a graph delta must actually
    # land it: the after snapshot's graph minus the before snapshot's graph is
    # exactly the declared delta (set difference on node ids and "from->to"
    # edge spellings). The highlight of "new in this commit" is only honest
    # if the snapshots' diff says so, never because a step wished it so.
    after_snap = SNAPS[after_fix or fixture]
    before_snap = SNAPS[prev] if prev else SNAPS[fixture]
    delta = after_snap.get("graphDelta")
    if delta is not None:
        ga = after_snap.get("graph") or {}
        gb = before_snap.get("graph") or {}
        real_nodes = {n["id"] for n in ga.get("nodes", [])} - {n["id"] for n in gb.get("nodes", [])}
        real_edges = {f"{e['from']}->{e['to']}" for e in ga.get("edges", [])} - {
            f"{e['from']}->{e['to']}" for e in gb.get("edges", [])
        }
        if set(delta["nodes"]) != real_nodes or set(delta["edges"]) != real_edges:
            raise AssertionError(
                f"{sid}: declared graphDelta {sorted(delta['nodes'])}/{sorted(delta['edges'])} "
                f"≠ snapshot diff {sorted(real_nodes)}/{sorted(real_edges)} — "
                "the highlight must be the snapshots' own difference"
            )
    out = {
        "id": sid,
        "title": title,
        "branch": branch,
        "fixture": fixture,
        # the live-act steps carry their landing snapshot forward, so the
        # runtime can resolve the after-state's payload (main-10's release +
        # generated files) when the real click lands; absent = the step lands
        # where it entered.
        **({"afterFix": after_fix} if after_fix else {}),
        # a release step names the labels its control walks while the real
        # click lands — presentation data the workbench forwards, never a
        # hardcoded timer inside the button.
        **({"releasePhases": release_phases} if release_phases else {}),
        # --- 三件套（保留）: 事件 + 状态迁移 + UI 反馈 ---
        "before": before,
        "action": {"event": event},
        "after": after,
        "highlight": {"target": target, "hint": hint, "open": open_locators or []},
        # --- 七字段（T10）：全部派生拼装，出处见 TARGET_VIEW 上方注释 ---
        # 从哪里开始：进入本步时状态层的读得出画面（before 观测的人话版）
        "startFrom": _start_from(before),
        # 用户做什么：既有事件描述，逐字复用，不另写一份
        "userAction": event,
        # 去了哪里：本步高亮目标所属的视图（goes_to 可覆写，默认按 target 查表）
        "goesTo": goes_to or TARGET_VIEW[target],
        # 用户看到什么：既有提示文案，逐字复用
        "userSees": hint,
        # 后台发生什么：前后快照观测差（派生）
        "backendFact": derive_backend_fact(after_fix or fixture, before, after),
        # 页面有什么变化：即上面 before/after，不重复存第三份
        # 怎样算通过：after 观测逐项生成（派生）
        "passCriteria": derive_pass_criteria(before, after),
    }
    check_seven(sid, out)
    return out


def _start_from(state: dict[str, Any]) -> str:
    """「从哪里开始」= the before observation as one readable clause — a
    rendering of derived data, so it cannot contradict the state machine."""
    ob = observables(state)
    bits = [f"{'脏' if ob['dirty'] else '干净'}", f"草稿记录 {ob['draftRecords']} 条", f"已提交 {ob['versions']} 版"]
    if "graphNodes" in ob:
        bits.append(f"图谱 {ob['graphNodes']} 节点")
        if ob["released"]:
            bits.append(f"已发版（生成 {ob['generatedFiles']} 文件）")
    return f"{state['doc']}：" + "、".join(bits)


SCRIPTS: dict[str, dict[str, Any]] = {
    "main-membership-points": {
        "scenario": "main-membership-points",
        "title": "会员积分系统：编辑 → 自动保存 → 提交闭环",
        "project": main.id,
        "steps": [
            step(
                "main-1",
                "进入项目，打开需求文档",
                "main-001",
                "打开「会员积分系统」，requirements.md 已在编辑器打开",
                "doc_editor",
                "当前：requirements.md 已打开，处于「干净」态——diff 与修改历史图标是灰的（当前内容==最近提交，0 条未提交修改）；版本历史图标是亮的（已提交 2 版）。",
            ),
            step(
                "main-2",
                "版本历史：看最新一版（v2）的增量 diff",
                "main-002",
                "点开工具栏「版本历史」，选最新一行",
                "version_view",
                "当前：v2 相对 v1 的 unified diff——新版只加了一行兑换规则（绿行），v1 的内容原样保留。",
                ["versions_btn", "version_row:newest"],
                prev="main-001",
                
            ),
            step(
                "main-3",
                "版本历史：最早版本（v1）整篇按新增展示",
                "main-003",
                "（返回编辑）再开「版本历史」选最早一行",
                "version_view",
                "当前：v1 没有前驱版本，diff 引擎拿空基线比对，整篇读作新增——最早版本的诚实形状，不是错误。上一步的只读视图已随步骤切换自动退出（每步整体换快照、整体重挂载）。",
                ["versions_btn", "version_row:oldest"],prev="main-002",
                
            ),
            step(
                "main-4",
                "用户追加两行验收标准（快照重放）",
                "main-004",
                "在编辑器追加两行验收标准——首次变更立即落一条草稿记录",
                "diff_btn",
                "当前：缓冲已变（追加了优惠券有效期与「积分抵现」排除项），页脚提示未保存，diff 图标由灰转亮。规则：diff 亮必有记录——首次变更立即自动保存落第一条记录，不存在「diff 亮着、修改历史 0 条」的窗口。",
                ["markdown_toggle", "set_buffer"],prev="main-003",

            ),
            step(
                "main-5",
                "停手 2 秒：没有第二条（去重）",
                "main-005",
                "停手 2 秒，防抖到期——内容与最新记录相同，不落新条",
                "draft_history_list",
                "当前：修改历史面板 1 条记录。规则：内容与上一条相同不落新条——后续输入走 2s 防抖，且去重只比最新一条，光标再动多久都不会灌出重复记录。",
                ["markdown_toggle", "set_buffer", "draft_history_btn"],prev="main-004",

            ),
            step(
                "main-6",
                "打开红绿 diff：当前缓冲 vs 最近提交",
                "main-006",
                "点亮 diff 图标，点开「与最近提交对比」",
                "diff_dialog",
                "当前：红行是上一版内容，绿行是缓冲新增——就是刚才追加的两行。",
                ["markdown_toggle", "set_buffer", "diff_btn"],prev="main-005",
                
            ),
            step(
                "main-7",
                "确认提交范围：顶栏汇总待提交文档",
                "main-007",
                "确认红绿无误，看顶栏的待提交汇总（ACP-727 后提交是项目级操作）",
                "commit_summary",
                "当前：顶栏徽章列出了所有含未提交草稿的文档——提交喂给整个项目的需求图谱，不再是单文档操作。下一步点「提交全部」真实走一遍提交路径。",
                ["markdown_toggle", "set_buffer"],prev="main-006",

            ),
            step(
                "main-8",
                "点「提交全部」：版本 +1、修改历史清空、图标回灰",
                "main-007",
                "点顶栏「提交全部」——旧内容进版本快照、草稿记录整体清空、编辑器重挂到已提交基线",
                "version_history_list",
                "当前：提交刚真实发生（同一个顶栏按钮、同一套业务逻辑，数据来自快照 fake）——版本历史 3 版（v3 即刚才的提交），修改历史 0 条（提交即清空），diff 图标回灰——闭环走完。",
                ["markdown_toggle", "set_buffer", "commit_all_btn", "versions_btn"],
                prev="main-007",
                after_fix="main-008",

            ),
            step(
                "main-9",
                "提交喂图谱：两个新需求节点亮起",
                "main-009",
                "提交完成的同一时刻，需求图谱收到 v3 的两条新需求——闭环在开头承诺的地方合上",
                "graph_view",
                "当前：图谱 8 个节点，绿框的两个（优惠券 7 天有效期、积分不可抵现）是刚才那次提交新增的——正是 v3 新加的两行。提交不是终点：旧内容进版本快照，新需求进图谱，这才是完整的闭环。",
                None,
                prev="main-008",
            ),
            step(
                "main-10",
                "点「发版」：AI 按图谱生成代码，需求→图谱→代码收官",
                "main-009",
                "点顶栏「发版」——解析图谱 → 生成文件清单 → v3 就绪；每个文件标注它实现图谱里的哪条需求",
                "codegen_view",
                "当前：v3 已发布，4 个生成文件就位——coupon/refund 实现「优惠券 7 天有效期」、pay/schema 实现「积分不可抵现」。每个文件的来源都是图谱节点，且生成器已校验它们全部落在本次提交带来的图谱增量里：需求→图谱→代码的追溯链在这里合龙，这就是全旅程的收官镜头。",
                ["release_btn"],
                prev="main-009",
                after_fix="main-010",
                release_phases=["解析需求图谱…", "按图谱生成文件清单…", "生成完成，v3 就绪"],
            ),
        ],
    },
    "alt-1-draft-restore": {
        "scenario": "alt-1-draft-restore",
        "title": "App 官网改版：从修改历史恢复（分支 A）",
        "project": site.id,
        "steps": [
            step(
                "alt1-1",
                "进入项目：文档干净，图标是灰的",
                "alt1-001",
                "打开「App 官网改版」，requirements.md 停在最近一次提交上",
                "toolbar_trio",
                "当前：干净态——diff 与修改历史图标是灰的（当前内容==最近提交，0 条未提交记录）。这个「旧版本」就是稍后恢复要去的地方。",
                branch="alt-1",
            ),
            step(
                "alt1-2",
                "写一版首屏文案（候选 A）",
                "alt1-002",
                "在编辑器追加「首屏文案·候选 A」草稿段——首次变更立即落第一条记录",
                "doc_editor",
                "当前：缓冲比最近提交多了一段候选 A 文案，diff 图标由灰转亮；首次变更同步落了第一条草稿记录——diff 亮的那一刻起，修改历史就不是空的。",
                ["markdown_toggle", "set_buffer"],
                prev="alt1-001",
                branch="alt-1",
            ),
            step(
                "alt1-3",
                "打开修改历史：候选 A 已在列",
                "alt1-003",
                "点开修改历史面板确认记录已在（停手到期也不落重复条）",
                "draft_history_list",
                "当前：修改历史 1 条——候选 A。内容与最新一条相同不再落新条：去重只比最新一条。",
                ["markdown_toggle", "set_buffer", "draft_history_btn"],
                prev="alt1-002",
                branch="alt-1",
            ),
            step(
                "alt1-4",
                "改主意：把草稿改成候选 B",
                "alt1-004",
                "把主标题改成「候选 B」并加一行副标题——内容与最新记录不同，立刻落了第二条",
                "diff_btn",
                "当前：缓冲换成候选 B，diff 图标保持亮；B 与最新记录（A）不同，落为第二条——每一段改过的文字都没有丢。",
                ["markdown_toggle", "set_buffer"],
                prev="alt1-003",
                branch="alt-1",
            ),
            step(
                "alt1-5",
                "两条记录都在：最新在上",
                "alt1-005",
                "打开修改历史面板看两条记录",
                "draft_history_list",
                "当前：两条记录，最新在上——候选 B 在上、候选 A 在下。停手到期也不会再多落条（与最新一条相同）。",
                ["markdown_toggle", "set_buffer", "draft_history_btn"],
                prev="alt1-004",
                branch="alt-1",
            ),
            step(
                "alt1-6",
                "分支点：回到较早那条（候选 A）",
                "alt1-006",
                "打开修改历史，点较早一条（候选 A），在红绿弹窗里点「恢复到该版」",
                "doc_editor",
                "当前：缓冲回到了候选 A 的文本。恢复是编辑不是提交：最近提交不动，两条记录也还在——草稿态可以回到过去。",
                ["markdown_toggle", "set_before_buffer", "draft_history_btn", "draft_row:older", "restore_btn"],
                prev="alt1-005",
                branch="alt-1",
            ),
            step(
                "alt1-7",
                "恢复的文本再被记为第三条",
                "alt1-007",
                "又 2 秒过去，防抖把恢复后的文本记成第三条",
                "draft_history_list",
                "当前：三条记录——恢复后的候选 A 与最新一条（候选 B）不同，去重放行，落为新一条。「撤销的撤销」依然找得回。",
                ["markdown_toggle", "set_buffer", "draft_history_btn"],
                prev="alt1-006",
                branch="alt-1",
            ),
        ],
    },
    "alt-2-empty-gray": {
        "scenario": "alt-2-empty-gray",
        "title": "空项目示例：为什么图标是灰的（分支 B）",
        "project": empty.id,
        "steps": [
            step(
                "alt2-1",
                "进入刚创建的项目：三个图标全灰",
                "alt2-001",
                "打开「空项目示例」，requirements.md 只有种子内容",
                "toolbar_trio",
                "当前：diff、修改历史、版本历史三个图标全是灰的。灰不是坏了，是状态机给出的答案——下面逐个解释。",
                branch="alt-2",
            ),
            step(
                "alt2-2",
                "diff 为什么灰：当前内容==最近提交",
                "alt2-002",
                "尝试点亮 diff 图标",
                "diff_btn",
                "当前：Markdown 源视图里缓冲内容与 docs/ 里的提交内容逐字符相同，状态机判定「干净」→ diff 置灰不可点。没有差异可看时把按钮点亮，才是骗人。",
                ["markdown_toggle"],
                prev="alt2-001",
                branch="alt-2",
            ),
            step(
                "alt2-3",
                "两个历史面板为什么灰：0 条记录 / 从未提交",
                "alt2-003",
                "看修改历史与版本历史图标",
                "toolbar_trio",
                "当前：修改历史灰 = 上次提交以来 0 条自动保存；版本历史灰 = 从未提交过（空列表点开也没有行）。灰态即数据态。",
                None,
                prev="alt2-002",
                branch="alt-2",
            ),
        ],
    },
}

# `None` in an open list is a placeholder the TS side resolves per step; keep
# the generator honest by rejecting stray Nones here.
for script in SCRIPTS.values():
    for s in script["steps"]:
        s["highlight"]["open"] = [o for o in s["highlight"]["open"] if o]


# ---------------------------------------------------------------------------
# Emit
# ---------------------------------------------------------------------------


def check_graph_shape(key: str, snap: dict[str, Any]) -> None:
    """ACP-729 schema precheck: a carried graph must be well-formed — the
    StudioGraph shape (node id/label/kind, edge from/to/kind), unique node
    ids, edges only between existing nodes. A snapshot the fake cannot serve
    honestly is a broken model; fail at generation, not at presentation."""
    graph = snap.get("graph")
    if graph is None:
        return
    ids = set()
    for n in graph["nodes"]:
        assert n["kind"] in ("requirement", "doc", "module"), f"{key}: node {n['id']} kind {n['kind']!r}"
        assert n["id"] not in ids, f"{key}: duplicate node id {n['id']}"
        ids.add(n["id"])
        assert isinstance(n["label"], str) and n["label"]
        assert "doc" not in n or isinstance(n["doc"], str)
    for e in graph["edges"]:
        assert e["kind"] in ("trace", "depends"), f"{key}: edge kind {e['kind']!r}"
        assert e["from"] in ids and e["to"] in ids, f"{key}: dangling edge {e['from']}->{e['to']}"
    delta = snap.get("graphDelta")
    if delta is not None:
        assert set(delta["nodes"]) <= ids, f"{key}: delta names unknown nodes"
        known = {f"{e['from']}->{e['to']}" for e in graph["edges"]}
        assert set(delta["edges"]) <= known, f"{key}: delta names unknown edges"


def check_generated_traceability(key: str, snap: dict[str, Any]) -> None:
    """ACP-730 — the release's generated code must trace to the graph, as
    DATA. A snapshot that carries generated files also names the snapshot
    (generatedFrom) whose graph delta they implement; every file's
    derivedFrom must be a subset of THAT delta's nodes, and each file's
    source nodes must exist in the released graph. This is the traceability
    the closing shot claims — checked here, never in prose (the hint text
    describing it is only honest because this function runs)."""
    files = snap.get("generatedFiles")
    if files is None:
        return
    anchor = snap.get("generatedFrom")
    assert anchor in SNAPS, f"{key}: generatedFrom {anchor!r} names no snapshot"
    delta = SNAPS[anchor].get("graphDelta") or {}
    delta_nodes = set(delta.get("nodes", []))
    graph = snap.get("graph") or {}
    graph_nodes = {n["id"] for n in graph.get("nodes", [])}
    for f in files:
        src = set(f["derivedFrom"])
        assert src, f"{key}: file {f['path']} names no source node"
        assert src <= graph_nodes, f"{key}: file {f['path']} derives from a node absent from the released graph"
        assert src <= delta_nodes, (
            f"{key}: file {f['path']} derives from {sorted(src - delta_nodes)}, "
            f"not in {anchor}'s graph delta — generated code must trace to this release's new requirements"
        )


def dump(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main_run() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    STEPS.mkdir(parents=True, exist_ok=True)
    for key, snap in SNAPS.items():
        check_graph_shape(key, snap)
        check_generated_traceability(key, snap)
        dump(FIXTURES / f"state-{key}.json", snap)
    for name, script in SCRIPTS.items():
        dump(STEPS / f"{name}.json", script)
    print(f"wrote {len(SNAPS)} fixtures, {len(SCRIPTS)} scripts")


if __name__ == "__main__":
    main_run()
