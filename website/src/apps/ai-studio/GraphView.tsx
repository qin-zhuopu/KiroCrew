// The requirement graph the commits feed (ACP-729), rendered as plain SVG —
// no graph library: three node kinds and two edge kinds do not justify one,
// and a hand-drawn layout keeps the demo deterministic (same snapshot, same
// pixels — a force layout would re-shuffle every remount).
//
// The component is demo-agnostic by design (§4): it receives a StudioGraph
// and an optional "new in this update" id set as PROPS and knows nothing
// about scenarios, steps or the fake. Today only the demo workbench renders
// it — the real backend has no graph endpoint yet, and an entry point in the
// ordinary workbench would advertise a feature that does not exist (the
// ToolSidebar's graph rows still read fixtures.ts). When GET …/graph lands,
// the real workspace passes real data through the same props.
import { useId } from 'react'
import { i18nT } from '../../i18n/t'
import type { StudioGraph, StudioGraphNode } from './studioApi'

// Column x for each node kind — a fixed three-column layout reads as
// "requirements feed docs feed modules" without a layout engine.
const COL_X: Record<StudioGraphNode['kind'], number> = {
  requirement: 130,
  doc: 370,
  module: 610,
}
const ROW_Y = (i: number) => 70 + i * 96
const NODE_W = 148
const NODE_H = 44

/** node fill per kind: the graph's own legend, read through CSS vars so the
 * panel follows the theme like every other surface */
const KIND_FILL: Record<StudioGraphNode['kind'], string> = {
  requirement: 'var(--accent-subtle)',
  doc: 'var(--bg-hover)',
  module: 'var(--bg-elevated)',
}

export default function GraphView({ graph, addedNodeIds, addedEdges }: {
  graph: StudioGraph
  /** nodes this snapshot's story added (the commit's contribution) — ringed
   * and exposed as data-graph-added for the ring/locator layer */
  addedNodeIds?: string[]
  /** the same for edges, each spelled "from->to" */
  addedEdges?: string[]
}) {
  const markerId = useId()
  const addedNodes = new Set(addedNodeIds ?? [])
  const addedEdgeSet = new Set(addedEdges ?? [])
  // slot index within each kind's column, in declaration order — the
  // snapshot's node order is the layout order (deterministic replay)
  const seen: Record<string, number> = {}
  const pos = new Map<string, { x: number; y: number }>()
  const nodes = graph.nodes.map((n) => {
    const i = (seen[n.kind] = (seen[n.kind] ?? -1) + 1)
    const p = { x: COL_X[n.kind], y: ROW_Y(i) }
    pos.set(n.id, p)
    return { node: n, ...p }
  })
  const maxRow = Math.max(0, ...Object.values(seen))

  return (
    <div data-testid="graph-view" className="p-4">
      <svg
        viewBox={`0 0 740 ${maxRow * 96 + 140}`}
        className="w-full max-w-[740px] h-auto"
        role="img"
        aria-label={i18nT('apps.aiStudio.tool_graph')}
      >
        <defs>
          <marker id={markerId} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L8,4 L0,8 z" fill="var(--muted)" />
          </marker>
        </defs>
        {graph.edges.map((e) => {
          const a = pos.get(e.from)
          const b = pos.get(e.to)
          if (!a || !b) return null // a dangling edge is a broken snapshot, not a render problem
          const added = addedEdgeSet.has(`${e.from}->${e.to}`)
          return (
            <line
              key={`${e.from}->${e.to}`}
              data-graph-edge={added ? 'added' : undefined}
              data-graph-edge-id={`${e.from}->${e.to}`}
              x1={a.x + NODE_W / 2}
              y1={a.y}
              x2={b.x - NODE_W / 2}
              y2={b.y}
              stroke={added ? 'var(--accent)' : 'var(--muted)'}
              strokeWidth={added ? 2.5 : 1.25}
              markerEnd={`url(#${markerId})`}
            />
          )
        })}
        {nodes.map(({ node, x, y }) => {
          const added = addedNodes.has(node.id)
          return (
            <g
              key={node.id}
              data-graph-node={node.id}
              data-graph-node-kind={node.kind}
              data-graph-added={added ? 'true' : undefined}
            >
              <rect
                x={x - NODE_W / 2}
                y={y - NODE_H / 2}
                width={NODE_W}
                height={NODE_H}
                rx={9}
                fill={KIND_FILL[node.kind]}
                stroke={added ? 'var(--accent)' : 'var(--border)'}
                strokeWidth={added ? 2.5 : 1}
              />
              <text x={x} y={y - (node.doc ? 2 : -5)} textAnchor="middle" fontSize={13} fill="var(--text)">
                {node.label}
              </text>
              {node.doc && (
                <text x={x} y={y + 13} textAnchor="middle" fontSize={10} fill="var(--muted)">
                  {node.doc}
                </text>
              )}
            </g>
          )
        })}
      </svg>
    </div>
  )
}
