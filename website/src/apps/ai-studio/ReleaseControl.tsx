// The workspace top bar's project-level release (ACP-730), shaped like
// ProjectCommitBar: one control, both surfaces, the `api`/callback seam doing
// the work. The real path has no release endpoint yet, so StudioWorkspace
// does not render this at all — an enabled 发版 button whose click goes
// nowhere is exactly the fake feature the doctrine forbids. The demo
// workbench renders it and passes an onRelease that lands on the step's
// declared snapshot, with `phases` carrying the labels of the generation
// story it walks while that lands (解析图谱 → 生成文件清单 → 完成): labels
// IN, logic untouched — the control never invents phases for the real path.
import { useCallback, useEffect, useRef, useState } from 'react'
import { Rocket } from 'lucide-react'
import { Btn } from '../../components/ui'
import { i18nT } from '../../i18n/t'

export default function ReleaseControl({ onRelease, phases, phaseMs = 600, disabled = false }: {
  /** performs the release; the panel switches when this resolves */
  onRelease: () => Promise<void>
  /** labels shown while pending (demo passes three; the real path passes
   * none and gets the single "Releasing…" label) */
  phases?: string[]
  /** dwell per phase label; one cycle through the list, then it holds on
   * the last until onRelease resolves */
  phaseMs?: number
  disabled?: boolean
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
    ? (phases?.[phase] ?? i18nT('apps.aiStudio.releasing'))
    : i18nT('apps.aiStudio.release')

  return (
    <Btn
      onClick={release}
      disabled={disabled || pending}
      data-testid="release-btn"
      data-release-pending={pending ? 'true' : undefined}
      title={i18nT('apps.aiStudio.release_hint')}
    >
      <Rocket size={13} className="lucide-inline" />
      {label}
    </Btn>
  )
}
