// ACP-795: the commits-tab contract for C1/C2.
//
// WHY THIS SHAPE: the commits tab is the sidebar's, not the center's, so the
// frame can only pin it through the two seams this task added to the REAL
// `ToolSidebar` (`initialTool` + the `changed` / `commits` data props). So this
// test mounts the SHIPPED sidebar component — no look-alike shell, no
// `state-*` demo testid — and asserts the outline's testid/copy contract on
// the tree a presenter will actually see: the committed tab is the `role="tab"`
// with `aria-selected="true"`, the 「待提交的改动」 rows are its buttons, the
// 「提交历史」 rows are the ones below the second section header.
//
// ZERO FETCHES: rendering is local state only; the global fetch spy is the
// external witness. The ONE thing on this tab that does read — the commit
// bar's drafts query (the button moved here in ACP-801) — is fed the frame's
// own in-memory fake, so it is data here too. i18n: the suite pins the English
// catalog, so the section headers read 'Uncommitted changes' / 'Commit history';
// the doc names are Chinese data. No screenshots — DOM only.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import ToolSidebar from '../ToolSidebar'
import { CHANGED, COMMITS } from '../fixtures'
import { renderStudio } from '../testUtils'
import { createDemoApi } from './runtime'
import { COMMIT_STATES } from './states-commit'
import type { CommitStateSnapshot } from './states-commit'

const FOCUS_DOC = '产品需求设计文档.md'
const JOURNEY_DOC = '用户旅程设计.md'
const MODEL_DOC = '业务模型设计.md'
const PAGE_DOC = '页面交互设计.md'
const ALL_DOCS = [FOCUS_DOC, JOURNEY_DOC, MODEL_DOC, PAGE_DOC]

const byId = (id: string): CommitStateSnapshot => {
  const s = COMMIT_STATES.find((x) => x.id === id)
  if (!s) throw new Error(`state ${id} missing from COMMIT_STATES`)
  return s
}
const C1 = byId('C1')
const C2 = byId('C2')

let fetchSpy: ReturnType<typeof vi.spyOn>
beforeEach(() => {
  window.localStorage.clear()
  fetchSpy = vi.spyOn(globalThis, 'fetch')
})
afterEach(() => {
  expect(fetchSpy).not.toHaveBeenCalled()
  fetchSpy.mockRestore()
})

/** mount the real sidebar on a frame, exactly as the renderer will wire it.
 * `off` drops the FRAME's seams (tab + lists), which is the ordinary caller's
 * call shape.
 *
 * The tab's action button is the shipped `ProjectCommitBar` (ACP-801 moved it
 * here from the page header), so this mount now needs a QueryClient and a data
 * source: it gets the frame's in-memory fake — the same `commitApi` the
 * renderer passes — so the bar's real drafts read is answered as data and no
 * request leaves the test either way. */
function mountFrame(frame: CommitStateSnapshot, off = false) {
  const onOpenTab = vi.fn()
  // one fake serves both live seams: the commit bar's drafts and — since
  // ACP-2015 step 2 made 需求 the default tab, so an `off` mount lands on it —
  // the 需求 tab's requirement list. The frame's snapshot answers both and no
  // request leaves the test.
  const demoApi = createDemoApi(frame.fixture)
  renderStudio(
    <ToolSidebar
      onOpenTab={onOpenTab}
      docs={frame.fixture.docs}
      projectId={frame.fixture.project.id}
      initialTool={off ? undefined : frame.activeSidebarTab}
      changed={off ? undefined : frame.changed}
      commits={off ? undefined : frame.commits}
      commitApi={demoApi}
      requirementApi={demoApi}
      commitKey={frame.id}
    />,
  )
  return onOpenTab
}

/** an exact-match regex for a literal (doc names carry dots) */
const lit = (s: string) => new RegExp(s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))

/** the two sections are siblings inside the tool container, so the rows of a
 * section are exactly the buttons that follow its header — until the next
 * section header (the first non-button sibling) or the end of the list */
function rowsAfter(header: HTMLElement): HTMLElement[] {
  const rows: HTMLElement[] = []
  for (let el = header.nextElementSibling; el; el = el.nextElementSibling) {
    if (el.tagName !== 'BUTTON') break
    rows.push(el as HTMLElement)
  }
  return rows
}
const pendingRows = () => rowsAfter(screen.getByText('Uncommitted changes'))
const commitHistoryRows = () => rowsAfter(screen.getByText('Commit history'))

const draftOf = (frame: CommitStateSnapshot, name: string) =>
  frame.fixture.draftVersions.find((d) => d.name === name)?.content
const committedOf = (frame: CommitStateSnapshot, name: string) =>
  frame.fixture.docs.find((d) => d.name === name)?.content ?? ''

// ---------------------------------------------------------------------------
// the data layer: the claims the frames must never break
// ---------------------------------------------------------------------------

