// The development run view (ACP-735): the acceptance doc's steps 12-15 —
// 开发记录 (which frozen design this builds), 开发过程 (the four-phase walk
// with one factual summary per finished phase), 开发结果 (artifacts + the
// runnable entry) — plus the built-in experience screen the runnable version
// opens. Demo-agnostic by design (§4): pure props in, no scenario knowledge.
//
// The phase statuses are the SNAPSHOT's, not a timer's: this component
// renders whatever frame it is given, so autoplay walking the frames and a
// manual step-by-step produce identical pictures (回放一致). The 体验 entry
// only renders when the run carries a runnableVersion, and opening it is an
// internal switch to the preview screen — no server, no container, nothing
// leaves the page.
import { Hammer, PlayCircle } from 'lucide-react'
import { Btn } from '../../components/ui'
import { i18nT } from '../../i18n/t'
import type { StudioDevRun, StudioRunPreview } from './studioApi'

const PHASE_KEYS = ['tasks', 'implement', 'test', 'build'] as const

export default function DevRunPanel({ run, onOpenRun }: {
  run: StudioDevRun
  /** presses 打开可运行版本 (only offered when the run HAS one); the demo
   * workbench switches its frame, the business components never see this */
  onOpenRun?: () => void
}) {
  return (
    <div data-testid="dev-run-panel" data-dev-run-id={run.id} className="p-3 flex flex-col gap-2">
      <div className="flex items-center gap-2 text-[12px] font-semibold text-text-strong">
        <Hammer size={13} className="text-accent shrink-0" />
        {i18nT('apps.aiStudio.dev_title')}
        <span data-testid="dev-design-version" className="ml-auto rounded-full bg-accent-subtle px-2 py-0.5 text-[11px] font-semibold text-accent">
          {run.designVersion}
        </span>
      </div>
      {/* dev-phases for the same container/row-prefix reason as dev-artifacts */}
      <ol className="flex flex-col gap-1" data-testid="dev-phases">
        {run.phases.map((p) => (
          <li
            key={p.name}
            data-testid={`dev-phase-${p.name}`}
            data-dev-phase-status={p.status}
            className="rounded-md border border-border bg-bg px-2 py-1.5"
          >
            <div className="flex items-center gap-2 text-[12px] text-text">
              {PHASE_KEYS.includes(p.name as (typeof PHASE_KEYS)[number])
                ? i18nT(`apps.aiStudio.dev_phase_${p.name}`)
                : p.name}
              <span className="ml-auto text-[11px] text-muted" data-dev-phase-status-label>
                {i18nT(`apps.aiStudio.dev_status_${p.status}`)}
              </span>
            </div>
            {p.summary && (
              <div className="mt-0.5 text-[11px] text-muted" data-dev-phase-summary={p.name}>
                {p.summary}
              </div>
            )}
          </li>
        ))}
      </ol>
      {/* testid dev-artifacts (not dev-artifact-list): the artifact rows
       * carry dev-artifact-<kind>, and a prefix query must not also match
       * the container — same discipline as codegen-file-tree vs options */}
      {run.artifacts.length > 0 && (
        <div className="flex flex-col gap-1" data-testid="dev-artifacts">
          {run.artifacts.map((a) => (
            <div key={a.path} data-testid={`dev-artifact-${a.kind}`} className="flex items-center gap-2 text-[11px] text-muted px-2">
              <span className="font-semibold text-text">{i18nT(`apps.aiStudio.dev_artifact_${a.kind}`)}</span>
              <span className="font-mono">{a.path}</span>
            </div>
          ))}
        </div>
      )}
      {run.runnableVersion && (
        <div className="flex items-center gap-2">
          <span data-testid="dev-runnable-version" className="rounded-full bg-accent-subtle px-2 py-0.5 text-[11px] font-semibold text-accent">
            {i18nT('apps.aiStudio.dev_runnable_ready', { version: run.runnableVersion })}
          </span>
          {onOpenRun && (
            <Btn onClick={onOpenRun} data-testid="run-open-btn" className="ml-auto">
              <PlayCircle size={13} className="lucide-inline" /> {i18nT('apps.aiStudio.run_open')}
            </Btn>
          )}
        </div>
      )}
    </div>
  )
}

/** The experience screen 「打开可运行版本」 opens: an internal takeover
 * rendering the snapshot's preview data — the feature list is exactly the
 * graph's requirement labels (machine-checked at generation), so the running
 * version shows only what the structured design promised. No server exists
 * anywhere in this path, by design and by ticket. */
export function RunPreviewScreen({ preview, onClose }: {
  preview: StudioRunPreview
  onClose?: () => void
}) {
  return (
    <div data-testid="run-preview" data-run-version={preview.version} className="absolute inset-0 z-40 bg-bg flex flex-col">
      <div className="flex items-center gap-2 px-4 h-[44px] shrink-0 border-b border-border bg-card">
        <PlayCircle size={14} className="text-accent" />
        <span className="text-sm font-semibold text-text-strong">{preview.title}</span>
        <span className="text-[11px] text-muted">{i18nT('apps.aiStudio.run_preview_note', { from: preview.devRunId })}</span>
        {onClose && (
          <Btn onClick={onClose} data-testid="run-preview-close" className="ml-auto">
            {i18nT('apps.aiStudio.run_preview_close')}
          </Btn>
        )}
      </div>
      <div className="flex-1 min-h-0 overflow-auto p-6">
        <div className="max-w-[560px] mx-auto rounded-xl border border-border bg-card p-5 flex flex-col gap-2">
          <h2 className="text-[15px] font-semibold text-text-strong">{preview.title}</h2>
          <ul data-testid="run-preview-lines">
            {preview.lines.map((l) => (
              <li key={l} data-run-line={l} className="text-[13px] text-text py-1 border-b border-border last:border-b-0">
                {l}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  )
}
