// T7 (ACP-851): the ORDINARY workbench's 需求图谱 tab on real backend data.
//
// GraphView.realdata.test.tsx proves the fetch→type→canvas half; this file
// closes the half the workbench actually renders — ToolSidebar's GraphTool
// draws a text drill-down over GRAPH_NODES fixtures, and the task's edge is
// that a live GET …/graph response replaces those fixtures with the same list
// shape the demo frames already use. The witness is again the captured real
// response body (__fixtures__/graph-real.json), passed in as the `realGraph`
// prop the workspace query now feeds — no hand-written graph stands in.
//
// The demo paths are asserted to stay untouched: a frame's `entries` outrank
// the live graph, and an empty/absent graph leaves the old drill-down byte
// for byte. DOM-only assertions, no screenshots (house rule).
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import ToolSidebar from './ToolSidebar'
import type { StudioGraph } from './studioApi'
import realGraphBody from './__fixtures__/graph-real.json'

const entryRowEls = () => document.querySelectorAll<HTMLElement>('[data-testid^="graph-entry-"]')

function mountReal(graph: StudioGraph, onOpenTab = vi.fn()) {
  render(
    <ToolSidebar
      onOpenTab={onOpenTab}
      docs={[{ name: 'requirements.md', content: '# x' }]}
      projectId="p1"
      initialTool="graph"
      realGraph={graph}
    />,
  )
  return onOpenTab
}

describe('GraphTool on the real graph (T7)', () => {
  const real = realGraphBody.graph as StudioGraph

  it('renders every real node as a list row, grouped by kind', () => {
    mountReal(real)
    // 22 canvas nodes + the 20-SR semantic layer in the captured response —
    // every one gets its own row (T7 closed ACP-847's SR drop)
    expect(entryRowEls()).toHaveLength(real.nodes.length + (real.srs?.length ?? 0))
    expect(real.srs).toHaveLength(20)
    // requirement rows and module rows are present under their own groups
    expect(screen.getByTestId('graph-entry-KDU-AC-01')).toBeInTheDocument()
    expect(screen.getByTestId('graph-entry-domc:attachment-first-upload')).toBeInTheDocument()
    // the SR layer closes as its own group, each SR under its own id
    expect(screen.getByText('语义需求')).toBeInTheDocument()
    expect(screen.getByTestId('graph-entry-SR-R1-1')).toBeInTheDocument()
    // the groups read 需求 / 文档 / 模块 — the frames' own kind vocabulary
    expect(screen.getByText('需求')).toBeInTheDocument()
    expect(screen.getByText('文档')).toBeInTheDocument()
    expect(screen.getByText('模块')).toBeInTheDocument()
    // no fixture nodes leaked in
    expect(screen.queryByTestId('graph-entry-page-opportunity')).not.toBeInTheDocument()
  })

  it('a doc row whose doc exists opens the editor; a module row is not a fake button', async () => {
    const docNode = real.nodes.find((n) => n.kind === 'doc')!
    const onOpenTab = vi.fn()
    render(
      <ToolSidebar
        onOpenTab={onOpenTab}
        // the doc groups' rows name their own label as the doc; make one of
        // them a doc the workbench really has, so the row is genuinely live
        docs={[{ name: docNode.label, content: '# x' }]}
        projectId="p1"
        initialTool="graph"
        realGraph={real}
      />,
    )
    await userEvent.click(screen.getByTestId(`graph-entry-${docNode.id}`))
    expect(onOpenTab).toHaveBeenCalledWith(
      expect.objectContaining({ kind: 'doc', docName: docNode.label }),
    )
    // a module names no doc → plain text, not a button that lies
    const mod = screen.getByTestId('graph-entry-domc:attachment-first-upload')
    expect(mod.tagName).not.toBe('BUTTON')
  })

  it('a frame injects entries → the live graph never overrides the frame', () => {
    const frameEntries = [{ label: '需求', rows: [{ id: 'frame-only', label: '帧内节点' }] }]
    render(
      <ToolSidebar
        onOpenTab={vi.fn()}
        docs={[]}
        projectId="p1"
        initialTool="graph"
        graphEntries={frameEntries}
        realGraph={real}
      />,
    )
    expect(screen.getByTestId('graph-entry-frame-only')).toBeInTheDocument()
    expect(screen.queryByTestId('graph-entry-KDU-AC-01')).not.toBeInTheDocument()
  })

  it('the page-passed graphLoop sits above the list on the graph tab only', async () => {
    const user = userEvent.setup()
    render(
      <ToolSidebar
        onOpenTab={vi.fn()}
        docs={[]}
        projectId="p1"
        initialTool="graph"
        realGraph={real}
        graphLoop={<div data-testid="graph-loop-stub" />}
      />,
    )
    // the graph tab is open: the row is placed, above the entry list
    const stub = screen.getByTestId('graph-loop-stub')
    const firstEntry = screen.getByTestId('graph-entry-KDU-AC-01')
    expect(stub.compareDocumentPosition(firstEntry) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    // another tab does not show it
    await user.click(screen.getByRole('tab', { name: 'Docs' }))
    expect(screen.queryByTestId('graph-loop-stub')).not.toBeInTheDocument()
  })

  it('an empty live graph keeps the fixture drill-down (never blank)', () => {
    render(
      <ToolSidebar
        onOpenTab={vi.fn()}
        docs={[]}
        projectId="p1"
        initialTool="graph"
        realGraph={{ nodes: [], edges: [] }}
      />,
    )
    // the type list is what shipped: 节点类型 section over GRAPH_NODES keys
    expect(screen.getByText('页面')).toBeInTheDocument()
    expect(entryRowEls()).toHaveLength(0)
  })
})
