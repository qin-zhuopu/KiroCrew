// Right column: the tool sidebar. Six tool tabs (docs / commits / releases /
// graph / dev / deploy); every row opens a tab in the center work area via
// onOpenTab. The graph tab drills type → node → (tab), mirroring the demo's
// two-level navigation. Docs are the project's real files (passed in from the
// workspace query); the other five tabs remain fixture-backed.
import { useState } from 'react'
import { ArrowLeft } from 'lucide-react'
import { i18nT } from '../../i18n/t'
import {
  CHANGED,
  COMMITS,
  DEPLOYMENTS,
  DEV,
  DEV_HISTORY,
  GRAPH_NODES,
  RELEASE,
  RELEASES,
  type ProgressModel,
} from './fixtures'
import type { StudioDoc } from './studioApi'
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

export interface ToolSidebarProps {
  onOpenTab: (tab: WorkTab) => void
  /** The current project's docs, straight from the store. */
  docs: StudioDoc[]
}

export default function ToolSidebar({ onOpenTab, docs }: ToolSidebarProps) {
  const [tool, setTool] = useState<Tool>('docs')
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
        {tool === 'commits' && <CommitsTool onOpenTab={onOpenTab} />}
        {tool === 'releases' && <ReleasesTool model={RELEASE} onOpenTab={onOpenTab} history={RELEASES} noun={i18nT('apps.aiStudio.release')} />}
        {tool === 'graph' && <GraphTool graphType={graphType} setGraphType={setGraphType} onOpenTab={onOpenTab} />}
        {tool === 'dev' && <ReleasesTool model={DEV} onOpenTab={onOpenTab} history={DEV_HISTORY} noun={i18nT('apps.aiStudio.dev')} />}
        {tool === 'deploy' && <DeployTool onOpenTab={onOpenTab} />}
      </div>
    </div>
  )
}

function Section({ children }: { children: string }) {
  return <div className="text-[11px] uppercase tracking-wide text-muted mx-0.5 mt-2 mb-1.5 first:mt-0">{children}</div>
}

function Row({ title, meta, pill, pillTone = 'idle', onClick }: {
  title: string
  meta?: string
  pill?: string
  pillTone?: 'idle' | 'done' | 'now'
  onClick?: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full text-left rounded-lg border border-border bg-card px-3 py-2.5 mb-2 transition-colors hover:border-accent cursor-pointer"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-[12px] font-semibold text-text truncate">{title}</span>
        {pill && (
          <span className={`shrink-0 rounded-full px-1.5 py-0.5 text-[10px] ${
            pillTone === 'done' ? 'bg-accent-subtle text-accent' : pillTone === 'now' ? 'bg-bg-hover text-accent' : 'bg-bg-hover text-muted'
          }`}>{pill}</span>
        )}
      </div>
      {meta && <div className="text-[11px] text-muted mt-1">{meta}</div>}
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

function CommitsTool({ onOpenTab }: Pick<ToolSidebarProps, 'onOpenTab'>) {
  return (
    <div>
      <Section>{i18nT('apps.aiStudio.pending_changes')}</Section>
      {CHANGED.map((c) => (
        <Row
          key={c.file}
          title={c.file}
          pill={i18nT('apps.aiStudio.modified')}
          pillTone="now"
          onClick={() => onOpenTab({ id: `diff-${c.file}`, kind: 'diff', title: `${c.file} · ${i18nT('apps.aiStudio.diff_title')}`, file: c.file })}
        />
      ))}
      <Section>{i18nT('apps.aiStudio.commit_history')}</Section>
      {COMMITS.map((c) => (
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
  history: typeof RELEASES
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

function GraphTool({ graphType, setGraphType, onOpenTab }: {
  graphType: string | null
  setGraphType: (t: string | null) => void
  onOpenTab: ToolSidebarProps['onOpenTab']
}) {
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
