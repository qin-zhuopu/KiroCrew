// The 开发 tab's development board (ACP-2085-S4, design 07 §〇-1/§〇-2, cut to
// the one-phase version the ticket names). One button, one task list, one log,
// and an acceptance block that appears only once every task is done.
//
// Two rules hold the whole component together.
//
// (1) The board's state is the BACKEND's, never ours. Every render reads
// `GET …/dev/dag`, which reads `<workspace>/.ai-studio/dev-run.json` — the file
// the scheduler writes on every state change. A refresh, a second tab, or a
// gateway restart therefore draw the same board, which is what makes a run that
// died mid-page legible instead of a spinner that never ends. Nothing here
// derives a node's state from a timer or from what it last sent.
//
// (2) A node's failure text is shown VERBATIM. `message` is the assistant's own
// last line (「失败：单测没过」) or the scheduler's one-line verdict (「超时」,
// 「回复说完成了，但没有新提交」). Re-templating it would hide the exact sentence
// the next round of work needs, and the ticket says so in as many words.
//
// The confirm step is not ceremony: 开始开发 hands the workspace to an assistant
// session that writes code and commits it without asking each time. That is a
// consequence worth one click, and the button's label changes to name it while
// the click is live (「从失败处继续」 after a failed round), because continuing is
// a different decision from starting.
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Hammer } from 'lucide-react'
import { Btn } from '../../components/ui'
import Clickable from '../../components/Clickable'
import { i18nT } from '../../i18n/t'
import {
  devBoardApi,
  StudioApiError,
  type StudioAcceptRecord,
  type StudioDevBoardApi,
  type StudioDevNodeState,
  type StudioDevRunState,
} from './studioApi'

/** The board's refusals that get their own sentence, keyed by the backend's
 * machine `code`. The backend's `error` prose is not localized — the code is the
 * contract, and a localized UI that renders an English sentence verbatim cannot
 * be translated by construction (docs/system-specs/common/error-handling.md, and
 * ProjectsListPage.apiErrorMessage does the same thing for this app).
 *
 * Deliberately NOT here: `not_ready`. That message is the page names, and the
 * names are the whole point — a translated sentence would drop the one piece of
 * data telling the operator which 页 to finish in the 需求 tab. Same for a node
 * failure `message`: it is the assistant's own last line. */
const NOTICE_KEY: Record<string, string> = {
  no_pages: 'apps.aiStudio.devDag.err_no_pages',
  run_active: 'apps.aiStudio.devDag.err_run_active',
  dev_not_done: 'apps.aiStudio.devDag.err_dev_not_done',
  app_disabled: 'apps.aiStudio.err_app_disabled',
}

function noticeText(err: unknown): string {
  if (err instanceof StudioApiError) {
    const key = NOTICE_KEY[err.code]
    if (key) return i18nT(key)
    return err.message
  }
  return err instanceof Error ? err.message : String(err)
}

/** The four node states, each with its own copy. The board renders exactly one
 * of the four words per node — 07 §〇-1 makes that set a contract, and an
 * untranslated fifth value would read as a bug in the scheduler. */
const NODE_STATE_KEY: Record<StudioDevNodeState, string> = {
  queued: 'apps.aiStudio.devDag.node_queued',
  running: 'apps.aiStudio.devDag.node_running',
  done: 'apps.aiStudio.devDag.node_done',
  failed: 'apps.aiStudio.devDag.node_failed',
}

const NODE_STATE_CLASS: Record<StudioDevNodeState, string> = {
  queued: 'text-muted',
  running: 'text-warn',
  done: 'text-ok',
  failed: 'text-err',
}

/** The run's own one-line status. `idle` is 「空闲」 — no run has ever started,
 * which is a state of the board, not an error. */
const RUN_STATE_KEY: Record<StudioDevRunState, string> = {
  idle: 'apps.aiStudio.devDag.run_idle',
  running: 'apps.aiStudio.devDag.run_running',
  done: 'apps.aiStudio.devDag.run_done',
  failed: 'apps.aiStudio.devDag.run_failed',
}

