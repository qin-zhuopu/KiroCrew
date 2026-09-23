// The release-phase states (R1~R6) for the state-direct demo (`?demo=states`),
// ACP-791 — the second batch after the design-phase trio in `states.ts`.
//
// LIKE `states.ts`, every frame here is a COMPLETE, immutable snapshot: the
// renderer reads it and paints, prev/next/direct-select are all just "read
// state n" — no operation chain, nothing to leave dirty. Unlike the design
// trio, these six frames show REAL business components (PublishVersionList,
// ReleaseJobPage + DeployLog, RunPreviewScreen), so the payload below is
// shaped exactly like what those components read today:
//   - `versions` / `records`  — the GET /publish/versions and /publish/records
//     bodies (B4); the 已发布 state, the 发布按钮 hash rule and the R4 result
//     strip are all DERIVED by PublishVersionList from these two reads, never
//     restated here — this snapshot only carries the facts, the real component
//     re-derives the rule (same doctrine as ProjectCommitBar in `states.ts`).
//   - `previews` — B1's per-version form verdict (形态 + 判定原因), the source
//     of `ai-studio-publish-reason-<v>`.
//   - `jobs` / `logFrames` — R5's release-job history and the SSE replay the
//     page's DeployLog shows (frames are append-only tails, matching the real
//     `LogFrame` wire shape in DeployLog.tsx).
//   - `runPreview` — R6's experience screen, the same StudioRunPreview the
//     dev-phase demo already feeds RunPreviewScreen.
//   - `files` (ACP-798) — 本版修改过的文件: name, 新增/修改/删除, and each
//     file's 图谱拆解状态 (已 / 正在 / 尚未拆解成图谱). The release tab renders
//     one list ROW per file; no frame here draws a box-and-arrow diagram.
//
// WHY A SUBTYPE INSTEAD OF A `states.ts` EDIT (公共文件不改, the ticket's hard
// line): `StateSnapshot` carries no publish field and `DemoFixture` fakes only
// `StudioApi` (studioApi.ts: "the demo never fakes a publish entry"). So each
// frame below is a `ReleaseStateSnapshot` = StateSnapshot + `publish`. It stays
// a STRUCTURAL member of `StateSnapshot[]`: master's wiring can concatenate
// `[...DEMO_STATES, ...RELEASE_STATES]` with no cast, and reaches the payload
// through `isReleaseState` (a positive phase + field check, never a negative
// test). The payload keys mirror the publishApi method names one-for-one so
// the snapshot-backed fake is a lookup, not a translation.
//
// WIRING THE RENDERER NEEDS (posted to ACP-791 before this file was written):
//  1. a snapshot-backed `publishApi` stand-in for the release branch — the
//     module singleton's `?demo=` guard throws on every read otherwise (the
//     states-release.test.tsx mocks are the worked example of exactly which
//     answers each frame needs);
//  2. R3: 「发布中」 is PublishVersionList's LOCAL run state, only reachable
//     through its real trigger path — the frame declares `inFlight` and the
//     renderer performs the frame's ONE real click on `ai-studio-publish-btn-
//     <v>` after mount (fake trigger never resolves), a single act per frame,
//     not a replay chain;
//  3. R5: DeployLog streams over a raw `EventSource` (SSE, not fetch) — the
//     replay plays `logFrames` through an EventSource stand-in, else the tab
//     honestly 404s the fake job id;
//  4. R6: the serving address is a deployed app no snapshot can open
//     fetch-free, so the frame lands on the real 体验页 (RunPreviewScreen)
//     whose lines carry this iteration's new rule; the address string itself
//     still shows verbatim on R4's result bar (template 版本号-应用名-工号
//     .gb10.jereh-pe.cn, the scheme-less shape publish_url() actually stores).
//  5. ACP-798: `files` rides a NEW optional prop on ToolSidebar /
//     PublishVersionList (`releaseFiles`), omitted by every ordinary
//     workbench — its default is exactly today's render, so the releases tab
//     is unchanged where the demo is not. The section is a list; the demo's
//     center column stays the doc editor (`selectedDoc`), per owner 口径.
//
// STORY CONSISTENCY (asserted by states-release.test.tsx): the design phase
// committed 产品需求设计文档.md as V5 (odd = manual, 附一) — the tag cut from
// that commit IS the publish version `v5`. R3's in-flight deploymentId, R4's
// success record and R5's selected job are ONE job (job-v5): the frames are
// six reads of one world advancing, so jumping back and forth never shows a
// run whose facts disagree with the frame you came from.
import type {
  StudioPublishJob,
  StudioPublishPreview,
  StudioPublishRecord,
  StudioPublishVersion,
  StudioReleaseFiles,
  StudioRunPreview,
} from '../studioApi'
import type { DemoFixture } from './types'
import type { StateDocRow, StateSnapshot } from './states'

