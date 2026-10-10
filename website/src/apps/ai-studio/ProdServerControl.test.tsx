// The top-bar production-server control (ACP-2085-S5). Like the dev control, the
// state is the backend's on purpose, so the fake api is the whole fixture: one
// stubbed read per scenario plus the action calls the buttons make.
//
// The scenario list is the ticket's: 查询中 disables, not_accepted shows the
// hint, deploying shows the step, running shows the URL and the version, failed
// shows the backend's text verbatim, and 停止 calls stop.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const getProdServer = vi.hoisted(() => vi.fn())
const deployProdServer = vi.hoisted(() => vi.fn())
const stopProdServer = vi.hoisted(() => vi.fn())
const getProdServerLog = vi.hoisted(() => vi.fn())
vi.mock('./studioApi', async () => {
  const actual = await vi.importActual('./studioApi')
  return {
    ...actual,
    prodServerApi: { getProdServer, deployProdServer, stopProdServer, getProdServerLog },
  }
})

import ProdServerControl from './ProdServerControl'
import { StudioApiError, type StudioProdServer } from './studioApi'
import { renderStudio } from './testUtils'

const URL = 'https://eqp-14409.gb10.jereh-pe.cn/'
const VERSION_URL = 'https://v1-eqp-14409.gb10.jereh-pe.cn/'

function view(over: Partial<StudioProdServer> = {}): StudioProdServer {
  return {
    state: 'stopped',
    url: '',
    versionUrl: '',
    version: '',
    ports: { web: null, api: null },
    step: null,
    failedStep: null,
    message: null,
    deployedAt: null,
    commit: '',
    ...over,
  }
}

async function mountShowing(v: StudioProdServer) {
  getProdServer.mockResolvedValue(v)
  renderStudio(<ProdServerControl projectId="p1" />)
  await screen.findByTestId('prod-server-control')
}

beforeEach(() => {
  vi.clearAllMocks()
  getProdServer.mockResolvedValue(view())
  deployProdServer.mockResolvedValue(view({ state: 'deploying', step: '检查验收' }))
  stopProdServer.mockResolvedValue(view())
  getProdServerLog.mockResolvedValue({ lines: ['pnpm build', 'ERR build failed'] })
})

