// ACP-793: the on-page demo entry button.
//
// Proves the owner's complaint is fixed without a screenshot: on an ordinary
// AI Studio page the button is visible, one click pushes `?demo=states` and the
// state-direct demo renders, and the same button (now "Exit demo") takes you
// back. Both the project list (`/workspaces`) and the workbench
// (`/workspaces/<id>/ai-studio`) carry it, since it gates on the query, not the
// path.
//
// Why these assertions are DOM-only: the route is client-side and the test
// reads `location.search` through a probe, so "URL has the param" is observed
// as text, not measured. Dock-overlap is proven structurally by the button's
// `data-demo-entry` placement flag flipping to `docked` (it shifts left of the
// fixed 340px dock), not by pixel geometry happy-dom cannot compute.
//
// The ordinary surfaces run real React Query reads; in this environment there
// is no gateway, so `fetch` is stubbed to a benign response. That is incidental
// to what is under test — the button renders as a fixed overlay regardless of
// whether the page behind it resolves — and it is also what lets the "click →
// demo param → demo renders" round trip be the thing we watch.
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

beforeEach(() => {
  window.localStorage.clear()
  // ordinary (non-demo) surfaces would otherwise hit a gateway that does not
  // exist here; a resolved-but-empty body is enough to render their error/empty
  // state without an unhandled rejection.
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ projects: [] }),
      text: async () => '',
      headers: { get: () => null },
    }),
  )
})

describe('demo entry button (ACP-793)', () => {
  it('on the project list: visible, corner placement, and one click enters the demo (param + demo render)', async () => {
    mount('/workspaces')
    expect(screen.getByTestId('ai-studio-projects')).toBeInTheDocument()
    expect(btn()).toBeInTheDocument()
    expect(btn()).toHaveAttribute('data-demo-entry', 'corner')
    expect(btn()).toHaveTextContent('Demo')

    fireEvent.click(btn())

    // the param is now on the URL...
    await waitFor(() => expect(loc()).toContain('demo=states'))
    // ...and the state-direct demo is actually rendered...
    expect(await screen.findByTestId('demo-states-dock')).toBeInTheDocument()
    // ...so the same button has switched to "exit" and stepped out of the dock band.
    expect(btn()).toHaveTextContent('Exit demo')
    expect(btn()).toHaveAttribute('data-demo-entry', 'docked')
  })

  it('the demo button is the same element, not a swap: exit clears the param and returns to the list', async () => {
    mount('/workspaces')
    fireEvent.click(btn())
    await screen.findByTestId('demo-states-dock')
    await waitFor(() => expect(loc()).toContain('demo=states'))

    fireEvent.click(btn())

    // back to the ordinary list, param gone, placement back in the corner.
    expect(await screen.findByTestId('ai-studio-projects')).toBeInTheDocument()
    await waitFor(() => expect(loc()).not.toContain('demo'))
    expect(screen.queryByTestId('demo-states-dock')).toBeNull()
    expect(btn()).toHaveAttribute('data-demo-entry', 'corner')
    expect(btn()).toHaveTextContent('Demo')
  })

  it('on the workbench path it also enters the demo (gates on the query, not the path)', async () => {
    mount('/workspaces/demo-product/ai-studio')
    expect(btn()).toBeInTheDocument()
    expect(btn()).toHaveAttribute('data-demo-entry', 'corner')

    fireEvent.click(btn())

    expect(await screen.findByTestId('demo-states-dock')).toBeInTheDocument()
    await waitFor(() => expect(loc()).toContain('demo=states'))
    expect(btn()).toHaveAttribute('data-demo-entry', 'docked')
  })
})
