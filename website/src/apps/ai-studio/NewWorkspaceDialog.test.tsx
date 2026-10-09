// The 新建工作区 dialog (ACP-2085). Like DevServerControl.test.tsx, the fake api
// is the whole fixture: the dialog owns no step state of its own — the rows are
// `GET /projects/{id}` — so each scenario is one stubbed read plus the calls the
// buttons make. Tests mock ./studioApi, mount through renderStudio, assert what
// the screen says (English catalog: tests pin en; the step names and failure text
// are backend data and asserted in Chinese, because verbatim is the contract).
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const createProject = vi.hoisted(() => vi.fn())
const getProject = vi.hoisted(() => vi.fn())
const listProjects = vi.hoisted(() => vi.fn())
const retryWorkspace = vi.hoisted(() => vi.fn())
const getWorkspaceLog = vi.hoisted(() => vi.fn())
const deleteProject = vi.hoisted(() => vi.fn())
vi.mock('./studioApi', async () => {
  const actual = await vi.importActual('./studioApi')
  return {
    ...actual,
    studioApi: { createProject, getProject, listProjects },
    workspaceApi: { retryWorkspace, getWorkspaceLog, deleteProject },
  }
})

import NewWorkspaceDialog from './NewWorkspaceDialog'
import ProjectsListPage from './ProjectsListPage'
import type { StudioProject, StudioWorkspaceStep } from './studioApi'
import { renderStudio } from './testUtils'
import ZH_CATALOG from '../../i18n/locales/zh-CN.json'

/** The four steps exactly as `workspace.STEPS` writes them — Chinese by contract,
 * which is why the assertions match on them: the dialog shows the backend's
 * words, not its own. */
const STEP_NAMES = ['克隆模板', '建个人仓', '推送', '启动开发服务器']

function step(name: string, state: StudioWorkspaceStep['state'], message: string | null = null): StudioWorkspaceStep {
  return { name, state, message }
}

function steps(states: StudioWorkspaceStep['state'][]): StudioWorkspaceStep[] {
  return STEP_NAMES.map((name, i) => step(name, states[i] ?? 'pending'))
}

function wsProject(over: Partial<StudioProject> = {}): StudioProject {
  return {
    id: 'sbgl',
    name: '设备管理',
    description: '',
    createdAt: Date.now() / 1000,
    code: 'sbgl',
    template: 'https://bitbucket.jereh.cn/scm/~14409/webapp-template.git',
    status: 'creating',
    failedStep: null,
    message: null,
    workspaceDir: null,
    repoUrl: null,
    steps: steps(['running', 'pending', 'pending', 'pending']),
    ...over,
  }
}

function mountDialog(over: Partial<{ staffId: string; initialProjectId: string | null }> = {}) {
  const onCreated = vi.fn()
  renderStudio(
    <NewWorkspaceDialog
      staffId={over.staffId ?? '14409'}
      initialProjectId={over.initialProjectId ?? null}
      onClose={vi.fn()}
      onCreated={onCreated}
    />,
  )
  return onCreated
}

async function openForm() {
  mountDialog()
  await screen.findByTestId('new-ws-dialog')
}

beforeEach(() => {
  vi.clearAllMocks()
  createProject.mockResolvedValue({ project: wsProject() })
  getProject.mockResolvedValue({ project: wsProject(), docs: [] })
  listProjects.mockResolvedValue({ projects: [], staffId: '14409' })
  retryWorkspace.mockResolvedValue({
    project: wsProject({ steps: steps(['running', 'pending', 'pending', 'pending']) }),
  })
  getWorkspaceLog.mockResolvedValue({
    lines: ["Cloning into 'sbgl'…", 'fatal: could not read Remote'],
  })
  deleteProject.mockResolvedValue({
    deleted: true,
    trash: '/workspaces/.trash/sbgl-20261009-150000',
    recordTrash: '/crew/crew/apps/ai_studio/projects/.trash/sbgl-20261009-150000',
  })
})

