// The state-direct demo (`?demo=states`) — the renderer half of ACP-787.
//
// Where the step-replay surface (DemoWorkspace + overlay) gets its picture by
// replaying locator acts onto a live editor, this component is a PURE function
// of the selected snapshot in `states.ts`: given a state, it paints exactly
// what that state's fields say, and prev/next/direct-select are all just
// "read state n". No operation chain runs, so switching back and forth never
// accumulates anything and the same state always renders the same frame
// (methodology §6 idempotence, achieved structurally rather than by replay).
//
// The data layer is the SAME snapshot-backed fake the replay runtime uses
// (`createDemoApi`), minted fresh per state so any live mutation a presenter
// makes is discarded on the next switch — and the `?demo=` guard in
// studioApi.request keeps the promise honest: this mode issues ZERO fetches.
// `ProjectCommitBar` runs its real logic against that fake, so the commit
// button's enabled state for the dirty frames is produced by real code on real
// (in-memory) data, not a hardcoded prop.
//
// The dock mirrors the existing stepper's shape (badge / counter / prev / next)
// and adds the ticket's direct-select buttons; every control sets the state
// index directly. All per-state prose is snapshot DATA, so no user-facing
// string is hardcoded here — only fixed chrome rides the existing i18n keys.
import { useCallback, useMemo, useState } from 'react'
import { ChevronLeft, ChevronRight, FileText, GitCompareArrows } from 'lucide-react'
import Clickable from '../../../components/Clickable'
import { i18nT } from '../../../i18n/t'
import ProjectCommitBar from '../ProjectCommitBar'
import { LineDiff } from '../DiffView'
import { createDemoApi } from './runtime'
import { DEMO_STATES } from './states'

interface StateDemoProps {
  /** the `?demo=` params (parseDemoScenario shape); only `scenario` is read —
   * the harness knobs belong to the replay runtime and are ignored here */
  params: { scenario: string; autoMs: number; settleMs: number }
}