describe('C1/C2 snapshot data contract', () => {
  it('exports the two commits frames in order, with the commits tab lit', () => {
    expect(COMMIT_STATES.map((s) => s.id)).toEqual(['C1', 'C2'])
    for (const s of COMMIT_STATES) {
      expect(s.phase).toBe('design')
      expect(s.activeSidebarTab).toBe('commits')
      expect(s.label).not.toBe('')
      expect(s.title).not.toBe('')
      expect(s.caption).not.toBe('')
      expect(s.docs.map((d) => d.name)).toEqual(ALL_DOCS)
    }
    // the pair brackets the commit: pending → clean
    expect(C1.dirty && C1.commitEnabled).toBe(true)
    expect(C2.dirty || C2.commitEnabled).toBe(false)
  })

  it('parity discipline (附一) holds for EVERY version row of both frames', () => {
    const check = (r: { version?: string; parity?: string; source?: string }, where: string) => {
      expect(r.version, where).toBeTruthy()
      const want = Number((r.version as string).slice(1)) % 2 === 1 ? 'odd' : 'even'
      expect(r.parity, `${where} ${r.version}`).toBe(want)
      expect(r.source, `${where} ${r.version}`).toBe(want === 'odd' ? 'manual' : 'regen')
    }
    for (const s of COMMIT_STATES) {
      s.versionHistory?.forEach((r) => check(r, `${s.id} versionHistory`))
      for (const [doc, rows] of Object.entries(s.fixture.versions)) {
        rows.forEach((r) => check(r, `${s.id} fixture.versions[${doc}]`))
      }
    }
  })

  it('C1 is the pending frame: every pending file has a real draft, and the snippets are lines of it', () => {
    expect(C1.changed.map((c) => c.file)).toEqual(ALL_DOCS)
    for (const c of C1.changed) {
      const draft = draftOf(C1, c.file)
      const committed = committedOf(C1, c.file)
      // the file is both listed and really changed — no wishful row
      expect(draft, `${c.file} has no draft record`).toBeTruthy()
      expect(draft).not.toBe(committed)
      for (const line of c.added.split('\n')) {
        expect(line.startsWith('+'), `${c.file} added line ${line}`).toBe(true)
        expect((draft as string).split('\n')).toContain(line.slice(1))
      }
      if (c.removed) {
        for (const line of c.removed.split('\n')) {
          expect(line.startsWith('-')).toBe(true)
          expect(committed.split('\n')).toContain(line.slice(1))
          expect((draft as string).split('\n')).not.toContain(line.slice(1))
        }
      }
    }
  })

  it('C2 is the committed frame: nothing pending, and the drafts are gone', () => {
    expect(C2.changed).toEqual([])
    expect(C2.fixture.draftVersions).toEqual([])
    // what the commit landed IS what was pending, byte for byte
    for (const c of C1.changed) {
      expect(committedOf(C2, c.file)).toBe(draftOf(C1, c.file))
    }
  })

  it('the closing commit is exactly the pending list, added on top of the same history', () => {
    expect(C2.commits.length).toBe(C1.commits.length + 1)
    expect(C2.commits[0].id).not.toBe(C1.commits[0].id)
    expect(C2.commits[0].files).toEqual(C1.changed.map((c) => c.file))
    expect(C2.commits.slice(1)).toEqual(C1.commits)
  })

  it('shows the previous two iterations, and no commit claims a doc that does not exist', () => {
    const messages = C1.commits.map((c) => c.message)
    expect(messages.some((m) => m.startsWith('第一轮迭代：'))).toBe(true)
    expect(messages.some((m) => m.startsWith('第二轮迭代：'))).toBe(true)
    const ids = C1.commits.map((c) => c.id)
    expect([...ids].sort().reverse()).toEqual(ids) // newest first
    for (const entry of [...C1.commits, ...C2.commits]) {
      expect(entry.time).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/)
      for (const f of entry.files) expect(ALL_DOCS).toContain(f)
    }
  })

  it("this iteration's new rows are sliced from that doc's committed text", () => {
    const previousTop: Record<string, string> = {
      [FOCUS_DOC]: 'v4', [JOURNEY_DOC]: 'v3', [MODEL_DOC]: 'v1', [PAGE_DOC]: 'v3',
    }
    const newTop = [FOCUS_DOC, JOURNEY_DOC, MODEL_DOC, PAGE_DOC]
    for (const doc of newTop) {
      const rows = C2.fixture.versions[doc]
      expect(rows[0].version).not.toBe(previousTop[doc])
      expect(C1.fixture.versions[doc][0].version).toBe(previousTop[doc])
      const content = committedOf(C2, doc).split('\n')
      for (const line of rows[0].diff.split('\n')) {
        if (!line.startsWith('+') || line === '+' || line.startsWith('+++')) continue
        expect(content, `${doc} ${rows[0].version} ${line}`).toContain(line.slice(1))
      }
    }
  })
})

// ---------------------------------------------------------------------------
// the real sidebar: the tab is lit and the two lists are the frame's
// ---------------------------------------------------------------------------

