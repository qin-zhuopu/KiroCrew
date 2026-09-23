// AI Studio — a three-column coding-studio shell over Kiro Crew.
//
// This component is the app's whole route surface: the dashboard's catch-all
// (`/:builtinApp/*`) resolves every sub-path through the registry's
// `/workspaces` entry, so the split between the two views happens here by URL:
//   /workspaces                  → ProjectsListPage (list + create)
//   /workspaces/<id>/ai-studio   → StudioWorkspace (the workbench for one project)
// The pre-rename URLs redirect here — `/ai-studio` through a static route in
// App.tsx, `/projects/<id>/ai-studio` through ProjectsPage's legacy shim — so
// bookmarks and acceptance scripts keep landing on the right view.
//
// Workspace: left the native chat (ChatEmbed, real sessions — same embed
// contract the spec-builder uses), center a tabbed work area (docs / diffs /
// commits / graph / deploy logs), right the tool sidebar that opens tabs.
// Docs are the project's real files from /api/apps/ai-studio; the other tool
// tabs are still fixture-backed (fixtures.ts) until those APIs exist. Pane
// widths and visibility persist per app in localStorage.
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, FolderKanban, PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen } from 'lucide-react'
import { AppScopedApiProvider } from '../../app-sdk/scopedApi'
import ErrorNotice from '../../components/ErrorNotice'
import { Btn, ContentSkeleton } from '../../components/ui'
import { usePointerDrag } from '../../hooks/usePointerDrag'
import { i18nT } from '../../i18n/t'
import ChatPane from './ChatPane'
import ProjectCommitBar from './ProjectCommitBar'
import ProjectsListPage from './ProjectsListPage'
import RecentActivityFeed from './RecentActivityFeed'
import ToolSidebar from './ToolSidebar'
import WorkArea, { type WorkTab } from './WorkArea'
import { DESIGN_VERSION, RUN_VERSION } from './fixtures'
import { parseDemoScenario, STATE_DEMO_SCENARIO, createDemoApi } from './demo/runtime'
import { ALL_STATES, DEPLOY_PAYLOADS } from './demo/allStates'
import StatesDock from './demo/StatesDock'
import DeployFramePanel from './demo/DeployFramePanel'
import { createDemoPublishApi } from './demo/publishFake'
import { isReleaseState } from './demo/states-release'
import type { CommitStateSnapshot } from './demo/states-commit'
import type { StateSnapshot } from './demo/states'
import ReleaseJobPage from './ReleaseJobPage'
import DevRunPanel, { RunPreviewScreen } from './DevRunView'
import GraphView from './GraphView'
import DemoEntryButton from './DemoEntryButton'
import { studioApi, StudioApiError, type StudioDoc } from './studioApi'

// The demo surface (steps, fixtures, overlay, fake) loads ONLY on the
// `?demo=` route — an ordinary visit never pays its bundle cost.
const DemoWorkspace = lazy(() => import('./demo/DemoWorkspace'))

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

/** `/workspaces/<id>/ai-studio` → the id; anything else → the list. The id is
 * read off the pathname rather than nested <Route>s because the dashboard
 * mounts this page as one catch-all entry (see BuiltinAppRoute). The legacy
 * `/projects/<id>/ai-studio` URL is redirected by ProjectsPage before this
 * page is reached. */
const WORKSPACE_RE = /^\/workspaces\/([^/]+)\/ai-studio/

export default function AiStudioPage() {
  const location = useLocation()
  // `?demo=<scenario>` is the whole demo injection point (§4): the query is
  // read here and nowhere else in the app — no business component below
  // learns a demo exists.
  // ACP-793: one floating control, whose label and behaviour flip on `?demo=`
  // presence — the entry the owner could not find.
  const demo = parseDemoScenario(location.search)
  const match = location.pathname.match(WORKSPACE_RE)
  const projectId = match ? decodeURIComponent(match[1]) : null

  // ACP-794: the state-direct demo is a MODE of the real workbench, not a
  // sibling page. Same route, same already-loaded project, query-only switch —
  // which is the only shape that keeps `location.pathname` and the project id
  // intact (owner 口径) and re-reads nothing: `projectQuery` is keyed on the id,
  // and the id does not change here.
  if (demo && demo.scenario === STATE_DEMO_SCENARIO && projectId) {
    return (
      <>
        <StudioWorkspace projectId={projectId} demoStates />
        <DemoEntryButton demoTarget={location.pathname} />
      </>
    )
  }
  // the step-replay line (`?demo=<script name>`) keeps its own surface
  if (demo && demo.scenario !== STATE_DEMO_SCENARIO) {
    return (
      <>
        <Suspense fallback={<div className="h-full p-6"><ContentSkeleton rows={6} /></div>}>
          {/* keyed on the scenario: swapping `?demo=` remounts the runtime
           * from step 0 instead of leaving it mid-script on another line */}
          <DemoWorkspace key={demo.scenario} params={demo} />
        </Suspense>
        <DemoEntryButton demoTarget={location.pathname} />
      </>
    )
  }
  if (projectId) {
    return (
      <>
        <StudioWorkspace projectId={projectId} />
        <DemoEntryButton demoTarget={location.pathname} />
      </>
    )
  }
  return <ProjectsList />
}

