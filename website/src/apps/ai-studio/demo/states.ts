// The state-snapshot layer for the state-direct demo (`?demo=states`).
//
// This is the "给定状态直接渲染" half of the AI-Studio demo redesign (ACP-787,
// parent ACP-786). Where the step-replay runtime (runtime.ts + steps/fixtures
// JSON) reaches a picture by replaying locator acts onto the real editor, this
// module holds a COMPLETE, immutable snapshot per state: everything the page
// must show is a field on the object, and the renderer is a pure function of
// the selected snapshot. Back and forward are both "read state n" — there is
// no operation chain to run, nothing to leave dirty, no reverse computation
// (the v9 `rebuildToCursor` replay mechanism is explicitly NOT copied).
//
// FIELD ALIGNMENT (owner 补充): D1 only ships the minimal 3-state subset
// (raw/ai-studio-acceptance/demo-script-outline.md 附三 maps them to S1-0 /
// S1-2 / S1-3), but every field below is named so the full 3-phase / 42-step
// outline can be layered on later without reshaping the type:
//   - `outlineRef` pins which outline step each snapshot stands for, so the
//     future build-out extends this list rather than renumbering it.
//   - the version vocabulary (`committedVersion` / `workingVersionLabel`, and
//     the odd=manual / even=regen parity rule from 附一) rides the same words
//     `StudioVersion` already carries.
//   - the "dirty = workspace differs from the last commit, commit clears it"
//     rule (附一 脏与提交) is the same fact `DemoFixture`'s draft store models,
//     so `fixture` and the declarative markers can never disagree.
import type { StudioDoc } from '../studioApi'
import type { DemoFixture } from './types'

/** The product stage a state belongs to — the current AI-Studio happy path
 * (owner 范围更正): design → release → dev → deploy. D1 ships design-phase
 * states only, but the field is here from day one so a later 发版/开发/部署
 * state is `{ phase: 'release', activeSurface: 'release', fixture: {...release} }`
 * — a data addition plus one render branch, never a reshape of this type. */
export type DemoPhase = 'design' | 'release' | 'dev' | 'deploy'

/** Which center surface a state shows. The values cover the WHOLE design-phase
 * pipeline the owner named (文档 / 聊天+AI建议 / diff / 提交 / 版本历史 / 图谱)
 * plus the three later stages, so the enumeration is closed against the
 * product, not against what D1 happens to render. D1 draws `list` / `doc` /
 * `diff`; the rest are reserved positions — a future state names one and the
 * renderer gains a branch for it. */
export type StateSurface =
  | 'list'           // 文档列表（无打开项，welcome/empty centre）
  | 'doc'            // 编辑器：文档正文 / 工作区缓冲
  | 'diff'           // 当前 diff：V(n) → 工作区行级差异
  | 'chat'           // 聊天 + AI 建议（reserved；fixture 可带 chatThread/aiSuggestions）
  | 'versionHistory' // 版本历史（reserved；parity=奇偶即来源，附一）
  | 'graph'          // 需求图谱（reserved；fixture.graph 携带）
  | 'commit'         // 提交汇总（reserved；ProjectCommitBar 已贯穿各态）
  | 'release'        // 发版（reserved；fixture.release/generatedFiles）
  | 'dev'            // 开发（reserved；fixture.devRun）
  | 'deploy'         // 部署（reserved；后续 deploy fixture 位）

/** One row of the left doc list. `docId`/`version` are the outline's DOC-00N
 * identity and its CURRENT committed label (odd=manual / even=regen — 附一).
 * Display data; the fake's committed text lives on `fixture.docs` keyed by
 * `name`. */
export interface StateDocRow {
  docId: string
  name: string
  version: string
}

/** One committed version row, aligned to the `StudioVersion` parity vocabulary
 * (version/parity/source) the future 版本历史 surface renders. Optional on a
 * state — the design frames that show it seed it from the snapshot's real
 * trail; empty is not a gap, it means "this frame never opened history". */
export interface StateVersionRow {
  version: string
  parity: 'odd' | 'even'
  source: 'manual' | 'regen'
  time: number
}

/** A complete, directly-renderable picture of one demo state. */
export interface StateSnapshot {
  id: string
  /** the outline step this snapshot stands for (附三 mapping) */
  outlineRef: string
  /** which stage of the happy path this frame is in (design → release → dev → deploy) */
  phase: DemoPhase
  /** short label used on the dock's direct-select button */
  label: string
  /** the state title (the dock's "当前" headline) */
  title: string
  /** one line describing what the frame looks like (附二 "当前：<这一步>") */
  caption: string

