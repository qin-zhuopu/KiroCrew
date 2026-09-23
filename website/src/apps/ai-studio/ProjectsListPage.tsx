// The app's landing view: every AI Studio project as a card, newest first, and
// the "new project" dialog. A project is a directory the backend created under
// the data home (identity + three seeded docs); this page only names and lists
// them — opening one is a route into the workbench, which loads the docs.
//
// Data is React Query (the frontend rule): the list is a query, the create is a
// mutation that invalidates it so the new card appears without a manual refetch.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Plus, X } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import Clickable from '../../components/Clickable'
import ErrorNotice from '../../components/ErrorNotice'
import { Btn, ContentSkeleton, EmptyState, Input, PageHeader } from '../../components/ui'
import { useDialogFocusTrap } from '../../hooks/useDialogFocusTrap'
import { fmtRelative } from '../../i18n/format'
import { i18nT } from '../../i18n/t'
import { studioApi, StudioApiError, type StudioProject } from './studioApi'

export default function ProjectsListPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)

  const projectsQuery = useQuery({
    queryKey: ['ai-studio', 'projects'],
    queryFn: () => studioApi.listProjects().then((r) => r.projects),
  })

  const createProject = useMutation({
    mutationFn: ({ name, description }: { name: string; description: string }) =>
      studioApi.createProject(name, description),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['ai-studio', 'projects'] })
      setCreating(false)
      navigate(`/ai-studio/projects/${encodeURIComponent(res.project.id)}`)
    },
  })

  return (
    <div className="flex flex-col h-full min-h-0" data-testid="ai-studio-projects">
      <PageHeader
        title={i18nT('apps.aiStudio.projects_title')}
        actions={
          <Btn primary onClick={() => setCreating(true)}>
            <Plus size={14} className="lucide-inline" /> {i18nT('apps.aiStudio.new_project')}
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
              <Btn primary onClick={() => setCreating(true)}>
                {i18nT('apps.aiStudio.new_project')}
              </Btn>
            }
          />
        ) : (
          <div className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(240px,1fr))]">
            {(projectsQuery.data ?? []).map((p) => (
              <ProjectCard
                key={p.id}
                project={p}
                onOpen={() => navigate(`/ai-studio/projects/${encodeURIComponent(p.id)}`)}
              />
            ))}
          </div>
        )}
      </div>

      <AnimatePresence>
        {creating && (
          <NewProjectDialog
            pending={createProject.isPending}
            error={createProject.error ? apiErrorMessage(createProject.error) : null}
            onCancel={() => setCreating(false)}
            onSubmit={(name, description) => createProject.mutate({ name, description })}
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
      className="text-left rounded-xl border border-border bg-card px-4 py-3.5 cursor-pointer transition-colors hover:border-accent"
    >
      <div className="text-[13px] font-semibold text-text-strong truncate">{project.name}</div>
      {project.description && (
        <div className="text-[12px] text-muted mt-1 line-clamp-2 min-h-[2em]">{project.description}</div>
      )}
      <div className="text-[11px] text-muted mt-2">{fmtRelative(project.createdAt * 1000)}</div>
    </Clickable>
  )
}

function NewProjectDialog({
  pending,
  error,
  onCancel,
  onSubmit,
}: {
  pending: boolean
  error: string | null
  onCancel: () => void
  onSubmit: (name: string, description: string) => void
}) {
  const dialogRef = useRef<HTMLDivElement>(null)
  useDialogFocusTrap(dialogRef, onCancel)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const canSubmit = name.trim().length > 0 && !pending

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3">
      <Clickable className="absolute inset-0 bg-bg/50 backdrop-blur-xs" onClick={onCancel} aria-label={i18nT('apps.aiStudio.cancel')} />
      <motion.div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={i18nT('apps.aiStudio.new_project')}
        tabIndex={-1}
        initial={{ opacity: 0, y: 8, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 8, scale: 0.98 }}
        transition={{ duration: 0.18, ease: 'easeOut' }}
        className="relative w-full max-w-[440px] border border-border rounded-[14px] bg-card p-6 shadow-2xl outline-hidden"
        onKeyDown={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          onClick={onCancel}
          disabled={pending}
          aria-label={i18nT('apps.aiStudio.cancel')}
          className="absolute top-3 right-3 p-1.5 rounded-md text-muted hover:text-text hover:bg-bg-hover cursor-pointer bg-transparent border-0 disabled:opacity-30 disabled:cursor-default"
        >
          <X size={16} />
        </button>
        <div className="text-[15px] font-semibold text-text-strong mb-4">{i18nT('apps.aiStudio.new_project')}</div>
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (canSubmit) onSubmit(name.trim(), description.trim())
          }}
        >
          <label className="flex flex-col gap-1 text-[12px] text-muted">
            {i18nT('apps.aiStudio.project_name')}
            <Input
              autoFocus
              value={name}
              maxLength={120}
              onChange={(e) => setName(e.target.value)}
              placeholder={i18nT('apps.aiStudio.project_name_placeholder')}
            />
          </label>
          <label className="flex flex-col gap-1 text-[12px] text-muted">
            {i18nT('apps.aiStudio.project_description')}
            <textarea
              value={description}
              maxLength={2000}
              rows={3}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={i18nT('apps.aiStudio.project_description_placeholder')}
              className="w-full resize-none rounded-md border border-border bg-bg px-2.5 py-2 text-[13px] text-text outline-none focus:border-accent"
            />
          </label>
          {error && <ErrorNotice message={error} askAgent={false} />}
          <div className="flex justify-end gap-2 mt-1">
            <Btn type="button" onClick={onCancel} disabled={pending}>
              {i18nT('apps.aiStudio.cancel')}
            </Btn>
            <Btn type="submit" primary disabled={!canSubmit}>
              {i18nT('apps.aiStudio.create_project')}
            </Btn>
          </div>
        </form>
      </motion.div>
    </div>
  )
}

// The backend's error body carries a machine code; the user sees a sentence.
// app_disabled in particular must not read as "network" — it means the app was
// switched off in Settings while this tab sat open.
function apiErrorMessage(err: unknown): string {
  if (err instanceof StudioApiError) {
    if (err.code === 'app_disabled') return i18nT('apps.aiStudio.err_app_disabled')
    if (err.code === 'name_required') return i18nT('apps.aiStudio.err_name_required')
    return err.message
  }
  return err instanceof Error ? err.message : String(err)
}
