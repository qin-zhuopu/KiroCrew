// T7 step 4 (ACP-851): the 开发 tab's real loop. The panel takes its api as
// a prop, so the fake is instrumented: 开始开发 performs exactly ONE
// startDevRun with the page's project and design version, and the run's
// picture is the SHIPPED DevRunPanel drawing the returned record — including
// the honest shapes a real gate produces: a failed middle phase with the
// later phases pending (the gate stopped there), and the wiring refusal
// (503) shown as the backend's sentence instead of a fake run.
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import DevLoopPanel from './DevLoopPanel'
import { StudioApiError, type StudioApi, type StudioDevRun } from './studioApi'

const greenRun: StudioDevRun = {
  id: 'dev-1', designVersion: 'v1 · gate:examples/widget',
  phases: (['tasks', 'implement', 'test', 'build'] as const).map((n) => ({
    name: n, status: 'done' as const, summary: `${n} PASS`,
  })),
  artifacts: [], runnableVersion: 'v1',
}
const failingRun: StudioDevRun = {
  id: 'dev-2', designVersion: 'v1 · gate:examples/widget',
  phases: [
    { name: 'tasks', status: 'done', summary: 'G2 PASS' },
    { name: 'implement', status: 'failed', summary: 'G3 FAIL (exit 1)' },
    { name: 'test', status: 'pending', summary: '' },
    { name: 'build', status: 'pending', summary: '' },
  ],
  artifacts: [],
}

function mount(api: StudioApi, initialRuns: StudioDevRun[] = [], onRan = vi.fn()) {
  render(
    <DevLoopPanel projectId="p1" api={api} initialRuns={initialRuns} designVersion="v1" onRan={onRan} />,
  )
  return onRan
}

describe('DevLoopPanel (T7 step 4)', () => {
  it('开始开发 calls the api once and the shipped panel draws the green run', async () => {
    const api = { startDevRun: vi.fn(async () => ({ run: greenRun })) } as unknown as StudioApi
    const onRan = mount(api)
    await userEvent.click(screen.getByTestId('dev-start-btn'))
    await waitFor(() => expect(api.startDevRun).toHaveBeenCalledTimes(1))
    expect(api.startDevRun).toHaveBeenCalledWith('p1', 'v1')
    expect(onRan).toHaveBeenCalledTimes(1)
    // the SHIPPED DevRunPanel is what renders — four done phases, the
    // runnable badge only because this walk went fully green
    const panel = await screen.findByTestId('dev-run-panel')
    expect(panel).toHaveAttribute('data-dev-run-id', 'dev-1')
    expect(panel.querySelector('[data-testid="dev-phase-test"]')).toHaveAttribute('data-dev-phase-status', 'done')
    expect(screen.getByTestId('dev-runnable-version')).toBeInTheDocument()
  })

  it('a failed gate run shows 已失败 on its phase and pending after — never a fake green', async () => {
    const api = { startDevRun: vi.fn(async () => ({ run: failingRun })) } as unknown as StudioApi
    mount(api)
    await userEvent.click(screen.getByTestId('dev-start-btn'))
    const panel = await screen.findByTestId('dev-run-panel')
    expect(panel.querySelector('[data-testid="dev-phase-implement"]')).toHaveAttribute('data-dev-phase-status', 'failed')
    expect(panel.querySelector('[data-testid="dev-phase-build"]')).toHaveAttribute('data-dev-phase-status', 'pending')
    expect(panel.querySelector('[data-testid="dev-phase-implement"]')).toHaveTextContent('G3 FAIL')
    // no runnable badge on an unfinished walk
    expect(screen.queryByTestId('dev-runnable-version')).not.toBeInTheDocument()
  })

  it('the wiring refusal (503) is shown verbatim and no run appears', async () => {
    const api = {
      startDevRun: vi.fn(async () => {
        throw new StudioApiError(503, 'dev_wiring_not_configured', 'dev runs are not wired on this instance')
      }),
    } as unknown as StudioApi
    const onRan = mount(api)
    await userEvent.click(screen.getByTestId('dev-start-btn'))
    expect(await screen.findByTestId('dev-loop-notice')).toHaveTextContent('not wired')
    expect(screen.queryByTestId('dev-run-panel')).not.toBeInTheDocument()
    expect(onRan).not.toHaveBeenCalled()
    // the button survives the refusal — the operator wires the env and clicks again
    expect(screen.getByTestId('dev-start-btn')).toBeEnabled()
  })

  it('store-read runs render before any click; older ones list as history', () => {
    const api = { startDevRun: vi.fn() } as unknown as StudioApi
    mount(api, [greenRun, { ...failingRun, id: 'dev-0' }])
    expect(screen.getByTestId('dev-run-panel')).toHaveAttribute('data-dev-run-id', 'dev-1')
    expect(screen.getByTestId('dev-loop-history-dev-0')).toBeInTheDocument()
    expect(api.startDevRun).not.toHaveBeenCalled()
  })
})