export default function StateDemo({ params }: StateDemoProps) {
  const [index, setIndex] = useState(0)
  const state = DEMO_STATES[index]

  // one fake per state: a fresh in-memory world seeded from this state's
  // snapshot, so live writes never leak across a switch (the same "一帧=一次
  // 整体加载" discipline the replay runtime holds).
  const api = useMemo(() => createDemoApi(state.fixture), [state])

  const select = useCallback((i: number) => setIndex(i), [])
  const prev = useCallback(() => setIndex((i) => Math.max(0, i - 1)), [])
  const next = useCallback(() => setIndex((i) => Math.min(DEMO_STATES.length - 1, i + 1)), [])

  const focusLabel = state.selectedDoc ?? ''

  return (
    <div className="flex flex-col h-full min-h-0" data-testid="ai-studio" data-demo-states={params.scenario}>
      <header className="flex items-center gap-3 px-4 h-[44px] shrink-0 border-b border-border bg-card">
        <span className="text-sm font-semibold text-text-strong">AI Studio</span>
        <span className="text-[13px] text-muted truncate max-w-[280px]">
          {i18nT('apps.aiStudio.project_label')} · {state.fixture.project.name}
        </span>
        <span className="flex-1" />
        {/* the shared project-level commit control, running real logic on the
          * injected snapshot fake — its enabled state is data, not a prop.
          * Keyed on the state id: its drafts read is a React Query cached under
          * `[..., 'drafts', projectId]`, and projectId is constant across
          * states, so without a remount a switch would show the PREVIOUS
          * frame's cached draft list (the same stale-store hazard the replay
          * runtime avoids by rebuilding the fake per step). Remounting per
          * frame re-reads the fresh fake — and is also what makes "来回切不脏"
          * structural: no component state survives a switch. */}
        <div className="relative flex items-center gap-2">
          <ProjectCommitBar key={state.id} projectId={state.fixture.project.id} api={api} />
        </div>
      </header>

      <div className="flex flex-1 min-h-0">
        {/* LEFT: the doc list, shown on every state (data-driven rows) */}
        <aside className="shrink-0 w-[260px] min-w-[180px] flex flex-col min-h-0 border-r border-border bg-card" data-testid="state-doc-list">
          <div className="px-3 h-[38px] shrink-0 flex items-center border-b border-border text-[13px] font-semibold text-text-strong">
            {i18nT('apps.aiStudio.doc_list')}
          </div>
          <ul className="flex-1 min-h-0 overflow-auto p-3">
            {state.docs.map((d) => {
              const active = d.name === state.selectedDoc
              return (
                <li
                  key={d.docId}
                  data-testid={`state-doc-row-${d.docId}`}
                  data-doc-active={active ? 'true' : 'false'}
                  className={`w-full text-left rounded-lg border px-3 py-2.5 mb-2 flex items-center justify-between gap-2 ${
                    active ? 'border-accent bg-accent-subtle' : 'border-border bg-card'
                  }`}
                >
                  <span className="text-[12px] font-semibold text-text truncate">{d.name}</span>
                  <span className="shrink-0 rounded-full bg-bg-hover px-1.5 py-0.5 text-[10px] text-muted">{d.version}</span>
                </li>
              )
            })}
          </ul>
        </aside>

        {/* CENTER: tab strip + the frame's content, straight off the snapshot */}
        <main className="flex-1 min-w-0 flex flex-col min-h-0 bg-bg">
          <div className="flex shrink-0 border-b border-border" role="tablist" aria-label={i18nT('apps.aiStudio.workspace_tabs')}>
            <StateTab
              active={state.activeSurface === 'doc'}
              onClick={() => select(1)}
              testid="state-tab-doc"
            >
              <FileText size={13} className="lucide-inline" /> {focusLabel || i18nT('apps.aiStudio.doc_list')}
            </StateTab>
            <StateTab
              active={state.activeSurface === 'diff'}
              onClick={() => select(2)}
              testid="state-tab-diff"
            >
              <GitCompareArrows size={13} className="lucide-inline" /> {i18nT('apps.aiStudio.diff_title')}
              {/* 红点角标: the badge the snapshot carries, shown on the Diff tab */}
              {state.diffBadge && (
                <span
                  data-testid="diff-tab-badge"
                  aria-hidden
                  className="ml-1 inline-block w-2 h-2 rounded-full bg-danger"
                />
              )}
            </StateTab>
          </div>

          <div className="flex-1 min-h-0 overflow-auto">
            {state.activeSurface === 'list' && (
              // S1: nothing open — the welcome/empty centre, caption is the frame's own data
              <div className="h-full flex flex-col items-center justify-center gap-2 p-8 text-center" data-testid="state-empty">
                <FileText size={28} className="text-muted" />
                <p className="text-[13px] text-muted max-w-[320px]">{state.caption}</p>
              </div>
            )}

            {state.activeSurface === 'doc' && (
              // S2: the open doc shows the WORKSPACE buffer (which differs from
              // the committed baseline) and the dirty affordance — both read
              // off the snapshot, not from a live typing session.
              <div
                className="flex flex-col h-full min-h-0"
                data-testid={`state-editor-${state.committedVersion}`}
                data-doc-dirty={state.dirty ? 'true' : 'false'}
                data-doc-name={focusLabel}
              >
                <div className="flex items-center gap-2 px-4 h-[34px] shrink-0 border-b border-border text-[12px]">
                  <span className="text-muted">{i18nT('apps.aiStudio.project_label')}: {state.committedVersion}</span>
                  {state.dirty && (
                    <span
                      data-testid="state-dirty-marker"
                      className="rounded-full bg-accent-subtle px-2 py-0.5 text-[11px] text-accent"
                    >
                      {i18nT('apps.aiStudio.draft_dirty')}{state.workingVersionLabel ? ` → ${state.workingVersionLabel}` : ''}
                    </span>
                  )}
                </div>
                <div className="flex-1 min-h-0 overflow-auto p-5 text-[13px] leading-6 whitespace-pre-wrap break-words text-text font-mono">
                  {state.buffer}
                </div>
              </div>
            )}

            {state.activeSurface === 'diff' && (
              // S3: the row-level V(n) → workspace diff. LineDiff is the real
              // business renderer (green added lines), fed from the snapshot.
              <div className="p-5 max-w-[820px]" data-testid="state-diff">
                <h1 className="text-[15px] font-semibold text-text-strong mb-3">
                  {focusLabel} · {i18nT('apps.aiStudio.diff_title')} · {state.committedVersion} → {state.workingVersionLabel}
                </h1>
                <LineDiff oldText={state.baseline} newText={state.buffer} />
              </div>
            )}
          </div>
        </main>
      </div>

      {/* DOCK: bottom-right, mirrors the replay stepper's shape + adds the
        * ticket's direct-select. Any control SETS the index — never replays. */}
      <div
        data-testid="demo-states-dock"
        data-demo-state={state.id}
        // which happy-path stage this frame is in (design → release → dev →
        // deploy); additive attribute so the shipped DOM the tests read is
        // unchanged, and future-phase states/tests can anchor on it
        data-demo-phase={state.phase}
        className="fixed bottom-4 right-4 z-[10001] w-[340px] rounded-xl border border-border bg-card p-3 shadow-2xl"
      >
        <div className="flex items-center gap-2">
          <span className="rounded-full bg-accent-subtle px-2 py-0.5 text-[10px] text-accent">
            {i18nT('apps.aiStudio.demo_badge')}
          </span>
          <span className="text-[12px] font-semibold text-text-strong truncate">{state.title}</span>
          <span className="ml-auto shrink-0 text-[11px] text-muted">
            {i18nT('apps.aiStudio.demo_counter', { n: index + 1, total: DEMO_STATES.length })}
          </span>
        </div>
        <div className="mt-1 text-[11px] leading-5 text-muted">{i18nT('apps.aiStudio.demo_event', { event: state.caption })}</div>

        {/* direct-select: jump straight to any state, forward or back */}
        <div className="mt-2 flex items-center gap-1.5" role="group" aria-label={state.title}>
          {DEMO_STATES.map((s, i) => (
            <Clickable
              key={s.id}
              data-testid={`demo-states-select-${s.id}`}
              data-selected={i === index ? 'true' : 'false'}
              onClick={() => select(i)}
              className={`flex-1 rounded-md border px-2 py-1 text-[11px] text-center ${
                i === index
                  ? 'border-accent bg-accent-subtle text-accent'
                  : 'border-border text-text hover:bg-bg-hover cursor-pointer'
              }`}
            >
              {s.label}
            </Clickable>
          ))}
        </div>

        <div className="mt-2 flex items-center gap-1.5">
          <Clickable
            data-testid="demo-states-prev"
            onClick={prev}
            disabled={index === 0}
            className={`rounded-md border border-border px-2.5 py-1 text-[12px] ${index === 0 ? 'text-muted opacity-50' : 'text-text hover:bg-bg-hover cursor-pointer'}`}
          >
            <span className="flex items-center gap-0.5"><ChevronLeft size={13} />{i18nT('apps.aiStudio.demo_prev')}</span>
          </Clickable>
          <Clickable
            data-testid="demo-states-next"
            onClick={next}
            disabled={index === DEMO_STATES.length - 1}
            className={`rounded-md border border-border px-2.5 py-1 text-[12px] ${index === DEMO_STATES.length - 1 ? 'text-muted opacity-50' : 'text-text hover:bg-bg-hover cursor-pointer'}`}
          >
            <span className="flex items-center gap-0.5">{i18nT('apps.aiStudio.demo_next')}<ChevronRight size={13} /></span>
          </Clickable>
        </div>
      </div>
    </div>
  )
}

function StateTab({ active, onClick, testid, children }: {
  active: boolean
  onClick: () => void
  testid: string
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      data-testid={testid}
      onClick={onClick}
      className={`flex items-center gap-1 px-3 py-2.5 text-[12px] whitespace-nowrap cursor-pointer border-b-2 transition-colors ${
        active ? 'text-accent border-accent font-semibold' : 'text-muted border-transparent hover:text-text'
      }`}
    >
      {children}
    </button>
  )
}
