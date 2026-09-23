// 开发 + 部署 阶段的状态直出快照（ACP-792，提纲 阶段三 V1~V3 / 阶段四 P1~P2）。
//
// This is the dev-deploy slice of the `?demo=states` state-direct demo: five
// COMPLETE, immutable snapshots following the design/release frames already in
// `states.ts` (and the sibling D/R files). Each frame is pure data — the same
// 3rd-iteration story (会员积分系统, 新规则「大额采购需追加一级审批，审批人请假
// 时自动转交代理人」, committed as V5 at D6) seen one step later: the frozen v5
// design is developed (V1 advancing → V2 finished → V3 试运行 opened) and then
// deployed to replace the live instance (P1 发布中 → P2 已完成·线上可访问).
// Nothing here replays an operation chain; selecting a frame is reading it.
//
// WIRING CONTRACT FOR MASTER (接线由 master 统一做；this file only ships data):
//
// ACP-792 shipped this slice rendered in the CENTER column. ACP-799 moves that
// content into the sidebar's 开发 / 部署 tabs (owner's layout rule: 中间列只
// 显示文字内容，其余一切都在右边工具边栏对应页签里）:
//   - every frame carries `activeSidebarTab` ('dev' | 'deploy') — hand it to
//     `ToolSidebar` as `initialTool`, the way the commit slice already does.
//   - every frame carries `history` (the tab's 历史记录 rows) and
//     `actionDisabled` (its top action button's state).
//   - the tab's 过程区 and its top button are injected by the CALLER as nodes,
//     so `ToolSidebar` keeps knowing nothing about the demo:
//       dev={{ action: <ReleaseControl act="dev" disabled={f.actionDisabled} … />,
//              current: <DevRunPanel run={f.fixture.devRun} />, history: f.history }}
//       deploy={{ action: <ReleaseControl act="deploy" disabled={f.actionDisabled} … />,
//                 current: <DeployFramePanel frame={DEPLOY_PAYLOADS[f.id]} />, history: f.history }}
//   - THE TWO CENTER MOUNTS ACP-794 ADDED MUST GO with it (AiStudioPage): the
//     `activeSurface === 'dev'` DevRunPanel branch and the
//     `DEPLOY_PAYLOADS[id]` DeployFramePanel branch. Until they are removed the
//     old picture still renders — which is what keeps every other slice's tests
//     green in the meantime; removing them is what makes ③ (「这些帧的中间列
//     是打开的文档」) the only thing left on screen.
//   - `DevRunPanel` / `RunPreviewScreen` stay the SAME real components, now
//     rendered inside the 开发 tab; the V3 preview overlay
//     (`fixture.runPreview`) is unchanged. V1/V2 carry no runPreview; V3 carries
//     the finished devRun too, so the panel stays mounted under the preview the
//     way the workbench does.
//   - the deploy frames keep what ACP-792 built, restated for the tab: the
//     product's real deploy path
//     (DeployLog/ReleaseJobPage) streams over SSE and cannot run fetch-free, so
//     per the ticket these ship as SNAPSHOT FRAMES: the deploy branch renders a
//     pure, data-driven panel from `DEPLOY_PAYLOADS[state.id]` below, keeping
//     the outline's acceptance testids — the 部署记录 进行中/完成态 and the log
//     container `deploy-log-<deploymentId>` (role=log, aria-live=polite, the
//     same contract DeployLog holds). The log lines reproduce the REAL
//     executor's wording and order (kiro_crew publish.py/deploy.py:
//     开始发布 → 开始构建 → 执行构建命令 → 构建完成 → 停止旧实例 → 旧实例已替换 →
//     启动新实例 → 新实例已启动 → 发布地址 → 发布完成), and P2's lines extend
//     P1's as a prefix — that is how 「持续增长」 reads in a fetch-free demo.
//   - `DEPLOY_PAYLOADS` is keyed by the StateSnapshot id; a frame whose id is
//     in it must render its deploy frame from that payload, nothing else.
import type { StateDocRow, StateSnapshot } from './states'
import type { DemoFixture } from './types'
import type { StudioDevRun, StudioRunPreview } from '../studioApi'

// ---------------------------------------------------------------------------
// The sidebar-tab seam (ACP-799), shaped like the commit slice's C1/C2: a
// frame stays a plain snapshot and ADDS the fields its tab needs, so the
// renderer's wiring is a spread and nothing on the public side learns a demo
// exists. `activeSidebarTab` says which tab lights up; `history` is that tab's
// 历史记录 list; `actionDisabled` is the tab-top action button's state.
//
// The owner's layout rule these frames must produce (四个页签统一): 过程在上,
// 历史 records below —
//   上：当前进行中的清单与每一项的状态（开发 = 四阶段推进 + 产物 + 可运行版本，
//       部署 = 部署记录 + 部署日志）—— rendered by the REAL components;
//   下：历史记录列表（上一轮及更早的那几次）。
// ---------------------------------------------------------------------------

