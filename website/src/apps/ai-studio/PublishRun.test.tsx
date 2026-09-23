// The inline publish run (08-publish-app T6 / §二 A3–A8, 场景 B, §三 幂等与
// 并发): clicking a row's button fires POST /publish, the row honestly reads
// 发布中, the records query polls until the success record lands — then the
// result strip appears (发布成功, the form badge, the serving-url link and
// the release-job link, both opening in a NEW tab) and the hash rule writes
// the row back to 已发布 with its button gone from the DOM. A failed trigger
// shows 发布失败 plus the reason (a failed job never writes a record, so the
// response is the reason's only carrier), and a 409 keeps exactly one 发布中
// with no error notice.
// studioApi/publishApi are mocked per test file (see testUtils.tsx note).
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const api = vi.hoisted(() => ({
  getProject: vi.fn(),
  saveDoc: vi.fn(),
  saveDraft: vi.fn(async () => ({ ok: true })),
  listDraftDocs: vi.fn(async () => ({ drafts: [] })),
  listDraftVersions: vi.fn(async () => ({ versions: [] })),
  listVersions: vi.fn(async () => ({ versions: [] })),
  listRecords: vi.fn(),
  preview: vi.fn(),
  trigger: vi.fn(),
}))
vi.mock('./studioApi', async () => {
  const actual = await vi.importActual('./studioApi')
  return { ...actual, studioApi: api, publishApi: api }
})
vi.mock('../../app-sdk/ChatEmbed', () => ({
  default: () => <div data-testid="chat-embed-stub" />,
}))

import AiStudioPage from './AiStudioPage'
import { StudioApiError } from './studioApi'
import { TEST_DOCS, TEST_PROJECT, renderStudio } from './testUtils'

const HASH_V3 = 'c333333333333333333333333333333333333333'
const HASH_V2 = 'c222222222222222222222222222222222222222'
// The serving url the backend's record carries — the domain template verbatim
// (08 §〇): 版本号-应用名-工号.gb10.jereh-pe.cn.
const URL_V3 = 'https://v3-crm-14409.gb10.jereh-pe.cn'

const RECORD_V2 = {
  deploymentId: 'd2',
  version: 'v2',
  commitHash: HASH_V2,
  form: 'full',
  status: 'success',
  url: 'https://v2-crm-14409.gb10.jereh-pe.cn',
  ts: 20,
  requirementVersion: 'r1',
  jiraTaskIds: ['ACP-1'],
}
const RECORD_V3 = {
  deploymentId: 'job-9',
  version: 'v3',
  commitHash: HASH_V3,
  form: 'full',
  status: 'success',
  url: URL_V3,
  ts: 30,
  requirementVersion: 'r1',
  jiraTaskIds: ['ACP-1'],
}

const VERSIONS = [
  { version: 'v3', commitHash: HASH_V3, time: 3 },
  { version: 'v2', commitHash: HASH_V2, time: 2 },
]

beforeEach(() => {
  vi.clearAllMocks()
  api.getProject.mockResolvedValue({ project: TEST_PROJECT, docs: TEST_DOCS })
  api.listVersions.mockResolvedValue({ versions: VERSIONS })
  // v2 is the latest published; v3 has nothing yet — the pre-publish state.
  api.listRecords.mockResolvedValue({ records: [RECORD_V2] })
  api.preview.mockResolvedValue({ form: 'full', reason: '完整版通过验收（git tag 标注为完整版）' })
})

async function openPublish(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByTestId('ai-studio-publish-entry'))
  await screen.findByTestId('ai-studio-publish-version-list')
}

/** listRecords whose FIRST call returns `first` and every call after that
 * `later` — how a test plays the record store advancing under the poll. */
function recordsThen(first: unknown[], later: unknown[]) {
  let n = 0
  api.listRecords.mockImplementation(async () => {
    const r = n === 0 ? first : later
    n += 1
    return { records: r }
  })
}

