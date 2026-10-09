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
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Hammer, Scissors } from 'lucide-react'
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
 * which is a state of the board, not an error. `planned` is 「已拆任务」: the
 * tasks and their Jira issues exist and nothing has been dispatched yet, so the
 * next click is 开始开发 rather than 继续 (ACP-2085-S6). */
const RUN_STATE_KEY: Record<StudioDevRunState, string> = {
  idle: 'apps.aiStudio.devDag.run_idle',
  planned: 'apps.aiStudio.devDag.run_planned',
  running: 'apps.aiStudio.devDag.run_running',
  done: 'apps.aiStudio.devDag.run_done',
  failed: 'apps.aiStudio.devDag.run_failed',
}

/** The two refresh cadences the ticket names. A running round moves on a file
 * the gateway writes every few seconds; anything else only moves when SOMEONE
 * else moves it — another tab, another agent session, a Jira round-trip — and
 * 10s is what the board needs to look alive without becoming a poll storm on a
 * personal server that also serves the chat. */
export const REFRESH_FAST_MS = 3000
export const REFRESH_SLOW_MS = 10000

/** What the 需求 tab fires when its 〔开始开发〕 succeeds (ACP-2150: the event
 * existed and no one listened). */
export const START_DEV_EVENT = 'ai-studio:start-dev'

/** One 开始开发 the 需求 tab asked for and the 开发 tab has not served yet. */
export interface StartDevRequest {
  projectId: string
  /** the one page the click was about, omitted = every page that is ready */
  pages?: string[]
  /** identity, so a board can tell a new request from the one it already served */
  seq: number
}

/** The channel that carries it from the tab's owner down to the board.
 *
 * WHY A CONTEXT AND NOT A LISTENER ON THE BOARD
 *
 * The two parties that must act on the event are mounted at different times.
 * ToolSidebar owns the tab state and is on screen the whole time, so it can
 * switch to 开发 and it holds the request in its own state. The board that does
 * the splitting is `devBoard`, an injected node that EXISTS ONLY while the 开发
 * tab is open — so at the moment RequirementPage fires the event it is usually
 * not mounted, and a listener on it would be a listener that is not there. That
 * is ACP-2150: the event existed, nothing received it.
 *
 * Context reaches an injected node because it is read at the node's POSITION IN
 * THE TREE, not where the element was created — the page creates `devBoard` but
 * the sidebar renders it, inside this provider. A board mounted later reads the
 * pending request on its first render; a board already on screen reads it the
 * moment the state changes. No module-level queue: the request lives in the
 * sidebar's state and dies with it. */
export interface StartDevChannel {
  request: StartDevRequest | null
  /** tell the holder this `seq` has been served, so it stops asking */
  served: (seq: number) => void
}

export const StartDevContext = createContext<StartDevChannel | null>(null)

