// The 新建工作区 dialog (ACP-2085, RFC §7 A2~A3). One component holds both halves
// of the journey on purpose: the form and, after the create is accepted, the step
// progress. Splitting them would mean passing a fresh project id across a mount
// boundary and re-deriving which half to show — whereas the honest predicate is
// "do I have an id yet", which is one piece of state inside this component.
//
// Three rules the backend forces on this UI:
//
// 1. The record is the progress. `POST /projects` answers 201 as soon as the
//    directory exists — a template clone is minutes long and no HTTP handler may
//    wait for it — so the rows come from `GET /projects/{id}`, re-read every 2s
//    while the job is `creating`. A refresh or a second tab sees the same rows,
//    which is why nothing here keeps step state of its own.
// 2. Step names and failure text are BACKEND data, rendered verbatim. The names
//    are Chinese by contract (§9.1) and the message is the tail of the failing
//    command's output — the only place the real error exists. Re-labelling or
//    re-templating either would put words between the operator and the failure.
// 3. Retry is one endpoint with no step argument: the backend re-runs whichever
//    step broke (and skips straight to the push when the workspace already
//    exists as a Git repo). So the button is "retry this job", never N buttons.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { AlertCircle, Check, Loader2, X } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import Clickable from '../../components/Clickable'
import ErrorNotice from '../../components/ErrorNotice'
import { Btn, Input } from '../../components/ui'
import { useDialogFocusTrap } from '../../hooks/useDialogFocusTrap'
import { i18nT } from '../../i18n/t'
import {
  studioApi,
  workspaceApi,
  StudioApiError,
  type StudioProject,
  type StudioWorkspaceStepState,
} from './studioApi'

/** Same expression as the backend's `workspace.CODE_RE` (§9.1): 3~24 characters,
 * lowercase letter first, letters/digits/hyphen, last character not a hyphen.
 * The copy below is what the RFC dictates the user sees when it does not match. */
export const CODE_RE = /^[a-z][a-z0-9-]{1,22}[a-z0-9]$/

/** The template this iteration offers, shown read-only (RFC §7 A2: 本期只有一个).
 * Display-only: the create posts no `template`, so the backend resolves its own
 * configured default and the two can never disagree about what got cloned. */
const TEMPLATE_LABEL = 'webapp-template'

/** Icons per step state. `pending` is a dim circle rather than the ⏳ the RFC
 * sketch used: same message (nothing has happened here), and a glyph from the
 * icon set the rest of the dashboard already ships instead of an emoji whose
 * rendering differs per platform. */
function StepIcon({ state }: { state: StudioWorkspaceStepState }) {
  if (state === 'running')
    return <Loader2 size={13} className="shrink-0 animate-spin motion-reduce:animate-none text-accent" aria-hidden />
  if (state === 'done') return <Check size={13} className="shrink-0 text-ok" aria-hidden />
  if (state === 'failed') return <AlertCircle size={13} className="shrink-0 text-err" aria-hidden />
  return (
    <span
      aria-hidden
      className="inline-block w-2 h-2 shrink-0 rounded-full border border-border-strong"
    />
  )
}

const STATE_TEXT: Record<StudioWorkspaceStepState, string> = {
  pending: 'apps.aiStudio.newWorkspace.step_pending',
  running: 'apps.aiStudio.newWorkspace.step_running',
  done: 'apps.aiStudio.newWorkspace.step_done',
  failed: 'apps.aiStudio.newWorkspace.step_failed',
}

