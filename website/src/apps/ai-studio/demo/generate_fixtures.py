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
    ) -> dict[str, Any]:
        """One replayable state: every doc's committed content, the focused
        doc's editor buffer, and its draft records (newest first)."""
        return {
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
# main-001..003: nothing touched yet (the trail already holds v1, v2).
add("main-001", main.snapshot("requirements.md", REQ_V2, []))
add("main-002", main.snapshot("requirements.md", REQ_V2, []))
add("main-003", main.snapshot("requirements.md", REQ_V2, []))
# main-004: the user appended two lines (dirty, still nothing autosaved).
add("main-004", main.snapshot("requirements.md", REQ_EDIT, []))
# main-005: the ~2s debounce fired — one draft record, diff icon lit.
add("main-005", main.snapshot("requirements.md", REQ_EDIT, [(T0 + 172800, REQ_EDIT)]))
# main-006/007: same state; the steps only change what the overlay opens.
add("main-006", main.snapshot("requirements.md", REQ_EDIT, [(T0 + 172800, REQ_EDIT)]))
add("main-007", main.snapshot("requirements.md", REQ_EDIT, [(T0 + 172800, REQ_EDIT)]))
# main-008: the commit. The store moved the buffer into docs/ and versions/
# (v3) and deleted the drafts — the snapshot below shows exactly that.
req.commit(REQ_EDIT, T0 + 172800)
add("main-008", main.snapshot("requirements.md", REQ_EDIT, []))

# branch A --------------------------------------------------------------------
# The honest chain (same rhythm as the main line): enter clean → type draft
# A → autosave it → extend to draft B → autosave → open history → pick the
# OLDER record and restore → the restored text is recorded as a third entry
# (dedupe only compares against the newest record, and the newest was B).
add("alt1-001", site.snapshot("requirements.md", SITE_V1, []))
add("alt1-002", site.snapshot("requirements.md", SITE_D1, []))
add("alt1-003", site.snapshot("requirements.md", SITE_D1, [(T0 + 1800, SITE_D1)]))
add("alt1-004", site.snapshot("requirements.md", SITE_D2, [(T0 + 1800, SITE_D1)]))
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
    return {
        "doc": focus,
        "dirty": dirty,
        "diffIcon": "active" if dirty else "gray",
        "draftRecords": drafts,
        "historyIcon": "list" if drafts else "gray",
        "versions": versions,
        "versionsIcon": "list" if versions else "gray",
    }


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
) -> dict[str, Any]:
    """One script step. `fixture` is the state the step LANDS on (after);
    `prev` is the one it starts from — the script can never claim a before
    its chain does not carry, because before(k) is derived from fixture(k-1).
    """
    snap = SNAPS[fixture]
    return {
        "id": sid,
        "title": title,
        "branch": branch,
        "fixture": fixture,
        "before": derive(SNAPS[prev]) if prev else derive(snap),
        "action": {"event": event},
        "after": derive(snap),
        "highlight": {"target": target, "hint": hint, "open": open_locators or []},
    }


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
                "在编辑器追加两行验收标准，停手",
                "diff_btn",
                "当前：缓冲已变（追加了优惠券有效期与「积分抵现」排除项），页脚提示未保存，diff 图标由灰转亮——存在未提交修改。缓冲内容来自快照，经编辑器真实的 Markdown 源视图落位，不碰真实后端。",
                ["markdown_toggle", "set_buffer"],prev="main-003",
                
            ),
            step(
                "main-5",
                "防抖 2s 到期，自动保存记下一条草稿",
                "main-005",
                "停手 2 秒，防抖自动保存把当前缓冲记成一条草稿记录",
                "draft_history_list",
                "当前：修改历史面板出现 1 条记录。规则：内容与上一条相同不落新条——光标再动多久都不会灌出重复记录。",
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
                "点「提交版本」",
                "main-007",
                "确认红绿无误，点击提交",
                "commit_btn",
                "当前：提交触发的内部动作——旧内容进版本快照（v3）、草稿记录整体清空、diff 图标回灰。下一步直接载入提交后的快照。",
                ["markdown_toggle", "set_buffer"],prev="main-006",
                
            ),
            step(
                "main-8",
                "提交后：版本 +1、修改历史清空、图标回灰",
                "main-008",
                "提交完成，页面回到干净态",
                "version_history_list",
                "当前：版本历史变成 3 版（v3 即刚才的提交），修改历史 0 条（提交即清空），diff 图标回灰——闭环走完。",
                ["versions_btn"],prev="main-007",
                
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
                "在编辑器追加「首屏文案·候选 A」草稿段",
                "doc_editor",
                "当前：缓冲比最近提交多了一段候选 A 文案，diff 图标由灰转亮。缓冲内容来自快照，经真实的 Markdown 源视图敲进编辑器。",
                ["markdown_toggle", "set_buffer"],
                prev="alt1-001",
                branch="alt-1",
            ),
            step(
                "alt1-3",
                "防抖到期，候选 A 记为第一条草稿",
                "alt1-003",
                "停手 2 秒，自动保存落下第一条记录",
                "draft_history_list",
                "当前：修改历史 1 条——候选 A。点开面板看它的时间与摘要。",
                ["markdown_toggle", "set_buffer", "draft_history_btn"],
                prev="alt1-002",
                branch="alt-1",
            ),
            step(
                "alt1-4",
                "改主意：把草稿改成候选 B",
                "alt1-004",
                "把主标题改成「候选 B」并加一行副标题",
                "diff_btn",
                "当前：缓冲换成候选 B，diff 图标保持亮——两版文案的取舍还没定。",
                ["markdown_toggle", "set_buffer"],
                prev="alt1-003",
                branch="alt-1",
            ),
            step(
                "alt1-5",
                "候选 B 也记下了：现在有两条记录",
                "alt1-005",
                "再停 2 秒，防抖落下第二条",
                "draft_history_list",
                "当前：两条记录，最新在上——候选 B 在上、候选 A 在下。每一段改过的文字都没有丢。",
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


def dump(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main_run() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    STEPS.mkdir(parents=True, exist_ok=True)
    for key, snap in SNAPS.items():
        dump(FIXTURES / f"state-{key}.json", snap)
    for name, script in SCRIPTS.items():
        dump(STEPS / f"{name}.json", script)
    print(f"wrote {len(SNAPS)} fixtures, {len(SCRIPTS)} scripts")


if __name__ == "__main__":
    main_run()
