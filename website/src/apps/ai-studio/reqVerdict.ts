// The verdict → copy-and-colour table the requirement pages share (ACP-2015
// step 2). One table on purpose: the sidebar row's badge and the center page's
// verdict bar must say the same thing about the same verdict, and the owner's
// reading of the three v34 states is a product decision, not a per-component
// guess. Colours are theme classes (never a literal), per `lint:theme-colors`.
import { i18nT } from '../../i18n/t'
import type { StudioVerdict } from './studioApi'

export interface VerdictStyle {
  /** the badge's classes (a pill on a sidebar row) */
  badge: string
  /** the verdict bar's classes (a full-width strip above the doc) */
  bar: string
  /** the bar's text colour, for the count inside it */
  strong: string
}

export const VERDICT_STYLE: Record<StudioVerdict, VerdictStyle> = {
  // 全齐 = green. `accent` is ai-studio's green (the freeze badge and the
  // publish state pill both use it); `ok` is the same semantic in the house
  // palette and is what code-review-sage's status pill uses.
  全齐: {
    badge: 'bg-ok-subtle text-ok',
    bar: 'border-ok bg-ok-subtle',
    strong: 'text-ok',
  },
  可以开工但有已知缺口: {
    badge: 'bg-warn-subtle text-warn',
    bar: 'border-warn bg-warn-subtle',
    strong: 'text-warn',
  },
  不齐: {
    badge: 'bg-danger-subtle text-danger',
    bar: 'border-danger bg-danger-subtle',
    strong: 'text-danger',
  },
}

/** The badge's SHORT word. The verdict itself is three Chinese phrases long
 * ('可以开工但有已知缺口'), which reads badly inside a pill; the bar carries the
 * full sentence. */
const BADGE_KEY: Record<StudioVerdict, string> = {
  全齐: 'apps.aiStudio.req_verdict_full',
  可以开工但有已知缺口: 'apps.aiStudio.req_verdict_gap_short',
  不齐: 'apps.aiStudio.req_verdict_incomplete',
}

export function verdictBadgeText(verdict: StudioVerdict): string {
  return i18nT(BADGE_KEY[verdict])
}

/** How many known gaps the 「有缺口」 sentence quotes: the three tier lists,
 * which is what 「可以开工但有已知缺口」 counts (errors and missing belong to
 * 「不齐」's own reasons). */
export function gapCount(tiers: { api: string[]; ui: string[]; parts: string[] }): number {
  return tiers.api.length + tiers.ui.length + tiers.parts.length
}