export default function DevDagPanel({ projectId, api = devBoardApi }: {
  projectId: string
  /** the board's reads; the real client by default, a stand-in in tests */
  api?: StudioDevBoardApi
}) {
  const queryClient = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const [starting, setStarting] = useState(false)
  const [notice, setNotice] = useState('')
  const [showLog, setShowLog] = useState(false)
  const [accepting, setAccepting] = useState(false)

  const dagQuery = useQuery({
    queryKey: ['ai-studio', 'dev-dag', projectId],
    queryFn: () => api.getDevDag(projectId),
    // Only a running round changes on its own, and it changes on a file the
    // gateway writes — 3s is the ticket's cadence, and it stops the moment the
    // run reaches a terminal state so a finished board costs no requests.
    refetchInterval: (query) => (query.state.data?.runState === 'running' ? 3000 : false),
  })
  const recordsQuery = useQuery({
    queryKey: ['ai-studio', 'accept-records', projectId],
    queryFn: () => api.listAcceptRecords(projectId),
  })
  const logQuery = useQuery({
    queryKey: ['ai-studio', 'dev-log', projectId],
    queryFn: () => api.getDevLog(projectId, 100),
    // the log is a file tail on the backend and it stopped changing when the run
    // did, so it is pulled on open — never polled beside the board
    enabled: showLog,
  })

  const dag = dagQuery.data
  const nodes = dag?.nodes ?? []
  const runState: StudioDevRunState = dag?.runState ?? 'idle'
  const running = runState === 'running'
  const allDone = runState === 'done'
  // A failed round is resumable, and the button must say so: the backend keeps
  // the done nodes done and re-queues the rest, so this click does not redo work
  // that already committed.
  const resume = runState === 'failed'
  const latest: StudioAcceptRecord | undefined = recordsQuery.data?.records[0]

  const refreshDag = () =>
    queryClient.invalidateQueries({ queryKey: ['ai-studio', 'dev-dag', projectId] })

  async function confirmStart() {
    setConfirming(false)
    setNotice('')
    setStarting(true)
    try {
      // pages omitted: every page whose requirement verdict allows it. The
      // backend refuses a 不齐 page either way, so the guard is not client-side.
      await api.startDev(projectId)
      await refreshDag()
    } catch (e) {
      // A 422 `not_ready` names the pages that are 不齐, a 409 says a round is
      // already running. Codes with their own copy get it; the rest stay the
      // backend's sentence, which is honest even when it is English.
      setNotice(noticeText(e))
      await refreshDag()
    } finally {
      setStarting(false)
    }
  }

  async function runAccept() {
    setNotice('')
    setAccepting(true)
    try {
      const res = await api.runAccept(projectId)
      const previous = recordsQuery.data?.records ?? []
      queryClient.setQueryData(['ai-studio', 'accept-records', projectId], {
        records: [res.record, ...previous],
      })
    } catch (e) {
      // 409 dev_not_done is the honest answer when a node failed after the board
      // last read; the message says it, so the board re-reads instead of guessing
      setNotice(noticeText(e))
      await refreshDag()
    } finally {
      setAccepting(false)
    }
  }

  async function toggleLog() {
    setShowLog((v) => !v)
  }

  const failedCount = latest ? latest.results.filter((r) => !r.ok).length : 0

  return (
    <div className="flex flex-col gap-2" data-testid="ai-studio-dev-dag-panel">
      <div className="flex items-center gap-2">
        <Btn
          onClick={() => setConfirming(true)}
          disabled={running || starting}
          data-testid="ai-studio-dev-start-btn"
          className="shrink-0"
        >
          <Hammer size={13} className="lucide-inline" />
          {resume ? i18nT('apps.aiStudio.devDag.continue') : i18nT('apps.aiStudio.devDag.start')}
        </Btn>
        <span
          className={`text-[11px] ${running ? 'text-warn' : runState === 'failed' ? 'text-err' : 'text-muted'}`}
          data-testid="ai-studio-dev-status"
        >
          {i18nT(RUN_STATE_KEY[runState])}
        </span>
      </div>

      {confirming && (
        // A plain inline block, not a portal: this lives in the sidebar's scroll
        // container, and the consequence it names is specific to this button.
        <div
          className="rounded-md border border-border bg-bg px-2 py-2 text-[11px] text-text"
          data-testid="ai-studio-dev-confirm"
        >
          <div className="mb-2 whitespace-pre-wrap">
            {i18nT('apps.aiStudio.devDag.confirm_body')}
          </div>
          <div className="flex items-center gap-2">
            <Btn onClick={confirmStart} data-testid="ai-studio-dev-confirm-ok">
              {i18nT('apps.aiStudio.devDag.confirm_ok')}
            </Btn>
            <Btn onClick={() => setConfirming(false)} data-testid="ai-studio-dev-confirm-cancel">
              {i18nT('apps.aiStudio.devDag.confirm_cancel')}
            </Btn>
          </div>
        </div>
      )}

      {notice && (
        <div className="text-[11px] text-err whitespace-pre-wrap break-all" data-testid="ai-studio-dev-error">
          {notice}
        </div>
      )}

      <div className="flex flex-col" data-testid="ai-studio-dev-dag">
        {nodes.length === 0 && (
          <div className="text-[11px] text-muted px-0.5" data-testid="ai-studio-dev-dag-empty">
            {i18nT('apps.aiStudio.devDag.no_nodes')}
          </div>
        )}
        {nodes.map((node) => (
          <div key={node.jiraKey} data-testid={`ai-studio-dev-dag-node-${node.jiraKey}`}>
            <div className="flex items-center gap-2 px-0.5 py-1">
              <span className="text-[12px] text-text truncate min-w-0 flex-1">{node.title}</span>
              <span
                className={`text-[11px] shrink-0 ${NODE_STATE_CLASS[node.state] ?? 'text-muted'}`}
                data-testid={`ai-studio-dev-dag-node-state-${node.jiraKey}`}
              >
                {i18nT(NODE_STATE_KEY[node.state] ?? NODE_STATE_KEY.queued)}
              </span>
            </div>
            {node.state === 'failed' && node.message && (
              // verbatim, per the file header
              <div
                className="text-[11px] text-err whitespace-pre-wrap break-all pl-2 pb-1"
                data-testid={`ai-studio-dev-dag-node-message-${node.jiraKey}`}
              >
                {node.message}
              </div>
            )}
          </div>
        ))}
      </div>

      <div>
        <Clickable
          onClick={toggleLog}
          data-testid="ai-studio-dev-log-toggle"
          className="text-[11px] text-muted hover:text-text cursor-pointer"
        >
          {showLog
            ? i18nT('apps.aiStudio.devDag.log_hide')
            : i18nT('apps.aiStudio.devDag.log_show')}
        </Clickable>
        {showLog && (
          <pre
            data-testid="ai-studio-dev-dag-log"
            className="mt-1 max-h-[220px] overflow-auto rounded-md border border-border bg-bg px-2 py-1.5 text-[10.5px] leading-[1.45] text-muted whitespace-pre-wrap break-all"
          >
            {logQuery.isPending
              ? i18nT('apps.aiStudio.devDag.log_loading')
              : (logQuery.data?.lines ?? []).join('\n') || i18nT('apps.aiStudio.devDag.log_empty')}
          </pre>
        )}
      </div>

      {allDone && (
        // The block appears only on an all-green round: a failed node must not
        // offer 跑验收 (07 §D2 「不许假全绿」), and the backend 409s anyway.
        <div className="flex flex-col gap-1 border-t border-border pt-2">
          <div className="flex items-center gap-2">
            <Btn
              onClick={runAccept}
              disabled={accepting}
              data-testid="ai-studio-accept-run-btn"
              className="shrink-0"
            >
              {i18nT('apps.aiStudio.devDag.accept_run')}
            </Btn>
            {latest && (
              <span
                className={`text-[11px] ${latest.result === 'passed' ? 'text-ok' : 'text-err'}`}
                data-testid="ai-studio-accept-status"
              >
                {latest.result === 'passed'
                  ? i18nT('apps.aiStudio.devDag.accept_passed')
                  : i18nT('apps.aiStudio.devDag.accept_failed', { n: failedCount })}
              </span>
            )}
          </div>
          {latest && (
            <div className="flex flex-col" data-testid="ai-studio-accept-result-list">
              {latest.results.map((r, index) => (
                <div key={r.id} data-testid={`ai-studio-accept-result-row-${index}`}>
                  <div className="flex items-center gap-2 px-0.5 py-1 text-[11px]">
                    <span className={r.ok ? 'text-ok shrink-0' : 'text-err shrink-0'} aria-hidden>
                      {r.ok ? '✓' : '✗'}
                    </span>
                    <span className="text-text truncate min-w-0 flex-1">{r.id}</span>
                  </div>
                  {!r.ok && r.tail && (
                    <pre className="text-[10.5px] leading-[1.45] text-err whitespace-pre-wrap break-all pl-5 pb-1">
                      {r.tail}
                    </pre>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
