// The real workbench's BGDD loop actions on the 需求图谱 tab (T7, ACP-851):
// 沉淀 (doc→graph candidates) → 冻结 (pin the graph version) → 重生成
// (graph→doc draft). The demo never mounts this file — its frames carry
// their own snapshot states through ToolSidebar's injection props — so every
// call here is a real studioApi call against the real store, and the button
// row lives ONLY behind the real-data seam (ToolSidebar renders it next to
// the live graph, never over a frame's entries).
//
// What each act does on success:
// * 沉淀 → POST …/distill, the run becomes the DistillPanel above the node
//   list (the shipped panel, the same component a frame injects);
// * 冻结 → the shipped FreezeControl owns the confirm dialog; a 409 is the
//   data layer's rule surfacing, shown as the freeze_duplicate hint;
// * 重生成 → POST …/regen writes the draft — the doc editor's draft machinery
//   picks it up on its next read, and a notice names the doc it touched.
// Nothing here fakes progress: a pending act disables its button; a failed
// one says so with the backend's error text.
import { useState } from 'react'
import { RefreshCw, Sparkles } from 'lucide-react'
import { Btn } from '../../components/ui'
import { i18nT } from '../../i18n/t'
import DistillPanel from './DistillPanel'
import FreezeControl from './FreezeControl'
import type { StudioApi, StudioDistillation, StudioFreeze } from './studioApi'

export default function GraphLoopPanel({ projectId, docName, api, initialFreezes, initialDistills, onActed }: {
  projectId: string
  /** the doc the loop acts on — the workbench's canonical requirement doc */
  docName: string
  api: StudioApi
  /** what the page already read; the panel keeps its own fresh state after */
  initialFreezes: StudioFreeze[]
  initialDistills: StudioDistillation[]
  /** any act that landed (a distillation, a freeze, a regen's draft) may
   * want the page to refresh its reads — optional, the panel renders
   * standalone */
  onActed?: () => void
}) {
  const [distill, setDistill] = useState<StudioDistillation | undefined>(initialDistills[0])
  const [freezes, setFreezes] = useState<StudioFreeze[]>(initialFreezes)
  const [busy, setBusy] = useState<'distill' | 'regen' | ''>('')
  const [notice, setNotice] = useState('')

  const runDistill = async () => {
    setBusy('distill')
    setNotice('')
    try {
      const r = await api.distill(projectId, docName)
      setDistill(r.distillation)
      onActed?.()
    } catch (e) {
      setNotice(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
    }
  }

  const runRegen = async () => {
    setBusy('regen')
    setNotice('')
    try {
      const r = await api.regen(projectId, docName)
      // the draft landed in the store — say WHICH doc and from WHICH graph,
      // the two facts that make the write traceable from screen
      setNotice(`${r.doc} ← ${r.generatedFrom}`)
      onActed?.()
    } catch (e) {
      setNotice(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
    }
  }

  const frozen = freezes[0]
  const doFreeze = async () => {
    // FreezeControl's confirm already names the version. The store refuses a
    // re-freeze of a held label (409); the panel says so in its own notice
    // instead of swallowing it, and never re-raises — an unhandled rejection
    // in a click handler is invisible to the user, the notice line is not.
    const version = distill?.releaseVersion || 'v1'
    try {
      const r = await api.freeze(projectId, version, docName)
      setFreezes((f) => [r.freeze, ...f])
      onActed?.()
    } catch (e) {
      setNotice(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div data-testid="graph-loop-panel">
      {distill && (
        <div className="mb-2" data-testid="graph-loop-run">
          <DistillPanel distillation={distill} />
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2 mb-1">
        <Btn onClick={runDistill} disabled={busy !== ''} data-testid="graph-distill-btn">
          <Sparkles size={13} className="lucide-inline" />
          {i18nT('apps.aiStudio.distill')}
        </Btn>
        <FreezeControl
          // once a baseline exists FreezeControl renders itself disabled —
          // the visible half of the store's 409 rule
          onFreeze={frozen ? undefined : doFreeze}
          frozen={frozen}
          version={distill?.releaseVersion || 'v1'}
        />
        <Btn onClick={runRegen} disabled={busy !== ''} data-testid="graph-regen-btn">
          <RefreshCw size={13} className="lucide-inline" />
          {i18nT('apps.aiStudio.regen')}
        </Btn>
      </div>
      {notice && (
        <div className="text-[11px] text-muted" data-testid="graph-loop-notice">{notice}</div>
      )}
    </div>
  )
}
