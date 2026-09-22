// The work-area views, driven through the tool sidebar the way the page wires
// them: each tool tab opens its tab kinds, and each kind renders its data.
// Docs now come from the project API (mocked); the other tools are still
// fixture-backed. ChatEmbed is stubbed (WebSocket). UI strings assert the
// English catalog (tests pin en); fixture content is Chinese by design and
// asserted as data.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('../../app-sdk/ChatEmbed', () => ({
  default: () => <div data-testid="chat-embed-stub" />,
}))

const api = vi.hoisted(() => ({
  listProjects: vi.fn(),
  createProject: vi.fn(),
  getProject: vi.fn(),
  saveDoc: vi.fn(),
  saveDraft: vi.fn(async () => ({ ok: true })),
  listDraftDocs: vi.fn(async () => ({ drafts: [] })),
  listDraftVersions: vi.fn(async () => ({ versions: [] })),
  listVersions: vi.fn(async () => ({ versions: [] })),
}))
vi.mock('./studioApi', async () => {
  const actual = await vi.importActual('./studioApi')
  return { ...actual, studioApi: api }
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

  it('releases tab: progress bar renders, history row opens a tab', async () => {
    const user = userEvent.setup()
    renderStudio(<AiStudioPage />)
    await openTool(user, 'Releases')
    const sidebar = screen.getByTestId('tool-sidebar')
    // progress block: done/total, the current task, and a running-row badge
    expect(within(sidebar).getByText('4/6')).toBeInTheDocument()
    expect(within(sidebar).getByText('生成正式设计文档')).toBeInTheDocument()
    expect(within(sidebar).getByText('Running')).toBeInTheDocument()
    expect(within(sidebar).getByText('v1.3')).toBeInTheDocument()
    await user.click(within(sidebar).getByText('v1.3'))
    expect(await screen.findByRole('tab', { name: 'Release v1.3' })).toBeInTheDocument()
  })

  it('dev tab: history row opens a tab', async () => {
    const user = userEvent.setup()
    renderStudio(<AiStudioPage />)
    await openTool(user, 'Dev')
    const sidebar = screen.getByTestId('tool-sidebar')
    await user.click(within(sidebar).getByText('dev-309'))
    expect(await screen.findByRole('tab', { name: 'Dev run dev-309' })).toBeInTheDocument()
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
    await user.click(screen.getByText('requirements.md'))
    await screen.findByTestId('doc-requirements.md')
    await user.click(within(sidebar).getByText('workflow.md'))
    await screen.findByTestId('doc-workflow.md')
    // click back to the first tab body is the doc view again
    await user.click(screen.getByRole('tab', { name: /requirements\.md/ }))
    expect(screen.getByTestId('doc-requirements.md')).toBeInTheDocument()
  })
})
