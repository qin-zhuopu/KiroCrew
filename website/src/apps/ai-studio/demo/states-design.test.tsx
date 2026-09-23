// ACP-790: the D6~D8 design-phase contract.
//
// WHY THIS SHAPE: the renderer (`StateDemo.tsx`) draws only list/doc/diff
// today — the versionHistory/graph branches are the master's wiring step —
// so asserting the frames "through the dock" is impossible from this file
// without touching a public file. The contract the outline pins is a TESTID
// and COPY contract against the REAL components this story feeds
// (DocEditor's version-history popover, GraphView, RegenDiffPair,
// ProjectCommitBar), so this test mounts exactly those, with exactly the
// data each snapshot carries, and asserts on the shipped business DOM. When
// the master adds the render branches, these components are what they will
// render — a frame cannot pass this test and fail the wired one on the same
// data. Plus the pure-data layer (parity discipline, wave closure,
// diff-slice provenance) a renderer cannot fix if the data lies.
//
// ZERO FETCHES (§5): every read here runs on `createDemoApi`'s in-memory
// fake; the global fetch spy is the external witness. No screenshots, DOM
// assertions only. i18n: tests pin the English catalog (like DocEditor.test),
// so badge COPY asserts read the en labels; the doc content is Chinese data.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import DocEditor from '../DocEditor'
import GraphView from '../GraphView'
import { RegenDiffPair } from '../RegenDiffView'
import ProjectCommitBar from '../ProjectCommitBar'
import { renderStudio } from '../testUtils'
import { createDemoApi } from './runtime'
import { DESIGN_STATES } from './states-design'
// read-only imports: the pre-commit world for a positive control (the drafts
// badge DOES render when drafts exist), and the `StateSnapshot` type. Nothing
// here mutates or rewrites those modules. The pre-commit world is C1 (the
// 提交-tab frame that opens the same iteration a step earlier); the three
// opening frames it used to come from were retired by the owner in ACP-794.
import { COMMIT_STATES } from './states-commit'
import type { StateSnapshot } from './states'

const C1 = COMMIT_STATES.find((s) => s.id === 'C1')!

const byId = (id: string): StateSnapshot => {
  const s = DESIGN_STATES.find((x) => x.id === id)
  if (!s) throw new Error(`state ${id} missing from DESIGN_STATES`)
  return s
}
const D6 = byId('D6')
const D7 = byId('D7')
const D8 = byId('D8')

const FOCUS_DOC = '产品需求设计文档.md'
const JOURNEY_DOC = '用户旅程设计.md'
const MODEL_DOC = '业务模型设计.md'
const PAGE_DOC = '页面交互设计.md'

let fetchSpy: ReturnType<typeof vi.spyOn>
beforeEach(() => {
  window.localStorage.clear()
  fetchSpy = vi.spyOn(globalThis, 'fetch')
})
afterEach(() => {
  expect(fetchSpy).not.toHaveBeenCalled()
  fetchSpy.mockRestore()
})

/** mount DocEditor on a frame's own snapshot fake, at the frame's committed
 * content for `docName` — exactly what the master's wiring will hand it. */
async function mountEditorAtCommitted(state: StateSnapshot, docName: string) {
  const content = state.fixture.docs.find((d) => d.name === docName)?.content ?? ''
  renderStudio(
    <DocEditor
      projectId={state.fixture.project.id}
      docName={docName}
      initialContent={content}
      api={createDemoApi(state.fixture)}
    />,
  )
  return screen.findByTestId(`doc-${docName}`)
}

/** open the version-history popover (the real Radix trigger) and return the
 * real rows list — the outline's `version-history-list`. The trigger only
 * enables once the versions query lands, so wait on it, not on a race. */
async function openVersionHistory(doc: HTMLElement) {
  const verBtn = within(doc).getByRole('button', { name: /Version history/i })
  await waitFor(() => expect(verBtn).toBeEnabled())
  await userEvent.click(verBtn)
  return screen.findByTestId('version-history-list')
}

