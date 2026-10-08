// Tests for the app's route surface and the workbench shell: /workspaces lands
// on the project list (empty state + new-project dialog), /workspaces/<id>/ai-studio
// lands on the three-column workbench whose header names the project,
// its Docs tool lists the project's real files, and opening one lands a
// closable tab. ChatEmbed is stubbed (it opens a WebSocket the test
// environment neither serves nor needs); studioApi is stubbed so no fetch
// leaves the test. UI strings assert the English catalog (tests pin en);
// project/doc content is Chinese by design and asserted as data.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../../app-sdk/ChatEmbed', () => ({
  default: () => <div data-testid="chat-embed-stub" />,
}))

// ChatPane opens its chat slot via the scoped api before mounting the embed;
// stub the barrel's hook so no fetch leaves the test (AppScopedApiProvider is
// imported from the scopedApi path directly, so the provider itself stays).
const fakeApi = vi.hoisted(() => ({ api: null as unknown }))
vi.mock('../../app-sdk', async () => {
  const actual = await vi.importActual('../../app-sdk')
  return { ...actual, useAppApi: () => fakeApi.api }
})
fakeApi.api = { post: vi.fn(async () => ({ key: 'x' })) }

const api = vi.hoisted(() => ({
  listProjects: vi.fn(),
  createProject: vi.fn(),
  getProject: vi.fn(),
  saveDoc: vi.fn(),
  saveDraft: vi.fn(async () => ({ ok: true })),
  listDraftDocs: vi.fn(async () => ({ drafts: [] as unknown[] })),
  listDraftVersions: vi.fn(async () => ({ versions: [] })),
  listVersions: vi.fn(async () => ({ versions: [] })),
  getGraph: vi.fn(async () => ({ graphId: 'none', graph: { nodes: [], edges: [] } })),
  listFreezes: vi.fn(async () => ({ freezes: [] })),
  listDistills: vi.fn(async () => ({ distillations: [] })),
  distill: vi.fn(async () => ({ distillation: { id: 'd1', releaseVersion: 'v1', status: 'done', candidates: [] } })),
  freeze: vi.fn(async () => ({ freeze: { version: 'v1', docName: 'requirements.md', generatedFrom: 'd1', time: 1, notes: '' } })),
  regen: vi.fn(async () => ({ doc: 'requirements.md', content: '# x', generatedFrom: 'd1' })),
  startDevRun: vi.fn(async () => ({
    run: { id: 'dev-1', designVersion: 'v1', phases: [], artifacts: [] },
  })),
  listDevRuns: vi.fn(async () => ({ runs: [] })),
  // ACP-2015 step 2: 需求 is the sidebar's default tab, so every workbench mount
  // runs the requirement list read; this project has no graphs.
  listRequirements: vi.fn(async () => ({ pages: [] })),
  getRequirement: vi.fn(async () => { throw new Error('unused') }),
}))
vi.mock('./studioApi', async () => {
  const actual = await vi.importActual('./studioApi')
  return { ...actual, studioApi: api }
})

import AiStudioPage from './AiStudioPage'
import { TEST_DOCS, TEST_PROJECT } from './testUtils'

beforeEach(() => {
  vi.clearAllMocks()
  // the pane-toggle test hides the tool sidebar and the component persists
  // that to localStorage; without this clear the NEXT test in this file would
  // mount with the sidebar hidden and never reach the 提交 tab
  window.localStorage.clear()
  api.getProject.mockResolvedValue({ project: TEST_PROJECT, docs: TEST_DOCS })
  api.listProjects.mockResolvedValue({ projects: [TEST_PROJECT] })
  // clearAllMocks does not drop a mockResolvedValue a test set, so the
  // no-drafts default is re-armed per test (the commit tests override it).
  api.listDraftDocs.mockResolvedValue({ drafts: [] })
})

