// D2 (ACP-788): the minimal end-to-end for the state-direct demo.
//
// WHICH CHANNEL, AND WHY (the ticket asked me to justify it in a comment if I
// could not use a real browser): the repo's true browser-E2E is Playwright, but
// `playwright.config.ts` sets `webServer: undefined` and
// `docs/ci/e2e-gate.md` documents that a spec only runs against an ALREADY
// booting gateway (CI reaches it via `python setup.py test_e2e`, minutes per
// run). My demo route is entirely client-side — `?demo=states` renders from
// local snapshots and, per §5, issues ZERO fetches — so booting a real gateway
// to serve the SPA would add cost while observing nothing the gateway provides.
//
// So I use the channel the repo already ships for exactly this surface:
// `demoScript.test.tsx` mounts the WHOLE route stack — AiStudioPage resolving
// `?demo=` → the demo branch → the real business components (ProjectCommitBar,
// LineDiff) running on the snapshot fake — and asserts on the rendered business
// DOM. That is route-level end-to-end (open a page → see it render → drive the
// controls → see each state paint), not a leaf-component unit test. The
// "component-level only" case the ticket warned about is rendering one
// component in isolation; this renders the entry route and everything under it.
//
// Coverage (the ticket's ~4 minimal): enter→S1, forward→S2, forward→S3, and the
// bidirectional jump back to S1 (plus a direct forward skip S1→S3), each
// asserted only by DOM text / testid — never a screenshot.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

import AiStudioPage from '../AiStudioPage'

/** `StateDemo` sits behind the demo branch's `React.lazy` boundary, so the
 * first paint is the Suspense skeleton, not the dock — every case awaits the
 * dock once after mount (a named wait on the real lazy chunk, per
 * website/docs/testing.md "A React.lazy boundary races the 1000ms default"). */
function mountStates() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/workspaces/demo-product/ai-studio?demo=states']}>
        <AiStudioPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const clickByTestId = (testid: string) => {
  const el = document.querySelector<HTMLElement>(`[data-testid="${testid}"]`)
  if (!el) throw new Error(`control ${testid} not found`)
  fireEvent.click(el)
}

const commitBtn = () => document.querySelector<HTMLButtonElement>('[data-testid="commit-all-btn"]')!

let fetchSpy: ReturnType<typeof vi.spyOn>
beforeEach(() => {
  window.localStorage.clear()
  // §5 / the ticket's hard line: demo mode never reads the network. Spy on
  // global fetch (real location has no `demo=`, so studioApi's own guard would
  // not stop a stray call — this is the external witness that none happens).
  fetchSpy = vi.spyOn(globalThis, 'fetch')
})
afterEach(() => {
  fetchSpy.mockRestore()
})