// ---------------------------------------------------------------------------
// the data layer: the rules the frames must never break
// ---------------------------------------------------------------------------

describe('D6~D8 snapshot data contract', () => {
  it('exports the three design frames in outline order', () => {
    expect(DESIGN_STATES.map((s) => s.id)).toEqual(['D6', 'D7', 'D8'])
    expect(DESIGN_STATES.map((s) => s.outlineRef)).toEqual(['D6', 'D7', 'D8'])
    for (const s of DESIGN_STATES) {
      expect(s.phase).toBe('design')
      expect(s.label).not.toBe('')
      expect(s.title).not.toBe('')
      expect(s.caption).not.toBe('')
      // the outline's four docs, Chinese names, on every frame
      expect(s.docs.map((d) => d.name)).toEqual([FOCUS_DOC, JOURNEY_DOC, MODEL_DOC, PAGE_DOC])
    }
  })

  it('parity discipline (附一) holds for EVERY version row of EVERY frame', () => {
    const check = (r: { version?: string; parity?: string; source?: string }, where: string) => {
      expect(r.version, where).toBeTruthy()
      const n = Number((r.version as string).slice(1))
      const want = n % 2 === 1 ? 'odd' : 'even'
      expect(r.parity, `${where} ${r.version}`).toBe(want)
      expect(r.source, `${where} ${r.version}`).toBe(want === 'odd' ? 'manual' : 'regen')
    }
    for (const s of DESIGN_STATES) {
      s.versionHistory?.forEach((r) => check(r, `${s.id} versionHistory`))
      for (const [doc, rows] of Object.entries(s.fixture.versions)) {
        rows.forEach((r) => check(r, `${s.id} fixture.versions[${doc}]`))
      }
    }
  })

  it('D6 is the committed frame: clean buffer, no drafts, v5 first in history', () => {
    expect(D6.dirty).toBe(false)
    expect(D6.diffBadge).toBe(false)
    expect(D6.commitEnabled).toBe(false)
    expect(D6.workingVersionLabel).toBe('')
    expect(D6.buffer).toBe(D6.baseline)
    expect(D6.committedVersion).toBe('V5')
    expect(D6.docs[0].version).toBe('V5')
    // the fake agrees with the markers: no draft records, and the committed
    // doc content IS the buffer (this is what disables the commit button)
    expect(D6.fixture.draftVersions).toHaveLength(0)
    const committed = D6.fixture.docs.find((d) => d.name === FOCUS_DOC)?.content
    expect(committed).toBe(D6.buffer)
    // the trail is newest-first and its newest row is the new odd/manual v5
    const trail = D6.fixture.versions[FOCUS_DOC]
    expect(trail[0].version).toBe('v5')
    expect(trail[0].parity).toBe('odd')
    expect(trail[0].source).toBe('manual')
    expect(D6.versionHistory?.[0]).toMatchObject({ version: 'v5', parity: 'odd', source: 'manual' })
    // the v5 row's diff carries the supplement the S2/S3 buffer held
    expect(trail[0].diff).toContain('大额采购需追加一级审批')
    // the frame continues the design-phase world, it does not restart it: the
    // pending buffer C1 carries is exactly this frame's committed text
    expect(C1.buffer).toBe(D6.buffer)
  })

  it('D7 names its own wave: added ∈ graph, removed ∉ graph, edges resolve', () => {
    expect(D7.activeSurface).toBe('graph')
    expect(D7.graphNote).not.toBe('')
    const graph = D7.fixture.graph
    const delta = D7.fixture.graphDelta
    expect(graph).toBeTruthy()
    expect(delta).toBeTruthy()
    const ids = new Set(graph!.nodes.map((n) => n.id))
    // all four wave kinds the outline lists are present, or the frame would
    // silently not show a highlight class it claims
    expect(delta!.nodes.length).toBeGreaterThan(0) // 新增
    expect((delta!.modified ?? []).length).toBeGreaterThan(0) // 修改
    expect((delta!.removed ?? []).length).toBeGreaterThan(0) // 移除
    expect(delta!.edges.length).toBeGreaterThan(0) // 新增边
    for (const id of delta!.nodes) expect(ids.has(id)).toBe(true)
    for (const id of delta!.modified ?? []) expect(ids.has(id)).toBe(true)
    for (const id of delta!.removed ?? []) expect(ids.has(id)).toBe(false)
    const edges = new Set(graph!.edges.map((e) => `${e.from}->${e.to}`))
    for (const e of delta!.edges) {
      expect(edges.has(e)).toBe(true)
      const [from, to] = e.split('->')
      expect(ids.has(from)).toBe(true)
      expect(ids.has(to)).toBe(true)
    }
  })

  it('D8: three downstream docs each gain an EVEN regen row; review data closes', () => {
    const v = D8.fixture.versions
    expect(v[JOURNEY_DOC][0]).toMatchObject({ version: 'v4', parity: 'even', source: 'regen' })
    expect(v[MODEL_DOC][0]).toMatchObject({ version: 'v2', parity: 'even', source: 'regen' })
    expect(v[PAGE_DOC][0]).toMatchObject({ version: 'v4', parity: 'even', source: 'regen' })
    // the doc list labels moved with them
    expect(D8.docs.map((d) => d.version)).toEqual(['V5', 'V4', 'V2', 'V4'])
    // the committed contents ARE the regenerated texts (badge follows content)
    for (const name of [JOURNEY_DOC, MODEL_DOC, PAGE_DOC]) {
      expect(v[name][0].name).toBe(`${v[name][0].time}.md`)
      const doc = D8.fixture.docs.find((d) => d.name === name)
      expect(doc?.content).toContain('图谱反生')
    }
    // distillation applied, and the regeneration names it
    expect(D8.fixture.distillation?.status).toBe('done')
    expect(D8.fixture.distillation?.appliedAt).toBeTruthy()
    expect(D8.fixture.regeneration?.generatedFrom).toBe(D8.fixture.distillation?.id)
    // every group pairs against a real candidate of that run
    const candidateIds = new Set((D8.fixture.distillation?.candidates ?? []).map((c) => c.id))
    const groups = D8.fixture.diffGroups ?? []
    expect(groups.length).toBeGreaterThan(0)
    for (const g of groups) {
      expect(candidateIds.has(g.candidateId)).toBe(true)
      for (const c of g.structuredChanges) expect(candidateIds.has(c.id)).toBe(true)
    }
    // diff-slice provenance (the check_regen doctrine): every line a group
    // shows was sliced out of THIS fixture's own version rows — user lines
    // from the focus doc's trail, regen lines from the downstream trails.
    const focusDiff = v[FOCUS_DOC].map((r) => r.diff).join('')
    const downDiff = [JOURNEY_DOC, MODEL_DOC, PAGE_DOC].flatMap((d) => v[d].map((r) => r.diff)).join('')
    const plusLines = (patch: string) =>
      patch.split('\n').filter((l) => l.startsWith('+') && l !== '+++ current')
    for (const g of groups) {
      for (const l of plusLines(g.userDiff)) expect(focusDiff).toContain(l)
      for (const l of plusLines(g.regenDiff)) expect(downDiff).toContain(l)
    }
  })
})

