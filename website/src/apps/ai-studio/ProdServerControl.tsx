// The production-server control in the workbench top bar (ACP-2085-S5), to the
// right of the dev-server control: deploy this project to its own domain, watch
// the seven steps, and read the version that is live.
//
// Same two rules as DevServerControl, same reasons. (1) The state is the
// backend's: every render reads `GET prod-server`, which recomputes truth from
// live pids plus a live HTTP probe on the fixed URL — so a refresh, a second tab
// or a gateway restart all agree. (2) `deploying` is a poll, not a timer: the
// build takes minutes and the route answers 202 at once, so the only honest UI
// is to re-read every 2s until the state moves.
//
// One thing this has and the dev control does not: a refusal that is NOT a
// failure. 「先通过验收再部署」 (409 not_accepted) is a precondition the operator
// has not met yet, so it is one grey line under the control, not a red error and
// not a dialog. A real failure (red) shows the backend's message VERBATIM — that
// string already carries the step name, and the log tail is one click away
// because the message is one line by design.
import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, Rocket, Square } from 'lucide-react'
import { Btn } from '../../components/ui'
import Clickable from '../../components/Clickable'
import { i18nT } from '../../i18n/t'
import {
  prodServerApi,
  StudioApiError,
  type StudioProdServer,
  type StudioProdServerState,
} from './studioApi'

/** Dot colours per state: grey / amber / green / red. Literal class strings — a
 * composed `bg-${x}` is invisible to the theme scan (and to Tailwind). */
const DOT_CLASS: Record<StudioProdServerState, string> = {
  stopped: 'bg-muted/50',
  deploying: 'bg-warn',
  running: 'bg-ok',
  failed: 'bg-err',
}

const STATE_LABEL: Record<StudioProdServerState, string> = {
  stopped: 'apps.aiStudio.prodServer.stopped',
  deploying: 'apps.aiStudio.prodServer.deploying',
  running: 'apps.aiStudio.prodServer.running',
  failed: 'apps.aiStudio.prodServer.failed',
}

