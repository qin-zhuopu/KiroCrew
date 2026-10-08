// One requirement page, read-only (ACP-2015 step 2, RFC §7 B2 / §8): the v34
// verdict bar on top, the graph-generated document below it, and the raw graph
// behind a toggle. Nothing here edits anything — 直改 is step 3 and 开始开发 is
// step 4, which is why 开始开发 ships DISABLED rather than absent (the owner
// reads the workbench with the button in place).
//
// The read re-runs every 5s: the graph is a file another person edits, and the
// owner's whole point is that the page says NOW what the graph says NOW.
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import MarkdownRenderer from '../../components/MarkdownRenderer'
import ErrorNotice from '../../components/ErrorNotice'
import { Btn } from '../../components/ui'
import { i18nT } from '../../i18n/t'
import { VERDICT_STYLE, gapCount } from './reqVerdict'
import { StudioApiError, studioApi, type StudioApi, type StudioVerdict } from './studioApi'

/** The 判定条's sentence — the full reading, not the badge's short word. */
function barText(verdict: StudioVerdict, gaps: number): string {
  if (verdict === '全齐') return i18nT('apps.aiStudio.req_bar_full')
  if (verdict === '不齐') return i18nT('apps.aiStudio.req_bar_incomplete')
  return i18nT('apps.aiStudio.req_bar_gap', { n: gaps })
}

export default function RequirementPage({ projectId, page, api = studioApi }: {
  projectId: string
  /** the page name, which IS the graph file's stem in the workspace */
  page: string
  /** data source, injectable for the demo's snapshot fake */
  api?: StudioApi
}) {
  const [gapsOpen, setGapsOpen] = useState(false)
  const [showGraph, setShowGraph] = useState(false)

  const { data, error } = useQuery({
    queryKey: ['ai-studio', 'requirement', projectId, page],
    queryFn: () => api.getRequirement(projectId, page),
    refetchInterval: 5000,
  })

  // The verdict service missing is a STATE the bar renders, not a failure strip
  // — the page still has nothing to say about readiness, and saying so in the
  // bar is the honest version of "we don't know".
  const unavailable = error instanceof StudioApiError && error.code === 'reqdoc_cmd_unavailable'
  const style = VERDICT_STYLE[data?.verdict ?? '不齐'] ?? VERDICT_STYLE['不齐']
  const gaps = data ? gapCount(data.tiers) : 0
  const groups = data
    ? ([
      ['apps.aiStudio.req_group_errors', data.errors],
      ['apps.aiStudio.req_group_missing', data.missing],
      ['apps.aiStudio.req_group_tiers', [...data.tiers.api, ...data.tiers.ui, ...data.tiers.parts]],
    ] as const).filter(([, items]) => items.length > 0)
    : []

  return (
    <div className="p-4" data-testid="requirement-page" data-page={page}>
      <div className="flex items-start justify-between gap-3 mb-3">
        {/* The bar states a readiness verdict, so it renders only once the page
            either has one (`data`) or knows why it cannot (`error`) — a bar
            that paints while the read is in flight invites a read of 「齐」
            that nobody checked. */}
        {(data || error) && (
          <div
            data-testid="req-verdict-bar"
            className={`flex-1 rounded-lg border px-3 py-2 text-[12px] font-semibold ${style.bar} ${style.strong}`}
          >
            {unavailable
              ? i18nT('apps.aiStudio.req_service_unavailable')
              : data
                ? barText(data.verdict, gaps)
                : i18nT('apps.aiStudio.req_loading')}
            {data && groups.length > 0 && (
              <button
                type="button"
                data-testid="req-gaps-toggle"
                onClick={() => setGapsOpen((v) => !v)}
                className="ml-2 font-normal underline cursor-pointer"
              >
                {i18nT(gapsOpen ? 'apps.aiStudio.req_collapse' : 'apps.aiStudio.req_expand')}
              </button>
            )}
          </div>
        )}
        <div className="flex shrink-0 items-center gap-1.5">
          {/* step 4 wires this; the affordance ships greyed so the workbench
              reads as the flow it will be */}
          <Btn data-testid="req-start" disabled title={i18nT('apps.aiStudio.req_start_todo')}>
            {i18nT('apps.aiStudio.req_start')}
          </Btn>
          <Btn
            data-testid="req-graph-toggle"
            aria-pressed={showGraph}
            onClick={() => setShowGraph((v) => !v)}
          >
            {i18nT(showGraph ? 'apps.aiStudio.req_show_doc' : 'apps.aiStudio.req_graph')}
          </Btn>
        </div>
      </div>

      {gapsOpen && groups.length > 0 && (
        <div data-testid="req-gaps" className="mb-3 rounded-lg border border-border bg-bg-elevated px-3 py-2">
          {groups.map(([key, items]) => (
            <div key={key} className="mb-2 last:mb-0">
              <div className="text-[11px] uppercase tracking-wide text-muted mb-1">{i18nT(key)}</div>
              <ul className="text-[12px] text-text list-disc pl-4">
                {items.map((item, i) => <li key={i}>{item}</li>)}
              </ul>
            </div>
          ))}
        </div>
      )}

      {!error && !data && (
        <div className="text-[12px] text-muted">{i18nT('apps.aiStudio.req_loading')}</div>
      )}
      {error && !unavailable && <ErrorNotice message={error instanceof Error ? error.message : String(error)} />}

      {data && (showGraph ? (
        <pre
          data-testid="req-graph-json"
          className="text-[11px] font-mono text-text whitespace-pre-wrap break-all rounded-lg border border-border bg-bg-elevated p-3 max-h-[70vh] overflow-auto"
        >
          {JSON.stringify(data.graph, null, 2)}
        </pre>
      ) : data.markdown === null ? (
        // v34 refuses to render an unqualified graph; the bar already says 不齐,
        // and the reasons are the same list the gaps panel holds.
        <div data-testid="req-no-markdown" className="text-[12px] text-muted">
          <div className="mb-1.5">{i18nT('apps.aiStudio.req_no_markdown')}</div>
          {data.errors.length > 0 && (
            <ul className="text-text list-disc pl-4">
              {data.errors.map((e, i) => <li key={i}>{e}</li>)}
            </ul>
          )}
        </div>
      ) : (
        <div data-testid="req-doc" className="rounded-lg border border-border bg-card p-4 max-h-[70vh] overflow-auto">
          <MarkdownRenderer content={data.markdown ?? ''} readOnlyCode />
        </div>
      ))}
    </div>
  )
}
