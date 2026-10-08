// One requirement page (ACP-2015 step 2 read, ACP-2104 step 4 writes; RFC §7
// B2/B5/B6, §8): the v34 verdict bar on top, the graph-generated document in an
// editor below it, 〔保存〕 and 〔开始开发〕 at the top right, and the raw graph
// behind a toggle.
//
// The doc is a VIEW of the graph (RFC §2 铁律 2), and that decides what the two
// buttons mean:
//   - 保存 is 直改. It never writes a file. The backend diffs the two views, and
//     the diff goes to the 需求会话 as a change REQUEST which the writer lands
//     back into the graph (§5 DocDirectEdited). Until it does, the bar says
//     「改动待落回需求」 (pendingEdit) and 开始开发 is greyed — the readiness on
//     screen describes a graph that no longer matches what the owner asked for.
//   - 开始开发 sends the graphHash the bar is showing. The backend re-runs the
//     verdict and re-checks that hash (R2), so the frontend's own reading can
//     never authorise a start; a 409/422 is a fresh verdict arriving, not a
//     failure to hide.
//
// The editing surface is a textarea over the Markdown source, not the page's
// rich editor: a rendered v34 document is tens of KB, and Tiptap's Markdown
// round-trip is lossy on that shape — a lossy round-trip turns a save into a
// diff full of changes the owner never made. DocEditor is not reused for the
// same reason: its autosave-draft tier belongs to an authored doc, and silently
// dropping it from a shared component would break the project tabs.
//
// The read re-runs every 5s: the graph is a file the assistant edits while the
// owner is looking at this page, and the owner's whole point is that the page
// says NOW what the graph says NOW (ACP-2085 S2 / RFC §7 B4). A new graphHash
// therefore re-renders both the bar and the document, and while the backend is
// still regenerating the document for the newest graph (`stale`) the bar says
// 「生成中…」 instead of repeating a verdict that no longer describes the file.
// A refresh does NOT touch a dirty buffer — the owner's unsaved typing is the
// one thing on this page the assistant does not own.
import { useCallback, useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import MarkdownRenderer from '../../components/MarkdownRenderer'
import ErrorNotice from '../../components/ErrorNotice'
import { Btn } from '../../components/ui'
import { useDialogFocusTrap } from '../../hooks/useDialogFocusTrap'
import { i18nT } from '../../i18n/t'
import { VERDICT_STYLE, gapCount } from './reqVerdict'
import {
  StudioApiError,
  requirementWriteApi,
  studioApi,
  type StudioApi,
  type StudioVerdict,
} from './studioApi'

/** The 判定条's sentence — the full reading, not the badge's short word. */
function barText(verdict: StudioVerdict, gaps: number): string {
  if (verdict === '全齐') return i18nT('apps.aiStudio.req_bar_full')
  if (verdict === '不齐') return i18nT('apps.aiStudio.req_bar_incomplete')
  return i18nT('apps.aiStudio.req_bar_gap', { n: gaps })
}

/** Why the bar reads 「需求刚刚变了，判定为不齐，请先补齐」: 409 (the graph moved
 * under the click) and 422 (it is not buildable) mean the same thing to the
 * owner — the backend looked at the CURRENT graph and cannot start it — and the
 * bar redraws with the details a moment later, so the strip only has to say
 * which fact arrived, not restate the gaps the 422 body carries. */
function isStartRefusal(err: unknown): boolean {
  return err instanceof StudioApiError
    && (err.code === 'graph_changed' || err.code === 'not_ready')
}

export default function RequirementPage({ projectId, page, api = studioApi, onStarted }: {
  projectId: string
  /** the page name, which IS the graph file's stem in the workspace */
  page: string
  /** data source, injectable for the demo's snapshot fake */
  api?: StudioApi
  /** the start request landed. The event on `window` is the one this app's own
   * dev tab listens for (another work stream's tab, same event name); this prop
   * is the app-internal half of the same fact, so the workbench can switch tabs
   * without any component subscribing to a global. */
  onStarted?: (page: string) => void
}) {
  const [gapsOpen, setGapsOpen] = useState(false)
  const [showGraph, setShowGraph] = useState(false)
  // 直改 buffer: null while the owner has typed nothing, else the Markdown they
  // typed. Holding it separately from the document is what makes "dirty" a fact
  // rather than a guess, and what lets a 5s refresh replace the VIEW while the
  // unsaved edit stays put.
  const [buffer, setBuffer] = useState<string | null>(null)
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'conflict' | 'error'>('idle')
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [startState, setStartState] = useState<'idle' | 'starting' | 'requested' | 'refused'>('idle')
  const queryClient = useQueryClient()

  const { data, error, isFetching } = useQuery({
    queryKey: ['ai-studio', 'requirement', projectId, page],
    queryFn: () => api.getRequirement(projectId, page),
    refetchInterval: 5000,
  })

  // A page change re-mounts (WorkArea keys on project+page) rather than resetting
  // seven pieces of state, so the buffer cannot follow the owner across pages;
  // this covers the paths that do NOT re-mount, where a stale buffer would let a
  // save post page A's text against page B's docHash.
  useEffect(() => {
    setBuffer(null)
    setSaveState('idle')
    setStartState('idle')
    setConfirmOpen(false)
  }, [projectId, page])

  // 「生成中…」 is the bar's reading of a refresh in flight (RFC §7 B4), and it
  // is literal, not decoration: one read runs `jc fe reqdoc check` + `render`
  // over the graph file, so while this poll is running the verdict on screen IS
  // the previous graph's answer and a new document is being computed. `stale`
  // (R1: the graph's hash moved and the doc was not regenerated yet) is the
  // durable version of the same sentence. The first read is excluded — nothing
  // is being refreshed then, and the bar already refuses to paint a verdict.
  // Only the WORDS change while regenerating; the bar keeps the colour of the
  // verdict it is holding, so a poll does not read as the readiness flipping.
  // A pending direct edit OUTRANKS 「生成中」. The pending sentence is the fact the
  // owner just caused and can act on; letting a 5s poll replace it for the length
  // of a subprocess makes the one state that gates 开始开发 flicker.
  const generating = !data?.pendingEdit
    && (Boolean(data?.stale) || (isFetching && data !== undefined))

  // The verdict service missing is a STATE the bar renders, not a failure strip
  // — the page still has nothing to say about readiness, and saying so in the
  // bar is the honest version of "we don't know".
  const unavailable = error instanceof StudioApiError && error.code === 'reqdoc_cmd_unavailable'
  const style = VERDICT_STYLE[data?.verdict ?? '不齐'] ?? VERDICT_STYLE['不齐']
  const gaps = data ? gapCount(data.tiers) : 0
  const groups = data
    ? ([
      ['apps.aiStudio.req_group_errors', data.errors],
      ['apps.aiStudio.req_group_missing', data.missing],
      ['apps.aiStudio.req_group_tiers', [...data.tiers.api, ...data.tiers.ui, ...data.tiers.parts]],
    ] as const).filter(([, items]) => items.length > 0)
    : []

  const dirty = buffer !== null && data !== undefined && buffer !== data.markdown
  // The one sentence the owner needs at the moment a poll would eat their typing:
  // the new text is NOT swapped in, so this is a fact about the buffer, not a hint.
  const heldBack = dirty && data !== undefined && buffer !== (data.markdown ?? '')

  // A refresh is a RE-READ of this page, so it re-runs the read on the spot: the
  // backend recomputes the verdict and re-renders the doc for the graph the
  // assistant just moved, and the new `docHash` arrives with it. Navigating is
  // the wrong verb here — it would throw away the tab the owner is standing in.
  const refresh = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ['ai-studio', 'requirement', projectId, page] })
  }, [queryClient, projectId, page])

  // One gate, three readings (B6): 不齐 cannot start; 「有缺口」 confirms first;
  // 全齐 goes straight through. `pendingEdit` and 「生成中」 are the two states
  // where the answer is not knowable yet, so they block too.
  const blockReason = !data
    ? 'loading'
    : unavailable
      ? 'unavailable'
      : generating
        ? 'generating'
        : data.pendingEdit
          ? 'pending'
          : data.verdict === '不齐'
            ? 'incomplete'
            : null
  const startDisabled = blockReason !== null || startState === 'starting'
  const startTitle = blockReason === 'incomplete'
    ? i18nT('apps.aiStudio.req_start_blocked', {
      gap: [...data!.errors, ...data!.missing][0] ?? '',
    })
    : blockReason === 'pending'
      ? i18nT('apps.aiStudio.req_bar_pending')
      : blockReason === 'generating'
        ? i18nT('apps.aiStudio.req_generating')
        : blockReason === 'unavailable'
          ? i18nT('apps.aiStudio.req_service_unavailable')
          : undefined
  const alreadyStarted = data?.devState === 'started'

  const save = async () => {
    if (!data || buffer === null || saveState === 'saving') return
    setSaveState('saving')
    try {
      // the hash of the view the buffer was typed AGAINST. Sending the newest
      // hash instead would be the bug: it claims the owner saw the current text.
      const result = await requirementWriteApi.directEditRequirement(
        projectId, page, data.docHash, buffer,
      )
      setBuffer(null)
      setSaveState('idle')
      // the bar's 「改动待落回需求」 is a backend fact (pendingEdit), so the page
      // goes and reads it rather than painting it from here
      if (result.changed) refresh()
    } catch (err) {
      if (err instanceof StudioApiError && err.code === 'doc_changed') setSaveState('conflict')
      else setSaveState('error')
    }
  }

  const runStart = async () => {
    // the same gate the button enforces, checked again here. The confirm dialog
    // also calls this, so the gate cannot live in the button's handler alone —
    // and the 5s poll can move a verdict between a render and this click. The
    // backend would refuse anyway (it re-checks the hash and re-runs the check);
    // this is the 0-cost version of not sending a request we already know about.
    if (!data || startState === 'starting' || blockReason !== null) return
    setStartState('starting')
    try {
      await requirementWriteApi.startRequirement(projectId, page, data.graphHash)
      setStartState('requested')
      // the 开发 page listens for this (RFC §9.4 hands task splitting to another
      // work stream); dispatching is the point, opening that tab is not this
      // component's business and it cannot — the tab list lives in the parent.
      window.dispatchEvent(new CustomEvent('ai-studio:start-dev', { detail: { projectId, page } }))
      onStarted?.(page)
      refresh()
    } catch (err) {
      setStartState('refused')
      // either refusal means the on-screen verdict was stale, so re-read and let
      // the bar say what the current graph actually is
      if (isStartRefusal(err)) refresh()
    }
  }

  return (
    <div className="p-4" data-testid="requirement-page" data-page={page}>
      <div className="flex items-start justify-between gap-3 mb-3">
        {/* The bar states a readiness verdict, so it renders only once the page
            either has one (`data`) or knows why it cannot (`error`) — a bar
            that paints while the read is in flight invites a read of 「齐」
            that nobody checked. */}
        {(data || error) && (
          <div
            data-testid="req-verdict-bar"
            // 待落回 is its own colour: the verdict it would otherwise repeat is
            // about a graph that no longer matches what the owner asked for, so
            // keeping the old colour under new words would read as "still green".
            className={`flex-1 rounded-lg border px-3 py-2 text-[12px] font-semibold ${
              data?.pendingEdit ? 'border-warn bg-warn-subtle text-warn' : `${style.bar} ${style.strong}`
            }`}
          >
            {unavailable
              ? i18nT('apps.aiStudio.req_service_unavailable')
              : data?.pendingEdit
                ? i18nT('apps.aiStudio.req_bar_pending')
                : generating
                  ? i18nT('apps.aiStudio.req_generating')
                  : data
                    ? barText(data.verdict, gaps)
                    : i18nT('apps.aiStudio.req_loading')}
            {data && !data.pendingEdit && groups.length > 0 && (
              <button
                type="button"
                data-testid="req-gaps-toggle"
                onClick={() => setGapsOpen((v) => !v)}
                className="ml-2 font-normal underline cursor-pointer"
              >
                {i18nT(gapsOpen ? 'apps.aiStudio.req_collapse' : 'apps.aiStudio.req_expand')}
              </button>
            )}
          </div>
        )}
        <div className="flex shrink-0 items-center gap-1.5">
          {alreadyStarted ? (
            // R3's two readings: 「已开工」 is the settled state, and the line
            // below says what the void marker means — the record still exists,
            // the owner just has to ask again.
            <Btn data-testid="req-start-btn" disabled>
              {i18nT('apps.aiStudio.req_start_started')}
            </Btn>
          ) : (
            <Btn
              data-testid="req-start-btn"
              primary
              disabled={startDisabled}
              title={startTitle}
              // B6's three readings, one click each: 「有缺口」 asks first so the
              // owner says the gap risk out loud, 全齐 goes straight through.
              // The gate is here and NOT inside runStart because the confirm
              // dialog also calls runStart — gating the shared function would
              // make the confirmed path ask again, forever.
              onClick={() => {
                if (data?.verdict === '可以开工但有已知缺口') setConfirmOpen(true)
                else void runStart()
              }}
            >
              {i18nT('apps.aiStudio.req_start')}
            </Btn>
          )}
          <Btn
            data-testid="req-graph-toggle"
            aria-pressed={showGraph}
            onClick={() => setShowGraph((v) => !v)}
          >
            {i18nT(showGraph ? 'apps.aiStudio.req_show_doc' : 'apps.aiStudio.req_graph')}
          </Btn>
        </div>
      </div>

      {startState === 'requested' && (
        <div
          data-testid="req-start-result"
          className="mb-3 rounded-lg border border-ok bg-ok-subtle px-3 py-2 text-[12px] font-semibold text-ok"
        >
          {i18nT('apps.aiStudio.req_start_requested')}
        </div>
      )}
      {startState === 'refused' && (
        <div
          data-testid="req-start-refused"
          className="mb-3 rounded-lg border border-warn bg-warn-subtle px-3 py-2 text-[12px] font-semibold text-warn"
        >
          {i18nT('apps.aiStudio.req_start_refused')}
        </div>
      )}
      {data?.changedAfterStart && (
        <div
          data-testid="req-changed-after-start"
          className="mb-3 rounded-lg border border-warn bg-warn-subtle px-3 py-2 text-[12px] font-semibold text-warn"
        >
          {i18nT('apps.aiStudio.req_changed_after_start')}
        </div>
      )}

      {gapsOpen && groups.length > 0 && (
        <div data-testid="req-gaps" className="mb-3 rounded-lg border border-border bg-bg-elevated px-3 py-2">
          {groups.map(([key, items]) => (
            <div key={key} className="mb-2 last:mb-0">
              <div className="text-[11px] uppercase tracking-wide text-muted mb-1">{i18nT(key)}</div>
              <ul className="text-[12px] text-text list-disc pl-4">
                {items.map((item, i) => <li key={i}>{item}</li>)}
              </ul>
            </div>
          ))}
        </div>
      )}

      {!error && !data && (
        <div className="text-[12px] text-muted">{i18nT('apps.aiStudio.req_loading')}</div>
      )}
      {error && !unavailable && <ErrorNotice message={error instanceof Error ? error.message : String(error)} />}

      {data && (showGraph ? (
        // the raw graph, for the owner who wants to see the truth and not the
        // view of it
        <pre
          data-testid="req-graph-json"
          className="text-[11px] font-mono text-text whitespace-pre-wrap break-all rounded-lg border border-border bg-bg-elevated p-3 max-h-[70vh] overflow-auto"
        >
          {JSON.stringify(data.graph, null, 2)}
        </pre>
      ) : data.markdown === null ? (
        // v34 refuses to render an unqualified graph; the bar already says 不齐,
        // and the reasons are the same lists the gaps panel holds. BOTH of them:
        // a refused render is most often a 待定 rule (which lands in `missing`),
        // not a shape error — showing only `errors` here would explain the
        // refusal with an empty list, which is the one thing this panel exists
        // to prevent.
        <div data-testid="req-no-markdown" className="text-[12px] text-muted">
          <div className="mb-1.5">{i18nT('apps.aiStudio.req_no_markdown')}</div>
          {[...data.errors, ...data.missing].length > 0 && (
            <ul className="text-text list-disc pl-4">
              {[...data.errors, ...data.missing].map((e, i) => <li key={i}>{e}</li>)}
            </ul>
          )}
        </div>
      ) : (
        <div className="rounded-lg border border-border bg-card max-h-[70vh] flex flex-col overflow-hidden">
          <div className="flex items-center gap-2 border-b border-border px-3 py-1.5 shrink-0">
            <span className="text-[11px] text-muted">{i18nT('apps.aiStudio.req_doc_source_hint')}</span>
            <span className="flex-1" />
            {saveState === 'conflict' && (
              <>
                {/* the backend's sentence verbatim (RFC §8) — this is its reason,
                    not ours to rephrase — plus the only action that can resolve
                    it: re-read the view and retype against it */}
                <span data-testid="req-save-conflict" className="text-[12px] font-semibold text-warn">
                  {i18nT('apps.aiStudio.req_save_conflict')}
                </span>
                <Btn
                  data-testid="req-refresh-btn"
                  onClick={() => {
                    setBuffer(null)
                    setSaveState('idle')
                    refresh()
                  }}
                >
                  {i18nT('apps.aiStudio.req_refresh')}
                </Btn>
              </>
            )}
            {saveState === 'error' && (
              <span data-testid="req-save-error" className="text-[12px] font-semibold text-danger">
                {i18nT('apps.aiStudio.req_save_failed')}
              </span>
            )}
            <Btn
              data-testid="req-save-btn"
              primary
              disabled={!dirty || saveState === 'saving'}
              onClick={save}
            >
              {i18nT('apps.aiStudio.save')}
            </Btn>
          </div>
          {heldBack && (
            <div
              data-testid="req-buffer-held"
              className="border-b border-border bg-warn-subtle px-3 py-1.5 text-[11px] text-warn shrink-0"
            >
              {i18nT('apps.aiStudio.req_buffer_held')}
            </div>
          )}
          <textarea
            data-testid="req-doc-editor"
            className="flex-1 min-h-[40vh] w-full resize-none bg-transparent p-4 text-[13px] leading-6 font-mono text-text outline-none"
            value={buffer ?? (data.markdown ?? '')}
            onChange={(e) => {
              // typing over a resolved conflict starts a fresh attempt; the
              // buffer IS the new base the next save will be judged from
              if (saveState === 'conflict') setSaveState('idle')
              setBuffer(e.target.value)
            }}
            aria-label={page}
          />
          {/* the rendered document, kept (ACP-2015 step 2's promise: the doc
              renders RICH) under the source the owner can actually edit */}
          <div data-testid="req-doc" className="border-t border-border overflow-auto p-4 max-h-[40vh]">
            <MarkdownRenderer content={buffer ?? (data.markdown ?? '')} readOnlyCode />
          </div>
        </div>
      ))}

      {confirmOpen && data && (
        <StartConfirmDialog
          gaps={gaps}
          onCancel={() => setConfirmOpen(false)}
          onConfirm={() => {
            setConfirmOpen(false)
            void runStart()
          }}
        />
      )}
    </div>
  )
}