// ---------------------------------------------------------------------------
// the real-component layer: the testids and copy the outline pins, rendered
// by the shipped components on this data
// ---------------------------------------------------------------------------

describe('D6 on the real version-history / commit surfaces', () => {
  it('editor stands clean on the new baseline: no dirty, diff gray, v5 row odd/manual', async () => {
    const doc = await mountEditorAtCommitted(D6, FOCUS_DOC)
    expect(doc).toHaveAttribute('data-doc-dirty', 'false')
    // the counts ride the queries — wait for the reads to land, not for the
    // first paint, so 0 is never mistaken for the settled value
    await waitFor(() => expect(doc).toHaveAttribute('data-version-count', '5'))
    expect(doc).toHaveAttribute('data-draft-count', '0')
    expect(screen.getByTestId('diff-btn')).toBeDisabled()
    const list = await openVersionHistory(doc)
    const v5 = within(list).getByTestId('version-row-v5')
    expect(v5).toHaveAttribute('data-version-parity', 'odd')
    expect(v5).toHaveAttribute('data-version-source', 'manual')
    // 奇数版=人工修改 徽章 — the en catalog copy the component ships
    expect(within(v5).getByTestId('version-source-v5')).toHaveTextContent('Manual commit · odd')
    // the row BELOW is an even row, and it carries the regen provenance —
    // parity is read from data everywhere, never invented by the view
    const v4 = within(list).getByTestId('version-row-v4')
    expect(v4).toHaveAttribute('data-version-parity', 'even')
    expect(v4).toHaveAttribute('data-version-source', 'regen')
    expect(within(v4).getByTestId('version-source-v4')).toHaveTextContent('Graph regen · even')
  })

  it('commit affordance reads the frame as clean: drafts-pending not in DOM, button disabled', async () => {
    // POSITIVE CONTROL first: the same bar on the C1 (dirty) fixture DOES
    // render the badge and enable — so the clean-frame absence below is a
    // rendered fact about D6's data, not an always-true query.
    const dirty = renderStudio(
      <ProjectCommitBar projectId={C1.fixture.project.id} api={createDemoApi(C1.fixture)} />,
    )
    await screen.findByTestId('drafts-pending')
    await waitFor(() => expect(screen.getByTestId('commit-all-btn')).toBeEnabled())
    dirty.unmount()

    renderStudio(
      <ProjectCommitBar projectId={D6.fixture.project.id} api={createDemoApi(D6.fixture)} />,
    )
    const btn = await screen.findByTestId('commit-all-btn')
    await waitFor(() => expect(btn).toBeDisabled())
    // let the drafts read settle, then: the badge NEVER enters the DOM
    await new Promise((r) => setTimeout(r, 50))
    expect(screen.queryByTestId('drafts-pending')).toBeNull()
    expect(btn).toBeDisabled()
  })

  it('the publish list gains its row from the SAME data (documented seam)', () => {
    // 08-publish's PublishVersionList reads publishApi, which studioApi
    // deliberately does NOT let the demo fake ("the demo never fakes a
    // publish entry"). The outline's 「发布页签版本列表同步多一行」 is
    // therefore pinned HERE at its source: the committed trail this frame
    // hands the app carries v5 — the release-tab wiring lists one more row
    // than the pre-commit frames held. DOM-level wiring is the master's step.
    expect(D6.fixture.versions[FOCUS_DOC].some((r) => r.version === 'v5')).toBe(true)
    // the pre-commit frame (C1) had no v5 row at all
    expect(C1.fixture.versions[FOCUS_DOC].some((r) => r.version === 'v5')).toBe(false)
  })
})

