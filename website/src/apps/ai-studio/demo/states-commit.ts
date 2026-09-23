// Commits-tab states C1/C2 of the state-direct demo (ACP-795, parent ACP-786)
// — the two frames that cover the ONE tool tab the demo outline never covered
// (提纲本无 C 步：D6 演的是「提交按钮 + 版本历史」，不是工具边栏的「提交」页签).
//
// THE STORY (接 S1~S3 / D6~D8 同一世界): the 会员积分系统 has already been
// iterated TWICE (前两轮 iteration-closing commits are in the history below),
// and this is the THIRD iteration — the one whose design work the D6~D8 frames
// show. C1 stands at the moment that iteration's design work is finished but
// nothing is submitted yet; C2 is the same frame one click later, after
// 「提交全部」.
//
// WHY THESE FIELDS: the commits tab is a SIDEBAR tab, not a center surface, so
// a frame cannot pin it with `activeSurface` alone. The two additive seams live
// on the frame: `activeSidebarTab` names the lit tab, and `changed` / `commits`
// are exactly the two lists `ToolSidebar`'s `CommitsTool` takes (ACP-795 added
// those optional props with the shipped `CHANGED` / `COMMITS` fixtures as
// defaults — 不传就是零行为变化). The renderer's wiring is therefore
//   <ToolSidebar initialTool={f.activeSidebarTab} changed={f.changed} commits={f.commits} … />
// and nothing else on the public side has to know this tab exists.
//
// HONESTY RULES this file keeps (and `states-commit.test.tsx` re-derives, the
// way the outline's checks re-derive rather than trust a badge):
//   - 「待提交的改动」 is not a wish: every pending file has a real draft record
//     on the same frame's `fixture.draftVersions`, and its added/removed
//     snippets are lines sliced out of that draft vs that doc's committed text.
//     C2's list is EMPTY and its `draftVersions` empty too — 空态也是数据.
//   - 「提交后历史多一条」 is a data fact: C2.commits = [the new row, …C1.commits]
//     and the new row's `files` IS C1's pending list.
//   - PARITY DISCIPLINE (附一) as in states-design.ts: vN odd ⇔ manual,
//     even ⇔ regen, derived from the number rather than typed per row.
//
// TWO CLOCKS, one instant: `StudioVersion.time` is epoch seconds (what
// DocEditor renders through fmtDateTimeNumeric) while `CommitEntry.time` is a
// display string. Each entry below spells the SAME instant as the version row
// it closes (UTC+8), so the sidebar's history and the editor's version panel
// read as one timeline instead of two inventions.
import type { ChangedFile, CommitEntry } from '../fixtures'
import type { StudioDoc, StudioVersion } from '../studioApi'
import type { StateDocRow, StateSnapshot, StateVersionRow } from './states'
import type { DemoFixture } from './types'

/** A commits-tab frame: a normal snapshot plus the lit sidebar tab and the two
 * lists the tab renders. Nothing else is added — the center surface, the doc
 * list and the fixture markers keep their usual meaning. */
export interface CommitStateSnapshot extends StateSnapshot {
  /** which sidebar tab is lit on first paint ('commits' — the tab this pair
   * exists to cover). The renderer passes it straight to `initialTool`. */
  activeSidebarTab: 'commits'
  /** 「待提交的改动」 rows (本次迭代动过的文档). Empty is a real state — the
   * committed frame lists nothing. */
  changed: ChangedFile[]
  /** 「提交历史」 rows, newest first — the two previous iterations' closing
   * commits, plus this iteration's once it lands. */
  commits: CommitEntry[]
}

// ---------------------------------------------------------------------------
// the world carried over from states.ts / states-design.ts (re-declared, not
// imported: neither file exports its constants, and the paths stay read-only).
// The doc texts are byte-identical to those files' so all three share one
// project.
// ---------------------------------------------------------------------------

const DEMO_PROJECT = { id: 'demo-product', name: '会员积分系统', description: '状态驱动演示项目', createdAt: 1735689600 }

