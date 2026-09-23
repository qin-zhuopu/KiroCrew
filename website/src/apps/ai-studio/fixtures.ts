// AI Studio mock fixtures — the demo workspace state (sales-opportunity
// project) as typed constants. Everything the shell renders on first load
// comes from here; nothing hits the network. When the real project APIs land,
// each consumer swaps its fixture read for a React Query call and this file
// retires. The left chat column is deliberately NOT mocked — it embeds the
// native session (ChatEmbed).

export interface StudioDoc {
  id: string
  name: string
  version: string
  content: string
}

export interface ChangedFile {
  file: string
  added: string
  removed: string
}

export interface CommitEntry {
  id: string
  message: string
  time: string
  files: string[]
}

export interface ReleaseRun {
  id: string
  time: string
  status: string
}

export type TaskState = 'done' | 'now' | 'todo'

export interface ProgressModel {
  total: number
  done: number
  current: string
  tasks: Array<[string, TaskState]>
}

/** One instance an edge lands on (ACP-802): enough to read the relation as a
 * row — the instance's own id, its display name, and the type it belongs to. */
export interface GraphEdgeTarget {
  id: string
  name: string
  type: string
}

/** One edge of a node, READ AS ITS TARGETS (ACP-802): the same relation
 * `edges` spells as a sentence, carried as the instances it connects.
 * `label` is that sentence, so the two can never describe different edges. */
export interface GraphEdgeLink {
  label: string
  targets: GraphEdgeTarget[]
}

export interface GraphNode {
  id: string
  name: string
  props: Record<string, string>
  edges: string[]
  /** OPTIONAL: the instances each edge lands on. A node without it renders
   * exactly as it always has — one plain-text card per edge. */
  edgeLinks?: GraphEdgeLink[]
}

export interface DeployEntry {
  id: string
  env: string
  version: string
  status: string
  time: string
}

export const DOCS: StudioDoc[] = [
  {
    id: 'requirements',
    name: 'requirements.md',
    version: 'v1.4',
    content:
      '# 需求说明\n\n## 商机阶段\n\n当前阶段：线索确认 → 需求分析 → 方案确认 → 技术澄清 → 商务谈判 → 合同签署。',
  },
  {
    id: 'workflow',
    name: 'workflow.md',
    version: 'v1.3',
    content: '# 流程设计\n\n## 阶段流转\n\n方案确认完成后进入技术澄清；技术澄清通过后进入商务谈判。',
  },
  {
    id: 'ui',
    name: 'ui-spec.md',
    version: 'v2.1',
    content: '# UI 设计\n\n商机详情页顶部展示当前阶段，并提供阶段推进操作。',
  },
]

export const CHANGED: ChangedFile[] = [
  { file: 'requirements.md', added: '+ 技术澄清', removed: '- 方案确认 → 商务谈判' },
  { file: 'workflow.md', added: '+ 方案确认 → 技术澄清 → 商务谈判', removed: '- 方案确认 → 商务谈判' },
]

export const COMMITS: CommitEntry[] = [
  { id: 'c1051', message: '新增技术澄清阶段', time: '2026-09-22 10:15', files: ['requirements.md', 'workflow.md'] },
  { id: 'c1046', message: '优化商机详情页操作', time: '2026-09-21 17:40', files: ['ui-spec.md'] },
  { id: 'c1038', message: '初始化商机阶段模型', time: '2026-09-20 09:30', files: ['requirements.md', 'workflow.md'] },
]

export const RELEASE: ProgressModel = {
  total: 6,
  done: 4,
  current: '生成正式设计文档',
  tasks: [
    ['冻结提交 c1051', 'done'],
    ['校验设计一致性', 'done'],
    ['生成结构化变更组', 'done'],
    ['更新需求图谱', 'done'],
    ['生成正式设计文档', 'now'],
    ['发布版本 v1.4', 'todo'],
  ],
}

export const RELEASES: ReleaseRun[] = [
  { id: 'v1.3', time: '2026-09-21 18:00', status: '成功' },
  { id: 'v1.2', time: '2026-09-20 12:20', status: '成功' },
]