export default function DevDagPanel({ projectId, api = devBoardApi }: {
  projectId: string
  /** the board's reads; the real client by default, a stand-in in tests */
  api?: StudioDevBoardApi
}) {
  const queryClient = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const [starting, setStarting] = useState(false)
  const [splitting, setSplitting] = useState(false)
  const [notice, setNotice] = useState('')
  const [showLog, setShowLog] = useState(false)
  const [accepting, setAccepting] = useState(false)

  const dagQuery = useQuery({
    queryKey: ['ai-studio', 'dev-dag', projectId],
    queryFn: () => api.getDevDag(projectId),
    // Both branches poll, which is the point of the change: the board is no
    // longer only about THIS tab's click. A planned run turns into a running
    // one elsewhere, a node's Jira number appears when a round trip lands, and
    // a finished board must still show what the last round did.
    refetchInterval: (query) =>
      query.state.data?.runState === 'running' ? REFRESH_FAST_MS : REFRESH_SLOW_MS,
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
  // 〔拆分任务〕 shows where the ticket puts it — an idle board, or a board with
  // no plan. Once tasks are listed they ARE the plan (planned, running, or the
  // residue of a round), and offering to rebuild it next to 开始开发 would offer
  // to void Jira issues somebody may already be working on.
  // 实战-4（2026-10-09）：一份拆错的计划（把模板已做好的页也拆了进来）跑失败后，
  // 不许重新拆分 = 只能「从失败处继续」把错的计划跑完。失败 / 已拆未开工时也给重新拆分；
  // 后端只作废没完成的 Jira 子单，做完的保留。跑着的时候不给。
  const splitBtn = runState === 'idle' || runState === 'failed' || runState === 'planned' || nodes.length === 0
  const replan = nodes.length > 0
  // key AND url come from the same read: a board whose header names ACP-1 must
  // not link somewhere else. The backend pairs them, and an empty key means
  // there is no parent issue, which renders no row at all.
  const parentLink = String(dag?.jiraParentUrl ?? '')
  const latest: StudioAcceptRecord | undefined = recordsQuery.data?.records[0]

  const refreshDag = useCallback(
    () => queryClient.invalidateQueries({ queryKey: ['ai-studio', 'dev-dag', projectId] }),
    [queryClient, projectId],
  )

  /** 〔拆分任务〕: build the node list AND its Jira sub-issues without starting
   * anything (ACP-2085-S6). `pages` is omitted for the button (every page whose
   * verdict allows it) and named for the 需求 tab's 开始开发 event, which asks
   * for one page. Splitting is idempotent server-side — the same page set
   * returns the same plan and creates no second batch of issues — so re-received
   * events are harmless. */
  const splitTasks = useCallback(
    async (pages?: string[]) => {
      setNotice('')
      setSplitting(true)
      try {
        await api.planDev(projectId, pages)
      } catch (e) {
        setNotice(noticeText(e))
      } finally {
        setSplitting(false)
        await refreshDag()
      }
    },
    [projectId, api, refreshDag],
  )

  // The 开始开发 the 需求 tab asked for, handed down by whoever owns the tab
  // state (ToolSidebar in the workbench, the test that mounts a bare board).
  // `splitTasks` is stable, so this effect re-runs only when a NEW request
  // arrives — and a mounted board is exactly when a pending one gets served,
  // which is the case a listener on this component would have missed.
  const startDev = useContext(StartDevContext)
  const servedRef = useRef(0)
  useEffect(() => {
    const req = startDev?.request
    if (!startDev || !req || req.projectId !== projectId) return
    if (req.seq <= servedRef.current) return
    servedRef.current = req.seq
    startDev.served(req.seq)
    void splitTasks(req.pages)
  }, [startDev, projectId, splitTasks])

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
        {splitBtn && (
          // 先拆任务、后开发 (ACP-2085-S6): the split is its own decision, taken
          // before any code is written, because that is when the Jira issues get
          // filed and when the operator can still see what the round will do.
          <Btn
            onClick={() => void splitTasks()}
            disabled={running || splitting}
            data-testid="ai-studio-dev-plan-btn"
            className="shrink-0"
          >
            <Scissors size={13} className="lucide-inline" />
            {replan ? i18nT('apps.aiStudio.devDag.replan') : i18nT('apps.aiStudio.devDag.plan')}
          </Btn>
        )}
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

      <div className="text-[10.5px] text-muted" data-testid="ai-studio-dev-refresh-hint">
        {i18nT(running ? 'apps.aiStudio.devDag.refresh_fast' : 'apps.aiStudio.devDag.refresh_slow')}
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

      {parentLink && (
        // One line above the tasks: the campaign's parent issue, so the board
        // says which Jira issue all of these hang under. Absent when the project
        // never got one (no Jira configured, or the create failed — the reason
        // then sits on the individual rows, where the build failed).
        <div className="text-[11px] text-muted" data-testid="ai-studio-dev-dag-jira-parent-row">
          {i18nT('apps.aiStudio.devDag.jira_parent')}{' '}
          <a
            href={parentLink}
            target="_blank"
            rel="noopener noreferrer"
            data-testid="ai-studio-dev-dag-jira-parent"
            className="text-accent hover:underline"
          >
            {dag?.jiraParent ?? ''}
          </a>
        </div>
      )}

      <div className="flex flex-col" data-testid="ai-studio-dev-dag">
        {nodes.length === 0 && (
          <div className="text-[11px] text-muted px-0.5" data-testid="ai-studio-dev-dag-empty">
            {i18nT(splitBtn ? 'apps.aiStudio.devDag.no_nodes_plan' : 'apps.aiStudio.devDag.no_nodes')}
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
            {node.state === 'running' && node.worktree && (
              // ACP-2207: which directory this row is actually writing in. Two
              // rows both reading 「in progress」 prove nothing about the
              // isolation; the paths being different is the whole point. Rendered
              // only while running — the backend clears the field when the branch
              // merges, and a done row pointing at a removed directory is a lie.
              // The path is data from the backend, so it is shown verbatim.
              <div
                className="pl-2 pb-1 text-[10.5px] text-muted whitespace-pre-wrap break-all"
                data-testid={`ai-studio-dev-dag-node-worktree-${node.jiraKey}`}
                title={node.branch}
              >
                {node.worktree}
              </div>
            )}
            {node.state === 'failed' && node.message && (
              // verbatim, per the file header
              <div
                className="text-[11px] text-err whitespace-pre-wrap break-all pl-2 pb-1"
                data-testid={`ai-studio-dev-dag-node-message-${node.jiraKey}`}
              >
                {node.message}
              </div>
            )}
            {node.jira ? (
              <a
                href={node.jiraUrl}
                target="_blank"
                rel="noopener noreferrer"
                data-testid={`ai-studio-dev-dag-node-jira-${node.jiraKey}`}
                title={node.jiraUrl}
                className="block min-w-0 truncate pl-2 pb-1 text-[11px] text-accent hover:underline"
              >
                {node.jira}
              </a>
            ) : node.jiraError ? (
              // The build's own failure line, verbatim, prefixed by why the board
              // is showing it. A row with no number and no reason would read as
              // a bug in this panel instead of a broken Jira command.
              <div
                className="pl-2 pb-1 text-[11px] text-muted whitespace-pre-wrap break-all"
                data-testid={`ai-studio-dev-dag-node-jira-missing-${node.jiraKey}`}
              >
                {i18nT('apps.aiStudio.devDag.jira_missing', { reason: node.jiraError })}
              </div>
            ) : null}
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
