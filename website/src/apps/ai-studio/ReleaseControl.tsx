// The workspace top bar's project-level long-running acts (ACP-730's 发版,
// ACP-733's 开始沉淀), shaped like ProjectCommitBar: one control, both
// surfaces, the callback seam doing the work. The real path has no release
// or distillation endpoint yet, so StudioWorkspace does not render this at
// all — an enabled button whose click goes nowhere is exactly the fake
// feature the doctrine forbids. The demo workbench renders it and passes an
// onRelease that lands on the step's declared snapshot, with `phases`
// carrying the labels of the story it walks while that lands (解析图谱 →
// 生成文件清单 → 完成): labels IN, logic untouched — the control never
// invents phases, and an act without phases just reads "…ing" until it
// lands (the distill click resolves straight into the snapshot's own
// running state).
import { useCallback, useEffect, useRef, useState } from 'react'
import { BrainCircuit, Rocket } from 'lucide-react'
import { Btn } from '../../components/ui'
import { i18nT } from '../../i18n/t'

export default function ReleaseControl({ onRelease, phases, phaseMs = 600, disabled = false, act = 'release' }: {
  /** performs the act; the panel switches when this resolves */
  onRelease: () => Promise<void>
  /** labels shown while pending (demo passes three for release; distill
   * passes none and gets the single pending label) */
  phases?: string[]
  /** dwell per phase label; one cycle through the list, then it holds on
   * the last until onRelease resolves */
  phaseMs?: number
  disabled?: boolean
  /** which top-bar act this button is: the testid, labels and icon come from
   * that act's keys, the walk mechanics are shared */
  act?: 'release' | 'distill'
}) {
  const [pending, setPending] = useState(false)
  const [phase, setPhase] = useState(0)
  const aliveRef = useRef(true)
  useEffect(() => { aliveRef.current = true; return () => { aliveRef.current = false } }, [])

  // the walk is presentational and self-stopping: a step change unmounts
  // this control, and the timer checks liveness before touching state
  useEffect(() => {
    if (!pending || !phases || phases.length === 0) return
    const iv = window.setInterval(() => setPhase((p) => Math.min(p + 1, phases.length - 1)), phaseMs)
    return () => window.clearInterval(iv)
  }, [pending, phases, phaseMs])

  const release = useCallback(async () => {
    if (pending) return
    setPending(true)
    setPhase(0)
    try {
      await onRelease()
    } finally {
      if (aliveRef.current) setPending(false)
    }
  }, [pending, onRelease])

  const label = pending
    ? (phases?.[phase] ?? i18nT(act === 'distill' ? 'apps.aiStudio.distill_running' : 'apps.aiStudio.releasing'))
    : i18nT(act === 'distill' ? 'apps.aiStudio.distill' : 'apps.aiStudio.release')
  const Icon = act === 'distill' ? BrainCircuit : Rocket

  return (
    <Btn
      onClick={release}
      disabled={disabled || pending}
      data-testid={act === 'distill' ? 'distill-btn' : 'release-btn'}
      data-release-pending={pending ? 'true' : undefined}
      title={i18nT(act === 'distill' ? 'apps.aiStudio.distill_hint' : 'apps.aiStudio.release_hint')}
    >
      <Icon size={13} className="lucide-inline" />
      {label}
    </Btn>
  )
}