const FOCUS_DOC = '产品需求设计文档.md'
const JOURNEY_DOC = '用户旅程设计.md'
const MODEL_DOC = '业务模型设计.md'
const PAGE_DOC = '页面交互设计.md'

/** the four docs' committed text BEFORE this iteration (第一轮 + 第二轮 landed
 * these): the focus doc stands at v4, the downstream at v3/v1/v3 */
const BASELINE_V4 = `# 产品需求设计文档

## 1. 背景
会员积分系统面向 C 端用户。

## 2. 目标
提升复购率。

## 3. 范围
积分获取与兑换。

## 4. 规则
- 消费 1 元累积 1 积分
- 100 积分抵扣 1 元
`

/** this iteration's text for the focus doc — what the drafts hold and what the
 * closing commit lands (the same bytes D6 commits as v5) */
const COMMITTED_V5 = BASELINE_V4 + `
## 5. 用户补充
大额采购需追加一级审批，审批人请假时自动转交代理人。
`

const JOURNEY_V3 = `# 用户旅程设计

## 主流程
1. 注册会员
2. 消费累积积分
3. 积分兑换优惠券
4. 优惠券核销
`
/** 用户旅程设计.md — the downstream sync the new rule forces (even = 图谱反生) */
const JOURNEY_V4 = JOURNEY_V3 + `
## 审批分支（图谱反生）
- 大额采购订单先经一级审批，审批人请假自动转交代理人
`

const MODEL_V1 = `# 业务模型设计

## 实体
- 会员
- 积分账户
- 兑换订单
`
const MODEL_V2 = MODEL_V1 + `
## 审批单（图谱反生）
- 字段：申请人、审批人、代理人、结果
`

const PAGE_V3 = `# 页面交互设计

## 页面
- 积分中心页
- 兑换记录页
`
const PAGE_V4 = PAGE_V3 + `
## 大额采购审批提示（图谱反生）
- 提交大额采购单时弹出：需一级审批通过后发放积分
`

// ---------------------------------------------------------------------------
// version trails (DocEditor's row contract). The rows the two PREVIOUS
// iterations landed, then this iteration's rows on top.
// ---------------------------------------------------------------------------

/** one diff hunk header + lines, the way generate_fixtures.py emits them */
function hunk(h: string, ...lines: string[]): string {
  return `--- previous\n+++ current\n@@ ${h} @@\n${lines.join('')}`
}

/** one trail row: the number's parity IS the provenance (附一), so `source` is
 * derived here rather than typed per row — the data cannot lie about itself */
function row(version: string, time: number, diff: string): StudioVersion {
  const n = Number(version.slice(1))
  const parity: 'odd' | 'even' = n % 2 === 1 ? 'odd' : 'even'
  return {
    name: `${time}.md`,
    time,
    diff,
    version,
    parity,
    source: parity === 'odd' ? 'manual' : 'regen',
  }
}

/** the focus doc before this iteration (v4 = 第二轮 定稿, odd/manual) */
const FOCUS_TRAIL_V4: StudioVersion[] = [
  row('v4', 1735660000, hunk('-12,1 +12,2', ' - 消费 1 元累积 1 积分\n', '+- 100 积分抵扣 1 元\n')),
  row('v3', 1735650000, hunk('-11,0 +11,1', ' ## 4. 规则\n', '+- 消费 1 元累积 1 积分\n')),
  row('v2', 1735610000, hunk('-6,0 +6,2', ' ## 3. 范围\n', '+\n', '+## 4. 规则\n')),
  row('v1', 1735600000, hunk('-0,0 +1,4', '+# 产品需求设计文档\n', '+\n', '+## 1. 背景\n', '+会员积分系统面向 C 端用户。\n')),
]

const JOURNEY_TRAIL: StudioVersion[] = [
  row('v3', 1735650000, hunk('-8,1 +8,2', ' 3. 积分兑换优惠券\n', '+4. 优惠券核销\n')),
  row('v2', 1735610000, hunk('-3,1 +3,2', ' ## 主流程\n', '+2. 消费累积积分\n')),
  row('v1', 1735600000, hunk('-0,0 +1,4', '+# 用户旅程设计\n', '+\n', '+## 主流程\n', '+1. 注册会员\n')),
]