// B6's 「有缺口」 gate. Its own component so the focus trap mounts and unmounts
// with the dialog (the FreezeControl precedent, same reason).
function StartConfirmDialog({ gaps, onCancel, onConfirm }: {
  gaps: number
  onCancel: () => void
  onConfirm: () => void
}) {
  const dialogRef = useRef<HTMLDivElement>(null)
  useDialogFocusTrap(dialogRef, onCancel)
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={i18nT('apps.aiStudio.req_start')}
        tabIndex={-1}
        className="relative w-full max-w-[420px] border border-border rounded-[14px] bg-card p-5 shadow-2xl outline-hidden"
        onKeyDown={(e) => e.stopPropagation()}
      >
        <h2 className="text-[15px] font-semibold text-text-strong mb-2">
          {i18nT('apps.aiStudio.req_start')}
        </h2>
        <p className="text-[13px] leading-6 text-text">
          {i18nT('apps.aiStudio.req_start_confirm', { n: gaps })}
        </p>
        <div className="mt-4 flex items-center justify-end gap-2">
          <Btn onClick={onCancel}>{i18nT('apps.aiStudio.cancel')}</Btn>
          <Btn primary onClick={onConfirm} data-testid="req-start-confirm">
            {i18nT('apps.aiStudio.req_start')}
          </Btn>
        </div>
      </div>
    </div>
  )
}
