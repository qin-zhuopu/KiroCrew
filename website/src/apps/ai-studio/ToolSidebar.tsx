// Right column: the tool sidebar. Six tool tabs (docs / commits / releases /
// graph / dev / deploy); every row opens a tab in the center work area via
// onOpenTab. The graph tab drills type → node → (tab), mirroring the demo's
// two-level navigation. Docs are the project's real files (passed in from the
// workspace query) and the releases tab is the publish version list; the other
// four tabs are fixture-backed unless a caller injects its own content — the
// commits lists (ACP-795) and the 开发 / 部署 tabs (ACP-799). Every injection is
// optional and defaults to that fixture, so an ordinary workbench is unchanged.
import { useState, type ReactNode } from 'react'
import { ArrowLeft } from 'lucide-react'
import { i18nT } from '../../i18n/t'
import {
  CHANGED,
  COMMITS,
  DEPLOYMENTS,
  DEV,
  DEV_HISTORY,
  GRAPH_NODES,
  type ChangedFile,
  type CommitEntry,
  type ProgressModel,
  type ReleaseRun,
} from './fixtures'
import DistillPanel from './DistillPanel'
import type {
  StudioDistillation,
  StudioDoc,
  StudioPublishApi,
  StudioReleaseFiles,
} from './studioApi'
import PublishVersionList from './PublishVersionList'
import type { WorkTab } from './WorkArea'

type Tool = 'docs' | 'commits' | 'releases' | 'graph' | 'dev' | 'deploy'

const TOOL_KEYS: Record<Tool, string> = {
  docs: i18nT('apps.aiStudio.tool_docs'),
  commits: i18nT('apps.aiStudio.tool_commits'),
  releases: i18nT('apps.aiStudio.tool_releases'),
  graph: i18nT('apps.aiStudio.tool_graph'),
  dev: i18nT('apps.aiStudio.tool_dev'),
  deploy: i18nT('apps.aiStudio.tool_deploy'),
}

/** One sidebar tab whose content comes from OUTSIDE (ACP-799). The 开发 and 部署
 * tabs are the two the demo's dev/deploy frames cover, and a frame knows facts
 * the shipped fixtures do not (its own run, its own deployment, its own
 * history). A caller injects the three parts and this file owns the SHAPE, once,
 * because the owner's layout rule is uniform across tabs: 过程 on top — the
 * current in-flight items with each one's state — and 历史记录 below. An
 * injected tab therefore cannot drift into a third arrangement.
 *
 * The parts are nodes, not data, on purpose: the demo hands in the render of the
 * REAL components (`DevRunPanel`, `DeployFramePanel`, `ReleaseControl`), so this
 * file keeps knowing nothing about the demo and the product keeps one
 * implementation of each picture. */
export interface ToolTabInjection {
  /** the tab-top action button (the frames pass ReleaseControl's own 开始开发 /
   * 部署 button); omitted = no button, exactly as today */
  action?: ReactNode
  /** 「过程」: the current in-flight list and each item's state */
  current: ReactNode
  /** 「历史记录」: the previous rounds, newest last */
  history: ReleaseRun[]
}

