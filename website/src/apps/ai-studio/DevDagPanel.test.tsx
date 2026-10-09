// The 开发 tab's board (ACP-2085-S4 §5). The board reads the backend's state
// file through three endpoints, so the injected `api` is the whole fixture: one
// canned dag per scenario plus the two actions. Every assertion goes through a
// data-testid or the rendered words — design 07 §颗粒度约定 makes the testids the
// contract and the four node words the only legal status text.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import DevDagPanel, { REFRESH_SLOW_MS, StartDevContext } from './DevDagPanel'
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
    // the split defaults to 「建好了」：一个节点默认带着 Jira 号，因为接了 Jira
    // 的部署上每个任务都该有一张单，测试要单独构造的是「没建出来」那种例外。
    jira: `ACP-${7000 + jiraKey.length}`,
    jiraUrl: `https://jira.jereh.cn/browse/ACP-${7000 + jiraKey.length}`,
    jiraError: '',
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
    planDev: vi.fn(async () => dag({ runState: 'planned', nodes: [node('设备点检记录:api', 'queued')] })),
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
    fixAccept: vi.fn(async () => ({ runId: 'dev-2', phase: 'full' })),
    ...over,
  }
}

/** The 需求 tab's 〔开始开发〕 click, as RequirementPage actually fires it. */
function fireStartDev(projectId: string, page?: string) {
  window.dispatchEvent(new CustomEvent('ai-studio:start-dev', { detail: { projectId, page } }))
}

function mount(api: StudioDevBoardApi = apiOver()) {
  renderStudio(<DevDagPanel projectId="p1" api={api} />)
  return api
}

/** Mount and wait for the board's FIRST real read. The shell paints immediately
 * (an idle board is a legitimate first paint, not a spinner), so an assertion
 * taken straight after mount sees 空闲 and zero rows — waiting on the run line is
 * waiting on the one read every scenario varies. */
const RUN_WORDS: Record<StudioDevDag['runState'], string> = {
  idle: 'Idle',
  planned: 'Tasks split',
  running: 'Developing',
  done: 'Completed',
  failed: 'Failed',
}

async function mountShowing(runState: StudioDevDag['runState'], api: StudioDevBoardApi) {
  mount(api)
  await waitFor(() =>
    expect(screen.getByTestId('ai-studio-dev-status')).toHaveTextContent(RUN_WORDS[runState]),
  )
  return api
}

beforeEach(() => {
  vi.clearAllMocks()
})

