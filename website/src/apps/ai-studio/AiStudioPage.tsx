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
import DevServerControl from './DevServerControl'
import DevLoopPanel from './DevLoopPanel'
import GraphLoopPanel from './GraphLoopPanel'
import ProjectsListPage from './ProjectsListPage'
import RecentActivityFeed from './RecentActivityFeed'
import ToolSidebar, { type ToolTabInjection } from './ToolSidebar'
import ReleaseControl from './ReleaseControl'
import WorkArea, { type WorkTab } from './WorkArea'
import { DESIGN_VERSION, RUN_VERSION } from './fixtures'
import { parseDemoScenario, STATE_DEMO_SCENARIO, createDemoApi } from './demo/runtime'
import { ALL_STATES, DEPLOY_PAYLOADS } from './demo/allStates'
import StatesDock from './demo/StatesDock'
import DeployFramePanel from './demo/DeployFramePanel'
import { createDemoPublishApi } from './demo/publishFake'
import { isReleaseState } from './demo/states-release'
import { isDevDeployState } from './demo/states-devdeploy'
import type { CommitStateSnapshot } from './demo/states-commit'
import type { GraphStateSnapshot } from './demo/states-graph'
import type { StateSnapshot } from './demo/states'
import ReleaseJobPage from './ReleaseJobPage'
import DevRunPanel, { RunPreviewScreen } from './DevRunView'
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
  // The frame's own top button (开发 / 部署) does what it says: the act it names
  // IS the next frame of the same story, so pressing it lands that frame. Only
  // the first frame of each group ships a live button (`actionDisabled: false`);
  // a frame whose act already landed ships a disabled one — never a live no-op.
  const landFrameAct = useCallback(async () => {
    setStateIndex((i) => Math.min(ALL_STATES.length - 1, i + 1))
  }, [])
  // 试运行 (V3): opened by 打开可运行版本 and closed by its own 关闭 button. It
  // never arrives WITH the frame — the middle column is a document and stays one
  // until the presenter asks for the experience screen.
  const [runPreviewOpen, setRunPreviewOpen] = useState(false)
  // The two frames that drive a SURFACE OF THEIR OWN rather than the center:
  // a 提交-tab frame lights the sidebar's commits tab and feeds its two lists,
  // a release frame lights the releases tab and feeds the publish reads. Both
  // are positive checks against the frame's own payload — the same doctrine
  // as `isReleaseState` — never "everything that is not the other one".
  const demoCommit = useMemo(() => (isCommitState(demoState) ? demoState : null), [demoState])
  // A graph frame (ACP-797) is the same kind of surface frame: it lights the
  // 需求图谱 tab and hands it the frame's own list + generation run. Its
  // identity is CARRYING `graphEntries` (the slice's stated rule) rather than a
  // shared tab field, so D7 — the design phase's 图谱修订, which carries them
  // too — lights that tab as well, exactly as it should.
  const demoGraph = useMemo(() => (isGraphState(demoState) ? demoState : null), [demoState])
  const demoRelease = useMemo(
    () => (demoState && isReleaseState(demoState) ? demoState : null),
    [demoState],
  )
  // A dev/deploy frame (ACP-803) is the LAST of that kind: its subject is
  // observed in the 开发 / 部署 tab of the sidebar (owner's rule — 中间列只放
  // 文字内容), so the frame names the tab, that tab's 历史记录, and its own
  // top action button's state. `activeSidebarTab` is the commit pair's field
  // NAME — both slices declare it — so the identity test is on its VALUE
  // ('dev' / 'deploy'), never on the field's mere presence; a 提交 frame keeps
  // its own tab, and neither guard can claim the other's frames.
  const demoDevDeploy = useMemo(
    () => (demoState && isDevDeployState(demoState) ? demoState : null),
    [demoState],
  )
  const demoPublishApi = useMemo(
    () => (demoRelease ? createDemoPublishApi(demoRelease.publish) : null),
    [demoRelease],
  )
  // The dev/deploy frames' 过程区 and their top button, as NODES (ACP-803).
  // ToolSidebar owns the shape (过程 above, 历史记录 below) and never learns a
  // demo exists; the demo hands in the REAL components — DevRunPanel /
  // DeployFramePanel / ReleaseControl — so each picture has one implementation.
  // Absent injection (every other frame, and the ordinary workbench) => those
  // two tabs render today's fixtures, byte for byte.
  const demoDevTab = useMemo<ToolTabInjection | undefined>(() => {
    const run = demoDevDeploy?.fixture.devRun
    if (!demoDevDeploy || demoDevDeploy.activeSidebarTab !== 'dev' || !run) return undefined
    const preview = demoDevDeploy.fixture.runPreview
    return {
      action: <ReleaseControl act="dev" disabled={demoDevDeploy.actionDisabled} onRelease={landFrameAct} />,
      current: (
        <DevRunPanel
          run={run}
          // 试运行 opens from the panel's own entry, never by arriving at the
          // frame: the middle column is a document and stays one until asked.
          onOpenRun={preview ? () => setRunPreviewOpen(true) : undefined}
        />
      ),
      history: demoDevDeploy.history,
    }
  }, [demoDevDeploy, landFrameAct])
  const demoDeployTab = useMemo<ToolTabInjection | undefined>(() => {
    if (!demoDevDeploy || demoDevDeploy.activeSidebarTab !== 'deploy') return undefined
    const frame = DEPLOY_PAYLOADS[demoDevDeploy.id]
    if (!frame) return undefined
    return {
      action: <ReleaseControl act="deploy" disabled={demoDevDeploy.actionDisabled} onRelease={landFrameAct} />,
      current: <DeployFramePanel frame={frame} />,
      history: demoDevDeploy.history,
    }
  }, [demoDevDeploy, landFrameAct])
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
    setRunPreviewOpen(false)
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
  // feed is what the store itself reports — the project's drafted docs.
  //
  // The read is HERE, not in the commit bar, since ACP-801 moved that bar into
  // the sidebar's 提交 tab: a bar that mounts only when that tab is open cannot
  // be the feed's source (the feed would go empty until someone opened a tab
  // that has nothing to do with it). It is the SAME query key the bar asks for,
  // so opening the tab shares this cache entry rather than issuing a second
  // request — one read, one network call, exactly as before.
  const draftsQuery = useQuery({
    queryKey: ['ai-studio', 'drafts', projectId],
    queryFn: () => studioApi.listDraftDocs(projectId).then((r) => r.drafts),
    // the demo's frames carry their own activity list; asking here would both
    // fetch in demo mode and hit the `?demo=` guard's throw
    enabled: !demoStates,
  })
  // T7 (ACP-851): the live requirement graph for the 需求图谱 tab. Same rule
  // as every other real read here — never asked in demo mode (a frame feeds
  // its own snapshot list instead). A failed or empty read leaves the tab on
  // its fixture drill-down: the graph tab degrades to what it was, it does
  // not go blank.
  const graphQuery = useQuery({
    queryKey: ['ai-studio', 'graph'],
    queryFn: () => studioApi.getGraph(),
    enabled: !demoStates,
  })
  const realGraph = graphQuery.data?.graph
  // T7 (ACP-851): the 需求图谱 tab's loop reads — the frozen baselines and
  // the distillation runs the store actually holds. Same rule as every real
  // read: never asked in demo mode (a frame carries its own snapshot states).
  const freezesQuery = useQuery({
    queryKey: ['ai-studio', 'freezes', projectId],
    queryFn: () => studioApi.listFreezes(projectId).then((r) => r.freezes),
    enabled: !demoStates,
  })
  const distillsQuery = useQuery({
    queryKey: ['ai-studio', 'distills', projectId],
    queryFn: () => studioApi.listDistills(projectId).then((r) => r.distillations),
    enabled: !demoStates,
  })
  // T7 step 4: the gate-driven dev runs this project has recorded
  const devRunsQuery = useQuery({
    queryKey: ['ai-studio', 'dev-runs', projectId],
    queryFn: () => studioApi.listDevRuns(projectId).then((r) => r.runs),
    enabled: !demoStates,
  })
  // one place decides what a landed act re-reads: the loop's own lists, plus
  // the drafts (a regen lands as a draft) and the doc list it edits
  const onLoopActed = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['ai-studio', 'freezes', projectId] })
    queryClient.invalidateQueries({ queryKey: ['ai-studio', 'distills', projectId] })
    queryClient.invalidateQueries({ queryKey: ['ai-studio', 'drafts', projectId] })
    queryClient.invalidateQueries({ queryKey: ['ai-studio', 'project', projectId] })
  }, [queryClient, projectId])
  // the loop acts on the canonical requirement doc the project is seeded
  // with; the doc list is its source of truth for the name when it changes
  const loopDocName = docs.some((d) => d.name === 'requirements.md')
    ? 'requirements.md'
    : docs[0]?.name ?? 'requirements.md'
  const draftedNames = useMemo(() => (draftsQuery.data ?? []).map((d) => d.name), [draftsQuery.data])
  const activity = useMemo(
    () => draftedNames.map((name) => ({ label: `${i18nT('apps.aiStudio.drafts_pending')}: ${name}` })),
    [draftedNames],
  )

  // The commit itself lives in ProjectCommitBar (shared with the demo
  // workbench, and since ACP-801 placed at the top of the sidebar's 提交 tab);
  // this side owns what a landing commit does to the tabs: re-point each open
  // doc tab at its committed content and bump the rev so the editors re-mount
  // onto it.
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
        {/* The project-level commit is NOT here (owner, ACP-801): 提交全部 acts on
            the 提交 stage, so the button lives at the top of the sidebar's 提交 tab
            (ToolSidebar → CommitsTool) and the header keeps only what the page
            itself is — its project and its two version badges. The bar is still
            the one `ProjectCommitBar`; the sidebar is handed its inputs below. */}
        <span className="rounded-full bg-bg-hover px-2 py-0.5 text-[11px] text-muted">
          {i18nT('apps.aiStudio.design_version')}: {DESIGN_VERSION}
        </span>
        <span className="rounded-full bg-bg-hover px-2 py-0.5 text-[11px] text-muted">
          {i18nT('apps.aiStudio.run_version')}: {RUN_VERSION}
        </span>
        {/* ACP-2060: the dev-server control sits at the right end of the bar
            because it is the one piece of bar state that is about the HOST, not
            about the project's documents. Absent in the demo: a snapshot spawns
            no processes and owns no ports, and the frames are frozen copy. */}
        {!demoStates && <DevServerControl projectId={projectId} />}
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
            {/* The later-phase frames' payoff panels (ACP-794) — and, since
              * ACP-803, the reason there are none left here.
              *
              * The rule the owner restated is 「中间列只放文字内容，其余一切都
              * 在右边工具边栏对应页签里」: the graph moved to the 需求图谱 tab
              * (ACP-797), the dev run and the deployment to the 开发 / 部署 tabs
              * (ACP-799's seam, wired in ACP-803) — and each time the center
              * branch went with it rather than staying as a second, unreachable
              * home. This column is the open document now, for every frame; a
              * panel left here would be a second place the same fact is read,
              * which is exactly what the rule forbids. (The release-job page
              * below is not a leftover: its frame's payoff IS the page itself.) */}
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
              initialTool={
                demoDevDeploy ? demoDevDeploy.activeSidebarTab
                  : demoGraph ? 'graph' : demoRelease ? 'releases' : demoCommit ? 'commits'
                    // a frame that names no tab keeps 文档 explicitly rather than
                    // riding the component's default: ACP-2015 step 2 moved that
                    // default to 需求, and a demo frame has no workspace repo, so
                    // inheriting it would have every design frame open on 「this
                    // workspace has no requirement graphs」. The ORDINARY
                    // workbench (no frame) passes undefined and gets the new
                    // default — the first screen a real project answers is its
                    // readiness verdict.
                    : demoState ? 'docs' : undefined
              }
              changed={demoCommit?.changed}
              commits={demoCommit?.commits}
              publishApi={demoPublishApi ?? undefined}
