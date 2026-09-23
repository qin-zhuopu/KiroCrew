// The state-direct demo's control dock (ACP-794, moved out of the deleted
// `StateDemo` shell).
//
// Every control SETS a frame index — nothing replays, so entering the same
// frame twice is the same picture (methodology §6 idempotence, structural).
// The frames are grouped by the big phase of the product's happy path
// (设计 → 发版 → 开发 → 部署, `allStates.ts`), because eleven buttons in one
// undifferentiated row stopped reading as a story; a group renders only when
// its phase actually has merged frames.
//
// The ✕ closes the demo: it drops the `demo` query param, which is the whole
// demo switch — the same route then renders the ordinary workbench again
// (owner 口径: 退出演示回到原页面).
//
// All chrome copy rides the existing i18n catalog; per-frame prose (title /
// caption / label) is snapshot DATA, so no user-facing string is authored here.
import { ChevronLeft, ChevronRight, X } from 'lucide-react'
import Clickable from '../../../components/Clickable'
import { i18nT } from '../../../i18n/t'
import { ALL_STATES, PHASE_LABEL_KEY, PHASE_ORDER, statesOfPhase } from './allStates'
import type { StateSnapshot } from './states'

export default function StatesDock({ index, onSelect, onPrev, onNext, onClose }: {
  index: number
  onSelect: (i: number) => void
  onPrev: () => void
  onNext: () => void
  onClose: () => void
}) {
  const state = ALL_STATES[index]
  if (!state) return null
  const atStart = index === 0
  const atEnd = index === ALL_STATES.length - 1

  return (
    <div
      data-testid="demo-states-dock"
      data-demo-state={state.id}
      // which happy-path stage this frame is in (design → release → dev →
      // deploy); additive attribute so the shipped DOM the tests read is
      // unchanged, and future-phase states/tests can anchor on it
      data-demo-phase={state.phase}
      className="fixed bottom-4 right-4 z-[10001] w-[392px] rounded-xl border border-border bg-card p-3 shadow-2xl"
    >
      <div className="flex items-center gap-2">
        <span className="rounded-full bg-accent-subtle px-2 py-0.5 text-[10px] text-accent">
          {i18nT('apps.aiStudio.demo_badge')}
        </span>
        <span className="text-[12px] font-semibold text-text-strong truncate" title={state.title}>
          {state.title}
        </span>
        <span className="ml-auto shrink-0 text-[11px] text-muted" data-testid="demo-states-counter">
          {i18nT('apps.aiStudio.demo_counter', { n: index + 1, total: ALL_STATES.length })}
        </span>
        <Clickable
          data-testid="demo-states-close"
          aria-label={i18nT('apps.aiStudio.demo_exit')}
          title={i18nT('apps.aiStudio.demo_exit')}
          onClick={onClose}
          className="shrink-0 rounded-md border border-border p-1 text-muted hover:bg-bg-hover hover:text-text cursor-pointer"
        >
          <X size={13} />
        </Clickable>
      </div>
      <div className="mt-1 text-[11px] leading-5 text-muted">{i18nT('apps.aiStudio.demo_event', { event: state.caption })}</div>

      {/* one row per big phase: the phase name, then its frames as direct-select
        * buttons. A frame's own label is long ("S2 · 未提交修改"), so the button
        * carries the id and the label rides the tooltip — the dock stays one
        * glance wide however many frames a phase grows to. */}
      {PHASE_ORDER.map((phase) => {
        const frames = statesOfPhase(phase)
        if (frames.length === 0) return null
        return (
          <div key={phase} className="mt-2 flex items-center gap-1.5" data-testid={`demo-states-group-${phase}`}>
            <span className="w-[28px] shrink-0 text-[10px] text-muted">{i18nT(PHASE_LABEL_KEY[phase])}</span>
            {frames.map((s: StateSnapshot) => {
              const i = ALL_STATES.indexOf(s)
              return (
                <Clickable
                  key={s.id}
                  data-testid={`demo-states-select-${s.id}`}
                  data-selected={i === index ? 'true' : 'false'}
                  title={s.label}
                  onClick={() => onSelect(i)}
                  className={`flex-1 rounded-md border px-1.5 py-1 text-[11px] text-center ${
                    i === index
                      ? 'border-accent bg-accent-subtle text-accent'
                      : 'border-border text-text hover:bg-bg-hover cursor-pointer'
                  }`}
                >
                  {s.id}
                </Clickable>
              )
            })}
          </div>
        )
      })}

      <div className="mt-2 flex items-center gap-1.5">
        <Clickable
          data-testid="demo-states-prev"
          onClick={onPrev}
          disabled={atStart}
          className={`rounded-md border border-border px-2.5 py-1 text-[12px] ${atStart ? 'text-muted opacity-50' : 'text-text hover:bg-bg-hover cursor-pointer'}`}
        >
          <span className="flex items-center gap-0.5"><ChevronLeft size={13} />{i18nT('apps.aiStudio.demo_prev')}</span>
        </Clickable>
        <Clickable
          data-testid="demo-states-next"
          onClick={onNext}
          disabled={atEnd}
          className={`rounded-md border border-border px-2.5 py-1 text-[12px] ${atEnd ? 'text-muted opacity-50' : 'text-text hover:bg-bg-hover cursor-pointer'}`}
        >
          <span className="flex items-center gap-0.5">{i18nT('apps.aiStudio.demo_next')}<ChevronRight size={13} /></span>
        </Clickable>
      </div>
    </div>
  )
}