const MODEL_TRAIL: StudioVersion[] = [
  row('v1', 1735600000, hunk('-0,0 +1,6', '+# 业务模型设计\n', '+\n', '+## 实体\n', '+- 会员\n', '+- 积分账户\n', '+- 兑换订单\n')),
]

const PAGE_TRAIL: StudioVersion[] = [
  row('v3', 1735650000, hunk('-4,1 +4,2', ' - 积分中心页\n', '+- 兑换记录页\n')),
  row('v2', 1735610000, hunk('-1,2 +1,3', ' # 页面交互设计\n', '+\n', '+## 页面\n')),
  row('v1', 1735600000, hunk('-0,0 +1,3', '+# 页面交互设计\n', '+\n', '+- 积分中心页\n')),
]

/** this iteration's four rows: the focus doc's odd/manual v5 (the same commit
 * D6 shows) and the three even/regen rows the graph wave regenerated */
const FOCUS_V5_ROW = row('v5', 1735692000, hunk(
  '-14,3 +14,6',
  ' ## 4. 规则\n',
  ' - 消费 1 元累积 1 积分\n',
  ' - 100 积分抵扣 1 元\n',
  '+\n',
  '+## 5. 用户补充\n',
  '+大额采购需追加一级审批，审批人请假时自动转交代理人。\n',
))
const JOURNEY_V4_ROW = row('v4', 1735695000, hunk(
  '-6,1 +6,3',
  ' 4. 优惠券核销\n',
  '+## 审批分支（图谱反生）\n',
  '+- 大额采购订单先经一级审批，审批人请假自动转交代理人\n',
))
const MODEL_V2_ROW = row('v2', 1735695000, hunk(
  '-6,1 +6,3',
  '- 兑换订单\n',
  '+## 审批单（图谱反生）\n',
  '+- 字段：申请人、审批人、代理人、结果\n',
))
const PAGE_V4_ROW = row('v4', 1735695000, hunk(
  '-5,1 +5,2',
  ' - 兑换记录页\n',
  '+## 大额采购审批提示（图谱反生）\n',
  '+- 提交大额采购单时弹出：需一级审批通过后发放积分\n',
))


// ---------------------------------------------------------------------------
// the commits tab's two lists.
// ---------------------------------------------------------------------------

/** the THIRD iteration's uncommitted work: the rule the user added to the
 * requirement doc, and the three downstream docs the new rule ripples into
 * (what D7's graph wave + D8's regen produced). Snippets are lines of the
 * draft that differs from each doc's committed text — the test re-slices them. */
const CHANGED_THIS_ITERATION: ChangedFile[] = [
  {
    file: FOCUS_DOC,
    added: '+## 5. 用户补充\n+大额采购需追加一级审批，审批人请假时自动转交代理人。',
    removed: '',
  },
  {
    file: JOURNEY_DOC,
    added: '+## 审批分支（图谱反生）\n+- 大额采购订单先经一级审批，审批人请假自动转交代理人',
    removed: '',
  },
  {
    file: MODEL_DOC,
    added: '+## 审批单（图谱反生）\n+- 字段：申请人、审批人、代理人、结果',
    removed: '',
  },
  {
    file: PAGE_DOC,
    added: '+## 大额采购审批提示（图谱反生）\n+- 提交大额采购单时弹出：需一级审批通过后发放积分',
    removed: '',
  },
]

/** the two PREVIOUS iterations' closing commits, newest first. Each entry's
 * `files` are docs whose trail really gained a row at that instant, so the
 * history cannot claim work the version panel does not show. */
