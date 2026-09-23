// The workspace top bar's project-level commit (ACP-727), extracted so both
// workbench surfaces render the SAME control running the SAME logic: the
// ordinary StudioWorkspace (real studioApi) and the demo's snapshot-backed
// workbench (injected fake — the same `api` seam DocEditor and WorkArea
// already take). Committing is a PROJECT-level operation because the commit
// feeds the whole project's requirements graph, not one file: the bar reads
// every doc with a draft (GET projects/{id}/drafts), names them in the
// badge, and commits each through the per-doc endpoint (old content into
// versions/, drafts cleared), sequentially — the store is plain file I/O and
// a mid-list failure should leave the earlier commits done rather than race
// partial writes. Afterwards the caller re-mounts its open editors onto the
// committed content (onCommitted carries the refetched docs).
import { useCallback, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { GitCommit } from 'lucide-react'
import ErrorNotice from '../../components/ErrorNotice'
import { Btn } from '../../components/ui'
import { i18nT } from '../../i18n/t'
import { studioApi, type StudioApi, type StudioDoc } from './studioApi'

export default function ProjectCommitBar({ projectId, api = studioApi, onCommitted }: {
  projectId: string
  /** data source, injectable for the demo's snapshot fake */
  api?: StudioApi
  /** called after a successful commit with the freshly committed docs */
  onCommitted?: (docs: StudioDoc[]) => void
}) {
  const [committing, setCommitting] = useState(false)
  const [commitErr, setCommitErr] = useState<string | null>(null)
  const queryClient = useQueryClient()

  // Which docs hold an uncommitted draft — the Commit affordance and its
  // work list. No polling: the default refetch-on-focus plus the post-commit
  // refetch keep it honest.
  const draftsQuery = useQuery({
    queryKey: ['ai-studio', 'drafts', projectId],
    queryFn: () => api.listDraftDocs(projectId).then((r) => r.drafts),
  })
  const draftDocs = draftsQuery.data ?? []

  const commitAll = useCallback(async () => {
    const work = draftDocs
    if (work.length === 0 || committing) return
    setCommitting(true)
    setCommitErr(null)
    try {
      for (const d of work) {
        await api.saveDoc(projectId, d.name, d.content)
      }
      // The tabs must be re-pointed at the COMMITTED content, and the only
      // safe source is the refetch result itself: any list captured before
      // the commit is a pre-edit snapshot, and rewriting a tab from it would
      // silently roll the editor back to the pre-edit text.
      const [fresh] = await Promise.all([
        queryClient.fetchQuery({
          queryKey: ['ai-studio', 'project', projectId],
          queryFn: () => api.getProject(projectId),
        }),
        draftsQuery.refetch(),
        queryClient.invalidateQueries({ queryKey: ['ai-studio', 'draft-versions', projectId] }),
        queryClient.invalidateQueries({ queryKey: ['ai-studio', 'versions', projectId] }),
      ])
      onCommitted?.(fresh.docs ?? [])
    } catch (err) {
      setCommitErr(err instanceof Error ? err.message : String(err))
    } finally {
      setCommitting(false)
    }
  }, [draftDocs, committing, projectId, api, draftsQuery, queryClient, onCommitted])

  return (
    <>
      {draftDocs.length > 0 && (
        <span data-testid="drafts-pending" className="rounded-full bg-accent-subtle px-2 py-0.5 text-[11px] text-accent max-w-[280px] truncate" title={draftDocs.map((d) => d.name).join(', ')}>
          {i18nT('apps.aiStudio.drafts_pending')}: {draftDocs.map((d) => d.name).join(', ')}
        </span>
      )}
      <Btn
        primary
        onClick={commitAll}
        disabled={draftDocs.length === 0 || committing}
        title={i18nT('apps.aiStudio.commit_all_hint')}
        data-testid="commit-all-btn"
      >
        <GitCommit size={13} className="lucide-inline" />
        {committing ? i18nT('apps.aiStudio.committing') : i18nT('apps.aiStudio.commit_all')}
      </Btn>
      {commitErr && (
        // the bar sits inside a `relative` header, so the failure reads the
        // way it always did: a strip dropped under the top bar, not a card
        // crushed into the 44px row.
        <div className="absolute left-0 right-0 top-full z-40 px-4 pt-2">
          {/* askAgent off: the failing commit is re-runnable from this same
              bar, there is no buffer in here to hand off. */}
          <ErrorNotice message={commitErr} askAgent={false} onDismiss={() => setCommitErr(null)} />
        </div>
      )}
    </>
  )
}
