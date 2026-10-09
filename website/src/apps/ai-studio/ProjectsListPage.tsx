// The app's landing view: every AI Studio project as a card, newest first, and
// the 新建工作区 dialog. A project is a directory the backend created under the
// data home; a WORKSPACE (ACP-2085) is one of those plus a Git repo derived from
// the template, and the only difference this page renders is a status word and
// what the card's click does.
//
// Data is React Query (the frontend rule): the list is a query, the create lives
// inside the dialog and invalidates this key so the new card appears without a
// manual refetch.
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { AnimatePresence } from 'framer-motion'
import { Plus } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import Clickable from '../../components/Clickable'
import { useConfirm } from '../../components/ConfirmDialog'
import ErrorNotice from '../../components/ErrorNotice'
import { Btn, ContentSkeleton, EmptyState, PageHeader } from '../../components/ui'
import { fmtRelative } from '../../i18n/format'
import { i18nT } from '../../i18n/t'
import { DevServerBadge } from './DevServerControl'
import NewWorkspaceDialog from './NewWorkspaceDialog'
import { studioApi, workspaceApi, type StudioProject } from './studioApi'

export default function ProjectsListPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  // The dialog doubles as the derive-progress view (ACP-2085, RFC §7 A3), so what
  // opens it is a project id: null = the blank form, an id = that job's progress.
  // 「点卡片可重新打开进度」 — a card whose job is creating/failed opens the same
  // component seeded with its record, which is why one piece of state covers both.
  const [openFor, setOpenFor] = useState<string | null>(null)
  // The delete's own refusal (ACP-2206), shown at the top of the list rather
  // than inside a card: a card is a `Clickable`, so an error box inside one
  // would be a control that also opens the workbench. Verbatim backend text —
  // 「开发进行中，先等它结束」 names what to wait for, and paraphrasing it would
  // lose that.
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const { confirm, confirmDialog } = useConfirm()

  // The unwrapped array is this key's shape on purpose: `ProjectsList` in
  // AiStudioPage.tsx observes the SAME key and reads `data[0]` off it for the
  // demo button, so whoever wins the race has to answer the same shape. The 工号
  // the dialog needs is therefore read by its own query (below), not by changing
  // this one to return the whole `{projects, staffId}` body.
  const projectsQuery = useQuery({
    queryKey: ['ai-studio', 'projects'],
    queryFn: () => studioApi.listProjects().then((r) => r.projects),
  })

  // Only read while the dialog is open, and only so long: one list GET per open,
  // which is what the 工号 display (RFC §7 A2: it comes from the login, the user
  // cannot type it) costs.
  const staffQuery = useQuery({
    queryKey: ['ai-studio', 'staff-id'],
    queryFn: () => studioApi.listProjects().then((r) => r.staffId ?? ''),
    enabled: openFor !== null,
  })

  const onCreated = () => queryClient.invalidateQueries({ queryKey: ['ai-studio', 'projects'] })

  // 删除工作区 (ACP-2206). The dialog is the whole safety story: the backend
  // MOVES the workspace and its record into `.trash` and leaves the remote repo
  // alone, and the copy says exactly that — an operator deciding with this
  // sentence in front of them does not need to know the ticket to know what
  // they are losing. The refusal is shown, never swallowed: 409 `dev_running`
  // means a development run is mid-flight, which is a fact about their board.
  const onDelete = async (project: StudioProject) => {
    const confirmed = await confirm({
      title: i18nT('apps.aiStudio.projectDelete.title'),
      body: i18nT('apps.aiStudio.projectDelete.confirm', { name: project.name }),
      confirmLabel: i18nT('apps.aiStudio.projectDelete.confirm_label'),
    })
    if (!confirmed) return
    setDeleteError(null)
    try {
      await workspaceApi.deleteProject(project.id)
      // the list is the whole success state: the card is gone and nothing else
      // on this screen changes. The response's `trash` path has no screen of
      // its own yet (this iteration ships no 回收站 view), so it stays in the
      // response rather than becoming an invented toast.
      onCreated()
    } catch (e) {
      setDeleteError(String((e as Error)?.message ?? e))
    }
  }

  return (
    <div className="flex flex-col h-full min-h-0" data-testid="ai-studio-projects">
      <PageHeader
        title={i18nT('apps.aiStudio.projects_title')}
        actions={
          <Btn primary data-testid="new-ws-open" onClick={() => setOpenFor('')}>
            <Plus size={14} className="lucide-inline" /> {i18nT('apps.aiStudio.newWorkspace.title')}
          </Btn>
        }
      />
      <div className="flex-1 min-h-0 overflow-auto p-4">
        <ErrorNotice message={deleteError} onDismiss={() => setDeleteError(null)} testId="project-delete-error" />
        {projectsQuery.isLoading ? (
          <ContentSkeleton rows={3} />
        ) : projectsQuery.isError ? (
          <ErrorNotice message={String(projectsQuery.error?.message ?? projectsQuery.error)} />
        ) : (projectsQuery.data?.length ?? 0) === 0 ? (
          <EmptyState
            icon={<Plus size={22} />}
            title={i18nT('apps.aiStudio.projects_empty_title')}
            subtitle={i18nT('apps.aiStudio.projects_empty_hint')}
            action={
              <Btn primary data-testid="new-ws-open" onClick={() => setOpenFor('')}>
                {i18nT('apps.aiStudio.newWorkspace.title')}
              </Btn>
            }
          />
        ) : (
          <div className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(240px,1fr))]">
            {(projectsQuery.data ?? []).map((p) => (
              <ProjectCard
                key={p.id}
                project={p}
                // a workspace that never finished deriving has nothing to open:
                // its workbench would show no docs and no repo. The progress is
                // the useful view, so the card reopens the dialog instead.
                onOpen={() =>
                  p.code && p.status !== 'ready'
                    ? setOpenFor(p.id)
                    : navigate(`/workspaces/${encodeURIComponent(p.id)}/ai-studio`)
                }
                onDelete={() => onDelete(p)}
              />
            ))}
          </div>
        )}
      </div>
      {confirmDialog}

      <AnimatePresence>
        {openFor !== null && (
          <NewWorkspaceDialog
            initialProjectId={openFor || null}
            staffId={staffQuery.data ?? ''}
            onClose={() => setOpenFor(null)}
            onCreated={onCreated}
          />
        )}
      </AnimatePresence>
    </div>
  )
}