describe('inline publish run (T6)', () => {
  it('A3: a click fires POST /publish; BOTH state and status read 发布中 and the job-id link opens in a new tab', async () => {
    let resolveTrigger: (v: { deploymentId: string }) => void = () => {}
    api.trigger.mockReturnValue(new Promise((r) => (resolveTrigger = r)))
    const user = userEvent.setup()
    renderStudio(<AiStudioPage />)
    await openPublish(user)
    await user.click(screen.getByTestId('ai-studio-publish-btn-v3'))
    // the request: (project, version, the row's hash) — B2's body
    expect(api.trigger).toHaveBeenCalledWith(TEST_PROJECT.id, 'v3', HASH_V3)
    // the honest 发布中 while the trigger is in flight: the lifecycle state
    // AND the action-result text, in separate elements (§〇-1 分工)
    const row = screen.getByTestId('ai-studio-publish-version-row-v3')
    expect(within(row).getByTestId('ai-studio-publish-version-state')).toHaveTextContent('Publishing')
    expect(within(row).getByTestId('ai-studio-publish-status-v3')).toHaveTextContent('Publishing')
    resolveTrigger({ deploymentId: 'job-9' })
    // the release-job id link appears, pointing at /release-jobs/<发布号>
    // and opening in a NEW tab (§〇-1 链接列)
    const idLink = await within(row).findByTestId('ai-studio-publish-id-v3')
    expect(idLink).toHaveAttribute('href', '/release-jobs/job-9')
    expect(idLink).toHaveAttribute('target', '_blank')
  })

  it('A4–A8: the success record landing settles 发布成功, shows badge + url link (new tab), flips the row to 已发布 and removes its button', async () => {
    api.trigger.mockResolvedValue({ deploymentId: 'job-9' })
    // the invalidate refetch still misses (the job runs); the 2s poll lands
    // the record — the settle is the RECORD's arrival, never the response.
    recordsThen([RECORD_V2], [RECORD_V3, RECORD_V2])
    const user = userEvent.setup()
    renderStudio(<AiStudioPage />)
    await openPublish(user)
    await user.click(screen.getByTestId('ai-studio-publish-btn-v3'))
    await waitFor(
      () =>
        expect(
          within(screen.getByTestId('ai-studio-publish-version-row-v3')).getByTestId(
            'ai-studio-publish-status-v3',
          ),
        ).toHaveTextContent('Publish succeeded'),
      { timeout: 8000 },
    )
    const row = screen.getByTestId('ai-studio-publish-version-row-v3')
    // A5: the form badge, from the release record's form
    expect(within(row).getByTestId('ai-studio-publish-form-badge-v3')).toHaveTextContent('Full')
    // A6: the url link — href verbatim the record's serving url, new tab
    const link = within(row).getByTestId('ai-studio-publish-url-v3')
    expect(link).toHaveAttribute('href', URL_V3)
    expect(link).toHaveAttribute('target', '_blank')
    // A8: the row flipped to 已发布 and its button left the DOM (its hash IS
    // the newest success record's now).
    expect(within(row).getByTestId('ai-studio-publish-version-state')).toHaveTextContent('Published')
    expect(within(row).queryByTestId('ai-studio-publish-btn-v3')).not.toBeInTheDocument()
    // D3 by the same hash rule: v2 is now published-but-not-latest — its
    // own record keeps it 已发布 (its state is unchanged by this run), while
    // its button comes back (a rollback re-publish is allowed).
    const v2 = screen.getByTestId('ai-studio-publish-version-row-v2')
    expect(within(v2).getByTestId('ai-studio-publish-btn-v2')).toBeInTheDocument()
    expect(within(v2).getByTestId('ai-studio-publish-version-state')).toHaveTextContent('Published')
    // A7: the job-id link survives the settle and still opens the job page
    expect(within(row).getByTestId('ai-studio-publish-id-v3')).toHaveAttribute('href', '/release-jobs/job-9')
  }, 15000)

  it('场景 B: a demo release badges the record form (演示版 reads Demo in the en catalog)', async () => {
    api.trigger.mockResolvedValue({ deploymentId: 'job-9' })
    api.preview.mockResolvedValue({
      form: 'demo',
      reason: '完整版未通过验收（git tag 标注为演示版），仅可发布演示版',
    })
    recordsThen([RECORD_V2], [{ ...RECORD_V3, form: 'demo' }, RECORD_V2])
    const user = userEvent.setup()
    renderStudio(<AiStudioPage />)
    await openPublish(user)
    await user.click(screen.getByTestId('ai-studio-publish-btn-v3'))
    await waitFor(
      () =>
        expect(
          within(screen.getByTestId('ai-studio-publish-version-row-v3')).getByTestId(
            'ai-studio-publish-form-badge-v3',
          ),
        ).toHaveTextContent('Demo'),
      { timeout: 8000 },
    )
  }, 15000)

  it('失败路径: a failed trigger shows 发布失败 with the reason and the row state reads Failed', async () => {
    api.trigger.mockResolvedValue({
      deploymentId: 'job-8',
      status: 'failed',
      reason: '构建失败：exit 1',
    })
    const user = userEvent.setup()
    renderStudio(<AiStudioPage />)
    await openPublish(user)
    await user.click(screen.getByTestId('ai-studio-publish-btn-v3'))
    const row = screen.getByTestId('ai-studio-publish-version-row-v3')
    // §三 失败路径: the status text carries BOTH 失败 and the reason.
    await waitFor(() =>
      expect(within(row).getByTestId('ai-studio-publish-status-v3')).toHaveTextContent(
        'Publish failed: 构建失败：exit 1',
      ),
    )
    // the lifecycle state reads 失败 — its own element, not the status text
    expect(within(row).getByTestId('ai-studio-publish-version-state')).toHaveTextContent('Failed')
    // the button stays (the version never published — a retry is allowed)
    expect(within(row).getByTestId('ai-studio-publish-btn-v3')).toBeEnabled()
  })

  it('并发 409: a trigger refused as in-progress keeps ONE 发布中 on the row and raises no error notice', async () => {
    // the row was not fired this visit — another session started this hash's
    // publish, so the click is refused with 409 publish_in_progress.
    api.trigger.mockRejectedValue(
      new StudioApiError(409, 'publish_in_progress', 'this hash is already publishing'),
    )
    const user = userEvent.setup()
    renderStudio(<AiStudioPage />)
    await openPublish(user)
    const row = screen.getByTestId('ai-studio-publish-version-row-v3')
    await user.click(within(row).getByTestId('ai-studio-publish-btn-v3'))
    await waitFor(() => expect(within(row).getByTestId('ai-studio-publish-status-v3')).toHaveTextContent('Publishing'))
    // ONE 发布中 is structural: one status element per row, and the state
    // chip says the same — while no error notice appears (§五 并发路径).
    expect(within(row).getAllByTestId('ai-studio-publish-status-v3')).toHaveLength(1)
    expect(within(row).getByTestId('ai-studio-publish-version-state')).toHaveTextContent('Publishing')
    expect(screen.queryByText('The publish could not be started')).not.toBeInTheDocument()
  })

  it('a failed trigger that is not a 409 surfaces through ErrorNotice and frees the row', async () => {
    api.trigger.mockRejectedValue(new StudioApiError(500, 'request_failed', 'boom'))
    const user = userEvent.setup()
    renderStudio(<AiStudioPage />)
    await openPublish(user)
    const row = screen.getByTestId('ai-studio-publish-version-row-v3')
    await user.click(within(row).getByTestId('ai-studio-publish-btn-v3'))
    expect(await screen.findByText('boom')).toBeInTheDocument()
    expect(within(row).getByTestId('ai-studio-publish-version-state')).toHaveTextContent('Unpublished')
    expect(within(row).getByTestId('ai-studio-publish-btn-v3')).toBeEnabled()
  })

  it('D1: the latest-published row shows NO button but still links its serving url and job id (record-sourced)', async () => {
    api.listRecords.mockResolvedValue({ records: [RECORD_V3, RECORD_V2] })
    const user = userEvent.setup()
    renderStudio(<AiStudioPage />)
    await openPublish(user)
    const row = screen.getByTestId('ai-studio-publish-version-row-v3')
    expect(within(row).queryByTestId('ai-studio-publish-btn-v3')).not.toBeInTheDocument()
    // D1/A7: the published row keeps its url and job-id links even without
    // a run this visit — both come off the success record.
    expect(within(row).getByTestId('ai-studio-publish-url-v3')).toHaveAttribute('href', URL_V3)
    expect(within(row).getByTestId('ai-studio-publish-id-v3')).toHaveAttribute('href', '/release-jobs/job-9')
    expect(within(row).getByTestId('ai-studio-publish-form-badge-v3')).toHaveTextContent('Full')
  })

  it('a running row never shows a serving url or badge — those are release facts, not job facts', async () => {
    api.trigger.mockReturnValue(new Promise(() => {})) // never resolves: stays running
    const user = userEvent.setup()
    renderStudio(<AiStudioPage />)
    await openPublish(user)
    await user.click(screen.getByTestId('ai-studio-publish-btn-v3'))
    const row = screen.getByTestId('ai-studio-publish-version-row-v3')
    expect(within(row).getByTestId('ai-studio-publish-status-v3')).toHaveTextContent('Publishing')
    expect(within(row).queryByTestId('ai-studio-publish-url-v3')).not.toBeInTheDocument()
    expect(within(row).queryByTestId('ai-studio-publish-form-badge-v3')).not.toBeInTheDocument()
  })
})
