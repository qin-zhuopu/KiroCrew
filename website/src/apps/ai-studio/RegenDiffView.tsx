// The regeneration review (ACP-734): the two screens the acceptance doc's
// steps 10-11 ask for, after a distillation has been applied to the graph.
// Demo-agnostic by design (§4): pure props in, no scenario knowledge — the
// workbench feeds it what a snapshot holds, a future API can feed the same.
//
//   RegenDocView  — the regenerated document itself: content plus the badge
//                   naming which distillation produced it. The "new version"
//                   claim is the content; the badge only states its source.
//   RegenDiffPair — the three-segment grouped diff: per business point, left
//                   what the USER changed, middle the structured candidate
//                   the distillation produced, right what the REGENERATION
//                   changed. One row per point, the point is the linkage —
//                   the same fact reads across all three segments. An empty
//                   side is shown as empty: a purely distilled point has no
//                   user lines, a graph-only removal has none on either side.
//
// Every diff line rendered here was sliced out of a version row's unified
// diff by the generator (check_regen re-slices and re-verifies) — this
// component adds no lines of its own.
import { FileOutput, Layers } from 'lucide-react'
import { i18nT } from '../../i18n/t'
import { UnifiedDiffText } from './DiffView'
import type { StudioDiffGroup, StudioRegeneration } from './studioApi'

const SEGMENTS = ['user', 'structured', 'regen'] as const

/** The regenerated document, badged with the distillation that produced it
 * (the acceptance doc's step-10 annotation: generatedFrom, on screen). */
export function RegenDocView({ regen }: { regen: StudioRegeneration }) {
  return (
    <div data-testid="regen-doc-view" className="p-3 flex flex-col gap-2">
      <div className="flex items-center gap-2 text-[12px] font-semibold text-text-strong">
        <FileOutput size={13} className="text-accent shrink-0" />
        {regen.docName}
        <span
          data-testid={`regen-badge-${regen.generatedFrom}`}
          className="rounded-full bg-accent-subtle px-2 py-0.5 text-[11px] font-semibold text-accent"
        >
          {i18nT('apps.aiStudio.regen_badge', { version: regen.version, from: regen.generatedFrom })}
        </span>
      </div>
      <pre className="text-[12px] font-mono leading-5 whitespace-pre-wrap break-words text-text rounded-md border border-border bg-bg p-2.5">
        {regen.content}
      </pre>
    </div>
  )
}

/** The grouped three-segment review (step 11): rows keyed by business point,
 * columns keyed by segment. `data-group-primary` marks the row where all
 * three segments carry content — the row the guidance rings when it walks
 * the segments one by one (every segment of one point, the linkage shot). */
export function RegenDiffPair({ groups }: { groups: StudioDiffGroup[] }) {
  return (
    <div data-testid="regen-diff-pair" data-diff-group-count={String(groups.length)} className="p-3 flex flex-col gap-3">
      <div className="flex items-center gap-2 text-[12px] font-semibold text-text-strong">
        <Layers size={13} className="text-accent shrink-0" />
        {i18nT('apps.aiStudio.diff_group_title')}
      </div>
      {groups.map((g) => {
        const primary = g.userDiff !== '' && g.regenDiff !== ''
        return (
          <div
            key={g.point}
            data-testid={`diff-group-row-${g.candidateId}`}
            data-group-point={g.point}
            data-group-primary={primary ? 'true' : 'false'}
            className="rounded-lg border border-border overflow-hidden"
          >
            <div className="px-2.5 py-1.5 text-[12px] font-semibold text-text-strong bg-card border-b border-border">
              {g.point}
            </div>
            <div className="grid grid-cols-3">
              {SEGMENTS.map((seg) => (
                <div
                  key={seg}
                  data-group-segment={seg}
                  data-group-candidate={g.candidateId}
                  className="min-w-0 border-r border-border last:border-r-0"
                >
                  <div className="px-2.5 py-1 text-[11px] font-semibold text-muted border-b border-border bg-card">
                    {i18nT(`apps.aiStudio.diff_group_${seg}`)}
                  </div>
                  <div className="px-2.5 py-1.5 min-h-[44px]">
                    {seg === 'structured' ? (
                      g.structuredChanges.map((c) => (
                        <div key={c.id} data-testid={`diff-group-change-${c.id}`} data-distill-kind={c.kind}>
                          <div className="text-[12px] text-text">{c.summary}</div>
                          <div className="mt-0.5 text-[11px] text-muted">
                            {c.target}
                            <span className="mx-1">·</span>
                            {i18nT('apps.aiStudio.distill_evidence', { doc: c.evidenceDoc })}
                          </div>
                        </div>
                      ))
                    ) : seg === 'user' ? (
                      g.userDiff === '' ? (
                        <div className="text-[11px] text-muted italic" data-diff-group-empty="true">
                          {i18nT('apps.aiStudio.diff_group_empty')}
                        </div>
                      ) : (
                        <UnifiedDiffText patch={g.userDiff} />
                      )
                    ) : g.regenDiff === '' ? (
                      <div className="text-[11px] text-muted italic" data-diff-group-empty="true">
                        {i18nT('apps.aiStudio.diff_group_empty')}
                      </div>
                    ) : (
                      <UnifiedDiffText patch={g.regenDiff} />
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}
