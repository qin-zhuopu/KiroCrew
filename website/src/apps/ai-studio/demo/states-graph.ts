// Graph-tab states G1/G2 of the state-direct demo (ACP-797, parent ACP-789):
// the 需求图谱 as the 提交 stage's PRODUCT — watched being generated, and then
// read as a LIST.
//
// WHY THESE FRAMES: the owner's 大阶段 → 产物 chain says 提交 → 需求图谱, i.e.
// once the iteration's commit lands, the agent goes and builds the graph from
// what was committed. The demo could show the result but never the generation;
// these two frames are that missing beat —
//   G1 提交后 · agent 正在生成需求图谱   (the run is 进行中, the entries that
//                                        have landed so far are already listed)
//   G2 图谱生成完成                      (the run is done, the whole graph reads
//                                        as a grouped list)
//
// WHERE IT IS OBSERVED (owner 口径, and the rule this file is built around):
// **the generation process and the graph itself are observed ONLY in the tool
// sidebar's 「需求图谱」 tab, as a LIST — never a box-and-arrow canvas in the
// middle column.** The middle column stays the doc editor on both frames
// (`activeSurface: 'doc'`), and nothing here draws an SVG, an edge or a node
// box. The tab's own seam is `ToolSidebar`'s `graphEntries` / `distillation`
// props (additive, default-unchanged — 不传就是今天的两级下钻), so the frame →
// tab wiring is
//   <ToolSidebar initialTool="graph" graphEntries={f.graphEntries} distillation={f.distillation} … />
// plus one line in the renderer's positive identity: a frame IS a graph frame
// by CARRYING `graphEntries`. (It deliberately does NOT reuse
// `activeSidebarTab`: that field is the commits frames' positive identity and
// the renderer tests it by NAME — `'activeSidebarTab' in s` — so a second value
// landing on it would light the 提交 tab on D7, which is a merged frame.)
//
// ONE WAVE, TWO MOMENTS, and the honesty rules `states-graph.test.tsx`
// re-derives rather than trusts:
//   - G1's graph/delta/entries are the FULL wave FILTERED by what had landed
//     (`waveOf` / `deltaOf` below) — the partial picture is derived from the
//     complete one, so 「逐条出现」 cannot disagree with what G2 ends up showing.
//   - Every row's 新增 / 修改 / 移除 mark is DERIVED from the delta, never
//     typed per row; every entry that names a doc is a node really carrying it.
//   - The marks, the candidate list and the graph are one story: a done run's
//     candidates address exactly the delta (D8's rule, re-checked here).
//   - G1/G2 stand on C2's world — the same commit, the same four versions, the
//     same clean editor (asserted, not assumed).
import type {
  StudioDistillCandidate,
  StudioDistillation,
  StudioGraph,
  StudioGraphNode,
} from '../studioApi'
import type { GraphEntryGroup, GraphEntryRow } from '../ToolSidebar'
import { COMMIT_STATES } from './states-commit'
import type { StateSnapshot } from './states'

const FOCUS_DOC = '产品需求设计文档.md'
const MODEL_DOC = '业务模型设计.md'

/** A graph-tab frame: a normal snapshot plus the two things the 「需求图谱」
 * tab renders — the list, and the run that produced it. `graphEntries` is the
 * positive identity of a graph frame (see the header). */
export interface GraphStateSnapshot extends StateSnapshot {
  /** the tab's list: entries grouped by type, one row per entry, each marked
   * with what THIS change did to it. Derived from the frame's own graph wave. */
  graphEntries: GraphEntryGroup[]
  /** the generation run the tab shows above the list. Its status IS the
   * frame's beat: 'running' = 正在生成 (G1), 'done' = 生成完成 (G2). */
  distillation?: StudioDistillation
}

// ---------------------------------------------------------------------------
// the wave: what THIS commit (第三轮迭代's closing commit) moves in the graph.
// ids are ASCII like the shipped fixtures; labels are the Chinese facts the
// entries carry. This module owns the wave — `states-design.ts`'s D7/D8 read
// it from here, so the design slice's 图谱修订 and the 提交 slice's 生成过程
// can never describe two different graphs.
// ---------------------------------------------------------------------------