/** What the release branch of the renderer needs beyond the base snapshot.
 * The optional members are per-frame positions, same style as `states.ts`:
 * `jobs`/`logFrames` exist only from R5 on, `runPreview` only on R6 — a frame
 * missing a field means that picture has no such fact, not an empty render. */
export interface ReleasePublishPayload {
  /** GET /publish/versions — the rows (tag + hash), newest first */
  versions: StudioPublishVersion[]
  /** GET /publish/records — success facts (B3/B4); drives 已发布, the hash
   * rule and the R4 result strip. BEFORE the R4 settle this holds only the
   * previous releases; from R4 on it leads with the v5 record. */
  records: StudioPublishRecord[]
  /** GET /publish/preview per version (B1): 形态 + 判定原因 */
  previews: Record<string, StudioPublishPreview>
  /** R2~R6: the version this frame is about (the row the presenter points at) */
  focusVersion?: string
  /** R3 ONLY: the run the frame lands with — the renderer clicks that row's
   * real 发布 button once (fake trigger never resolves), and the component's
   * own code paints 发布中. Absent = no run in flight on this frame. */
  inFlight?: { version: string; deploymentId: string }
  /** R5: the release-job history (GET /publish/jobs), newest first */
  jobs?: StudioPublishJob[]
  /** R5: the selected job (ReleaseJobPage's route param / log target) */
  selectedJobId?: string
  /** R5: the DeployLog SSE replay — append-only frames, last one done=true */
  logFrames?: { lines: string[]; done: boolean; status: string }[]
  /** ACP-798: 本版修改过的文件 — which files this version changed, HOW, and
   * where each stands in the distillation into the requirement graph. Data
   * only: the release tab renders one list row per file. Every frame carries
   * it (owner 口径: 一个发版状态里要能读出「历史版本」和「本版改动文件」两样). */
  files?: StudioReleaseFiles
  /** ACP-798 (owner 追加): the 发版 tab's own top action — 动作按钮跟着页签走.
   * `version` is the version the button fires for; `phaseKeys` are i18n KEYS
   * for the pending walk (labels are resolved where they render — this file
   * holds no literal label). Every release frame declares it, so the 发版 tab
   * always carries the button; the component disables it wherever that
   * version's row would lose its own 发布 button (the §〇 hash rule). */
  releaseAction?: { version: string; phaseKeys: string[] }
  /** R6: what 「打开这一版」 shows — the real RunPreviewScreen's data */
  runPreview?: StudioRunPreview
}

/** A release-phase state: the base snapshot plus its publish world. */
export interface ReleaseStateSnapshot extends StateSnapshot {
  publish: ReleasePublishPayload
}

/** Positive identity (harness-parity doctrine): a release frame IS one by
 * phase + payload, never by "not a design frame". */
export function isReleaseState(s: StateSnapshot): s is ReleaseStateSnapshot {
  return s.phase === 'release' && 'publish' in s
}

// ---------------------------------------------------------------------------
// The shared release-phase world. The doc texts are re-declared here (NOT
// imported from states.ts — those consts are module-private and the file is
// frozen): the R frames stand AFTER the design phase committed V5, so the
// baseline is the design phase's working buffer promoted to committed.
// ---------------------------------------------------------------------------

const DEMO_PROJECT = { id: 'demo-product', name: '会员积分系统', description: '状态驱动演示项目', createdAt: 1735689600 }

const FOCUS_DOC = '产品需求设计文档.md'
const FOCUS_ID = 'DOC-001'

