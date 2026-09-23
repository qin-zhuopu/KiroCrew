// The workbench's 「最近活动」 feed (ACP-754). Rendered by BOTH surfaces —
// the demo workbench (items come from the loaded snapshot's `recentActivity`,
// where every entry is derived from that snapshot's own payloads and the
// generator re-verifies it) and the ordinary StudioWorkspace (items are
// derived from the store's own draft reads — what the top bar's query
// already fetched, so the feed never invents an activity the backend has
// not reported). The feed displays only what it is handed: an empty list
// renders the empty-state text, and 空态也是数据 — the absence is the
// snapshot's own fact, not a missing section.
import { i18nT } from '../../i18n/t'

export interface ActivityItem {
  /** seconds since epoch (the snapshot's own time unit); omitted when the
   * surface's data source does not carry one (the drafts read does not) */
  time?: number
  label: string
}

export default function RecentActivityFeed({ items }: { items: ActivityItem[] }) {
  return (
    <div
      className="flex items-center gap-3 px-4 h-[30px] shrink-0 border-b border-border bg-card overflow-x-auto text-[11px]"
      data-testid="recent-activity"
      data-activity-count={items.length}
    >
      <span className="shrink-0 font-semibold text-muted">{i18nT('apps.aiStudio.recent_activity')}</span>
      {items.length === 0 ? (
        <span className="text-muted" data-testid="recent-activity-empty">
          {i18nT('apps.aiStudio.recent_activity_empty')}
        </span>
      ) : (
        items.map((it, i) => (
          <span key={i} className="shrink-0 text-text truncate max-w-[320px]" data-testid={`recent-activity-item-${i}`}>
            {it.time !== undefined ? `${new Date(it.time * 1000).toLocaleString()} · ${it.label}` : it.label}
          </span>
        ))
      )}
    </div>
  )
}