const BASE_NODES: StudioGraphNode[] = [
  { id: 'req-points-earn', kind: 'requirement', label: '消费积分', doc: FOCUS_DOC },
  { id: 'req-points-redeem', kind: 'requirement', label: '积分兑换', doc: FOCUS_DOC },
  { id: 'doc-requirements', kind: 'doc', label: FOCUS_DOC },
  { id: 'mod-points-center', kind: 'module', label: '积分中心模块' },
]
const ADDED_NODES: StudioGraphNode[] = [
  { id: 'req-purchase-approval', kind: 'requirement', label: '大额采购一级审批', doc: FOCUS_DOC },
  { id: 'mod-approval-service', kind: 'module', label: '审批服务模块' },
]

const BASE_EDGES = [
  { from: 'req-points-earn', to: 'doc-requirements', kind: 'trace' as const },
  { from: 'req-points-redeem', to: 'doc-requirements', kind: 'trace' as const },
  { from: 'req-points-earn', to: 'mod-points-center', kind: 'depends' as const },
  { from: 'req-points-redeem', to: 'mod-points-center', kind: 'depends' as const },
]
/** edges this wave adds, spelled "from->to" exactly as the delta reads them */
const ADDED_EDGES = [
  'req-purchase-approval->doc-requirements',
  'req-purchase-approval->mod-approval-service',
  'req-points-earn->mod-approval-service',
]

/** the graph after the wave is fully absorbed: the new requirement and its
 * module, plus the three edges that connect them. `mod-manual-adjust` is by
 * contract NOT here — the wave pruned it. */
export const GRAPH_WAVE: StudioGraph = {
  nodes: [BASE_NODES[0], ADDED_NODES[0], BASE_NODES[1], BASE_NODES[2], BASE_NODES[3], ADDED_NODES[1]],
  edges: [
    ...BASE_EDGES,
    ...ADDED_EDGES.map((e) => {
      const [from, to] = e.split('->')
      return { from, to, kind: to === 'doc-requirements' ? ('trace' as const) : ('depends' as const) }
    }),
  ],
}

/** what the wave changed: two nodes added, three edges added, one node
 * refined, one pruned */
export const GRAPH_DELTA = {
  nodes: ADDED_NODES.map((n) => n.id),
  edges: ADDED_EDGES,
  modified: ['req-points-earn'],
  removed: ['mod-manual-adjust'],
}

// ---------------------------------------------------------------------------
// the entries list: the graph read as text.
// ---------------------------------------------------------------------------

/** the type groups the list is laid out in — frame DATA, like the shipped
 * GRAPH_NODES' 页面 / 实体 keys: the graph's vocabulary belongs to the world
 * the frame describes, not to the sidebar's copy */
const KIND_GROUPS = [
  { kind: 'requirement', label: '需求' },
  { kind: 'doc', label: '文档' },
  { kind: 'module', label: '模块' },
] as const

const REMOVED_GROUP = '本次移除'

/** a pruned node is absent from the graph by contract, so its display name
 * cannot come from it — this is the one label the delta cannot carry, and it
 * is stated here rather than left as a bare id */
const REMOVED_LABELS: Record<string, string> = { 'mod-manual-adjust': '人工调分模块' }

/** The graph as the 「需求图谱」 tab's list: one group per node kind, one row
 * per node, and every row's mark DERIVED from the frame's own delta. The
 * pruned ids close the list in their own group, struck through — a removal is
 * part of what this change did, so it is shown, not omitted. */
export function graphEntryGroups(
  graph: StudioGraph,
  delta: { nodes: string[]; modified?: string[]; removed?: string[] },
  removedLabels: Record<string, string> = REMOVED_LABELS,
): GraphEntryGroup[] {
  const added = new Set(delta.nodes)
  const modified = new Set(delta.modified ?? [])
  const groups: GraphEntryGroup[] = KIND_GROUPS.map(({ kind, label }) => ({
    label,
    rows: graph.nodes.filter((n) => n.kind === kind).map((n): GraphEntryRow => ({
      id: n.id,
      label: n.label,
      // a node is added OR modified OR untouched — never two of them
      mark: added.has(n.id) ? 'added' : modified.has(n.id) ? 'modified' : undefined,
      // a doc node IS a document; a requirement names the one that produced it
      doc: n.doc ?? (n.kind === 'doc' ? n.label : undefined),
    })),
  }))
  const removed = (delta.removed ?? []).map((id): GraphEntryRow => ({
    id,
    label: removedLabels[id] ?? id,
    mark: 'removed',
    // the only handle a pruned node has left: its id in the delta
    meta: id,
  }))
  if (removed.length > 0) groups.push({ label: REMOVED_GROUP, rows: removed })
  return groups
}