/** the committed V5 text: the V4 baseline plus 本次迭代新增的审批规则
 * (the same paragraph the design-phase trio carried as the uncommitted
 * supplement — committing it is the bridge between the two batches) */
const BASELINE_V5 = `# 产品需求设计文档

## 1. 背景
会员积分系统面向 C 端用户。

## 2. 目标
提升复购率。

## 3. 范围
积分获取与兑换。

## 4. 规则
- 消费 1 元累积 1 积分
- 100 积分抵扣 1 元

## 5. 用户补充
大额采购需追加一级审批，审批人请假时自动转交代理人。
`

/** the new rule, in one line — the graph's requirement node, the R6 feature
 * list's added row, and the sentence the whole iteration is about */
export const NEW_RULE = '大额采购需追加一级审批（审批人请假时自动转交代理人）'

/** the doc list as the release phase sees it: 需求文档 now stands at the
 * committed V5 (odd = manual, 附一 — the design phase's commit landed) */
const DOC_ROWS: StateDocRow[] = [
  { docId: FOCUS_ID, name: FOCUS_DOC, version: 'V5' },
  { docId: 'DOC-002', name: '用户旅程设计.md', version: 'V2' },
  { docId: 'DOC-003', name: '业务模型设计.md', version: 'V1' },
  { docId: 'DOC-004', name: '页面交互设计.md', version: 'V2' },
]

/** the publish tags: v5 is this iteration's commit (doc V5 → tag v5), v4 was
 * the previous release (the version serving now), v3 an older demo-form one.
 * 40-hex like real git hashes; the rows show slice(0,7) verbatim. */
const HASH_V5 = 'f5a1c0d3e7b2496c8d0e1f2a3b4c5d6e7f8091a2'
const HASH_V4 = 'd4b0e1f2a3b4c5d6e7f8091a2b3c4d5e6f7a8b9c'
const HASH_V3 = 'c3a9f8e7d6c5b4a3928170f6e5d4c3b2a1908f7e'

/** the serving-url template's actual output (publish.py URL_TEMPLATE —
 * 版本号-应用名-工号.gb10.jereh-pe.cn, scheme-less as the record stores it;
 * 应用名 is the project's app slug, 工号 the operator's) */
export const URL_V5 = 'v5-points-14409.gb10.jereh-pe.cn'
const URL_V4 = 'v4-points-14409.gb10.jereh-pe.cn'
const URL_V3 = 'v3-points-14409.gb10.jereh-pe.cn'

const VERSIONS: StudioPublishVersion[] = [
  { version: 'v5', commitHash: HASH_V5, time: 1735692000 },
  { version: 'v4', commitHash: HASH_V4, time: 1735680000 },
  { version: 'v3', commitHash: HASH_V3, time: 1733000000 },
]

/** B1's per-version verdict — the tag annotation's own words (完整版/演示版) */
const PREVIEWS: Record<string, StudioPublishPreview> = {
  v5: { form: 'full', reason: 'git tag 标注：完整版（四篇设计文档均已提交，验收通过）' },
  v4: { form: 'full', reason: 'git tag 标注：完整版' },
  v3: { form: 'demo', reason: 'git tag 标注：演示版（页面交互设计缺失）' },
}

const RECORD_V4: StudioPublishRecord = {
  deploymentId: 'job-v4', version: 'v4', commitHash: HASH_V4, form: 'full',
  requirementVersion: 'V4', jiraTaskIds: [], status: 'success', url: URL_V4, ts: 1735680600,
}
const RECORD_V3: StudioPublishRecord = {
  deploymentId: 'job-v3', version: 'v3', commitHash: HASH_V3, form: 'demo',
  requirementVersion: 'V3', jiraTaskIds: [], status: 'success', url: URL_V3, ts: 1733000600,
}
/** the record R3's run WRITES on success — it appears at the head of the
 * records read from R4 on (the settle is the record landing, B4) */
const RECORD_V5: StudioPublishRecord = {
  deploymentId: 'job-v5', version: 'v5', commitHash: HASH_V5, form: 'full',
  requirementVersion: 'V5', jiraTaskIds: [], status: 'success', url: URL_V5, ts: 1735693200,
}

