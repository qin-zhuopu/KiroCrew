// The 部署 frames' panel (ACP-794, wiring the P1/P2 snapshots from
// `states-devdeploy.ts`).
//
// The product's real deploy path (`DeployLog` + the release-job page) streams
// over SSE and therefore CANNOT run in a fetch-free demo — `DeployLog` opens an
// `EventSource` on mount, which is a live request by construction. So this
// frame renders the same facts from the snapshot instead, and keeps every
// acceptance hook the real components own, so a demo assertion and a product
// assertion read the same DOM:
//   - `deploy-log-<deploymentId>` with `role="log"` / `aria-live="polite"` —
//     DeployLog's own contract (08 §六).
//   - `ai-studio-release-job-row-<id>` / `-status-<id>` / `-header` /
//     `-open-url` — the release-job page's contract (ACP-772).
//   - the same status words the real page renders (`release_job_status_*`), so
//     进行中 / 完成 read as the product words, not demo words.
// The log lines themselves are the real executor's wording and order, carried
// by the frame (P2's lines extend P1's as a prefix — that is how 「持续增长」
// reads without a stream).
import { ExternalLink } from 'lucide-react'
import { i18nT } from '../../../i18n/t'
import { fmtDateTimeNumeric } from '../../../i18n/format'
import type { DeployFramePayload } from './allStates'

function statusLabel(status: string): string {
  if (status === 'success') return i18nT('apps.aiStudio.release_job_status_success')
  if (status === 'failed') return i18nT('apps.aiStudio.release_job_status_failed')
  return i18nT('apps.aiStudio.release_job_status_running')
}

export default function DeployFramePanel({ frame }: { frame: DeployFramePayload }) {
  const succeeded = frame.status === 'success'
  return (
    <div className="p-5 max-w-[820px]" data-testid={`deploy-frame-${frame.deploymentId}`}>
      {/* the release-job header the real page renders for a selected job */}
      <div
        className="rounded-lg border border-border bg-card px-4 py-3"
        data-testid="ai-studio-release-job-header"
      >
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-semibold text-text-strong">{frame.deploymentId}</span>
          <span
            data-testid={`ai-studio-release-job-status-${frame.deploymentId}`}
            className={`shrink-0 rounded-full px-1.5 py-0.5 text-[11px] ${
              succeeded ? 'bg-accent-subtle text-accent' : 'bg-bg-hover text-muted'
            }`}
          >
            {statusLabel(frame.status)}
          </span>
        </div>
        <dl className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-muted">
          <span>{i18nT('apps.aiStudio.release_job_field_version')}: {frame.version}</span>
          <span>{i18nT('apps.aiStudio.release_job_field_commit')}: {frame.commitHash}</span>
          <span>{i18nT('apps.aiStudio.release_job_field_form')}: {frame.env}</span>
          <span>{i18nT('apps.aiStudio.release_job_field_time')}: {fmtDateTimeNumeric(frame.startedAt * 1000)}</span>
        </dl>
        {/* 单实例替换: the instance this deployment replaced — the frame's own
          * fact, so the claim is data rather than prose */}
        {frame.replaced && (
          <div className="mt-2 text-[12px] text-muted" data-testid="deploy-replaced">
            {frame.replaced.version} · {frame.replaced.deploymentId}
          </div>
        )}
        {succeeded && frame.url && (
          <a
            data-testid="ai-studio-release-job-open-url"
            href={`https://${frame.url}`}
            target="_blank"
            rel="noreferrer"
            className="mt-3 inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-[12px] text-accent hover:bg-bg-hover"
          >
            <ExternalLink size={13} className="lucide-inline" />
            {i18nT('apps.aiStudio.release_job_open_app')}
          </a>
        )}
      </div>

      {/* the online feature list (P2): what the opened URL serves — verbatim the
        * running version's features, i.e. 线上可访问 sees 本次新增规则 */}
      {frame.onlineFeatureLines && frame.onlineFeatureLines.length > 0 && (
        <ul className="mt-3 rounded-lg border border-border bg-card px-4 py-3 text-[12px] text-text" data-testid="deploy-online-features">
          {frame.onlineFeatureLines.map((line) => <li key={line}>· {line}</li>)}
        </ul>
      )}

      {/* the log container: DeployLog's own testid + a11y contract */}
      <div className="mt-3" data-testid={`deploy-log-${frame.deploymentId}`}>
        <h2 className="text-[12px] font-semibold text-text-strong">{i18nT('apps.aiStudio.deploy_log')}</h2>
        <pre
          role="log"
          aria-live="polite"
          className="mt-2 rounded-lg bg-bg-elevated border border-border font-mono text-[12px] leading-6 p-4 whitespace-pre-wrap overflow-auto max-h-[240px] text-muted"
        >
          {frame.logLines.join('\n')}
        </pre>
      </div>
    </div>
  )
}