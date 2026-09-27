// ACP-847 (BGDD PoC T3): the graph view rendering REAL data.
//
// The witness file is __fixtures__/graph-real.json — the byte-for-byte body
// of one real `GET /api/apps/ai-studio/graph` against the aiohttp backend
// (served from the worktree's code, real routes, real graph JSON — the curl
// proof is pasted on the ticket). No hand-written graph object stands in for
// it: fetch is stubbed to answer WITH that file, so the test walks the whole
// real path — JSON body → request<T> → StudioGraph type → GraphView props →
// SVG DOM — and only the socket itself is stubbed.
//
// Assertions are DOM-only (data-testid / data-graph-* attributes), per the
// house rule: no screenshots. i18n: the suite pins the English catalog; the
// node labels are Chinese data by design and asserted as data.
import { describe, it, expect, vi, afterEach } from 'vitest'
import { screen } from '@testing-library/react'
import { render } from '@testing-library/react'

import GraphView from './GraphView'
import { studioApi } from './studioApi'
import realGraphBody from './__fixtures__/graph-real.json'

afterEach(() => vi.unstubAllGlobals())

function stubFetchWithRealBody() {
  const fetchMock = vi.fn(async (url: string) => ({
    ok: true,
    status: 200,
    json: async () => realGraphBody,
  }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('GET …/graph → studioApi.getGraph → GraphView on real data', () => {
  it('fetches the real endpoint and parses the captured real response', async () => {
    const fetchMock = stubFetchWithRealBody()
    const res = await studioApi.getGraph()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(String(fetchMock.mock.calls[0][0])).toBe('/api/apps/ai-studio/graph')
    // the captured response really carries the graph identity and 5 scenarios
    expect(res.graphId).toBe('knowledge-doc-upload-v1')
    const scenarios = res.graph.nodes.filter((n) => n.kind === 'requirement')
    expect(scenarios.map((n) => n.id)).toEqual([
      'KDU-AC-01',
      'KDU-AC-02',
      'KDU-AC-03',
      'KDU-AC-04',
      'KDU-AC-05',
    ])
    // wire-shape guards: kinds the view's layout table can actually place
    expect(new Set(res.graph.nodes.map((n) => n.kind))).toEqual(
      new Set(['requirement', 'doc', 'module']),
    )
    expect(new Set(res.graph.edges.map((e) => e.kind))).toEqual(new Set(['depends', 'trace']))
  })

  it('GraphView renders every real node and edge into the DOM', async () => {
    stubFetchWithRealBody()
    const { graph } = await studioApi.getGraph()
    render(<GraphView graph={graph} />)

    const view = await screen.findByTestId('graph-view')
    // every node from the real response is a DOM node with its real id/kind
    for (const n of graph.nodes) {
      const el = view.querySelector(`[data-graph-node="${CSS.escape(n.id)}"]`)
      expect(el, `node ${n.id}`).not.toBeNull()
      expect(el!.getAttribute('data-graph-node-kind')).toBe(n.kind)
    }
    // the 5 scenario nodes specifically (the acceptance bar: ≥5 scenarios)
    const drawn = view.querySelectorAll('[data-graph-node-kind="requirement"]')
    expect(drawn.length).toBe(5)
    // every edge renders as a line keyed by its real endpoints
    for (const e of graph.edges) {
      expect(
        view.querySelector(`[data-graph-edge-id="${CSS.escape(`${e.from}->${e.to}`)}"]`),
        `edge ${e.from}->${e.to}`,
      ).not.toBeNull()
    }
    // the Chinese labels from the graph are the rendered text (data, not chrome)
    expect(view.textContent).toContain('重复上传被拒绝')
  })
})