export interface ToolSidebarProps {
  onOpenTab: (tab: WorkTab) => void
  /** The current project's docs, straight from the store. */
  docs: StudioDoc[]
  /** The project whose versions the publish tab lists. */
  projectId: string
  // ---- two OPTIONAL seams the state-direct demo's frames pin (ACP-795).
  // Both default to today's behaviour, so an ordinary workbench that passes
  // neither renders exactly what it rendered before: the sidebar always opens
  // on 文档, and the commits tab reads the CHANGED / COMMITS fixtures.
  /** which tool tab is showing on first paint (a demo frame sets 'commits'
   * to pin the 提交 tab lit); omitted = 'docs' */
  initialTool?: Tool
  /** the commits tab's 「待提交的改动」 rows (a demo frame's own list) */
  changed?: ChangedFile[]
  /** the commits tab's 「提交历史」 rows (a demo frame's own list) */
  commits?: CommitEntry[]
  // ACP-794 adds ONE more of the same kind, for the same reason: the releases
  // tab's publish reads. The demo's release frames carry their versions /
  // records / previews as data, and the real client throws under `?demo=`, so
  // that frame hands its snapshot-backed stand-in down to the version list.
  // Omitted (every ordinary workbench) => PublishVersionList's own default.
  /** the releases tab's publish read source */
  publishApi?: StudioPublishApi
// ---- ACP-797 adds the SAME kind of seam for the 需求图谱 tab, because the
  // owner's rule is that a stage's artifacts and processes are observed in
  // their own sidebar tab and never on a canvas in the center column. So a
  // demo frame hands in its graph AS A LIST — grouped by type, one row per
  // entry, each row marked 新增 / 修改 / 移除 for this change — plus the
  // generation run that produced it, which the real DistillPanel renders.
  // Neither is passed by an ordinary workbench: absent `graphEntries` the tab
  // is byte-for-byte today's type → node drill-down over GRAPH_NODES, and
  // absent `distillation` the panel is not mounted at all.
  /** the 需求图谱 tab's list: entries grouped by type (a demo frame's graph) */
  graphEntries?: GraphEntryGroup[]
  /** the 需求图谱 tab's generation run (status 'running' → 进行中, 'done' →
   * the extracted candidates), rendered by the shipped DistillPanel */
  distillation?: StudioDistillation
  // ACP-798 adds a fourth of the same kind: 本版修改过的文件 for the releases
  // tab. Omitted — every ordinary workbench — the list is simply absent.
  /** the releases tab's 本版修改过的文件 list (a demo frame's own data) */
  releaseFiles?: StudioReleaseFiles
  // ACP-798 (owner 追加) adds the fifth: the 发版 tab's OWN 发版 button, at the
  // top of that tab — 动作按钮跟着页签走. Omitted (every ordinary workbench)
  // the tab renders no button, exactly as it did before.
  /** the releases tab's own 发版 action (which version it fires, walk labels) */
  releaseAction?: { version: string; phaseKeys?: string[] }
  // ACP-799 adds the same kind of seam to the LAST two fixture-backed tabs: the
  // 开发 / 部署 tabs read the DEV / DEPLOYMENTS fixtures today, and the demo's
  // V/P frames carry their own run / deployment / history. Omitted (every
  // ordinary workbench, and every frame that is not a dev/deploy one) => the
  // fixtures render exactly as before.
  /** the 开发 tab's injected 过程 / 历史 (a dev frame's own run) */
  dev?: ToolTabInjection
  /** the 部署 tab's injected 过程 / 历史 (a deploy frame's own record) */
  deploy?: ToolTabInjection
}

/** One entry row of the 需求图谱 tab's list (ACP-797): a node of the frame's
 * graph, read as a line of text. `mark` is the frame's own derivation of what
 * THIS change did to it — never a per-row hand-written label. */
export interface GraphEntryRow {
  id: string
  label: string
  /** 本次新增 / 修改 / 移除, absent for an entry this change left alone */
  mark?: 'added' | 'modified' | 'removed'
  /** the entry's own provenance line (frame data) */
  meta?: string
  /** the doc this entry traces to. A row that names one opens that doc's
   * editor — the middle column's only allowed content under the same rule;
   * a row without one (a module, a pruned entry) is read-only, and renders as
   * plain text rather than a button that would do nothing when pressed. */
  doc?: string
}

/** A type group of that list. The header is frame DATA, like the shipped
 * GRAPH_NODES' 页面 / 实体 keys: the graph's vocabulary belongs to the world
 * the frame describes, not to this component's copy. */
export interface GraphEntryGroup {
  label: string
  rows: GraphEntryRow[]
}

/** the mark's label, read from the distillation vocabulary the panel already
 * ships (Add / Modify / Remove) — the same three words for the same three
 * changes, so the tab and the panel beside it cannot drift apart */
const MARK_KEY = {
  added: 'apps.aiStudio.distill_group_add',
  modified: 'apps.aiStudio.distill_group_modify',
  removed: 'apps.aiStudio.distill_group_remove',
} as const