// the graph frame's own list + generation run: the tab renders
              // the shipped DistillPanel above the grouped entries, so the
              // process and the artifact are both observed where the owner's
              // rule puts them — in the tab, never in the middle column
              graphEntries={demoGraph?.graphEntries}
              distillation={demoGraph?.distillation}
              realGraph={demoStates ? undefined : realGraph}
              // T7: the real loop's 沉淀/冻结/重生成 row, placed at the top of
              // the graph tab. Only the ordinary workbench gets it — a demo
              // frame's actions are snapshot data, and a button that hits the
              // `?demo=` guard would be a button that lies.
              graphLoop={demoStates ? undefined : (
                <GraphLoopPanel
                  projectId={projectId}
                  docName={loopDocName}
                  api={studioApi}
                  initialFreezes={freezesQuery.data ?? []}
                  initialDistills={distillsQuery.data ?? []}
                  onActed={onLoopActed}
                />
              )}
              // ACP-798: 本版修改过的文件 rides the frame's own payload — the
              // releases tab reads the version history AND this version's
              // changed files (each with its 图谱拆解状态) from one frame.
              releaseFiles={demoRelease?.publish.files}
              // ACP-798 (owner 追加): the 发版 tab carries its own 发版 button
              // at the top — the frame names the version it fires; the
              // component's own hash rule decides whether it is live.
              releaseAction={demoRelease?.publish.releaseAction}
              // ACP-803: the dev/deploy frames' own two tabs. The frame names
              // the tab and hands in its 过程区, its top button and its 历史记录;
              // a frame of any other slice passes neither, and those two tabs
              // then render the shipped DEV / DEPLOYMENTS fixtures unchanged.
              dev={demoDevTab}
              // T7 step 4: the real 开发 tab — 开始开发 runs the four phases
              // as bgdd gate stages through the backend. Real workbench only
              // (a demo frame passes `dev` instead, and its fake throws on
              // the real calls anyway).
              devLoop={demoStates ? undefined : (
                <DevLoopPanel
                  projectId={projectId}
                  api={studioApi}
                  initialRuns={devRunsQuery.data ?? []}
                  // the round's design version is the FROZEN one the graph
                  // loop pinned (or the round's default until a baseline
                  // exists) — a dev run builds a design, not a hope
                  designVersion={freezesQuery.data?.[0]?.version ?? 'v1'}
                  onRan={() => queryClient.invalidateQueries({ queryKey: ['ai-studio', 'dev-runs', projectId] })}
                />
              )}
              deploy={demoDeployTab}
              // the 提交 tab's action button (ACP-801) — the same bar the header
              // used to place, with the same wiring: the frame's fake as its
              // data source, and a key so a frame switch remounts it onto that
              // frame's draft list instead of serving the previous one's
              commitApi={shownApi}
              commitKey={demoState?.id ?? 'real'}
              // ACP-2015 step 2: the 需求 tab's workspace read. The frame's
              // snapshot fake answers with an empty list (a demo frame has no
              // workspace repo), the ordinary workbench reads the real client.
              requirementApi={shownApi}
              onCommitted={onDocCommitted}
              // no onDraftsSeen: the feed reads the drafts query this page owns
              // (same key as the bar's, so the bar opening shares that read
              // rather than adding one), and a second reporter would only be a
              // second writer to the same list
            />
          </aside>
        )}
      </div>

      {/* the runnable experience (V3): an internal overlay onto the frame's own
        * runPreview data — no server, no container. ACP-803: it opens ONLY on
        * the 开发 tab panel's own 打开可运行版本 press and closes on its own
        * 关闭 button — arriving at the frame never covers the middle column
        * (the owner's 「中间列只放文字」 rule extended to the overlay). */}
      {runPreviewOpen && demoState?.fixture.runPreview && (
        <RunPreviewScreen
          preview={demoState.fixture.runPreview}
          onClose={() => setRunPreviewOpen(false)}
        />
      )}
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
 * the frame IS one by naming 'commits' as its lit sidebar tab, never by being
 * "not a release frame". The value, not the field's presence: the dev/deploy
 * slice (ACP-803) declares the SAME field name for its own two tabs, so a
 * presence test would claim V/P frames as 提交 frames too. Null-safe because
 * the caller holds "no frame at all" too. */
function isCommitState(s: StateSnapshot | null): s is CommitStateSnapshot {
  return s !== null
    && (s as { activeSidebarTab?: unknown }).activeSidebarTab === 'commits'
}

/** A graph frame, by the same rule the slice states: it CARRIES the tab's
 * entries. (`states-graph.ts` deliberately did not reuse `activeSidebarTab`
 * for this — that field is the commit pair's identity and the guard above
 * tests it by name, so a second value on it would light 提交 on D7.) */
function isGraphState(s: StateSnapshot | null): s is GraphStateSnapshot {
  return s !== null && 'graphEntries' in s
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
