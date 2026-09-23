// The release-job log stream (ACP-772, 08-publish-app §〇-2): the component
// opens the backend's SSE endpoint for its deployment, appends each frame's
// NEW lines as they arrive (发布中实时滚动追加), stops appending when a frame
// says done, and shows the failure honestly when the connection fails — never
// an empty panel pretending the job logged nothing.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'

// vi.mock below must not hoist over this import, so the fake lives in hoisted
// scope and drives the component through its exposed instance list.
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

import DeployLog from './DeployLog'

beforeEach(() => {
  FakeES.instances = []
  vi.stubGlobal('EventSource', FakeES as unknown as typeof EventSource)
})
afterEach(() => vi.unstubAllGlobals())

function renderLog(deployId = 'job-1', projectId = 'p1') {
  return render(<DeployLog deployId={deployId} projectId={projectId} />)
}

function lastStream() {
  expect(FakeES.instances.length).toBeGreaterThan(0)
  return FakeES.instances[FakeES.instances.length - 1]
}

describe('DeployLog SSE stream', () => {
  it('opens the publish log endpoint for its deployment and project', () => {
    renderLog('job-9', 'proj X')
    const es = lastStream()
    expect(es.url).toBe('/api/apps/ai-studio/publish/job-9/log?project=proj%20X')
  })

  it('keeps the deploy-log-<id> testid contract', async () => {
    const { getByTestId } = renderLog('job-1')
    expect(getByTestId('deploy-log-job-1')).toBeInTheDocument()
  })

  it('appends each frame\'s new lines as they stream in', async () => {
    const { getByTestId } = renderLog()
    const es = lastStream()
    es.emit({ lines: ['build: start'], done: false, status: 'running' })
    await waitFor(() => expect(getByTestId('deploy-log-job-1')).toHaveTextContent('build: start'))
    es.emit({ lines: ['build: npm ci OK', 'build: vite build OK'], done: false, status: 'running' })
    await waitFor(() =>
      expect(getByTestId('deploy-log-job-1').textContent).toContain(
        'build: start\nbuild: npm ci OK\nbuild: vite build OK',
      ),
    )
  })

  it('stops the stream on done and keeps the full replay', async () => {
    const { getByTestId } = renderLog()
    const es = lastStream()
    es.emit({ lines: ['step 1'], done: false, status: 'running' })
    es.emit({ lines: ['done.'], done: true, status: 'success' })
    await waitFor(() => expect(es.closed).toBe(true))
    // an auto-reconnect after done would replay and duplicate; closed says no.
    expect(getByTestId('deploy-log-job-1').textContent).toContain('step 1\ndone.')
  })

  it('a finished job opened later replays its full log in one frame', async () => {
    const { getByTestId } = renderLog()
    lastStream().emit({
      lines: ['checkout', 'npm ci', 'npm run build', 'deployed'],
      done: true,
      status: 'success',
    })
    await waitFor(() =>
      expect(getByTestId('deploy-log-job-1').textContent).toContain(
        'checkout\nnpm ci\nnpm run build\ndeployed',
      ),
    )
  })

  it('a failed connection shows the reason instead of an empty success', async () => {
    const { getByTestId } = renderLog('job-404')
    const es = lastStream()
    es.onerror?.()
    await waitFor(() => expect(es.closed).toBe(true))
    const log = getByTestId('deploy-log-job-404')
    // an ErrorNotice (role=alert) names the failure and the endpoint it hit
    expect(log.querySelector('[role="alert"]')).not.toBeNull()
    expect(log).toHaveTextContent('/publish/job-404/log')
  })

  it('malformed frames are dropped without breaking the panel', async () => {
    const { getByTestId } = renderLog()
    const es = lastStream()
    es.onmessage?.({ data: '{not json' } as MessageEvent)
    es.emit({ lines: ['survived'], done: false, status: 'running' })
    await waitFor(() => expect(getByTestId('deploy-log-job-1')).toHaveTextContent('survived'))
  })

  it('closing the tab closes the stream (no reconnect hammering)', () => {
    const { unmount } = renderLog()
    const es = lastStream()
    unmount()
    expect(es.closed).toBe(true)
  })
})