export default function ToolSidebar({
onOpenTab, docs, projectId, initialTool = 'docs', changed, commits, publishApi,
  graphEntries, distillation, releaseFiles, releaseAction, dev, deploy,
}: ToolSidebarProps) {
  const [tool, setTool] = useState<Tool>(initialTool)
  // graph drill state: null = type list, string = inside a type
  const [graphType, setGraphType] = useState<string | null>(null)

  const pick = (t: Tool) => {
    setTool(t)
    if (t !== 'graph') setGraphType(null)
  }

  return (
    <div className="flex flex-col h-full min-h-0" data-testid="tool-sidebar">
      <div className="px-3 h-[38px] shrink-0 flex items-center border-b border-border text-[13px] font-semibold text-text-strong">
        {i18nT('apps.aiStudio.tools_title')}
      </div>
      <div className="flex shrink-0 border-b border-border overflow-x-auto" role="tablist" aria-label={i18nT('apps.aiStudio.tools_title')}>
        {(Object.keys(TOOL_KEYS) as Tool[]).map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={tool === t}
            data-testid={t === 'releases' ? 'ai-studio-publish-entry' : undefined}
            onClick={() => pick(t)}
            className={`px-2.5 py-2.5 text-[12px] whitespace-nowrap cursor-pointer border-b-2 transition-colors ${
              tool === t ? 'text-accent border-accent font-semibold' : 'text-muted border-transparent hover:text-text'
            }`}
          >
            {TOOL_KEYS[t]}
          </button>
        ))}
      </div>
      <div className="flex-1 min-h-0 overflow-auto p-3">
        {tool === 'docs' && <DocsTool docs={docs} onOpenTab={onOpenTab} />}
        {tool === 'commits' && <CommitsTool onOpenTab={onOpenTab} changed={changed} commits={commits} />}
{tool === 'releases' && (
          <PublishVersionList
            projectId={projectId}
            api={publishApi}
            releaseFiles={releaseFiles}
            releaseAction={releaseAction}
          />
        )}
        {tool === 'graph' && (
          <GraphTool
            graphType={graphType}
            setGraphType={setGraphType}
            onOpenTab={onOpenTab}
            docs={docs}
            entries={graphEntries}
            distillation={distillation}
          />
        )}
        {tool === 'dev' && (dev
          ? <InjectedTool tab="dev" injection={dev} onOpenTab={onOpenTab} />
          : <ReleasesTool model={DEV} onOpenTab={onOpenTab} history={DEV_HISTORY} noun={i18nT('apps.aiStudio.dev')} />)}
        {tool === 'deploy' && (deploy
          ? <InjectedTool tab="deploy" injection={deploy} onOpenTab={onOpenTab} />
          : <DeployTool onOpenTab={onOpenTab} />)}
      </div>
    </div>
  )
}

function Section({ children }: { children: string }) {
  return <div className="text-[11px] uppercase tracking-wide text-muted mx-0.5 mt-2 mb-1.5 first:mt-0">{children}</div>
}

function Row({ title, meta, pill, pillTone = 'idle', strike = false, testid, onClick }: {
  title: string
  meta?: string
  pill?: string
  pillTone?: 'idle' | 'done' | 'now'
  /** 本次移除的条目: struck through, so the list says what is gone instead of
   * quietly omitting it (ACP-797 — the same mark the graph view drew) */
  strike?: boolean
  /** the row's own testid, for the lists whose rows a frame names (ACP-797's
   * graph entries). Omitted everywhere else → no attribute, as before. */
  testid?: string
  /** absent → the row is NOT interactive and renders as plain text: a button
   * that does nothing when pressed is a lie about what the row offers. Every
   * shipped call site passes one, so their DOM is unchanged. */
  onClick?: () => void
}) {
  const body = (
    <>
      <div className="flex items-center justify-between gap-2">
        <span className={`text-[12px] font-semibold truncate ${strike ? 'text-muted line-through' : 'text-text'}`}>{title}</span>
        {pill && (
          <span className={`shrink-0 rounded-full px-1.5 py-0.5 text-[10px] ${
            pillTone === 'done' ? 'bg-accent-subtle text-accent' : pillTone === 'now' ? 'bg-bg-hover text-accent' : 'bg-bg-hover text-muted'
          }`}>{pill}</span>
        )}
      </div>
      {meta && <div className="text-[11px] text-muted mt-1">{meta}</div>}
    </>
  )
  const shell = 'w-full text-left rounded-lg border border-border bg-card px-3 py-2.5 mb-2'
  if (!onClick) return <div data-testid={testid} className={shell}>{body}</div>
  return (
    <button type="button" data-testid={testid} onClick={onClick} className={`${shell} transition-colors hover:border-accent cursor-pointer`}>
      {body}
    </button>
  )
}

function DocsTool({ docs, onOpenTab }: Pick<ToolSidebarProps, 'docs' | 'onOpenTab'>) {
  return (
    <div>
      <Section>{i18nT('apps.aiStudio.doc_list')}</Section>
      {docs.length === 0 && (
        <div className="text-[12px] text-muted px-1 py-2">{i18nT('apps.aiStudio.no_docs')}</div>
      )}
      {docs.map((d) => (
        <Row
          key={d.name}
          title={d.name}
          onClick={() => onOpenTab({ id: `doc-${d.name}`, kind: 'doc', title: d.name, docName: d.name, initialContent: d.content })}
        />
      ))}
    </div>
  )
}