function renderAt(entry: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[entry]}>
        <AiStudioPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('route dispatch', () => {
  it('/workspaces renders the project list with its cards', async () => {
    renderAt('/workspaces')
    expect(await screen.findByTestId('ai-studio-projects')).toBeInTheDocument()
    expect(await screen.findByText('测试项目')).toBeInTheDocument()
    expect(screen.queryByTestId('ai-studio')).not.toBeInTheDocument()
  })

  it('/workspaces/<id>/ai-studio renders the workbench and names the project', async () => {
    renderAt('/workspaces/p1/ai-studio')
    expect(await screen.findByTestId('ai-studio')).toBeInTheDocument()
    // the header shows the fetched project's name, not a hardcoded demo
    expect(screen.getByText(/测试项目/)).toBeInTheDocument()
    // no demo surface is on screen. (This used to read `queryByText(/Demo/)`,
    // which stopped being true once ACP-793 added the 「Demo」 entry button to
    // the workbench — the word is on the button, not in the page. The claim
    // this case exists to make is the SURFACE one.)
    expect(screen.queryByTestId('demo-states-dock')).not.toBeInTheDocument()
    expect(screen.getByTestId('ai-studio')).not.toHaveAttribute('data-demo-states')
    expect(api.getProject).toHaveBeenCalledWith('p1')
  })

  it('an unknown project id offers a way back to the list', async () => {
    const { StudioApiError } = await import('./studioApi')
    api.getProject.mockRejectedValue(new StudioApiError(404, 'project_not_found', 'project not found'))
    renderAt('/workspaces/gone/ai-studio')
    expect(await screen.findByTestId('ai-studio-load-error')).toBeInTheDocument()
    expect(screen.getByText('Project no longer exists')).toBeInTheDocument()
  })
})

describe('workbench shell', () => {
  it('renders the three columns with the embedded chat', async () => {
    renderAt('/workspaces/p1/ai-studio')
    expect(await screen.findByTestId('chat-embed-stub')).toBeInTheDocument()
    expect(screen.getByTestId('tool-sidebar')).toBeInTheDocument()
    expect(screen.getByTestId('resizer-left')).toBeInTheDocument()
    expect(screen.getByTestId('resizer-right')).toBeInTheDocument()
  })

  it('opens a real project doc from the sidebar into a closable center tab', async () => {
    const user = userEvent.setup()
    renderAt('/workspaces/p1/ai-studio')
    // ACP-2015 step 2: the sidebar opens on 需求 now, so the doc list is one tab
    // click away — this test is about the center tab it opens, not the first tab
    await user.click(await screen.findByRole('tab', { name: 'Docs' }))
    await user.click(await screen.findByText('requirements.md'))
    const tab = await screen.findByRole('tab', { name: /requirements\.md/ })
    expect(document.querySelector('[data-testid="doc-requirements.md"]')).toBeInTheDocument()
    await user.click(within(tab).getByRole('button', { name: /close tab/i }))
    expect(screen.queryByRole('tab', { name: /requirements\.md/ })).not.toBeInTheDocument()
  })

  it('refuses to hide the last visible pane', async () => {
    const user = userEvent.setup()
    renderAt('/workspaces/p1/ai-studio')
    // the shell renders only once the project query resolves; the toggles do
    // not exist during the skeleton
    await screen.findByTestId('ai-studio')
    await user.click(screen.getByTitle('Toggle workspace pane'))
    await user.click(screen.getByTitle('Toggle tool sidebar'))
    await user.click(screen.getByTitle('Toggle chat pane'))
    // hiding everything would leave no way back — chat must survive
    expect(await screen.findByTestId('chat-embed-stub')).toBeInTheDocument()
  })
})

describe('recent activity (ACP-754)', () => {
  it('the workbench feed exists and shows its empty state when nothing is drafted', async () => {
    renderAt('/workspaces/p1/ai-studio')
    await screen.findByTestId('ai-studio')
    const feed = await screen.findByTestId('recent-activity')
    expect(feed).toHaveAttribute('data-activity-count', '0')
    expect(within(feed).getByTestId('recent-activity-empty')).toHaveTextContent('No activity yet')
  })

  it('the feed lists exactly the drafted docs the store reports', async () => {
    api.listDraftDocs.mockResolvedValue({
      drafts: [
        { name: 'requirements.md', content: '# 草稿', changed: true },
        { name: 'workflow.md', content: '# 流程草稿', changed: true },
      ],
    })
    renderAt('/workspaces/p1/ai-studio')
    const feed = await screen.findByTestId('recent-activity')
    await waitFor(() => expect(feed).toHaveAttribute('data-activity-count', '2'))
    expect(within(feed).getByTestId('recent-activity-item-0')).toHaveTextContent(/requirements\.md/)
    expect(within(feed).getByTestId('recent-activity-item-1')).toHaveTextContent(/workflow\.md/)
  })
})

