// The release-job detail page (ACP-773, 08-publish-app §〇-2): opened at
// /release-jobs/<发布号>?project=<项目id>, it lists the project's whole
// release-job history (running pinned top), shows the selected job's header
// facts, streams its log through the reused T7 DeployLog (one SSE path: live
// growth, full replay when finished), and terminates honestly — success
// offers the app URL from the release record, failure is marked. The list is
// read-only: a row selects, nothing else (no retry/cancel/delete affordance).
// studioApi/publishApi are mocked per test file; EventSource is faked as in
// DeployLog.test.tsx because the page's log half IS DeployLog.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

const api = vi.hoisted(() => ({
  listJobs: vi.fn(),
  listRecords: vi.fn(),
}))
vi.mock('./studioApi', async () => {
  const actual = await vi.importActual('./studioApi')
  return { ...actual, publishApi: api }
})

// Same fake EventSource shape as DeployLog.test.tsx: the page reuses DeployLog,
// so the SSE frames land on this instance list.
const FakeES = vi.hoisted(() => {
  class Fake {
    static instances: Fake[] = []
    onmessage: ((ev: MessageEvent) => void) | null = null
    onerror: (() => void) | null = null
    closed = false
    constructor(public url: string) {
      Fake.instances.push(this)
    }
    close() { this.closed = true }
    emit(frame: unknown) {
      this.onmessage?.({ data: JSON.stringify(frame) } as MessageEvent)
    }
  }
  return Fake
})

import ReleaseJobPage from './ReleaseJobPage'

const RUNNING = { id: 'job-run', version: 'v3', form: 'demo', status: 'running', ts: 200, commitHash: 'c333333333333333333333333333333333333333' }
const DONE    = { id: 'job-done', version: 'v2', form: 'full', status: 'success', ts: 300, commitHash: 'c222222222222222222222222222222222222222' }
const FAILED  = { id: 'job-bad',  version: 'v1', form: 'full', status: 'failed',  ts: 100 }
const RECORDS = [
  { deploymentId: 'job-done', version: 'v2', commitHash: DONE.commitHash, form: 'full', requirementVersion: 'req-1', jiraTaskIds: ['ACP-1'], status: 'success', url: 'v2-crm-14409.gb10.jereh-pe.cn', ts: 360 },
]

beforeEach(() => {
  vi.clearAllMocks()
  FakeES.instances = []
  vi.stubGlobal('EventSource', FakeES as unknown as typeof EventSource)
  // The backend sorts by ts newest-first: DONE(300) is first, RUNNING(200)
  // second. The page pins RUNNING to the top for display — asserting that
  // ORDER (not just presence) is the whole §〇-2 "进行中的置顶" contract.
  api.listJobs.mockResolvedValue({ jobs: [DONE, RUNNING, FAILED] })
  api.listRecords.mockResolvedValue({ records: RECORDS })
})
afterEach(() => vi.unstubAllGlobals())

