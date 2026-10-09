// The work-area views, driven through the tool sidebar the way the page wires
// them: each tool tab opens its tab kinds, and each kind renders its data.
// Docs now come from the project API (mocked); the other tools are still
// fixture-backed. ChatEmbed is stubbed (WebSocket). UI strings assert the
// English catalog (tests pin en); fixture content is Chinese by design and
// asserted as data.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('../../app-sdk/ChatEmbed', () => ({
  default: () => <div data-testid="chat-embed-stub" />,
}))

// happy-dom has no EventSource; the DeployLog now opens one on mount (ACP-772).
// The fake records every instance so a test can answer the open stream with
// frames; instances default to a finished-job replay of one line (the shape a
// re-opened log gets) so views that merely mount a deploy tab still show
// content. The growth/stream contract itself is covered in DeployLog.test.tsx.
class FakeEventSource {
  static instances: FakeEventSource[] = []
  onmessage: ((ev: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null
  closed = false
  constructor(public url: string) {
    FakeEventSource.instances.push(this)
    const deployId = decodeURIComponent(url.match(/\/publish\/([^/]+)\/log/)?.[1] ?? '?')
    setTimeout(() => {
      this.onmessage?.({
        data: JSON.stringify({
          lines: [`Deployment ${deployId} is RUNNING`],
          done: true,
          status: 'success',
        }),
      } as MessageEvent)
    }, 0)
  }
  close() { this.closed = true }
}
beforeEach(() => {
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource as unknown as typeof EventSource)
})
afterEach(() => vi.unstubAllGlobals())

const api = vi.hoisted(() => ({
  listProjects: vi.fn(),
  createProject: vi.fn(),
  getProject: vi.fn(),
  saveDoc: vi.fn(),
  saveDraft: vi.fn(async () => ({ ok: true })),
  listDraftDocs: vi.fn(async () => ({ drafts: [] })),
  listDraftVersions: vi.fn(async () => ({ versions: [] })),
  listVersions: vi.fn(async () => ({ versions: [{ version: 'v1.0', commitHash: 'c1051100', time: 1 }] })),
  listRecords: vi.fn(async () => ({ records: [] })),
  preview: vi.fn(async () => ({ form: 'full', reason: '完整版通过验收' })),
  trigger: vi.fn(),
  // T7 (ACP-851): the real workbench now also reads the graph loop and the
  // gate-driven dev runs; defaults keep every OTHER tab's test at the shape
  // it had before these endpoints existed.
  getGraph: vi.fn(async () => ({ graphId: 'none', graph: { nodes: [], edges: [] } })),
  listFreezes: vi.fn(async () => ({ freezes: [] })),
  listDistills: vi.fn(async () => ({ distillations: [] })),
  listDevRuns: vi.fn(async () => ({ runs: [] })),
  startDevRun: vi.fn(async () => ({ run: { id: 'x', designVersion: '', phases: [], artifacts: [] } })),
  // ACP-2015 step 2: 需求 is the sidebar's default tab, so every workbench mount
  // runs the requirement list read; this fixture project has no graphs.
  listRequirements: vi.fn(async () => ({ pages: [] })),
  getRequirement: vi.fn(async () => { throw new Error('unused') }),
  // ACP-2085 S2: every workbench mount opens the chat column's 需求会话 through
  // this api; the ordering contract is ChatPane.test's, here it is chrome.
  ensureReqSession: vi.fn(async (id: string) => ({ slotKey: `ai-studio-req-${id}`, created: false })),
}))
vi.mock('./studioApi', async () => {
  const actual = await vi.importActual('./studioApi')
  return { ...actual, studioApi: api, publishApi: api }
})

import AiStudioPage from './AiStudioPage'
import { TEST_DOCS, TEST_PROJECT, renderStudio } from './testUtils'

beforeEach(() => {
  vi.clearAllMocks()
  api.getProject.mockResolvedValue({ project: TEST_PROJECT, docs: TEST_DOCS })
})

async function openTool(user: ReturnType<typeof userEvent.setup>, name: string) {
  await user.click(await screen.findByRole('tab', { name }))
}

describe('tool sidebar -> work area views', () => {
  it('commits tab: pending diff row opens DiffView, commit row opens CommitView', async () => {
    const user = userEvent.setup()
    renderStudio(<AiStudioPage />)
    await openTool(user, 'Commits')
    // pending change -> diff view
    await user.click(await screen.findByText('requirements.md'))
    expect(await screen.findByTestId('diff-requirements.md')).toBeInTheDocument()
    // commit history -> commit view; c1051's files overlap CHANGED so hunks
    // render, and c1046-only files hit the "historical" fallback line
    const sidebar = screen.getByTestId('tool-sidebar')
    await user.click(within(sidebar).getByText('新增技术澄清阶段'))
    const commit = await screen.findByTestId('commit-c1051')
    expect(commit).toBeInTheDocument()
    await user.click(within(sidebar).getByText('优化商机详情页操作'))
    const c2 = await screen.findByTestId('commit-c1046')
    expect(within(c2).getByText('ui-spec.md')).toBeInTheDocument()
  })

  it('releases tab: the publish version list renders (the dev tab keeps the old ReleasesTool)', async () => {
    const user = userEvent.setup()
    renderStudio(<AiStudioPage />)
    await user.click(await screen.findByTestId('ai-studio-publish-entry'))
    const sidebar = screen.getByTestId('tool-sidebar')
    expect(await within(sidebar).findByTestId('ai-studio-publish-version-list')).toBeInTheDocument()
    expect(within(sidebar).getByTestId('ai-studio-publish-version-row-v1.0')).toBeInTheDocument()
    expect(within(sidebar).getByTestId('ai-studio-publish-btn-v1.0')).toBeInTheDocument()
  })

  // T7 step 4 (ACP-851) changed this tab's contract: the ordinary workbench's
  // 开发 tab no longer stands on the DEV fixture — it runs the four phases
  // through the bgdd gate (DevLoopPanel, observed IN the tab exactly like the
  // graph tab's list rule). The fixture ReleasesTool the old case witnessed
  // still stands behind ToolSidebar for callers that pass neither injection.
  it('dev tab: the real workbench shows the development board (ACP-2085)', async () => {
    const user = userEvent.setup()
    renderStudio(<AiStudioPage />)
    await openTool(user, 'Dev')
    const sidebar = screen.getByTestId('tool-sidebar')
    expect(await within(sidebar).findByTestId('ai-studio-dev-dag-panel')).toBeInTheDocument()
    expect(within(sidebar).queryByTestId('dev-start-btn')).not.toBeInTheDocument()
  })

  it('deploy tab: current and historical rows open deploy logs', async () => {
    const user = userEvent.setup()
    renderStudio(<AiStudioPage />)
    await openTool(user, 'Deploy')
    const sidebar = screen.getByTestId('tool-sidebar')
    await user.click(within(sidebar).getByText('deploy-024'))
    expect(await screen.findByTestId('deploy-log-deploy-024')).toBeInTheDocument()
    await user.click(within(sidebar).getByText('deploy-018'))
    const log = await screen.findByTestId('deploy-log-deploy-018')
    expect(log).toHaveTextContent('Deployment deploy-018 is RUNNING')
  })

  it('graph: node row opens NodeDetail; back returns to type list', async () => {
    const user = userEvent.setup()
    renderStudio(<AiStudioPage />)
    await openTool(user, 'Graph')
    const sidebar = screen.getByTestId('tool-sidebar')
    await user.click(await within(sidebar).findByRole('button', { name: /实体/ }))
    await user.click(within(sidebar).getByText('商机'))
    expect(await screen.findByRole('tab', { name: '商机' })).toBeInTheDocument()
    // drill back out of the node list
    await user.click(within(sidebar).getByRole('button', { name: /Node types/ }))
    expect(within(sidebar).getByText('页面')).toBeInTheDocument()
  })

  it('work area: a second tab switches selection on click', async () => {
    const user = userEvent.setup()
    renderStudio(<AiStudioPage />)
    // wait out the project-query skeleton before reaching for the sidebar
    await screen.findByTestId('ai-studio')
    const sidebar = screen.getByTestId('tool-sidebar')
    // ACP-2015 step 2: the sidebar now opens on 需求, so the doc list has to be
    // asked for — the test is about tab switching, not about which tab is first
    await openTool(user, 'Docs')
    await user.click(await within(sidebar).findByText('requirements.md'))
    await screen.findByTestId('doc-requirements.md')
    await user.click(within(sidebar).getByText('workflow.md'))
    await screen.findByTestId('doc-workflow.md')
    // click back to the first tab body is the doc view again
    await user.click(screen.getByRole('tab', { name: /requirements\.md/ }))
    expect(screen.getByTestId('doc-requirements.md')).toBeInTheDocument()
  })
})
