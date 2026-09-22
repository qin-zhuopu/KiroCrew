// A requirement-graph node: its properties and its edges, from the fixture
// graph. The graph will become real (built from the docs by the agent) in a
// later cut; the node/edge shape here is what that builder would emit.
import { Card } from '../../components/ui'
import { i18nT } from '../../i18n/t'
import { GRAPH_NODES } from './fixtures'

export default function NodeDetail({ type, nodeId }: { type: string; nodeId: string }) {
  const node = GRAPH_NODES[type]?.find((n) => n.id === nodeId)
  if (!node) return null
  return (
    <div className="p-5 max-w-[820px]" data-testid="graph-node">
      <h1 className="text-[15px] font-semibold text-text-strong">{node.name}</h1>
      <p className="text-[11px] text-muted mt-0.5">
        {i18nT('apps.aiStudio.node_type')}: {type}
      </p>
      <h2 className="text-[13px] font-semibold text-text-strong mt-4 mb-2">{i18nT('apps.aiStudio.node_props')}</h2>
      <div className="grid grid-cols-[90px_1fr] gap-x-4 gap-y-1.5 text-[13px]">
        {Object.entries(node.props).map(([k, v]) => (
          <div key={k} className="contents">
            <span className="text-muted">{k}</span>
            <span className="text-text">{v}</span>
          </div>
        ))}
      </div>
      <h2 className="text-[13px] font-semibold text-text-strong mt-4 mb-2">{i18nT('apps.aiStudio.node_edges')}</h2>
      {node.edges.map((e) => (
        <Card key={e} className="!px-3 !py-2.5 !mb-2 text-[13px] text-text cursor-default">{e}</Card>
      ))}
    </div>
  )
}
