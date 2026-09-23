// ACP-797: the 需求图谱 tab's contract for G1/G2 — the 提交 stage's product,
// watched being generated and then read as a LIST.
//
// WHY THIS SHAPE: the owner's rule is that the generation process and the graph
// itself are observed in the tool sidebar's 「需求图谱」 tab and NOWHERE else —
// no box-and-arrow canvas, least of all in the middle column. So this file
// mounts the REAL shipped components a presenter will see: the real
// `ToolSidebar` (its 需求图谱 tab lit by the frame's own data seam) and, inside
// it, the real `DistillPanel` the product already ships — and it asserts on
// their shipped testids and copy (`distill-panel[data-distill-status]`,
// `distill-status-running|done`, `distill-candidate-<id>`, the entry rows). No
// look-alike shell is built for the test, and no SVG exists to assert on.
//
// THE ONE PLACE THE FRAME'S DATA DIFFERS FROM THE TICKET'S WORDING, stated
// here so it is not mistaken for a gap: the shipped `DistillPanel` prints ONLY
// the 「进行中」 hint while `status === 'running'` — candidate rows appear when
// the run is done. So G1's 「逐条出现」 is carried by the ENTRY LIST (which is
// what the tab shows under the panel, and which really is a subset of G2's),
// while `distill-candidate-*` is asserted on G2, where the product renders it.
// The test pins that as a fact (`no candidate rows while running`) rather than
// pretending the panel lists results it does not have yet.
//
// ZERO FETCHES: rendering is local state only; the global fetch spy is the
// external witness. i18n: the suite pins the English catalog, so the mark pills
// read Add / Modify / Remove; the entry labels, group headers and doc names are
// Chinese data. No screenshots — DOM only.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import ToolSidebar from '../ToolSidebar'
import type { GraphEntryGroup } from '../ToolSidebar'
import { renderStudio } from '../testUtils'
import { COMMIT_STATES } from './states-commit'
import { DESIGN_STATES } from './states-design'
import { GRAPH_STATES, GRAPH_DELTA, GRAPH_WAVE } from './states-graph'
import type { GraphStateSnapshot } from './states-graph'

const FOCUS_DOC = '产品需求设计文档.md'
const ALL_DOCS = ['产品需求设计文档.md', '用户旅程设计.md', '业务模型设计.md', '页面交互设计.md']

const byId = (id: string): GraphStateSnapshot => {
  const s = GRAPH_STATES.find((x) => x.id === id)
  if (!s) throw new Error(`state ${id} missing from GRAPH_STATES`)
  return s
}
const G1 = byId('G1')
const G2 = byId('G2')

const C2 = COMMIT_STATES.find((s) => s.id === 'C2')!
const D7 = DESIGN_STATES.find((s) => s.id === 'D7') as unknown as { graphEntries: GraphEntryGroup[] }

const rows = (s: GraphStateSnapshot) => s.graphEntries.flatMap((g) => g.rows)
const targetOf = (s: GraphStateSnapshot, id: string) => rows(s).find((r) => r.id === id)

let fetchSpy: ReturnType<typeof vi.spyOn>
beforeEach(() => {
  window.localStorage.clear()
  fetchSpy = vi.spyOn(globalThis, 'fetch')
})
afterEach(() => {
  expect(fetchSpy).not.toHaveBeenCalled()
  fetchSpy.mockRestore()
})

/** mount the real sidebar on a graph frame, exactly as the renderer will wire
 * it. `off` drops both seams — the ordinary caller's call shape. */
function mountFrame(frame: GraphStateSnapshot, off = false) {
  const onOpenTab = vi.fn()
  const view = render(
    <ToolSidebar
      onOpenTab={onOpenTab}
      docs={frame.fixture.docs}
      projectId={frame.fixture.project.id}
      initialTool={off ? undefined : 'graph'}
      graphEntries={off ? undefined : frame.graphEntries}
      distillation={off ? undefined : frame.distillation}
    />,
  )
  return { onOpenTab, unmount: view.unmount }
}

const entryRowEls = () => document.querySelectorAll<HTMLElement>('[data-testid^="graph-entry-"]')