function ProjectCard({
  project,
  onOpen,
  onDelete,
}: {
  project: StudioProject
  onOpen: () => void
  onDelete: () => void
}) {
  return (
    <Clickable
      onClick={onOpen}
      data-testid={`project-card-${project.id}`}
      className="text-left rounded-xl border border-border bg-card px-4 py-3.5 cursor-pointer transition-colors hover:border-accent"
    >
      <div className="text-[13px] font-semibold text-text-strong truncate">{project.name}</div>
      {project.description && (
        <div className="text-[12px] text-muted mt-1 line-clamp-2 min-h-[2em]">{project.description}</div>
      )}
      {/* the footer row carries the when, the workspace's derive status
          (ACP-2085) and, ACP-2060, the live dev-server URL. The badge renders
          nothing at all unless that project's server answers `running`, and a
          non-workspace project has no `status`, so an ordinary project's card is
          byte-identical to before. */}
      <div className="flex items-center justify-between gap-2 mt-2 min-w-0">
        <span className="flex items-center gap-2 min-w-0">
          <span className="text-[11px] text-muted shrink-0">{fmtRelative(project.createdAt * 1000)}</span>
          {project.status === 'creating' && (
            <span className="text-[11px] text-warn shrink-0" data-testid={`project-status-${project.id}`}>
              {i18nT('apps.aiStudio.newWorkspace.status_creating')}
            </span>
          )}
          {project.status === 'failed' && (
            <span className="text-[11px] text-err shrink-0" data-testid={`project-status-${project.id}`}>
              {i18nT('apps.aiStudio.newWorkspace.status_failed')}
            </span>
          )}
        </span>
        {/* `shrink-0` on the pair, not the row: the badge truncates by design and
            a delete label must never be the thing that gets squeezed away. */}
        <span className="flex items-center gap-1 shrink-0">
          <DevServerBadge projectId={project.id} />
          {/* 删除 (ACP-2206). Every card carries it, including a failed or
              half-derived one — a botched derive is precisely the project an
              operator wants gone, and the backend's delete tolerates a
              workspace directory that was never created. `stopPropagation`
              because the card itself is the click target: without it the
              button would open the workbench on the way to the dialog. */}
          <Btn
            danger
            data-testid={`project-delete-${project.id}`}
            onClick={(e) => {
              e.stopPropagation()
              onDelete()
            }}
            className="px-1.5 py-0.5 text-[11px]"
          >
            {i18nT('apps.aiStudio.projectDelete.label')}
          </Btn>
        </span>
      </div>
    </Clickable>
  )
}
