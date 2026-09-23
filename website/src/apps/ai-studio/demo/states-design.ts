// Design-phase states D6~D8 of the state-direct demo (ACP-790, parent ACP-789)
// — the continuation of the S1/S2/S3 world in `states.ts` (raw/ai-studio-
// acceptance/demo-script-outline.md 阶段一).
//
// This file is DATA ONLY by contract: it exports a `StateSnapshot[]` and imports
// nothing but types — plus, since ACP-797, the graph wave itself from
// `states-graph.ts`, which owns it. Public files (`states.ts`, `StateDemo.tsx`,
// `AiStudioPage.tsx`) are untouched — the master wires these frames into the
// renderer. Because the renderer does not draw every reserved surface yet, the
// CONTRACT tests in `states-design.test.tsx` mount the REAL business components
// this phase's story feeds (DocEditor's version-history popover, RegenDiffPair,
// ProjectCommitBar, and the 需求图谱 tab of the real ToolSidebar) with exactly
// the data each snapshot carries, so the testid and copy assertions are checked
// against the shipped components, not against a look-alike built for the test.
//
// THE STORY so far (carried over verbatim from states.ts): the 会员积分系统
// stands at V4 on 《产品需求设计文档.md》; the workspace holds the uncommitted
// 「## 5. 用户补充」 rule (大额采购需追加一级审批…). D6 commits it, D7 is the
// graph that commit feeds, D8 is the three downstream docs syncing to the
// regenerated facts.
//
// D7 IS A LIST, NOT A CANVAS (ACP-797, owner 口径): the 需求图谱 is observed in
// the tool sidebar's 「需求图谱」 tab as entries grouped by type, never as a
// box-and-arrow graph in the middle column — so D7 names no `graph` surface,
// its center is the doc editor like every other design frame, and the graph it
// carries is handed to the tab through `graphEntries` (the same derivation the
// G1/G2 frames use, from the same wave).
//
// PARITY DISCIPLINE (附一): a version row's number parity and its
// parity/source fields are the same fact — vN odd ⇔ manual, even ⇔ regen.
// Every trail below (including every downstream doc's) satisfies this, and
// `states-design.test.tsx` walks ALL rows to prove it, so no frame can show a
// badge the numbering contradicts. NOTE for the master: states.ts's S2 seed
// carries V4 as odd/manual and the D1 doc rows top the downstream at V2/V1/V2;
// the strictly-even-regen reading here tops them at v3/v1/v3 in D6~D7 (V3/V1/V3
// in the list) so the D8 regen rows can be even. Reconcile S1/S2 or these —
// one of the two should move, and it is not this file (read-only contract).
//
// TWO LABEL VOCABULARIES, deliberately: the doc-list display fields
// (`docs[].version`, `committedVersion`) keep states.ts's uppercase style ("V5");
// the version ROW labels (`StateVersionRow.version` and the fixture rows
// DocEditor renders) use the lowercase "v5" the shipped fixtures already use
// (fixtures/state-main-013.json), which is what the outline's
// `version-row-vN` testid literally spells.
import type { StateDocRow, StateSnapshot, StateVersionRow } from './states'
import type { DemoFixture } from './types'
import { DISTILL_CANDIDATES, DISTILLATION, GRAPH_DELTA, GRAPH_WAVE, graphEntryGroups } from './states-graph'
import type { StudioDiffGroup, StudioDoc, StudioVersion } from '../studioApi'

// ---------------------------------------------------------------------------
// the world carried over from states.ts (re-declared, not imported: states.ts
// exports no constants; the strings are kept byte-identical to its S1~S3 so
// the commit in D6 lands exactly the buffer S2/S3 showed).
// ---------------------------------------------------------------------------

const DEMO_PROJECT = { id: 'demo-product', name: '会员积分系统', description: '状态驱动演示项目', createdAt: 1735689600 }

const FOCUS_DOC = '产品需求设计文档.md'
const JOURNEY_DOC = '用户旅程设计.md'
const MODEL_DOC = '业务模型设计.md'
const PAGE_DOC = '页面交互设计.md'

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

/** the committed text AFTER D6: exactly the S2/S3 workspace buffer — the
 * supplement paragraph is what this round's commit carries into history */
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