describe('ProdServerControl', () => {
  it('查询中：the buttons are disabled until the first answer lands', async () => {
    let resolveRead: (v: StudioProdServer) => void = () => {}
    getProdServer.mockReturnValue(
      new Promise<StudioProdServer>((res) => {
        resolveRead = res
      }),
    )
    renderStudio(<ProdServerControl projectId="p1" />)
    // a spinner over a button that might be the wrong action: 「部署到正式服务器」
    // for a server that is already live would be a 409 dance
    expect(await screen.findByTestId('prod-server-control')).toBeInTheDocument()
    expect(screen.getByTestId('prod-server-deploy')).toBeDisabled()
    expect(screen.queryByTestId('prod-server-stop')).not.toBeInTheDocument()
    resolveRead(view())
    await waitFor(() =>
      expect(screen.getByTestId('prod-server-deploy')).toBeEnabled(),
    )
  })

  it('stopped: a 部署 button and no URL', async () => {
    await mountShowing(view())
    expect(await screen.findByTestId('prod-server-dot-stopped')).toBeInTheDocument()
    expect(screen.getByTestId('prod-server-deploy')).toHaveTextContent(
      'Confirm release',
    )
    expect(screen.queryByTestId('prod-server-url')).not.toBeInTheDocument()
    expect(screen.queryByTestId('prod-server-stop')).not.toBeInTheDocument()
  })

  it('a 409 not_accepted is one grey hint line, not an error', async () => {
    const user = userEvent.setup()
    await mountShowing(view())
    deployProdServer.mockRejectedValue(
      new StudioApiError(409, 'not_accepted', '先通过验收（最新一次验收要通过，且之后没有新提交）'),
    )
    await user.click(screen.getByTestId('prod-server-deploy'))
    const hint = await screen.findByTestId('prod-server-hint')
    expect(hint).toHaveTextContent('Pass acceptance first')
    // it is a precondition, not a failure: nothing red, and the deploy button is
    // still there for the next try
    expect(screen.queryByTestId('prod-server-action-error')).not.toBeInTheDocument()
    expect(screen.getByTestId('prod-server-deploy')).toBeEnabled()
  })

  it('deploying: the step name the backend is on, verbatim', async () => {
    await mountShowing(
      view({
        state: 'deploying',
        step: '构建',
        url: URL,
        versionUrl: VERSION_URL,
        version: 'v2',
      }),
    )
    expect(await screen.findByTestId('prod-server-dot-deploying')).toBeInTheDocument()
    expect(screen.getByTestId('prod-server-step')).toHaveTextContent('Deploying: 构建')
    // a half-deployed site is not a site: no URL link, no version badge yet
    expect(screen.queryByTestId('prod-server-url')).not.toBeInTheDocument()
    expect(screen.queryByTestId('prod-server-version')).not.toBeInTheDocument()
    // 停止 stays clickable so a hung build is cancellable
    expect(screen.getByTestId('prod-server-stop')).toBeEnabled()
    expect(screen.getByTestId('prod-server-deploy')).toBeDisabled()
  })

  it('running: the fixed URL with the right href, the version, and 重新部署', async () => {
    const user = userEvent.setup()
    await mountShowing(
      view({
        state: 'running',
        url: URL,
        versionUrl: VERSION_URL,
        version: 'v3',
        ports: { web: 7001, api: 7000 },
        deployedAt: '2026-10-09T10:00:00Z',
        commit: 'abc1234',
      }),
    )
    const link = await screen.findByTestId('prod-server-url')
    // the FIXED url, not the versioned one — the stable address is what you share
    expect(link).toHaveAttribute('href', URL)
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    expect(screen.getByTestId('prod-server-version')).toHaveTextContent('Version v3')
    expect(screen.getByTestId('prod-server-dot-running')).toBeInTheDocument()
    expect(screen.getByTestId('prod-server-deploy')).toHaveTextContent('Release again')

    await user.click(screen.getByTestId('prod-server-stop'))
    expect(stopProdServer).toHaveBeenCalledWith('p1')
    await waitFor(() =>
      expect(
        within(screen.getByTestId('prod-server-control')).getByText('Not deployed'),
      ).toBeInTheDocument(),
    )
  })

  it('failed: the backend message verbatim, step name and all', async () => {
    // The shape prodserver._fail writes: 「<步骤名>失败：<原文>」. Re-templating the
    // step here would print it twice; the tail is the only copy of the real error.
    const message = '构建失败：pnpm build:web 退出码 1：ERR Missing dependency'
    await mountShowing(view({ state: 'failed', failedStep: '构建', message }))
    const err = await screen.findByTestId('prod-server-error')
    expect(err.textContent).toBe(message)
    expect(await screen.findByTestId('prod-server-dot-failed')).toBeInTheDocument()
    // a failed project is deployable again — that is the point of naming the step
    expect(screen.getByTestId('prod-server-deploy')).toBeEnabled()
  })

  it('the log toggle pulls the tail and shows it', async () => {
    const user = userEvent.setup()
    await mountShowing(view({ state: 'failed', failedStep: '构建', message: 'x' }))
    await user.click(screen.getByTestId('prod-server-log-toggle'))
    const log = await screen.findByTestId('prod-server-log')
    expect(log).toHaveTextContent('ERR build failed')
    expect(getProdServerLog).toHaveBeenCalledWith('p1', 80)
    await user.click(screen.getByTestId('prod-server-log-toggle'))
    expect(screen.queryByTestId('prod-server-log')).not.toBeInTheDocument()
  })

  it('another refusal is shown as an error, not as the acceptance hint', async () => {
    const user = userEvent.setup()
    await mountShowing(view())
    deployProdServer.mockRejectedValue(new StudioApiError(409, 'already_deploying', '部署正在进行中'))
    await user.click(screen.getByTestId('prod-server-deploy'))
    expect(await screen.findByTestId('prod-server-action-error')).toHaveTextContent(
      '部署正在进行中',
    )
    expect(screen.queryByTestId('prod-server-hint')).not.toBeInTheDocument()
  })
})