describe('the real ToolSidebar on the commits tab', () => {
  it('has the commits tab selected and the other six not', () => {
    mountFrame(C1)
    expect(screen.getByTestId('tool-sidebar')).toBeTruthy()
    const tabs = screen.getAllByRole('tab')
    // 7 since ACP-2015 step 2 (需求 leads the row); commits is the third
    expect(tabs).toHaveLength(7)
    expect(tabs.map((t) => t.getAttribute('aria-selected'))).toEqual(['false', 'false', 'true', 'false', 'false', 'false', 'false'])
    expect(screen.getByRole('tab', { name: 'Commits' }).getAttribute('aria-selected')).toBe('true')
  })

  it('carries the project commit at its top (ACP-801), above both lists', async () => {
    mountFrame(C1)
    // the bar's drafts read is async: wait for the badge, which is what its
    // enable rule is derived from
    await screen.findByTestId('drafts-pending')
    const btn = screen.getByTestId('commit-all-btn')
    // it is INSIDE this tab: the sidebar contains it, and it precedes the
    // first section header — the action acts on 提交, so it leads the tab
    expect(screen.getByTestId('tool-sidebar').contains(btn)).toBe(true)
    const pendingHeader = screen.getByText('Uncommitted changes')
    expect(btn.compareDocumentPosition(pendingHeader) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    // the frame's own drafts really enable it — the badge names them
    expect(btn).toBeEnabled()
    expect(screen.getByTestId('drafts-pending')).toBeInTheDocument()
  })

  it("lists this iteration's four docs under 待提交的改动", () => {
    mountFrame(C1)
    const rows = pendingRows()
    expect(rows).toHaveLength(4)
    ALL_DOCS.forEach((name, i) => expect(rows[i].textContent).toContain(name))
    for (const name of ALL_DOCS) {
      expect(screen.getByRole('button', { name: lit(name) })).toBeTruthy()
    }
    // the frame's list wins over the shipped fixture
    expect(screen.queryByText('requirements.md')).toBeNull()
  })

  it('lists the two previous iterations under 提交历史', () => {
    mountFrame(C1)
    const rows = commitHistoryRows()
    expect(rows).toHaveLength(C1.commits.length)
    expect(screen.getByText(`c1051 · 2024-12-31 23:46`)).toBeTruthy()
    expect(screen.getByText(`c1027 · 2024-12-31 07:06`)).toBeTruthy()
    for (const c of C1.commits) {
      expect(screen.getByRole('button', { name: lit(c.message) })).toBeTruthy()
    }
  })

  it('C2 clears the pending list and gains exactly one history row', () => {
    mountFrame(C2)
    expect(pendingRows()).toHaveLength(0)
    const rows = commitHistoryRows()
    expect(rows).toHaveLength(C2.commits.length)
    const first = rows[0].textContent ?? ''
    expect(first).toContain(C2.commits[0].message)
    expect(first).toContain(`c1052 · 2025-01-01 09:30`)
    // the section headers survive the empty list — 空态也是数据
    expect(screen.getByText('Uncommitted changes')).toBeTruthy()
  })

  it('the rows still open the real work area tabs', async () => {
    const onOpenTab = mountFrame(C1)
    await userEvent.click(screen.getByRole('button', { name: lit(FOCUS_DOC) }))
    expect(onOpenTab).toHaveBeenCalledWith(expect.objectContaining({ kind: 'diff', file: FOCUS_DOC, id: `diff-${FOCUS_DOC}` }))
    await userEvent.click(screen.getByRole('button', { name: lit(C1.commits[0].message) }))
    expect(onOpenTab).toHaveBeenLastCalledWith(expect.objectContaining({ kind: 'commit', commitId: C1.commits[0].id }))
  })

  it('without the new props the sidebar renders exactly what it rendered before', async () => {
    mountFrame(C1, true)
    // The default tab is no longer 文档 — ACP-2015 step 2 moved the sidebar's
    // first screen to 需求, deliberately. What must not have changed is the
    // panel BEHIND the default: with the frame's seams dropped, 文档 still
    // lists the caller's own docs and nothing else. So the before-picture is
    // asserted by clicking 文档, and 需求 is pinned as the new default.
    expect(screen.getByRole('tab', { name: 'Requirements' }).getAttribute('aria-selected')).toBe('true')
    await userEvent.click(screen.getByRole('tab', { name: 'Docs' }))
    expect(screen.getByText(FOCUS_DOC)).toBeTruthy()
    await userEvent.click(screen.getByRole('tab', { name: 'Commits' }))
    await userEvent.click(screen.getByRole('tab', { name: 'Commits' }))
    // the shipped fixtures, not the frame's lists
    expect(screen.getByText(CHANGED[0].file)).toBeTruthy()
    expect(screen.getByText(COMMITS[0].message)).toBeTruthy()
    expect(screen.queryByText(FOCUS_DOC)).toBeNull()
  })
})