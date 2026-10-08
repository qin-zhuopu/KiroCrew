// The publish version list (08-publish-app T5 / §〇-1): the Releases tab
// renders the project's versions as rows, each with a state, a form reason,
// and an inline publish button whose rendering follows the hash rule —
// equal to the latest published hash means NO button (not a disabled one),
// any other hash (including an older published one, D3) renders it.
// studioApi/publishApi are mocked per test file (see testUtils.tsx note).
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, within } from '@testing-library/react'
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
  // ACP-2085 S2: the workbench's chat column opens its 需求会话 through this api
  // before mounting the embed. The stub above already keeps ChatEmbed off the
  // network; this only answers the open so the column resolves.
  ensureReqSession: vi.fn(async (id: string) => ({ slotKey: `ai-studio-req-${id}`, created: false })),
}))
vi.mock('./studioApi', async () => {
  const actual = await vi.importActual('./studioApi')
  return { ...actual, studioApi: api, publishApi: api }
})
vi.mock('../../app-sdk/ChatEmbed', () => ({
  default: () => <div data-testid="chat-embed-stub" />,
}))

import AiStudioPage from './AiStudioPage'
import { TEST_DOCS, TEST_PROJECT, renderStudio } from './testUtils'

// v2 is the latest published version; v1 is an older published version and
// v3 was never published — that trio exercises every branch of the hash rule.
const VERSIONS = [
  { version: 'v3', commitHash: 'c333333333333333333333333333333333333333', time: 3 },
  { version: 'v2', commitHash: 'c222222222222222222222222222222222222222', time: 2 },
  { version: 'v1', commitHash: 'c111111111111111111111111111111111111111', time: 1 },
]

const REASON = { full: '完整版通过验收（git tag 标注为完整版）', demo: '完整版未通过验收（git tag 标注为演示版），仅可发布演示版' }

beforeEach(() => {
  vi.clearAllMocks()
  api.getProject.mockResolvedValue({ project: TEST_PROJECT, docs: TEST_DOCS })
  api.listVersions.mockResolvedValue({ versions: VERSIONS })
  api.listRecords.mockResolvedValue({
    records: [
      // newest first, as the backend sorts; the newest success carries the
      // "latest published hash" — v2's
      { deploymentId: 'd2', version: 'v2', commitHash: 'c222222222222222222222222222222222222222', form: 'full', status: 'success', url: '', ts: 20, requirementVersion: '', jiraTaskIds: [] },
      { deploymentId: 'd1', version: 'v1', commitHash: 'c111111111111111111111111111111111111111', form: 'demo', status: 'success', url: '', ts: 10, requirementVersion: '', jiraTaskIds: [] },
    ],
  })
  api.preview.mockImplementation(async (_id: string, version: string) => ({
    form: version === 'v3' ? 'full' : 'demo',
    reason: REASON[version === 'v3' ? 'full' : 'demo'],
  }))
  api.trigger.mockResolvedValue({ deploymentId: 'd9' })
})

async function openPublish(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByTestId('ai-studio-publish-entry'))
  await screen.findByTestId('ai-studio-publish-version-list')
}

describe('publish version list', () => {
  it('A1: the publish tab opens the version list; every version is a row, no picker', async () => {
    const user = userEvent.setup()
    renderStudio(<AiStudioPage />)
    await openPublish(user)
    for (const v of VERSIONS) {
      expect(screen.getByTestId(`ai-studio-publish-version-row-${v.version}`)).toBeInTheDocument()
      expect(screen.getByTestId(`ai-studio-publish-version-row-${v.version}`))
        .toHaveTextContent(v.version)
    }
    // the list is the whole input surface: no select, no textbox anywhere in it
    const list = screen.getByTestId('ai-studio-publish-version-list')
    expect(within(list).queryByRole('combobox')).not.toBeInTheDocument()
    expect(within(list).queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('A2/D1: hash rule — the latest published row has NO button and reads Published; unpublished and older rows render one', async () => {
    const user = userEvent.setup()
    renderStudio(<AiStudioPage />)
    await openPublish(user)
    // D1: v2 IS the latest published hash → button not in the DOM, state 已发布
    const v2 = screen.getByTestId('ai-studio-publish-version-row-v2')
    expect(within(v2).queryByTestId('ai-studio-publish-btn-v2')).not.toBeInTheDocument()
    expect(within(v2).getByTestId('ai-studio-publish-version-state')).toHaveTextContent('Published')
    // A2: v3 was never published → button + Unpublished
    const v3 = screen.getByTestId('ai-studio-publish-version-row-v3')
    expect(within(v3).getByTestId('ai-studio-publish-btn-v3')).toBeInTheDocument()
    expect(within(v3).getByTestId('ai-studio-publish-version-state')).toHaveTextContent('Unpublished')
    // D3: v1's hash was published but is NOT the latest → the button still renders
    expect(within(screen.getByTestId('ai-studio-publish-version-row-v1'))
      .getByTestId('ai-studio-publish-btn-v1')).toBeInTheDocument()
  })

  it('the state and the reason are separate elements (B1 reason rides the row)', async () => {
    const user = userEvent.setup()
    renderStudio(<AiStudioPage />)
    await openPublish(user)
    const v3 = screen.getByTestId('ai-studio-publish-version-row-v3')
    const state = within(v3).getByTestId('ai-studio-publish-version-state')
    const reason = within(v3).getByTestId('ai-studio-publish-reason-v3')
    expect(state).toHaveTextContent('Unpublished')
    expect(reason).toHaveTextContent('完整版通过验收')
    expect(state).not.toBe(reason)
  })

  it('C1: a rejected version renders no button and shows the rejection reason as Unpublished', async () => {
    api.preview.mockResolvedValue({ form: 'rejected', reason: '验收未通过：版本 v3 无 git tag 标注' })
    const user = userEvent.setup()
    renderStudio(<AiStudioPage />)
    await openPublish(user)
    const v3 = screen.getByTestId('ai-studio-publish-version-row-v3')
    expect(within(v3).queryByTestId('ai-studio-publish-btn-v3')).not.toBeInTheDocument()
    expect(within(v3).getByTestId('ai-studio-publish-reason-v3')).toHaveTextContent('验收未通过')
    expect(within(v3).getByTestId('ai-studio-publish-version-state')).toHaveTextContent('Unpublished')
  })

  it('A3: clicking the row button fires POST /publish and flips the row to Publishing (T6 owns the settle)', async () => {
    const user = userEvent.setup()
    renderStudio(<AiStudioPage />)
    await openPublish(user)
    await user.click(screen.getByTestId('ai-studio-publish-btn-v3'))
    expect(api.trigger).toHaveBeenCalledWith(TEST_PROJECT.id, 'v3', VERSIONS[0].commitHash)
    const v3 = screen.getByTestId('ai-studio-publish-version-row-v3')
    expect(within(v3).getByTestId('ai-studio-publish-version-state')).toHaveTextContent('Publishing')
  })

  it('nothing published yet: every row renders its button (no latest hash to match)', async () => {
    api.listRecords.mockResolvedValue({ records: [] })
    const user = userEvent.setup()
    renderStudio(<AiStudioPage />)
    await openPublish(user)
    for (const v of VERSIONS) {
      expect(within(screen.getByTestId(`ai-studio-publish-version-row-${v.version}`))
        .getByTestId(`ai-studio-publish-btn-${v.version}`)).toBeInTheDocument()
    }
  })
})
