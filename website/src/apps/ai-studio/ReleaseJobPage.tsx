// The release-job detail page (ACP-773, 08-publish-app §〇-2): a Jenkins-style
// read-only page at /release-jobs/<发布号>?project=<项目id>, opened in a new
// tab from the publish result row. One page shows the project's whole
// release-job history (running pinned to the top) and, for the selected job,
// its header facts (version / commit hash / status / time / app URL) plus its
// execution log — the log STREAM is the T7 DeployLog reused verbatim (one SSE
// code path: live growth while running, full replay once finished), never a
// second log component.
//
// Read-only is a contract (§〇-2 列表只读): a row is only clickable to view its
// detail; no retry, cancel or delete control may appear in the list.
//
// T6 linkage point: PublishVersionList's result strip (its
// `ai-studio-publish-id-<版本号>` link, T6's file, not touched here) opens this
// page with
//   href={`/release-jobs/${encodeURIComponent(deploymentId)}?project=${encodeURIComponent(projectId)}`}
//   target="_blank"
// — the job id IS the deploymentId the log endpoint takes, and the project id
// rides as the query because both store reads are per-project.
//
// The testids below are acceptance contracts (08 §六): page / history-list /
// row / status / log, all keyed by the 发布号; they survive any restyle.
import { useMemo, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import Clickable from '../../components/Clickable'
import ErrorNotice from '../../components/ErrorNotice'
import { ContentSkeleton } from '../../components/ui'
import { fmtDateTime } from '../../i18n/format'
import { i18nT } from '../../i18n/t'
import DeployLog from './DeployLog'
import { publishApi, type StudioPublishJob } from './studioApi'

const SHORT_HASH = 7

/** The three states the page renders (08 §〇-2: 已完成 / 已失败 / 发布中). */
function jobStatusLabel(status: string): string {
  if (status === 'success') return i18nT('apps.aiStudio.release_job_status_success')
  if (status === 'failed') return i18nT('apps.aiStudio.release_job_status_failed')
  return i18nT('apps.aiStudio.release_job_status_running')
}

function jobStatusCls(status: string): string {
  if (status === 'success') return 'bg-accent-subtle text-accent'
  if (status === 'failed') return 'bg-danger/10 text-danger'
  return 'bg-bg-hover text-muted'
}

export default function ReleaseJobPage() {
  // The 发布号 is a route param (the URL contract the result row links to);
  // the project id rides as a query param — every publish read is per-project
  // and job ids are only unique inside one project's store.
  const { jobId = '' } = useParams<{ jobId: string }>()
  const [searchParams] = useSearchParams()
  const projectId = searchParams.get('project') ?? ''

  // Which row's detail the page shows: opened on the URL's 发布号, switched by
  // clicking another row (the list's only interaction, §〇-2 只读).
  const [selected, setSelected] = useState(jobId)

  const jobsQuery = useQuery({
    queryKey: ['ai-studio', 'publish-jobs', projectId],
    queryFn: () => publishApi.listJobs(projectId),
    enabled: !!projectId,
    // 发布中轮询: while any job still runs, re-read so a finishing publish
    // settles its row on screen; a settled list never polls again.
    refetchInterval: (query) =>
      query.state.data?.jobs.some((j) => j.status === 'running') ? 2000 : false,
  })
  // The app URL is a release fact, not a job fact (§〇-2: 成功后的对外结果) —
  // the record a successful job wrote carries it, so the success branch reads
  // it from the records endpoint.
  const recordsQuery = useQuery({
    queryKey: ['ai-studio', 'publish-records', projectId],
    queryFn: () => publishApi.listRecords(projectId),
    enabled: !!projectId,
  })

  const jobs = jobsQuery.data?.jobs ?? []
  // Newest first as stored; running jobs pin to the top (§〇-2 进行中的置顶).
  // Array#sort is stable, so the backend's ts order holds within each group.
  const sorted = useMemo(
    () =>
      [...jobs].sort(
        (a, b) => Number(b.status === 'running') - Number(a.status === 'running'),
      ),
    [jobs],
  )
  const selectedJob = jobs.find((j) => j.id === selected) ?? null
  const successUrl =
    selectedJob?.status === 'success'
      ? (recordsQuery.data?.records ?? []).find(
          (r) => r.status === 'success' && r.deploymentId === selectedJob.id,
        )?.url ?? ''
      : ''

  if (!projectId) {
    return (
      <div className="h-full p-6 flex flex-col gap-3 max-w-[560px]" data-testid="ai-studio-release-job-page">
        <ErrorNotice title={i18nT('apps.aiStudio.release_job_error')} message={i18nT('apps.aiStudio.release_job_missing_project')} askAgent={false} />
      </div>
    )
  }

  return (
    <div className="h-full overflow-auto p-5" data-testid="ai-studio-release-job-page">
      <h1 className="text-[15px] font-semibold text-text-strong">
        {i18nT('apps.aiStudio.release_job_title')} · {selected}
      </h1>

      {/* 头部信息（任务书）: the selected job's facts; a deep link to an id
          the store no longer has renders the id alone — the log below then
          answers through DeployLog's own error path, honestly. */}
      {selectedJob && (
        <div className="mt-3 rounded-lg border border-border bg-card px-4 py-3 max-w-[820px]" data-testid="ai-studio-release-job-header">
          <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 text-[12px]">
            <span className="text-muted">
              {i18nT('apps.aiStudio.release_job_field_version')}:{' '}
              <span className="text-text font-semibold">{selectedJob.version}</span>
            </span>
            <span className="text-muted">
              {i18nT('apps.aiStudio.release_job_field_form')}:{' '}
              <span className="text-text">{formLabel(selectedJob.form)}</span>
            </span>
            {selectedJob.commitHash && (
              <span className="text-muted font-mono">
                {i18nT('apps.aiStudio.release_job_field_commit')}:{' '}
                {selectedJob.commitHash.slice(0, SHORT_HASH)}
              </span>
            )}
            <span className="text-muted">
              {i18nT('apps.aiStudio.release_job_field_time')}:{' '}
              <span className="text-text">{fmtDateTime(selectedJob.ts * 1000)}</span>
            </span>
            <span className={`rounded-full px-1.5 py-0.5 text-[11px] ${jobStatusCls(selectedJob.status)}`}>
              {jobStatusLabel(selectedJob.status)}
            </span>
          </div>
          {/* 终态展示: success offers the app URL (§四 探活 opens this); a
              failure is marked — its reason lives in the log below. */}
          {selectedJob.status === 'success' && successUrl && (
            <a
              href={`https://${successUrl}`}
              target="_blank"
              rel="noreferrer"
              className="inline-block mt-2 text-[12px] text-accent hover:underline"
              data-testid="ai-studio-release-job-open-url"
            >
              {i18nT('apps.aiStudio.release_job_open_app')} {successUrl}
            </a>
          )}
          {selectedJob.status === 'failed' && (
            <div className="mt-2 text-[12px] text-danger" data-testid="ai-studio-release-job-failed-mark">
              {i18nT('apps.aiStudio.release_job_failed_hint')}
            </div>
          )}
        </div>
      )}

      {/* 发布历史列表 (job 列表): the project's whole release-job history,
          read-only — clicking a row only switches the detail above/below. */}
      <h2 className="mt-5 text-[11px] uppercase tracking-wide text-muted">
        {i18nT('apps.aiStudio.release_job_history_title')}
      </h2>
      {jobsQuery.isError ? (
        <ErrorNotice
          title={i18nT('apps.aiStudio.release_job_error')}
          message={String(jobsQuery.error?.message ?? jobsQuery.error)}
          askAgent={false}
        />
      ) : jobsQuery.isPending ? (
        <div className="max-w-[820px]"><ContentSkeleton rows={3} /></div>
      ) : sorted.length === 0 ? (
        <div className="text-[12px] text-muted" data-testid="ai-studio-release-job-empty">
          {i18nT('apps.aiStudio.release_job_empty')}
        </div>
      ) : (
        <div className="max-w-[820px]" data-testid="ai-studio-release-job-history-list">
          {sorted.map((j) => (
            <JobRow key={j.id} job={j} active={j.id === selected} onSelect={setSelected} />
          ))}
        </div>
      )}

      {/* 流式日志: T7's DeployLog reused verbatim (its own deploy-log-<id>
          testid stays; this wrapper carries the §〇-2 contract testid). The
          stream recovery story — close on done, ErrorNotice on a dead stream,
          waiting state before the first frame — is DeployLog's, not re-spelled
          here. */}
      <div className="mt-4 -mb-5" data-testid={`ai-studio-release-job-log-${selected}`}>
        <DeployLog deployId={selected} projectId={projectId} />
      </div>
    </div>
  )
}

/** One history row: the job's facts plus its three-state status; the ONLY
 * interactive affordance is selecting it (§〇-2 列表只读 — no retry, cancel
 * or delete may ever appear here). */
function JobRow({ job, active, onSelect }: {
  job: StudioPublishJob
  active: boolean
  onSelect: (id: string) => void
}) {
  return (
    <Clickable
      onClick={() => onSelect(job.id)}
      aria-label={i18nT('apps.aiStudio.release_job_view_detail')}
      data-testid={`ai-studio-release-job-row-${job.id}`}
      className={`w-full flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border px-3 py-2 mb-2 text-left text-[12px] ${
        active ? 'border-accent bg-accent-subtle' : 'border-border bg-card'
      }`}
    >
      <span className="font-mono text-[11px] text-muted truncate max-w-[240px]" title={job.id}>
        {job.id}
      </span>
      <span className="text-text font-semibold">{job.version}</span>
      <span className="text-muted">{formLabel(job.form)}</span>
      <span className="text-muted">{fmtDateTime(job.ts * 1000)}</span>
      <span
        data-testid={`ai-studio-release-job-status-${job.id}`}
        className={`ml-auto shrink-0 rounded-full px-1.5 py-0.5 text-[11px] ${jobStatusCls(job.status)}`}
      >
        {jobStatusLabel(job.status)}
      </span>
    </Clickable>
  )
}

/** The form badge text: the store's two form tokens, plus the raw value for
 * anything else (a form the store may learn later reads as itself). */
function formLabel(form: string): string {
  if (form === 'full') return i18nT('apps.aiStudio.release_job_form_full')
  if (form === 'demo') return i18nT('apps.aiStudio.release_job_form_demo')
  return form
}
