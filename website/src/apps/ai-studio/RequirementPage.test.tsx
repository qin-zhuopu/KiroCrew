// The requirement page: the read (ACP-2015 step 2) and the two acts (ACP-2104
// step 4). What these cases pin is the verdict bar's three readings, the two doc
// states, and — since step 4 — the writes: a save that posts the docHash the text
// was typed against, and a 开始开发 that refuses to click itself when the verdict
// says no. The bar is the one thing the owner reads to decide 「can this be built
// yet」, so a bar that says 齐 when the graph says otherwise is worse than no bar;
// the act cases exist for the mirror reason — a button that fires when the
// backend would refuse teaches the owner to distrust the bar.
//
// UI strings assert the English catalog (tests pin i18next to en); the graph
// names and the document content are Chinese by design and asserted as data.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const getRequirement = vi.hoisted(() => vi.fn())
const directEditRequirement = vi.hoisted(() => vi.fn())
const startRequirement = vi.hoisted(() => vi.fn())
vi.mock('./studioApi', async () => {
  const actual = await vi.importActual('./studioApi')
  return {
    ...actual,
    // the read surface and the write surface are separate objects (studioApi
    // explains why), so the fake replaces both
    studioApi: { getRequirement },
    requirementWriteApi: { directEditRequirement, startRequirement },
  }
})

import RequirementPage, { REQ_REFRESH_MS } from './RequirementPage'
import { StudioApiError, type StudioRequirementPage } from './studioApi'
import { renderStudio } from './testUtils'

const EMPTY_TIERS = { api: [], ui: [], parts: [] }

/** set up in beforeEach, i.e. BEFORE any render — user-event wants to install
 * its listeners on a clean document, and `typeInto` is shared by every case. */
let user: ReturnType<typeof userEvent.setup>

function pageData(over: Partial<StudioRequirementPage> = {}): StudioRequirementPage {
  return {
    page: '设备清单',
    graph: { goal: '维护设备台账', page: { title: '设备清单' } },
    markdown: '# 需求：设备清单（设备管理/设备点检）\n\n设备管理员维护全厂设备',
    graphHash: 'acb3cd2c9d469a30',
    docHash: 'a'.repeat(16),
    verdict: '全齐',
    errors: [],
    missing: [],
    tiers: EMPTY_TIERS,
    pendingEdit: false,
    devState: 'editing',
    changedAfterStart: false,
    stale: false,
    ...over,
  }
}

/** mounts the page and waits for the first read: the doc surface (editor, 保存)
 * exists only once a document arrived, so a case that touches it must not query
 * before then. */
async function mount(over?: Partial<StudioRequirementPage>) {
  getRequirement.mockResolvedValue(pageData(over))
  const view = renderStudio(<RequirementPage projectId="p1" page="设备清单" />)
  await screen.findByTestId('req-verdict-bar')
  return view
}

/** replaces the doc textarea's content with `text` and types it for real.
 * `user.paste` needs a ClipboardEvent this environment does not build, and a
 * Ctrl+A does not select inside a textarea here, so the clear is explicit — which
 * also makes the posted body exactly `text`, so an assertion about the whole body
 * means what it says. */
async function typeInto(el: HTMLElement, text: string) {
  await user.clear(el)
  await user.type(el, text)
}

beforeEach(() => {
  user = userEvent.setup()
  getRequirement.mockReset()
  directEditRequirement.mockReset()
  startRequirement.mockReset()
})