/** The project list, plus the demo entry. The list carries no project page to
 * take over, so the button opens the demo on a REPRESENTATIVE project — the
 * first one, read from the same React Query cache `ProjectsListPage` already
 * fills (same key → one request, never a second one for the button). No
 * projects → nothing to demo → no button. */
function ProjectsList() {
  // The key is SHARED with `ProjectsListPage` (whoever mounts first answers it,
  // and the other observer reads the same cache entry), so the queryFn must
  // return the same SHAPE it does — the unwrapped array. Reading `.projects`
  // off this cache entry would be undefined the moment the page's observer
  // wins the race, which is silent: the button simply never appears.
  const projectsQuery = useQuery({
    queryKey: ['ai-studio', 'projects'],
    queryFn: () => studioApi.listProjects().then((r) => r.projects),
  })
  const first = projectsQuery.data?.[0]?.id
  return (
    <>
      <ProjectsListPage />
      <DemoEntryButton demoTarget={first ? `/workspaces/${encodeURIComponent(first)}/ai-studio` : undefined} />
    </>
  )
}

export function StudioWorkspace({ projectId, demoStates = false }: {
  projectId: string
  /** ACP-794: render this workbench as the state-direct demo (`?demo=states`)
   * — the SAME component tree, the same loaded project, driven by a frame's
   * snapshot instead of the store (see the demo block below). Default false:
   * every ordinary visit renders exactly the page it always has. */
  demoStates?: boolean
}) {
  const navigate = useNavigate()
  const location = useLocation()
  const queryClient = useQueryClient()
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

  // ---------------------------------------------------------------------
  // ACP-794 demo mode. Everything below this block is inert until `demoStates`
  // is on; when it is, this component renders the SAME columns, the same
  // sidebar and the same editors — fed by one frame's snapshot instead of the
  // store. The project read is deliberately NOT replaced: its query key is the
  // real id, which does not change when the demo opens, so the top bar keeps
  // the values this page already loaded and re-reads nothing (owner 口径:
  // 顶栏项目名/版本徽章沿用当前页面的值，不许发新请求).
  // ---------------------------------------------------------------------
  const [stateIndex, setStateIndex] = useState(0)
  const demoState = demoStates ? ALL_STATES[stateIndex] : null
  // one fake per frame, minted on the frame: a live write a presenter makes
  // belongs to the frame that made it and is gone on the next switch
  const demoApi = useMemo(() => (demoState ? createDemoApi(demoState.fixture) : null), [demoState])
  // The two frames that drive a SURFACE OF THEIR OWN rather than the center:
  // a 提交-tab frame lights the sidebar's commits tab and feeds its two lists,
  // a release frame lights the releases tab and feeds the publish reads. Both
  // are positive checks against the frame's own payload — the same doctrine
  // as `isReleaseState` — never "everything that is not the other one".
  const demoCommit = useMemo(() => (isCommitState(demoState) ? demoState : null), [demoState])
  const demoRelease = useMemo(
    () => (demoState && isReleaseState(demoState) ? demoState : null),
    [demoState],
  )
  const demoPublishApi = useMemo(
    () => (demoRelease ? createDemoPublishApi(demoRelease.publish) : null),
    [demoRelease],
  )
  const [demoActiveId, setDemoActiveId] = useState<string | null>(null)
  const [demoExtraTabs, setDemoExtraTabs] = useState<WorkTab[]>([])
  // scopes the R3 click below to THIS workbench (never a sibling on screen)
  const rootRef = useRef<HTMLDivElement>(null)

  // R3's one act (ACP-791 wiring note 2): 「发布中」 is PublishVersionList's
  // LOCAL run state — no snapshot paints it — so the frame that declares
  // `inFlight` performs the ONE real click on that row's real 发布 button once
  // it renders. The fake trigger never settles, so the row honestly rests at
  // 发布中 instead of an outcome this frame does not carry (the finished run
  // is R4's frame). One act per frame, not a replay chain.
  const inFlightVersion = demoRelease?.publish.inFlight?.version ?? null
  useEffect(() => {
    if (!inFlightVersion) return
    let tries = 0
    const timer = setInterval(() => {
      const btn = rootRef.current?.querySelector<HTMLButtonElement>(
        `[data-testid="ai-studio-publish-btn-${inFlightVersion}"]`,
      )
      if (btn && !btn.disabled) {
        clearInterval(timer)
        btn.click()
        return
      }
      if (++tries > 120) clearInterval(timer) // the button never came: stay put
    }, 25)
    return () => clearInterval(timer)
  }, [inFlightVersion, stateIndex])

  // A frame switch is a wholesale reload: every ai-studio read is stale by
  // construction (the fake that answered it is gone). The PROJECT key is
  // spared on purpose — dropping it would re-issue the request this mode
  // promises not to make.
  useEffect(() => {
    if (!demoStates) return
    queryClient.removeQueries({
      predicate: (q) => q.queryKey[0] === 'ai-studio' && q.queryKey[1] !== 'project',
    })
    setDemoActiveId(null)
    setDemoExtraTabs([])
  }, [demoStates, stateIndex, queryClient])

  const projectQuery = useQuery({
    queryKey: ['ai-studio', 'project', projectId],
    queryFn: () => studioApi.getProject(projectId),
    // in the demo the project read is a CACHE read, never a request: a deep
    // link straight into `?demo=states` has nothing cached, and asking would
    // both fetch in demo mode and hit the `?demo=` guard's throw
    enabled: !demoStates,
  })
  const docs: StudioDoc[] = projectQuery.data?.docs ?? []

  // the recent-activity feed (ACP-754): in the ordinary workbench the honest
  // feed is what the store itself reports — the project's drafted docs. The
  // commit bar already runs that drafts read, so it reports the names up
  // (onDraftsSeen) rather than this view opening a SECOND query — one read,
  // one network call, no second observer to perturb the fetch count. Nothing
  // drafted → the feed shows its empty state; no new endpoint, no invented
  // activity.
  const [draftedNames, setDraftedNames] = useState<string[]>([])
  const activity = useMemo(
    () => draftedNames.map((name) => ({ label: `${i18nT('apps.aiStudio.drafts_pending')}: ${name}` })),
    [draftedNames],
  )
  const onDraftsSeen = useCallback((names: string[]) => setDraftedNames(names), [])

  // The commit itself lives in ProjectCommitBar (shared with the demo
  // workbench); this side owns what a landing commit does to the tabs:
  // re-point each open doc tab at its committed content and bump the rev so
  // the editors re-mount onto it.
  const onDocCommitted = useCallback((freshDocs: StudioDoc[]) => {
    setTabs((ts) => ts.map((t) => {
      if (t.kind !== 'doc') return t
      const doc = freshDocs.find((x) => x.name === t.docName)
      return doc ? { ...t, initialContent: doc.content } : t
    }))
    setCommitRev((r) => r + 1)
  }, [])

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

  // The demo's open doc tab, derived from the frame: the committed content is
  // the editor's baseline and `initialDraft` is the frame's workspace buffer,
  // so 「有未提交修改」 arrives through the real component's own `dirty` rule
  // rather than a look-alike panel. `diffOpen` / `versionsOpen` are the two
  // frames whose headline IS a popover (当前 Diff / 版本历史).
  const demoTabs: WorkTab[] = useMemo(() => {
    if (!demoState) return []
    const docName = demoState.selectedDoc
    if (!docName || demoState.activeSurface === 'list') return []
    const committed = demoState.fixture.docs.find((d) => d.name === docName)?.content ?? demoState.baseline
    return [{
      id: `demo-${demoState.id}-${docName}`,
      kind: 'doc',
      title: docName,
      docName,
      initialContent: committed,
      initialDraft: demoState.dirty && demoState.buffer !== committed ? demoState.buffer : undefined,
      diffOpen: demoState.activeSurface === 'diff',
      versionsOpen: demoState.activeSurface === 'versionHistory',
    }]
  }, [demoState])

  // In demo mode the sidebar's doc list is real and clickable: opening a doc
  // from it adds an ordinary tab, backed by the same frame fake.
  const shownTabs = demoStates ? [...demoTabs, ...demoExtraTabs] : tabs
  const shownActiveId = demoStates ? (demoActiveId ?? demoTabs[0]?.id ?? null) : activeId
  const shownApi = demoStates ? (demoApi ?? undefined) : undefined
  const onShownSelect = demoStates ? setDemoActiveId : setActiveId
  const onShownClose = demoStates
    ? (id: string) => {
      setDemoExtraTabs((ts) => ts.filter((t) => t.id !== id))
      setDemoActiveId(null)
    }
    : closeTab
  const onShownOpen = demoStates
    ? (tab: WorkTab) => {
      setDemoExtraTabs((ts) => (ts.some((t) => t.id === tab.id) ? ts : [...ts, tab]))
      setDemoActiveId(tab.id)
    }
    : openTab

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

  if (!demoStates && projectQuery.isLoading) {
    return (
      <div className="h-full p-6" data-testid="ai-studio-loading">
        <ContentSkeleton rows={6} />
      </div>
    )
  }
  if (!demoStates && projectQuery.isError) {
    const gone = projectQuery.error instanceof StudioApiError && projectQuery.error.code === 'project_not_found'
    return (
      <div className="h-full p-6 flex flex-col gap-3 max-w-[560px]" data-testid="ai-studio-load-error">
        <ErrorNotice
          message={gone ? i18nT('apps.aiStudio.err_project_missing') : String(projectQuery.error?.message ?? projectQuery.error)}
          askAgent={false}
        />
        <Btn onClick={() => navigate('/workspaces')}>
          <ArrowLeft size={14} className="lucide-inline" /> {i18nT('apps.aiStudio.back_to_projects')}
        </Btn>
      </div>
    )
  }
  // In the demo this is the already-loaded project (owner 口径); the URL id is
  // the honest fallback for a deep link that arrived with nothing cached.
  const project = projectQuery.data?.project
    ?? { id: projectId, name: projectId, description: '', createdAt: 0 }

  return (
    <div
      ref={rootRef}
      className="flex flex-col h-full min-h-0"
      data-testid="ai-studio"
      data-demo-states={demoStates ? STATE_DEMO_SCENARIO : undefined}
    >
      <header className="flex items-center gap-3 px-4 h-[44px] shrink-0 border-b border-border bg-card">
        <Btn onClick={() => navigate('/workspaces')} title={i18nT('apps.aiStudio.back_to_projects')} aria-label={i18nT('apps.aiStudio.back_to_projects')}>
          <ArrowLeft size={14} className="lucide-inline" />
        </Btn>
        <span className="text-sm font-semibold text-text-strong">AI Studio</span>
        <span className="text-[13px] text-muted truncate max-w-[280px]" title={project.description || undefined}>
          {i18nT('apps.aiStudio.project_label')} · {project.name}
        </span>
        {toggleBtns}
        <span className="flex-1" />
        {/* Project-level commit (ACP-727): the shared bar owns the badge,
            the button and the commit run; this header just places it. */}
        <div className="relative flex items-center gap-2">
          {/* keyed on the frame: its drafts read is cached under a key that
              carries only the project id, so without a remount a switch would
              serve the PREVIOUS frame's draft list */}
          <ProjectCommitBar
            key={demoState?.id ?? 'real'}
            projectId={projectId}
            api={demoApi ?? undefined}
            onCommitted={onDocCommitted}
            onDraftsSeen={demoStates ? undefined : onDraftsSeen}
          />
        </div>
        <span className="rounded-full bg-bg-hover px-2 py-0.5 text-[11px] text-muted">
          {i18nT('apps.aiStudio.design_version')}: {DESIGN_VERSION}
        </span>
        <span className="rounded-full bg-bg-hover px-2 py-0.5 text-[11px] text-muted">
          {i18nT('apps.aiStudio.run_version')}: {RUN_VERSION}
        </span>
      </header>
      {/* the recent-activity feed, the same component the demo workbench
       * mounts (ACP-754) — the hook exists on both surfaces, fed by data
       * each surface honestly holds */}
      <RecentActivityFeed items={demoState ? demoState.fixture.recentActivity : activity} />

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
            <div className="flex-1 min-h-0">
              <WorkArea
                tabs={shownTabs}
                activeId={shownActiveId}
                onSelect={onShownSelect}
                onClose={onShownClose}
                projectId={projectId}
                api={shownApi}
                commitRev={commitRev}
              />
            </div>
            {/* The later-phase frames' payoff panels (ACP-794): a frame whose
              * story IS the graph / the dev run / the deployment renders the
              * REAL component for it under the editor, exactly where the
              * replay surface mounts them. Snapshot-driven: a panel exists
              * only where the loaded frame carries its payload. */}
            {demoState?.activeSurface === 'graph' && demoState.fixture.graph && (
              <div className="shrink-0 max-h-[300px] overflow-auto border-t border-border bg-bg">
                <GraphView
                  graph={demoState.fixture.graph}
                  addedNodeIds={demoState.fixture.graphDelta?.nodes}
                  addedEdges={demoState.fixture.graphDelta?.edges}
                  modifiedNodeIds={demoState.fixture.graphDelta?.modified}
                  removedNodeIds={demoState.fixture.graphDelta?.removed}
                />
              </div>
            )}
            {demoState?.activeSurface === 'dev' && demoState.fixture.devRun && (
              <div className="shrink-0 max-h-[340px] overflow-auto border-t border-border bg-bg">
                <DevRunPanel run={demoState.fixture.devRun} />
              </div>
            )}
            {demoState && DEPLOY_PAYLOADS[demoState.id] && (
              <div className="shrink-0 max-h-[420px] overflow-auto border-t border-border bg-bg">
                <DeployFramePanel frame={DEPLOY_PAYLOADS[demoState.id]} />
              </div>
            )}
            {/* R5's payoff: the release-job page itself, mounted with the
              * frame's own project/job/api/log-tail (it reads route params and
              * streams over SSE on every ordinary visit — inside the demo
              * there is no such route and no stream, so all four are injected;
              * each one defaults to exactly what a real visit uses). */}
            {demoRelease?.publish.selectedJobId && demoPublishApi && (
              <div className="shrink-0 h-[420px] overflow-hidden border-t border-border bg-bg">
                <ReleaseJobPage
                  projectId={projectId}
                  jobId={demoRelease.publish.selectedJobId}
                  api={demoPublishApi}
                  logFrames={demoRelease.publish.logFrames}
                />
              </div>
            )}
          </main>
        )}
        {!hidden.center && !hidden.right && (
          <Resizer side="right" startWidth={widths.right} onResize={(w) => resize('right', w)} invert />
        )}

        {!hidden.right && (
          <aside style={{ width: widths.right }} className="shrink-0 min-w-[240px] max-w-[55vw] flex flex-col min-h-0 border-l border-border bg-card">
            {/* keyed on the frame: the lit tab is LOCAL state, so a switch
                must re-mount onto the new frame's tab (and the ordinary
                workbench keeps its stable 'real' key, unchanged) */}
            <ToolSidebar
              key={demoState?.id ?? 'real'}
              onOpenTab={onShownOpen}
              docs={demoState ? demoState.fixture.docs : docs}
              projectId={projectId}
              initialTool={demoRelease ? 'releases' : demoCommit ? 'commits' : 'docs'}
              changed={demoCommit?.changed}
              commits={demoCommit?.commits}
              publishApi={demoPublishApi ?? undefined}
              // ACP-798: 本版修改过的文件 rides the frame's own payload — the
              // releases tab reads the version history AND this version's
              // changed files (each with its 图谱拆解状态) from one frame.
              releaseFiles={demoRelease?.publish.files}
              // ACP-798 (owner 追加): the 发版 tab carries its own 发版 button
              // at the top — the frame names the version it fires; the
              // component's own hash rule decides whether it is live.
              releaseAction={demoRelease?.publish.releaseAction}
            />
          </aside>
        )}
      </div>

      {/* the runnable experience (V3): an internal overlay onto the frame's own
        * runPreview data — no server, no container */}
      {demoState?.fixture.runPreview && <RunPreviewScreen preview={demoState.fixture.runPreview} />}
      {/* R6: the release frames carry their experience screen on the publish
        * payload (the dev-phase frames carry theirs on the fixture) */}
      {demoRelease?.publish.runPreview && <RunPreviewScreen preview={demoRelease.publish.runPreview} />}

      {demoState && (
        <StatesDock
          index={stateIndex}
          onSelect={setStateIndex}
          onPrev={() => setStateIndex((i) => Math.max(0, i - 1))}
          onNext={() => setStateIndex((i) => Math.min(ALL_STATES.length - 1, i + 1))}
          onClose={() => {
            const params = new URLSearchParams(location.search)
            params.delete('demo')
            const qs = params.toString()
            navigate(qs ? `${location.pathname}?${qs}` : location.pathname)
          }}
        />
      )}
    </div>
  )
}

/** Positive identity for a 提交-tab frame (same doctrine as `isReleaseState`):
 * the frame IS one by carrying the lit sidebar tab, never by being "not a
 * release frame". Null-safe because the caller holds "no frame at all" too. */
function isCommitState(s: StateSnapshot | null): s is CommitStateSnapshot {
  return s !== null && 'activeSidebarTab' in s
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