export default function ProdServerControl({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient()
  const [pending, setPending] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  // 409 not_accepted lives apart from actionError on purpose: it is a grey hint
  // about what to do next, not something that went wrong.
  const [hint, setHint] = useState<string | null>(null)
  const [showLog, setShowLog] = useState(false)
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
    queryKey: ['ai-studio', 'prod-server', projectId],
    queryFn: () => prodServerApi.getProdServer(projectId),
    // Only a deploy in flight changes on its own. Everything else is user-driven:
    // a mount, a mutation, a focus.
    refetchInterval: (query) => (query.state.data?.state === 'deploying' ? 2000 : false),
  })

  // Switching projects must not keep polling the previous project's server, and
  // must not carry its hint over.
  useEffect(() => {
    setActionError(null)
    setHint(null)
    setShowLog(false)
    setLogLines(null)
  }, [projectId])

  // Before the first answer lands we genuinely do not know: say 「查询中…」 and
  // disable the buttons, rather than showing 「已停止」 + a 部署 button for a
  // server that may be running (clicking it would be a 409 dance).
  const view: StudioProdServer | undefined = statusQuery.data
  const querying = view === undefined
  const state: StudioProdServerState = view?.state ?? 'stopped'
  const deploying = state === 'deploying'
  const running = state === 'running'
  const url = view?.url ?? ''

  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: ['ai-studio', 'prod-server', projectId] })

  async function run(action: () => Promise<StudioProdServer>) {
    setActionError(null)
    setHint(null)
    setPending(true)
    try {
      const next = await action()
      // The action's response IS the fresh state (deploy: the gate passed and a
      // thread is running; stop: the process groups are gone). Writing it is both
      // the immediate repaint and what keeps the poll alive, since refetchInterval
      // keys on the `deploying` in this cache. No extra refetch — that would race
      // this answer.
      queryClient.setQueryData(['ai-studio', 'prod-server', projectId], next)
    } catch (err) {
      if (err instanceof StudioApiError && err.code === 'not_accepted') {
        // The gate refusing: one grey line, no dialog. The server did not move,
        // so nothing to re-read.
        if (mounted.current) setHint(i18nT('apps.aiStudio.prodServer.not_accepted'))
      } else {
        if (mounted.current)
          setActionError(err instanceof Error ? err.message : String(err))
        // A refusal may still mean the truth moved (409 already_deploying), so
        // re-read instead of trusting our cache.
        await refresh()
      }
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
        const res = await prodServerApi.getProdServerLog(projectId, 80)
        if (mounted.current) setLogLines(res.lines)
      } catch (err) {
        if (mounted.current)
          setActionError(err instanceof Error ? err.message : String(err))
      } finally {
        if (mounted.current) setLogLoading(false)
      }
    }
  }

  const failure = state === 'failed' ? view : null

  return (
    <div className="flex flex-col gap-1 max-w-[560px]" data-testid="prod-server-control">
      <div className="flex items-center gap-2">
        <span
          aria-hidden
          data-testid={`prod-server-dot-${querying ? 'unknown' : state}`}
          className={`inline-block w-2 h-2 shrink-0 rounded-full ${
            querying ? 'bg-muted/50' : DOT_CLASS[state]
          }`}
        />
        {/* One status string, not two: a deploying project reads 「部署中：<步骤>」
            as a whole, so the step name is interpolated into the status rather
            than bolted on beside it. The seven step names are the backend's
            (prodserver.STEPS) and appear VERBATIM — they are what the operator
            reads back to whoever owns the build, so nothing rewords them here. */}
        <span
          className={`text-[11px] shrink-0 ${deploying ? 'text-warn' : 'text-muted'}`}
          data-testid={deploying && !querying ? 'prod-server-step' : undefined}
        >
          {querying
            ? i18nT('apps.aiStudio.prodServer.querying')
            : deploying
              ? view?.step
                ? i18nT('apps.aiStudio.prodServer.deploying_step', { step: view.step })
                : i18nT(STATE_LABEL.deploying)
              : i18nT(STATE_LABEL[state])}
        </span>
        {running && url && (
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            data-testid="prod-server-url"
            title={url}
            className="text-[11px] text-accent truncate hover:underline flex items-center gap-1 min-w-0"
          >
            {url.replace(/^https?:\/\//, '')}
            <ExternalLink size={11} />
          </a>
        )}
        {running && view?.version && (
          <span className="text-[11px] text-muted shrink-0" data-testid="prod-server-version">
            {i18nT('apps.aiStudio.prodServer.version', { version: view.version })}
          </span>
        )}
        <Btn
          onClick={() => run(() => prodServerApi.deployProdServer(projectId))}
          // Only our own in-flight request disables the buttons. A deploying
          // project MUST keep its 停止 clickable: a build that hangs is cancelled
          // with it, and prodserver.stop() is written to kill a half-launched set
          // (it bumps the generation the deploy thread checks).
          disabled={querying || pending || deploying}
          data-testid="prod-server-deploy"
          className="shrink-0"
        >
          <Rocket size={12} className="lucide-inline" />
          {running
            ? i18nT('apps.aiStudio.prodServer.redeploy')
            : i18nT('apps.aiStudio.prodServer.deploy')}
        </Btn>
        {(running || deploying) && (
          <Btn
            onClick={() => run(() => prodServerApi.stopProdServer(projectId))}
            disabled={pending}
            data-testid="prod-server-stop"
            className="shrink-0"
          >
            <Square size={12} className="lucide-inline" />
            {i18nT('apps.aiStudio.prodServer.stop')}
          </Btn>
        )}
        <Clickable
          onClick={toggleLog}
          data-testid="prod-server-log-toggle"
          className="text-[11px] text-muted hover:text-text cursor-pointer shrink-0 whitespace-nowrap"
        >
          {showLog
            ? i18nT('apps.aiStudio.prodServer.hide_log')
            : i18nT('apps.aiStudio.prodServer.view_log')}
        </Clickable>
      </div>

      {hint && (
        <div className="text-[11px] text-muted" data-testid="prod-server-hint">
          {hint}
        </div>
      )}
      {actionError && (
        <div className="text-[11px] text-err" data-testid="prod-server-action-error">
          {actionError}
        </div>
      )}
      {failure && (
        // VERBATIM: `_fail` wrote 「<步骤名>失败：<原文>」 into `message`, so
        // re-templating the step here would print it twice, and paraphrasing the
        // tail would drop the only copy of the real error.
        <div
          className="text-[11px] text-err whitespace-pre-wrap break-all"
          data-testid="prod-server-error"
        >
          {failure.message || failure.failedStep || i18nT('apps.aiStudio.prodServer.failed')}
        </div>
      )}
      {showLog && (
        <pre
          data-testid="prod-server-log"
          className="max-h-[220px] overflow-auto rounded-md border border-border bg-bg px-2 py-1.5 text-[10.5px] leading-[1.45] text-muted whitespace-pre-wrap break-all"
        >
          {logLoading
            ? i18nT('apps.aiStudio.prodServer.log_loading')
            : (logLines ?? []).join('\n') || i18nT('apps.aiStudio.prodServer.log_empty')}
        </pre>
      )}
    </div>
  )
}