/** no box-and-arrow anywhere: GraphView draws rects, edges and node groups, so
 * this is the canvas it would leave behind — the icons the tab legitimately
 * carries (lucide) are SVGs too, which is why the check names the shapes. */
const canvasProbe = () => ({
  view: screen.queryByTestId('graph-view'),
  nodes: document.querySelectorAll('[data-graph-node]'),
  edges: document.querySelectorAll('[data-graph-edge], svg line'),
  boxes: document.querySelectorAll('svg rect'),
})

// ---------------------------------------------------------------------------
// the data layer: the claims the frames must never break
// ---------------------------------------------------------------------------

describe('G1/G2 snapshot data contract', () => {
  it('exports the two graph frames in order, each with a list and a run', () => {
    expect(GRAPH_STATES.map((s) => s.id)).toEqual(['G1', 'G2'])
    for (const s of GRAPH_STATES) {
      expect(s.label).not.toBe('')
      expect(s.title).not.toBe('')
      expect(s.caption).not.toBe('')
      expect(s.docs.map((d) => d.name)).toEqual(ALL_DOCS)
      expect(s.graphEntries.length).toBeGreaterThan(0)
      expect(s.distillation).toBeTruthy()
      // 中间列只放文档编辑器（owner 口径）：图谱帧不开画布面
      expect(s.activeSurface).toBe('doc')
      expect(s.selectedDoc).toBe(FOCUS_DOC)
    }
    // the pair is one run at two instants — 进行中 then 完成, same run id
    expect(G1.distillation!.status).toBe('running')
    expect(G2.distillation!.status).toBe('done')
    expect(G1.distillation!.id).toBe(G2.distillation!.id)
    expect(G2.distillation!.appliedAt).toBeTruthy()
    expect(G1.distillation!.appliedAt).toBeUndefined()
  })

  it('the frames stand on C2: same commit, same completed rows, clean editor', () => {
    for (const s of GRAPH_STATES) {
      expect(s.committedVersion).toBe(C2.committedVersion)
      expect(s.buffer).toBe(C2.buffer)
      expect(s.baseline).toBe(C2.baseline)
      expect(s.dirty).toBe(C2.dirty)
      expect(s.commitEnabled).toBe(C2.commitEnabled)
      expect(s.versionHistory).toEqual(C2.versionHistory)
      expect(s.fixture.docs).toEqual(C2.fixture.docs)
      // 提交之后，草稿清空是数据的，不是画出来的
      expect(s.fixture.draftVersions).toEqual([])
    }
  })

  it('G1 is G2 filtered to what had landed: 「逐条出现」 is a derivation', () => {
    const g1 = new Set(rows(G1).map((r) => r.id))
    const g2 = new Set(rows(G2).map((r) => r.id))
    expect(g1.size).toBeLessThan(g2.size)
    for (const r of rows(G1)) {
      expect(g2.has(r.id), `${r.id} appears in G1 but not in G2`).toBe(true)
      // the same entry cannot read differently in the two moments
      const later = targetOf(G2, r.id)!
      expect(later.label).toBe(r.label)
      expect(later.mark).toBe(r.mark)
      expect(later.doc).toBe(r.doc)
    }
    // the landed half is exactly the wave's landed ids
    const g1Delta = G1.fixture.graphDelta!
    for (const id of g1Delta.nodes) expect(g1.has(id)).toBe(true)
    expect(g1Delta.nodes.length).toBe(1)
    expect(g1Delta.removed).toEqual([])
    // the finished frame holds the whole wave
    expect(G2.fixture.graphDelta).toEqual(GRAPH_DELTA)
    expect(G2.fixture.graph!.nodes.length).toBe(GRAPH_WAVE.nodes.length)
  })

  it('every mark is derived from the delta — never typed per row', () => {
    for (const s of GRAPH_STATES) {
      const delta = s.fixture.graphDelta!
      const inGraph = new Set(s.fixture.graph!.nodes.map((n) => n.id))
      for (const r of rows(s)) {
        const want = delta.nodes.includes(r.id) ? 'added'
          : (delta.modified ?? []).includes(r.id) ? 'modified'
            : (delta.removed ?? []).includes(r.id) ? 'removed'
              : undefined
        expect(r.mark, `${s.id} ${r.id}`).toBe(want)
        if (r.mark === 'removed') {
          // a pruned entry is absent from the graph by contract
          expect(inGraph.has(r.id)).toBe(false)
        } else {
          expect(inGraph.has(r.id)).toBe(true)
        }
        // a row that names a doc names a doc the frame really carries
        if (r.doc) expect(ALL_DOCS).toContain(r.doc)
      }
    }
  })

  it("the run's candidates address the graph's changes, and the graph is closed", () => {
    for (const s of GRAPH_STATES) {
      const graph = s.fixture.graph!
      const delta = s.fixture.graphDelta!
      const ids = new Set(graph.nodes.map((n) => n.id))
      // every edge connects two nodes that exist on this frame
      for (const e of graph.edges) {
        expect(ids.has(e.from), `${s.id} ${e.from}`).toBe(true)
        expect(ids.has(e.to), `${s.id} ${e.to}`).toBe(true)
      }
      // every changed id is a real node (or a real removal) on this frame
      for (const id of delta.nodes) expect(ids.has(id)).toBe(true)
      for (const id of delta.modified ?? []) expect(ids.has(id)).toBe(true)
      for (const id of delta.removed ?? []) expect(ids.has(id)).toBe(false)
      // every candidate addresses one of this frame's changes
      const changed = new Set([...delta.nodes, ...(delta.modified ?? []), ...(delta.removed ?? [])])
      const candidates = s.distillation!.candidates
      expect(candidates.length).toBeGreaterThan(0)
      for (const c of candidates) expect(changed.has(c.target), `${c.id} → ${c.target}`).toBe(true)
      // …and once the run is done, EVERY change has its candidate (one story)
      if (s.distillation!.status === 'done') {
        expect(new Set(candidates.map((c) => c.target))).toEqual(changed)
      }
    }
  })

  it("G2's list IS D7's: the design slice and the 提交 slice read one wave", () => {
    expect(G2.graphEntries).toEqual(D7.graphEntries)
    // the removed entry keeps its name — a pruned node has no label of its own
    const removed = targetOf(G2, 'mod-manual-adjust')!
    expect(removed.label).toBe('人工调分模块')
    expect(removed.mark).toBe('removed')
    expect(removed.meta).toBe('mod-manual-adjust')
  })
})

