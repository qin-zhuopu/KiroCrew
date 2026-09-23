// A visible, on-page entry into the state-direct demo (ACP-793).
//
// Before this the only way in was hand-typing `?demo=states`, which the owner
// could not find on the page. This is a small floating control that pushes
// `?demo=states` onto the CURRENT path (client-side route push, no full
// reload), which `AiStudioPage` renders as the workbench's demo mode.
//
// ONCE THE STATE DEMO IS OPEN THIS BUTTON IS NOT THERE AT ALL (owner, ACP-794):
// it used to flip to 「退出演示」 and step left of the dock. The owner asked
// for one exit and only one — the dock's own ✕ in its top-right — so the state
// demo running and this button showing are mutually exclusive states, and the
// component returns null rather than rendering a second, competing exit.
//
// The OTHER demo line (`?demo=<script>`, the step-replay surface) keeps its
// exit form: that surface has no close control of its own, so removing the
// exit here would leave a visitor with no way back but editing the URL. Only
// the state demo — the one whose dock now owns the ✕ — loses it.
//
// The button deliberately does NOT know what the demo renders — it only owns
// the query param. So it works identically from the project list (`/workspaces`)
// and the workbench (`/workspaces/<id>/ai-studio`), because `parseDemoScenario`
// gates on the query, not the path. All copy rides the i18n catalog, all colour
// rides design tokens through `<Btn primary>`, and the glyphs are
// `lucide-react`.
import { useLocation, useNavigate } from 'react-router-dom'
import { LogOut, Presentation } from 'lucide-react'
import { Btn } from '../../components/ui'
import { i18nT } from '../../i18n/t'
import { STATE_DEMO_SCENARIO } from './demo/runtime'

export default function DemoEntryButton({ demoTarget }: {
  /** The path the demo opens ON. On a workbench that is the current path —
   * entering is a query-only switch, so the page (and its loaded project) stays
   * put. On the project LIST there is no project page to take over, so the
   * caller passes the representative project's workbench path and the click
   * navigates there once, the ordinary way. `undefined` = this page has
   * nothing the demo could take over (an empty project list) → no button. */
  demoTarget?: string
}) {
  const navigate = useNavigate()
  const location = useLocation()
  const scenario = new URLSearchParams(location.search).get('demo')
  // The state demo is on: its dock's ✕ is the only way out (owner 口径), so
  // this button leaves the screen entirely instead of competing with it.
  if (scenario === STATE_DEMO_SCENARIO) return null

  // Mutate only the `demo` key; anything else in the query is preserved so this
  // never stomps an unrelated parameter (a future `?demo=&theme=` must survive
  // the round trip).
  const setDemo = (on: boolean) => {
    const params = new URLSearchParams(location.search)
    if (on) params.set('demo', STATE_DEMO_SCENARIO)
    else params.delete('demo')
    const qs = params.toString()
    navigate(on ? `${demoTarget}?${qs}` : qs ? `${location.pathname}?${qs}` : location.pathname)
  }

  // A demo of the other line (the step-replay scripts): keep its exit — that
  // surface ships no close control of its own.
  if (scenario !== null) {
    return (
      <Btn
        onClick={() => setDemo(false)}
        aria-label={i18nT('apps.aiStudio.demo_exit')}
        data-testid="demo-entry-btn"
        data-demo-entry="corner"
        className="fixed bottom-4 right-4 z-[10000] gap-1.5 rounded-full px-3.5 py-2 shadow-lg"
      >
        <LogOut size={15} className="lucide-inline" />
        {i18nT('apps.aiStudio.demo_exit')}
      </Btn>
    )
  }

  // Nothing this page could take over (no project to open the demo on).
  if (!demoTarget) return null

  return (
    <Btn
      primary
      onClick={() => setDemo(true)}
      aria-label={i18nT('apps.aiStudio.demo_enter')}
      data-testid="demo-entry-btn"
      data-demo-entry="corner"
      className="fixed bottom-4 right-4 z-[10000] gap-1.5 rounded-full px-3.5 py-2 shadow-lg"
    >
      <Presentation size={15} className="lucide-inline" />
      {i18nT('apps.aiStudio.demo_enter')}
    </Btn>
  )
}