// ACP-801: the project-level commit lives at the TOP OF THE 提交 TAB, not in the
// page header. 「提交全部」 acts on 提交, so the action button rides the tab it acts
// on; the header keeps only what the page is (project name + the two version
// badges). These cases therefore reach the button the way a presenter does: by
// opening that tab.
describe('project-level commit (moved into the 提交 tab, ACP-801)', () => {
  /** open the sidebar's 提交 tab with a real click */
  const openCommitsTab = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(await screen.findByRole('tab', { name: 'Commits' }))
  }

  it('keeps the header free of it: no commit affordance outside the tab', async () => {
    renderAt('/workspaces/p1/ai-studio')
    await screen.findByTestId('ai-studio')
    // the header is the workbench's own row; the button is not in it (it may
    // not be anywhere yet — the tab has not been opened)
    const header = document.querySelector('header')!
    expect(header.querySelector('[data-testid="commit-all-btn"]')).toBeNull()
    expect(within(header).queryByTestId('drafts-pending')).toBeNull()
    // …and the tab that now owns it shows it once opened
    await openCommitsTab(userEvent.setup())
    expect(screen.getByTestId('commit-all-btn')).toBeInTheDocument()
    expect(screen.getByTestId('tool-sidebar').contains(screen.getByTestId('commit-all-btn'))).toBe(true)
  })

  it('lists drafted docs on the tab and commits every one of them', async () => {
    const user = userEvent.setup()
    api.listDraftDocs.mockResolvedValue({
      drafts: [
        { name: 'requirements.md', content: '# 草稿', changed: true },
        { name: 'workflow.md', content: '# 流程草稿', changed: true },
      ],
    })
    api.saveDoc.mockResolvedValue({ doc: { name: 'x', content: 'x' } })
    renderAt('/workspaces/p1/ai-studio')
    await screen.findByTestId('ai-studio')
    await openCommitsTab(user)
    // the summary names the drafted docs next to the button; waiting on it
    // also waits for the drafts query to land, so the click below cannot
    // race the query's first resolution
    const badge = await screen.findByTitle(/requirements\.md, workflow\.md/)
    expect(badge).toBeInTheDocument()
    const commitBtn = screen.getByRole('button', { name: /Commit all/i })
    expect(commitBtn).toBeEnabled()
    await user.click(commitBtn)
    // one existing-API commit per drafted doc
    await waitFor(() => expect(api.saveDoc).toHaveBeenCalledTimes(2))
    expect(api.saveDoc).toHaveBeenCalledWith('p1', 'requirements.md', '# 草稿')
    expect(api.saveDoc).toHaveBeenCalledWith('p1', 'workflow.md', '# 流程草稿')
    // three reads, and each one is accounted for: the page's feed query (one),
    // the commit bar mounting on the tab with the SAME key — react-query shares
    // the entry but a fresh observer on a stale (default staleTime 0) one
    // revalidates (two) — and the bar's post-commit refetch (three). It still
    // reports the list, so re-enabling the button is the honest state after a
    // refetch that kept the drafts.
    expect(api.listDraftDocs).toHaveBeenCalledTimes(3)
  })

  it('the commit button is disabled while nothing is drafted', async () => {
    const user = userEvent.setup()
    renderAt('/workspaces/p1/ai-studio')
    await screen.findByTestId('ai-studio')
    await openCommitsTab(user)
    expect(screen.getByRole('button', { name: /Commit all/i })).toBeDisabled()
    expect(api.saveDoc).not.toHaveBeenCalled()
  })
})