/** The wave as it stood PART-WAY through the generation, derived from the
 * complete one by the changes that had LANDED — not by "which nodes exist":
 * a node the wave merely MODIFIED exists either way, so keying the cut on node
 * presence would report the refinement as already applied and hand G1 a
 * picture its own candidate list does not support. The cut is therefore taken
 * on the run's own atoms (its candidate ids), and the graph, the delta and the
 * candidate list of that instant all fall out of the same set. */
function waveThrough(landedIds: Set<string>): {
  graph: StudioGraph
  delta: typeof GRAPH_DELTA
  candidates: StudioDistillCandidate[]
} {
  const candidates = DISTILL_CANDIDATES.filter((c) => landedIds.has(c.id))
  const targets = new Set(candidates.map((c) => c.target))
  // the graph still holds everything the wave did not touch; the wave's own
  // additions appear only once their candidate has landed
  const nodes = GRAPH_WAVE.nodes.filter(
    (n) => !ADDED_NODES.some((a) => a.id === n.id) || targets.has(n.id),
  )
  const present = new Set(nodes.map((n) => n.id))
  const edges = GRAPH_WAVE.edges.filter((e) => present.has(e.from) && present.has(e.to))
  return {
    graph: { nodes, edges },
    delta: {
      nodes: GRAPH_DELTA.nodes.filter((id) => targets.has(id)),
      // an edge only exists once BOTH of its ends do
      edges: GRAPH_DELTA.edges.filter((e) => e.split('->').every((id) => present.has(id))),
      modified: (GRAPH_DELTA.modified ?? []).filter((id) => targets.has(id)),
      removed: (GRAPH_DELTA.removed ?? []).filter((id) => targets.has(id)),
    },
    candidates,
  }
}

// ---------------------------------------------------------------------------
// the run: one distillation, watched at two instants (G1 running → G2 done).
// The candidates are the changes it proposes, and a done run's list addresses
// exactly the delta above (the test re-checks both directions).
// ---------------------------------------------------------------------------

export const DISTILL_CANDIDATES: StudioDistillCandidate[] = [
  {
    id: 'dc-add-approval-req', kind: 'add', target: 'req-purchase-approval',
    summary: '新增需求「大额采购一级审批」：审批人请假自动转交代理人',
    evidenceDoc: `${FOCUS_DOC} § 5. 用户补充`,
  },
  {
    id: 'dc-add-approval-service', kind: 'add', target: 'mod-approval-service',
    summary: '新增模块「审批服务」：审批流转与代理转交都归它',
    evidenceDoc: `${FOCUS_DOC} § 5. 用户补充`,
  },
  {
    id: 'dc-modify-points-earn', kind: 'modify', target: 'req-points-earn',
    summary: '细化「消费积分」：大额消费的积分发放以审批通过为前置',
    evidenceDoc: `${FOCUS_DOC} § 5. 用户补充`,
  },
  {
    id: 'dc-remove-manual-adjust', kind: 'remove', target: 'mod-manual-adjust',
    summary: '「人工调分模块」被审批流取代，从图谱移除',
    evidenceDoc: `${MODEL_DOC} § 实体`,
  },
]

/** the finished run — the same one D8 applied (one run, two frames: G2 shows
 * the graph it produced, D8 the documents it regenerated) */
export const DISTILLATION: StudioDistillation = {
  id: 'distill-r3',
  releaseVersion: 'v5',
  status: 'done',
  candidates: DISTILL_CANDIDATES,
  appliedAt: 1735695000,
}

/** G1's instant: two of the four changes have landed (the new requirement and
 * the refinement of 消费积分), the module they brought with them has not, and
 * the run is still going. Its `candidates` is what it has extracted SO FAR —
 * the running panel prints the hint instead of the list, so that array is the
 * run's own progress, and the entries below it are its result so far. */
const LANDED_BY_G1 = waveThrough(new Set(['dc-add-approval-req', 'dc-modify-points-earn']))
const DISTILLATION_RUNNING: StudioDistillation = {
  id: DISTILLATION.id,
  releaseVersion: DISTILLATION.releaseVersion,
  status: 'running',
  candidates: LANDED_BY_G1.candidates,
}

