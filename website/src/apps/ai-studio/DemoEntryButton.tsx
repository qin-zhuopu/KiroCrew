// A visible, on-page entry into the state-direct demo (ACP-793).
//
// Before this the only way in was hand-typing `?demo=states`, which the owner
// could not find on the page. This is a small floating control that does one of
// two things from ONE button (the same element that changes form, per the
// website AGENTS "stays one element" rule — it is never a hard swap of two
// components):
//   - outside the demo: label 「演示」, clicking pushes `?demo=states` onto the
//     CURRENT path (client-side route push, no full reload), which
//     `AiStudioPage` already renders as `StateDemo`;
//   - inside the demo: label 「退出演示」, clicking drops the `demo` param and
//     the same route resolves back to the ordinary workbench / project list.
//
// The button deliberately does NOT know what the demo renders — it only owns
// the query param. So it works identically from the project list (`/workspaces`)
// and the workbench (`/workspaces/<id>/ai-studio`), because `parseDemoScenario`
// gates on the query, not the path.
//
// Dock avoidance: the demo dock (`StateDemo`) is `fixed bottom-4 right-4` and
// 340px wide, so once the demo is open a bottom-right button would sit on top of
// its controls. When (and only when) the demo is active this button shifts left
// of that band (see the `docked` branch below), and it reports its placement on
// `data-demo-entry` so the wiring is provable in the DOM without measuring
// pixels. All copy rides the i18n catalog, all colour rides design tokens
// through `<Btn primary>`, and the glyphs are `lucide-react`.
import { useLocation, useNavigate } from 'react-router-dom'
import { LogOut, Presentation } from 'lucide-react'
import { Btn } from '../../components/ui'
import { i18nT } from '../../i18n/t'
import { STATE_DEMO_SCENARIO } from './demo/runtime'

/** True when the current URL is in demo mode (`?demo=<anything>`), read straight
 * off the location so the button and the router branch never disagree. */
export function isDemoSearch(search: string): boolean {
  return new URLSearchParams(search).has('demo')
}

export default function DemoEntryButton() {
  const navigate = useNavigate()
  const location = useLocation()
  const inDemo = isDemoSearch(location.search)

  // Mutate only the `demo` key; anything else in the query is preserved so this
  // never stomps an unrelated parameter (a future `?demo=&theme=` must survive
  // an enter→exit round trip).
  const toggle = () => {
    const params = new URLSearchParams(location.search)
    if (params.has('demo')) params.delete('demo')
    else params.set('demo', STATE_DEMO_SCENARIO)
    const qs = params.toString()
    navigate(qs ? `${location.pathname}?${qs}` : location.pathname)
  }

  const label = inDemo ? i18nT('apps.aiStudio.demo_exit') : i18nT('apps.aiStudio.demo_enter')

  return (
    <Btn
      primary
      onClick={toggle}
      aria-label={label}
      data-testid="demo-entry-btn"
      // `docked` => demo is open and the button has stepped left of the dock;
      // `corner` => ordinary bottom-right placement. Test + reviewers read this.
      data-demo-entry={inDemo ? 'docked' : 'corner'}
      className={`fixed bottom-4 z-[10000] gap-1.5 rounded-full px-3.5 py-2 shadow-lg ${
        // the dock is `w-[340px]` at `right-4`; clear 340 + 16 + 16 = 372px so a
        // sliver of gutter separates them and no dock control is ever covered.
        inDemo ? 'right-[372px]' : 'right-4'
      }`}
    >
      {inDemo ? <LogOut size={15} className="lucide-inline" /> : <Presentation size={15} className="lucide-inline" />}
      {label}
    </Btn>
  )
}