/** before the v5 publish: latest success = v4 → v4 has NO button (hash rule),
 * v5 has one (new), v3 has one (an old hash — a rollback re-publish is legal,
 * §〇's D3 case) */
const RECORDS_BEFORE: StudioPublishRecord[] = [RECORD_V4, RECORD_V3]
/** from R4 on: v5 is the newest success → its button is gone, v4's returns */
const RECORDS_AFTER: StudioPublishRecord[] = [RECORD_V5, RECORD_V4, RECORD_V3]

const JOBS: StudioPublishJob[] = [
  { id: 'job-v5', version: 'v5', form: 'full', status: 'success', ts: 1735693200, commitHash: HASH_V5 },
  { id: 'job-v4', version: 'v4', form: 'full', status: 'success', ts: 1735680600, commitHash: HASH_V4 },
  { id: 'job-v3', version: 'v3', form: 'demo', status: 'success', ts: 1733000600, commitHash: HASH_V3 },
]

/** the job-v5 execution log as the SSE stream replayed it — append-only
 * frames (each `lines` is NEW since the last), the final frame done=true
 * (08 §〇-2 完成即全量回放). The last line quotes the serving url exactly as
 * publish.py's executor logs it (发布地址 …（pid …）). */
const LOG_FRAMES = [
  { lines: ['开始发布 v5（完整版） commit ' + HASH_V5.slice(0, 7)], done: false, status: 'running' },
  { lines: ['产物构建完成', '部署上线（单实例替换旧版本）'], done: false, status: 'running' },
  { lines: ['健康检查通过', `发布地址 ${URL_V5}（pid 4821）`], done: true, status: 'success' },
]

/** ACP-798 · 本版（v5）修改过的文件, one row per file: the name, HOW v5 changed
 * it, and where it stands in the distillation into the requirement graph.
 * The three change kinds are all represented (新增 / 修改 / 删除) and the
 * deleted one is a file that stood at v4 and is gone at v5 — so the list is
 * 「本版动过的文件」, NOT 「项目现在有哪些文档」 (that is DOC_ROWS, and the two
 * stay consistent: none of the four current docs is marked deleted here).
 *
 * The distill state ADVANCES across the story because the distillation is
 * launched BY the release (ACP-733): before the v5 record lands every file is
 * 尚未拆解, R4's landed release shows the run in progress — one file already
 * distilled, one running, one still pending (all three states on ONE frame,
 * so no reader has to hop frames to see them) — and R5/R6 carry the run on to
 * completion. Every file is a LIST ROW, never a box-and-arrow diagram. */
const FILE_REQ = '产品需求设计文档.md'
const FILE_JOURNEY = '用户旅程设计.md'
const FILE_OLD_RULE = '旧版积分规则说明.md'

/** R1~R3: the version's changed files are known (the tag froze them), but the
 * release has not landed, so nothing has been distilled yet. */
const FILES_FRESH: StudioReleaseFiles = {
  version: 'v5',
  files: [
    { name: FILE_REQ, change: 'modified', distill: 'pending' },
    { name: FILE_JOURNEY, change: 'added', distill: 'pending' },
    { name: FILE_OLD_RULE, change: 'deleted', distill: 'pending' },
  ],
}

/** R4: the release landed and its distillation is IN PROGRESS — the frame the
 * 三态口径 reads on (已拆解 / 正在拆解 / 尚未拆解 side by side). */
const FILES_SETTLING: StudioReleaseFiles = {
  version: 'v5',
  files: [
    { name: FILE_REQ, change: 'modified', distill: 'done' },
    { name: FILE_JOURNEY, change: 'added', distill: 'running' },
    { name: FILE_OLD_RULE, change: 'deleted', distill: 'pending' },
  ],
}

/** R5: one file left running. */
const FILES_ALMOST: StudioReleaseFiles = {
  version: 'v5',
  files: [
    { name: FILE_REQ, change: 'modified', distill: 'done' },
    { name: FILE_JOURNEY, change: 'added', distill: 'done' },
    { name: FILE_OLD_RULE, change: 'deleted', distill: 'running' },
  ],
}