// ---------------------------------------------------------------------------
// the world: G1/G2 continue C2 — the iteration's commit has just landed, so
// they stand on the SAME docs, trails and clean editor. Derived from that
// frame rather than re-typed, so 「提交之后」 is a fact of the data.
// ---------------------------------------------------------------------------

const C2 = COMMIT_STATES.find((s) => s.id === 'C2')
if (!C2) throw new Error('states-graph: C2 (the commit this pair follows) is missing from COMMIT_STATES')

// ---------------------------------------------------------------------------
// the two frames. `outlineRef` is 'G1'/'G2' on purpose, like C1/C2: the outline
// has no G step (that gap IS this task) and a frame must not impersonate one.
// ---------------------------------------------------------------------------

export const GRAPH_STATES: GraphStateSnapshot[] = [
  {
    id: 'G1',
    outlineRef: 'G1',
    // ACP-796's DemoPhase gains 'commit' (the dock's fifth group) one branch
    // over; until that lands here, the pair carries the same phase the frames
    // it continues do, and the dock's owner stamps the group they sit in.
    phase: 'design',
    label: 'G1 · 正在生成图谱',
    title: '提交后 · agent 正在生成需求图谱',
    caption: '工具边栏「需求图谱」页签亮着：生成过程就在页签里（真实生成面板的进行中态），已经抽取到的条目先逐条列出来',
    docs: C2.docs,
    selectedDoc: C2.selectedDoc,
    // 中间列仍是文档编辑器（owner 口径）：图谱只在边栏页签里看
    activeSurface: 'doc',
    buffer: C2.buffer,
    baseline: C2.baseline,
    committedVersion: C2.committedVersion,
    workingVersionLabel: C2.workingVersionLabel,
    dirty: C2.dirty,
    diffBadge: C2.diffBadge,
    commitEnabled: C2.commitEnabled,
    versionHistory: C2.versionHistory,
    graphNote: `生成中：已抽取 ${LANDED_BY_G1.candidates.length}/${DISTILL_CANDIDATES.length} 条改动`,
    graphEntries: graphEntryGroups(LANDED_BY_G1.graph, LANDED_BY_G1.delta),
    distillation: DISTILLATION_RUNNING,
    fixture: {
      ...C2.fixture,
      graph: LANDED_BY_G1.graph,
      graphDelta: LANDED_BY_G1.delta,
      distillation: DISTILLATION_RUNNING,
      recentActivity: [
        { time: 1735695600, label: `图谱生成中：已抽取 ${LANDED_BY_G1.candidates.length}/${DISTILL_CANDIDATES.length} 条改动` },
        ...C2.fixture.recentActivity,
      ],
    },
  },
  {
    id: 'G2',
    outlineRef: 'G2',
    phase: 'design',
    label: 'G2 · 图谱生成完成',
    title: '图谱生成完成',
    caption: '同一个页签，生成已完成：需求图谱按类型列成条目，每条读得出本次新增 / 修改，被移除的条目划掉',
    docs: C2.docs,
    selectedDoc: C2.selectedDoc,
    activeSurface: 'doc',
    buffer: C2.buffer,
    baseline: C2.baseline,
    committedVersion: C2.committedVersion,
    workingVersionLabel: C2.workingVersionLabel,
    dirty: C2.dirty,
    diffBadge: C2.diffBadge,
    commitEnabled: C2.commitEnabled,
    versionHistory: C2.versionHistory,
    graphNote: `本次提交喂图谱：新增 ${GRAPH_DELTA.nodes.length} 节点 / 新增 ${GRAPH_DELTA.edges.length} 边 / 修改 ${GRAPH_DELTA.modified.length} / 移除 ${GRAPH_DELTA.removed.length}`,
    graphEntries: graphEntryGroups(GRAPH_WAVE, GRAPH_DELTA),
    distillation: DISTILLATION,
    fixture: {
      ...C2.fixture,
      graph: GRAPH_WAVE,
      graphDelta: GRAPH_DELTA,
      distillation: DISTILLATION,
      recentActivity: [
        { time: 1735696400, label: '图谱生成完成：+2 节点 / 改 1 / 删 1' },
        ...C2.fixture.recentActivity,
      ],
    },
  },
]