describe('RequirementPage', () => {
  it('全齐: the bar says ready and the generated doc renders rich', async () => {
    await mount()
    const bar = await screen.findByTestId('req-verdict-bar')
    expect(bar).toHaveTextContent('Requirements complete — ready to build')
    // the markdown is RENDERED, not a <pre> of its source
    const doc = await screen.findByTestId('req-doc')
    expect(await within(doc).findByRole('heading', { name: /设备清单/ })).toBeInTheDocument()
    expect(doc).not.toHaveTextContent('# 需求：')
    // a qualified graph has nothing to expand
    expect(screen.queryByTestId('req-gaps-toggle')).not.toBeInTheDocument()
  })

  it('不齐: the bar blocks, and 展开缺口 lists the missing items', async () => {
    await mount({
      verdict: '不齐',
      markdown: null,
      missing: ['接口口径有待定'],
      errors: ['/goal 类型要是 string'],
    })
    expect(await screen.findByTestId('req-verdict-bar')).toHaveTextContent(
      'Incomplete — not buildable yet',
    )
    await user.click(screen.getByTestId('req-gaps-toggle'))
    const gaps = await screen.findByTestId('req-gaps')
    expect(within(gaps).getByText('接口口径有待定')).toBeInTheDocument()
    expect(within(gaps).getByText('/goal 类型要是 string')).toBeInTheDocument()
  })

  it('有缺口: the bar quotes the tier count', async () => {
    await mount({
      verdict: '可以开工但有已知缺口',
      tiers: { api: [], ui: ['列表缺空态', '缺加载态'], parts: [] },
    })
    expect(await screen.findByTestId('req-verdict-bar')).toHaveTextContent(
      'Buildable, but 2 known gaps',
    )
  })

  it('a refused render says so instead of showing an empty document', async () => {
    await mount({ verdict: '不齐', markdown: null, errors: ['/goal 类型要是 string'] })
    const box = await screen.findByTestId('req-no-markdown')
    expect(box).toHaveTextContent('The requirement graph is unqualified')
    expect(box).toHaveTextContent('/goal 类型要是 string')
    // no document, and no editor either: there is no view to edit, and a save
    // against a graph that will not render is a change nobody can review
    expect(screen.queryByTestId('req-doc')).not.toBeInTheDocument()
    expect(screen.queryByTestId('req-doc-editor')).not.toBeInTheDocument()
  })

  it('看需求图谱 swaps in the raw graph and back', async () => {
    await mount()
    await screen.findByTestId('req-verdict-bar')
    await user.click(screen.getByTestId('req-graph-toggle'))
    const pre = await screen.findByTestId('req-graph-json')
    expect(JSON.parse(pre.textContent ?? '')).toEqual(pageData().graph)
    expect(screen.queryByTestId('req-doc')).not.toBeInTheDocument()
    // and back to the document
    await user.click(screen.getByTestId('req-graph-toggle'))
    expect(await screen.findByTestId('req-doc')).toBeInTheDocument()
  })

  it('a missing verdict service is a bar state, not an error strip', async () => {
    getRequirement.mockRejectedValue(
      new StudioApiError(503, 'reqdoc_cmd_unavailable', 'requirement command not found: jc'),
    )
    renderStudio(<RequirementPage projectId="p1" page="设备清单" />)
    expect(await screen.findByTestId('req-verdict-bar')).toHaveTextContent(
      'Verdict service unavailable',
    )
    expect(screen.queryByTestId('req-doc')).not.toBeInTheDocument()
  })

  it('the graph moving under the page flips the bar within one poll (B4)', async () => {
    // RFC §7 B4: the assistant writes the graph while the owner is looking at
    // this page. The read is a subprocess (check + render), so 「生成中…」 is the
    // literal state while the poll is in flight, and the verdict that lands is
    // the NEW graph's — not the one the page opened on.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      getRequirement.mockResolvedValue(pageData())
      renderStudio(<RequirementPage projectId="p1" page="设备清单" />)
      const bar = await screen.findByTestId('req-verdict-bar', undefined, { timeout: 3000 })
      expect(bar).toHaveTextContent('Requirements complete — ready to build')

      // the assistant added a 待定 rule; only the file changed, nothing was clicked
      getRequirement.mockResolvedValue(
        pageData({
          graphHash: 'ff'.repeat(8),
          verdict: '不齐',
          markdown: null,
          missing: ['接口口径有待定'],
        }),
      )
      await act(async () => {
        await vi.advanceTimersByTimeAsync(REQ_REFRESH_MS)
      })
      await waitFor(
        () => expect(bar).toHaveTextContent('Incomplete — not buildable yet'),
        { timeout: 3000 },
      )
      // the document swap is part of the same refresh: an unqualified graph has
      // no document, so the refusal panel replaces it
      expect(await screen.findByTestId('req-no-markdown', undefined, { timeout: 3000 }))
        .toHaveTextContent('接口口径有待定')
    } finally {
      vi.useRealTimers()
    }
  })

  it('a stale document says 生成中… instead of re-reading an old verdict', async () => {
    // R1: graph hash moved, document not regenerated yet. The bar must not
    // repeat the readiness sentence it is holding — that verdict described the
    // previous file. 开始开发 waits with it: 「齐」 is unknowable mid-render.
    getRequirement.mockResolvedValue(pageData({ stale: true }))
    renderStudio(<RequirementPage projectId="p1" page="设备清单" />)
    expect(await screen.findByTestId('req-verdict-bar')).toHaveTextContent('Regenerating…')
    // ACP-2231: the button stays live; the click re-reads and, still stale, says so
    await user.click(screen.getByTestId('req-start-btn'))
    expect(await screen.findByTestId('req-start-blocked')).toHaveTextContent('Regenerating…')
    expect(startRequirement).not.toHaveBeenCalled()
  })

  // ----------------------------------------------------------------- 直改 (B5)

  it('the doc is editable and 保存 posts the docHash of the view it was typed against', async () => {
    await mount()
    const saveBtn = screen.getByTestId('req-save-btn')
    // nothing typed yet: greyed, so a stray click cannot post a no-op save
    expect(saveBtn).toBeDisabled()
    const editor = screen.getByTestId('req-doc-editor')
    await typeInto(editor, '备注：删除按钮要二次确认')
    expect(saveBtn).toBeEnabled()
    directEditRequirement.mockResolvedValue({ changed: true, diff: '+备注', pending: true })
    await user.click(saveBtn)
    // the credential is the hash READ with this text in the buffer — the backend
    // 409s anything else, which is how a concurrent landing surfaces
    expect(directEditRequirement).toHaveBeenCalledWith(
      'p1', '设备清单', 'a'.repeat(16), expect.stringContaining('备注：删除按钮要二次确认'),
    )
  })

  it('保存 sends the edited text, not the document it was served', async () => {
    await mount({ markdown: '设备管理员维护全厂设备' })
    const editor = await screen.findByTestId('req-doc-editor')
    directEditRequirement.mockResolvedValue({ changed: false })
    await typeInto(editor, '设备管理员维护全厂设备台账')
    await user.click(screen.getByTestId('req-save-btn'))
    await waitFor(() => expect(directEditRequirement).toHaveBeenCalled())
    expect(directEditRequirement.mock.calls[0][3]).toBe('设备管理员维护全厂设备台账')
  })

  it('409 doc_changed: the backend\'s sentence verbatim, plus the one action that resolves it', async () => {
    await mount()
    const editor = await screen.findByTestId('req-doc-editor')
    await typeInto(editor, '备注')
    directEditRequirement.mockRejectedValue(
      new StudioApiError(409, 'doc_changed', '文档已被别人改过，请刷新'),
    )
    await user.click(screen.getByTestId('req-save-btn'))
    expect(await screen.findByTestId('req-save-conflict')).toHaveTextContent(
      'The document was changed by someone else — reload',
    )
    // 刷新 is a RE-READ of this page, not a navigation: the owner stays put and
    // gets the docHash of the document that actually exists now
    const before = getRequirement.mock.calls.length
    await user.click(screen.getByTestId('req-refresh-btn'))
    expect(screen.queryByTestId('req-save-conflict')).not.toBeInTheDocument()
    await waitFor(() => expect(getRequirement.mock.calls.length).toBeGreaterThan(before))
  })

  it('a save that fails for another reason says 保存失败 and keeps the text', async () => {
    await mount()
    const editor = await screen.findByTestId('req-doc-editor')
    await typeInto(editor, '备注')
    directEditRequirement.mockRejectedValue(
      new StudioApiError(503, 'store_write_failed', 'cannot write the ledger'),
    )
    await user.click(screen.getByTestId('req-save-btn'))
    expect(await screen.findByTestId('req-save-error')).toHaveTextContent('Could not save')
    // the typing survives — a lost edit is worse than a retry
    expect((editor as HTMLTextAreaElement).value).toContain('备注')
  })

  it('pendingEdit: the bar says the edit has not landed and 开始开发 is greyed', async () => {
    // B5's middle state: the verdict on screen describes a graph that no longer
    // matches what the owner asked for, so it must not authorise a start
    await mount({ pendingEdit: true })
    expect(await screen.findByTestId('req-verdict-bar')).toHaveTextContent(
      'Change awaiting the requirement',
    )
    await user.click(screen.getByTestId('req-start-btn'))
    expect(await screen.findByTestId('req-start-blocked')).toHaveTextContent(
      'Change awaiting the requirement',
    )
    expect(startRequirement).not.toHaveBeenCalled()
  })

  it('a refresh that lands while the owner has typed does not eat the typing', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      getRequirement.mockResolvedValue(pageData())
      renderStudio(<RequirementPage projectId="p1" page="设备清单" />)
      const editor = await screen.findByTestId('req-doc-editor')
      await typeInto(editor, '备注：手工录入')
      // the 5s poll answers with a NEW document (the assistant landed something)
      getRequirement.mockResolvedValue(pageData({
        markdown: '助手改过了',
        docHash: 'b'.repeat(16),
      }))
      await act(async () => {
        await vi.advanceTimersByTimeAsync(REQ_REFRESH_MS)
      })
      await waitFor(() => expect(getRequirement.mock.calls.length).toBeGreaterThan(1),
        { timeout: 3000 })
      // the buffer is the owner's, so it stays put — and the page says so out
      // loud, because silence here reads as "the refresh found nothing new"
      const value = () => (screen.getByTestId('req-doc-editor') as HTMLTextAreaElement).value
      expect(value()).toContain('备注：手工录入')
      expect(value()).not.toContain('助手改过了')
      expect(screen.getByTestId('req-buffer-held')).toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })

  it('a page change drops the unsaved buffer of the page it belonged to', async () => {
    // WorkArea keys the page on project+page, so a real page change re-mounts;
    // the reset effect is for the paths that do NOT. A buffer that followed the
    // owner across pages would post page A's text against page B's docHash.
    const first = await mount()
    await typeInto(screen.getByTestId('req-doc-editor'), '备注')
    getRequirement.mockResolvedValue(pageData({ page: '设备分类', markdown: '# 需求：设备分类' }))
    first.unmount()
    renderStudio(<RequirementPage projectId="p1" page="设备分类" />)
    await screen.findByTestId('req-verdict-bar')
    const value = () => (screen.getByTestId('req-doc-editor') as HTMLTextAreaElement).value
    await waitFor(() => expect(value()).toContain('设备分类'))
    expect(value()).not.toContain('备注')
  })

  // ------------------------------------------------------- 开始开发 (B6, R2/R3)

  /** a 不齐 page whose first gap is the one the tooltip must quote */
  const INCOMPLETE = {
    verdict: '不齐', markdown: null, errors: ['goal 为空'], missing: ['缺验收'],
  } as const

  it('不齐: the click re-checks, refuses on the spot and names the first gap (ACP-2231)', async () => {
    await mount(INCOMPLETE)
    expect(await screen.findByTestId('req-verdict-bar')).toHaveTextContent(
      'Incomplete — not buildable yet',
    )
    const start = screen.getByTestId('req-start-btn')
    expect(start).toBeEnabled()
    const before = getRequirement.mock.calls.length
    await user.click(start)
    expect(await screen.findByTestId('req-start-blocked')).toHaveTextContent(
      'Cannot start yet: goal 为空',
    )
    expect(getRequirement.mock.calls.length).toBeGreaterThan(before)
    expect(screen.getByTestId('req-gaps')).toHaveTextContent('缺验收')
    expect(startRequirement).not.toHaveBeenCalled()
  })

  it('every click re-reads first: a page that turned 不齐 since the last refresh is refused (ACP-2231)', async () => {
    await mount()
    await screen.findByTestId('req-verdict-bar')
    // the screen still says 全齐; the graph has moved since
    getRequirement.mockResolvedValue(pageData(INCOMPLETE))
    await user.click(screen.getByTestId('req-start-btn'))
    expect(await screen.findByTestId('req-start-blocked')).toHaveTextContent('Cannot start yet')
    expect(startRequirement).not.toHaveBeenCalled()
  })

  it('shows when it last refreshed, and 刷新 re-reads on demand (ACP-2231)', async () => {
    await mount()
    await screen.findByTestId('req-verdict-bar')
    expect(screen.getByTestId('req-updated-at')).toHaveTextContent(/Updated \d{2}:\d{2}:\d{2}/)
    const before = getRequirement.mock.calls.length
    await user.click(screen.getByTestId('req-reload-btn'))
    await waitFor(() => expect(getRequirement.mock.calls.length).toBeGreaterThan(before))
    expect(REQ_REFRESH_MS).toBe(60_000)
  })

  it('有缺口: 开始开发 asks first, and 取消 sends nothing', async () => {
    await mount({
      verdict: '可以开工但有已知缺口',
      tiers: { api: ['接口待定'], ui: [], parts: ['字段待定'] },
    })
    expect(await screen.findByTestId('req-verdict-bar')).toHaveTextContent(
      'Buildable, but 2 known gaps',
    )
    expect(screen.getByTestId('req-start-btn')).toBeEnabled()
    await user.click(screen.getByTestId('req-start-btn'))
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('This page has 2 known gaps')
    await user.click(within(dialog).getByRole('button', { name: /Cancel/ }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(startRequirement).not.toHaveBeenCalled()
  })

  it('有缺口 confirmed: the request carries the hash the bar is showing, and the 开发 tab is told', async () => {
    await mount({
      verdict: '可以开工但有已知缺口',
      graphHash: 'ffff0000ffff0000',
      tiers: { api: ['接口待定'], ui: [], parts: [] },
    })
    await screen.findByTestId('req-verdict-bar')
    startRequirement.mockResolvedValue({
      ok: true, page: '设备清单', graphHash: 'ffff0000ffff0000', verdict: '可以开工但有已知缺口',
    })
    // the event the 开发 page listens for (RFC §9.4 hands task splitting to
    // another work stream): this page dispatches, it does not own that tab
    const seen: unknown[] = []
    const listener = (e: Event) => seen.push((e as CustomEvent).detail)
    window.addEventListener('ai-studio:start-dev', listener)
    try {
      await user.click(screen.getByTestId('req-start-btn'))
      await user.click(await screen.findByTestId('req-start-confirm'))
      expect(await screen.findByTestId('req-start-result')).toHaveTextContent(
        'Start requested — waiting for task breakdown',
      )
      expect(startRequirement).toHaveBeenCalledWith('p1', '设备清单', 'ffff0000ffff0000')
      expect(seen).toEqual([{ projectId: 'p1', page: '设备清单' }])
    } finally {
      window.removeEventListener('ai-studio:start-dev', listener)
    }
  })

  it('全齐: 开始开发 asks nothing and goes straight through', async () => {
    await mount()
    await screen.findByTestId('req-verdict-bar')
    startRequirement.mockResolvedValue({ ok: true, page: '设备清单', graphHash: 'a', verdict: '全齐' })
    await user.click(screen.getByTestId('req-start-btn'))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await waitFor(() => expect(startRequirement).toHaveBeenCalled())
  })

  it('a refused start says the graph moved, and re-reads instead of arguing', async () => {
    // R2: 409/422 mean the verdict on screen was stale, so the page goes and
    // gets a new one rather than showing a refusal that outlives its cause
    await mount()
    await screen.findByTestId('req-verdict-bar')
    startRequirement.mockRejectedValue(new StudioApiError(422, 'not_ready', '需求不齐'))
    const before = getRequirement.mock.calls.length
    await user.click(screen.getByTestId('req-start-btn'))
    expect(await screen.findByTestId('req-start-refused')).toHaveTextContent(
      'The requirement just changed and is now incomplete — close the gaps first',
    )
    await waitFor(() => expect(getRequirement.mock.calls.length).toBeGreaterThan(before))
  })

  it('devState=started: the button reads 已开工 and is greyed', async () => {
    await mount({ devState: 'started' })
    await screen.findByTestId('req-verdict-bar')
    const start = screen.getByTestId('req-start-btn')
    expect(start).toBeDisabled()
    expect(start).toHaveTextContent('Already started')
    expect(startRequirement).not.toHaveBeenCalled()
  })

  it('changedAfterStart: the void marker says ask again, and the button is live', async () => {
    // R3: the record is not deleted, the hash simply no longer matches, so the
    // page says the start is void instead of pretending it never happened
    await mount({ changedAfterStart: true })
    expect(await screen.findByTestId('req-changed-after-start')).toHaveTextContent(
      'The requirement changed — press Confirm requirements & start again',
    )
    expect(screen.getByTestId('req-start-btn')).toBeEnabled()
  })
})
