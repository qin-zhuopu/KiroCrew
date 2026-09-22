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
import re
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
        distillation: "dict[str, Any] | None" = None,
        regeneration: "dict[str, Any] | None" = None,
        diff_groups: "list[dict[str, Any]] | None" = None,
        dev_run: "dict[str, Any] | None" = None,
        run_preview: "dict[str, Any] | None" = None,
        history: "dict[str, Any] | None" = None,
        new_round: bool = False,
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
        if distillation is not None:
            snap["distillation"] = distillation
        if regeneration is not None:
            snap["regeneration"] = regeneration
        if diff_groups is not None:
            snap["diffGroups"] = diff_groups
        if dev_run is not None:
            snap["devRun"] = dev_run
        if run_preview is not None:
            snap["runPreview"] = run_preview
        if history is not None:
            snap["history"] = history
        if new_round:
            snap["newRound"] = True
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

# ---- the distillation wave after the release (ACP-733) -----------------------
# 验收文档口径：图谱的这轮更新不是提交直接出的——发版冻结文档后，AI 把文档
# 变化「沉淀」为结构化设计事实（候选的新增/修改/删除），图谱随之更新。
# GRAPH_DISTILLED is GRAPH_AFTER with the accepted candidates applied:
# mod-coupon-service added, req-redeem's label refined, the orphan
# doc-workflow removed. check_distillation() proves every candidate's target
# landed exactly that way — the candidate list and the graph are one fact.

_DISTILL_REDEEM = _node("req-redeem", "积分兑换优惠券（7 天有效）", "requirement", "requirements.md")

GRAPH_DISTILLED: dict[str, Any] = {
    "nodes": [
        _DISTILL_REDEEM if n["id"] == "req-redeem" else n
        for n in GRAPH_AFTER["nodes"]
        if n["id"] != "doc-workflow"
    ] + [_node("mod-coupon-service", "优惠券服务模块", "module")],
    "edges": GRAPH_AFTER["edges"] + [
        _edge("req-coupon-expiry", "mod-coupon-service", "depends"),
        _edge("req-redeem", "mod-coupon-service", "depends"),
    ],
}

# the three candidates the distillation proposes (add/modify/remove, one per
# group — the acceptance doc's step-8 list). evidenceDoc names the paragraph
# each fact was distilled from; targets are machine-checked against the
# before/after graphs by check_distillation.
DISTILL_CANDIDATES: list[dict[str, Any]] = [
    {
        "id": "dc-add-coupon-service",
        "kind": "add",
        "target": "mod-coupon-service",
        "summary": "新增模块「优惠券服务」：有效期判断与过期退款都归它",
        "evidenceDoc": "requirements.md § 兑换与有效期",
    },
    {
        "id": "dc-modify-redeem",
        "kind": "modify",
        "target": "req-redeem",
        "summary": "细化「积分兑换优惠券」：兑换出的券带 7 天有效期",
        "evidenceDoc": "requirements.md § 兑换与有效期",
    },
    {
        "id": "dc-remove-workflow",
        "kind": "remove",
        "target": "doc-workflow",
        "summary": "workflow.md 仍描述旧流程且无需求挂靠，先从设计图谱移除",
        "evidenceDoc": "workflow.md § 全文",
    },
]

# the two frames of the distillation story: the run in flight (candidate list
# still empty on screen, status tells the panel "processing") and the landed
# run (candidates grouped for viewing, appliedAt set, graph already updated).
DISTILL_RUNNING: dict[str, Any] = {
    "id": "distill-v3",
    "releaseVersion": RELEASE_V3["version"],
    "status": "running",
    "candidates": [],
}

DISTILL_DONE: dict[str, Any] = {
    "id": "distill-v3",
    "releaseVersion": RELEASE_V3["version"],
    "status": "done",
    "candidates": DISTILL_CANDIDATES,
}

# the landed frame carries appliedAt with it (the run finished AND the graph
# absorbed the accepted candidates — check_distillation refuses appliedAt on
# a snapshot whose graph has not moved, and refuses an unmoved done-frame
# claiming appliedAt)
DISTILL_APPLIED: dict[str, Any] = {**DISTILL_DONE, "appliedAt": RELEASE_V3["time"] + 600}

# ---- the regeneration the applied distillation feeds (ACP-734 / T12) --------
# 验收文档口径：沉淀成结构化事实之后，系统能【从结构化数据反向重生成文档】
# （新文档版本出现并标注来自哪次沉淀），再把「用户改动 Diff + 结构化变化 +
# 重生成 Diff」按业务点成组展示——用户核对「系统理解得对不对」的关键一步。
# REQ_REGEN 是机器派生，不是第三份手写事实：细化行带着被修改节点的新标签，
# 「设计事实」段落的每一行就是新增候选的 summary——重生成内容是沉淀数据的
# 函数，check_regen() 再把成组 Diff 的行逐字节对回版本行的 diff。

REGEN_TS = DISTILL_APPLIED["appliedAt"] + 1200

_DISTILL_CAND_BY_ID = {c["id"]: c for c in DISTILL_CANDIDATES}

# the three business points the pairing shows — one per distillation
# candidate (candidateId is the traceability link; check_regen resolves each
# one and re-slices the diff texts from the snapshot's own version rows).
# keyword = the phrase that identifies the point inside a diff line.
REGEN_POINTS: list[dict[str, str]] = [
    {"candidate": "dc-add-coupon-service", "point": "优惠券服务模块", "keyword": "优惠券服务"},
    {"candidate": "dc-modify-redeem", "point": "兑换券 7 天有效", "keyword": "7 天"},
    {"candidate": "dc-remove-workflow", "point": "workflow 孤儿移除", "keyword": "workflow"},
]

_REDEEM_SUFFIX = _DISTILL_REDEEM["label"].removeprefix("积分兑换优惠券")  # （7 天有效）

