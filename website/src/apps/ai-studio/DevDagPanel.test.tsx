// The 开发 tab's board (ACP-2085-S4 §5). The board reads the backend's state
// file through three endpoints, so the injected `api` is the whole fixture: one
// canned dag per scenario plus the two actions. Every assertion goes through a
// data-testid or the rendered words — design 07 §颗粒度约定 makes the testids the
// contract and the four node words the only legal status text.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import DevDagPanel from './DevDagPanel'
import ToolSidebar from './ToolSidebar'
import { StudioApiError, type StudioDevBoardApi, type StudioDevDag, type StudioDevNode } from './studioApi'
import { renderStudio } from './testUtils'

function node(jiraKey: string, state: StudioDevNode['state'], over: Partial<StudioDevNode> = {}): StudioDevNode {
  return {
    jiraKey,
    title: `${jiraKey.split(':')[0]}：后端接口`,
    dependsOn: [],
    state,
    slotKey: '',
    startCommit: '',
    endCommit: '',
    message: '',
    ...over,
  }
}

function dag(over: Partial<StudioDevDag> = {}): StudioDevDag {
  return {
    runId: 'dev-1',
    phase: 'full',
    runState: 'idle',
    graphHashes: {},
    nodes: [],
    ...over,
  }
}

function apiOver(over: Partial<StudioDevBoardApi> = {}): StudioDevBoardApi {
  return {
    startDev: vi.fn(async () => ({ runId: 'dev-1', phase: 'full' })),
    getDevDag: vi.fn(async () => dag()),
    getDevLog: vi.fn(async () => ({ lines: ['12:00:00 start dev-1', '12:00:01 node start 设备点检记录:api'] })),
    runAccept: vi.fn(async () => ({
      record: {
        id: 'acc-1', phase: 'full', result: 'passed' as const, voided: false,
        results: [{ id: 'pnpm typecheck', ok: true, tail: '' }],
        requirementVersion: '设备点检记录:a1', commitHash: 'c1', at: '2026-10-08T10:00:00Z',
      },
    })),
    listAcceptRecords: vi.fn(async () => ({ records: [] })),
    ...over,
  }
}

function mount(api: StudioDevBoardApi = apiOver()) {
  renderStudio(<DevDagPanel projectId="p1" api={api} />)
  return api
}

/** Mount and wait for the board's FIRST real read. The shell paints immediately
 * (an idle board is a legitimate first paint, not a spinner), so an assertion
 * taken straight after mount sees 空闲 and zero rows — waiting on the run line is
 * waiting on the one read every scenario varies. */