/** The commits tab. Its two lists are PROPS with the fixtures as defaults
 * (ACP-795): a demo frame hands in its own 「本次迭代的待提交改动」 and
 * 「提交历史」 without a second sidebar, and every ordinary caller keeps
 * reading CHANGED / COMMITS exactly as before. */
function CommitsTool({ onOpenTab, changed = CHANGED, commits = COMMITS }: Pick<ToolSidebarProps, 'onOpenTab'> & {
  changed?: ChangedFile[]
  commits?: CommitEntry[]
}) {
  return (
    <div>
      <Section>{i18nT('apps.aiStudio.pending_changes')}</Section>
      {changed.map((c) => (
        <Row
          key={c.file}
          title={c.file}
          pill={i18nT('apps.aiStudio.modified')}
          pillTone="now"
          onClick={() => onOpenTab({ id: `diff-${c.file}`, kind: 'diff', title: `${c.file} · ${i18nT('apps.aiStudio.diff_title')}`, file: c.file })}
        />
      ))}
      <Section>{i18nT('apps.aiStudio.commit_history')}</Section>
      {commits.map((c) => (
        <Row
          key={c.id}
          title={c.message}
          meta={`${c.id} · ${c.time}`}
          onClick={() => onOpenTab({ id: `commit-${c.id}`, kind: 'commit', title: `${i18nT('apps.aiStudio.commit')} ${c.id}`, commitId: c.id })}
        />
      ))}
    </div>
  )
}

function ProgressBar({ model }: { model: ProgressModel }) {
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2.5 mb-2">
      <div className="flex items-center justify-between">
        <span className="text-[12px] font-semibold text-text">{i18nT('apps.aiStudio.progress_title')}</span>
        <span className="text-[11px] text-muted">{model.done}/{model.total}</span>
      </div>
      <div className="text-[11px] text-muted mt-1">{i18nT('apps.aiStudio.in_progress')}: {model.current}</div>
      <div className="h-2 rounded-full bg-bg-hover mt-2 overflow-hidden">
        <div className="h-full bg-accent rounded-full" style={{ width: `${(model.done / model.total) * 100}%` }} />
      </div>
      {model.tasks.map(([name, st], i) => (
        <div key={i} className="flex items-center gap-2 py-1.5 border-t border-dashed border-border text-[12px] mt-2 first:mt-2">
          <span className={`w-2 h-2 rounded-full shrink-0 ${st === 'done' ? 'bg-accent' : st === 'now' ? 'bg-accent animate-pulse' : 'bg-border-strong'}`} />
          <span className={st === 'todo' ? 'text-muted' : 'text-text'}>{name}</span>
          {st === 'now' && <span className="ml-auto rounded-full bg-bg-hover text-accent px-1.5 py-0.5 text-[10px]">{i18nT('apps.aiStudio.running')}</span>}
        </div>
      ))}
    </div>
  )
}

function ReleasesTool({ model, history, noun, onOpenTab }: {
  model: ProgressModel
  history: Array<{ id: string; time: string; status: string }>
  noun: string
  onOpenTab: ToolSidebarProps['onOpenTab']
}) {
  return (
    <div>
      <Section>{i18nT('apps.aiStudio.current_progress')}</Section>
      <ProgressBar model={model} />
      <Section>{i18nT('apps.aiStudio.history')}</Section>
      {history.map((r) => (
        <Row
          key={r.id}
          title={r.id}
          meta={r.time}
          pill={r.status}
          pillTone="done"
          onClick={() => onOpenTab({ id: `rel-${r.id}`, kind: 'commit', title: `${noun} ${r.id}`, commitId: r.id })}
        />
      ))}
    </div>
  )
}

/** The 需求图谱 tab (ACP-797). Two shapes, and which one is on screen is
 * DATA: a frame that carries `entries` shows its own graph as a list — the
 * generation run above it (the shipped DistillPanel, on the run's own status),
 * then one section per type, one row per entry, each row marked with what THIS
 * change did to it. No frame carries entries → the shipped drill-down, byte
 * for byte as before. Neither shape draws a node-and-arrow canvas: the owner's
 * rule is that the graph is observed here, as text. */