/** R6: every changed file is in the graph. */
const FILES_DISTILLED: StudioReleaseFiles = {
  version: 'v5',
  files: [
    { name: FILE_REQ, change: 'modified', distill: 'done' },
    { name: FILE_JOURNEY, change: 'added', distill: 'done' },
    { name: FILE_OLD_RULE, change: 'deleted', distill: 'done' },
  ],
}

/** ACP-798 · the 发版 tab's own 发版 button (owner 追加: 动作按钮跟着页签走).
 * The act is the same one a row's 发布 button fires — this only names WHICH
 * version it aims at, so the tab control and the row control are one code
 * path. The walk labels are i18n keys (解析图谱 → 生成文件清单 → 就绪), the
 * same three phases the top bar's release walks. */
const RELEASE_ACTION: NonNullable<ReleasePublishPayload['releaseAction']> = {
  version: 'v5',
  phaseKeys: [
    'apps.aiStudio.publish_phase_parse',
    'apps.aiStudio.publish_phase_filelist',
    'apps.aiStudio.publish_phase_ready',
  ],
}

/** R6's experience page: the feature list is the graph's requirement labels,
 * and the added line IS this iteration's rule (逐字对应图谱需求节点) */
const RUN_PREVIEW: StudioRunPreview = {
  version: 'v5',
  devRunId: 'run-v5',
  title: '会员积分系统 · v5',
  lines: [
    '消费 1 元累积 1 积分',
    '100 积分抵扣 1 元',
    NEW_RULE,
  ],
}

/** the fake's design world once the release phase starts: everything
 * committed (V5), no drafts → the shared commit bar reads disabled on every
 * R frame (dirty=false, commitEnabled=false are DATA, and the fixture agrees
 * with them exactly the way `states.ts`' dirty frames do). */
function releaseFixture(): DemoFixture {
  return {
    project: DEMO_PROJECT,
    focusDoc: FOCUS_DOC,
    buffer: BASELINE_V5,
    docs: [
      { name: FOCUS_DOC, content: BASELINE_V5 },
      { name: '用户旅程设计.md', content: '# 用户旅程设计\n' },
      { name: '业务模型设计.md', content: '# 业务模型设计\n' },
      { name: '页面交互设计.md', content: '# 页面交互设计\n' },
    ],
    draftVersions: [],
    versions: {},
    recentActivity: [],
  }
}

/** the fields every R frame shares except its own id/label/title/caption and
 * its payload; the design doc list + committed V5 + clean markers ride all
 * six (给定哪个渲染哪个 — a switch is a full re-read, never an accumulate). */
function releaseBase(id: string, label: string, title: string, caption: string): Omit<StateSnapshot, 'fixture' | 'publish'> & {
  versionHistory: StateSnapshot['versionHistory']
} {
  return {
    id,
    outlineRef: id, // 提纲阶段二表的行号 R1~R6 逐字
    phase: 'release',
    label,
    title,
    caption,
    docs: DOC_ROWS,
    // Owner 口径 (ACP-798): in the demo the CENTER column is only ever the doc
    // editor — the release story is read in the right sidebar's 发布 tab, so
    // the frame keeps the focus doc open in the middle rather than leaving it
    // empty. `activeSurface: 'release'` is what lights the tab.
    selectedDoc: FOCUS_DOC,
    activeSurface: 'release',
    buffer: BASELINE_V5,
    baseline: BASELINE_V5,
    committedVersion: 'V5',
    workingVersionLabel: '',
    dirty: false,
    diffBadge: false,
    commitEnabled: false,
    versionHistory: [{ version: 'V5', parity: 'odd', source: 'manual', time: 1735692000 }],
  }
}

// ---------------------------------------------------------------------------
// The six states, in the outline's 阶段二 order. R1~R4 are one PublishVersionList
// read each (the differences ARE data: the records list before/after the
// settle, and R3's one real click); R5 is the release-job page + its log
// replay; R6 is the experience screen behind the result bar's address.
// ACP-798: every frame ALSO carries 本版修改过的文件 (name + 新增/修改/删除 +
// 已/正在/尚未拆解成图谱), because owner's 口径 is that ONE release state reads
// both the version history and this version's changed files. The three distill
// states are all on R4 at once (FILES_SETTLING), so a presenter sees them
// without hopping; R5/R6 show the run finishing.
// ---------------------------------------------------------------------------

