// The top-bar dev-server control (ACP-2060). The state is the backend's on
// purpose — every render re-reads `GET dev-server` — so the fake api is the
// whole fixture: one stubbed read per scenario, plus the two action calls the
// button makes. Tests follow the same split as RequirementsTool.test.tsx: mock
// ./studioApi, mount through renderStudio, assert what the screen says.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const getDevServer = vi.hoisted(() => vi.fn())
const startDevServer = vi.hoisted(() => vi.fn())
const stopDevServer = vi.hoisted(() => vi.fn())
const getDevServerLog = vi.hoisted(() => vi.fn())
vi.mock('./studioApi', async () => {
  const actual = await vi.importActual('./studioApi')
  return {
    ...actual,
    studioApi: { getDevServer, startDevServer, stopDevServer, getDevServerLog },
  }
})

import DevServerControl, { DevServerBadge } from './DevServerControl'
import type { StudioDevServer } from './studioApi'
import { renderStudio } from './testUtils'

const URL = 'https://sbgl-14409-dev.gb10.jereh-pe.cn/'

function view(over: Partial<StudioDevServer> = {}): StudioDevServer {
  return {
    state: 'stopped',
    url: '',
    ports: { web: null, api: null },
    failedStep: null,
    message: null,
    startedAt: null,
    ...over,
  }
}

function mount() {
  renderStudio(<DevServerControl projectId="p1" />)
}

async function mountShowing(v: StudioDevServer) {
  getDevServer.mockResolvedValue(v)
  mount()
  await screen.findByTestId('dev-server-control')
}

beforeEach(() => {
  vi.clearAllMocks()
  getDevServer.mockResolvedValue(view())
  startDevServer.mockResolvedValue(view({ state: 'starting' }))
  stopDevServer.mockResolvedValue(view())
  getDevServerLog.mockResolvedValue({ lines: ['pnpm install', 'ERR 404 not found'] })
})

describe('DevServerControl', () => {
  it('stopped: a grey dot and a start button, no URL', async () => {
    await mountShowing(view())
    expect(await screen.findByTestId('dev-server-dot-stopped')).toBeInTheDocument()
    expect(screen.getByTestId('dev-server-toggle')).toHaveTextContent('Start dev server')
    expect(screen.queryByTestId('dev-server-url')).not.toBeInTheDocument()
  })

  it('clicking start calls start and shows 「启动中…」', async () => {
    const user = userEvent.setup()
    await mountShowing(view())
    await user.click(screen.getByTestId('dev-server-toggle'))
    expect(startDevServer).toHaveBeenCalledWith('p1')
    // the optimistic label is the backend's next answer: the refetch after the
    // mutation returns `starting`, so the screen must land on 「启动中…」
    await waitFor(() =>
      expect(within(screen.getByTestId('dev-server-control')).getByText('Starting…')).toBeInTheDocument(),
    )
    expect(screen.queryByTestId('dev-server-url')).not.toBeInTheDocument()
  })

  it('running: the URL link with the right href, and the button became stop', async () => {
    const user = userEvent.setup()
    await mountShowing(
      view({
        state: 'running',
        url: URL,
        ports: { web: 6801, api: 6802 },
        startedAt: '2026-10-08T10:00:00Z',
      }),
    )
    const link = await screen.findByTestId('dev-server-url')
    expect(link).toHaveAttribute('href', URL)
    // a dev URL is opened in a tab the dashboard can be closed without
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    expect(screen.getByTestId('dev-server-toggle')).toHaveTextContent('Stop dev server')
    expect(screen.getByTestId('dev-server-dot-running')).toBeInTheDocument()
    await user.click(screen.getByTestId('dev-server-toggle'))
    expect(stopDevServer).toHaveBeenCalledWith('p1')
  })

  it('failed: the backend message verbatim, step name and all', async () => {
    // The shape devserver._fail writes: the step name is ALREADY in `message`
    // (「装依赖失败：<tail>」), so the UI must neither re-templat it nor paraphrase
    // the tail — the tail is the only place the real error exists.
    const message = '装依赖失败：Command failed: pnpm install\nERR 404 Not Found'
    await mountShowing(view({ state: 'failed', failedStep: '装依赖', message }))
    const err = await screen.findByTestId('dev-server-error')
    expect(err.textContent).toBe(message)
    // a failed project is startable again, so the button reads 「启动」
    expect(screen.getByTestId('dev-server-toggle')).toHaveTextContent('Start dev server')
  })

  it('the log toggle pulls the tail once and shows it', async () => {
    const user = userEvent.setup()
    await mountShowing(view({ state: 'failed', failedStep: 'pnpm install', message: 'x' }))
    await user.click(screen.getByTestId('dev-server-log-toggle'))
    const log = await screen.findByTestId('dev-server-log')
    expect(log).toHaveTextContent('ERR 404 not found')
    expect(getDevServerLog).toHaveBeenCalledWith('p1', 200)
    await user.click(screen.getByTestId('dev-server-log-toggle'))
    expect(screen.queryByTestId('dev-server-log')).not.toBeInTheDocument()
  })

  it('an action the backend refuses is shown, not swallowed', async () => {
    const user = userEvent.setup()
    startDevServer.mockRejectedValue(new Error('项目未配置代号'))
    await mountShowing(view())
    await user.click(screen.getByTestId('dev-server-toggle'))
    expect(await screen.findByTestId('dev-server-action-error')).toHaveTextContent('项目未配置代号')
  })
})

describe('DevServerBadge (project card)', () => {
  it('a running project shows the green dot and its URL', async () => {
    getDevServer.mockResolvedValue(view({ state: 'running', url: URL }))
    renderStudio(<DevServerBadge projectId="p1" />)
    const link = await screen.findByTestId('project-dev-url')
    expect(link).toHaveAttribute('href', URL)
  })

  it('a stopped project renders nothing', async () => {
    getDevServer.mockResolvedValue(view())
    renderStudio(<DevServerBadge projectId="p1" />)
    await waitFor(() => expect(getDevServer).toHaveBeenCalled())
    expect(screen.queryByTestId('project-dev-url')).not.toBeInTheDocument()
  })
})
