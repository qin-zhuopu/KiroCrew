// ACP-794: the state-direct demo rendered INTO the real workbench.
//
// What the owner rejected was a self-built shell — its own header, a
// hand-rolled doc list, a text block in the middle. These cases therefore do
// not assert "a demo is on screen"; they assert the SHIPPED components are on
// screen while it is: the tool sidebar's six tool tabs, the chat column, the
// activity feed, both resizers, and the real DocEditor / the DistillPanel-fed
// 需求图谱 tab / DevRunPanel / PublishVersionList / ReleaseJobPage /
// DeployLog-contract panels, addressed by their own testids. That is the whole
// difference between the two surfaces, so it is the thing measured.
// (ACP-797 retired the center GraphView: the graph is a list in that tab, and
// the middle column is a doc editor. The tab's own contract lives in
// demo/states-graph.test.tsx + demo/states-design.test.tsx.)
//
// Two rules ride along:
//   - 就地接管: entering the demo must not move the page. `location.pathname`
//     still carries the project id and the project read is not re-issued —
//     asserted by counting `getProject` calls, not by reading a flag.
//   - 幂等: selecting the same frame twice renders the same picture, because
//     every switch is a wholesale reload of a snapshot and nothing accumulates.
//
// ChatEmbed is stubbed exactly as AiStudioPage.test stubs it (it opens a
// WebSocket this environment neither serves nor needs); the studio api is
// stubbed so no fetch leaves the test. The publish-side reads are NOT stubbed
// — the frames' own snapshot fake answers them, which is what proves the
// release frames never reach for the real client.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, useLocation } from 'react-router-dom'

vi.mock('../../app-sdk/ChatEmbed', () => ({
  default: () => <div data-testid="chat-embed-stub" />,
}))

const fakeApi = vi.hoisted(() => ({ api: {} as { post: unknown } }))
vi.mock('../../app-sdk', async () => {
  const actual = await vi.importActual('../../app-sdk')
  return { ...actual, useAppApi: () => fakeApi.api }
})
fakeApi.api = { post: vi.fn(async () => ({ key: 'x' })) }

const api = vi.hoisted(() => ({
  getProject: vi.fn(),
  listProjects: vi.fn(),
  listDraftDocs: vi.fn(),
  listVersions: vi.fn(),
  listDraftVersions: vi.fn(),
}))
vi.mock('../studioApi', async () => {
  const actual = await vi.importActual('../studioApi')
  return { ...actual, studioApi: api }
})

import AiStudioPage from '../AiStudioPage'
import { TEST_DOCS, TEST_PROJECT } from '../testUtils'

const DEPLOY_ID = '20260923-071530-120-4f9a2c71'
const FOCUS_DOC = '产品需求设计文档.md'

function LocProbe() {
  const { search, pathname } = useLocation()
  return <span data-testid="loc-probe">{`${pathname}${search}`}</span>
}