async function mountShowing(runState: StudioDevDag['runState'], api: StudioDevBoardApi) {
  mount(api)
  const expected = { idle: 'Idle', running: 'Developing', done: 'Completed', failed: 'Failed' }[runState]
  await waitFor(() => expect(screen.getByTestId('ai-studio-dev-status')).toHaveTextContent(expected))
  return api
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('DevDagPanel — the four node states', () => {
  it('renders one row per task with exactly the four status words', async () => {
    await mountShowing(
      'running',
      apiOver({
        getDevDag: vi.fn(async () =>
          dag({
            runState: 'running',
            nodes: [
              node('设备点检记录:api', 'done'),
              node('设备点检记录:web', 'running'),
              node('备件台账:api', 'queued'),
              node('备件台账:web', 'failed', { message: '失败：单测没过' }),
            ],
          }),
        ),
      }),
    )
    const dagBox = screen.getByTestId('ai-studio-dev-dag')
    // one row per task: the rows are the container's direct children, each keyed
    // by its own testid (07 §颗粒度约定: 前台断言只认 data-testid)
    expect(dagBox.children).toHaveLength(4)

    const state = (key: string) => within(dagBox).getByTestId(`ai-studio-dev-dag-node-state-${key}`)
    expect(state('设备点检记录:api')).toHaveTextContent('Done')
    expect(state('设备点检记录:web')).toHaveTextContent('In progress')
    expect(state('备件台账:api')).toHaveTextContent('Queued')
    expect(state('备件台账:web')).toHaveTextContent('Failed')
    // a failed node shows the assistant's own line, unedited
    expect(within(dagBox).getByTestId('ai-studio-dev-dag-node-message-备件台账:web')).toHaveTextContent(
      '失败：单测没过',
    )
    // the run line says 开发中 while a node is in flight
    expect(screen.getByTestId('ai-studio-dev-status')).toHaveTextContent('Developing')
  })

  it('idle: no rows, and the whole run line reads 空闲', async () => {
    mount()
    await screen.findByTestId('ai-studio-dev-dag')
    expect(screen.getByTestId('ai-studio-dev-status')).toHaveTextContent('Idle')
    expect(screen.getByTestId('ai-studio-dev-dag-empty')).toBeInTheDocument()
    // an idle board offers no acceptance: 跑验收 belongs to an all-green round
    expect(screen.queryByTestId('ai-studio-accept-run-btn')).not.toBeInTheDocument()
  })

  it('failed: the start button becomes 「Continue from the failure」', async () => {
    await mountShowing(
      'failed',
      apiOver({ getDevDag: vi.fn(async () => dag({ runState: 'failed', nodes: [node('a:api', 'failed')] })) }),
    )
    expect(screen.getByTestId('ai-studio-dev-start-btn')).toHaveTextContent('Continue from the failure')
  })

  it('completed: the run line reads 已完成', async () => {
    await mountShowing(
      'done',
      apiOver({ getDevDag: vi.fn(async () => dag({ runState: 'done', nodes: [node('a:api', 'done')] })) }),
    )
  })
})

describe('DevDagPanel — starting a round', () => {
  it('the button asks first, and 取消 sends nothing', async () => {
    const user = userEvent.setup()
    const api = mount()
    await screen.findByTestId('ai-studio-dev-dag')
    await user.click(screen.getByTestId('ai-studio-dev-start-btn'))
    // the consequence is spelled out before anything happens
    expect(await screen.findByTestId('ai-studio-dev-confirm')).toHaveTextContent(
      'writes code in this workspace and commits',
    )
    await user.click(screen.getByTestId('ai-studio-dev-confirm-cancel'))
    expect(screen.queryByTestId('ai-studio-dev-confirm')).not.toBeInTheDocument()
    expect(api.startDev).not.toHaveBeenCalled()
  })

  it('确认 starts the run and the board re-reads', async () => {
    const user = userEvent.setup()
    const api = mount()
    await screen.findByTestId('ai-studio-dev-dag')
    await user.click(screen.getByTestId('ai-studio-dev-start-btn'))
    await user.click(await screen.findByTestId('ai-studio-dev-confirm-ok'))
    await waitFor(() => expect(api.startDev).toHaveBeenCalledWith('p1'))
    // pages omitted: the backend picks every page whose verdict allows it
    expect((api.startDev as ReturnType<typeof vi.fn>).mock.calls[0][1]).toBeUndefined()
    await waitFor(() => expect(api.getDevDag).toHaveBeenCalledTimes(2))
  })

  it('running: the button is disabled, so a second round cannot be started by accident', async () => {
    const user = userEvent.setup()
    const api = await mountShowing(
      'running',
      apiOver({ getDevDag: vi.fn(async () => dag({ runState: 'running', nodes: [node('a:api', 'running')] })) }),
    )
    const btn = screen.getByTestId('ai-studio-dev-start-btn')
    expect(btn).toBeDisabled()
    await user.click(btn)
    expect(screen.queryByTestId('ai-studio-dev-confirm')).not.toBeInTheDocument()
    expect(api.startDev).not.toHaveBeenCalled()
  })

  it('a not_ready refusal is shown verbatim — the page names are the payload', async () => {
    const user = userEvent.setup()
    const api = mount(
      apiOver({
        startDev: vi.fn(async () => {
          throw new StudioApiError(422, 'not_ready', '不齐：还不能开发：设备点检记录')
        }),
      }),
    )
    await screen.findByTestId('ai-studio-dev-dag')
    await user.click(screen.getByTestId('ai-studio-dev-start-btn'))
    await user.click(await screen.findByTestId('ai-studio-dev-confirm-ok'))
    // NOT re-worded from the code: which page to go finish is the whole message,
    // and a translated template would drop it.
    expect(await screen.findByTestId('ai-studio-dev-error')).toHaveTextContent('不齐：还不能开发：设备点检记录')
  })

  it('a refusal whose code has its own copy is rendered localized', async () => {
    const user = userEvent.setup()
    const api = mount(
      apiOver({
        startDev: vi.fn(async () => {
          throw new StudioApiError(422, 'no_pages', "no page's requirement is ready for development")
        }),
      }),
    )
    await screen.findByTestId('ai-studio-dev-dag')
    await user.click(screen.getByTestId('ai-studio-dev-start-btn'))
    await user.click(await screen.findByTestId('ai-studio-dev-confirm-ok'))
    // the test locale is en; the point is that the panel keyed off `code` and did
    // not surface the backend's English sentence
    expect(await screen.findByTestId('ai-studio-dev-error')).toHaveTextContent(
      "No page's requirement is complete enough to develop",
    )
  })
})

describe('DevDagPanel — the log', () => {
  it('collapsed by default, and expanding pulls the tail', async () => {
    const user = userEvent.setup()
    const api = mount()
    await screen.findByTestId('ai-studio-dev-dag')
    expect(screen.queryByTestId('ai-studio-dev-dag-log')).not.toBeInTheDocument()
    expect(api.getDevLog).not.toHaveBeenCalled()
    await user.click(screen.getByTestId('ai-studio-dev-log-toggle'))
    expect(await screen.findByTestId('ai-studio-dev-dag-log')).toHaveTextContent('node start 设备点检记录:api')
    expect(api.getDevLog).toHaveBeenCalledWith('p1', 100)
  })
})

describe('DevDagPanel — acceptance', () => {
  const doneDag = dag({ runState: 'done', nodes: [node('a:api', 'done'), node('a:web', 'done')] })

  it('the block appears only once every node is done', async () => {
    mount(apiOver({ getDevDag: vi.fn(async () => dag({ runState: 'running', nodes: [node('a:api', 'done'), node('a:web', 'queued')] })) }))
    await screen.findByTestId('ai-studio-dev-dag')
    // 不许假全绿 (07 §D2): a green-looking list with a queued node offers no acceptance
    expect(screen.queryByTestId('ai-studio-accept-run-btn')).not.toBeInTheDocument()
  })

  it('running acceptance shows the result rows and their commands', async () => {
    const user = userEvent.setup()
    const api = mount(
      apiOver({
        getDevDag: vi.fn(async () => doneDag),
        listAcceptRecords: vi.fn(async () => ({ records: [] })),
      }),
    )
    await screen.findByTestId('ai-studio-accept-run-btn')
    await user.click(screen.getByTestId('ai-studio-accept-run-btn'))
    const list = await screen.findByTestId('ai-studio-accept-result-list')
    expect(within(list).getByTestId('ai-studio-accept-result-row-0')).toHaveTextContent('pnpm typecheck')
    expect(screen.getByTestId('ai-studio-accept-status')).toHaveTextContent('Passed')
    expect(api.runAccept).toHaveBeenCalledWith('p1')
  })

  it('a failed acceptance reports the count and the failing command’s tail', async () => {
    const record = {
      id: 'acc-2',
      phase: 'full',
      result: 'failed' as const,
      voided: false,
      results: [
        { id: 'pnpm typecheck', ok: true, tail: '' },
        { id: 'pnpm test:unit', ok: false, tail: 'FAIL src/a.spec.ts\n2 failed' },
      ],
      requirementVersion: 'a:h1',
      commitHash: 'c2',
      at: '2026-10-08T11:00:00Z',
    }
    mount(apiOver({ getDevDag: vi.fn(async () => doneDag), listAcceptRecords: vi.fn(async () => ({ records: [record] })) }))
    expect(await screen.findByTestId('ai-studio-accept-status')).toHaveTextContent('Failed (1 checks)')
    const row = await screen.findByTestId('ai-studio-accept-result-row-1')
    expect(row).toHaveTextContent('pnpm test:unit')
    expect(row).toHaveTextContent('FAIL src/a.spec.ts')
    // a passing row shows no output block: nothing failed there
    expect(within(screen.getByTestId('ai-studio-accept-result-list')).getByTestId('ai-studio-accept-result-row-0')).toHaveTextContent('pnpm typecheck')
  })

  it('refusal (dev not done) is shown instead of a status', async () => {
    const user = userEvent.setup()
    mount(
      apiOver({
        getDevDag: vi.fn(async () => doneDag),
        runAccept: vi.fn(async () => {
          throw new Error('dev not done')
        }),
      }),
    )
    await screen.findByTestId('ai-studio-accept-run-btn')
    await user.click(screen.getByTestId('ai-studio-accept-run-btn'))
    expect(await screen.findByTestId('ai-studio-dev-error')).toHaveTextContent('dev not done')
    expect(screen.queryByTestId('ai-studio-accept-status')).not.toBeInTheDocument()
  })
})

describe('the board in the 开发 tab (07 §〇-1)', () => {
  it('the tab is reachable by testid and holds the board when the page injects it', async () => {
    const user = userEvent.setup()
    const api = apiOver()
    renderStudio(
      <ToolSidebar
        onOpenTab={vi.fn()}
        docs={[]}
        projectId="p1"
        initialTool="dev"
        devBoard={<DevDagPanel projectId="p1" api={api} />}
      />,
    )
    expect(screen.getByTestId('ai-studio-dev-entry')).toBeInTheDocument()
    expect(screen.getByTestId('ai-studio-dev-entry')).toHaveAttribute('aria-selected', 'true')
    expect(await screen.findByTestId('ai-studio-dev-start-btn')).toBeInTheDocument()
    await waitFor(() => expect(api.getDevDag).toHaveBeenCalledWith('p1'))
  })

  it('a caller that injects no board keeps the tab exactly as it was, fetches included', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    renderStudio(<ToolSidebar onOpenTab={vi.fn()} docs={[]} projectId="p1" initialTool="dev" />)
    await screen.findByTestId('tool-sidebar')
    expect(screen.getByText('dev-309')).toBeInTheDocument()
    expect(fetchSpy).not.toHaveBeenCalled()
    fetchSpy.mockRestore()
  })
})