REQ_REGEN = REQ_EDIT.replace(
    "- [ ] 积分满 100 可兑换 5 元优惠券\n",
    f"- [ ] 积分满 100 可兑换 5 元优惠券{_REDEEM_SUFFIX}\n",
) + (
    f"\n## 设计事实（发版沉淀 · {RELEASE_V3['version']}）\n\n"
    + "".join(
        f"- {c['summary']}\n" for c in DISTILL_CANDIDATES if c["kind"] == "add"
    )
)

REGEN: dict[str, Any] = {
    "version": "v4",
    "generatedFrom": DISTILL_APPLIED["id"],
    "docName": "requirements.md",
    "content": REQ_REGEN,
}

# ---- the development run opened on the frozen design (ACP-735 / T13) --------
# 验收文档步骤 12-15：「开始开发」不是一句口号——先立开发记录（标注所用
# 设计/图谱版本，追溯起点），再走 任务生成→实现→测试→构建 四阶段，每阶段
# 一句事实摘要，最后给出 测试报告/构建产物/可运行入口。四阶段的推进是三个
# 快照帧（running 落点→测试进行中→全部完成），不是业务组件里的假计时器；
# 自动播放逐帧走过即「过程推进」，手动步进得到逐帧相同的画面（回放一致）。
# designVersion 锚定本世界的重生成版本与沉淀 id（check_devrun 校验）；体验
# 页的功能清单逐字等于图谱的需求节点标签（同样是派生，不是文案）。

DEV_ID = "dev-v4"
DEV_RUNNABLE = "0.4.0"

def _phase(name: str, status: str, summary: str = "") -> dict[str, Any]:
    return {"name": name, "status": status, "summary": summary}

DEV_SUMMARIES: dict[str, str] = {
    "tasks": "按 v4 冻结设计拆分 5 个开发任务：有效期判断、过期退款、支付方式排除、优惠券服务、数据表",
    "implement": "实现 4 个生成文件对应的模块，优惠券服务落地 COUPON_TTL=7 天",
    "test": "23 项测试全部通过：有效期边界 6 项、过期退款 9 项、支付方式排除 8 项",
    "build": "构建产物 points-service-0.4.0 打包完成，可运行版本就绪",
}

DEV_PREVIEW_LINES: list[str] = [
    n["label"] for n in GRAPH_DISTILLED["nodes"] if n["kind"] == "requirement"
]

def _dev_run(phases: list[dict[str, Any]], artifacts: list[dict[str, str]]) -> dict[str, Any]:
    run: dict[str, Any] = {
        "id": DEV_ID,
        "designVersion": f"{REGEN['version']} · graph@{DISTILL_APPLIED['id']}",
        "phases": phases,
        "artifacts": artifacts,
    }
    if all(p["status"] == "done" for p in phases):
        run["runnableVersion"] = DEV_RUNNABLE
    return run

# the runnable experience (步骤 15): what the built-in preview screen shows
# when 「打开可运行版本」 is pressed — an internal overlay route onto this
# data, no server anywhere in the path. Its feature list is exactly the
# graph's requirement-node labels (derived above), so the experience claims
# only what the structured design holds.
RUN_PREVIEW: dict[str, Any] = {
    "version": DEV_RUNNABLE,
    "devRunId": DEV_ID,
    "title": f"{main.name} · {DEV_RUNNABLE}",
    "lines": DEV_PREVIEW_LINES,
}

DEV_ARTIFACTS: list[dict[str, str]] = [
    {"kind": "test", "path": "reports/test-v4.json"},
    {"kind": "build", "path": "dist/points-service-0.4.0.tar.gz"},
    {"kind": "runtime", "path": "runtime/points-service"},
]

# ---- the project-wide history timeline (ACP-736 / T14) ----------------------
# 验收文档步骤 16 的口径：修改/提交/发版/沉淀/开发（+运行）是 DIFFERENT 且不
# 可混淆的事实，任何一个最终结果都能沿真实引用回指到最初那次修改。时间线就
# 是一条六事件链：每个事件的 links 只指向前因（check_history 校验链接必须回
# 指、ref 必须是某个快照），点节点跳转 = 加载它 ref 命名的快照（回放铁律：
# 禁反向计算）。kind 枚举是封闭的——没有 AI 来源变体：本演示的文档修改全部
# 按人工来源建模（DAG 显式不做），所以这里也绝不新增来源枚举。

HISTORY: dict[str, Any] = {
    "events": [
        {
            "id": "he-edit",
            "kind": "edit",
            "at": T0 + 172800,
            "ref": "main-006",
            "summary": "手工修改 requirements.md：补上优惠券 7 天有效期与积分不可抵现两行",
            "links": [],
        },
        {
            "id": "he-commit",
            "kind": "commit",
            "at": T0 + 172800 + 600,
            "ref": "main-008",
            "summary": "提交为 v3：两行修改进入版本历史，草稿记录清空",
            "links": ["he-edit"],
        },
        {
            "id": "he-release",
            "kind": "release",
            "at": RELEASE_V3["time"],
            "ref": "main-010",
            "summary": "发布 v3 并生成 4 个代码文件，每个文件标注来源需求节点",
            "links": ["he-commit"],
        },
        {
            "id": "he-distill",
            "kind": "distill",
            "at": DISTILL_APPLIED["appliedAt"],
            "ref": "main-013",
            "summary": "沉淀 3 条结构化事实并被图谱吸收，重生成文档 v4",
            "links": ["he-release"],
        },
        {
            "id": "he-dev",
            "kind": "dev",
            "at": REGEN_TS + 600,
            "ref": "main-017",
            "summary": "按 v4 · graph@distill-v3 开发：四阶段全过，产物三件套就绪",
            "links": ["he-distill"],
        },
        {
            "id": "he-run",
            "kind": "run",
            "at": REGEN_TS + 1200,
            "ref": "main-018",
            "summary": "可运行版本 0.4.0 上线体验，功能清单等于图谱需求节点",
            "links": ["he-dev"],
        },
    ]
}