describe('D7 on the real GraphView', () => {
  it('added=rings solid, modified=rings dashed, removed=struck row, added edges marked', () => {
    const graph = D7.fixture.graph!
    const delta = D7.fixture.graphDelta!
    renderStudio(
      <GraphView
        graph={graph}
        addedNodeIds={delta.nodes}
        addedEdges={delta.edges}
        modifiedNodeIds={delta.modified}
        removedNodeIds={delta.removed}
      />,
    )
    expect(screen.getByTestId('graph-view')).toBeInTheDocument()
    // 新增节点: 实线亮框 — accent stroke, NO dash pattern
    const added = document.querySelector<SVGGElement>('[data-graph-node="req-purchase-approval"]')
    expect(added).not.toBeNull()
    expect(added).toHaveAttribute('data-graph-added', 'true')
    const addedRect = added!.querySelector('rect')!
    expect(addedRect).toHaveAttribute('stroke', 'var(--accent)')
    expect(addedRect.getAttribute('stroke-dasharray')).toBeNull()
    // 修改节点: 虚线亮框 — the OTHER stroke, so the two read differently
    const modified = document.querySelector<SVGGElement>('[data-graph-node="req-points-earn"]')
    expect(modified).toHaveAttribute('data-graph-modified', 'true')
    const modRect = modified!.querySelector('rect')!
    expect(modRect).toHaveAttribute('stroke', 'var(--accent)')
    expect(modRect).toHaveAttribute('stroke-dasharray', '6 4')
    // an untouched node keeps the plain border ring
    const plain = document.querySelector<SVGGElement>('[data-graph-node="req-points-redeem"]')!
    expect(plain.querySelector('rect')).toHaveAttribute('stroke', 'var(--border)')
    // 新增边: data-graph-edge="added" on exactly the delta's edges
    const addedEdges = document.querySelectorAll('line[data-graph-edge="added"]')
    expect(addedEdges).toHaveLength(delta.edges.length)
    for (const e of delta.edges) {
      expect(document.querySelector(`line[data-graph-edge-id="${e}"][data-graph-edge="added"]`)).not.toBeNull()
    }
    // 移除: 删除线行 under the canvas
    const removedRow = screen.getByTestId('graph-removed-row')
    expect(removedRow).toHaveTextContent('Removed:')
    for (const id of delta.removed ?? []) {
      expect(removedRow.querySelector(`[data-graph-removed="${id}"]`)).not.toBeNull()
    }
    expect(removedRow.querySelector('.line-through')).not.toBeNull()
  })
})