// Every node below carries `edgeLinks` (ACP-802): each edge's own sentence
// plus the instances it lands on. The graph is CLOSED — every target names a
// node that really is in this table, under the type it is filed under — so the
// drill-down 类型 → 实例 → 边 → 关联实例 walks a world that exists rather than
// one assembled per screen.
export const GRAPH_NODES: Record<string, GraphNode[]> = {
  页面: [
    {
      id: 'page-opportunity',
      name: '商机详情页',
      props: { 编码: 'PAGE_OPPORTUNITY', 布局: '详情页布局', 状态: '有效' },
      edges: ['包含 → 阶段推进组件', '读取 → 商机实体', '写入 → 商机历史'],
      edgeLinks: [
        { label: '包含 → 阶段推进组件', targets: [{ id: 'comp-stage', name: '阶段推进组件', type: '组件' }] },
        { label: '读取 → 商机实体', targets: [{ id: 'entity-opportunity', name: '商机', type: '实体' }] },
        { label: '写入 → 商机历史', targets: [{ id: 'entity-opportunity-history', name: '商机历史', type: '实体' }] },
      ],
    },
  ],
  实体: [
    {
      id: 'entity-opportunity',
      name: '商机',
      props: { 编码: 'OPPORTUNITY', 主键: 'opportunity_id', 状态: '有效' },
      edges: ['拥有 → 商机阶段', '产生 → 商机历史', '展示于 → 商机详情页'],
      edgeLinks: [
        { label: '拥有 → 商机阶段', targets: [{ id: 'entity-opportunity-stage', name: '商机阶段', type: '实体' }] },
        { label: '产生 → 商机历史', targets: [{ id: 'entity-opportunity-history', name: '商机历史', type: '实体' }] },
        { label: '展示于 → 商机详情页', targets: [{ id: 'page-opportunity', name: '商机详情页', type: '页面' }] },
      ],
    },
    {
      id: 'entity-opportunity-stage',
      name: '商机阶段',
      props: { 编码: 'OPPORTUNITY_STAGE', 主键: 'opportunity_stage_id', 状态: '有效' },
      edges: ['属于 → 商机', '受约束于 → 商机阶段流转规则'],
      edgeLinks: [
        { label: '属于 → 商机', targets: [{ id: 'entity-opportunity', name: '商机', type: '实体' }] },
        { label: '受约束于 → 商机阶段流转规则', targets: [{ id: 'rule-stage', name: '商机阶段流转规则', type: '业务规则' }] },
      ],
    },
    {
      id: 'entity-opportunity-history',
      name: '商机历史',
      props: { 编码: 'OPPORTUNITY_HISTORY', 主键: 'opportunity_history_id', 状态: '有效' },
      edges: ['记录 → 商机'],
      edgeLinks: [
        { label: '记录 → 商机', targets: [{ id: 'entity-opportunity', name: '商机', type: '实体' }] },
      ],
    },
  ],
  业务规则: [
    {
      id: 'rule-stage',
      name: '商机阶段流转规则',
      props: { 编码: 'RULE_STAGE_FLOW', 类型: '状态流转', 状态: '有效' },
      edges: ['约束 → 商机阶段', '影响 → 商机详情页'],
      edgeLinks: [
        { label: '约束 → 商机阶段', targets: [{ id: 'entity-opportunity-stage', name: '商机阶段', type: '实体' }] },
        { label: '影响 → 商机详情页', targets: [{ id: 'page-opportunity', name: '商机详情页', type: '页面' }] },
      ],
    },
  ],
  组件: [
    {
      id: 'comp-stage',
      name: '阶段推进组件',
      props: { 编码: 'COMP_STAGE', 类型: '业务组件', 状态: '有效' },
      edges: ['嵌入 → 商机详情页', '操作 → 商机实体'],
      edgeLinks: [
        { label: '嵌入 → 商机详情页', targets: [{ id: 'page-opportunity', name: '商机详情页', type: '页面' }] },
        { label: '操作 → 商机实体', targets: [{ id: 'entity-opportunity', name: '商机', type: '实体' }] },
      ],
    },
  ],
}

export const DEV: ProgressModel = {
  total: 7,
  done: 4,
  current: '实现前端阶段推进组件',
  tasks: [
    ['准备开发输入', 'done'],
    ['生成开发任务', 'done'],
    ['后端模型调整', 'done'],
    ['后端接口调整', 'done'],
    ['实现前端阶段推进组件', 'now'],
    ['自动化测试', 'todo'],
    ['构建开发结果', 'todo'],
  ],
}

export const DEV_HISTORY: ReleaseRun[] = [
  { id: 'dev-309', time: '2026-09-21 19:20', status: '完成' },
  { id: 'dev-301', time: '2026-09-20 15:05', status: '完成' },
]

export const DEPLOYMENTS: DeployEntry[] = [
  { id: 'deploy-024', env: '测试环境', version: 'run-024', status: '运行中', time: '2026-09-22 11:20' },
  { id: 'deploy-023', env: '测试环境', version: 'run-023', status: '成功', time: '2026-09-21 20:10' },
  { id: 'deploy-018', env: '集成环境', version: 'run-018', status: '成功', time: '2026-09-20 16:00' },
]

export const DESIGN_VERSION = 'v1.4'
export const RUN_VERSION = 'run-024'