describe('NewWorkspaceDialog form', () => {
  it('shows the read-only template and the 工号 from the list response', async () => {
    await openForm()
    expect(screen.getByTestId('new-ws-template')).toHaveTextContent('webapp-template')
    expect(screen.getByTestId('new-ws-staff')).toHaveTextContent('14409')
  })

  it('a bad code disables 创建 and says why, in the RFC wording', async () => {
    const user = userEvent.setup()
    await openForm()
    await user.type(screen.getByTestId('new-ws-name'), '设备管理')
    // underscore survives the field's case-fold, so this really is an invalid
    // code rather than one the input would silently repair into a valid one
    await user.type(screen.getByTestId('new-ws-code'), 'SB_GL')
    expect(screen.getByTestId('new-ws-code')).toHaveValue('sb_gl')
    expect(screen.getByTestId('new-ws-submit')).toBeDisabled()
    expect(screen.getByTestId('new-ws-code-hint')).toHaveTextContent(
      'The code takes lowercase letters, digits and hyphens only',
    )
  })

  it('a 1-character name is not enough either', async () => {
    const user = userEvent.setup()
    await openForm()
    await user.type(screen.getByTestId('new-ws-name'), 'x')
    await user.type(screen.getByTestId('new-ws-code'), 'sbgl')
    expect(screen.getByTestId('new-ws-submit')).toBeDisabled()
  })

  it('a good code and name enable 创建, which posts the code', async () => {
    const user = userEvent.setup()
    const onCreated = mountDialog()
    await screen.findByTestId('new-ws-dialog')
    await user.type(screen.getByTestId('new-ws-name'), '设备管理')
    await user.type(screen.getByTestId('new-ws-code'), 'sbgl')
    await user.type(screen.getByTestId('new-ws-desc'), '设备台账')
    const submit = screen.getByTestId('new-ws-submit')
    await waitFor(() => expect(submit).toBeEnabled())
    await user.click(submit)
    expect(createProject).toHaveBeenCalledWith('设备管理', '设备台账', { code: 'sbgl' })
    await waitFor(() => expect(onCreated).toHaveBeenCalled())
  })

  it('a refused create keeps the dialog on the form and names the failure', async () => {
    const { StudioApiError } = await import('./studioApi')
    createProject.mockRejectedValue(new StudioApiError(409, 'code_taken', '代号已被占用'))
    const user = userEvent.setup()
    await openForm()
    await user.type(screen.getByTestId('new-ws-name'), '设备管理')
    await user.type(screen.getByTestId('new-ws-code'), 'sbgl')
    await user.click(screen.getByTestId('new-ws-submit'))
    expect(await screen.findByText('代号已被占用')).toBeInTheDocument()
    // still the form: the operator fixes the code, they do not lose the dialog
    expect(screen.getByTestId('new-ws-code')).toBeInTheDocument()
    expect(screen.queryByTestId('new-ws-steps')).not.toBeInTheDocument()
  })
})