/** One 历史记录 row. Structurally the sidebar's own history shape
 * (`ReleaseRun` in fixtures.ts): id + display time + a status pill. */
export interface TabHistoryRow {
  id: string
  time: string
  status: string
}

/** A dev/deploy frame: a normal snapshot plus the sidebar tab its content
 * lives in, that tab's history rows, and its action button's state. */
export interface DevDeploySnapshot extends StateSnapshot {
  /** which sidebar tab this frame's content lives in — the renderer passes it
   * straight to `ToolSidebar`'s `initialTool`. */
  activeSidebarTab: 'dev' | 'deploy'
  /** 历史记录 rows, newest last (the previous iterations' runs). The CURRENT
   * one is not listed here — it is the 过程区 above, exactly as the shipped
   * ReleasesTool / DeployTool split it. */
  history: TabHistoryRow[]
  /** the tab-top action button ("开发" / "部署"): disabled because the act this
   * frame shows is already running or done — a frozen design is developed
   * once, a version is deployed once. A frame whose act has NOT landed yet
   * sets this false and the caller's onRelease lands it. */
  actionDisabled: boolean
}

/** Positive identity for a dev/deploy frame (same doctrine as
 * `isReleaseState`: never guess from the ABSENCE of the other slices). */
export function isDevDeployState(s: StateSnapshot): s is DevDeploySnapshot {
  return 'activeSidebarTab' in s
}

// ---------------------------------------------------------------------------
// The shared world: same project/doc identity as `states.ts` (会员积分系统,
// 产品需求设计文档.md), but AFTER this iteration's commit — the V4 → V5 draft
// of S2/S3 has landed (D6: odd V5 = manual), so every frame below is clean
// (no drafts → commit disabled) and the downstream docs carry this round's
// even regen versions (D8: even = graph 反生).
// ---------------------------------------------------------------------------

const DEMO_PROJECT = { id: 'demo-product', name: '会员积分系统', description: '状态驱动演示项目', createdAt: 1735689600 }

const FOCUS_DOC = '产品需求设计文档.md'