  // ---- the doc list, shown on every state (data, not a scattered if) ----
  docs: StateDocRow[]
  /** the focused doc name, or null on the list-only frame (S1) */
  selectedDoc: string | null
  /** which center surface this frame shows */
  activeSurface: StateSurface

  // ---- the editor / diff payload for the open frame ----
  /** workspace buffer (may differ from the committed baseline — that gap IS
   * the dirty state, declared as data, not read from a live typing session) */
  buffer: string
  /** the committed baseline (V(n)) the buffer diffs against */
  baseline: string
  /** committed version label, e.g. "V4" */
  committedVersion: string
  /** the version the working buffer would become on commit, e.g. "V5" */
  workingVersionLabel: string

  // ---- the declarative markers the renderer paints ----
  /** 「有未提交修改」 — data, drives the editor dirty chip */
  dirty: boolean
  /** the Diff tab's 红点角标 */
  diffBadge: boolean
  /** whether the project commit button is enabled for this frame */
  commitEnabled: boolean

  // ---- reserved design-phase fields (owner 范围更正) ----
  // D1's three frames leave most of these undefined — they are the PIPELINE
  // POSITIONS the fuller design phase fills, not speculative UI. Every one
  // mirrors a shape already used elsewhere in the app, so wiring a future
  // state that uses it is data + one render branch, never a type edit.
  /** 聊天线程（reserved：design-phase `activeSurface: 'chat'` 渲染它） */
  chatThread?: { role: 'user' | 'ai'; text: string }[]
  /** AI 建议（reserved：`chat` 面板上「采纳/忽略」的建议行） */
  aiSuggestions?: { id: string; text: string; applied?: boolean }[]
  /** 版本历史（reserved：`versionHistory` 面板；parity 奇=人工/偶=反生，附一） */
  versionHistory?: StateVersionRow[]
  /** 图谱一句话摘要（reserved：`graph` 面板的说明行；全量结构在 fixture.graph） */
  graphNote?: string

  /** the snapshot-backed fake's whole world for this frame — seeded so the
   * data layer (via `createDemoApi`) agrees with every marker above and no
   * fetch is ever issued (`?demo=` guard). For the dirty frames this carries a
   * draft record whose content differs from the committed doc, which is what
   * genuinely enables `ProjectCommitBar` from real data.
   *
   * This is ALSO where the later stages reserve their payload: `DemoFixture`
   * already carries `graph` / `release` / `generatedFiles` / `distillation` /
   * `regeneration` / `devRun` / `runPreview` / `freeze` (the studioApi-shaped
   * world), so a 发版/开发/部署 state adds a `fixture` populating the matching
   * field and sets `activeSurface` — the design-phase graph/release/dev data
   * slots are open, not invented later. */
  fixture: DemoFixture
}

// ---------------------------------------------------------------------------
// The shared world for the minimal subset: the first-round membership doc
// standing at V4 (odd = a human-committed version, 附一). S2 appends a plain-
// language paragraph to the workspace WITHOUT committing it, so V4 stays the
// baseline and the appended text is the uncommitted (→ V5) working buffer.
// ---------------------------------------------------------------------------

const DEMO_PROJECT = { id: 'demo-product', name: '会员积分系统', description: '状态驱动演示项目', createdAt: 1735689600 }

const FOCUS_DOC = '产品需求设计文档.md'
const FOCUS_ID = 'DOC-001'

/** the committed V4 text (the baseline every frame diffs against) */
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

/** the workspace buffer: V4 plus a plain-language supplement, not yet
 * committed — this difference is the whole "有未提交修改" claim (S1-2) */
const BUFFER_V5 = BASELINE_V4 + `
## 5. 用户补充
大额采购需追加一级审批，审批人请假时自动转交代理人。
`

/** the four-doc list as the outline's S1-0 sees it (committed labels only) */
const DOC_ROWS: StateDocRow[] = [
  { docId: FOCUS_ID, name: FOCUS_DOC, version: 'V4' },
  { docId: 'DOC-002', name: '用户旅程设计.md', version: 'V2' },
  { docId: 'DOC-003', name: '业务模型设计.md', version: 'V1' },
  { docId: 'DOC-004', name: '页面交互设计.md', version: 'V2' },
]