describe('NewWorkspaceDialog progress', () => {
  it('after the create it shows the four steps, in the backend order and words', async () => {
    const user = userEvent.setup()
    mountDialog()
    await screen.findByTestId('new-ws-dialog')
    await user.type(screen.getByTestId('new-ws-name'), '设备管理')
    await user.type(screen.getByTestId('new-ws-code'), 'sbgl')
    await user.click(screen.getByTestId('new-ws-submit'))
    await screen.findByTestId('new-ws-step-0')
    expect(screen.getByTestId('new-ws-step-0')).toHaveTextContent('克隆模板')
    expect(screen.getByTestId('new-ws-step-1')).toHaveTextContent('建个人仓')
    expect(screen.getByTestId('new-ws-step-2')).toHaveTextContent('推送')
    expect(screen.getByTestId('new-ws-step-3')).toHaveTextContent('启动开发服务器')
    // the rows come from the record, not from anything the client invented
    expect(getProject).toHaveBeenCalledWith('sbgl')
    // not ready → no way in yet
    expect(screen.queryByTestId('new-ws-enter')).not.toBeInTheDocument()
  })

  it('a failed step shows its message verbatim and 重试这一步', async () => {
    const message = "建个人仓失败：fatal: could not read Remote 'origin'"
    getProject.mockResolvedValue({
      project: wsProject({
        status: 'failed',
        failedStep: '建个人仓',
        message,
        steps: steps(['done', 'failed', 'pending', 'pending']).map((s) =>
          s.name === '建个人仓' ? step(s.name, 'failed', message) : s,
        ),
      }),
      docs: [],
    })
    mountDialog({ initialProjectId: 'sbgl' })
    // VERBATIM: the tail of the failing command is the only place the real error
    // exists, so nothing here may re-templat it or trim it.
    const err = await screen.findByTestId('new-ws-step-error')
    expect(err.textContent).toBe(message)
    expect(screen.getByTestId('new-ws-retry')).toBeInTheDocument()
  })

  it('clicking 重试这一步 calls retry', async () => {
    getProject.mockResolvedValue({
      project: wsProject({
        status: 'failed',
        failedStep: '推送',
        message: '推送失败：remote rejected',
        steps: steps(['done', 'done', 'failed', 'pending']),
      }),
      docs: [],
    })
    const user = userEvent.setup()
    mountDialog({ initialProjectId: 'sbgl' })
    await screen.findByTestId('new-ws-retry')
    await user.click(screen.getByTestId('new-ws-retry'))
    expect(retryWorkspace).toHaveBeenCalledWith('sbgl')
  })

  it('a retry the backend refuses is shown, not swallowed', async () => {
    const { StudioApiError } = await import('./studioApi')
    getProject.mockResolvedValue({
      project: wsProject({
        status: 'failed',
        failedStep: '推送',
        message: '推送失败：remote rejected',
        steps: steps(['done', 'done', 'failed', 'pending']),
      }),
      docs: [],
    })
    retryWorkspace.mockRejectedValue(new StudioApiError(409, 'not_failed', '当前不是失败状态'))
    const user = userEvent.setup()
    mountDialog({ initialProjectId: 'sbgl' })
    // the record says failed, so the button renders; the 409 means someone else
    // already moved the job — the operator has to see that, not a dead button
    await user.click(await screen.findByTestId('new-ws-retry'))
    expect(await screen.findByTestId('new-ws-action-error')).toHaveTextContent('当前不是失败状态')
  })

  it('查看日志 pulls the derive log once', async () => {
    getProject.mockResolvedValue({
      project: wsProject({
        status: 'failed',
        failedStep: '克隆模板',
        message: '克隆模板失败：fatal',
        steps: steps(['failed', 'pending', 'pending', 'pending']),
      }),
      docs: [],
    })
    const user = userEvent.setup()
    mountDialog({ initialProjectId: 'sbgl' })
    await user.click(await screen.findByTestId('new-ws-log-toggle'))
    expect(await screen.findByTestId('new-ws-log')).toHaveTextContent('could not read Remote')
    expect(getWorkspaceLog).toHaveBeenCalledWith('sbgl')
  })

  it('all done shows 进入工作区 and no retry', async () => {
    getProject.mockResolvedValue({
      project: wsProject({
        status: 'ready',
        workspaceDir: '/x/sbgl',
        repoUrl: 'https://bitbucket/jereh/sbgl.git',
        steps: steps(['done', 'done', 'done', 'done']),
      }),
      docs: [],
    })
    mountDialog({ initialProjectId: 'sbgl' })
    const enter = await screen.findByTestId('new-ws-enter')
    expect(enter).toHaveTextContent('Open workspace')
    expect(screen.queryByTestId('new-ws-retry')).not.toBeInTheDocument()
  })

  it('a workspace still creating reads its record on mount', async () => {
    getProject.mockResolvedValue({ project: wsProject(), docs: [] })
    mountDialog({ initialProjectId: 'sbgl' })
    await screen.findByTestId('new-ws-step-0')
    // one read on mount proves the dialog reads rather than guesses; the 2s tick
    // is the same refetchInterval DevServerControl established, and waiting a
    // wall-clock second to watch it fire is exactly the flake that doc forbids
    await waitFor(() => expect(getProject).toHaveBeenCalledWith('sbgl'))
  })
})