# the three frames of the process: the run just opened (任务生成 in flight),
# mid-run (实现 done, 测试 in flight), landed (all done, artifacts + runnable)
DEV_TASKS = _dev_run(
    [_phase("tasks", "running"), _phase("implement", "pending"),
     _phase("test", "pending"), _phase("build", "pending")],
    [],
)
DEV_TEST = _dev_run(
    [_phase("tasks", "done", DEV_SUMMARIES["tasks"]),
     _phase("implement", "done", DEV_SUMMARIES["implement"]),
     _phase("test", "running"),
     _phase("build", "pending")],
    [],
)
DEV_DONE = _dev_run(
    [_phase(name, "done", DEV_SUMMARIES[name]) for name in ("tasks", "implement", "test", "build")],
    DEV_ARTIFACTS,
)


def _diff_lines(diff: str, keyword: str) -> str:
    """The +/- lines of a unified diff that carry one business point (file
    headers never match: they hold the previous/current labels, not content).
    The slicing IS the pairing — the same lines stay in the group, no line
    enters that the row's own diff does not carry."""
    return "".join(
        line + "\n"
        for line in diff.splitlines()
        if (line.startswith("+") or line.startswith("-"))
        and not line.startswith(("+++", "---"))
        and keyword in line
    )


def build_diff_groups(user_diff: str, regen_diff: str) -> list[dict[str, Any]]:
    """The three-segment pairing (T12): per business point, the user's own
    diff lines (sliced from the committed row BEFORE the regen), the
    structured candidate that point produced, and the regen's diff lines
    (sliced from the regen's row). An honest slice can be empty — a point the
    user never wrote (the distilled module, the removed orphan) shows nothing
    on the sides it has no lines for."""
    groups = []
    for p in REGEN_POINTS:
        cand = _DISTILL_CAND_BY_ID[p["candidate"]]
        groups.append(
            {
                "point": p["point"],
                "candidateId": cand["id"],
                "structuredChanges": [cand],
                "userDiff": _diff_lines(user_diff, p["keyword"]),
                "regenDiff": _diff_lines(regen_diff, p["keyword"]),
            }
        )
    return groups

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

add(
    "main-011",
    main.snapshot(
        "requirements.md",
        REQ_EDIT,
        [],
        graph=GRAPH_AFTER,
        release=RELEASE_V3,
        generated_files=GENERATED_FILES,
        generated_from="main-009",
        distillation=DISTILL_RUNNING,
    ),
)
# main-012: the run is done and its candidate list is finished, but the
# graph has NOT moved yet (no delta, no appliedAt) — this is step 8's frame:
# 看沉淀过程, the grouped candidate list with each change naming its source
# paragraph, over the still-old graph. The absorption lands one frame later.
add(
    "main-012",
    main.snapshot(
        "requirements.md",
        REQ_EDIT,
        [],
        graph=GRAPH_AFTER,
        release=RELEASE_V3,
        generated_files=GENERATED_FILES,
        generated_from="main-009",
        distillation=DISTILL_DONE,
    ),
)
# main-013: the applied frame (step 9, 看最新结构化设计) — the graph absorbed
# the accepted candidates (GRAPH_DISTILLED) and the wave's own delta (added /
# modified / removed, machine-proven equal to the before/after graph diff)
# is what the graph highlights. appliedAt names the instant of absorption.
add(
    "main-013",
    main.snapshot(
        "requirements.md",
        REQ_EDIT,
        [],
        graph=GRAPH_DISTILLED,
        graph_delta={
            "nodes": ["mod-coupon-service"],
            "edges": [
                "req-coupon-expiry->mod-coupon-service",
                "req-redeem->mod-coupon-service",
            ],
            "modified": ["req-redeem"],
            "removed": ["doc-workflow"],
        },
        release=RELEASE_V3,
        generated_files=GENERATED_FILES,
        generated_from="main-009",
        distillation=DISTILL_APPLIED,
    ),
)
# main-014: the regeneration frame (T12, 验收文档步骤 10-11). The applied
# distillation flows BACK into the documents: REQ_REGEN is committed as a new
# version (v4) whose row names no human author — the snapshot carries a
# `regeneration` naming the distillation that generated it. The graph does NOT
# move here (the wave was main-013's shot); what lands instead is the three-
# segment pairing data, built by slicing the two version rows' own diffs by
# business point — check_regen re-slices them from the emitted rows, so the
# pairing view cannot show a line the snapshots do not hold.
req.commit(REQ_REGEN, REGEN_TS)
add(
    "main-014",
    main.snapshot(
        "requirements.md",
        REQ_REGEN,
        [],
        graph=GRAPH_DISTILLED,
        release=RELEASE_V3,
        generated_files=GENERATED_FILES,
        generated_from="main-009",
        distillation=DISTILL_APPLIED,
        regeneration=REGEN,
        diff_groups=build_diff_groups(
            unified_diff(REQ_V2, REQ_EDIT), unified_diff(REQ_EDIT, REQ_REGEN)
        ),
    ),
)

# main-015..018: the development run opened on the frozen v4 design (T13,
# 验收文档步骤 12-15). The doc world stands still (v4 is the newest row,
# the graph holds its absorbed shape); what moves is the RUN: opened with
# its designVersion anchor (main-015), mid-flight (main-016), landed with
# artifacts + runnableVersion (main-017), and the frame whose experience
# page is open (main-018 — identical derived state to main-017 plus the
# preview payload, so the chain before(k)≡after(k-1) holds across the
# 打开可运行版本 click). check_devrun proves the phase machine is a legal
# monotonic walk and the runnable entry only exists with its product.
_DEV_BASE = {
    "graph": GRAPH_DISTILLED,
    "release": RELEASE_V3,
    "generated_files": GENERATED_FILES,
    "generated_from": "main-009",
    "distillation": DISTILL_APPLIED,
    "regeneration": REGEN,
    "diff_groups": build_diff_groups(
        unified_diff(REQ_V2, REQ_EDIT), unified_diff(REQ_EDIT, REQ_REGEN)
    ),
}
add("main-015", main.snapshot("requirements.md", REQ_REGEN, [], dev_run=DEV_TASKS, **_DEV_BASE))
add("main-016", main.snapshot("requirements.md", REQ_REGEN, [], dev_run=DEV_TEST, **_DEV_BASE))
add("main-017", main.snapshot("requirements.md", REQ_REGEN, [], dev_run=DEV_DONE, **_DEV_BASE))
add(
    "main-018",
    main.snapshot(
        "requirements.md", REQ_REGEN, [], dev_run=DEV_DONE, run_preview=RUN_PREVIEW, **_DEV_BASE
    ),
)

