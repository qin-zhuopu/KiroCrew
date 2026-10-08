// The right column's 需求 tab (ACP-2015 step 2, RFC §7 B1): one row per page of
// the workspace's docs/需求图谱, each carrying the v34 verdict and its update
// time, and each row opening that page read-only in the center column.
//
// The read lives HERE, not in ToolSidebar, on purpose: every other tab's data
// is passed down or injected (the demo frames carry their own), while this one
// is a live workspace read — the same shape ProjectCommitBar owns for the 提交
// tab. So ToolSidebar keeps placing components and keeps knowing nothing about
// requirement graphs.
import { useQuery } from '@tanstack/react-query'
import ErrorNotice from '../../components/ErrorNotice'
import { fmtDateTimeNumeric } from '../../i18n/format'
import { i18nT } from '../../i18n/t'
import { VERDICT_STYLE, verdictBadgeText } from './reqVerdict'
import { studioApi, type StudioApi } from './studioApi'
import type { WorkTab } from './WorkArea'

export default function RequirementsTool({ projectId, api = studioApi, onOpenTab }: {
  projectId: string
  /** data source, injectable for the demo's snapshot fake */
  api?: StudioApi
  onOpenTab: (tab: WorkTab) => void
}) {
  // No polling: the center page polls its own page every 5s, and this list
  // refreshes on mount/focus, which is when a new page would be noticed.
  const { data, error, isLoading } = useQuery({
    queryKey: ['ai-studio', 'requirements', projectId],
    queryFn: () => api.listRequirements(projectId).then((r) => r.pages),
  })
  const pages = data ?? []

  return (
    <div data-testid="req-list">
      {error && (
        <ErrorNotice message={error instanceof Error ? error.message : String(error)} />
      )}
      {isLoading && !error && (
        <div className="text-[12px] text-muted px-1 py-2">{i18nT('apps.aiStudio.req_loading')}</div>
      )}
      {/* the empty state is a CONCLUSION (this workspace holds no graphs), so
          it waits for the read: painting it mid-flight tells someone their
          project has no requirements when the answer is still arriving */}
      {!error && !isLoading && pages.length === 0 && (
        <div className="text-[12px] text-muted px-1 py-2">{i18nT('apps.aiStudio.req_empty')}</div>
      )}
      {pages.map((p) => {
        const style = VERDICT_STYLE[p.verdict] ?? VERDICT_STYLE['不齐']
        return (
          <button
            key={p.page}
            type="button"
            data-testid={`req-row-${p.page}`}
            onClick={() => onOpenTab({ id: `req-${p.page}`, kind: 'req', title: p.page, page: p.page })}
            className="w-full text-left rounded-lg border border-border bg-card px-3 py-2.5 mb-2 transition-colors hover:border-accent cursor-pointer"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-[12px] font-semibold text-text truncate">{p.page}</span>
              <span
                data-testid={`req-verdict-${p.page}`}
                className={`shrink-0 rounded-full px-1.5 py-0.5 text-[10px] ${style.badge}`}
              >
                {verdictBadgeText(p.verdict)}
              </span>
            </div>
            <div className="text-[11px] text-muted mt-1">
              {fmtDateTimeNumeric(p.updatedAt)}
              {p.missingCount > 0 && <> · {i18nT('apps.aiStudio.req_missing_n', { n: p.missingCount })}</>}
            </div>
          </button>
        )
      })}
    </div>
  )
}