function mount(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <AiStudioPage />
        <LocProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const loc = () => screen.getByTestId('loc-probe').textContent ?? ''
const dock = () => screen.getByTestId('demo-states-dock')
const sidebar = () => screen.getByTestId('tool-sidebar')

/** Enter the demo the way the owner does: from a workbench whose project has
 * ALREADY loaded (that is the whole reason the top bar can keep showing it
 * without a second request), then wait for the dock. */
async function enterDemo() {
  await screen.findByText(/测试项目/)
  fireEvent.click(screen.getByTestId('demo-entry-btn'))
  await screen.findByTestId('demo-states-dock')
}

async function select(id: string) {
  fireEvent.click(screen.getByTestId(`demo-states-select-${id}`))
  await waitFor(() => expect(dock()).toHaveAttribute('data-demo-state', id))
}

/** the lit tool tab of the sidebar — the frame's own `activeSidebarTab`, or
 * 'docs' when the frame names none. Read off `aria-selected`, the same fact
 * the browser reports. */
function litTool(): string {
  const tabs = within(sidebar()).getAllByRole('tab')
  const lit = tabs.find((t) => t.getAttribute('aria-selected') === 'true')
  return lit?.textContent ?? ''
}

beforeEach(() => {
  vi.clearAllMocks()
  api.getProject.mockResolvedValue({ project: TEST_PROJECT, docs: TEST_DOCS })
  api.listProjects.mockResolvedValue({ projects: [TEST_PROJECT] })
  api.listDraftDocs.mockResolvedValue({ drafts: [] })
  api.listVersions.mockResolvedValue({ versions: [] })
  api.listDraftVersions.mockResolvedValue({ versions: [] })
  window.localStorage.clear()
})

describe('state demo inside the real workbench (ACP-794)', () => {
  it('enters on the same path, keeping the project, and shows the real workbench chrome', async () => {
    mount('/workspaces/p1/ai-studio')
    const projectCallsBefore = api.getProject.mock.calls.length

    await enterDemo()

    // the URL kept its path and its project id; only the query changed
    expect(loc()).toContain('/workspaces/p1/ai-studio')
    expect(loc()).toContain('demo=states')
    expect(screen.getByTestId('ai-studio')).toHaveAttribute('data-demo-states', 'states')
    // the top bar still shows the project this page loaded
    expect(screen.getByText(/测试项目/)).toBeInTheDocument()

    // the shipped three-column chrome, by its own testids
    expect(within(screen.getByTestId('tool-sidebar')).getAllByRole('tab')).toHaveLength(6)
    expect(screen.getByTestId('ai-studio-chat')).toBeInTheDocument()
    expect(screen.getByTestId('recent-activity')).toBeInTheDocument()
    expect(screen.getByTestId('resizer-left')).toBeInTheDocument()
    expect(screen.getByTestId('resizer-right')).toBeInTheDocument()

    // 就地表: the demo opened no project request of its own
    expect(api.getProject.mock.calls.length).toBe(projectCallsBefore)
  })

  it('docks every frame under its five stages, in story order, and prev/next walks it', async () => {
    mount('/workspaces/p1/ai-studio')
    await enterDemo()

    const design = within(screen.getByTestId('demo-states-group-design'))
    for (const id of ['D6', 'D7', 'D8']) {
      expect(design.getByTestId(`demo-states-select-${id}`)).toBeInTheDocument()
    }
    // C1/C2 LEFT the design group (owner, ACP-796): 提交 is its own stage, so
    // the pair lives in the commit group and nowhere else
    expect(design.queryByTestId('demo-states-select-C1')).toBeNull()

    const commit = within(screen.getByTestId('demo-states-group-commit'))
    for (const id of ['C1', 'C2']) {
      expect(commit.getByTestId(`demo-states-select-${id}`)).toBeInTheDocument()
    }

    const release = within(screen.getByTestId('demo-states-group-release'))
    for (const id of ['R1', 'R2', 'R3', 'R4', 'R5', 'R6']) {
      expect(release.getByTestId(`demo-states-select-${id}`)).toBeInTheDocument()
    }
    const dev = within(screen.getByTestId('demo-states-group-dev'))
    for (const id of ['V1', 'V2', 'V3']) expect(dev.getByTestId(`demo-states-select-${id}`)).toBeInTheDocument()
    const deploy = within(screen.getByTestId('demo-states-group-deploy'))
    for (const id of ['P1', 'P2']) expect(deploy.getByTestId(`demo-states-select-${id}`)).toBeInTheDocument()

    // exactly five stages, rendered top to bottom in the owner's order — the
    // story order IS the group order, which is what makes prev/next readable
    const groups = [...dock().querySelectorAll('[data-testid^="demo-states-group-"]')]
      .map((el) => el.getAttribute('data-testid'))
    expect(groups).toEqual([
      'demo-states-group-design', 'demo-states-group-commit', 'demo-states-group-release',
      'demo-states-group-dev', 'demo-states-group-deploy',
    ])

    // the story opens on the design stage's first frame — a committed doc that
    // reads clean through the real editor's own rule
    expect(dock()).toHaveAttribute('data-demo-state', 'D6')
    const editor = await screen.findByTestId(`doc-${FOCUS_DOC}`)
    expect(editor).toHaveAttribute('data-doc-dirty', 'false')

    fireEvent.click(screen.getByTestId('demo-states-next'))
    await waitFor(() => expect(dock()).toHaveAttribute('data-demo-state', 'D7'))
  })

  it('names the product each stage hands on, next to its group', async () => {
    mount('/workspaces/p1/ai-studio')
    await enterDemo()

    // the chain the owner pinned (ACP-796): 设计→文档, 提交→需求图谱,
    // 发版→开发任务, 开发→git tag, 部署→应用 url. Rendered here from the
    // catalog — this suite pins English, so the values are the en catalog's;
    // zh-CN carries the owner's own wording for the same keys.
    const product = (phase: string) => screen.getByTestId(`demo-states-product-${phase}`)
    expect(product('design')).toHaveTextContent('Docs')
    expect(product('commit')).toHaveTextContent('Requirement graph')
    expect(product('release')).toHaveTextContent('Dev tasks')
    expect(product('dev')).toHaveTextContent('git tag')
    expect(product('deploy')).toHaveTextContent('App URL')
    // each one rides its own group's header row, not a legend somewhere else
    for (const phase of ['design', 'commit', 'release', 'dev', 'deploy']) {
      expect(within(screen.getByTestId(`demo-states-group-${phase}`)).getByTestId(`demo-states-product-${phase}`))
        .toBeInTheDocument()
    }
  })

  it('lights the sidebar tab the frame names: 提交 for C1/C2, 发布 for the R frames', async () => {
    mount('/workspaces/p1/ai-studio')
    await enterDemo()

    await select('C1')
    expect(litTool()).toBe('Commits')
    // the commits tab renders the FRAME's two lists, not the fixtures
    const pending = within(sidebar())
    expect(pending.getByText('产品需求设计文档.md')).toBeInTheDocument()
    expect(pending.getByText('第二轮迭代：积分抵扣规则定稿')).toBeInTheDocument()

    await select('C2')
    // 提交后: the pending list is empty and the history leads with this round
    const after = within(sidebar())
    expect(after.queryByText('第二轮迭代：积分抵扣规则定稿')).toBeInTheDocument()
    expect(after.getByText('第三轮迭代：大额采购一级审批（提交全部）')).toBeInTheDocument()

    await select('R1')
    expect(litTool()).toBe('Releases')
  })

  it('renders the release frames through the real publish list — including R3\'s one real click', async () => {
    mount('/workspaces/p1/ai-studio')
    await enterDemo()

    // R2: the rows, the v5 verdict and its publish button, from the frame's data
    await select('R2')
    const list = await screen.findByTestId('ai-studio-publish-version-list')
    expect(within(list).getByTestId('ai-studio-publish-btn-v5')).toBeEnabled()
    expect(within(list).getByTestId('ai-studio-publish-reason-v5')).toHaveTextContent('完整版')
    // v4 is the latest success on this frame → its button is retired
    expect(within(list).queryByTestId('ai-studio-publish-btn-v4')).toBeNull()

    // R3: the frame's ONE act — the real button's real click — leaves the row
    // resting at 发布中 (the fake trigger never settles; the finished run is
    // R4's frame, not this one)
    await select('R3')
    await waitFor(() => expect(screen.getByTestId('ai-studio-publish-btn-v5')).toBeDisabled())
    expect(screen.getByTestId('ai-studio-publish-status-v5')).toBeInTheDocument()

    // R4: the settle — the result strip the record carries
    await select('R4')
    const strip = await screen.findByTestId('ai-studio-publish-url-v5')
    // the record's serving address IS the link's href (the anchor's own text
    // is the localised "open" label — the address reads verbatim on the
    // record, and 08 §四 probes exactly this field)
    expect(strip).toHaveAttribute('href', 'v5-points-14409.gb10.jereh-pe.cn')
    expect(screen.getByTestId('ai-studio-publish-form-badge-v5')).toBeInTheDocument()
    expect(screen.getByTestId('ai-studio-publish-id-v5')).toBeInTheDocument()
  })

  it('renders R5 as the release-job page with its replayed log, R6 as the experience screen', async () => {
    mount('/workspaces/p1/ai-studio')
    await enterDemo()

    await select('R5')
    const page = await screen.findByTestId('ai-studio-release-job-page')
    expect(within(page).getByTestId('ai-studio-release-job-header')).toBeInTheDocument()
    expect(within(page).getByTestId('ai-studio-release-job-row-job-v5')).toBeInTheDocument()
    // the log is the shipped DeployLog, fed the frame's recorded tail instead
    // of an EventSource (a stream IS a network call)
    const log = within(page).getByTestId('deploy-log-job-v5')
    expect(within(log).getByRole('log')).toHaveAttribute('aria-live', 'polite')
    expect(log).toHaveTextContent('健康检查通过')

    await select('R6')
    expect(await screen.findByTestId('run-preview')).toHaveAttribute('data-run-version', 'v5')
  })

  it('renders each later phase through the shipped component for it', async () => {
    mount('/workspaces/p1/ai-studio')
    await enterDemo()

    await select('D7')
    // ACP-797 changed what "the component for this phase" IS: D7's graph is a
    // LIST in the 需求图谱 tab of the tool sidebar (its `graphEntries`, wired by
    // the dock/renderer), and the owner's rule keeps the middle column a doc
    // editor — so the centre proof here is the editor, and no canvas may exist.
    // The tab's own list is asserted in demo/states-graph.test.tsx; once the
    // dock hands `graphEntries` through, this step can assert the lit tab too.
    expect(await screen.findByTestId(`doc-${FOCUS_DOC}`)).toBeInTheDocument()
    expect(screen.queryByTestId('graph-view')).toBeNull()

    await select('V1')
    expect(await screen.findByTestId('dev-run-panel')).toHaveAttribute('data-dev-run-id', 'dev-v5')

    await select('P2')
    // the deploy frames cannot stream fetch-free, so the frame carries the log
    // — under DeployLog's own testid and a11y contract
    const log = await screen.findByTestId(`deploy-log-${DEPLOY_ID}`)
    expect(within(log).getByRole('log')).toHaveAttribute('aria-live', 'polite')
    expect(screen.getByTestId('ai-studio-release-job-header')).toBeInTheDocument()
  })

  it('is idempotent: reading the same frame twice renders the same picture', async () => {
    mount('/workspaces/p1/ai-studio')
    await enterDemo()

    await select('C1')
    const first = (await screen.findByTestId(`doc-${FOCUS_DOC}`)).outerHTML

    await select('D7')
    await select('C1')
    await waitFor(() => expect(dock()).toHaveAttribute('data-demo-state', 'C1'))
    expect(screen.getByTestId(`doc-${FOCUS_DOC}`).outerHTML).toBe(first)
  })

  it('leaves through the dock close button: back to the ordinary workbench', async () => {
    mount('/workspaces/p1/ai-studio')
    await enterDemo()

    fireEvent.click(screen.getByTestId('demo-states-close'))

    await waitFor(() => expect(loc()).not.toContain('demo'))
    expect(screen.queryByTestId('demo-states-dock')).toBeNull()
    expect(screen.getByTestId('ai-studio')).not.toHaveAttribute('data-demo-states')
    // the page is the project's workbench again
    expect(api.listDraftDocs).toHaveBeenCalled()
  })

  it('from the project list, the button opens the demo on a representative project', async () => {
    mount('/workspaces')
    // the button appears once the list has answered: it needs a project to
    // open the demo ON (an empty list has nothing to take over)
    fireEvent.click(await screen.findByTestId('demo-entry-btn'))

    await screen.findByTestId('demo-states-dock')
    expect(loc()).toContain('/workspaces/p1/ai-studio')
    expect(loc()).toContain('demo=states')
    expect(screen.getByTestId('ai-studio')).toHaveAttribute('data-demo-states', 'states')
  })
})