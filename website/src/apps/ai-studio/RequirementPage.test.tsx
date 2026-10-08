// The read-only requirement page (ACP-2015 step 2). What these cases pin is
// the verdict bar's three readings and the two doc states, because the bar is
// the one thing the owner reads to decide 「can this be built yet」 — a bar that
// says 齐 when the graph says otherwise is worse than no bar.
//
// UI strings assert the English catalog (tests pin i18next to en); the graph
// names and the document content are Chinese by design and asserted as data.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const getRequirement = vi.hoisted(() => vi.fn())
vi.mock('./studioApi', async () => {
  const actual = await vi.importActual('./studioApi')
  return { ...actual, studioApi: { getRequirement } }
})

import RequirementPage from './RequirementPage'
import { StudioApiError, type StudioRequirementPage } from './studioApi'
import { renderStudio } from './testUtils'

const EMPTY_TIERS = { api: [], ui: [], parts: [] }

function pageData(over: Partial<StudioRequirementPage> = {}): StudioRequirementPage {
  return {
    page: '设备清单',
    graph: { goal: '维护设备台账', page: { title: '设备清单' } },
    markdown: '# 需求：设备清单（设备管理/设备点检）\n\n设备管理员维护全厂设备',
    graphHash: 'acb3cd2c9d469a30',
    verdict: '全齐',
    errors: [],
    missing: [],
    tiers: EMPTY_TIERS,
    devState: 'editing',
    stale: false,
    ...over,
  }
}

function mount(over?: Partial<StudioRequirementPage>) {
  getRequirement.mockResolvedValue(pageData(over))
  renderStudio(<RequirementPage projectId="p1" page="设备清单" />)
}

beforeEach(() => {
  getRequirement.mockReset()
})

describe('RequirementPage', () => {
  it('全齐: the bar says ready and the generated doc renders rich', async () => {
    mount()
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
    const user = userEvent.setup()
    mount({
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
    mount({
      verdict: '可以开工但有已知缺口',
      tiers: { api: [], ui: ['列表缺空态', '缺加载态'], parts: [] },
    })
    expect(await screen.findByTestId('req-verdict-bar')).toHaveTextContent(
      'Buildable, but 2 known gaps',
    )
  })

  it('a refused render says so instead of showing an empty document', async () => {
    mount({ verdict: '不齐', markdown: null, errors: ['/goal 类型要是 string'] })
    const box = await screen.findByTestId('req-no-markdown')
    expect(box).toHaveTextContent('The requirement graph is unqualified')
    expect(box).toHaveTextContent('/goal 类型要是 string')
    expect(screen.queryByTestId('req-doc')).not.toBeInTheDocument()
  })

  it('开始开发 ships disabled; 看需求图谱 swaps in the raw graph', async () => {
    const user = userEvent.setup()
    mount()
    const start = await screen.findByTestId('req-start')
    expect(start).toBeDisabled()
    expect(start).toHaveAccessibleName('Start development')

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
        await vi.advanceTimersByTimeAsync(5000)
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
    // previous file.
    getRequirement.mockResolvedValue(pageData({ stale: true }))
    renderStudio(<RequirementPage projectId="p1" page="设备清单" />)
    expect(await screen.findByTestId('req-verdict-bar')).toHaveTextContent('Regenerating…')
  })
})