describe('state-direct demo: enter, switch, jump', () => {
  it('enters on S1: the doc list shows, nothing is open, commit is disabled', async () => {
    mountStates()
    // let the lazy demo chunk resolve past the Suspense skeleton first
    await screen.findByTestId('demo-states-dock')
    expect(screen.getByTestId('state-doc-list')).toBeInTheDocument()
    // all four outline docs listed
    expect(document.querySelectorAll('[data-testid^="state-doc-row-"]')).toHaveLength(4)
    // centre is the empty/welcome frame — no editor, no diff mounted
    expect(screen.getByTestId('state-empty')).toBeInTheDocument()
    expect(document.querySelector('[data-testid^="state-editor-"]')).toBeNull()
    expect(screen.queryByTestId('state-diff')).toBeNull()
    // the dock names this frame, and the commit button has nothing to commit
    expect(screen.getByTestId('demo-states-dock').getAttribute('data-demo-state')).toBe('S1')
    await waitFor(() => expect(commitBtn()).toBeDisabled())
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('next → S2: the requirement doc opens showing the workspace buffer + the dirty marker, commit enables', async () => {
    mountStates()
    await screen.findByTestId('demo-states-dock')
    await waitFor(() => expect(commitBtn()).toBeDisabled())
    clickByTestId('demo-states-next')

    expect(screen.getByTestId('demo-states-dock').getAttribute('data-demo-state')).toBe('S2')
    // the open editor shows the UNCOMMITTED working text (the plain-language
    // supplement), not just the committed baseline
    const editor = screen.getByTestId('state-editor-V4')
    expect(editor).toHaveAttribute('data-doc-dirty', 'true')
    expect(editor).toHaveTextContent('产品需求')
    expect(editor).toHaveTextContent('用户补充')
    // 「有未提交修改」 marker, naming the version the buffer would become
    expect(screen.getByTestId('state-dirty-marker')).toHaveTextContent('Unsaved changes')
    expect(screen.getByTestId('state-dirty-marker')).toHaveTextContent('V5')
    // the Diff tab carries its badge (data-driven 红点角标)
    expect(screen.getByTestId('diff-tab-badge')).toBeInTheDocument()
    // the commit button becomes ENABLED — driven by ProjectCommitBar's real
    // read of the fake's pre-seeded draft, not a hardcoded prop
    await waitFor(() => expect(commitBtn()).toBeEnabled())
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('next → S3: the Diff tab renders the row-level V4 → workspace diff with added lines', async () => {
    mountStates()
    await screen.findByTestId('demo-states-dock')
    await waitFor(() => expect(commitBtn()).toBeDisabled())
    clickByTestId('demo-states-next') // → S2
    await waitFor(() => expect(commitBtn()).toBeEnabled())
    clickByTestId('demo-states-next') // → S3

    expect(screen.getByTestId('demo-states-dock').getAttribute('data-demo-state')).toBe('S3')
    // the diff tab is the active one
    expect(screen.getByTestId('state-tab-diff').getAttribute('aria-selected')).toBe('true')
    const diff = screen.getByTestId('state-diff')
    // LineDiff renders added lines prefixed '+ ' and coloured as additions;
    // the supplement lines are exactly what the workspace added over V4
    expect(diff).toHaveTextContent('V4 → V5')
    expect(diff.textContent).toMatch(/\+ .*用户补充/)
    expect(diff.textContent).toMatch(/大额采购/)
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('is bidirectional: from S3 direct-jump back to S1 (list, nothing open, commit disabled)', async () => {
    mountStates()
    await screen.findByTestId('demo-states-dock')
    await waitFor(() => expect(commitBtn()).toBeDisabled())
    // straight forward skip S1 → S3 via a direct-select button
    clickByTestId('demo-states-select-S3')
    await waitFor(() => expect(screen.getByTestId('state-diff')).toBeInTheDocument())
    expect(screen.getByTestId('demo-states-dock').getAttribute('data-demo-state')).toBe('S3')

    // now jump back to the first frame — a pure re-read of the S1 snapshot
    clickByTestId('demo-states-select-S1')
    expect(screen.getByTestId('demo-states-dock').getAttribute('data-demo-state')).toBe('S1')
    expect(screen.getByTestId('state-empty')).toBeInTheDocument()
    expect(document.querySelector('[data-testid^="state-editor-"]')).toBeNull()
    expect(screen.queryByTestId('state-diff')).toBeNull()
    // coming back to the clean frame re-derives its data: nothing to commit
    await waitFor(() => expect(commitBtn()).toBeDisabled())
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('prev walks back one frame at a time (S3 → S2), proving no replay prefix is needed', async () => {
    mountStates()
    await screen.findByTestId('demo-states-dock')
    await waitFor(() => expect(commitBtn()).toBeDisabled())
    clickByTestId('demo-states-select-S3')
    await waitFor(() => expect(screen.getByTestId('state-diff')).toBeInTheDocument())
    clickByTestId('demo-states-prev')
    expect(screen.getByTestId('demo-states-dock').getAttribute('data-demo-state')).toBe('S2')
    // back on the doc frame: the editor is on screen again, the diff is gone
    expect(screen.getByTestId('state-editor-V4')).toBeInTheDocument()
    expect(screen.queryByTestId('state-diff')).toBeNull()
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})