# main-019/020: the closing beats (T14, 验收文档步骤 16-17). main-019 is the
# round's world seen AFTER the experience — the experience overlay is closed
# (no runPreview), and for the first time the snapshot carries `history`: the
# six-event chain that ties this whole round together, its links walking back
# from 运行 to the first edit. main-020 is 继续设计: the SAME round data minus
# the runPreview the round's own frame already showed, plus newRound — the
# editor stands clean on v4 (the round's final design IS the new baseline)
# while the history stays readable, so the loop closes with 上一轮不丢. The
# round's facts are never rewritten here: same 4 versions, same graph, same
# devRun — 新一轮的起点就是上一轮的终点，这一句在快照里是数据。
add(
    "main-019",
    main.snapshot(
        "requirements.md", REQ_REGEN, [], dev_run=DEV_DONE, history=HISTORY, **_DEV_BASE
    ),
)
add(
    "main-020",
    main.snapshot(
        "requirements.md",
        REQ_REGEN,
        [],
        dev_run=DEV_DONE,
        history=HISTORY,
        new_round=True,
        **_DEV_BASE,
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
        # the modified/removed halves of a graph delta (ACP-733): the
        # distillation wave changes existing nodes and prunes orphans, and the
        # graph read-backs must be able to say so — 0 for every world/step
        # whose story is a plain addition.
        delta = snap.get("graphDelta", {})
        state["graphModifiedNodes"] = len(delta.get("modified", []))
        state["graphRemovedNodes"] = len(delta.get("removed", []))
        # the distillation vocabulary rides the release gate: the AI only
        # distils after a release froze the docs, so every step of that world
        # states its status (none/running/done) and the candidate count.
        dist = snap.get("distillation")
        state["distillStatus"] = dist["status"] if dist else "none"
        state["distillCandidates"] = len(dist["candidates"]) if dist else 0
        # the regeneration vocabulary (T12) rides the same gate: every step of
        # a graph world states whether the docs were regenerated from the
        # distilled facts and how many business points the paired-diff view
        # groups (0 until the regen lands).
        state["regenVersion"] = snap.get("regeneration") is not None
        state["diffGroups"] = len(snap.get("diffGroups", []))
        # the development-run vocabulary (T13) rides the same gate: whether a
        # run is open, how many of its four phases are done, and whether a
        # runnable version exists yet (0 until the build lands).
        dev = snap.get("devRun")
        state["devActive"] = dev is not None
        state["devPhasesDone"] = sum(1 for p in dev["phases"] if p["status"] == "done") if dev else 0
        state["devRunnable"] = bool(dev and dev.get("runnableVersion"))
        state["runOpen"] = snap.get("runPreview") is not None
        # the history vocabulary (T14) rides the same gate: how many events
        # the project-wide timeline carries (0 until the closing frames), and
        # whether this frame is a fresh round standing on the last one's
        # final design.
        state["historyEvents"] = len(snap.get("history", {}).get("events", []))
        state["newRound"] = bool(snap.get("newRound"))
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
    "distill_panel": "AI 沉淀面板",
    "regen_doc_view": "重新生成的文档视图",
    "diff_group": "三段成组 Diff 视图",
    "dev_record": "开发记录面板",
    "dev_process": "开发过程四阶段面板",
    "dev_result": "开发结果与体验入口",
    "run_preview": "可运行版本体验页",
    "history_timeline": "项目全过程历史时间线",
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
    "graphModifiedNodes": "本次修改图谱节点数",
    "graphRemovedNodes": "本次移除图谱节点数",
    "released": "已发版",
    "generatedFiles": "生成代码文件数",
    "distillStatus": "沉淀任务状态",
    "distillCandidates": "沉淀候选变化数",
    "regenVersion": "文档已由结构化事实重生成",
    "diffGroups": "成组 Diff 业务点数",
    "devActive": "开发任务已开启",
    "devPhasesDone": "开发已完成阶段数",
    "devRunnable": "已有可运行版本",
    "runOpen": "可运行体验页已打开",
    "historyEvents": "全过程历史事件数",
    "newRound": "新一轮设计已开启",
}
# the observable reading of a declared state — exactly the keys the script
# test's readState() mirrors, so a criterion is always checkable on the DOM
OBS_FIELDS = list(OBS_LABELS)
ICON_LABELS = {"gray": "灰", "active": "亮", "list": "列表", "none": "无任务", "running": "进行中", "done": "已完成"}


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
        out["graphModifiedNodes"] = state["graphModifiedNodes"]
        out["graphRemovedNodes"] = state["graphRemovedNodes"]
        out["released"] = state["released"]
        out["generatedFiles"] = state["generatedFiles"]
        out["distillStatus"] = state["distillStatus"]
        out["distillCandidates"] = state["distillCandidates"]
        out["regenVersion"] = state["regenVersion"]
        out["diffGroups"] = state["diffGroups"]
        out["devActive"] = state["devActive"]
        out["devPhasesDone"] = state["devPhasesDone"]
        out["devRunnable"] = state["devRunnable"]
        out["runOpen"] = state["runOpen"]
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
    # ACP-729/733 cross-check — a step that DECLARES a graph delta must
    # actually land it: the after snapshot's graph vs the before snapshot's
    # graph is exactly the declared delta — added nodes/edges by set
    # difference, removed nodes by reverse difference, modified nodes by label
    # change. The highlight of "new / changed in this wave" is only honest if
    # the snapshots' diff says so, never because a step wished it so.
    after_snap = SNAPS[after_fix or fixture]
    before_snap = SNAPS[prev] if prev else SNAPS[fixture]
    delta = after_snap.get("graphDelta")
    if delta is not None:
        ga = after_snap.get("graph") or {}
        gb = before_snap.get("graph") or {}
        ga_ids = {n["id"] for n in ga.get("nodes", [])}
        gb_ids = {n["id"] for n in gb.get("nodes", [])}
        real_nodes = ga_ids - gb_ids
        real_removed = gb_ids - ga_ids
        la = {n["id"]: n["label"] for n in ga.get("nodes", [])}
        lb = {n["id"]: n["label"] for n in gb.get("nodes", [])}
        real_modified = {i for i in ga_ids & gb_ids if la[i] != lb[i]}
        real_edges = {f"{e['from']}->{e['to']}" for e in ga.get("edges", [])} - {
            f"{e['from']}->{e['to']}" for e in gb.get("edges", [])
        }
        if (
            set(delta["nodes"]) != real_nodes
            or set(delta["edges"]) != real_edges
            or set(delta.get("modified", [])) != real_modified
            or set(delta.get("removed", [])) != real_removed
        ):
            raise AssertionError(
                f"{sid}: declared graphDelta "
                f"{sorted(delta['nodes'])}/{sorted(delta['edges'])}/"
                f"{sorted(delta.get('modified', []))}/{sorted(delta.get('removed', []))} "
                f"≠ snapshot diff {sorted(real_nodes)}/{sorted(real_edges)}/"
                f"{sorted(real_modified)}/{sorted(real_removed)} — "
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
        # 去了哪里：本步高亮目标所属的视图（goes_to 可覆写，默认按 target 查表；
        # 带参数的 target —— 如 "diff_group:structured" —— 查基名）
        "goesTo": goes_to or TARGET_VIEW[target.split(":")[0]],
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
        if ob["distillStatus"] != "none":
            bits.append(f"沉淀{'已完成' if ob['distillStatus'] == 'done' else '进行中'}（候选 {ob['distillCandidates']} 条）")
        if ob["regenVersion"]:
            bits.append(f"文档已重生成（成组 Diff {ob['diffGroups']} 组）")
    if ob.get("historyEvents"):
        bits.append(f"全过程历史 {ob['historyEvents']} 类事件")
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
            step(
                "main-11",
                "点「开始沉淀」：发版后 AI 把冻结文档沉淀为结构化事实",
                "main-010",
                "点顶栏「开始沉淀」——AI 从 v3 冻结的文档提炼结构化设计事实，任务进入进行中",
                "distill_panel",
                "当前：沉淀任务已真实启动（同一个顶栏按钮、快照 fake 落任务）——面板显示「进行中」。验收口径：图谱不是提交直接出的，是发版后 AI 沉淀文档变化、图谱随之更新；沉淀完成在下一步的快照里，不是计时器假装。",
                ["distill_btn"],
                prev="main-010",
                after_fix="main-011",
            ),
            step(
                "main-12",
                "看沉淀过程：3 条候选结构化变化，各标注来源段落",
                "main-012",
                "沉淀完成——候选清单按新增/修改/删除分组，每条带来源文档段落（可追溯，不是黑盒）",
                "distill_panel",
                "当前：3 条候选——新增「优惠券服务模块」（add）、细化「积分兑换优惠券」标签（modify）、移除无挂靠的 workflow.md（remove），每条注明提炼自哪段文档。图谱还是旧的：应用是下一拍的事。",
                None,
                prev="main-011",
            ),
            step(
                "main-13",
                "看最新结构化设计：图谱亮起本轮沉淀的新增/修改/移除",
                "main-013",
                "候选被采纳、图谱吸收——新节点实线亮框、修改节点虚线亮框、孤儿节点消失",
                "graph_view",
                "当前：图谱 8 节点——绿框实线是新增的「优惠券服务模块」，绿框虚线是被细化的「积分兑换优惠券」，workflow.md 已被移除。新增/修改/移除三个数都由前后快照的图谱差机器校验，且与候选清单一一对应：发版→沉淀→结构化设计的因果链完整了。",
                None,
                prev="main-012",
            ),
            step(
                "main-14",
                "看重生成的文档：结构化事实反向产出 v4",
                "main-014",
                "沉淀应用后，AI 从结构化设计事实反向重生成文档——版本历史出现 v4，快照标注它由哪次沉淀生成",
                "regen_doc_view",
                "当前：版本历史 4 版，最新一版（v4）是 AI 重生成的——细化行带着沉淀后的节点标签，「设计事实」段落逐字复用新增候选的 summary。反向链路通了：文档→图谱→代码之外，结构化事实还能反向产出文档版本；这版是否可信，下一步成组 Diff 逐点核对。",
                ["versions_btn", "version_row:newest"],
                prev="main-013",
            ),
            step(
                "main-15",
                "核对①用户改动：左段是你为这点亲手写的行",
                "main-014",
                "成组 Diff 按业务点分组（一组一个沉淀候选），先看闭环最完整的「兑换券 7 天有效」——左段高亮",
                "diff_group:user",
                "当前：左段是你在 v3 里亲手写下的那一行「优惠券 7 天内有效，过期自动退回积分」——它是这一点的全部用户来源。行是从版本行的 unified diff 里按关键词切出来的，预检逐字节校验：这一段显示什么，快照里就得有什么。",
                None,
                prev="main-014",
            ),
            step(
                "main-16",
                "核对②结构化变化：中段是 AI 沉淀出的事实",
                "main-014",
                "同一点的中段高亮——沉淀对这一点产出的结构化变化（候选 + 来源段落）",
                "diff_group:structured",
                "当前：中段是「兑换券 7 天有效」这个业务点的结构化形态：细化候选「积分兑换优惠券（7 天有效）」，注明提炼自 requirements.md 哪一段。左右是文档的行、中间是图谱的事实——三段同点联动，核对的就是 AI 把你写的行理解成了什么。",
                None,
                prev="main-014",
            ),
            step(
                "main-17",
                "核对③重生成差异：右段是结构化事实反向产出的行",
                "main-014",
                "同一点的右段高亮——v4 相对 v3 为这点带来的行，回扣左段你的原话",
                "diff_group:regen",
                "当前：右段是重生成 v4 为这一点带出的行——「积分满 100 可兑换 5 元优惠券」被细化成带 7 天标签的写法。左段你写的、中段沉淀的、右段重生成的，三段同点摆在一起：系统理解得对不对，用户一眼可核对。其余组同样展示：纯沉淀新增的组左段为空（你没写过它），图谱移除组左右皆空（移除的是挂靠不是文档行）——空也是数据，不是缺憾。",
                None,
                prev="main-014",
            ),
            step(
                "main-18",
                "点「开始开发」：开发记录立起，锚定所用设计版本",
                "main-014",
                "点顶栏「开始开发」——开发记录建立，标注它实现的是哪个冻结设计与图谱版本；「任务生成」阶段进行中",
                "dev_record",
                "当前：开发记录已真实落任务（同一个顶栏按钮、快照 fake 落记录）——记录头注明设计版本 v4 · graph@distill-v3：开发的追溯起点是冻结的结构化设计，不是口头需求。四阶段（任务生成→实现→测试→构建）的第一项进行中；过程的推进在下一步的快照帧里，不是计时器假装。",
                ["dev_btn"],
                prev="main-014",
                after_fix="main-015",
            ),
            step(
                "main-19",
                "看开发过程：四阶段步进，已完成阶段各带一句事实摘要",
                "main-016",
                "开发进行中——任务生成、实现两步已完成（各带摘要），测试进行中，构建待启动",
                "dev_process",
                "当前：四阶段走到「测试」进行中——已完成的两段各有一句事实摘要（拆了 5 个任务、实现 4 个模块）。摘要活在快照里：自动播放逐帧走到这里和手动步进走到这里，画面逐字段相同；阶段状态不是业务组件里的假计时器。",
                None,
                prev="main-015",
            ),
            step(
                "main-20",
                "看开发结果：4/4 阶段完成，测试报告/构建产物/可运行入口就位",
                "main-017",
                "开发完成——四阶段全部完成，产物清单出现：测试报告、构建包、运行时入口",
                "dev_result",
                "当前：4/4 阶段完成——测试摘要给出 23 项全过，产物三条就位（test/build/runtime），可运行版本 0.4.0 就绪。结果页的每个数字与路径都活在快照里，且「体验」入口只在构建产物存在后才出现：没有产品的入口不放。",
                None,
                prev="main-016",
            ),
            step(
                "main-21",
                "点「打开可运行版本」：内置体验页展示结构化设计承诺的功能",
                "main-017",
                "点结果页的「打开可运行版本」——演示内部路由切到内置快照组件（不起任何服务器/容器），可运行版本 0.4.0 跑起来",
                "run_preview",
                "当前：体验页打开——这就是从需求一路走到现在的可运行版本 0.4.0。页面列出的功能清单逐字等于图谱里的需求节点标签（生成器机器校验）：体验页只敢展示结构化设计承诺过的东西，全旅程 需求→图谱→代码→沉淀→重生成→开发→体验 在这里走完。",
                ["run_open_btn"],
                prev="main-017",
                after_fix="main-018",
            ),
            step(
                "main-22",
                "看全过程历史：修改/提交/发版/沉淀/开发/运行是六个可追溯的事实",
                "main-019",
                "回到工作台打开项目历史——本轮从最初那次修改到可运行版本的每一类事实，按时间与关联串成一条链",
                "history_timeline",
                "当前：时间线六个节点六类图标——编辑、提交、发版、沉淀、开发、运行各是一类事实，不可混淆。每个节点标注它产出的事实并回指前因（链是快照里的数据，生成器校验每条链接必须回指）；点任一节点跳回它当时的画面=加载它命名的快照，不反向计算。从运行节点沿链走回最初修改，验收文档步骤 16 的追溯在数据里成立。",
                None,
                prev="main-018",
            ),
            step(
                "main-23",
                "点「继续设计」：上一轮终点即新起点，历史仍在手边",
                "main-019",
                "点时间线底部的「继续设计」——编辑器落在 v4 干净态开始新一轮，时间线保留上一轮全部六类事件",
                "doc_editor",
                "当前：编辑器已落在上一轮的最终设计 v4 上，干净、可直接开始下一轮修改；版本历史、图谱、开发记录、六事件时间线一件不少——闭环不是重开一局，是在成果上续写。点下一步/重开可再看一遍整条链。",
                ["continue_design"],
                prev="main-019",
                after_fix="main-020",
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


def check_distillation(key: str, snap: dict[str, Any]) -> None:
    """ACP-733 — the distillation story as DATA, checked at generation:
    - a candidate list exists only in a released world (AI distils after the
      docs froze) and only with a non-empty release;
    - once status=done AND appliedAt is set, the snapshot's graphDelta must
      exist and its added/modified/removed node sets must equal exactly the
      candidates' targets by kind — the candidate list the panel groups and
      the graph wave the view highlights are one and the same fact;
    - appliedAt without a graph delta (a done-run claiming absorption over an
      unmoved graph) is rejected here, not on stage."""
    dist = snap.get("distillation")
    if dist is None:
        return
    assert snap.get("release") is not None, f"{key}: distillation without a release — AI distils frozen docs only"
    for c in dist["candidates"]:
        assert c["kind"] in ("add", "modify", "remove"), f"{key}: candidate {c['id']} kind {c['kind']!r}"
        assert c["evidenceDoc"].strip(), f"{key}: candidate {c['id']} names no source paragraph"
    if dist["status"] != "done":
        assert dist.get("appliedAt") is None, f"{key}: distillation appliedAt without status=done"
        return
    if dist.get("appliedAt") is None:
        # a finished run whose graph has not absorbed it yet (step 8's frame:
        # the candidate list is whole, the graph still old) — no wave to check
        assert "graphDelta" not in snap, (
            f"{key}: graph moved but distillation not marked applied — absorption lands with appliedAt"
        )
        return
    delta = snap.get("graphDelta")
    if delta is None and snap.get("regeneration") is not None:
        # a frame the wave merely PERSISTS through (T12's regeneration frame
        # still carries the applied run): the wave's landing story was the
        # applying snapshot's shot, and this frame's graph stands at exactly
        # that absorbed shape — check_regen's modified-candidate probe checks
        # the persistence against the facts. Only a REGEN frame earns this:
        # the applying frame itself must move the graph.
        return
    assert delta is not None, (
        f"{key}: distillation done+appliedAt but the graph never moved — "
        "the wave must land in the same frame that marks it applied"
    )
    by_kind: dict[str, set] = {"add": set(), "modify": set(), "remove": set()}
    for c in dist["candidates"]:
        by_kind[c["kind"]].add(c["target"])
    if (
        by_kind["add"] != set(delta["nodes"])
        or by_kind["modify"] != set(delta.get("modified", []))
        or by_kind["remove"] != set(delta.get("removed", []))
    ):
        raise AssertionError(
            f"{key}: candidate targets {({k: sorted(v) for k, v in by_kind.items()})} "
            f"≠ graph wave {sorted(delta['nodes'])}/{sorted(delta.get('modified', []))}/"
            f"{sorted(delta.get('removed', []))} — 候选清单与图谱更新必须是同一份事实"
        )


def check_regen(key: str, snap: dict[str, Any]) -> None:
    """ACP-734 — the regeneration + paired-diff story as DATA, checked at
    generation (the ticket's 预检：regenDiff 声明的行数/段落与快照内容一致):
    - a regeneration exists only where a done distillation fed it, and names
      exactly that run (generatedFrom); its content IS the committed doc —
      the "new version" is content, not a badge;
    - every added candidate's summary is a line of the content, and every
    modified node's label refinement shows up on an added diff line — the
    content is a function of the distilled facts, not prose about them;
    - every group's userDiff/regenDiff is re-sliced HERE from the version
      rows the fixture itself emitted (newest = the regen's row, the one
    below = the user's row) — a group cannot show a line its rows do not
    carry; a remove-kind group must be empty on both sides (removing a graph
    attachment cuts no doc lines — the emptiness is data, matching the hint)."""
    regen = snap.get("regeneration")
    if regen is None:
        assert "diffGroups" not in snap, f"{key}: diffGroups without a regeneration"
        return
    dist = snap.get("distillation")
    assert dist is not None and dist["status"] == "done", (
        f"{key}: regeneration without a done distillation to feed it"
    )
    assert regen["generatedFrom"] == dist["id"], (
        f"{key}: regeneration names {regen['generatedFrom']!r}, not this frame's distillation {dist['id']!r}"
    )
    rows = snap["versions"].get(regen["docName"]) or []
    assert len(rows) >= 2, f"{key}: regeneration doc has no version pair to pair against"
    committed = next(d["content"] for d in snap["docs"] if d["name"] == regen["docName"])
    assert regen["content"] == committed, f"{key}: regeneration.content ≠ the committed doc"
    content_lines = committed.splitlines()
    for c in dist["candidates"]:
        if c["kind"] == "add":
            assert f"- {c['summary']}" in content_lines, (
                f"{key}: added candidate {c['id']}: its summary is not a line of the regenerated content"
            )
    labels = {n["id"]: n["label"] for n in (snap.get("graph") or {}).get("nodes", [])}
    added = [
        ln[1:]
        for ln in rows[0]["diff"].splitlines()
        if ln.startswith("+") and not ln.startswith("+++")
    ]
    # the modified-kind candidates carry the proof the distillation precheck
    # cannot: the persisted frame has no graphDelta to compare against, so
    # each refined node's label must itself show up on an added diff line.
    for c in dist["candidates"]:
        if c["kind"] != "modify":
            continue
        refine = re.search(r"（([^）]+)）", labels[c["target"]])
        assert refine and any(refine.group(1) in ln for ln in added), (
            f"{key}: modified candidate {c['id']}: label {labels[c['target']]!r} — its refinement "
            "carries no added line in the regen's diff"
        )
    groups = snap.get("diffGroups") or []
    assert len(groups) == len(dist["candidates"]), (
        f"{key}: {len(groups)} diff groups ≠ {len(dist['candidates'])} candidates — 一组一候选"
    )
    seen_ids = set()
    by_point = {p["point"]: p for p in REGEN_POINTS}
    for g in groups:
        p = by_point.get(g["point"])
        assert p is not None, f"{key}: group {g['point']!r} is not a declared business point"
        assert g["candidateId"] == p["candidate"] and g["candidateId"] not in seen_ids, (
            f"{key}: group {g['point']!r} must name exactly candidate {p['candidate']!r}"
        )
        seen_ids.add(g["candidateId"])
        want_user = _diff_lines(rows[1]["diff"], p["keyword"])
        want_regen = _diff_lines(rows[0]["diff"], p["keyword"])
        assert g["userDiff"] == want_user, (
            f"{key}: group {g['point']!r} userDiff ≠ the user's version row re-sliced"
        )
        assert g["regenDiff"] == want_regen, (
            f"{key}: group {g['point']!r} regenDiff ≠ the regen's version row re-sliced"
        )
        for ln in (g["userDiff"] + g["regenDiff"]).splitlines():
            if ln.startswith("+"):
                assert ln[1:] in content_lines, (
                    f"{key}: group {g['point']!r} shows an added line the committed content does not hold"
                )
        kinds = {c["kind"] for c in g["structuredChanges"]}
        if kinds == {"remove"}:
            assert g["userDiff"] == "" and g["regenDiff"] == "", (
                f"{key}: remove-kind group {g['point']!r} carries doc lines — "
                "removing a graph attachment cuts no document lines"
            )


def check_devrun(key: str, snap: dict[str, Any]) -> None:
    """ACP-735 — the development run as DATA, checked at generation (the
    ticket's 预检：phases 完整性与 runnableVersion 存在):
    - a run exists only on top of a regenerated design, and its
      designVersion names exactly THIS world's regen version + distillation
      id — the run traces to the frozen structured facts, not to a wish;
    - the four phases are the fixed pipeline tasks→implement→test→build,
      each status legal; done phases carry a non-empty summary, non-done ones
      carry none (a fact line for work that has not finished is a lie);
    - artifacts and runnableVersion appear only when ALL phases are done —
      the 体验 entry cannot exist before its product;
    - the run preview's feature list is exactly the graph's requirement-node
      labels — the runnable experience shows only what the structured design
      promises; and it exists only in a frame whose run is finished."""
    dev = snap.get("devRun")
    if dev is None:
        assert "runPreview" not in snap, f"{key}: runPreview without a development run"
        return
    regen = snap.get("regeneration")
    dist = snap.get("distillation")
    assert regen is not None and dist is not None, (
        f"{key}: devRun before a regeneration/distillation — development builds on frozen structured facts"
    )
    assert dev["designVersion"] == f"{regen['version']} · graph@{dist['id']}", (
        f"{key}: devRun designVersion {dev['designVersion']!r} names neither this frame's regen version nor its distillation"
    )
    names = [p["name"] for p in dev["phases"]]
    assert names == ["tasks", "implement", "test", "build"], (
        f"{key}: devRun phases {names} ≠ the fixed pipeline tasks/implement/test/build"
    )
    for p in dev["phases"]:
        assert p["status"] in ("pending", "running", "done"), (
            f"{key}: phase {p['name']} status {p['status']!r}"
        )
        if p["status"] == "done":
            assert p["summary"].strip(), f"{key}: done phase {p['name']} has no fact summary"
        else:
            assert p["summary"] == "", f"{key}: unfinished phase {p['name']} already carries a summary"
    all_done = all(p["status"] == "done" for p in dev["phases"])
    if all_done:
        assert dev.get("runnableVersion"), (
            f"{key}: every phase done but no runnableVersion — the result page needs its product"
        )
        kinds = [a["kind"] for a in dev["artifacts"]]
        assert kinds == ["test", "build", "runtime"], (
            f"{key}: finished run's artifacts {kinds} ≠ test/build/runtime"
        )
    else:
        assert "runnableVersion" not in dev, (
            f"{key}: runnableVersion before the build lands — no entry without its product"
        )
        assert dev["artifacts"] == [], f"{key}: artifacts before every phase is done"
    preview = snap.get("runPreview")
    if preview is None:
        return
    assert all_done, f"{key}: runPreview frame whose run has not finished"
    assert preview["devRunId"] == dev["id"] and preview["version"] == dev["runnableVersion"], (
        f"{key}: runPreview names {preview['devRunId']!r}@{preview['version']!r}, not this run"
    )
    req_labels = [n["label"] for n in (snap.get("graph") or {}).get("nodes", []) if n["kind"] == "requirement"]
    assert preview["lines"] == req_labels, (
        f"{key}: runPreview feature list ≠ the graph's requirement labels — 体验页只能展示结构化设计承诺的功能"
    )


def check_history(key: str, snap: dict[str, Any], jumpable: "set[str]") -> None:
    """ACP-736 — the project history as DATA, checked at generation:
    - the kind union is closed (six facts, NO AI-source variant: the demo
      models every doc edit as human-made — the DAG's 显式不做);
    - event ids are unique, links only name events that exist, and every
      link points BACK in time (追溯 follows causes, never forward);
    - every `ref` names a snapshot some step actually lands on — 跳转=加载
      快照, so a timeline node can never point at a frame the script cannot
      show;
    - the five acceptance facts (edit/commit/release/distill/dev) all appear
      (run is the sixth, the round's product);
    - newRound only on a frame that still carries the history it continues."""
    hist = snap.get("history")
    if hist is None:
        assert not snap.get("newRound"), f"{key}: newRound without history — 新一轮必须带着上一轮的历史"
        return
    events = hist["events"]
    ids = set()
    at_of: dict[str, int] = {}
    kinds = set()
    for e in events:
        assert e["kind"] in ("edit", "commit", "release", "distill", "dev", "run"), (
            f"{key}: history event {e['id']} kind {e['kind']!r} outside the closed union "
            "(no AI-source variants — every doc edit is modelled human-made)"
        )
        assert e["id"] not in ids, f"{key}: duplicate history event id {e['id']}"
        ids.add(e["id"])
        assert isinstance(e["at"], int)
        at_of[e["id"]] = e["at"]
        assert e["ref"] in SNAPS, f"{key}: event {e['id']} refs snapshot {e['ref']!r} that does not exist"
        assert e["ref"] in jumpable, (
            f"{key}: event {e['id']} refs {e['ref']!r} — no script step lands on that "
            "snapshot, so the jump would have no frame to load"
        )
        assert e["summary"].strip(), f"{key}: history event {e['id']} has no summary"
        kinds.add(e["kind"])
    for e in events:
        for link in e["links"]:
            assert link in ids, f"{key}: event {e['id']} links to unknown event {link!r}"
            assert at_of[link] <= e["at"], (
                f"{key}: event {e['id']} links forward to {link!r} — 追溯沿因果往回走"
            )
    missing = {"edit", "commit", "release", "distill", "dev"} - kinds
    assert not missing, f"{key}: history misses the five facts {sorted(missing)} — 五类事实必须齐全"


def dump(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main_run() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    STEPS.mkdir(parents=True, exist_ok=True)
    # every snapshot a step can SHOW — its entry fixture or a live-act's
    # landing frame: the only frames a history jump may load
    jumpable = {s["fixture"] for script in SCRIPTS.values() for s in script["steps"]}
    jumpable |= {s["afterFix"] for script in SCRIPTS.values() for s in script["steps"] if "afterFix" in s}
    for key, snap in SNAPS.items():
        check_graph_shape(key, snap)
        check_generated_traceability(key, snap)
        check_distillation(key, snap)
        check_regen(key, snap)
        check_devrun(key, snap)
        check_history(key, snap, jumpable)
        dump(FIXTURES / f"state-{key}.json", snap)
    for name, script in SCRIPTS.items():
        dump(STEPS / f"{name}.json", script)
    print(f"wrote {len(SNAPS)} fixtures, {len(SCRIPTS)} scripts")


if __name__ == "__main__":
    main_run()