describe('ProjectsListPage with the workspace dialog', () => {
  it('the header button opens the new-workspace form', async () => {
    const user = userEvent.setup()
    renderStudio(<ProjectsListPage />, '/workspaces')
    await user.click(await screen.findByTestId('new-ws-open'))
    expect(await screen.findByTestId('new-ws-dialog')).toBeInTheDocument()
    expect(screen.getByTestId('new-ws-staff')).toHaveTextContent('14409')
  })

  it('a creating card says 创建中 and reopens the progress, not the workbench', async () => {
    listProjects.mockResolvedValue({
      projects: [wsProject({ status: 'creating' })],
      staffId: '14409',
    })
    const user = userEvent.setup()
    renderStudio(<ProjectsListPage />, '/workspaces')
    const status = await screen.findByTestId('project-status-sbgl')
    expect(status).toHaveTextContent('Creating…')
    await user.click(screen.getByTestId('project-card-sbgl'))
    // the progress rows, not a workbench: a half-derived repo has no docs to show
    expect(await screen.findByTestId('new-ws-step-0')).toBeInTheDocument()
  })

  it('a failed card says 创建失败 in the failure colour', async () => {
    listProjects.mockResolvedValue({
      projects: [wsProject({ status: 'failed', failedStep: '推送', message: '推送失败：x' })],
      staffId: '14409',
    })
    renderStudio(<ProjectsListPage />, '/workspaces')
    const status = await screen.findByTestId('project-status-sbgl')
    expect(status).toHaveTextContent('Create failed')
    expect(status.className).toContain('text-err')
  })

  it('a ready workspace is a plain card: no status word', async () => {
    listProjects.mockResolvedValue({
      projects: [wsProject({ status: 'ready', steps: steps(['done', 'done', 'done', 'done']) })],
      staffId: '14409',
    })
    renderStudio(<ProjectsListPage />, '/workspaces')
    await screen.findByTestId('project-card-sbgl')
    expect(screen.queryByTestId('project-status-sbgl')).not.toBeInTheDocument()
  })

  it('a project with no code (created before this change) renders unchanged', async () => {
    listProjects.mockResolvedValue({
      projects: [{ id: 'crm-p261008', name: '老项目', description: '', createdAt: 1 }],
      staffId: '',
    })
    renderStudio(<ProjectsListPage />, '/workspaces')
    const card = await screen.findByTestId('project-card-crm-p261008')
    expect(card).toHaveTextContent('老项目')
    expect(screen.queryByTestId('project-status-crm-p261008')).not.toBeInTheDocument()
  })

  it('删除 asks first, and only the answer 删除 sends the request', async () => {
    // ACP-2206. One case holds the whole contract because the two halves are one
    // decision: the button must NOT be the delete, and the dialog's own button
    // must be. So the click that should do nothing is asserted before the click
    // that should, against the same call count — which is exactly the pair a
    // future "simplify by deleting the confirm" change would break.
    //
    // The copy is the RFC's, pinned in Chinese: the dialog's job is to say what
    // is being lost (the workspace goes to the trash, the remote repo stays),
    // and a re-worded sentence silently changes what an operator agreed to. The
    // rendered dialog is English (the suite is pinned to `en`), so the pinned
    // sentence is asserted where it is authored — the zh-CN catalog — and the
    // rendered one only that it carries the project's name.
    expect(ZH_CATALOG.apps.aiStudio.projectDelete.confirm).toBe(
      '删除后工作区移到回收站，远端仓库保留。确定删除「{{name}}」吗？',
    )
    listProjects.mockResolvedValue({
      projects: [wsProject({ status: 'ready', steps: steps(['done', 'done', 'done', 'done']) })],
      staffId: '14409',
    })
    // the fake store drops the project when the delete lands, so the refetch the
    // invalidation triggers afterwards reads an empty list — the card vanishing
    // is then the backend's answer, not a second mock the test flipped by hand
    deleteProject.mockImplementation(async () => {
      listProjects.mockResolvedValue({ projects: [], staffId: '14409' })
      return { deleted: true, trash: '/workspaces/.trash/sbgl-20261009-150000' }
    })
    const user = userEvent.setup()
    renderStudio(<ProjectsListPage />, '/workspaces')
    await user.click(await screen.findByTestId('project-delete-sbgl'))

    const dialog = await screen.findByRole('dialog')
    // the name is interpolated INTO the sentence (rendered in the suite's
    // language), so it is matched as part of the line rather than as a line
    expect(within(dialog).getByText(/设备管理/)).toBeInTheDocument()
    // the card's own 删除 is a button INSIDE the clickable card: without the
    // propagation guard this same click would also have opened the workbench
    expect(screen.queryByTestId('new-ws-dialog')).not.toBeInTheDocument()

    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(deleteProject).not.toHaveBeenCalled()
    expect(screen.getByTestId('project-card-sbgl')).toBeInTheDocument()

    await user.click(screen.getByTestId('project-delete-sbgl'))
    const again = await screen.findByRole('dialog')
    await user.click(within(again).getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(deleteProject).toHaveBeenCalledWith('sbgl'))
    await waitFor(() => expect(screen.queryByTestId('project-card-sbgl')).not.toBeInTheDocument())
  })
})
