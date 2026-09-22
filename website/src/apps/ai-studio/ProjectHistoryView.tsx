// The project-wide history timeline (ACP-736, acceptance-doc step 16): the
// round's five kinds of fact — 修改/提交/发版/沉淀/开发 plus the run they
// produced — as one linked chain. Demo-agnostic by design (§4): pure props
// in, no scenario knowledge, no demo branch.
//
// The chain is the snapshot's own data: every node renders its event's kind,
// summary and the earlier events it links back to, so 追溯 walks real
// references, never a re-derivation. `onJump` is only offered by the demo
// workbench and only means 加载该事件命名的快照 — the timeline cannot make
// a frame up. The 继续设计 button is the loop's other half (step 17): the
// round's final design becomes the next round's baseline, so the button is
// rendered by whoever declares it (same live-act discipline as every other
// transition button).
import { BrainCircuit, GitCommitHorizontal, Hammer, Pencil, PlayCircle, Rocket } from 'lucide-react'
import { Btn } from '../../components/ui'
import { i18nT } from '../../i18n/t'
import type { StudioHistoryKind, StudioProjectHistory } from './studioApi'

// one icon per kind — the five kinds must stay visually DIFFERENT (验收标准:
// 五类不同且可追溯的事实); a closed table, so a new kind fails loudly here
const KIND_ICON: Record<StudioHistoryKind, typeof Pencil> = {
  edit: Pencil,
  commit: GitCommitHorizontal,
  release: Rocket,
  distill: BrainCircuit,
  dev: Hammer,
  run: PlayCircle,
}

export default function ProjectHistoryView({ history, onJump, onContinue }: {
  history: StudioProjectHistory
  /** presses an event's 回到当时画面 — the demo loads the event's `ref`
   * snapshot; absent (the real product path has no snapshots to jump to) the
   * rows stay read-only */
  onJump?: (ref: string) => void
  /** presses 继续设计 (only offered on the step that declares the next
   * round's landing frame) */
  onContinue?: () => void
}) {
  const events = [...history.events].sort((a, b) => a.at - b.at)
  const summaryOf = (id: string) => history.events.find((e) => e.id === id)?.summary ?? id
  return (
    <div data-testid="history-timeline" data-history-count={events.length} className="p-3 flex flex-col gap-2">
      <div className="flex items-center gap-2 text-[12px] font-semibold text-text-strong">
        <GitCommitHorizontal size={13} className="text-accent shrink-0" />
        {i18nT('apps.aiStudio.history_title')}
        <span className="ml-auto text-[11px] font-normal text-muted">
          {i18nT('apps.aiStudio.history_note', { count: events.length })}
        </span>
      </div>
      <ol className="flex flex-col gap-1">
        {events.map((e) => {
          const Icon = KIND_ICON[e.kind]
          return (
            <li
              key={e.id}
              data-testid={`history-event-${e.id}`}
              data-history-kind={e.kind}
              data-history-links={e.links.join(',')}
              className="rounded-md border border-border bg-bg px-2 py-1.5 flex flex-col gap-0.5"
            >
              <div className="flex items-center gap-2 text-[12px] text-text">
                <Icon size={13} className="text-accent shrink-0" />
                <span className="font-semibold">{i18nT(`apps.aiStudio.history_kind_${e.kind}`)}</span>
                <span className="text-[11px] text-muted font-mono">
                  {new Date(e.at * 1000).toLocaleString()}
                </span>
                {onJump && (
                  <Btn onClick={() => onJump(e.ref)} data-testid={`history-jump-${e.id}`} className="ml-auto">
                    {i18nT('apps.aiStudio.history_jump')}
                  </Btn>
                )}
              </div>
              <div className="text-[11px] text-muted" data-history-summary={e.id}>
                {e.summary}
              </div>
              {e.links.length > 0 && (
                <div className="text-[11px] text-muted flex flex-col gap-0.5 pl-4" data-history-linklist={e.id}>
                  {e.links.map((l) => (
                    <span key={l} data-history-link={l}>
                      ↳ {summaryOf(l)}
                    </span>
                  ))}
                </div>
              )}
            </li>
          )
        })}
      </ol>
      {onContinue && (
        <Btn onClick={onContinue} data-testid="continue-design-btn" primary className="self-end">
          <Pencil size={13} className="lucide-inline" /> {i18nT('apps.aiStudio.continue_design')}
        </Btn>
      )}
    </div>
  )
}