function GraphTool({ graphType, setGraphType, onOpenTab, docs, entries, distillation }: {
  graphType: string | null
  setGraphType: (t: string | null) => void
  onOpenTab: ToolSidebarProps['onOpenTab']
  docs: StudioDoc[]
  entries?: GraphEntryGroup[]
  distillation?: StudioDistillation
}) {
  if (entries) {
    return (
      <div>
        {distillation && (
          <div className="mb-2" data-testid="graph-tab-run">
            <DistillPanel distillation={distillation} />
          </div>
        )}
        {entries.map((group) => (
          <div key={group.label}>
            <Section>{group.label}</Section>
            {group.rows.map((r) => {
              // an entry that names a doc opens that doc's editor — the only
              // content the middle column may hold; one that does not is text
              const doc = r.doc ? docs.find((d) => d.name === r.doc) : undefined
              return (
                <Row
                  key={r.id}
                  testid={`graph-entry-${r.id}`}
                  title={r.label}
                  meta={r.meta}
                  strike={r.mark === 'removed'}
                  pill={r.mark ? i18nT(MARK_KEY[r.mark]) : undefined}
                  pillTone={r.mark === 'added' ? 'now' : r.mark === 'modified' ? 'done' : 'idle'}
                  onClick={doc
                    ? () => onOpenTab({ id: `doc-${doc.name}`, kind: 'doc', title: doc.name, docName: doc.name, initialContent: doc.content })
                    : undefined}
                />
              )
            })}
          </div>
        ))}
      </div>
    )
  }
  if (graphType === null) {
    return (
      <div>
        <Section>{i18nT('apps.aiStudio.node_types')}</Section>
        {Object.entries(GRAPH_NODES).map(([type, nodes]) => (
          <Row key={type} title={type} pill={String(nodes.length)} onClick={() => setGraphType(type)} />
        ))}
      </div>
    )
  }
  const nodes = GRAPH_NODES[graphType] ?? []
  return (
    <div>
      <button
        type="button"
        onClick={() => setGraphType(null)}
        className="flex items-center gap-1 text-[12px] text-accent cursor-pointer mb-2 hover:underline"
      >
        <ArrowLeft size={13} /> {i18nT('apps.aiStudio.node_types')}
      </button>
      <Section>{graphType}</Section>
      {nodes.map((n) => (
        <Row
          key={n.id}
          title={n.name}
          onClick={() => onOpenTab({ id: `node-${n.id}`, kind: 'node', title: n.name, type: graphType, nodeId: n.id })}
        />
      ))}
    </div>
  )
}

/** A 开发 / 部署 tab rendered from an injected 过程 + 历史 (ACP-799). The shape
 * is the same one `ReleasesTool` / `DeployTool` already use — action, then
 * 「过程」, then 「历史记录」 — so all four tabs read alike; the only difference is
 * WHERE the two blocks come from. History rows open the tab their own tool has
 * always opened (a dev record opens a commit tab, a deployment its deploy log). */
function InjectedTool({ tab, injection, onOpenTab }: {
  tab: 'dev' | 'deploy'
  injection: ToolTabInjection
  onOpenTab: ToolSidebarProps['onOpenTab']
}) {
  return (
    <div>
      {injection.action && <div className="mb-2">{injection.action}</div>}
      <Section>{i18nT('apps.aiStudio.current_progress')}</Section>
      {injection.current}
      <Section>{i18nT('apps.aiStudio.history')}</Section>
      {injection.history.map((r) => (
        <Row
          key={r.id}
          title={r.id}
          meta={r.time}
          pill={r.status}
          pillTone="done"
          onClick={() => onOpenTab(tab === 'deploy'
            ? { id: `deploy-${r.id}`, kind: 'deploy', title: `${r.id} · ${i18nT('apps.aiStudio.deploy_log')}`, deployId: r.id }
            : { id: `rel-${r.id}`, kind: 'commit', title: r.id, commitId: r.id })}
        />
      ))}
    </div>
  )
}

function DeployTool({ onOpenTab }: Pick<ToolSidebarProps, 'onOpenTab'>) {
  const [current, ...rest] = DEPLOYMENTS
  const open = (id: string) => {
    const d = DEPLOYMENTS.find((x) => x.id === id)
    if (d) onOpenTab({ id: `deploy-${d.id}`, kind: 'deploy', title: `${d.id} · ${i18nT('apps.aiStudio.deploy_log')}`, deployId: d.id })
  }
  return (
    <div>
      <Section>{i18nT('apps.aiStudio.running_deploy')}</Section>
      <Row title={current.id} meta={`${current.env} · ${current.version}`} pill={current.status} pillTone="now" onClick={() => open(current.id)} />
      <Section>{i18nT('apps.aiStudio.history')}</Section>
      {rest.map((d) => (
        <Row key={d.id} title={d.id} meta={`${d.env} · ${d.version} · ${d.time}`} pill={d.status} pillTone="done" onClick={() => open(d.id)} />
      ))}
    </div>
  )
}
