/**
 * AI Studio's pages moved from `/ai-studio` to `/workspaces` (and the
 * workbench's old `/projects/<id>/ai-studio` spelling now has its own shim in
 * ProjectsPage, pinned in ProjectsPage.test.tsx). This pins the `/ai-studio`
 * half END TO END through App's real route table — the redirect is a static
 * route that must win over the `/:builtinApp/*` catch-all, and the query has
 * to survive because `?demo=` is the documented demo injection point: losing
 * it would strand every demo bookmark on the plain list.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { Provider } from 'react-redux'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { configureStore } from '@reduxjs/toolkit'
import dashboardReducer from '../store/dashboardSlice'
import chatReducer from '../store/chatSlice'
import notificationsReducer from '../store/notificationsSlice'
import instancesReducer from '../store/instancesSlice'
import App from '../App'
import { ThemeProvider } from '../hooks/useTheme'

// The studio page reports the live location, so the assertion sees exactly
// where the redirect landed — path, query and hash together.
vi.mock('../apps/ai-studio/AiStudioPage', () => ({
  default: () => {
    const loc = useLocation()
    return <div data-testid="studio-page">{loc.pathname + loc.search + loc.hash}</div>
  },
}))
vi.mock('../pages/ChatPage', () => ({ default: () => <div data-testid="chat-page">ChatPage</div> }))
vi.mock('../hooks/useWebSocket', () => ({ useWebSocket: () => ({ subscribeLogs: () => {}, subscribeSubagents: () => {}, forceReconnect: () => {} }) }))
vi.mock('../hooks/useAgents', () => ({ useAgents: vi.fn(() => ({ agents: [{ name: 'kirocrew' }], defaultAgent: 'kirocrew' })) }))
vi.mock('../hooks/useDashboardHealthProbe', () => ({ useDashboardHealthProbe: () => {} }))
vi.mock('../providers/context', () => ({ useProvider: () => ({ id: 'acp' }) }))
vi.mock('../components/MarkdownRenderer', () => ({ default: ({ content }: { content: string }) => <span>{content}</span>, Lightbox: () => null }))
vi.mock('../api/client', () => ({
  api: {
    chatSlots: vi.fn().mockResolvedValue([]),
    notifications: vi.fn().mockResolvedValue({ notifications: [] }),
    status: vi.fn().mockResolvedValue({ uptime: '1h', sessions: 0, messages: 0, cron_jobs: 0, subagents: 0, lessons: 0 }),
    sessionsUsage: vi.fn().mockResolvedValue({ usage: { available: false } }),
    listApps: vi.fn().mockResolvedValue([]),
    system: vi.fn().mockResolvedValue({ mem_used_gb: 4.0, mem_total_gb: 16.0, cpu_pct: 25.0, disk_total_gb: 100.0, disk_free_gb: 60.0 }),
    chatSlotAgent: vi.fn().mockResolvedValue({}),
    chatSlotReasoningEffort: vi.fn().mockResolvedValue({}),
    chatSlotModel: vi.fn().mockResolvedValue({}),
    chatMode: vi.fn().mockResolvedValue({}),
    listInstances: vi.fn().mockResolvedValue({ instances: [], warm_set_cap: 5 }),
    approvals: vi.fn().mockResolvedValue([]),
  },
  isAuthBannerShown: vi.fn(() => false),
  ApiError: class extends Error { status: number; constructor(s: number, m: string) { super(m); this.status = s } },
}))

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation(query => ({
    matches: false, media: query, onchange: null,
    addListener: vi.fn(), removeListener: vi.fn(),
    addEventListener: vi.fn(), removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

function renderAt(path: string) {
  const store = configureStore({
    reducer: {
      dashboard: dashboardReducer,
      chat: chatReducer,
      notifications: notificationsReducer,
      instances: instancesReducer,
    },
  })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <Provider store={store}>
      <QueryClientProvider client={qc}>
        <ThemeProvider>
          <MemoryRouter initialEntries={[path]}>
            <App />
          </MemoryRouter>
        </ThemeProvider>
      </QueryClientProvider>
    </Provider>
  )
}

describe('the legacy /ai-studio URLs redirect to /workspaces', () => {
  it('lands on /workspaces', async () => {
    renderAt('/ai-studio')
    await waitFor(() => expect(screen.getByTestId('studio-page')).toBeInTheDocument())
    expect(screen.getByTestId('studio-page').textContent).toBe('/workspaces')
  })

  it('carries the query across, so `?demo=` bookmarks survive', async () => {
    renderAt('/ai-studio?demo=main-membership-points')
    await waitFor(() => expect(screen.getByTestId('studio-page')).toBeInTheDocument())
    expect(screen.getByTestId('studio-page').textContent).toBe('/workspaces?demo=main-membership-points')
  })

  it('redirects the pre-rename deep spellings too', async () => {
    renderAt('/ai-studio/projects/p1')
    await waitFor(() => expect(screen.getByTestId('studio-page')).toBeInTheDocument())
    expect(screen.getByTestId('studio-page').textContent).toBe('/workspaces')
  })
})
