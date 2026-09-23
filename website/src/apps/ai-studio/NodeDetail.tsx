// A requirement-graph node: its properties and its edges, from the fixture
// graph. The graph will become real (built from the docs by the agent) in a
// later cut; the node/edge shape here is what that builder would emit.
//
// ACP-802 adds the fourth level of the drill-down: 类型列表 → 实例列表 →
// 实例属性 → **每条边连到的关联实例**. When the node carries `edgeLinks`, each
// edge renders as a GROUP — the edge's own sentence on top, the instances it
// lands on underneath. A node WITHOUT that data renders exactly as it always
// did: one plain-text card per edge, byte for byte. Which branch a node takes
// is its own data, never a per-screen flag.
import { Card } from '../../components/ui'
import { i18nT } from '../../i18n/t'
import { GRAPH_NODES, type GraphEdgeLink } from './fixtures'

export default function NodeDetail({ type, nodeId }: { type: string; nodeId: string }) {
  const node = GRAPH_NODES[type]?.find((n) => n.id === nodeId)
  if (!node) return null
  return (
    <div className="p-5 max-w-[820px]" data-testid="graph-node" data-node-type={type} data-node-id={nodeId}>
      <h1 className="text-[15px] font-semibold text-text-strong">{node.name}</h1>
      <p className="text-[11px] text-muted mt-0.5">
        {i18nT('apps.aiStudio.node_type')}: {type}
      </p>
      <h2 className="text-[13px] font-semibold text-text-strong mt-4 mb-2">{i18nT('apps.aiStudio.node_props')}</h2>
      <div className="grid grid-cols-[90px_1fr] gap-x-4 gap-y-1.5 text-[13px]">
        {Object.entries(node.props).map(([k, v]) => (
          <div key={k} className="contents" data-testid={`node-prop-${k}`}>
            <span className="text-muted">{k}</span>
            <span className="text-text">{v}</span>
          </div>
        ))}
      </div>
      <h2 className="text-[13px] font-semibold text-text-strong mt-4 mb-2">{i18nT('apps.aiStudio.node_edges')}</h2>
      {node.edges.map((e, i) =>
        // the edge's own line is the INDEX, in the node's own edge order, so
        // `node-edge-<n>` means the same edge on every node below this line
        node.edgeLinks ? (
          <EdgeGroup key={e} index={i} link={node.edgeLinks.find((l) => l.label === e) ?? { label: e, targets: [] }} />
        ) : (
          <Card key={e} data-testid={`node-edge-${i}`} className="!px-3 !py-2.5 !mb-2 text-[13px] text-text cursor-default">{e}</Card>
        ),
      )}
    </div>
  )
}

/** One edge read as what it connects: the sentence, then the instances it
 * lands on — 实例名 + 类型, one row each. An edge that lands on nothing is
 * still shown (its sentence), so a missing link cannot turn into a vanished
 * edge. */
function EdgeGroup({ index, link }: { index: number; link: GraphEdgeLink }) {
  return (
    <div className="mb-2 rounded-lg border border-border bg-card px-3 py-2.5" data-testid={`node-edge-${index}`}>
      <div className="text-[13px] text-text">{link.label}</div>
      {link.targets.length > 0 && (
        <>
          <div className="text-[11px] uppercase tracking-wide text-muted mt-2 mb-1">
            {i18nT('apps.aiStudio.node_edge_targets')}
          </div>
          <ul>
            {link.targets.map((t) => (
              <li key={t.id} data-testid={`node-edge-target-${t.id}`} className="flex items-baseline gap-2 text-[13px]">
                <span className="text-text">{t.name}</span>
                <span className="text-[11px] text-muted">{t.type}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}