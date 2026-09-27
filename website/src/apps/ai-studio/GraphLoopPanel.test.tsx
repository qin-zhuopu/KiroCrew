// T7 (ACP-851): the 需求图谱 tab's REAL loop row. The panel takes its api as
// a prop, so these tests hand it an instrumented fake and assert the honest
// contract: each button performs exactly its one endpoint call with the page's
// project and doc, a landed act shows its data (DistillPanel row, frozen
// badge) rather than a success toast, and a refused act shows the backend's
// own error text instead of pretending. ToolSidebar's placement (graphLoop
// above the list) and AiStudioPage's real-only passing are the other two
// files' business; here is the panel's.
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import GraphLoopPanel from './GraphLoopPanel'
import { StudioApiError, type StudioApi, type StudioFreeze } from './studioApi'

function fakeApi(over: Partial<StudioApi> = {}) {
  return {
    distill: vi.fn(async () => ({
      distillation: {
        id: 'distill-1', releaseVersion: 'v1', status: 'done' as const,
        candidates: [{ id: 'requirements-001', kind: 'add' as const, target: 'KDU-AC-02',
          summary: '补充说明', evidenceDoc: 'requirements.md § 补充' }],
        distilledFromDoc: 'requirements.md', graphId: 'g1',
      },
    })),
    freeze: vi.fn(async () => ({
      freeze: { version: 'v1', docName: 'requirements.md', generatedFrom: 'distill-1', time: 1, notes: '' },
    })),
    regen: vi.fn(async () => ({
      doc: 'requirements.md', content: '# x', generatedFrom: 'distill-1',
    })),
    ...over,
  } as unknown as StudioApi
}

function mount(api: StudioApi, onActed = vi.fn(), initialFreezes: StudioFreeze[] = []) {
  render(
    <GraphLoopPanel
      projectId="p1"
      docName="requirements.md"
      api={api}
      initialFreezes={initialFreezes}
      initialDistills={[]}
      onActed={onActed}
    />,
  )
  return onActed
}

describe('GraphLoopPanel (T7 real loop)', () => {
  it('沉淀 calls distill once and renders the returned run', async () => {
    const api = fakeApi()
    const onActed = mount(api)
    await userEvent.click(screen.getByTestId('graph-distill-btn'))
    await waitFor(() => expect(screen.getByTestId('distill-panel')).toBeInTheDocument())
    expect(api.distill).toHaveBeenCalledTimes(1)
    expect(api.distill).toHaveBeenCalledWith('p1', 'requirements.md')
    expect(screen.getByTestId('distill-candidate-requirements-001')).toBeInTheDocument()
    expect(onActed).toHaveBeenCalledTimes(1)
  })

  it('冻结 goes through the confirm and lands the freeze; a re-freeze is refused, visibly', async () => {
    const api = fakeApi()
    const onActed = mount(api)
    await userEvent.click(screen.getByTestId('freeze-btn'))
    await userEvent.click(await screen.findByTestId('freeze-confirm'))
    await waitFor(() => expect(api.freeze).toHaveBeenCalledWith('p1', 'v1', 'requirements.md'))
    expect(onActed).toHaveBeenCalledTimes(1)
    // FreezeControl's own half of the rule: with a baseline the button stays
    // visible but disabled — the refusal shown, not the action hidden
    expect(screen.getByTestId('freeze-btn')).toBeDisabled()
  })

  it('重生成 calls regen and names the doc the draft landed on', async () => {
    const api = fakeApi()
    const onActed = mount(api)
    await userEvent.click(screen.getByTestId('graph-regen-btn'))
    await waitFor(() => expect(api.regen).toHaveBeenCalledWith('p1', 'requirements.md'))
    expect(await screen.findByTestId('graph-loop-notice')).toHaveTextContent(
      'requirements.md ← distill-1',
    )
    expect(onActed).toHaveBeenCalledTimes(1)
  })

  it('a refused distill shows the backend error, not a fake success', async () => {
    const api = fakeApi({
      distill: vi.fn(async () => {
        throw new StudioApiError(404, 'doc_not_found', 'doc not found')
      }),
    }) as unknown as StudioApi
    const onActed = mount(api)
    await userEvent.click(screen.getByTestId('graph-distill-btn'))
    expect(await screen.findByTestId('graph-loop-notice')).toHaveTextContent('doc not found')
    expect(screen.queryByTestId('distill-panel')).not.toBeInTheDocument()
    expect(onActed).not.toHaveBeenCalled()
  })

  it('a refused freeze reports the 409 text and never claims the baseline', async () => {
    const api = fakeApi({
      freeze: vi.fn(async () => {
        throw new StudioApiError(409, 'freeze_duplicate', 'version v1 is already frozen')
      }),
    }) as unknown as StudioApi
    mount(api)
    await userEvent.click(screen.getByTestId('freeze-btn'))
    await userEvent.click(await screen.findByTestId('freeze-confirm'))
    expect(await screen.findByTestId('graph-loop-notice')).toHaveTextContent('already frozen')
    expect(screen.getByTestId('freeze-btn')).not.toBeDisabled()
  })

  it('a store-held latest distillation renders before any click', () => {
    const api = fakeApi()
    render(
      <GraphLoopPanel
        projectId="p1"
        docName="requirements.md"
        api={api}
        initialFreezes={[]}
        initialDistills={[{
          id: 'distill-0', releaseVersion: 'v0', status: 'done', candidates: [],
        }]}
      />,
    )
    expect(screen.getByTestId('distill-panel')).toBeInTheDocument()
    expect(api.distill).not.toHaveBeenCalled()
  })
})