/** the committed V5 text: V4 baseline + the new rule, now part of the doc */
const COMMITTED_V5 = `# 产品需求设计文档

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

const DOC_ROWS: StateDocRow[] = [
  { docId: 'DOC-001', name: FOCUS_DOC, version: 'V5' },
  { docId: 'DOC-002', name: '用户旅程设计.md', version: 'V4' },
  { docId: 'DOC-003', name: '业务模型设计.md', version: 'V2' },
  { docId: 'DOC-004', name: '页面交互设计.md', version: 'V4' },
]

const FIXTURE_DOCS = [
  { name: FOCUS_DOC, content: COMMITTED_V5 },
  { name: '用户旅程设计.md', content: '# 用户旅程设计\n（V4 · 图谱反生：新增采购审批旅程节点与转交分支）\n' },
  { name: '业务模型设计.md', content: '# 业务模型设计\n（V2 · 图谱反生：审批单实体与代理关系）\n' },
  { name: '页面交互设计.md', content: '# 页面交互设计\n（V4 · 图谱反生：采购审批与转交提示的界面流）\n' },
]

/** the cut release the 发版 phase produced (R 段的前置事实，各帧共用) */
const RELEASED_V5 = { version: 'v5', notes: '本版：大额采购追加一级审批（请假自动转交代理人）', time: 1790140000 }

// ---------------------------------------------------------------------------
// The development run on the frozen v5 design (阶段三). One StudioDevRun per
// frame, exactly the shape `DevRunView.DevRunPanel` consumes; the frames differ
// ONLY in the phase statuses / products, so the four-phase walk IS a series of
// snapshot frames, never a timer (DevRunView's own comment: 回放一致).
// dev-v5 traces to `v5 · graph@distill-v4`: the odd V5 human commit distilled
// into the graph, whose distillation (even regen V4 rows) froze this design.
// ---------------------------------------------------------------------------

const DEV_ID = 'dev-v5'
const DEV_DESIGN_VERSION = 'v5 · graph@distill-v4'
const RUNNABLE_VERSION = '0.5.0'

const SUM_TASKS = '按 v5 冻结设计拆分 4 个开发任务：审批阈值判断、审批人请假转交、审批单服务、数据表变更'
const SUM_IMPLEMENT = '实现审批服务模块与数据表变更，大额采购阈值 APPROVAL_THRESHOLD=50000 落地'
const SUM_TEST = '21 项测试全部通过：审批阈值边界 6 项、请假转交代理 8 项、审批单流转 7 项'
const SUM_BUILD = `构建产物 points-service-${RUNNABLE_VERSION} 打包完成，可运行版本就绪`

/** V1: 开发启动·四阶段推进 — the frame caught mid-walk (one done, one running,
 * two pending), so every `dev-phase-*` row's `data-dev-phase-status` value is
 * on screen at once and the 完成摘要 shows only on finished phases. */
const DEV_RUN_V1: StudioDevRun = {
  id: DEV_ID,
  designVersion: DEV_DESIGN_VERSION,
  phases: [
    { name: 'tasks', status: 'done', summary: SUM_TASKS },
    { name: 'implement', status: 'running', summary: '' },
    { name: 'test', status: 'pending', summary: '' },
    { name: 'build', status: 'pending', summary: '' },
  ],
  artifacts: [],
}

/** V2/V3: 开发完成 — all four phases done, the three products present, and the
 * runnable version (with its 打开可运行版本 entry) appears only here, because
 * the product only exists once the build phase finished. */
function finishedDevRun(): StudioDevRun {
  return {
    id: DEV_ID,
    designVersion: DEV_DESIGN_VERSION,
    phases: [
      { name: 'tasks', status: 'done', summary: SUM_TASKS },
      { name: 'implement', status: 'done', summary: SUM_IMPLEMENT },
      { name: 'test', status: 'done', summary: SUM_TEST },
      { name: 'build', status: 'done', summary: SUM_BUILD },
    ],
    artifacts: [
      { kind: 'test', path: 'reports/test-v5.json' },
      { kind: 'build', path: `dist/points-service-${RUNNABLE_VERSION}.tar.gz` },
      { kind: 'runtime', path: 'runtime/points-service' },
    ],
    runnableVersion: RUNNABLE_VERSION,
  }
}

/** V3: 试运行 — what 「打开可运行版本」 shows. The feature list is the graph's
 * requirement labels verbatim: the five facts already live from the previous
 * two iterations plus THIS round's new rule split into its two nodes (审批 +
 * 转交) — the running version claims only what the structured design promises. */
const RUN_PREVIEW: StudioRunPreview = {
  version: RUNNABLE_VERSION,
  devRunId: DEV_ID,
  title: '会员积分系统 · 0.5.0',
  lines: [
    '每日签到返积分',
    '消费返积分',
    '积分兑换优惠券（7 天有效）',
    '优惠券 7 天有效期',
    '积分不可抵现',
    '大额采购需追加一级审批',
    '审批人请假时自动转交代理人',
  ],
}

// ---------------------------------------------------------------------------
// The deployment frames (阶段四). The StateSnapshot type carries no deploy
// slot (types.ts is read-only for this ticket), so the deploy payload rides
// THIS file as `DEPLOY_PAYLOADS`, keyed by the frame id — see the wiring
// contract at the top. The log lines reuse the real executor's wording and
// order, and the URL follows the store's template
// `{version}-{app}-{工号}.gb10.jereh-pe.cn` (publish.py URL_TEMPLATE).
// ---------------------------------------------------------------------------

export interface DeployFramePayload {
  /** the 发布号 — doubles as the `deploy-log-<deploymentId>` testid key */
  deploymentId: string
  /** the release cut that is being deployed */
  version: string
  commitHash: string
  /** P1 ships 'running' (进行中); P2 ships 'success' (完成态) */
  status: 'running' | 'success'
  env: string
  /** the live URL, only set once the job succeeded (P1 carries '') */
  url: string
  /** the log tail as of this frame; P2's lines extend P1's as a prefix */
  logLines: string[]
  /** 单实例替换: the instance this deployment replaced */
  replaced: { deploymentId: string; version: string } | null
  /** P2 only: the live feature list the opened URL shows — it equals V3's
   * preview lines, i.e. 线上可访问 sees 本次新增规则 */
  onlineFeatureLines?: string[]
  startedAt: number
  finishedAt?: number
}

const DEPLOY_ID = '20260923-071530-120-4f9a2c71'
const DEPLOY_URL = `v5-points-service-14409.gb10.jereh-pe.cn`
const DEPLOY_COMMIT = 'a31f9c7e2b58'
const DEPLOY_STARTED = 1790147730
const DEPLOY_FINISHED = 1790147790

/** P1's log: up to 停止旧实例 — the replacement is underway, no 发布完成 yet */
const LOG_P1 = [
  `开始发布 v5（${DEPLOY_COMMIT}）`,
  '开始构建 v5',
  '执行构建命令：npm run build',
  `构建命令输出：dist/ 生成完毕（points-service-${RUNNABLE_VERSION}.tar.gz）`,
  `构建完成：build/${DEPLOY_ID}/dist`,
  '停止旧实例 v4（pid 41277）',
]

/** P2's log: P1 + 旧实例已替换 → 启动新实例 → 新实例已启动 → 发布地址 → 发布完成
 * (the real publish/deploy executor's exact line order) */
const LOG_P2 = [
  ...LOG_P1,
  '旧实例已替换',
  '启动新实例 v5：python3 runtime/points-service --port 8760（端口 8760）',
  '新实例已启动：pid 41532，端口 8760',
  `发布地址 ${DEPLOY_URL}（pid 41532）`,
  '发布完成',
]

export const DEPLOY_PAYLOADS: Record<string, DeployFramePayload> = {
  P1: {
    deploymentId: DEPLOY_ID,
    version: 'v5',
    commitHash: DEPLOY_COMMIT,
    status: 'running',
    env: '生产环境',
    url: '',
    logLines: LOG_P1,
    replaced: { deploymentId: '20260920-103411-077-8b21c0de', version: 'v4' },
    startedAt: DEPLOY_STARTED,
  },
  P2: {
    deploymentId: DEPLOY_ID,
    version: 'v5',
    commitHash: DEPLOY_COMMIT,
    status: 'success',
    env: '生产环境',
    url: DEPLOY_URL,
    logLines: LOG_P2,
    replaced: { deploymentId: '20260920-103411-077-8b21c0de', version: 'v4' },
    onlineFeatureLines: [...RUN_PREVIEW.lines],
    startedAt: DEPLOY_STARTED,
    finishedAt: DEPLOY_FINISHED,
  },
}

// ---------------------------------------------------------------------------
// 历史记录 for the two tabs (ACP-799). Same rule as the 过程区: the list holds
// the PREVIOUS iterations only — this round's run / deployment is the 过程 above
// it. The deployment ids are the ones this story already names: v4's deployment
// IS `replaced.deploymentId` in both payloads (so 历史 and 单实例替换 agree on
// one number instead of two inventions), and v3's is the one before it.
// ---------------------------------------------------------------------------

const DEV_RUN_HISTORY: TabHistoryRow[] = [
  { id: 'dev-v4', time: '2026-09-20 09:20', status: '已完成' },
  { id: 'dev-v3', time: '2026-09-16 08:55', status: '已完成' },
]

const DEPLOY_HISTORY: TabHistoryRow[] = [
  { id: '20260920-103411-077-8b21c0de', time: '2026-09-20 10:34', status: '已替换' },
  { id: '20260916-094502-031-7d10e4bb', time: '2026-09-16 09:45', status: '已替换' },
]

// ---------------------------------------------------------------------------
// The five snapshots, in the forward order (V1 → V2 → V3 → P1 → P2). Like S1's
// clean frame, none of these carries drafts: this iteration's edit was already
// committed upstream (D6), so the commit button stays disabled and the whole
// story from here on is read-only progress.
// ---------------------------------------------------------------------------

/** the clean, committed-V5 world all five frames share; `extra` seeds the per-
 * frame 最近活动 rows the surface's own facts derive from (devRun lines on V
 * frames, the release job on P frames) */
function fixture(extra?: { label: string; time: number }[]): DemoFixture {
  return {
    project: DEMO_PROJECT,
    focusDoc: FOCUS_DOC,
    buffer: COMMITTED_V5,
    docs: FIXTURE_DOCS.map((d) => ({ ...d })),
    draftVersions: [],
    versions: {},
    release: RELEASED_V5,
    recentActivity: extra ?? [],
  }
}

const COMMIT_ACTIVITY = { time: 1790140000, label: '提交 产品需求设计文档.md（V5）' }
const DEV_OPEN_ACTIVITY = { time: 1790143200, label: `开启开发任务 ${DEV_ID}（设计 ${DEV_DESIGN_VERSION}）` }
const DEV_DONE_ACTIVITY = { time: 1790146200, label: `开发完成，可运行版本 ${RUNNABLE_VERSION} 就绪` }
const RUN_OPEN_ACTIVITY = { time: 1790146500, label: `打开可运行版本 ${RUNNABLE_VERSION}（试运行）` }
const DEPLOY_OPEN_ACTIVITY = { time: DEPLOY_STARTED, label: `开始发布 v5（${DEPLOY_ID}）` }
const DEPLOY_DONE_ACTIVITY = { time: DEPLOY_FINISHED, label: `发布完成：${DEPLOY_URL}` }

/** One dev/deploy frame. `tab` names both the big phase and the sidebar tab the
 * content lives in — 开发 and 部署 are the same word on purpose, so they come
 * from one argument instead of being typed twice.
 *
 * The CENTER still declares `activeSurface: tab`: ACP-794 mounts `DevRunPanel` /
 * `DeployFramePanel` there today, and dropping the value here would delete the
 * panels from the running demo before the sidebar is wired (ACP-796). Every
 * frame carries `selectedDoc` either way, so the center does render the open
 * document — the header's contract is what finishes the move. */
function frame(
  id: string,
  label: string,
  title: string,
  caption: string,
  tab: 'dev' | 'deploy',
  history: TabHistoryRow[],
  fixtureValue: DemoFixture,
): DevDeploySnapshot {
  return {
    id,
    outlineRef: id,
    phase: tab,
    label,
    title,
    caption,
    docs: DOC_ROWS,
    selectedDoc: FOCUS_DOC,
    activeSurface: tab,
    buffer: COMMITTED_V5,
    baseline: COMMITTED_V5,
    committedVersion: 'V5',
    workingVersionLabel: '',
    dirty: false,
    diffBadge: false,
    commitEnabled: false,
    fixture: fixtureValue,
    activeSidebarTab: tab,
    history,
    actionDisabled: true,
  }
}

export const DEV_DEPLOY_STATES: DevDeploySnapshot[] = [
  frame(
    'V1',
    'V1 · 开发推进',
    '开发启动 · 四阶段推进',
    `开发任务 ${DEV_ID} 基于冻结设计 ${DEV_DESIGN_VERSION} 推进：任务生成已完成、实现进行中、测试与构建待启动`,
    'dev',
    DEV_RUN_HISTORY,
    { ...fixture([COMMIT_ACTIVITY, DEV_OPEN_ACTIVITY]), devRun: DEV_RUN_V1 },
  ),
  frame(
    'V2',
    'V2 · 开发完成',
    '开发完成 · 产物与可运行版本',
    `四阶段全部完成，产出测试报告 / 构建产物 / 运行时入口三件套，可运行版本 ${RUNNABLE_VERSION} 就绪（打开可运行版本可用）`,
    'dev',
    DEV_RUN_HISTORY,
    { ...fixture([COMMIT_ACTIVITY, DEV_OPEN_ACTIVITY, DEV_DONE_ACTIVITY]), devRun: finishedDevRun() },
  ),
  frame(
    'V3',
    'V3 · 试运行',
    '试运行 · 打开可运行版本',
    `体验页列出这一版的功能清单（逐字对应图谱需求节点），含本次新增规则：大额采购需追加一级审批、审批人请假时自动转交代理人`,
    'dev',
    DEV_RUN_HISTORY,
    {
      ...fixture([COMMIT_ACTIVITY, DEV_OPEN_ACTIVITY, DEV_DONE_ACTIVITY, RUN_OPEN_ACTIVITY]),
      devRun: finishedDevRun(),
      runPreview: RUN_PREVIEW,
    },
  ),
  frame(
    'P1',
    'P1 · 部署中',
    '部署进行中 · 发布单执行',
    `部署记录 ${DEPLOY_ID} 进行中（生产环境），日志边发边长到「停止旧实例」——单实例替换已开始`,
    'deploy',
    DEPLOY_HISTORY,
    fixture([COMMIT_ACTIVITY, DEV_OPEN_ACTIVITY, DEV_DONE_ACTIVITY, DEPLOY_OPEN_ACTIVITY]),
  ),
  frame(
    'P2',
    'P2 · 部署完成',
    '部署完成 · 线上可访问',
    `部署记录完成（发布地址 ${DEPLOY_URL} 可打开，功能清单含本次新增规则）；旧实例 v4 已停、新实例 v5 在跑（单实例替换）`,
    'deploy',
    DEPLOY_HISTORY,
    fixture([COMMIT_ACTIVITY, DEV_OPEN_ACTIVITY, DEV_DONE_ACTIVITY, DEPLOY_OPEN_ACTIVITY, DEPLOY_DONE_ACTIVITY]),
  ),
]