export default function NewWorkspaceDialog({
  staffId,
  initialProjectId = null,
  onClose,
  onCreated,
}: {
  staffId: string
  /** open straight on a job's progress: a card whose workspace is still creating
   * (or whose derive failed) reopens the dialog rather than a workbench with no
   * repo in it (RFC §7 A3, and the list's 「点卡片可重新打开进度」) */
  initialProjectId?: string | null
  onClose: () => void
  /** called after the record exists, so the list learns about the new card even
   * if the operator closes the dialog mid-derive */
  onCreated: (project: StudioProject) => void
}) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const dialogRef = useRef<HTMLDivElement>(null)
  useDialogFocusTrap(dialogRef, onClose)

  const [name, setName] = useState('')
  const [code, setCode] = useState('')
  const [description, setDescription] = useState('')
  // non-null once there is a job to show: either the create below was accepted,
  // or the dialog opened straight onto an existing one
  const [createdId, setCreatedId] = useState<string | null>(initialProjectId)
  const [actionError, setActionError] = useState<string | null>(null)
  const [showLog, setShowLog] = useState(false)
  const [logLines, setLogLines] = useState<string[] | null>(null)

  const codeOk = CODE_RE.test(code.trim())
  // 2~40 characters, counted on the trimmed text — the same rule the backend's
  // name check enforces from the other side, and the reason both bounds are
  // checked here rather than trusting a 400 to arrive.
  const nameOk = name.trim().length >= 2 && name.trim().length <= 40

  const createWorkspace = useMutation({
    mutationFn: () =>
      studioApi.createProject(name.trim(), description.trim(), { code: code.trim() }),
    onSuccess: (res) => {
      setActionError(null)
      setCreatedId(res.project.id)
      onCreated(res.project)
    },
  })

  // The rows. `enabled` is what keeps a form-only mount from fetching a project
  // that does not exist; `creating` is the only state that moves on its own, so
  // `ready`/`failed` stop polling and the record on screen stays the last read.
  const projectQuery = useQuery({
    queryKey: ['ai-studio', 'project', createdId ?? ''],
    queryFn: () => studioApi.getProject(createdId ?? ''),
    enabled: createdId !== null,
    refetchInterval: (query) =>
      query.state.data?.project.status === 'creating' ? 2000 : false,
  })

  const retryWorkspace = useMutation({
    mutationFn: () => workspaceApi.retryWorkspace(createdId ?? ''),
    // Write the accepted answer into the same cache key the poll reads: the 202
    // body IS the record, and putting it there repaints the rows immediately
    // instead of waiting for the next tick (and keeps `creating`, which is what
    // restarts the poll).
    onSuccess: (res) => {
      setActionError(null)
      setShowLog(false)
      setLogLines(null)
      queryClient.setQueryData(['ai-studio', 'project', createdId ?? ''], res)
    },
    onError: (err) =>
      setActionError(err instanceof Error ? err.message : String(err)),
  })

  const project: StudioProject | undefined = projectQuery.data?.project
  const steps = project?.steps ?? []
  const status = project?.status ?? 'creating'
  const failed = status === 'failed'
  const ready = status === 'ready'
  const canSubmit = nameOk && codeOk && !createWorkspace.isPending

  async function toggleLog() {
    const next = !showLog
    setShowLog(next)
    if (next && logLines === null) {
      try {
        const res = await workspaceApi.getWorkspaceLog(createdId ?? '')
        setLogLines(res.lines)
      } catch (err) {
        setActionError(err instanceof Error ? err.message : String(err))
      }
    }
  }

  const errorText =
    actionError ??
    (createWorkspace.error
      ? createWorkspace.error instanceof StudioApiError
        ? createWorkspace.error.message
        : String(createWorkspace.error)
      : null)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3">
      <Clickable
        className="absolute inset-0 bg-bg/50 backdrop-blur-xs"
        onClick={onClose}
        aria-label={i18nT('apps.aiStudio.cancel')}
      />
      <motion.div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={i18nT('apps.aiStudio.newWorkspace.title')}
        tabIndex={-1}
        initial={{ opacity: 0, y: 8, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 8, scale: 0.98 }}
        transition={{ duration: 0.18, ease: 'easeOut' }}
        className="relative w-full max-w-[460px] max-h-[90vh] overflow-auto border border-border rounded-[14px] bg-card p-6 shadow-2xl outline-hidden"
        onKeyDown={(e) => e.stopPropagation()}
        data-testid="new-ws-dialog"
      >
        <button
          type="button"
          onClick={onClose}
          disabled={createWorkspace.isPending}
          aria-label={i18nT('apps.aiStudio.cancel')}
          className="absolute top-3 right-3 p-1.5 rounded-md text-muted hover:text-text hover:bg-bg-hover cursor-pointer bg-transparent border-0 disabled:opacity-30 disabled:cursor-default"
        >
          <X size={16} />
        </button>
        <div className="text-[15px] font-semibold text-text-strong mb-4">
          {i18nT(
            createdId === null
              ? 'apps.aiStudio.newWorkspace.title'
              : 'apps.aiStudio.newWorkspace.progress_title',
          )}
        </div>

        {createdId === null ? (
          <form
            className="flex flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault()
              if (canSubmit) createWorkspace.mutate()
            }}
          >
            <label className="flex flex-col gap-1 text-[12px] text-muted">
              {i18nT('apps.aiStudio.newWorkspace.name')}
              <Input
                autoFocus
                value={name}
                maxLength={40}
                data-testid="new-ws-name"
                onChange={(e) => setName(e.target.value)}
                placeholder={i18nT('apps.aiStudio.newWorkspace.name_placeholder')}
              />
            </label>
            <label className="flex flex-col gap-1 text-[12px] text-muted">
              {i18nT('apps.aiStudio.newWorkspace.code')}
              <Input
                value={code}
                maxLength={24}
                spellCheck={false}
                data-testid="new-ws-code"
                aria-invalid={!codeOk && code.length > 0}
                onChange={(e) => setCode(e.target.value.trim().toLowerCase())}
                placeholder={i18nT('apps.aiStudio.newWorkspace.code_placeholder')}
              />
              {/* the hint is the rule text, shown once what is typed does not
                  match it — an untouched field is not worth accusing yet */}
              {!codeOk && code.length > 0 && (
                <span
                  className="text-[11px] text-err"
                  data-testid="new-ws-code-hint"
                >
                  {i18nT('apps.aiStudio.newWorkspace.code_hint')}
                </span>
              )}
            </label>
            <label className="flex flex-col gap-1 text-[12px] text-muted">
              {i18nT('apps.aiStudio.newWorkspace.description')}
              <textarea
                value={description}
                maxLength={2000}
                rows={3}
                data-testid="new-ws-desc"
                onChange={(e) => setDescription(e.target.value)}
                placeholder={i18nT('apps.aiStudio.newWorkspace.description_placeholder')}
                className="w-full resize-none rounded-md border border-border bg-bg px-2.5 py-2 text-[13px] text-text outline-none focus:border-accent"
              />
            </label>
            <ReadOnlyField
              label={i18nT('apps.aiStudio.newWorkspace.template')}
              value={TEMPLATE_LABEL}
              testId="new-ws-template"
            />
            <ReadOnlyField
              label={i18nT('apps.aiStudio.newWorkspace.staff_id')}
              value={staffId}
              testId="new-ws-staff"
            />
            {errorText && <ErrorNotice message={errorText} askAgent={false} />}
            <div className="flex justify-end gap-2 mt-1">
              <Btn type="button" onClick={onClose} disabled={createWorkspace.isPending}>
                {i18nT('apps.aiStudio.cancel')}
              </Btn>
              <Btn type="submit" primary disabled={!canSubmit} data-testid="new-ws-submit">
                {createWorkspace.isPending ? (
                  <Loader2 size={12} className="shrink-0 animate-spin motion-reduce:animate-none" />
                ) : null}
                {i18nT('apps.aiStudio.newWorkspace.create')}
              </Btn>
            </div>
          </form>
        ) : (
          <div className="flex flex-col gap-3">
            <div className="text-[12px] text-muted" data-testid="new-ws-project">
              {project?.name ?? createdId}
            </div>
            <ol className="flex flex-col gap-1.5" data-testid="new-ws-steps">
              {steps.map((step, index) => (
                <li
                  key={`${index}-${step.name}`}
                  data-testid={`new-ws-step-${index}`}
                  className="flex flex-col gap-1"
                >
                  <div className="flex items-center gap-2 text-[12.5px]">
                    <StepIcon state={step.state} />
                    <span
                      className={
                        step.state === 'failed'
                          ? 'text-err'
                          : step.state === 'pending'
                            ? 'text-muted'
                            : 'text-text'
                      }
                    >
                      {/* the backend's step name, verbatim (it is data, and the
                          RFC pins these strings as the验收 wording) */}
                      {step.name}
                    </span>
                    <span className="text-[11px] text-muted">{i18nT(STATE_TEXT[step.state])}</span>
                  </div>
                  {/* the failing row carries the message; the record's own
                      `message` is the same text, so read whichever is set — a
                      backend that only fills the record still shows something */}
                  {step.state === 'failed' && (step.message || project?.message) && (
                    <pre
                      data-testid="new-ws-step-error"
                      className="ml-5 max-h-[160px] overflow-auto rounded-md border border-border bg-bg px-2 py-1.5 text-[10.5px] leading-[1.45] text-err whitespace-pre-wrap break-all"
                    >
                      {step.message || project?.message}
                    </pre>
                  )}
                </li>
              ))}
            </ol>

            {errorText && (
              <div className="text-[11px] text-err" data-testid="new-ws-action-error">
                {errorText}
              </div>
            )}

            {failed && (
              <div className="flex items-center gap-2">
                <Btn
                  onClick={() => retryWorkspace.mutate()}
                  disabled={retryWorkspace.isPending}
                  data-testid="new-ws-retry"
                >
                  {retryWorkspace.isPending ? (
                    <Loader2 size={12} className="shrink-0 animate-spin motion-reduce:animate-none" />
                  ) : null}
                  {i18nT('apps.aiStudio.newWorkspace.retry')}
                </Btn>
                <Clickable
                  onClick={toggleLog}
                  data-testid="new-ws-log-toggle"
                  className="text-[11px] text-muted hover:text-text cursor-pointer shrink-0 whitespace-nowrap"
                >
                  {showLog
                    ? i18nT('apps.aiStudio.newWorkspace.hide_log')
                    : i18nT('apps.aiStudio.newWorkspace.view_log')}
                </Clickable>
              </div>
            )}
            {showLog && (
              <pre
                data-testid="new-ws-log"
                className="max-h-[220px] overflow-auto rounded-md border border-border bg-bg px-2 py-1.5 text-[10.5px] leading-[1.45] text-muted whitespace-pre-wrap break-all"
              >
                {logLines === null
                  ? i18nT('apps.aiStudio.newWorkspace.log_loading')
                  : logLines.join('\n') || i18nT('apps.aiStudio.newWorkspace.log_empty')}
              </pre>
            )}

            <div className="flex justify-end gap-2 mt-1">
              <Btn onClick={onClose}>{i18nT('apps.aiStudio.newWorkspace.close')}</Btn>
              {/* only once the workspace actually exists on disk: entering it
                  before the clone lands would open a project with no docs */}
              {ready && (
                <Btn
                  primary
                  data-testid="new-ws-enter"
                  onClick={() =>
                    navigate(`/workspaces/${encodeURIComponent(createdId)}/ai-studio`)
                  }
                >
                  {i18nT('apps.aiStudio.newWorkspace.enter')}
                </Btn>
              )}
            </div>
          </div>
        )}
      </motion.div>
    </div>
  )
}

/** A value the operator cannot edit (the template this iteration has, and the
 * 工号 that came from the login). Rendered as text, not a disabled input: a
 * disabled field reads as "you could change this if you were allowed to". */
function ReadOnlyField({
  label,
  value,
  testId,
}: {
  label: string
  value: string
  testId: string
}) {
  return (
    <div className="flex items-center justify-between gap-2 text-[12px] text-muted">
      <span>{label}</span>
      <span
        data-testid={testId}
        title={value}
        className="text-text truncate font-mono text-[12px]"
      >
        {value || '—'}
      </span>
    </div>
  )
}
