// A release-job's execution log, streamed live (ACP-772, 08-publish-app §〇-2).
// The backend's GET /publish/<deploymentId>/log answers SSE frames of
// {lines, done, status}: a running job's frames grow with the log file
// ("边发边长"), a finished job replays everything in the final frame. Both
// paths land here, so an open tab shows the live tail and a re-open shows the
// full replay — one code path, no fixture text.
//
// The `deploy-log-<id>` testid is an acceptance contract (08 §六): the id is
// the deploymentId, and it must survive any restyle of this component.
import { useEffect, useRef, useState } from 'react'
import { i18nT } from '../../i18n/t'
import ErrorNotice from '../../components/ErrorNotice'

const API = '/api/apps/ai-studio'

/** One SSE frame from the backend (routes.py _handle_publish_log). `lines`
 * are the NEW lines since the previous frame — the stream is an append-only
 * tail, never a re-send of the whole log. */
interface LogFrame {
  lines: string[]
  done: boolean
  status: string
}

export default function DeployLog({ deployId, projectId }: { deployId: string; projectId: string }) {
  const [lines, setLines] = useState<string[]>([])
  // null while the stream is (or was) healthy; the failed endpoint on error —
  // the log that never arrived is a failure, so it renders as one (never a
  // silently empty panel the user might read as "nothing happened yet").
  const [failedUrl, setFailedUrl] = useState<string | null>(null)
  const preRef = useRef<HTMLPreElement>(null)

  useEffect(() => {
    setLines([])
    setFailedUrl(null)
    const url =
      `${API}/publish/${encodeURIComponent(deployId)}/log` +
      `?project=${encodeURIComponent(projectId)}`
    const es = new EventSource(url)
    es.onmessage = (ev) => {
      try {
        const frame = JSON.parse(ev.data) as LogFrame
        if (Array.isArray(frame.lines) && frame.lines.length > 0) {
          setLines((prev) => [...prev, ...frame.lines])
        }
        // The final frame closes the stream: the server is done and a live
        // EventSource left open would reconnect and re-play from the start,
        // duplicating every line.
        if (frame.done) es.close()
      } catch {
        /* a malformed frame is dropped; the next poll frame carries the tail */
      }
    }
    es.onerror = () => {
      // EventSource auto-reconnects on error, so a permanently bad stream
      // (unknown job → 404, gateway down) would hammer the endpoint forever.
      // Close it and say so; the tab re-opening the log retries.
      es.close()
      setFailedUrl(url)
    }
    return () => es.close()
  }, [deployId, projectId])

  // 发布中实时滚动追加: keep the newest line in view as the stream grows.
  useEffect(() => {
    const el = preRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [lines])

  return (
    <div className="p-5 max-w-[820px]" data-testid={`deploy-log-${deployId}`}>
      <h1 className="text-[15px] font-semibold text-text-strong">{deployId}</h1>
      {failedUrl && (
        <div className="mt-2">
          <ErrorNotice
            askAgent
            title={i18nT('apps.aiStudio.deploy_log_failed')}
            message={failedUrl}
          />
        </div>
      )}
      {lines.length === 0 && !failedUrl && (
        <p className="text-[12px] text-muted mt-1">{i18nT('apps.aiStudio.deploy_log_waiting')}</p>
      )}
      <pre
        ref={preRef}
        role="log"
        aria-live="polite"
        className="mt-3 rounded-lg bg-bg-elevated border border-border font-mono text-[12px] leading-6 p-4 whitespace-pre-wrap overflow-auto text-muted"
      >
        {lines.join('\n')}
      </pre>
    </div>
  )
}
