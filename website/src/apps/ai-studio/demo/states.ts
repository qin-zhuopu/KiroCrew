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
// RETIRED SLICE (owner, ACP-794): this file used to carry the three opening
// design frames S1~S3 (干净列表 / 未提交修改 / 当前 Diff). The owner reviewed
// them against the wireframe and had them removed: their content is carried
// by the design phase's own opening frames now (C1 opens the doc with the
// pending changes, D6 the committed result), and three near-duplicate frames
// only made the dock longer. What stays here is the vocabulary every slice
// still imports — the frame type, the phase list, the doc/version row shapes.
// The sibling slices (states-design / states-commit / states-release /
// states-devdeploy) own the frames themselves and none of them imports a
// value from this file, so nothing else moved.
//
// FIELD ALIGNMENT (owner 补充): every field below is named so the full
// 3-phase / 42-step outline can be layered on later without reshaping the type:
//   - `outlineRef` pins which outline step each snapshot stands for, so the
//     future build-out extends this list rather than renumbering it.
//   - the version vocabulary (`committedVersion` / `workingVersionLabel`, and
//     the odd=manual / even=regen parity rule from 附一) rides the same words
//     `StudioVersion` already carries.
//   - the "dirty = workspace differs from the last commit, commit clears it"
//     rule (附一 脏与提交) is the same fact `DemoFixture`'s draft store models,
//     so `fixture` and the declarative markers can never disagree.
import type { DemoFixture } from './types'
import type { GraphEntryGroup } from '../ToolSidebar'

/** The product stage a state belongs to — the current AI-Studio happy path
 * (owner 范围更正, then ACP-796): design → commit → release → dev → deploy.
 * D1 shipped design-phase states only, but the field has been here from day one
 * so a later 发版/开发/部署 state is
 * `{ phase: 'release', activeSurface: 'release', fixture: {...release} }`
 * — a data addition plus one render branch, never a reshape of this type.
 *
 * `'commit'` is the stage the owner split out of `'design'` (ACP-796): the
 * commit page and the requirement graph it produces are their own big step in
 * the product chain, not a tail of authoring. The dock groups by this value;
 * `allStates.ts` (not a slice file) is where a frame's slice default is
 * re-stated when the owner's stage model moves under it. */
export type DemoPhase = 'design' | 'commit' | 'release' | 'dev' | 'deploy'

/** Which center surface a state shows. The values cover the WHOLE design-phase
 * pipeline the owner named (文档 / 聊天+AI建议 / diff / 提交 / 版本历史 / 图谱)
 * plus the three later stages, so the enumeration is closed against the
 * product, not against what any one slice happens to render. Every value is
 * drawn by some merged slice today (the release / dev / deploy slices name
 * theirs); a value with no frame yet is a reserved position — a future state
 * names it and the renderer gains a branch for it. */
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
  /** the focused doc name, or null on a frame with no doc open (the release
   * frames' surface is the sidebar's 发布 tab, so they carry none) */
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
  /** the 需求图谱 tab's list for frames whose graph lives in that tab (ACP-797;
   * the full shape and its renderer seam live in ToolSidebar's `graphEntries`,
   * and states-graph.ts's GraphStateSnapshot carries the same field required).
   * A frame that names a doc row opens that doc in the middle column — never a
   * canvas there. */
  graphEntries?: GraphEntryGroup[]

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
