// The real workbench's 开发 tab (T7 step 4, ACP-851): 「开始开发」opens a
// development run whose four phases are BGDD gate stages (tasks→G2,
// implement→G3, test→G7, build→G4) executed by the backend through the
// gate's unified entry (bgdd tools/gate.ts, ACP-848). The demo never mounts
// this file — its V frames inject their snapshot runs through ToolSidebar's
// `dev` prop — so every call here is real, and the run's picture is the
// shipped DevRunPanel drawing the record the gate actually produced:
// a failed gate shows 已失败 on its phase and 待启动 on the phases that
// never ran (the gate stops at the first FAIL), never a fake all-green.
//
// The run is long (the gate runs real commands) and the backend's response
// carries the finished record, so the button stays disabled while in
// flight — progress is the record landing, not a timer inventing phases.
import { useState } from 'react'
import { Hammer } from 'lucide-react'
import { Btn } from '../../components/ui'
import { i18nT } from '../../i18n/t'
import DevRunPanel from './DevRunView'
import type { StudioApi, StudioDevRun } from './studioApi'

export default function DevLoopPanel({ projectId, api, initialRuns, onRan, designVersion }: {
  projectId: string
  api: StudioApi
  /** the runs the page already read, newest first; fresh ones prepend */
  initialRuns: StudioDevRun[]
  /** a landed run (pass or fail) may want the page to refresh its reads */
  onRan?: () => void
  /** the design this round builds — the workbench's freeze vocabulary; the
   * record names it, so the run traces back to the frozen baseline */
  designVersion: string
}) {
  const [runs, setRuns] = useState<StudioDevRun[]>(initialRuns)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')

  const start = async () => {
    if (busy) return
    setBusy(true)
    setNotice('')
    try {
      const r = await api.startDevRun(projectId, designVersion)
      setRuns((rs) => [r.run, ...rs])
      onRan?.()
    } catch (e) {
      // a 503 here is the wiring refusal ("dev runs are not wired on this
      // instance: set AI_STUDIO_BGDD_REPO…") — the operator-facing sentence
      // the backend wrote, surfaced verbatim rather than as a spinner that
      // never ends or a run that pretends to have happened
      setNotice(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const [current, ...rest] = runs
  return (
    <div data-testid="dev-loop-panel">
      <div className="mb-2">
        <Btn onClick={start} disabled={busy} data-testid="dev-start-btn">
          <Hammer size={13} className="lucide-inline" />
          {busy ? i18nT('apps.aiStudio.dev_running') : i18nT('apps.aiStudio.dev_start')}
        </Btn>
      </div>
      {notice && (
        <div className="text-[11px] text-muted mb-2" data-testid="dev-loop-notice">{notice}</div>
      )}
      {current && (
        <div data-testid="dev-loop-current">
          {/* the shipped panel, placed not re-drawn — the four phases, the
              gate log artifacts and the runnable entry are its contract */}
          <DevRunPanel run={current} />
        </div>
      )}
      {rest.length > 0 && (
        <div className="mt-2">
          <div className="text-[11px] uppercase tracking-wide text-muted mx-0.5 mb-1.5">
            {i18nT('apps.aiStudio.history')}
          </div>
          {rest.map((r) => (
            <div key={r.id} data-testid={`dev-loop-history-${r.id}`} className="text-[11px] text-muted px-2 py-1 truncate">
              {r.id} · {r.designVersion}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