/** the docs the fake serves: only the focused doc's committed text is read by
 * the commit path (`listDraftDocs` compares the draft against it); the others
 * ride along so `getProject` lists the full set. */
const FIXTURE_DOCS: StudioDoc[] = [
  { name: FOCUS_DOC, content: BASELINE_V4 },
  { name: '用户旅程设计.md', content: '# 用户旅程设计\n' },
  { name: '业务模型设计.md', content: '# 业务模型设计\n' },
  { name: '页面交互设计.md', content: '# 页面交互设计\n' },
]

/** a clean fixture (S1): no draft → commit disabled, editor would be clean */
function cleanFixture(): DemoFixture {
  return {
    project: DEMO_PROJECT,
    focusDoc: FOCUS_DOC,
    buffer: BASELINE_V4,
    docs: FIXTURE_DOCS.map((d) => ({ ...d })),
    draftVersions: [],
    versions: {},
    recentActivity: [],
  }
}

/** a dirty fixture (S2/S3): one draft record whose content differs from the
 * committed doc → `listDraftDocs` reports it `changed`, which is exactly what
 * enables the project commit button and the pending-drafts badge from DATA */
function dirtyFixture(): DemoFixture {
  return {
    ...cleanFixture(),
    buffer: BUFFER_V5,
    draftVersions: [{ name: FOCUS_DOC, time: 1735689900, content: BUFFER_V5 }],
  }
}

// ---------------------------------------------------------------------------
// The three states, in the forward order the dock walks (S1 → S2 → S3). Each
// is a full immutable snapshot; switching is a re-read, so the same state
// always renders the same picture, front-to-back or back-to-front.
// ---------------------------------------------------------------------------

export const DEMO_STATES: StateSnapshot[] = [
  {
    id: 'S1',
    outlineRef: 'S1-0',
    phase: 'design',
    label: 'S1 · 文档列表',
    title: '文档列表 · 干净',
    caption: '左侧文档列表，中间未打开任何文档（干净起始态）',
    docs: DOC_ROWS,
    selectedDoc: null,
    activeSurface: 'list',
    buffer: BASELINE_V4,
    baseline: BASELINE_V4,
    committedVersion: 'V4',
    workingVersionLabel: '',
    dirty: false,
    diffBadge: false,
    commitEnabled: false,
    fixture: cleanFixture(),
  },
  {
    id: 'S2',
    outlineRef: 'S1-2',
    phase: 'design',
    label: 'S2 · 未提交修改',
    title: '打开需求文档 · 有未提交修改',
    caption: '《产品需求设计文档》已打开（V4），工作区有未提交修改（将提交为 V5），Diff 页签带角标，提交可用',
    docs: DOC_ROWS,
    selectedDoc: FOCUS_DOC,
    activeSurface: 'doc',
    buffer: BUFFER_V5,
    baseline: BASELINE_V4,
    committedVersion: 'V4',
    workingVersionLabel: 'V5',
    dirty: true,
    diffBadge: true,
    commitEnabled: true,
    // the committed V4 is an ODD row, so per 附一 its provenance is a manual
    // commit — the reserved 版本历史 field is wired to the real parity rule,
    // not a decorative list. D1's editor frame does not open history; this is
    // the slot a future versionHistory state reads.
    versionHistory: [{ version: 'V4', parity: 'odd', source: 'manual', time: 1735689600 }],
    fixture: dirtyFixture(),
  },
  {
    id: 'S3',
    outlineRef: 'S1-3',
    phase: 'design',
    label: 'S3 · 当前 Diff',
    title: '当前 Diff',
    caption: '「当前 Diff」页签：V4 → 工作区的行级差异，新增行高亮',
    docs: DOC_ROWS,
    selectedDoc: FOCUS_DOC,
    activeSurface: 'diff',
    buffer: BUFFER_V5,
    baseline: BASELINE_V4,
    committedVersion: 'V4',
    workingVersionLabel: 'V5',
    dirty: true,
    // the badge is consumed by the act of opening the diff you're looking at
    diffBadge: false,
    commitEnabled: true,
    versionHistory: [{ version: 'V4', parity: 'odd', source: 'manual', time: 1735689600 }],
    fixture: dirtyFixture(),
  },
]

export const DEFAULT_STATE_ID = 'S1'

export const STATE_COUNT = DEMO_STATES.length