describe('D8 on the real RegenDiffPair + downstream history', () => {
  it('成组 Diff 三段 renders with its group count and per-row testids', () => {
    const groups = D8.fixture.diffGroups!
    renderStudio(<RegenDiffPair groups={groups} />)
    const pair = screen.getByTestId('regen-diff-pair')
    expect(pair).toHaveAttribute('data-diff-group-count', String(groups.length))
    expect(pair).toHaveTextContent('Paired diff review')
    for (const g of groups) {
      const row = within(pair).getByTestId(`diff-group-row-${g.candidateId}`)
      expect(row).toHaveAttribute('data-group-point', g.point)
      expect(within(row).getByText(g.point)).toBeInTheDocument()
      for (const c of g.structuredChanges) {
        expect(within(row).getByTestId(`diff-group-change-${c.id}`)).toHaveAttribute('data-distill-kind', c.kind)
      }
      // the primary flag is derivation, not wish: user AND regen non-empty
      const primary = g.userDiff !== '' && g.regenDiff !== ''
      expect(row).toHaveAttribute('data-group-primary', primary ? 'true' : 'false')
      // an empty side shows as empty — data, not a gap (ACP-734)
      const empties = Number(g.userDiff === '') + Number(g.regenDiff === '')
      expect(row.querySelectorAll('[data-diff-group-empty="true"]')).toHaveLength(empties)
    }
  })

  it('a downstream doc opens on its NEW even row, badge 图谱反生', async () => {
    const doc = await mountEditorAtCommitted(D8, JOURNEY_DOC)
    expect(doc).toHaveAttribute('data-doc-dirty', 'false')
    const list = await openVersionHistory(doc)
    const v4 = within(list).getByTestId('version-row-v4')
    expect(v4).toHaveAttribute('data-version-parity', 'even')
    expect(v4).toHaveAttribute('data-version-source', 'regen')
    expect(within(v4).getByTestId('version-source-v4')).toHaveTextContent('Graph regen · even')
    // the rows below keep their own provenance: v3 manual, v2 regen, v1 manual
    expect(within(list).getByTestId('version-row-v3')).toHaveAttribute('data-version-source', 'manual')
    expect(within(list).getByTestId('version-row-v2')).toHaveAttribute('data-version-source', 'regen')
    expect(within(list).getByTestId('version-row-v1')).toHaveAttribute('data-version-source', 'manual')
  })
})
