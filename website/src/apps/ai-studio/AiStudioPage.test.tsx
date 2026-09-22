// Tests for the app's route surface and the workbench shell: /ai-studio lands
// on the project list (empty state + new-project dialog), /ai-studio/projects
// /<id> lands on the three-column workbench whose header names the project,
// its Docs tool lists the project's real files, and opening one lands a
// closable tab. ChatEmbed is stubbed (it opens a WebSocket the test
// environment neither serves nor needs); studioApi is stubbed so no fetch
// leaves the test. UI strings assert the English catalog (tests pin en);
// project/doc content is Chinese by design and asserted as data.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
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
}))
vi.mock('./studioApi', async () => {
  const actual = await vi.importActual('./studioApi')
  return { ...actual, studioApi: api }
})

import AiStudioPage from './AiStudioPage'
import { TEST_DOCS, TEST_PROJECT } from './testUtils'

beforeEach(() => {
  vi.clearAllMocks()
  api.getProject.mockResolvedValue({ project: TEST_PROJECT, docs: TEST_DOCS })
  api.listProjects.mockResolvedValue({ projects: [TEST_PROJECT] })
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
  it('/ai-studio renders the project list with its cards', async () => {
    renderAt('/ai-studio')
    expect(await screen.findByTestId('ai-studio-projects')).toBeInTheDocument()
    expect(await screen.findByText('测试项目')).toBeInTheDocument()
    expect(screen.queryByTestId('ai-studio')).not.toBeInTheDocument()
  })

  it('/ai-studio/projects/<id> renders the workbench and names the project', async () => {
    renderAt('/ai-studio/projects/p1')
    expect(await screen.findByTestId('ai-studio')).toBeInTheDocument()
    // the header shows the fetched project's name, not a hardcoded demo
    expect(screen.getByText(/测试项目/)).toBeInTheDocument()
    expect(screen.queryByText(/Demo/)).not.toBeInTheDocument()
    expect(api.getProject).toHaveBeenCalledWith('p1')
  })

  it('an unknown project id offers a way back to the list', async () => {
    const { StudioApiError } = await import('./studioApi')
    api.getProject.mockRejectedValue(new StudioApiError(404, 'project_not_found', 'project not found'))
    renderAt('/ai-studio/projects/gone')
    expect(await screen.findByTestId('ai-studio-load-error')).toBeInTheDocument()
    expect(screen.getByText('Project no longer exists')).toBeInTheDocument()
  })
})

describe('workbench shell', () => {
  it('renders the three columns with the embedded chat', async () => {
    renderAt('/ai-studio/projects/p1')
    expect(await screen.findByTestId('chat-embed-stub')).toBeInTheDocument()
    expect(screen.getByTestId('tool-sidebar')).toBeInTheDocument()
    expect(screen.getByTestId('resizer-left')).toBeInTheDocument()
    expect(screen.getByTestId('resizer-right')).toBeInTheDocument()
  })

  it('opens a real project doc from the sidebar into a closable center tab', async () => {
    const user = userEvent.setup()
    renderAt('/ai-studio/projects/p1')
    await user.click(await screen.findByText('requirements.md'))
    const tab = await screen.findByRole('tab', { name: /requirements\.md/ })
    expect(document.querySelector('[data-testid="doc-requirements.md"]')).toBeInTheDocument()
    await user.click(within(tab).getByRole('button', { name: /close tab/i }))
    expect(screen.queryByRole('tab', { name: /requirements\.md/ })).not.toBeInTheDocument()
  })

  it('refuses to hide the last visible pane', async () => {
    const user = userEvent.setup()
    renderAt('/ai-studio/projects/p1')
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

describe('new-project dialog', () => {
  it('creates a project and lands in its workbench', async () => {
    const user = userEvent.setup()
    api.createProject.mockResolvedValue({
      project: { ...TEST_PROJECT, id: 'p2', name: '新项目' },
    })
    renderAt('/ai-studio')
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
    renderAt('/ai-studio')
    await userEvent.click(await screen.findByRole('button', { name: /New project/i }))
    await userEvent.type(screen.getByLabelText(/Project name/i), 'x')
    await userEvent.click(screen.getByRole('button', { name: /Create project/i }))
    expect(await screen.findByText('Project name is required')).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })
})
