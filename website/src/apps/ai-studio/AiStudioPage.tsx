// AI Studio — a three-column coding-studio shell over Kiro Crew.
//
// This component is the app's whole route surface: the dashboard's catch-all
// (`/:builtinApp/*`) resolves every sub-path through the registry's single
// `/ai-studio` entry, so the split between the two views happens here by URL:
//   /ai-studio                   → ProjectsListPage (list + create)
//   /ai-studio/projects/<id>     → StudioWorkspace (the workbench for one project)
//
// Workspace: left the native chat (ChatEmbed, real sessions — same embed
// contract the spec-builder uses), center a tabbed work area (docs / diffs /
// commits / graph / deploy logs), right the tool sidebar that opens tabs.
// Docs are the project's real files from /api/apps/ai-studio; the other tool
// tabs are still fixture-backed (fixtures.ts) until those APIs exist. Pane
// widths and visibility persist per app in localStorage.
import { useCallback, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, FolderKanban, GitCommit, PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen } from 'lucide-react'
import { AppScopedApiProvider } from '../../app-sdk/scopedApi'
import ErrorNotice from '../../components/ErrorNotice'
import { Btn, ContentSkeleton } from '../../components/ui'
import { usePointerDrag } from '../../hooks/usePointerDrag'
import { i18nT } from '../../i18n/t'
import ChatPane from './ChatPane'
import ProjectsListPage from './ProjectsListPage'
import ToolSidebar from './ToolSidebar'
import WorkArea, { type WorkTab } from './WorkArea'
import { DESIGN_VERSION, RUN_VERSION } from './fixtures'
import { studioApi, StudioApiError, type StudioDoc } from './studioApi'

const LS_WIDTHS = 'ai-studio.widths'
const LS_HIDDEN = 'ai-studio.hidden'

const MIN_W = 180
const clampW = (w: number) => Math.round(Math.max(MIN_W, Math.min(window.innerWidth * 0.55, w)))

interface Widths { left: number; right: number }
function loadWidths(): Widths {
  try {
    const raw = localStorage.getItem(LS_WIDTHS)
    if (raw) {
      const p = JSON.parse(raw) as Partial<Widths>
      return { left: clampW(p.left ?? 300), right: clampW(p.right ?? 390) }
    }
  } catch { /* fresh profile or corrupt value — fall through to defaults */ }
  return { left: 300, right: 390 }
}

interface Hidden { left: boolean; center: boolean; right: boolean }
function loadHidden(): Hidden {
  try {
    const raw = localStorage.getItem(LS_HIDDEN)
    if (raw) {
      const p = JSON.parse(raw) as Partial<Hidden>
      return { left: !!p.left, center: !!p.center, right: !!p.right }
    }
  } catch { /* same: defaults */ }
  return { left: false, center: false, right: false }
}

/** `/ai-studio/projects/<id>` → the id; anything else → the list. The id is
 * read off the pathname rather than nested <Route>s because the dashboard
 * mounts this page as one catch-all entry (see BuiltinAppRoute). */
const WORKSPACE_RE = /^\/ai-studio\/projects\/([^/]+)/

export default function AiStudioPage() {
  const match = useLocation().pathname.match(WORKSPACE_RE)
  if (match) return <StudioWorkspace projectId={decodeURIComponent(match[1])} />
  return <ProjectsListPage />
}

