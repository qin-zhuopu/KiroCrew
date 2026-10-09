// The dev-server control in the workbench top bar (ACP-2060, RFC §9.6): one
// button that starts or stops this project's `pnpm dev` pair and shows the rule
// domain once it is up.
//
// Two rules shape the component. (1) The state is the backend's, never ours:
// every render reads `GET dev-server`, which recomputes truth from live pids and
// a live HTTP probe. A refresh, a second browser tab, or a gateway restart all
// see the same answer, which is what acceptance 19 (kill the frontend by hand →
// no green dot) actually requires. (2) `starting` is a poll, not a spinner with
// a timer: a pnpm install is minutes long and the backend answers 202 at once,
// so the only honest UI is to re-read every 2s until the state moves.
//
// A failure shows the backend's step name and message VERBATIM. The log tail is
// one click away because the message is one line by design and the real error is
// never in one line.
import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Copy, ExternalLink, Square } from 'lucide-react'
import { Btn } from '../../components/ui'
import Clickable from '../../components/Clickable'
import { i18nT } from '../../i18n/t'
import { studioApi, StudioApiError, type StudioDevServer } from './studioApi'

/** Dot colours per state: grey / amber / green / red. Literal class strings —
 * the theme scan reads static classes, and a composed `bg-${x}` is invisible to
 * it (and to Tailwind's own extraction). */
const DOT_CLASS: Record<StudioDevServer['state'], string> = {
  stopped: 'bg-muted/50',
  starting: 'bg-warn',
  running: 'bg-ok',
  failed: 'bg-err',
}

const STATE_LABEL: Record<StudioDevServer['state'], string> = {
  stopped: 'apps.aiStudio.devServer.stopped',
  starting: 'apps.aiStudio.devServer.starting',
  running: 'apps.aiStudio.devServer.running',
  failed: 'apps.aiStudio.devServer.failed',
}

