// The 需求 tab's list (ACP-2015 step 2): one row per workspace requirement page
// with its verdict badge, and a row click opens that page read-only. Two pages
// with opposite verdicts is the minimum that proves the badge is DATA-driven
// (a hard-coded colour would pass a one-page test).
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const listRequirements = vi.hoisted(() => vi.fn())
vi.mock('./studioApi', async () => {
  const actual = await vi.importActual('./studioApi')
  return { ...actual, studioApi: { listRequirements } }
})

import RequirementsTool from './RequirementsTool'
import type { StudioRequirementSummary } from './studioApi'
import { renderStudio } from './testUtils'

const PAGES: StudioRequirementSummary[] = [
  { page: '设备清单', graphHash: 'a'.repeat(16), verdict: '全齐', missingCount: 0, updatedAt: '2026-10-08T01:27:41Z' },
  { page: '设备点检记录', graphHash: 'b'.repeat(16), verdict: '不齐', missingCount: 3, updatedAt: '2026-10-08T01:33:58Z' },
]

function mount(onOpenTab = vi.fn()) {
  renderStudio(
    <RequirementsTool projectId="p1" onOpenTab={onOpenTab} />,
  )
  return onOpenTab
}

async function mountAndAwaitRows() {
  mount()
  const list = await screen.findByTestId('req-list')
  await within(list).findByTestId('req-row-设备清单')
  return list
}

beforeEach(() => {
  listRequirements.mockReset()
  listRequirements.mockResolvedValue({ pages: PAGES })
})

describe('RequirementsTool', () => {
  it('lists every page with its own verdict badge', async () => {
    const list = await mountAndAwaitRows()
    expect(within(list).getByTestId('req-row-设备清单')).toBeInTheDocument()
    expect(within(list).getByTestId('req-verdict-设备清单')).toHaveTextContent('Complete')
    expect(within(list).getByTestId('req-verdict-设备点检记录')).toHaveTextContent('Incomplete')
    // a green page carries no 「to fill」 count; a red one does
    expect(within(list).getByTestId('req-row-设备清单')).not.toHaveTextContent('to fill')
    expect(within(list).getByTestId('req-row-设备点检记录')).toHaveTextContent('3 to fill')
  })

  it('a row opens that page as a read-only req tab', async () => {
    const user = userEvent.setup()
    const onOpenTab = mount()
    await user.click(await screen.findByTestId('req-row-设备清单'))
    expect(onOpenTab).toHaveBeenCalledWith({
      id: 'req-设备清单',
      kind: 'req',
      title: '设备清单',
      page: '设备清单',
    })
  })

  it('an empty workspace says so instead of drawing an empty list', async () => {
    listRequirements.mockResolvedValue({ pages: [] })
    mount()
    // the empty state is a conclusion, so it waits for the read to land
    const list = await screen.findByTestId('req-list')
    await waitFor(() => expect(list).toHaveTextContent('no requirement graphs'))
    expect(within(list).queryByTestId(/^req-row-/)).not.toBeInTheDocument()
  })
})