export function StudioWorkspace({ projectId }: { projectId: string }) {
  const navigate = useNavigate()
  // Stable identity: a fresh arrow per render would rebuild the scoped-api
  // context value, which re-fires ChatPane's slot-open effect.
  const navigateFn = useCallback((path: string) => navigate(path), [navigate])
  const [widths, setWidths] = useState<Widths>(loadWidths)
  const [hidden, setHidden] = useState<Hidden>(loadHidden)
  const [tabs, setTabs] = useState<WorkTab[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  // Bumped after each project-level commit so open doc editors re-mount
  // against the committed content (WorkArea keys the editor on it).
  const [commitRev, setCommitRev] = useState(0)
  const [committing, setCommitting] = useState(false)
  const [commitErr, setCommitErr] = useState<string | null>(null)
  const queryClient = useQueryClient()

  const projectQuery = useQuery({
    queryKey: ['ai-studio', 'project', projectId],
    queryFn: () => studioApi.getProject(projectId),
  })
  const docs: StudioDoc[] = projectQuery.data?.docs ?? []

  // Which docs hold an uncommitted draft — the top bar's Commit affordance
  // and its work list. No polling: the default refetch-on-focus plus the
  // post-commit refetch keep it honest, and an editor mid-typing lands its
  // next autosave draft as a fresh entry on the next such read.
  const draftsQuery = useQuery({
    queryKey: ['ai-studio', 'drafts', projectId],
    queryFn: () => studioApi.listDraftDocs(projectId).then((r) => r.drafts),
  })
  const draftDocs = draftsQuery.data ?? []

  // Project-level commit (ACP-727): every doc with a draft is committed one
  // by one through the existing per-doc endpoint (old content → versions/,
  // draft records cleared). Sequential, not Promise.all: the store is plain
  // file I/O and a mid-list failure should leave the earlier commits done
  // rather than race partial writes. Afterwards the committed docs, both
  // history layers and the draft list are stale reads, so all refetch, and
  // commitRev re-mounts the open editors onto the committed baselines.
  const commitAll = useCallback(async () => {
    const work = draftDocs
    if (work.length === 0 || committing) return
    setCommitting(true)
    setCommitErr(null)
    try {
      for (const d of work) {
        await studioApi.saveDoc(projectId, d.name, d.content)
      }
      // The tabs must be re-pointed at the COMMITTED content, and the only
      // safe source is the refetch result itself: the `docs` this closure
      // captured is the pre-commit snapshot, and rewriting a tab from it
      // would silently roll the editor back to the pre-edit text.
      const [fresh] = await Promise.all([
        projectQuery.refetch(),
        draftsQuery.refetch(),
        queryClient.invalidateQueries({ queryKey: ['ai-studio', 'draft-versions', projectId] }),
        queryClient.invalidateQueries({ queryKey: ['ai-studio', 'versions', projectId] }),
      ])
      const freshDocs = fresh.data?.docs ?? []
      setTabs((ts) => ts.map((t) => {
        if (t.kind !== 'doc') return t
        const doc = freshDocs.find((x) => x.name === t.docName)
        return doc ? { ...t, initialContent: doc.content } : t
      }))
      setCommitRev((r) => r + 1)
    } catch (err) {
      setCommitErr(err instanceof Error ? err.message : String(err))
    } finally {
      setCommitting(false)
    }
  }, [draftDocs, committing, projectId, projectQuery, draftsQuery, queryClient])

  const resize = useCallback((side: 'left' | 'right', w: number) => {
    setWidths((cur) => {
      const next = { ...cur, [side]: clampW(w) }
      try { localStorage.setItem(LS_WIDTHS, JSON.stringify(next)) } catch { /* private mode */ }
      return next
    })
  }, [])

  const togglePane = useCallback((pane: keyof Hidden) => {
    setHidden((h) => {
      const next = { ...h, [pane]: !h[pane] }
      // Never let the last visible pane hide — an all-hidden shell has no way
      // back except a reload.
      if (next.left && next.center && next.right) return h
      try { localStorage.setItem(LS_HIDDEN, JSON.stringify(next)) } catch { /* private mode */ }
      return next
    })
  }, [])

  const openTab = useCallback((tab: WorkTab) => {
    setTabs((ts) => (ts.some((t) => t.id === tab.id) ? ts : [...ts, tab]))
    setActiveId(tab.id)
  }, [])
  const closeTab = useCallback((id: string) => {
    setTabs((ts) => {
      const next = ts.filter((t) => t.id !== id)
      setActiveId((cur) => (cur === id ? next[next.length - 1]?.id ?? null : cur))
      return next
    })
  }, [])

  const toggleBtns = useMemo(() => (
    <div className="flex items-center gap-1" role="group" aria-label={i18nT('apps.aiStudio.toggle_panes')}>
      <button
        type="button"
        className={paneToggleCls(!hidden.left)}
        aria-pressed={!hidden.left}
        title={i18nT('apps.aiStudio.toggle_chat')}
        onClick={() => togglePane('left')}
      >
        {hidden.left ? <PanelLeftOpen size={14} /> : <PanelLeftClose size={14} />}
      </button>
      <button
        type="button"
        className={paneToggleCls(!hidden.center)}
        aria-pressed={!hidden.center}
        title={i18nT('apps.aiStudio.toggle_workspace')}
        onClick={() => togglePane('center')}
      >
        <FolderKanban size={14} />
      </button>
      <button
        type="button"
        className={paneToggleCls(!hidden.right)}
        aria-pressed={!hidden.right}
        title={i18nT('apps.aiStudio.toggle_tools')}
        onClick={() => togglePane('right')}
      >
        {hidden.right ? <PanelRightOpen size={14} /> : <PanelRightClose size={14} />}
      </button>
    </div>
  ), [hidden, togglePane])

  if (projectQuery.isLoading) {
    return (
      <div className="h-full p-6" data-testid="ai-studio-loading">
        <ContentSkeleton rows={6} />
      </div>
    )
  }
  if (projectQuery.isError) {
    const gone = projectQuery.error instanceof StudioApiError && projectQuery.error.code === 'project_not_found'
    return (
      <div className="h-full p-6 flex flex-col gap-3 max-w-[560px]" data-testid="ai-studio-load-error">
        <ErrorNotice
          message={gone ? i18nT('apps.aiStudio.err_project_missing') : String(projectQuery.error?.message ?? projectQuery.error)}
          askAgent={false}
        />
        <Btn onClick={() => navigate('/ai-studio')}>
          <ArrowLeft size={14} className="lucide-inline" /> {i18nT('apps.aiStudio.back_to_projects')}
        </Btn>
      </div>
    )
  }
  const project = projectQuery.data!.project

  return (
    <div className="flex flex-col h-full min-h-0" data-testid="ai-studio">
      <header className="flex items-center gap-3 px-4 h-[44px] shrink-0 border-b border-border bg-card">
        <Btn onClick={() => navigate('/ai-studio')} title={i18nT('apps.aiStudio.back_to_projects')} aria-label={i18nT('apps.aiStudio.back_to_projects')}>
          <ArrowLeft size={14} className="lucide-inline" />
        </Btn>
        <span className="text-sm font-semibold text-text-strong">AI Studio</span>
        <span className="text-[13px] text-muted truncate max-w-[280px]" title={project.description || undefined}>
          {i18nT('apps.aiStudio.project_label')} · {project.name}
        </span>
        {toggleBtns}
        <span className="flex-1" />
        {/* Project-level commit (ACP-727): the commit feeds the whole
            project's requirements graph, so it lives here, not per editor.
            The badge names the docs a commit would promote. */}
        {draftDocs.length > 0 && (
          <span className="rounded-full bg-accent-subtle px-2 py-0.5 text-[11px] text-accent max-w-[280px] truncate" title={draftDocs.map((d) => d.name).join(', ')}>
            {i18nT('apps.aiStudio.drafts_pending')}: {draftDocs.map((d) => d.name).join(', ')}
          </span>
        )}
        <Btn
          primary
          onClick={commitAll}
          disabled={draftDocs.length === 0 || committing}
          title={i18nT('apps.aiStudio.commit_all_hint')}
        >
          <GitCommit size={13} className="lucide-inline" />
          {committing ? i18nT('apps.aiStudio.committing') : i18nT('apps.aiStudio.commit_all')}
        </Btn>
        <span className="rounded-full bg-bg-hover px-2 py-0.5 text-[11px] text-muted">
          {i18nT('apps.aiStudio.design_version')}: {DESIGN_VERSION}
        </span>
        <span className="rounded-full bg-bg-hover px-2 py-0.5 text-[11px] text-muted">
          {i18nT('apps.aiStudio.run_version')}: {RUN_VERSION}
        </span>
      </header>
      {commitErr && (
        <div className="px-4 pt-2 shrink-0">
          {/* askAgent off: the failing commit is re-runnable from this same
              bar, there is no buffer in here to hand off. */}
          <ErrorNotice message={commitErr} askAgent={false} onDismiss={() => setCommitErr(null)} />
        </div>
      )}

      <div className="flex flex-1 min-h-0">
        {!hidden.left && (
          <aside style={{ width: widths.left }} className="shrink-0 min-w-[180px] max-w-[55vw] flex flex-col min-h-0 border-r border-border bg-card">
            <AppScopedApiProvider
              appName="ai-studio"
              allowedApiPaths={['/api/chat']}
              navigateFn={navigateFn}
            >
              {/* one chat slot per project: the workbench context IS the
                  project, so a second project's chat must not share this
                  one's transcript (slots stay _app='ai-studio' either way) */}
              <ChatPane slotKey={`ai-studio-${projectId}`} />
            </AppScopedApiProvider>
          </aside>
        )}
        {!hidden.left && !hidden.center && (
          <Resizer side="left" startWidth={widths.left} onResize={(w) => resize('left', w)} />
        )}

        {!hidden.center && (
          <main className="flex-1 min-w-0 flex flex-col min-h-0 bg-bg">
            <WorkArea
              tabs={tabs}
              activeId={activeId}
              onSelect={setActiveId}
              onClose={closeTab}
              projectId={projectId}
              commitRev={commitRev}
            />
          </main>
        )}
        {!hidden.center && !hidden.right && (
          <Resizer side="right" startWidth={widths.right} onResize={(w) => resize('right', w)} invert />
        )}

        {!hidden.right && (
          <aside style={{ width: widths.right }} className="shrink-0 min-w-[240px] max-w-[55vw] flex flex-col min-h-0 border-l border-border bg-card">
            <ToolSidebar onOpenTab={openTab} docs={docs} />
          </aside>
        )}
      </div>
    </div>
  )
}

function paneToggleCls(active: boolean): string {
  return `inline-flex items-center justify-center w-7 h-7 rounded-md border border-border text-[13px] cursor-pointer transition-colors ${
    active ? 'bg-bg-hover text-text' : 'bg-transparent text-muted line-through decoration-1'
  }`
}

function Resizer({ side, startWidth, onResize, invert = false }: {
  side: 'left' | 'right'
  startWidth: number
  onResize: (w: number) => void
  invert?: boolean
}) {
  // Pin the width at pointer-down: re-reading the live prop mid-drag would
  // feed each committed width back in as the next drag's base, compounding
  // every delta onto the previous one (a runaway resize at 2x pointer speed).
  const baseRef = useRef(startWidth)
  baseRef.current = startWidth
  const originRef = useRef(startWidth)
  const latest = useRef({ onResize, invert })
  latest.current = { onResize, invert }
  const drag = usePointerDrag({
    threshold: 3,
    onStart: () => { originRef.current = baseRef.current },
    onMove: ({ dx }) => {
      const { onResize: cb, invert: inv } = latest.current
      cb(inv ? originRef.current - dx : originRef.current + dx)
    },
  })
  return (
    <div
      {...drag}
      role="separator"
      aria-orientation="vertical"
      aria-label={side === 'left' ? i18nT('apps.aiStudio.resize_chat') : i18nT('apps.aiStudio.resize_tools')}
      className="w-[7px] shrink-0 cursor-col-resize bg-bg-elevated hover:bg-accent-subtle transition-colors touch-none"
      data-testid={`resizer-${side}`}
    />
  )
}