export const RELEASE_STATES: ReleaseStateSnapshot[] = [
  {
    ...releaseBase('R1', 'R1 · 发布页签', '发版页签 · 版本列表', '右侧「发布」页签打开：v5 / v4 / v3 逐行列出，各带短 hash 与发布状态'),
    fixture: releaseFixture(),
    publish: { versions: VERSIONS, records: RECORDS_BEFORE, previews: PREVIEWS, files: FILES_FRESH, releaseAction: RELEASE_ACTION },
  },
  {
    ...releaseBase('R2', 'R2 · 发版形态', '选中这一版 · 看发版形态', 'v5 行显示本版将以什么形态发布及判定原因（git tag 标注）；hash ≠ 最新成功发布 hash，发布按钮出现'),
    fixture: releaseFixture(),
    publish: { versions: VERSIONS, records: RECORDS_BEFORE, previews: PREVIEWS, focusVersion: 'v5', files: FILES_FRESH, releaseAction: RELEASE_ACTION },
  },
  {
    // 发布中 is the component's LOCAL run state (useState) — no initial data
    // paints it; this frame's one act is the real button's real click (see
    // the header's wiring note 2). The trigger fake stays pending, so the row
    // honestly rests at 发布中 with no result facts (badge/url are release
    // facts, they appear only when the record lands).
    ...releaseBase('R3', 'R3 · 发布中', '触发发版 · 发布中', '点 v5 行的「发布」：行状态变「发布中」，日志开始长（发布详情里看）'),
    fixture: releaseFixture(),
    publish: { versions: VERSIONS, records: RECORDS_BEFORE, previews: PREVIEWS, focusVersion: 'v5', inFlight: { version: 'v5', deploymentId: 'job-v5' }, files: FILES_FRESH, releaseAction: RELEASE_ACTION },
  },
  {
    // the settle: v5's success record IS the frame — PublishVersionList
    // re-derives 已发布 + 结果条（完整版徽章 / 访问地址 / 发布号链接）and the
    // hash rule retires v5's button while v4's comes back (D3 rollback case).
    ...releaseBase('R4', 'R4 · 发版成功', '发版成功 · 结果条', 'v5 行出现结果条：完整版徽章、访问地址（v5-points-14409.gb10.jereh-pe.cn）、发布号 job-v5（新页签打开发布详情）'),
    fixture: releaseFixture(),
    publish: { versions: VERSIONS, records: RECORDS_AFTER, previews: PREVIEWS, focusVersion: 'v5', files: FILES_SETTLING, releaseAction: RELEASE_ACTION },
  },
  {
    ...releaseBase('R5', 'R5 · 发布详情', '发布详情页 · 历史与流式日志', '发布详情页：该项目全部发布历史（job-v5 / v4 / v3 均已完成），本次 job-v5 的日志按帧回放、末帧 done 关流'),
    fixture: releaseFixture(),
    publish: {
      versions: VERSIONS, records: RECORDS_AFTER, previews: PREVIEWS, focusVersion: 'v5',
      jobs: JOBS, selectedJobId: 'job-v5', logFrames: LOG_FRAMES, files: FILES_ALMOST,
      releaseAction: RELEASE_ACTION,
    },
  },
  {
    // 取舍（ACP-791 评论 12739 第 4 条）: the serving url is a deployed app,
    // so the fetch-free frame lands on the real 体验页 instead — its lines
    // carry this iteration's new rule, which is exactly what 提纲 asks the
    // opened version to show. R4's address string remains the link a real
    // (non-demo) visit would open.
    ...releaseBase('R6', 'R6 · 线上可访问', '线上可访问 · 新规则已生效', '打开本次发布的版本：功能清单里能看到本次新增的规则「大额采购需追加一级审批」'),
    fixture: releaseFixture(),
    publish: { versions: VERSIONS, records: RECORDS_AFTER, previews: PREVIEWS, focusVersion: 'v5', runPreview: RUN_PREVIEW, files: FILES_DISTILLED, releaseAction: RELEASE_ACTION },
  },
]