const HISTORY_BEFORE: CommitEntry[] = [
  { id: 'c1051', message: '第二轮迭代：积分抵扣规则定稿', time: '2024-12-31 23:46', files: [FOCUS_DOC] },
  { id: 'c1046', message: '第二轮迭代：积分兑换与大促双倍积分', time: '2024-12-31 21:00', files: [FOCUS_DOC, JOURNEY_DOC, PAGE_DOC] },
  { id: 'c1038', message: '第二轮迭代：旅程与页面细化', time: '2024-12-31 09:53', files: [FOCUS_DOC, JOURNEY_DOC, PAGE_DOC] },
  { id: 'c1027', message: '第一轮迭代：初始化会员积分系统', time: '2024-12-31 07:06', files: [FOCUS_DOC, JOURNEY_DOC, MODEL_DOC, PAGE_DOC] },
]

/** this iteration's closing commit — 「提交全部」 puts ONE row on top, and its
 * `files` is exactly C1's pending list. */
const HISTORY_NEW: CommitEntry = {
  id: 'c1052',
  message: '第三轮迭代：大额采购一级审批（提交全部）',
  time: '2025-01-01 09:30',
  files: [FOCUS_DOC, JOURNEY_DOC, MODEL_DOC, PAGE_DOC],
}

// ---------------------------------------------------------------------------
// the two fixtures: the same world, before and after 「提交全部」.
// ---------------------------------------------------------------------------

function docs(texts: Record<string, string>): StudioDoc[] {
  return [FOCUS_DOC, JOURNEY_DOC, MODEL_DOC, PAGE_DOC].map((name) => ({ name, content: texts[name] }))
}

const BEFORE_TEXTS = {
  [FOCUS_DOC]: BASELINE_V4, [JOURNEY_DOC]: JOURNEY_V3, [MODEL_DOC]: MODEL_V1, [PAGE_DOC]: PAGE_V3,
}
const AFTER_TEXTS: Record<string, string> = {
  [FOCUS_DOC]: COMMITTED_V5, [JOURNEY_DOC]: JOURNEY_V4, [MODEL_DOC]: MODEL_V2, [PAGE_DOC]: PAGE_V4,
}

/** C1's world: every doc still committed at its pre-iteration text, and one
 * draft record per pending file holding the new text. This is what makes the
 * 「有未提交改动」 claim data — the focus doc's record is the one
 * `createDemoApi.listDraftDocs` reads, so ProjectCommitBar really enables. */
function beforeFixture(): DemoFixture {
  return {
    project: DEMO_PROJECT,
    focusDoc: FOCUS_DOC,
    buffer: COMMITTED_V5,
    docs: docs(BEFORE_TEXTS),
    draftVersions: CHANGED_THIS_ITERATION.map((c) => ({ name: c.file, time: 1735692000, content: AFTER_TEXTS[c.file] })),
    versions: {
      [FOCUS_DOC]: FOCUS_TRAIL_V4.map((r) => ({ ...r })),
      [JOURNEY_DOC]: JOURNEY_TRAIL.map((r) => ({ ...r })),
      [MODEL_DOC]: MODEL_TRAIL.map((r) => ({ ...r })),
      [PAGE_DOC]: PAGE_TRAIL.map((r) => ({ ...r })),
    },
    recentActivity: CHANGED_THIS_ITERATION.map((c) => ({ time: 1735692000, label: `草稿 ${c.file}` })),
  }
}

/** C2's world: the same texts, now committed — no drafts left, and this
 * iteration's rows on top of every trail. */
function afterFixture(): DemoFixture {
  return {
    project: DEMO_PROJECT,
    focusDoc: FOCUS_DOC,
    buffer: COMMITTED_V5,
    docs: docs(AFTER_TEXTS),
    draftVersions: [],
    versions: {
      [FOCUS_DOC]: [FOCUS_V5_ROW, ...FOCUS_TRAIL_V4].map((r) => ({ ...r })),
      [JOURNEY_DOC]: [JOURNEY_V4_ROW, ...JOURNEY_TRAIL].map((r) => ({ ...r })),
      [MODEL_DOC]: [MODEL_V2_ROW, ...MODEL_TRAIL].map((r) => ({ ...r })),
      [PAGE_DOC]: [PAGE_V4_ROW, ...PAGE_TRAIL].map((r) => ({ ...r })),
    },
    recentActivity: [{ time: 1735695000, label: `提交 ${HISTORY_NEW.id}` }],
  }
}

