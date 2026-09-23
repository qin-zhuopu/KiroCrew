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
//   - `activeSurface: 'dev'` frames (V1~V3): render the REAL business
//     components off `state.fixture` — `DevRunPanel` from
//     `state.fixture.devRun` (its own module: DevRunView.tsx), and for V3
//     additionally `RunPreviewScreen` from `state.fixture.runPreview` (the
//     体验 overlay 「打开可运行版本」 opens). Both are pure-props, zero-fetch.
//     V1/V2 carry no runPreview; V3 carries the finished devRun too, so the
//     panel stays mounted under the preview the way the workbench does.
//   - `activeSurface: 'deploy'` frames (P1~P2): the product's real deploy path
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

function frame(
  id: string,
  label: string,
  title: string,
  caption: string,
  phase: StateSnapshot['phase'],
  activeSurface: StateSnapshot['activeSurface'],
  fixtureValue: DemoFixture,
): StateSnapshot {
  return {
    id,
    outlineRef: id,
    phase,
    label,
    title,
    caption,
    docs: DOC_ROWS,
    selectedDoc: FOCUS_DOC,
    activeSurface,
    buffer: COMMITTED_V5,
    baseline: COMMITTED_V5,
    committedVersion: 'V5',
    workingVersionLabel: '',
    dirty: false,
    diffBadge: false,
    commitEnabled: false,
    fixture: fixtureValue,
  }
}

export const DEV_DEPLOY_STATES: StateSnapshot[] = [
  frame(
    'V1',
    'V1 · 开发推进',
    '开发启动 · 四阶段推进',
    `开发任务 ${DEV_ID} 基于冻结设计 ${DEV_DESIGN_VERSION} 推进：任务生成已完成、实现进行中、测试与构建待启动`,
    'dev',
    'dev',
    { ...fixture([COMMIT_ACTIVITY, DEV_OPEN_ACTIVITY]), devRun: DEV_RUN_V1 },
  ),
  frame(
    'V2',
    'V2 · 开发完成',
    '开发完成 · 产物与可运行版本',
    `四阶段全部完成，产出测试报告 / 构建产物 / 运行时入口三件套，可运行版本 ${RUNNABLE_VERSION} 就绪（打开可运行版本可用）`,
    'dev',
    'dev',
    { ...fixture([COMMIT_ACTIVITY, DEV_OPEN_ACTIVITY, DEV_DONE_ACTIVITY]), devRun: finishedDevRun() },
  ),
  frame(
    'V3',
    'V3 · 试运行',
    '试运行 · 打开可运行版本',
    `体验页列出这一版的功能清单（逐字对应图谱需求节点），含本次新增规则：大额采购需追加一级审批、审批人请假时自动转交代理人`,
    'dev',
    'dev',
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
    'deploy',
    fixture([COMMIT_ACTIVITY, DEV_OPEN_ACTIVITY, DEV_DONE_ACTIVITY, DEPLOY_OPEN_ACTIVITY]),
  ),
  frame(
    'P2',
    'P2 · 部署完成',
    '部署完成 · 线上可访问',
    `部署记录完成（发布地址 ${DEPLOY_URL} 可打开，功能清单含本次新增规则）；旧实例 v4 已停、新实例 v5 在跑（单实例替换）`,
    'deploy',
    'deploy',
    fixture([COMMIT_ACTIVITY, DEV_OPEN_ACTIVITY, DEV_DONE_ACTIVITY, DEPLOY_OPEN_ACTIVITY, DEPLOY_DONE_ACTIVITY]),
  ),
]