/** 用户旅程设计.md v4 — the D8 regen row's committed content (even = 图谱反生) */
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
// committed-version trails (StudioVersion rows — DocEditor's version-history
// contract). Newest first, exactly the order the fake's listVersions returns.
// ---------------------------------------------------------------------------

/** one diff hunk header + lines, the way generate_fixtures.py emits them */
function hunk(h: string, ...lines: string[]): string {
  return `--- previous\n+++ current\n@@ ${h} @@\n${lines.join('')}`
}

const V5_DIFF = hunk(
  '-14,3 +14,7',
  ' ## 4. 规则\n',
  ' - 消费 1 元累积 1 积分\n',
  ' - 100 积分抵扣 1 元\n',
  '+\n',
  '+## 5. 用户补充\n',
  '+大额采购需追加一级审批，审批人请假时自动转交代理人。\n',
)

/** one trail row: number parity IS the provenance (附一), so `source` is
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

/** 产品需求设计文档.md's trail. After D6's commit the newest row is v5
 * (odd/manual) — the frame's whole assertion. */
const FOCUS_TRAIL: StudioVersion[] = [
  row('v5', 1735692000, V5_DIFF),
  row('v4', 1735660000, hunk('-12,2 +12,3', ' - 100 积分抵扣 1 元\n', '+- 大促期间双倍积分\n', ' ')),
  row('v3', 1735650000, hunk('-6,1 +6,2', ' ## 2. 目标\n', '+- 提升复购率。\n')),
  row('v2', 1735610000, hunk('-1,3 +1,4', ' # 产品需求设计文档\n', '\n', '+## 1. 背景\n', '+会员积分系统面向 C 端用户。\n')),
  row('v1', 1735600000, hunk('-0,0 +1,5', '+# 产品需求设计文档\n', '+\n', '+## 2. 目标\n', '+提升复购率。\n', '+### 积分获取与兑换\n')),
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

/** D8's new even rows, one per downstream doc — each sliced from the exact
 * lines that doc's regenerated content adds over its odd predecessor. */
const JOURNEY_V4_ROW = row('v4', 1735695000, hunk(
  '-6,1 +6,4',
  ' 4. 优惠券核销\n',
  '+\n',
  '+## 审批分支（图谱反生）\n',
  '+- 大额采购订单先经一级审批，审批人请假自动转交代理人\n',
))
const MODEL_V2_ROW = row('v2', 1735695000, hunk(
  '-6,1 +6,3',
  '- 兑换订单\n',
  '+\n',
  '+## 审批单（图谱反生）\n',
  '+- 字段：申请人、审批人、代理人、结果\n',
))
const PAGE_V4_ROW = row('v4', 1735695000, hunk(
  '-5,1 +5,3',
  '- 兑换记录页\n',
  '+\n',
  '+## 大额采购审批提示（图谱反生）\n',
  '+- 提交大额采购单时弹出：需一级审批通过后发放积分\n',
))

// ---------------------------------------------------------------------------
// the graph wave D7 shows and the distillation D8 applies are both owned by
// `states-graph.ts` (ACP-797) and imported above: the design slice's 图谱修订
// and the 提交 slice's 生成过程 are two moments of ONE wave, so a second copy
// here could only drift. What stays local is D8's regeneration data below —
// the regenerated document and the three-segment groups pairing every
// structured change against the user's diff and the regen's diff.
// ---------------------------------------------------------------------------

const REGENERATION = {
  version: 'v4',
  generatedFrom: DISTILLATION.id,
  docName: JOURNEY_DOC,
  content: JOURNEY_V4,
}

/** the outline's 成组 Diff 三段. Every non-empty line below is a line one of
 * this file's version-row diffs carries (the test re-checks it against the
 * fixture, mirroring what check_regen does for the generated fixtures). */
const DIFF_GROUPS: StudioDiffGroup[] = [
  {
    point: '大额采购一级审批',
    candidateId: 'dc-add-approval-req',
    structuredChanges: [DISTILL_CANDIDATES[0]],
    userDiff: '+大额采购需追加一级审批，审批人请假时自动转交代理人。\n',
    regenDiff: '+## 审批分支（图谱反生）\n+- 大额采购订单先经一级审批，审批人请假自动转交代理人\n',
  },
  {
    point: '审批服务模块',
    candidateId: 'dc-add-approval-service',
    structuredChanges: [DISTILL_CANDIDATES[1]],
    // a purely distilled point has no user lines — the empty side is data
    userDiff: '',
    regenDiff: '+## 审批单（图谱反生）\n+- 字段：申请人、审批人、代理人、结果\n',
  },
  {
    point: '消费积分前置审批',
    candidateId: 'dc-modify-points-earn',
    structuredChanges: [DISTILL_CANDIDATES[2]],
    userDiff: '+大额采购需追加一级审批，审批人请假时自动转交代理人。\n',
    regenDiff: '+## 大额采购审批提示（图谱反生）\n+- 提交大额采购单时弹出：需一级审批通过后发放积分\n',
  },
  {
    point: '人工调分移除',
    candidateId: 'dc-remove-manual-adjust',
    structuredChanges: [DISTILL_CANDIDATES[3]],
    // a graph-only removal has none on either side
    userDiff: '',
    regenDiff: '',
  },
]

// ---------------------------------------------------------------------------
// fixture builders: one trail map per frame, docs contents per frame.
// ---------------------------------------------------------------------------

function versionsThrough(
  journey: StudioVersion[], model: StudioVersion[], page: StudioVersion[],
): Record<string, StudioVersion[]> {
  return { [FOCUS_DOC]: FOCUS_TRAIL, [JOURNEY_DOC]: journey, [MODEL_DOC]: model, [PAGE_DOC]: page }
}

function docsBefore(journey: string, model: string, page: string): StudioDoc[] {
  return [
    { name: FOCUS_DOC, content: COMMITTED_V5 },
    { name: JOURNEY_DOC, content: journey },
    { name: MODEL_DOC, content: model },
    { name: PAGE_DOC, content: page },
  ]
}

/** D6/D7 base: everything committed (no drafts), the focus doc at v5, the
 * downstream docs still on their odd pre-regen tops (v3/v1/v3). */
function designFixture(recentActivity: { time: number; label: string }[]): DemoFixture {
  return {
    project: DEMO_PROJECT,
    focusDoc: FOCUS_DOC,
    buffer: COMMITTED_V5,
    docs: docsBefore(JOURNEY_V3, MODEL_V1, PAGE_V3),
    draftVersions: [],
    versions: versionsThrough(
      JOURNEY_TRAIL.map((r) => ({ ...r })),
      MODEL_TRAIL.map((r) => ({ ...r })),
      PAGE_TRAIL.map((r) => ({ ...r })),
    ),
    recentActivity,
  }
}

/** the committed frame's own versionHistory read-back (the flat field's
 * convention, states.ts S2: the FOCUS doc's trail, newest first) */
const FOCUS_HISTORY: StateVersionRow[] = FOCUS_TRAIL.map((v) => ({
  version: v.version as string,
  parity: v.parity as 'odd' | 'even',
  source: v.source as 'manual' | 'regen',
  time: v.time,
}))

const DOC_ROWS_V5: StateDocRow[] = [
  { docId: 'DOC-001', name: FOCUS_DOC, version: 'V5' },
  { docId: 'DOC-002', name: JOURNEY_DOC, version: 'V3' },
  { docId: 'DOC-003', name: MODEL_DOC, version: 'V1' },
  { docId: 'DOC-004', name: PAGE_DOC, version: 'V3' },
]

/** D8: downstream tops bumped to their even regen rows (V4/V2/V4) */
const DOC_ROWS_REGENNED: StateDocRow[] = [
  { docId: 'DOC-001', name: FOCUS_DOC, version: 'V5' },
  { docId: 'DOC-002', name: JOURNEY_DOC, version: 'V4' },
  { docId: 'DOC-003', name: MODEL_DOC, version: 'V2' },
  { docId: 'DOC-004', name: PAGE_DOC, version: 'V4' },
]

// ---------------------------------------------------------------------------
// the three states. `activeSurface` names the RESERVED positions (versionHistory
// / graph) — a future render branch, one per surface, is the master's wiring
// step; the data each branch needs is complete on these objects already.
// ---------------------------------------------------------------------------

export const DESIGN_STATES: StateSnapshot[] = [
  {
    id: 'D6',
    outlineRef: 'D6',
    phase: 'design',
    label: 'D6 · 提交出版本',
    title: '提交 → 版本历史多一版',
    caption: '工作区已提交：编辑器回到基线、脏标记消失，版本历史新增 v5（奇数版=人工修改），无草稿可提交',
    docs: DOC_ROWS_V5,
    selectedDoc: FOCUS_DOC,
    // the frame's headline is the version history; states.ts reserved this
    // surface position from day one (其注释：parity=奇偶即来源，附一)
    activeSurface: 'versionHistory',
    buffer: COMMITTED_V5,
    baseline: COMMITTED_V5,
    committedVersion: 'V5',
    workingVersionLabel: '',
    dirty: false,
    diffBadge: false,
    // no drafts on the fixture → ProjectCommitBar's real read disables the
    // button and removes drafts-pending from the DOM (附一 脏与提交)
    commitEnabled: false,
    versionHistory: FOCUS_HISTORY,
    fixture: designFixture([
      { time: 1735692000, label: '提交 v5' },
      { time: 1735689900, label: '草稿 产品需求设计文档.md' },
    ]),
  },
  {
    id: 'D7',
    outlineRef: 'D7',
    phase: 'design',
    label: 'D7 · 图谱修订',
    title: '图谱修订：这次改动动到了什么',
    caption: '工具边栏「需求图谱」页签里，图谱按类型列成条目：本次新增的两条、被细化的消费积分都带标记，人工调分模块划掉',
    docs: DOC_ROWS_V5,
    selectedDoc: FOCUS_DOC,
    // 中间列是文档编辑器（owner 口径）；图谱是边栏「需求图谱」页签里的列表，
    // 由 `graphEntries` 送进去，页面里不再出现方框箭头的画布
    activeSurface: 'doc',
    buffer: COMMITTED_V5,
    baseline: COMMITTED_V5,
    committedVersion: 'V5',
    workingVersionLabel: '',
    dirty: false,
    diffBadge: false,
    commitEnabled: false,
    versionHistory: FOCUS_HISTORY,
    graphNote: '本次提交喂图谱：新增 2 节点 / 新增 3 边 / 修改 1 / 移除 1',
    graphEntries: graphEntryGroups(GRAPH_WAVE, GRAPH_DELTA),
    fixture: {
      ...designFixture([
        { time: 1735694000, label: '图谱修订：+2 节点 / 改 1 / 删 1' },
        { time: 1735692000, label: '提交 v5' },
      ]),
      graph: GRAPH_WAVE,
      graphDelta: GRAPH_DELTA,
    },
  },
  {
    id: 'D8',
    outlineRef: 'D8',
    phase: 'design',
    label: 'D8 · 下游文档同步',
    title: '其余文档同步到新版本',
    caption: '图谱反生同步下游：三篇各出偶数版（v4/v2/v4，even=图谱反生），成组 Diff 三段核对本次改动',
    docs: DOC_ROWS_REGENNED,
    selectedDoc: JOURNEY_DOC,
    // the frame pairs the regen version rows with the three-segment review;
    // 'versionHistory' names its headline (三篇的新偶数版), the review's data
    // rides the fixture either way — the master picks the branch.
    activeSurface: 'versionHistory',
    buffer: JOURNEY_V4,
    baseline: JOURNEY_V4,
    committedVersion: 'V4',
    workingVersionLabel: '',
    dirty: false,
    diffBadge: false,
    commitEnabled: false,
    fixture: {
      ...designFixture([
        { time: 1735695000, label: '反向生成 ×3 篇' },
        { time: 1735694000, label: '图谱修订：+2 节点 / 改 1 / 删 1' },
        { time: 1735692000, label: '提交 v5' },
      ]),
      graph: GRAPH_WAVE,
      graphDelta: GRAPH_DELTA,
      distillation: DISTILLATION,
      regeneration: REGENERATION,
      diffGroups: DIFF_GROUPS,
      versions: {
        [FOCUS_DOC]: FOCUS_TRAIL,
        [JOURNEY_DOC]: [JOURNEY_V4_ROW, ...JOURNEY_TRAIL],
        [MODEL_DOC]: [MODEL_V2_ROW, ...MODEL_TRAIL],
        [PAGE_DOC]: [PAGE_V4_ROW, ...PAGE_TRAIL],
      },
      docs: docsBefore(JOURNEY_V4, MODEL_V2, PAGE_V4),
    },
  },
]