/** the flat 版本历史 field (states.ts's convention: the FOCUS doc's trail,
 * newest first) — the reserved slot D6 already populates. */
const historyRows = (trail: StudioVersion[]): StateVersionRow[] =>
  trail.map((v) => ({
    version: v.version as string,
    parity: v.parity as 'odd' | 'even',
    source: v.source as 'manual' | 'regen',
    time: v.time,
  }))

const DOC_ROWS_BEFORE: StateDocRow[] = [
  { docId: 'DOC-001', name: FOCUS_DOC, version: 'V4' },
  { docId: 'DOC-002', name: JOURNEY_DOC, version: 'V3' },
  { docId: 'DOC-003', name: MODEL_DOC, version: 'V1' },
  { docId: 'DOC-004', name: PAGE_DOC, version: 'V3' },
]

const DOC_ROWS_AFTER: StateDocRow[] = [
  { docId: 'DOC-001', name: FOCUS_DOC, version: 'V5' },
  { docId: 'DOC-002', name: JOURNEY_DOC, version: 'V4' },
  { docId: 'DOC-003', name: MODEL_DOC, version: 'V2' },
  { docId: 'DOC-004', name: PAGE_DOC, version: 'V4' },
]

// ---------------------------------------------------------------------------
// the two frames. `outlineRef` is 'C1'/'C2' on purpose: the outline has no C
// step (that gap IS this task) — the pair stands at D6's moment, before and
// after its commit, and must not be mistaken for an outline step.
// ---------------------------------------------------------------------------

export const COMMIT_STATES: CommitStateSnapshot[] = [
  {
    id: 'C1',
    outlineRef: 'C1',
    phase: 'design',
    label: 'C1 · 提交页签',
    title: '提交页签 · 本次迭代的待提交改动',
    caption: '工具边栏「提交」页签亮着：本次（第三轮）迭代动过的 4 篇文档列在「待提交的改动」里，下面是前两轮迭代的提交历史',
    docs: DOC_ROWS_BEFORE,
    selectedDoc: FOCUS_DOC,
    // the center shows the doc being edited; the frame's headline is the
    // SIDEBAR tab, which is what `activeSidebarTab` pins
    activeSurface: 'doc',
    buffer: COMMITTED_V5,
    baseline: BASELINE_V4,
    committedVersion: 'V4',
    workingVersionLabel: 'V5',
    dirty: true,
    diffBadge: true,
    commitEnabled: true,
    versionHistory: historyRows(FOCUS_TRAIL_V4),
    activeSidebarTab: 'commits',
    changed: CHANGED_THIS_ITERATION,
    commits: HISTORY_BEFORE,
    fixture: beforeFixture(),
  },
  {
    id: 'C2',
    outlineRef: 'C2',
    phase: 'design',
    label: 'C2 · 提交页签（提交后）',
    title: '提交页签 · 提交后（改动清空，历史多一条）',
    caption: '点了「提交全部」：待提交的改动清空，提交历史多一条本轮迭代的记录，四篇文档各出一版',
    docs: DOC_ROWS_AFTER,
    selectedDoc: FOCUS_DOC,
    activeSurface: 'versionHistory',
    buffer: COMMITTED_V5,
    baseline: COMMITTED_V5,
    committedVersion: 'V5',
    workingVersionLabel: '',
    dirty: false,
    diffBadge: false,
    commitEnabled: false,
    versionHistory: historyRows([FOCUS_V5_ROW, ...FOCUS_TRAIL_V4]),
    activeSidebarTab: 'commits',
    // 空态也是数据：nothing pending, and the fixture agrees
    changed: [],
    commits: [HISTORY_NEW, ...HISTORY_BEFORE],
    fixture: afterFixture(),
  },
]