// T7 (ACP-851): the 需求图谱 tab's real loop row. The panel's own behaviour
// is GraphLoopPanel.test's business; what THIS file measures is the page's
// half of the seam — the row exists only in the ordinary workbench, its
// button reaches the real client with the page's project and doc, and a demo
// frame neither shows the row nor issues the real reads.
describe('graph loop row (real workbench vs demo, T7)', () => {
  it('the graph tab offers the real 沉淀/冻结/重生成 row and 沉淀 calls the api', async () => {
    const user = userEvent.setup()
    renderAt('/workspaces/p1/ai-studio')
    await screen.findByTestId('ai-studio')
    await user.click(await screen.findByRole('tab', { name: 'Graph' }))
    const panel = await screen.findByTestId('graph-loop-panel')
    expect(within(panel).getByTestId('graph-distill-btn')).toBeInTheDocument()
    expect(within(panel).getByTestId('freeze-btn')).toBeInTheDocument()
    expect(within(panel).getByTestId('graph-regen-btn')).toBeInTheDocument()
    // the loop's reads went out with the page's project
    expect(api.listFreezes).toHaveBeenCalledWith('p1')
    expect(api.listDistills).toHaveBeenCalledWith('p1')
    await user.click(within(panel).getByTestId('graph-distill-btn'))
    await waitFor(() => expect(api.distill).toHaveBeenCalledWith('p1', 'requirements.md'))
  })

  it('a demo frame shows no loop row and issues none of the real graph reads', async () => {
    renderAt('/workspaces/p1/ai-studio?demo=states')
    await screen.findByTestId('demo-states-dock')
    // the graph frame: its tab is lit, and the tab it shows is snapshot data
    const dock = screen.getByTestId('demo-states-dock')
    fireEvent.click(within(dock).getByTestId('demo-states-select-G1'))
    await waitFor(() => expect(dock).toHaveAttribute('data-demo-state', 'G1'))
    expect(screen.queryByTestId('graph-loop-panel')).not.toBeInTheDocument()
    expect(api.listFreezes).not.toHaveBeenCalled()
    expect(api.listDistills).not.toHaveBeenCalled()
    expect(api.getGraph).not.toHaveBeenCalled()
  })

  it('the dev tab offers the real gate-driven run row and 开始开发 calls the api (T7 step 4)', async () => {
    const user = userEvent.setup()
    renderAt('/workspaces/p1/ai-studio')
    await screen.findByTestId('ai-studio')
    await user.click(await screen.findByRole('tab', { name: 'Dev' }))
    await screen.findByTestId('dev-loop-panel')
    expect(api.listDevRuns).toHaveBeenCalledWith('p1')
    await user.click(screen.getByTestId('dev-start-btn'))
    await waitFor(() => expect(api.startDevRun).toHaveBeenCalledWith('p1', 'v1'))
  })

  it('a dev frame shows its snapshot run, not the real loop row', async () => {
    renderAt('/workspaces/p1/ai-studio?demo=states')
    await screen.findByTestId('demo-states-dock')
    const dock = screen.getByTestId('demo-states-dock')
    fireEvent.click(within(dock).getByTestId('demo-states-select-V1'))
    await waitFor(() => expect(dock).toHaveAttribute('data-demo-state', 'V1'))
    expect(screen.queryByTestId('dev-loop-panel')).not.toBeInTheDocument()
    expect(api.listDevRuns).not.toHaveBeenCalled()
  })
})

describe('new-project dialog', () => {
  it('creates a project and lands in its workbench', async () => {
    const user = userEvent.setup()
    api.createProject.mockResolvedValue({
      project: { ...TEST_PROJECT, id: 'p2', name: '新项目' },
    })
    renderAt('/workspaces')
    await user.click(await screen.findByRole('button', { name: /New project/i }))
    await user.type(screen.getByLabelText(/Project name/i), '新项目')
    await user.type(screen.getByLabelText(/Description/i), '描述')
    await user.click(screen.getByRole('button', { name: /Create project/i }))
    expect(api.createProject).toHaveBeenCalledWith('新项目', '描述')
    // navigation into the new project's workbench fires the detail load
    expect(await screen.findByTestId('ai-studio')).toBeInTheDocument()
  })

  it('keeps the dialog open and names the failure when create is refused', async () => {
    const { StudioApiError } = await import('./studioApi')
    api.createProject.mockRejectedValue(new StudioApiError(400, 'name_required', 'project name is required'))
    renderAt('/workspaces')
    await userEvent.click(await screen.findByRole('button', { name: /New project/i }))
    await userEvent.type(screen.getByLabelText(/Project name/i), 'x')
    await userEvent.click(screen.getByRole('button', { name: /Create project/i }))
    expect(await screen.findByText('Project name is required')).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })
})