export default function DevServerControl({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient()
  const [pending, setPending] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [showLog, setShowLog] = useState(false)
  const [copied, setCopied] = useState(false)
  // The failed step's output is pulled once per open, not polled: it is a file
  // tail on the backend and the interesting part stopped changing when the step
  // died. Re-read on every open so a retry's new failure shows up.
  const [logLines, setLogLines] = useState<string[] | null>(null)
  const [logLoading, setLogLoading] = useState(false)
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const statusQuery = useQuery({
    queryKey: ['ai-studio', 'dev-server', projectId],
    queryFn: () => studioApi.getDevServer(projectId),
    // While a start is in flight the answer changes on its own, so the client
    // re-reads it. Anything else is user-driven: a mount, a mutation, a focus.
    refetchInterval: (query) => (query.state.data?.state === 'starting' ? 2000 : false),
  })

  // A route change within the page (project switch) must not keep polling the
  // previous project's server.
  useEffect(() => {
    setActionError(null)
    setShowLog(false)
    setLogLines(null)
  }, [projectId])

  const view: StudioDevServer | undefined = statusQuery.data
  // Before the first answer lands we genuinely do not know, and 「已停止」 is a
  // claim about the world that the first GET may immediately contradict — so the
  // open of the workbench visibly read 已停止 → 运行中 (the dot went grey, then
  // green). Same shape as ProdServerControl: say 「查询中…」 and disable the
  // button, and let the real state arrive before naming it. The dot testid gains
  // the `unknown` suffix exactly as the prod one does.
  const querying = view === undefined
  const state = view?.state ?? 'stopped'
  const running = state === 'running'
  const starting = state === 'starting'
  const url = view?.url ?? ''

  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: ['ai-studio', 'dev-server', projectId] })

  async function toggle() {
    setActionError(null)
    setPending(true)
    try {
      const next = running || starting
        ? await studioApi.stopDevServer(projectId)
        : await studioApi.startDevServer(projectId)
      // The action's own response IS the fresh state — the backend recomputed it
      // (start: the domain rules passed and a thread is running; stop: the
      // process groups are gone). Writing it is both the immediate repaint and
      // the thing that keeps the poll alive, since `starting` here is what
      // refetchInterval keys on. No extra refetch: that would race this answer.
      queryClient.setQueryData(['ai-studio', 'dev-server', projectId], next)
    } catch (err) {
      // A 400 `code_required` / `staff_id_required` is the domain rule refusing
      // this project; a 409 means someone else already started it. Both are
      // worth reading, so the message goes on screen rather than into a console.
      setActionError(err instanceof Error ? err.message : String(err))
      // The refusal may still mean the truth moved (409 already_running), so
      // re-read instead of trusting our cache.
      await refresh()
    } finally {
      if (mounted.current) setPending(false)
    }
  }

  async function toggleLog() {
    const next = !showLog
    setShowLog(next)
    if (next && logLines === null) {
      setLogLoading(true)
      try {
        const res = await studioApi.getDevServerLog(projectId, 200)
        if (mounted.current) setLogLines(res.lines)
      } catch (err) {
        if (mounted.current)
          setActionError(err instanceof Error ? err.message : String(err))
      } finally {
        if (mounted.current) setLogLoading(false)
      }
    }
  }

  async function copyUrl() {
    try {
      await navigator.clipboard.writeText(url)
      if (!mounted.current) return
      setCopied(true)
      setTimeout(() => {
        if (mounted.current) setCopied(false)
      }, 1500)
    } catch {
      // Clipboard is unavailable over http and in jsdom; the link is next to the
      // button, so a silent no-op is the honest degradation, not an error toast.
    }
  }

  // Only our own in-flight request disables the button, plus the one moment we
  // have no answer at all: this button is one direction-per-state, so clicking
  // while `view` is undefined always means 启动 — including on a project that is
  // about to be reported as running, where the answer is a 409 dance. A
  // `starting` project MUST stay clickable: an install that hangs is cancelled
  // with 停止, and devserver.stop() is written to kill a half-launched set (it
  // bumps the generation the launch thread checks).
  const busy = querying || pending
  const failure = state === 'failed' ? view : null

  return (
    <div className="flex flex-col gap-1 max-w-[520px]" data-testid="dev-server-control">
      <div className="flex items-center gap-2">
        <span
          aria-hidden
          data-testid={`dev-server-dot-${querying ? 'unknown' : state}`}
          className={`inline-block w-2 h-2 shrink-0 rounded-full ${
            querying ? 'bg-muted/50' : DOT_CLASS[state]
          }`}
        />
        <span className="text-[11px] text-muted shrink-0">
          {querying ? i18nT('apps.aiStudio.devServer.querying') : i18nT(STATE_LABEL[state])}
        </span>
        {running && url && (
          <span className="flex items-center gap-1 min-w-0">
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              data-testid="dev-server-url"
              title={url}
              className="text-[11px] text-accent truncate hover:underline flex items-center gap-1"
            >
              {url.replace(/^https?:\/\//, '')}
              <ExternalLink size={11} />
            </a>
            <Clickable
              onClick={copyUrl}
              title={i18nT('apps.aiStudio.devServer.copy')}
              aria-label={i18nT('apps.aiStudio.devServer.copy')}
              data-testid="dev-server-copy"
              className="text-muted hover:text-text cursor-pointer inline-flex shrink-0"
            >
              {copied ? <Check size={12} /> : <Copy size={12} />}
            </Clickable>
            {copied && (
              <span className="text-[10px] text-muted">
                {i18nT('apps.aiStudio.devServer.copied')}
              </span>
            )}
          </span>
        )}
        {/* One button for both directions: 「运行中/启动中」 stops, anything else
            (stopped, failed) starts. A failed project MUST be startable again —
            that is the whole point of showing which step broke. */}
        <Btn
          onClick={toggle}
          disabled={busy}
          data-testid="dev-server-toggle"
          className="shrink-0"
        >
          {running || starting ? <Square size={12} className="lucide-inline" /> : null}
          {running || starting
            ? i18nT('apps.aiStudio.devServer.stop')
            : i18nT('apps.aiStudio.devServer.start')}
        </Btn>
        <Clickable
          onClick={toggleLog}
          data-testid="dev-server-log-toggle"
          className="text-[11px] text-muted hover:text-text cursor-pointer shrink-0 whitespace-nowrap"
        >
          {showLog
            ? i18nT('apps.aiStudio.devServer.hide_log')
            : i18nT('apps.aiStudio.devServer.view_log')}
        </Clickable>
      </div>

      {actionError && (
        <div className="text-[11px] text-err" data-testid="dev-server-action-error">
          {actionError}
        </div>
      )}
      {failure && (
        // VERBATIM. `message` already carries the step name — the backend wrote
        // 「装依赖失败：<tail>」 — so re-templating 「{step}失败：{message}」 here
        // would print the step twice. The message is the tail of the failing
        // step's output and the only place the real error exists; the log panel
        // below is the longer version of the same file.
        <div
          className="text-[11px] text-err whitespace-pre-wrap break-all"
          data-testid="dev-server-error"
        >
          {failure.message || failure.failedStep || i18nT('apps.aiStudio.devServer.failed')}
        </div>
      )}
      {showLog && (
        <pre
          data-testid="dev-server-log"
          className="max-h-[220px] overflow-auto rounded-md border border-border bg-bg px-2 py-1.5 text-[10.5px] leading-[1.45] text-muted whitespace-pre-wrap break-all"
        >
          {logLoading
            ? i18nT('apps.aiStudio.devServer.log_loading')
            : (logLines ?? []).join('\n') || i18nT('apps.aiStudio.devServer.log_empty')}
        </pre>
      )}
    </div>
  )
}

/** The card's one-line version (ProjectsListPage): a green dot and the URL, and
 * nothing at all when the project is not running. Split out so the list pays one
 * tiny read per project and no polling — the list is a survey, the workbench is
 * where a start happens. */
export function DevServerBadge({ projectId }: { projectId: string }) {
  const { data } = useQuery({
    queryKey: ['ai-studio', 'dev-server', projectId],
    queryFn: () => studioApi.getDevServer(projectId),
    refetchInterval: false,
    // A project with no workspace answers 404/400; the card just shows no badge.
    retry: false,
  })
  if (data?.state !== 'running' || !data.url) return null
  return (
    <a
      href={data.url}
      target="_blank"
      rel="noopener noreferrer"
      data-testid="project-dev-url"
      title={data.url}
      onClick={(e) => e.stopPropagation()}
      className="flex items-center gap-1 text-[11px] text-ok hover:underline min-w-0"
    >
      <span aria-hidden className="inline-block w-1.5 h-1.5 rounded-full bg-ok shrink-0" />
      <span className="truncate">{data.url.replace(/^https?:\/\//, '')}</span>
    </a>
  )
}