// ---------------------------------------------------------------------------
// the real sidebar: the process, then the list
// ---------------------------------------------------------------------------

describe('the real ToolSidebar on the 需求图谱 tab', () => {
  it('G1: the 需求图谱 tab is lit, and the generation process is on screen', () => {
    mountFrame(G1)
    expect(screen.getByRole('tab', { name: 'Graph' }).getAttribute('aria-selected')).toBe('true')
    expect(screen.getByTestId('tool-sidebar')).toBeInTheDocument()
    // the REAL panel, on the run's own status — not a look-alike
    expect(screen.getByTestId('distill-panel')).toHaveAttribute('data-distill-status', 'running')
    expect(screen.getByTestId('distill-status-running')).toBeInTheDocument()
    // the shipped panel prints the hint while running; results arrive with done
    expect(document.querySelectorAll('[data-testid^="distill-candidate-"]')).toHaveLength(0)
    // what HAS landed is listed already — the entries, not the canvas
    expect(screen.getByTestId('graph-entry-req-purchase-approval')).toBeInTheDocument()
    expect(screen.queryByTestId('graph-entry-mod-approval-service')).toBeNull()
    expect(entryRowEls()).toHaveLength(rows(G1).length)
  })

  it('G2: done panel + the generated entries as a grouped list', () => {
    mountFrame(G2)
    expect(screen.getByTestId('distill-panel')).toHaveAttribute('data-distill-status', 'done')
    expect(screen.getByTestId('distill-status-done')).toBeInTheDocument()
    // the candidates the run extracted, each by its own testid
    for (const c of G2.distillation!.candidates) {
      expect(screen.getByTestId(`distill-candidate-${c.id}`)).toHaveAttribute('data-distill-kind', c.kind)
    }
    // the graph itself, grouped by type
    for (const label of ['需求', '文档', '模块', '本次移除']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
    expect(entryRowEls()).toHaveLength(rows(G2).length)
    const added = screen.getByTestId('graph-entry-req-purchase-approval')
    expect(within(added).getByText('Add')).toBeInTheDocument()
    expect(within(screen.getByTestId('graph-entry-req-points-earn')).getByText('Modify')).toBeInTheDocument()
    const removed = screen.getByTestId('graph-entry-mod-manual-adjust')
    expect(within(removed).getByText('Remove')).toBeInTheDocument()
    expect(removed.querySelector('.line-through')).not.toBeNull()
    // and still no canvas anywhere: the graph is text on this frame
    const canvas = canvasProbe()
    expect(canvas.view).toBeNull()
    expect(canvas.nodes).toHaveLength(0)
    expect(canvas.edges).toHaveLength(0)
    expect(canvas.boxes).toHaveLength(0)
  })

  it('the entries grow between the two frames — same rows, one moment apart', () => {
    const first = mountFrame(G1)
    const before = new Set([...entryRowEls()].map((el) => el.getAttribute('data-testid')))
    first.unmount()
    mountFrame(G2)
    const after = new Set([...entryRowEls()].map((el) => el.getAttribute('data-testid')))
    for (const id of before) expect(after.has(id), `${id} vanished by G2`).toBe(true)
    expect(after.size).toBeGreaterThan(before.size)
  })

  it('a requirement entry opens its doc (the middle column keeps the editor)', async () => {
    const { onOpenTab } = mountFrame(G2)
    await userEvent.click(within(screen.getByTestId('graph-entry-req-points-redeem')).getByText('积分兑换'))
    expect(onOpenTab).toHaveBeenCalledWith(expect.objectContaining({
      kind: 'doc', docName: FOCUS_DOC, id: `doc-${FOCUS_DOC}`,
    }))
    // a module traces to no doc → read-only text, not a button that does nothing
    expect(screen.getByTestId('graph-entry-mod-points-center').tagName).not.toBe('BUTTON')
  })

  it('without the new props the tab renders exactly what it rendered before', async () => {
    mountFrame(G2, true)
    // the demo's default tab is still 文档, and the tab itself is unchanged
    expect(screen.getByRole('tab', { name: 'Docs' }).getAttribute('aria-selected')).toBe('true')
    await userEvent.click(screen.getByRole('tab', { name: 'Graph' }))
    // the shipped drill-down: the fixture's node types, and no frame data at all
    expect(screen.getByText('Node types')).toBeInTheDocument()
    expect(screen.getByText('页面')).toBeInTheDocument()
    expect(entryRowEls()).toHaveLength(0)
    expect(screen.queryByTestId('distill-panel')).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// the renderer's identity for a graph frame (the wiring demo-states adds):
// a frame IS one by carrying the list — never by not being another kind.
// ---------------------------------------------------------------------------

describe('the graph frame identity the renderer consumes', () => {
  it('is positive: only the frames carrying a list answer true', () => {
    const isGraphState = (s: object) => 'graphEntries' in s
    expect(GRAPH_STATES.filter(isGraphState).map((s) => s.id)).toEqual(['G1', 'G2'])
    // D7 carries one too (its own slice now renders the same list)
    expect(isGraphState(D7)).toBe(true)
    // the commits frames do not, and neither do the other design frames
    expect(COMMIT_STATES.filter(isGraphState)).toHaveLength(0)
    expect(DESIGN_STATES.filter(isGraphState).map((s) => s.id)).toEqual(['D7'])
  })

  it('mounts through the same renderer shape the dock will use', () => {
    // the wiring the master adds, exercised end to end through renderStudio's
    // providers: a graph frame lights 需求图谱 and hands over its own data
    renderStudio(
      <ToolSidebar
        onOpenTab={vi.fn()}
        docs={G2.fixture.docs}
        projectId={G2.fixture.project.id}
        initialTool="graph"
        graphEntries={G2.graphEntries}
        distillation={G2.distillation}
      />,
    )
    expect(screen.getByRole('tab', { name: 'Graph' }).getAttribute('aria-selected')).toBe('true')
    expect(screen.getByTestId('distill-status-done')).toBeInTheDocument()
  })
})