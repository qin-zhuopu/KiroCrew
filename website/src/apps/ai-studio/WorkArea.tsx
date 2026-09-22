// Center column: a closable tab strip over a content area. Each tab carries a
// discriminated `kind`; the body renders the matching view from fixtures. This
// is workspace-local state (which tabs are open), not shell state, so it lives
// here rather than in the surface registry or a global store.
import { X } from 'lucide-react'
import { i18nT } from '../../i18n/t'
import CommitView from './CommitView'
import DeployLog from './DeployLog'
import DiffView from './DiffView'
import DocEditor from './DocEditor'
import NodeDetail from './NodeDetail'
import type { StudioApi } from './studioApi'

export type WorkTab =
  | { id: string; kind: 'doc'; title: string; docName: string; initialContent: string }
  | { id: string; kind: 'diff'; title: string; file: string }
  | { id: string; kind: 'commit'; title: string; commitId: string }
  | { id: string; kind: 'node'; title: string; type: string; nodeId: string }
  | { id: string; kind: 'deploy'; title: string; deployId: string }

export interface WorkAreaProps {
  tabs: WorkTab[]
  activeId: string | null
  onSelect: (id: string) => void
  onClose: (id: string) => void
  /** Which project the open doc tabs belong to — DocEditor autosaves drafts against it. */
  projectId: string
  onDocSaved: () => void
  /** data source for the doc editor; the demo passes its snapshot fake */
  api?: StudioApi
  /** Bumped by the workspace top bar after a project-level commit: part of
   * the DocEditor's key, so the open editors re-mount against the tab's
   * freshly committed content instead of showing a stale dirty buffer. */
  /** omitted by the demo harness, whose script controls re-mounts itself */
  commitRev?: number
}

export default function WorkArea({ tabs, activeId, onSelect, onClose, projectId, onDocSaved, api, commitRev = 0 }: WorkAreaProps) {
  const active = tabs.find((t) => t.id === activeId) ?? null
  return (
    <div className="flex flex-col h-full min-h-0">
      {tabs.length > 0 && (
        <div className="flex flex-wrap items-start gap-0.5 px-2 min-h-[40px] border-b border-border bg-card" role="tablist" aria-label={i18nT('apps.aiStudio.workspace_tabs')}>
          {tabs.map((t) => {
            const on = t.id === activeId
            return (
              <div
                key={t.id}
                role="tab"
                aria-selected={on}
                tabIndex={0}
                onClick={() => onSelect(t.id)}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(t.id) } }}
                className={`group flex items-center gap-1.5 px-3 py-2.5 text-[13px] cursor-pointer select-none border-b-2 whitespace-nowrap ${
                  on ? 'text-accent border-accent font-semibold' : 'text-muted border-transparent hover:text-text'
                }`}
              >
                {t.title}
                <button
                  type="button"
                  aria-label={i18nT('apps.aiStudio.close_tab')}
                  onClick={(e) => { e.stopPropagation(); onClose(t.id) }}
                  className="opacity-0 group-hover:opacity-100 focus:opacity-100 rounded p-0.5 hover:bg-bg-hover text-muted hover:text-text"
                >
                  <X size={13} />
                </button>
              </div>
            )
          })}
        </div>
      )}
      <div className="flex-1 min-h-0 overflow-auto bg-card">
        {!active ? (
          <div className="h-full grid place-items-center text-muted text-[13px] p-10">
            {i18nT('apps.aiStudio.empty_hint')}
          </div>
        ) : active.kind === 'doc' ? (
          // the tab id rides in the key so a demo step (which re-keys its
          // single tab per step) re-mounts the editor wholesale; for the
          // ordinary path a tab's id is constant, so this stays the same
          // stable identity the editor has always had
          <DocEditor
            key={`${projectId}:${active.docName}:${commitRev}`}
            projectId={projectId}
            docName={active.docName}
            initialContent={active.initialContent}
            api={api}
          />
        ) : active.kind === 'diff' ? (
          <DiffView file={active.file} />
        ) : active.kind === 'commit' ? (
          <CommitView commitId={active.commitId} />
        ) : active.kind === 'node' ? (
          <NodeDetail type={active.type} nodeId={active.nodeId} />
        ) : (
          <DeployLog deployId={active.deployId} />
        )}
      </div>
    </div>
  )
}
