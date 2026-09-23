// ACP-793: the on-page demo entry button — as ACP-794 left it.
//
// Proves the owner's complaints are fixed without a screenshot:
//   - on an ordinary AI Studio page (the project list, the workbench) the
//     button is visible and one click pushes `?demo=states`;
//   - WHILE THE STATE DEMO RUNS THE BUTTON IS NOT IN THE DOM AT ALL (owner,
//     ACP-794): the dock's own ✕ in its top-right is the only exit, so a
//     second one is not rendered — and that ✕ is what these cases use to get
//     back, which is the whole point of the rule;
//   - the OTHER demo line (`?demo=<script>`) keeps its exit, because that
//     surface ships no close control of its own.
//
// Why these assertions are DOM-only: the route is client-side and the test
// reads `location.search` through a probe, so "URL has the param" is observed
// as text, not measured.
//
// The ordinary surfaces run real React Query reads; in this environment there
// is no gateway, so `fetch` is stubbed to a benign response carrying ONE
// project (the button only appears where a project can be taken over, so an
// empty list would — correctly — have no button to click).
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'

import AiStudioPage from './AiStudioPage'

function LocProbe() {
  const { search } = useLocation()
  return <span data-testid="loc-probe">{search}</span>
}

function mount(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route
            path="*"
            element={(
              <>
                <AiStudioPage />
                <LocProbe />
              </>
            )}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const btn = () => screen.getByTestId('demo-entry-btn')
const loc = () => screen.getByTestId('loc-probe').textContent ?? ''

const PROJECT = { id: 'p1', name: '演示项目', description: '', createdAt: 0 }

beforeEach(() => {
  window.localStorage.clear()
  // ordinary (non-demo) surfaces would otherwise hit a gateway that does not
  // exist here; a resolved body is enough to render their real state without
  // an unhandled rejection.
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ projects: [PROJECT], project: PROJECT, docs: [], drafts: [], versions: [] }),
      text: async () => '',
      headers: { get: () => null },
    }),
  )
})

describe('demo entry button (ACP-793 / ACP-794)', () => {
  it('on the project list: visible, corner placement, one click enters the demo — and then it is gone', async () => {
    mount('/workspaces')
    expect(await screen.findByTestId('ai-studio-projects')).toBeInTheDocument()
    // the button needs a project to open the demo ON, so it appears with the list
    expect(await screen.findByTestId('demo-entry-btn')).toBeInTheDocument()
    expect(btn()).toHaveAttribute('data-demo-entry', 'corner')
    expect(btn()).toHaveTextContent('Demo')

    fireEvent.click(btn())

    // the param is now on the URL...
    await waitFor(() => expect(loc()).toContain('demo=states'))
    // ...the state-direct demo is actually rendered...
    expect(await screen.findByTestId('demo-states-dock')).toBeInTheDocument()
    // ...and the entry button has left the screen: the dock's ✕ is the only exit
    expect(screen.queryByTestId('demo-entry-btn')).toBeNull()
  })

  it('leaves through the dock ✕, and the entry button comes back with the ordinary page', async () => {
    mount('/workspaces')
    fireEvent.click(await screen.findByTestId('demo-entry-btn'))
    await screen.findByTestId('demo-states-dock')
    // entering from the list moved onto that project's page, demo param and
    // all (the path itself is asserted in StatesWorkspace.test's probe) — the
    // demo took the workbench over rather than the list
    await waitFor(() => expect(screen.getByTestId('ai-studio')).toHaveAttribute('data-demo-states'))

    fireEvent.click(screen.getByTestId('demo-states-close'))

    // param gone, the page is the ordinary workbench again, and the entry
    // button is on screen once more — the same element, in its corner
    await waitFor(() => expect(loc()).not.toContain('demo'))
    expect(screen.queryByTestId('demo-states-dock')).toBeNull()
    // the ordinary workbench loads its project again (it was never fetched
    // while the demo was up), so wait for it rather than the loading skeleton
    expect(await screen.findByTestId('ai-studio')).not.toHaveAttribute('data-demo-states')
    expect(btn()).toHaveAttribute('data-demo-entry', 'corner')
    expect(btn()).toHaveTextContent('Demo')
  })

  it('on the workbench path it also enters the demo (gates on the query, not the path)', async () => {
    mount('/workspaces/p1/ai-studio')
    fireEvent.click(await screen.findByTestId('demo-entry-btn'))

    expect(await screen.findByTestId('demo-states-dock')).toBeInTheDocument()
    await waitFor(() => expect(loc()).toContain('demo=states'))
    expect(screen.queryByTestId('demo-entry-btn')).toBeNull()
  })

  it('the other demo line keeps its exit: that surface has no close control of its own', async () => {
    mount('/workspaces?demo=main-membership-points')

    // in a replay demo the button IS the exit, so it renders and says so
    expect(btn()).toHaveTextContent('Exit demo')
    expect(btn()).toHaveAttribute('data-demo-entry', 'corner')

    fireEvent.click(btn())
    await waitFor(() => expect(loc()).not.toContain('demo'))
  })
})