function renderPage(jobId = 'job-run', search = '?project=p1') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/release-jobs/${jobId}${search}`]}>
        <Routes>
          <Route path="/release-jobs/:jobId" element={<ReleaseJobPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function lastStream() {
  expect(FakeES.instances.length).toBeGreaterThan(0)
  return FakeES.instances[FakeES.instances.length - 1]
}

describe('ReleaseJobPage', () => {
  it('renders the page shell at its route and opens the log for the URL 发布号', async () => {
    renderPage('job-run')
    expect(await screen.findByTestId('ai-studio-release-job-page')).toBeInTheDocument()
    await screen.findByTestId('ai-studio-release-job-history-list')
    // DeployLog streams the job id (which IS the deploymentId) for this project
    expect(lastStream().url).toBe('/api/apps/ai-studio/publish/job-run/log?project=p1')
  })

  it('lists every job as a row with its three-state status; running pins above newer finished rows', async () => {
    renderPage()
    const list = await screen.findByTestId('ai-studio-release-job-history-list')
    // store order (newest-first) is DONE / RUNNING / FAILED; the page moves
    // RUNNING to the front and keeps DONE before FAILED inside the finished group.
    const rows = within(list).getAllByTestId(/^ai-studio-release-job-row-/)
    expect(rows.map((r) => r.getAttribute('data-testid'))).toEqual([
      'ai-studio-release-job-row-job-run',
      'ai-studio-release-job-row-job-done',
      'ai-studio-release-job-row-job-bad',
    ])
    expect(within(list).getByTestId('ai-studio-release-job-status-job-run')).toHaveTextContent('Publishing')
    expect(within(list).getByTestId('ai-studio-release-job-status-job-done')).toHaveTextContent('Completed')
    expect(within(list).getByTestId('ai-studio-release-job-status-job-bad')).toHaveTextContent('Failed')
  })

  it('header shows the job facts: version, form, short commit hash and status', async () => {
    renderPage()
    const header = await screen.findByTestId('ai-studio-release-job-header')
    expect(header).toHaveTextContent('v3')
    expect(header).toHaveTextContent('Demo')
    expect(header).toHaveTextContent('c333333')
    expect(header).toHaveTextContent('Publishing')
  })

  it('a success job shows the release record app URL', async () => {
    renderPage('job-done')
    const link = await screen.findByTestId('ai-studio-release-job-open-url')
    expect(link).toHaveAttribute('href', 'https://v2-crm-14409.gb10.jereh-pe.cn')
    expect(screen.queryByTestId('ai-studio-release-job-failed-mark')).not.toBeInTheDocument()
  })

  it('a failed job is marked, no URL offered', async () => {
    renderPage('job-bad')
    expect(await screen.findByTestId('ai-studio-release-job-failed-mark')).toBeInTheDocument()
    expect(screen.queryByTestId('ai-studio-release-job-open-url')).not.toBeInTheDocument()
  })

  it('streams the log through the reused DeployLog: frames grow, done closes', async () => {
    renderPage('job-run')
    await screen.findByTestId('ai-studio-release-job-log-job-run')
    const es = lastStream()
    es.emit({ lines: ['开始发布 v3'], done: false, status: 'running' })
    const log = await screen.findByTestId('ai-studio-release-job-log-job-run')
    await waitFor(() => expect(log).toHaveTextContent('开始发布 v3'))
    es.emit({ lines: ['构建完成'], done: false, status: 'running' })
    await waitFor(() => expect(log.textContent).toContain('开始发布 v3\n构建完成'))
    es.emit({ lines: ['发布完成'], done: true, status: 'success' })
    await waitFor(() => expect(es.closed).toBe(true))
  })

  it('clicking a history row switches the detail and reopens the log for that job', async () => {
    const user = userEvent.setup()
    renderPage('job-run')
    const list = await screen.findByTestId('ai-studio-release-job-history-list')
    await user.click(within(list).getByTestId('ai-studio-release-job-row-job-done'))
    // header flips to the success job and its URL appears
    expect(await screen.findByTestId('ai-studio-release-job-open-url')).toBeInTheDocument()
    // a fresh stream opened for the newly selected id
    await waitFor(() => expect(lastStream().url).toContain('/publish/job-done/log'))
  })

  it('the list is read-only: no button or other control inside a row', async () => {
    renderPage()
    const list = await screen.findByTestId('ai-studio-release-job-history-list')
    // Rows themselves are role=button (Clickable), which IS the "click to
    // view" affordance the contract allows; anything role=button INSIDE a
    // row would be a second control (retry/cancel/delete), which is forbidden.
    for (const row of within(list).getAllByTestId(/^ai-studio-release-job-row-/)) {
      expect(row).toHaveAttribute('role', 'button')
      // no nested <button>, no link, no menu, no input — the row IS the
      // only interactive element (per 08 §〇-2 "行内可点击元素仅『查看详情』")
      expect(row.querySelector('button, a, [role="link"], [role="menuitem"], input')).toBeNull()
    }
  })

  it('without a project query the page says so instead of firing project-less reads', async () => {
    renderPage('job-run', '')
    const page = await screen.findByTestId('ai-studio-release-job-page')
    expect(page).toHaveTextContent('no project id')
    expect(api.listJobs).not.toHaveBeenCalled()
  })

  it('empty history renders the empty state', async () => {
    api.listJobs.mockResolvedValue({ jobs: [] })
    renderPage()
    expect(await screen.findByTestId('ai-studio-release-job-empty')).toBeInTheDocument()
  })
})
