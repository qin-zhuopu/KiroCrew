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
import ErrorNotice from '../../components/ErrorNotice'
import { Btn, ContentSkeleton, EmptyState, PageHeader } from '../../components/ui'
import { fmtRelative } from '../../i18n/format'
import { i18nT } from '../../i18n/t'
import { DevServerBadge } from './DevServerControl'
import NewWorkspaceDialog from './NewWorkspaceDialog'
import { studioApi, type StudioProject } from './studioApi'

export default function ProjectsListPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  // The dialog doubles as the derive-progress view (ACP-2085, RFC §7 A3), so what
  // opens it is a project id: null = the blank form, an id = that job's progress.
  // 「点卡片可重新打开进度」 — a card whose job is creating/failed opens the same
  // component seeded with its record, which is why one piece of state covers both.
  const [openFor, setOpenFor] = useState<string | null>(null)

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
              />
            ))}
          </div>
        )}
      </div>

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

function ProjectCard({ project, onOpen }: { project: StudioProject; onOpen: () => void }) {
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
        <DevServerBadge projectId={project.id} />
      </div>
    </Clickable>
  )
}
