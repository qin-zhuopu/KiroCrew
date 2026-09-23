// The publish view (08-publish-app §〇-1): the versions of the project as
// rows in the right sidebar's Releases tab, one row per version, each row
// carrying its lifecycle state, its form verdict reason, and — when its hash
// differs from the latest published hash — an inline publish button built
// HERE (never the top bar's ReleaseControl, whose release-btn testid is a
// different control). No version picker, no free-text input, no confirm
// dialog: the user sees the list and fires a row.
//
// ACP-798 adds a SECOND list to the same tab, ABOVE the version rows: 本版
// 修改过的文件 — one list row per file, its 新增/修改/删除 and its 图谱拆解
// 状态 (已 / 正在 / 尚未拆解成图谱). The order is owner's sidebar layout rule:
// a tab with both a process and a history shows the process on top and the
// history below, the way ReleasesTool/DeployTool already read (当前进度 →
// 历史). It takes no read of its own: the rows are the `releaseFiles` prop,
// and an ordinary workbench passes none, so the tab renders exactly what it
// rendered before.
//
// Data: versions from the publish versions read; the per-version published
// states and the "latest published hash" (the newest success record's hash)
// from GET /publish/records (B4); the form reason from GET /publish/preview
// (B1, whose source is the version's git tag annotation).
//
// The run (T6): a click fires POST /publish and the row honestly reads
// 「发布中」; while any row is in flight the records query polls, and the run
// settles when its success record lands (terminal 「发布成功」 + the result
// strip) or the trigger answers a failed status (terminal 「发布失败」 + the
// reason, which only the trigger response carries — a failed job never
// writes a release record). A same-hash re-fire while publishing answers 409:
// the row simply keeps its single 「发布中」 — one run slot per version is
// what keeps it single — and no error notice fires.
import { useEffect, useMemo, useState } from 'react'
import { useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { i18nT } from '../../i18n/t'
import ErrorNotice from '../../components/ErrorNotice'
import { Btn } from '../../components/ui'
import ReleaseControl from './ReleaseControl'
import {
  publishApi,
  StudioApiError,
  type StudioPublishApi,
  type StudioPublishRecord,
  type StudioPublishVersion,
  type StudioReleaseFile,
  type StudioReleaseFiles,
} from './studioApi'

const SHORT_HASH = 7

/** How often the records query re-reads while a publish is in flight. The
 * settle is the success record landing (B4), so the poll is the terminal
 * state's source — the POST response alone never carries form or url. */
const POLL_MS = 2000

/** What one row knows about the publish fired for it this visit.
 * - running: fired (or a 409 said one is already in flight). The row reads
 *   「发布中」 and the records poll waits for the success record.
 * - success: the record carrying this run's deploymentId landed.
 * - failed: the trigger answered ``status: "failed"`` with the reason. */
type RunState = {
  state: 'running' | 'success' | 'failed'
  deploymentId?: string
  reason?: string
}

export default function PublishVersionList({
  projectId,
  api = publishApi,
  releaseFiles,
  releaseAction,
}: {
  projectId: string
  /** the data source, injectable for the demo's snapshot fake; the ordinary
   * path uses the real client and never passes this */
  api?: StudioPublishApi
  /** 本版修改过的文件 (ACP-798), injectable for the demo's frames the same way
   * `api` is. Omitted — every ordinary workbench — renders exactly what this
   * tab rendered before: no such list, no extra read, no extra request. The
   * rows are a LIST, one per file, drawn from the value's own data. */
  releaseFiles?: StudioReleaseFiles
  /** The tab's OWN 发版 button (ACP-798, owner's rule: 动作按钮跟着页签走 —
   * the act belongs to the tab it acts on, so it sits at the TOP of the 发版
   * tab). Omitted — every ordinary workbench, where the real path has no
   * release endpoint yet — renders no button at all. When given, the button
   * IS ReleaseControl, the same component (and the same `release-btn`
   * contract) the demo's top bar uses, and it fires the very act a row's 发布
   * button fires: `publish()` below, for `version` — one code path, so the
   * tab button and the row button cannot drift. `phaseKeys` are i18n KEYS,
   * resolved here at render time: the payload holds no literal label. */
  releaseAction?: { version: string; phaseKeys?: string[] }
}) {
  const qc = useQueryClient()
  // Per-version knowledge of this visit's publish runs (see RunState).
  const [runs, setRuns] = useState<Record<string, RunState>>({})
  const [triggerError, setTriggerError] = useState<string | null>(null)
  const anyRunning = Object.values(runs).some((r) => r.state === 'running')

  const versionsQuery = useQuery({
    queryKey: ['ai-studio', 'publish-versions', projectId],
    queryFn: () => api.listVersions(projectId),
  })
  const recordsQuery = useQuery({
    queryKey: ['ai-studio', 'publish-records', projectId],
    queryFn: () => api.listRecords(projectId),
    // Poll only while a run is in flight; at rest the view reads once.
    refetchInterval: anyRunning ? POLL_MS : false,
  })

  const versions: StudioPublishVersion[] = versionsQuery.data?.versions ?? []
  // Records arrive newest first (backend-sorted); the newest success record
  // IS the latest published hash (B4). A failed record never counts. Memoed
  // so the settle effect below does not re-run on every render.
  const records = useMemo(() => recordsQuery.data?.records ?? [], [recordsQuery.data])
  const latestHash = records.find((r) => r.status === 'success')?.commitHash ?? null

  // Settle a running row once its release record lands: the deploymentId the
  // trigger answered IS the record's, so the match is exact — a same-version
  // older record never settles a newer run.
  useEffect(() => {
    if (records.length === 0) return
    setRuns((prev) => {
      let changed = false
      const next: Record<string, RunState> = { ...prev }
      for (const [version, run] of Object.entries(prev)) {
        if (
          run.state === 'running' &&
          run.deploymentId &&
          records.some((r) => r.status === 'success' && r.deploymentId === run.deploymentId)
        ) {
          next[version] = { ...run, state: 'success' }
          changed = true
        }
      }
      return changed ? next : prev
    })
  }, [records])

  // B1 verdicts, one read per row — a rejected form is a verdict body, not
  // an error, so a failed read here just leaves the row without a reason.
  const previews = useQueries({
    queries: versions.map((v) => ({
      queryKey: ['ai-studio', 'publish-preview', projectId, v.version],
      queryFn: () => api.preview(projectId, v.version),
      staleTime: Infinity,
    })),
  })
  const reasonOf = (version: string): string =>
    previews[versions.findIndex((v) => v.version === version)]?.data?.reason ?? ''
  const formOf = (version: string): string =>
    previews[versions.findIndex((v) => v.version === version)]?.data?.form ?? ''

  const publish = async (v: StudioPublishVersion) => {
    setTriggerError(null)
    setRuns((s) => ({ ...s, [v.version]: { state: 'running' } }))
    try {
      const res = await api.trigger(projectId, v.version, v.commitHash)
      if (res.status === 'failed') {
        // The only carrier of a failure reason: a failed job never writes a
        // release record, so the records poll can never derive 「失败」.
        setRuns((s) => ({
          ...s,
          [v.version]: { state: 'failed', deploymentId: res.deploymentId, reason: res.reason ?? '' },
        }))
        return
      }
      setRuns((s) => ({ ...s, [v.version]: { state: 'running', deploymentId: res.deploymentId } }))
      // Re-read now (an active-query invalidate refetches immediately): the
      // idempotent path's existing record settles this render, a fresh job
      // settles on a later poll once the executor writes its record.
      await qc.invalidateQueries({ queryKey: ['ai-studio', 'publish-records', projectId] })
    } catch (err) {
      if (err instanceof StudioApiError && err.code === 'publish_in_progress') {
        // 409: the same hash is already publishing — the row keeps its ONE
        // 「发布中」 (one run slot per version) and no error notice fires:
        // the user's click was answered truthfully, there is nothing to fix.
        // Keep whatever the row already knows: a double-click's second 409
        // must not wipe the deploymentId its first response carried, or the
        // settle (which matches on it) could never fire.
        setRuns((s) =>
          s[v.version]?.state === 'running' ? s : { ...s, [v.version]: { state: 'running' } },
        )
        return
      }
      setRuns((s) => {
        const next = { ...s }
        delete next[v.version]
        return next
      })
      setTriggerError(err instanceof Error ? err.message : String(err))
    }
  }

  // The tab's own 发版 act (ACP-798): aimed at the version the frame names,
  // fired through the SAME publish() a row's button fires. It carries the
  // row's own §〇 hash rule, so the two controls can never disagree — the
  // button retires exactly when that version's row would lose its own.
  const actionVersion = releaseAction
    ? versions.find((v) => v.version === releaseAction.version)
    : undefined
  const actionDisabled =
    !actionVersion ||
    actionVersion.commitHash === latestHash ||
    formOf(releaseAction?.version ?? '') === 'rejected'

  if (versionsQuery.isError || recordsQuery.isError) {
    return (
      <div>
        <Section>{i18nT('apps.aiStudio.publish_versions_title')}</Section>
        <ErrorNotice
          title={i18nT('apps.aiStudio.publish_versions_error')}
          message={String(versionsQuery.error?.message ?? recordsQuery.error?.message ?? '')}
        />
      </div>
    )
  }

  return (
    <div>
      {/* 发版 — the tab's own action, at the very top of the tab (ACP-798,
          owner's rule 动作按钮跟着页签走). ReleaseControl, not a look-alike:
          same component as the top bar's act, same release-btn contract, and
          its onRelease runs publish(), the row button's own act. */}
      {releaseAction && (
        <div className="flex justify-end mb-2" data-testid="ai-studio-publish-action-row">
          <ReleaseControl
            act="release"
            onRelease={async () => {
              // only reachable while the button is enabled, i.e. the list
              // carries this version; the guard keeps the type honest
              if (actionVersion) await publish(actionVersion)
            }}
            phases={releaseAction.phaseKeys?.map((k) => i18nT(k))}
            disabled={actionDisabled}
          />
        </div>
      )}
      {/* 本版修改过的文件 (ACP-798): the PROCESS half of this tab — what this
          version changed and how far each file is through 拆解成图谱. It sits
          ABOVE the version list, which is the HISTORY half: owner's sidebar
          layout rule (2026-09-23) is that a tab carrying both shows 过程 on
          top (当前清单 + 每个任务的状态) and 历史记录 below, the same order
          ReleasesTool/DeployTool already use (当前进度 → 历史). One row per
          file, a LIST — never a box-and-arrow diagram. Purely a render of the
          bytes it is handed: the demo's frame owns the data, and with the prop
          omitted the whole block is absent, which is every ordinary workbench. */}
      {releaseFiles && releaseFiles.files.length > 0 && (
        <div data-testid="ai-studio-publish-files">
          <Section>{i18nT('apps.aiStudio.publish_files_title')}</Section>
          {releaseFiles.files.map((f) => (
            <div
              key={f.name}
              data-testid={`release-file-${f.name}`}
              className="rounded-lg border border-border bg-card px-3 py-2.5 mb-2"
            >
              <div className="flex items-center gap-2">
                {/* the same status dot the 当前进度 rows use: done = filled,
                    running = pulsing, todo = hollow */}
                <span
                  className={`w-2 h-2 rounded-full shrink-0 ${
                    f.distill === 'done'
                      ? 'bg-accent'
                      : f.distill === 'running'
                        ? 'bg-accent animate-pulse'
                        : 'bg-border-strong'
                  }`}
                />
                <span className="text-[12px] text-text truncate" title={f.name}>
                  {f.name}
                </span>
                {/* 新增 / 修改 / 删除 — the version's own change to this file */}
                <span
                  data-testid={`release-file-change-${f.name}`}
                  className="ml-auto shrink-0 rounded-full bg-bg-hover text-muted px-1.5 py-0.5 text-[10px]"
                >
                  {i18nT(CHANGE_LABEL_KEY[f.change])}
                </span>
              </div>
              {/* the distillation state, its own element with the state ALSO
                  on the DOM as data-distill-state, so a reader (and the
                  acceptance script) can assert the state itself rather than
                  parsing a translated sentence */}
              <span
                data-testid={`release-file-distill-${f.name}`}
                data-distill-state={f.distill}
                className={`mt-1.5 ml-4 inline-block rounded-full px-1.5 py-0.5 text-[10px] ${
                  f.distill === 'done'
                    ? 'bg-accent-subtle text-accent'
                    : f.distill === 'running'
                      ? 'bg-bg-hover text-accent'
                      : 'bg-bg-hover text-muted'
                }`}
              >
                {i18nT(DISTILL_LABEL_KEY[f.distill])}
              </span>
            </div>
          ))}
        </div>
      )}
      <Section>{i18nT('apps.aiStudio.publish_versions_title')}</Section>
      {versionsQuery.isPending || recordsQuery.isPending ? (
        <div className="text-[12px] text-muted px-1 py-2">{i18nT('apps.aiStudio.publish_versions_loading')}</div>
      ) : versions.length === 0 ? (
        <div className="text-[12px] text-muted px-1 py-2">{i18nT('apps.aiStudio.publish_versions_empty')}</div>
      ) : (
        <div data-testid="ai-studio-publish-version-list">
          {versions.map((v) => {
            const successRecord: StudioPublishRecord | undefined = records.find(
              (r) =>
                r.status === 'success' && r.version === v.version && r.commitHash === v.commitHash,
            )
            // Two derivations, deliberately separate:
            // - 状态 (B4): 「已发布」 = THIS hash has a success record (any
            //   version row with a record reads it, latest or superseded);
            // - 按钮 (§〇 hash rule): equal to the LATEST published hash →
            //   NO button (not a disabled one); any other hash — including
            //   an older published one, the D3 rollback re-publish — renders
            //   it. When a rollback makes an older hash the latest, this is
            //   exactly what returns the superseded row's button (D3) while
            //   its own record keeps it 已发布 (A8 「其余行不变」).
            const published = successRecord !== undefined
            const canPublish = v.commitHash !== latestHash && formOf(v.version) !== 'rejected'
            const run = runs[v.version]
            const running = run?.state === 'running'
            // The lifecycle state (§〇-1 four states), kept separate from the
            // action-result text below: 失败/发布中 come from this visit's
            // run, 已发布/未发布 from the records (no record = 未发布).
            const stateKey =
              run?.state === 'failed'
                ? 'apps.aiStudio.publish_state_failed'
                : running
                  ? 'apps.aiStudio.publish_state_publishing'
                  : published
                    ? 'apps.aiStudio.publish_state_published'
                    : 'apps.aiStudio.publish_state_unpublished'
            const reason = reasonOf(v.version)
            // The release-job id: this visit's run carries it from the
            // trigger response; an already-published row reads it off the
            // record (A7: the record lives on the release-job page, reached
            // through this link — the row shows the id, never a record).
            const deploymentId = run?.deploymentId ?? (published ? successRecord?.deploymentId : undefined)
            const showStrip = run !== undefined || published
            return (
              <div
                key={v.version}
                data-testid={`ai-studio-publish-version-row-${v.version}`}
                className="rounded-lg border border-border bg-card px-3 py-2.5 mb-2"
              >
                <div className="flex items-center justify-between gap-2">
                  {/* 版本 column: the label plus the short hash */}
                  <span className="text-[12px] font-semibold text-text truncate">
                    {v.version}
                    <span className="text-[11px] text-muted ml-1.5">{v.commitHash.slice(0, SHORT_HASH)}</span>
                  </span>
                  {/* 状态 column: the lifecycle state, its own element */}
                  <span
                    data-testid="ai-studio-publish-version-state"
                    className={`shrink-0 rounded-full px-1.5 py-0.5 text-[10px] ${
                      published
                        ? 'bg-accent-subtle text-accent'
                        : run?.state === 'failed'
                          ? 'bg-danger-subtle text-danger'
                          : 'bg-bg-hover text-muted'
                    }`}
                  >
                    {i18nT(stateKey)}
                  </span>
                </div>
                {/* 动作 column: the button when the hash rule says so, else
                    just the reason; the reason text always rides the row so
                    it stays separable from the state */}
                <div className="flex items-center justify-between gap-2 mt-1.5">
                  {canPublish ? (
                    <Btn
                      data-testid={`ai-studio-publish-btn-${v.version}`}
                      className="!text-[11px] !px-2 !py-1"
                      disabled={running}
                      onClick={() => publish(v)}
                    >
                      {i18nT('apps.aiStudio.publish_action')}
                    </Btn>
                  ) : (
                    <span />
                  )}
                  {reason && (
                    <span
                      data-testid={`ai-studio-publish-reason-${v.version}`}
                      title={reason}
                      className="text-[11px] text-muted text-right line-clamp-2"
                    >
                      {reason}
                    </span>
                  )}
                </div>
                {/* 行内发布结果条 (T6): the action-result text belongs to
                    this run; the release facts (form badge, serving url)
                    ride the row's success record, whose url is the href
                    verbatim (08 §〇 template — §四 probes it as written).
                    Both link out in a NEW tab (新页签). */}
                {showStrip && (
                  <div className="flex flex-wrap items-center gap-2 mt-1.5 min-w-0">
                    {run && (
                      <span
                        data-testid={`ai-studio-publish-status-${v.version}`}
                        aria-live="polite"
                        className={`text-[11px] break-all ${
                          run.state === 'failed'
                            ? 'text-danger'
                            : run.state === 'success'
                              ? 'text-accent'
                              : 'text-muted'
                        }`}
                      >
                        {run.state === 'running' && i18nT('apps.aiStudio.publish_state_publishing')}
                        {run.state === 'success' && i18nT('apps.aiStudio.publish_run_success')}
                        {run.state === 'failed' &&
                          i18nT('apps.aiStudio.publish_run_failed', { reason: run.reason ?? '' })}
                      </span>
                    )}
                    {published && successRecord && (
                      <>
                        <span
                          data-testid={`ai-studio-publish-form-badge-${v.version}`}
                          className="shrink-0 rounded-full bg-accent-subtle text-accent px-1.5 py-0.5 text-[10px]"
                        >
                          {formBadge(successRecord.form)}
                        </span>
                        <a
                          data-testid={`ai-studio-publish-url-${v.version}`}
                          href={successRecord.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-[11px] text-accent hover:underline truncate max-w-full"
                        >
                          {i18nT('apps.aiStudio.publish_open_link')}
                        </a>
                      </>
                    )}
                    {deploymentId && (
                      <a
                        data-testid={`ai-studio-publish-id-${v.version}`}
                        href={`/release-jobs/${encodeURIComponent(deploymentId)}?project=${encodeURIComponent(projectId)}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-[11px] text-muted hover:text-accent hover:underline truncate max-w-full"
                      >
                        {deploymentId}
                      </a>
                    )}
                  </div>
                )}
              </div>
            )
          })}
          {triggerError && (
            <ErrorNotice title={i18nT('apps.aiStudio.publish_trigger_error')} message={triggerError} />
          )}
        </div>
      )}
      </div>
  )
}

const CHANGE_LABEL_KEY: Record<StudioReleaseFile['change'], string> = {
  added: 'apps.aiStudio.publish_file_change_added',
  modified: 'apps.aiStudio.publish_file_change_modified',
  deleted: 'apps.aiStudio.publish_file_change_deleted',
}

const DISTILL_LABEL_KEY: Record<StudioReleaseFile['distill'], string> = {
  done: 'apps.aiStudio.publish_file_distill_done',
  running: 'apps.aiStudio.publish_file_distill_running',
  pending: 'apps.aiStudio.publish_file_distill_pending',
}

/** The release's form as the badge the acceptance reads (A5: the git-tag
 * annotation's own words — 完整版 / 演示版). The catalog keys carry those
 * labels per language; an unknown form string renders itself rather than a
 * invented label. */
function formBadge(form: string): string {
  if (form === 'full') return i18nT('apps.aiStudio.publish_form_full')
  if (form === 'demo') return i18nT('apps.aiStudio.publish_form_demo')
  return form
}

function Section({ children }: { children: string }) {
  return (
    <div className="text-[11px] uppercase tracking-wide text-muted mx-0.5 mt-2 mb-1.5 first:mt-0">
      {children}
    </div>
  )
}
