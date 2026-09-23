// The publish view (08-publish-app §〇-1): the versions of the project as
// rows in the right sidebar's Releases tab, one row per version, each row
// carrying its lifecycle state, its form verdict reason, and — when its hash
// differs from the latest published hash — an inline publish button built
// HERE (never the top bar's ReleaseControl, whose release-btn testid is a
// different control). No version picker, no free-text input, no confirm
// dialog: the user sees the list and fires a row.
//
// Data: versions from the publish versions read; the per-version published
// states and the "latest published hash" (the newest success record's hash)
// from GET /publish/records (B4); the form reason from GET /publish/preview
// (B1, whose source is the version's git tag annotation).
//
// Scope note: this is T5 only. The button fires POST /publish and flips the
// row to 「发布中」 honestly, but the result strip (status/badge/url/job-id
// links) and the refresh loop that settles the final state are T6's.
import { useState } from 'react'
import { useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { i18nT } from '../../i18n/t'
import ErrorNotice from '../../components/ErrorNotice'
import { Btn } from '../../components/ui'
import { publishApi, type StudioPublishVersion } from './studioApi'

const SHORT_HASH = 7

export default function PublishVersionList({ projectId }: { projectId: string }) {
  const qc = useQueryClient()
  // Which row's POST /publish is in flight — the honest 「发布中」 the row
  // shows until T6's polling loop owns the state end to end.
  const [starting, setStarting] = useState<string | null>(null)
  // Versions whose publish has been fired this visit but whose success record
  // has not landed yet: they read 「发布中」 until the record says otherwise
  // (T6 replaces this bookkeeping with real polling).
  const [fired, setFired] = useState<Set<string>>(new Set())
  const [triggerError, setTriggerError] = useState<string | null>(null)

  const versionsQuery = useQuery({
    queryKey: ['ai-studio', 'publish-versions', projectId],
    queryFn: () => publishApi.listVersions(projectId),
  })
  const recordsQuery = useQuery({
    queryKey: ['ai-studio', 'publish-records', projectId],
    queryFn: () => publishApi.listRecords(projectId),
  })

  const versions: StudioPublishVersion[] = versionsQuery.data?.versions ?? []
  // Records arrive newest first (backend-sorted); the newest success record
  // IS the latest published hash (B4). A failed record never counts.
  const records = recordsQuery.data?.records ?? []
  const latestHash = records.find((r) => r.status === 'success')?.commitHash ?? null

  // B1 verdicts, one read per row — a rejected form is a verdict body, not
  // an error, so a failed read here just leaves the row without a reason.
  const previews = useQueries({
    queries: versions.map((v) => ({
      queryKey: ['ai-studio', 'publish-preview', projectId, v.version],
      queryFn: () => publishApi.preview(projectId, v.version),
      staleTime: Infinity,
    })),
  })
  const reasonOf = (version: string): string =>
    previews[versions.findIndex((v) => v.version === version)]?.data?.reason ?? ''
  const formOf = (version: string): string =>
    previews[versions.findIndex((v) => v.version === version)]?.data?.form ?? ''

  const publish = async (v: StudioPublishVersion) => {
    setTriggerError(null)
    setStarting(v.version)
    try {
      await publishApi.trigger(projectId, v.version, v.commitHash)
      setFired((s) => new Set(s).add(v.version))
      // The record the job will leave is not written yet — re-read rather
      // than pretending the state settled (T6 replaces this with polling).
      await qc.invalidateQueries({ queryKey: ['ai-studio', 'publish-records', projectId] })
    } catch (err) {
      setTriggerError(err instanceof Error ? err.message : String(err))
    } finally {
      setStarting(null)
    }
  }

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
      <Section>{i18nT('apps.aiStudio.publish_versions_title')}</Section>
      {versionsQuery.isPending || recordsQuery.isPending ? (
        <div className="text-[12px] text-muted px-1 py-2">{i18nT('apps.aiStudio.publish_versions_loading')}</div>
      ) : versions.length === 0 ? (
        <div className="text-[12px] text-muted px-1 py-2">{i18nT('apps.aiStudio.publish_versions_empty')}</div>
      ) : (
        <div data-testid="ai-studio-publish-version-list">
          {versions.map((v) => {
            const published = records.some(
              (r) => r.status === 'success' && r.version === v.version && r.commitHash === v.commitHash,
            )
            // Hash rule (§〇): equal to the latest published hash → the row
            // renders NO button (not a disabled one) and reads 「已发布」;
            // any other hash — including an older published one, the D3
            // rollback re-publish — renders it.
            const canPublish = v.commitHash !== latestHash && formOf(v.version) !== 'rejected'
            const isStarting = starting === v.version
            // The lifecycle state (§〇-1): record-derived 已发布/未发布, with
            // the honest 「发布中」 while this visit's fired publish is
            // unsettled. (失败 and the settled 发布中 loop are T6's.)
            const publishing = (isStarting || fired.has(v.version)) && !published
            const reason = reasonOf(v.version)
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
                      published ? 'bg-accent-subtle text-accent' : 'bg-bg-hover text-muted'
                    }`}
                  >
                    {publishing
                      ? i18nT('apps.aiStudio.publish_state_publishing')
                      : published
                        ? i18nT('apps.aiStudio.publish_state_published')
                        : i18nT('apps.aiStudio.publish_state_unpublished')}
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
                      disabled={starting !== null}
                      onClick={() => publish(v)}
                    >
                      {i18nT('apps.aiStudio.publish_action')}
                    </Btn>
                  ) : <span />}
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
              </div>
            )
          })}
          {triggerError && (
            <ErrorNotice
              title={i18nT('apps.aiStudio.publish_trigger_error')}
              message={triggerError}
            />
          )}
        </div>
      )}
    </div>
  )
}

function Section({ children }: { children: string }) {
  return <div className="text-[11px] uppercase tracking-wide text-muted mx-0.5 mt-2 mb-1.5 first:mt-0">{children}</div>
}