// 请求存在 ToolSidebar 的 state 里，卸载即消失，没有跨测试的残留要清；这里只
// 负责把假计时器换回真的（有用到 vi.useFakeTimers 的那条测试自己换的，兜底）。
afterEach(() => {
  vi.useRealTimers()
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

  it('ACP-2207: an in-flight row names its own worktree, no other row does', async () => {
    // 并行开发时看板上两行「进行中」长得一模一样，隔离有没有发生就看不出来 ——
    // 这一格路径就是「它俩真的在两个目录里写」的唯一凭据（07 §四-1 的实测口径）。
    // 只在 in progress 时渲染：合完并后端就把这一格清空了，已完成还挂着一个已经
    // 删掉的目录等于撒谎；排队的行更没有目录。
    const api = apiOver({
      getDevDag: vi.fn(async () =>
        dag({
          runState: 'running',
          nodes: [
            node('设备点检记录:api', 'running', {
              worktree: '/ws/.ai-studio/wt/1',
              branch: 'dev/设备点检记录-api',
            }),
            node('备件台账:api', 'running', {
              worktree: '/ws/.ai-studio/wt/3',
              branch: 'dev/备件台账-api',
            }),
            // 串行轮次（并行度 1）根本没有 worktree 这一说，后端不回这一格
            node('备件台账:web', 'running'),
            node('报废申请:api', 'queued', { worktree: '/ws/.ai-studio/wt/4' }),
            node('报废申请:web', 'done', { worktree: '/ws/.ai-studio/wt/5' }),
          ],
        }),
      ),
    })
    await mountShowing('running', api)
    const dagBox = screen.getByTestId('ai-studio-dev-dag')

    const tree = (key: string) => within(dagBox).queryByTestId(`ai-studio-dev-dag-node-worktree-${key}`)
    expect(tree('设备点检记录:api')).toHaveTextContent('/ws/.ai-studio/wt/1')
    expect(tree('备件台账:api')).toHaveTextContent('/ws/.ai-studio/wt/3')
    // 两条路径不同这件事，是这一格存在的全部理由
    expect(tree('设备点检记录:api')!.textContent).not.toBe(tree('备件台账:api')!.textContent)
    expect(tree('备件台账:web')).not.toBeInTheDocument()
    expect(tree('报废申请:api')).not.toBeInTheDocument()
    expect(tree('报废申请:web')).not.toBeInTheDocument()
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

  // ACP-2210: the way out of a red acceptance. Before this the block printed
  // 「失败 2 条」 and stopped — the operator had to go open a terminal.
  describe('〔让助手修复〕', () => {
    const failedRecord = {
      id: 'acc-9',
      phase: 'full',
      result: 'failed' as const,
      voided: false,
      results: [
        { id: 'pnpm typecheck', ok: true, tail: '' },
        {
          id: 'pnpm test:unit',
          ok: false,
          tail: 'FAIL src/a.spec.ts',
          logPath: '.ai-studio/accept/acc-9-1.log',
        },
      ],
      requirementVersion: 'a:h1',
      commitHash: 'c9',
      at: '2026-10-10T11:00:00Z',
    }
    const failedDag = dag({
      runState: 'done',
      nodes: [node('a:api', 'done'), node('a:web', 'done')],
    })

    function withFailures(over: Partial<StudioDevBoardApi> = {}): StudioDevBoardApi {
      return apiOver({
        getDevDag: vi.fn(async () => failedDag),
        listAcceptRecords: vi.fn(async () => ({ records: [failedRecord] })),
        ...over,
      })
    }

    it('a failed acceptance offers the fix and a click schedules it', async () => {
      const user = userEvent.setup()
      const api = mount(withFailures())
      const btn = await screen.findByTestId('ai-studio-accept-fix-btn')
      expect(screen.getByTestId('ai-studio-accept-status')).toHaveTextContent('Failed (1 checks)')
      await user.click(btn)
      expect(api.fixAccept).toHaveBeenCalledWith('p1')
      // the board re-reads rather than inventing the fix row locally: the node
      // list is the backend's file, and the new row appears when it does
      await waitFor(() =>
        expect(vi.mocked(api.getDevDag).mock.calls.length).toBeGreaterThan(1),
      )
    })

    it('a passing acceptance offers nothing to fix', async () => {
      mount(
        apiOver({
          getDevDag: vi.fn(async () => doneDag),
          listAcceptRecords: vi.fn(async () => ({
            records: [
              {
                ...failedRecord,
                result: 'passed' as const,
                // a green record has no red row — the backend derives `result`
                // from the rows, so a fixture with both would be unconstructable
                results: [{ id: 'pnpm typecheck', ok: true, tail: '' }],
              },
            ],
          })),
        }),
      )
      expect(await screen.findByTestId('ai-studio-accept-status')).toHaveTextContent('Passed')
      expect(screen.queryByTestId('ai-studio-accept-fix-btn')).not.toBeInTheDocument()
      expect(screen.queryByTestId('ai-studio-accept-fix-exhausted')).not.toBeInTheDocument()
    })

    it('three repairs later the button is gone and the board says 请人工处理', async () => {
      // the reachable shape: three fixes that each COMMITTED (so the run is
      // `done` again) and the acceptance after the third one is still red. A fix
      // node that itself failed would put the run at `failed`, where this block
      // is not rendered at all — that round needs 从失败处继续, not this message.
      const three = dag({
        runState: 'done',
        nodes: [
          node('a:api', 'done'),
          node('a:web', 'done'),
          node('fix:1', 'done', { kind: 'fix', title: '修复验收失败（第 1 次）' }),
          node('fix:2', 'done', { kind: 'fix', title: '修复验收失败（第 2 次）' }),
          node('fix:3', 'done', { kind: 'fix', title: '修复验收失败（第 3 次）' }),
        ],
      })
      mount(
        withFailures({
          getDevDag: vi.fn(async () => three),
          fixAccept: vi.fn(async () => {
            throw new Error('must not be callable')
          }),
        }),
      )
      expect(await screen.findByTestId('ai-studio-accept-status')).toHaveTextContent('Failed (1 checks)')
      expect(screen.queryByTestId('ai-studio-accept-fix-btn')).not.toBeInTheDocument()
      // the copy is the ticket's, verbatim — its absence would read as a bug
      expect(screen.getByTestId('ai-studio-accept-fix-exhausted')).toHaveTextContent(
        'Still failing after 3 repairs',
      )
    })

    it('a fix that finishes on its own brings its new result onto the board', async () => {
      // ACP-2210's last inch: after 〔让助手修复〕 the round runs elsewhere (a
      // session, minutes later) and the platform re-accepts by itself. This tab
      // clicked nothing at that moment, so the ONLY thing that can put the new
      // record on screen is the records read polling — the manual cache write in
      // runAccept cannot help, because no runAccept ran here.
      vi.useFakeTimers({ shouldAdvanceTime: true })
      try {
        const later = { ...failedRecord, id: 'acc-10', result: 'passed' as const, results: [{ id: 'pnpm typecheck', ok: true, tail: '' }] }
        let reads = 0
        const api = withFailures({
          listAcceptRecords: vi.fn(async () => ({ records: ++reads === 1 ? [failedRecord] : [later] })),
        })
        mount(api)
        await waitFor(() => expect(api.listAcceptRecords).toHaveBeenCalledTimes(1), { timeout: 3000 })
        expect(screen.getByTestId('ai-studio-accept-status')).toHaveTextContent('Failed (1 checks)')

        await act(async () => {
          await vi.advanceTimersByTimeAsync(REFRESH_SLOW_MS)
        })
        await waitFor(
          () => expect(screen.getByTestId('ai-studio-accept-status')).toHaveTextContent('Passed'),
          { timeout: 3000 },
        )
        // and with nothing failed there is no button to offer any more
        expect(screen.queryByTestId('ai-studio-accept-fix-btn')).not.toBeInTheDocument()
      } finally {
        vi.useRealTimers()
      }
    })

    it('a refused fix is shown as a notice, not a silent no-op', async () => {
      const user = userEvent.setup()
      const api = mount(
        withFailures({
          fixAccept: vi.fn(async () => {
            throw new StudioApiError(409, 'nothing_to_fix', 'nothing to fix')
          }),
        }),
      )
      await user.click(await screen.findByTestId('ai-studio-accept-fix-btn'))
      // localized off the machine code, like every other refusal here
      expect(await screen.findByTestId('ai-studio-dev-error')).toHaveTextContent(
        'There is nothing to fix in the latest acceptance result',
      )
      expect(api.fixAccept).toHaveBeenCalledTimes(1)
    })
  })

  // ACP-2226: the quality gates. The board's job here is one sentence — say these
  // are advice, so a red 「AC 没有测试引用」 under a 「通过」 record reads as a
  // report and not as a broken acceptance run.
  describe('质量检查（仅提示）', () => {
    const advisory = [
      { id: 'ac-coverage', ok: false, missing: [{ page: '备件台账', id: 'AC-3' }, { page: '备件台账', id: 'AC-4' }] },
      { id: 'weakened-tests', ok: true, missing: [] },
      { id: 'lint', ok: true, skipped: true, detail: '工作区没有 lint 脚本' },
      { id: 'schema-requirements', ok: true, missing: [{ page: 'p', code: 'spareNo', column: 'spare_no' }] },
    ]
    const greenWithAdvisory = {
      id: 'acc-11',
      phase: 'full',
      result: 'passed' as const,
      voided: false,
      results: [{ id: 'pnpm typecheck', ok: true, tail: '' }],
      requirementVersion: 'a:h1',
      commitHash: 'c11',
      at: '2026-10-10T12:00:00Z',
      advisory,
      strict: false,
    }

    function withAdvisory(record: object) {
      return apiOver({
        getDevDag: vi.fn(async () => doneDag),
        listAcceptRecords: vi.fn(async () => ({ records: [record] })),
      })
    }

    it('lists one row per gate with the advisory heading', async () => {
      mount(withAdvisory(greenWithAdvisory))
      const block = await screen.findByTestId('ai-studio-accept-advisory')
      expect(block).toHaveTextContent('Quality checks (advisory only)')
      expect(within(block).getByTestId('ai-studio-accept-advisory-ac-coverage')).toHaveTextContent(
        'Requirement acceptance criteria covered by tests',
      )
      expect(within(block).getByTestId('ai-studio-accept-advisory-lint')).toHaveTextContent(
        '工作区没有 lint 脚本',
      )
      // the count is the row's only datum on a red gate: the board cannot name
      // which ACs without a second read, and a number beats nothing
      expect(within(block).getByTestId('ai-studio-accept-advisory-ac-coverage')).toHaveTextContent(
        '2 items',
      )
      expect(within(block).getByTestId('ai-studio-accept-advisory-schema-requirements')).toBeInTheDocument()
    })

    it('the heading becomes 拦截 under strict', async () => {
      mount(withAdvisory({ ...greenWithAdvisory, strict: true }))
      const block = await screen.findByTestId('ai-studio-accept-advisory')
      expect(block).toHaveTextContent('Quality checks (blocking)')
      expect(block).not.toHaveTextContent('advisory only')
    })

    it('an advisory red does not rewrite the pass status', async () => {
      // THE case for the whole feature: the record says passed and a gate says
      // ✗. If the board derived its colour from the gates, 「跑验收」 would look
      // broken — the deploy gate reads `result`, and this is the same promise.
      mount(withAdvisory(greenWithAdvisory))
      expect(await screen.findByTestId('ai-studio-accept-status')).toHaveTextContent('Passed')
      expect(screen.getByTestId('ai-studio-accept-advisory-ac-coverage')).toHaveTextContent('✗')
      // and the pass offered nothing to fix, unchanged by the advisory
      expect(screen.queryByTestId('ai-studio-accept-fix-btn')).not.toBeInTheDocument()
    })

    it('a record written before the gates renders no advisory block', async () => {
      // Additive fields mean records on disk from the previous release have no
      // `advisory`. A block that rendered 「0 项」 there would claim a check ran.
      mount(
        withAdvisory({
          id: 'acc-old',
          phase: 'full',
          result: 'passed' as const,
          voided: false,
          results: [{ id: 'pnpm typecheck', ok: true, tail: '' }],
          requirementVersion: 'a:h1',
          commitHash: 'c0',
          at: '2026-10-08T10:00:00Z',
        }),
      )
      expect(await screen.findByTestId('ai-studio-accept-status')).toHaveTextContent('Passed')
      expect(screen.queryByTestId('ai-studio-accept-advisory')).not.toBeInTheDocument()
    })
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

describe('DevDagPanel — 先拆任务，Jira 号（ACP-2085-S6）', () => {
  const planned = dag({
    runState: 'planned',
    jiraParent: 'ACP-8000',
    jiraParentUrl: 'https://jira.jereh.cn/browse/ACP-8000',
    nodes: [
      node('设备点检记录:api', 'queued', { jira: 'ACP-9001', jiraUrl: 'https://jira.jereh.cn/browse/ACP-9001' }),
      node('设备点检记录:web', 'queued', {
        jira: '', jiraUrl: '', jiraError: 'jc 连不上 jira：connection refused',
      }),
    ],
  })

  it('〔拆分任务〕 calls dev/plan and the rows carry the Jira numbers', async () => {
    const user = userEvent.setup()
    let reads = 0
    // the button exists to TURN this board into that one, so the read is staged:
    // idle and empty until the click, then the split board. Asserting the numbers
    // afterwards is what proves the click is what built the list.
    const api = apiOver({
      // 第一次读还是空的，点了拆分之后才变成分好的那份板
      getDevDag: vi.fn(async () => (++reads === 1 ? dag() : planned)),
    })
    mount(api)
    await screen.findByTestId('ai-studio-dev-dag-empty')
    expect(screen.queryByTestId('ai-studio-dev-dag-jira-parent')).not.toBeInTheDocument()
    const btn = screen.getByTestId('ai-studio-dev-plan-btn')
    await user.click(btn)
    // pages omitted = every page whose verdict allows it, same as 开始开发。
    // 断的是两个字面参数：按钮不带页名调过来，第二个参数就是 undefined
    await waitFor(() => expect(api.planDev).toHaveBeenCalledWith('p1', undefined))
    expect(api.startDev).not.toHaveBeenCalled()

    const dagBox = await screen.findByTestId('ai-studio-dev-dag')
    const link = within(dagBox).getByTestId('ai-studio-dev-dag-node-jira-设备点检记录:api')
    expect(link).toHaveTextContent('ACP-9001')
    expect(link).toHaveAttribute('href', 'https://jira.jereh.cn/browse/ACP-9001')
    // 新标签打开：点了不许把这块板换掉
    expect(link).toHaveAttribute('target', '_blank')
    // 表头那一行是父单
    const parent = screen.getByTestId('ai-studio-dev-dag-jira-parent')
    expect(parent).toHaveTextContent('ACP-8000')
    expect(parent).toHaveAttribute('href', 'https://jira.jereh.cn/browse/ACP-8000')
    // 状态从「空闲」变「已拆任务」，任务一行行列出来了
    await waitFor(() => expect(screen.getByTestId('ai-studio-dev-status')).toHaveTextContent('Tasks split'))
    expect(dagBox.children).toHaveLength(2)
  })

  it('a row with no Jira issue says why, verbatim', async () => {
    mount(apiOver({ getDevDag: vi.fn(async () => planned) }))
    const dagBox = await screen.findByTestId('ai-studio-dev-dag')
    const row = await within(dagBox).findByTestId('ai-studio-dev-dag-node-jira-missing-设备点检记录:web')
    // 「Jira 未建：<命令原文>」—— 原文不许被改写成一句通用报错
    expect(row).toHaveTextContent('No Jira issue: jc 连不上 jira：connection refused')
    // 有号的那一行不出现灰字，没号的那一行也不出现链接
    expect(within(dagBox).getByTestId('ai-studio-dev-dag-node-jira-设备点检记录:api')).toBeInTheDocument()
    expect(within(dagBox).queryByTestId('ai-studio-dev-dag-node-jira-设备点检记录:web')).not.toBeInTheDocument()
  })

  it('a deployment with no Jira configured shows no reason line at all', async () => {
    // 没配 AI_STUDIO_JIRA_CMD 的部署：节点上没号、也没原因。这时灰字一行都不该
    // 有 —— 否则每个没接 Jira 的实例都会看见四条看不懂的报错。
    mount(
      apiOver({
        getDevDag: vi.fn(async () =>
          dag({
            runState: 'planned',
            nodes: [node('x:api', 'queued', { jira: '', jiraUrl: '', jiraError: '' })],
          }),
        ),
      }),
    )
    const dagBox = await screen.findByTestId('ai-studio-dev-dag')
    expect(within(dagBox).queryAllByTestId(/ai-studio-dev-dag-node-jira-missing/)).toHaveLength(0)
    expect(screen.queryByText(/No Jira issue/)).not.toBeInTheDocument()
    // 没父单就没有表头那一行，而不是一个点开就 404 的空链接
    expect(screen.queryByTestId('ai-studio-dev-dag-jira-parent')).not.toBeInTheDocument()
  })

  it('planned: 开始开发 is clickable and keeps the same confirm', async () => {
    const user = userEvent.setup()
    const api = apiOver({ getDevDag: vi.fn(async () => planned) })
    mount(api)
    await screen.findByTestId('ai-studio-dev-status')
    const btn = screen.getByTestId('ai-studio-dev-start-btn')
    expect(btn).toBeEnabled()
    await user.click(btn)
    expect(await screen.findByTestId('ai-studio-dev-confirm')).toBeInTheDocument()
    await user.click(screen.getByTestId('ai-studio-dev-confirm-ok'))
    await waitFor(() => expect(api.startDev).toHaveBeenCalledWith('p1'))
    // 拆过了就不再提供「拆分任务」：计划已经在那儿了
    // 实战-4：已拆未开工时允许重新拆分（拆错了要能改），按钮文字变成「重新拆分任务」
    expect(screen.getByTestId('ai-studio-dev-plan-btn')).toHaveTextContent('Split again')
  })

  it('running: no 拆分任务, and the hint names the 3s cadence', async () => {
    // 等的是「开发中」这个词而不是状态块本身：状态块在第一次读之前就是「空闲」，
    // 而「空闲」正是要提供拆分按钮的状态 —— 等错对象就会拿首帧去断。
    await mountShowing('running', apiOver({ getDevDag: vi.fn(async () => dag({ runState: 'running', nodes: [node('a:api', 'running')] })) }))
    expect(screen.queryByTestId('ai-studio-dev-plan-btn')).not.toBeInTheDocument()
    expect(screen.getByTestId('ai-studio-dev-refresh-hint')).toHaveTextContent('Refreshes every 3 seconds')
  })

  it('a planned board still refreshes, every 10s, without a click', async () => {
    // the shape RequirementPage.test.tsx uses: `shouldAdvanceTime` keeps the
    // microtask queue moving (React Query resolves the fetch off a timer) while
    // the 10s clock is still ours to push. `getDevDag` is called once per render
    // cycle at most, so a count is a real measurement, not a race.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      const api = apiOver({ getDevDag: vi.fn(async () => planned) })
      mount(api)
      await waitFor(() => expect(api.getDevDag).toHaveBeenCalledTimes(1), { timeout: 3000 })
      await act(async () => {
        await vi.advanceTimersByTimeAsync(REFRESH_SLOW_MS)
      })
      await waitFor(() => expect(api.getDevDag).toHaveBeenCalledTimes(2), { timeout: 3000 })
      // 小字说明的就是这个节奏
      expect(screen.getByTestId('ai-studio-dev-refresh-hint')).toHaveTextContent('Refreshes every 10 seconds')
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('需求页〔开始开发〕→ 开发页签（ACP-2150/2151）', () => {
  /** The workbench shape: the sidebar owns the tab, the board is injected — and
   * it is created by the CALLER, which is exactly why context (not a prop) is
   * what has to carry the request. */
  function mountSidebar(api: StudioDevBoardApi, initialTool = 'requirements') {
    renderStudio(
      <ToolSidebar
        onOpenTab={vi.fn()}
        docs={[]}
        projectId="p1"
        initialTool={initialTool as 'requirements' | 'dev'}
        devBoard={<DevDagPanel projectId="p1" api={api} />}
      />,
    )
    return api
  }

  it('the event switches to the 开发 tab and splits just that page', async () => {
    const api = mountSidebar(apiOver({ getDevDag: vi.fn(async () => dag({ runState: 'planned' })) }))
    await screen.findByTestId('tool-sidebar')
    // 开局在需求页签，板上无事发生
    expect(screen.getByTestId('ai-studio-dev-entry')).toHaveAttribute('aria-selected', 'false')
    expect(api.planDev).not.toHaveBeenCalled()

    fireStartDev('p1', '设备点检记录')

    // 切页签是页签状态的主人（ToolSidebar）干的，拆任务是板干的 —— 事件到达时
    // 板还没挂载，这一条断的就是那个先后顺序
    await waitFor(() =>
      expect(screen.getByTestId('ai-studio-dev-entry')).toHaveAttribute('aria-selected', 'true'),
    )
    await waitFor(() => expect(api.planDev).toHaveBeenCalledWith('p1', ['设备点检记录']))
    expect(api.startDev).not.toHaveBeenCalled()
  })

  it('another project event switches nothing and splits nothing', async () => {
    const api = mountSidebar(apiOver())
    await screen.findByTestId('tool-sidebar')
    fireStartDev('other-project', '设备点检记录')
    // 让事件循环走一圈再断：detail.projectId 对不上就该什么都不发生
    await act(async () => {
      await Promise.resolve()
    })
    expect(screen.getByTestId('ai-studio-dev-entry')).toHaveAttribute('aria-selected', 'false')
    expect(api.planDev).not.toHaveBeenCalled()
  })

  it('a board already on screen splits the page too, and only once per request', async () => {
    const api = mountSidebar(
      apiOver({ getDevDag: vi.fn(async () => dag({ runState: 'planned' })) }),
      'dev',
    )
    await screen.findByTestId('ai-studio-dev-start-btn')
    fireStartDev('p1', '备件台账')
    await waitFor(() => expect(api.planDev).toHaveBeenCalledWith('p1', ['备件台账']))
    // 同一份请求不许因为板自己的重渲染（拿到数据、10 秒刷新）而重放一遍：
    // 重放就是往 Jira 里再写一轮，哪怕服务端幂等也是白跑
    await waitFor(() => expect(api.getDevDag).toHaveBeenCalledTimes(2))
    expect(api.planDev).toHaveBeenCalledTimes(1)
  })

  it('a page with no page in the detail splits everything', async () => {
    const api = mountSidebar(apiOver(), 'dev')
    await screen.findByTestId('ai-studio-dev-start-btn')
    fireStartDev('p1')
    await waitFor(() => expect(api.planDev).toHaveBeenCalledWith('p1', undefined))
  })
})

describe('a bare board with no sidebar above it', () => {
  it('the context channel is optional: 拆分任务 still works', async () => {
    const api = apiOver({ getDevDag: vi.fn(async () => dag({ runState: 'planned' })) })
    // 直接给一个 StartDevContext null 的树（等价于不套 Provider），证明这条
    // 链路是可选的：老的挂载方式（本文件上面所有测试）不会因为多了一个 context 就坏
    renderStudio(
      <StartDevContext.Provider value={null}>
        <DevDagPanel projectId="p1" api={api} />
      </StartDevContext.Provider>,
    )
    await screen.findByTestId('ai-studio-dev-plan-btn')
    const user = userEvent.setup()
    await user.click(screen.getByTestId('ai-studio-dev-plan-btn'))
    await waitFor(() => expect(api.planDev).toHaveBeenCalledWith('p1', undefined))
  })
})
