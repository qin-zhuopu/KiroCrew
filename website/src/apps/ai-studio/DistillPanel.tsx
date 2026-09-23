// The distillation panel (ACP-733): what the AI proposed to change in the
// requirement graph after a release froze the documents. Demo-agnostic by
// design (§4): pure props in, no scenario knowledge — the workbench feeds it
// a StudioDistillation from a snapshot, a future API can feed the same props.
//
// Three honest frames, chosen by the run's own status, never by a step:
//   running  → a processing note (the task exists, no results yet)
//   done     → the candidate list, grouped add/modify/remove, each candidate
//              naming the document paragraph it was distilled from (the
//              acceptance doc's step-8 traceability: no black-box changes)
// The list is the snapshot's own candidate array — the generator proved it
// equals the graph wave, so this panel and the graph highlight cannot lie
// to each other.
import { BrainCircuit } from 'lucide-react'
import { i18nT } from '../../i18n/t'
import type { StudioDistillation } from './studioApi'

const GROUP_KINDS = ['add', 'modify', 'remove'] as const

export default function DistillPanel({ distillation }: { distillation: StudioDistillation }) {
  return (
    <div data-testid="distill-panel" data-distill-status={distillation.status} className="p-3 flex flex-col gap-2">
      <div className="flex items-center gap-2 text-[12px] font-semibold text-text-strong">
        <BrainCircuit size={13} className="text-accent shrink-0" />
        {i18nT('apps.aiStudio.distill_title')}
        <span className="ml-auto text-[11px] font-normal text-muted" data-testid={`distill-status-${distillation.status}`}>
          {i18nT(distillation.status === 'running' ? 'apps.aiStudio.distill_running' : 'apps.aiStudio.distill_done')}
        </span>
      </div>
      {distillation.status === 'running' ? (
        <div className="text-[11px] text-muted">{i18nT('apps.aiStudio.distill_running_hint')}</div>
      ) : (
        GROUP_KINDS.map((kind) => {
          const rows = distillation.candidates.filter((c) => c.kind === kind)
          if (rows.length === 0) return null
          return (
            <div key={kind} className="flex flex-col gap-1">
              <div className="text-[11px] font-semibold text-muted">{i18nT(`apps.aiStudio.distill_group_${kind}`)}</div>
              {rows.map((c) => (
                <div
                  key={c.id}
                  data-testid={`distill-candidate-${c.id}`}
                  data-distill-kind={c.kind}
                  data-distill-target={c.target}
                  className="rounded-md border border-border bg-bg px-2 py-1.5"
                >
                  <div className="text-[12px] text-text">{c.summary}</div>
                  <div className="mt-0.5 text-[11px] text-muted">
                    {c.target}
                    <span className="mx-1">·</span>
                    {i18nT('apps.aiStudio.distill_evidence', { doc: c.evidenceDoc })}
                  </div>
                </div>
              ))}
            </div>
          )
        })
      )}
    </div>
  )
}
