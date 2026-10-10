// The workspace's project-level long-running acts (ACP-730's 发版, ACP-733's
// 开始沉淀, ACP-735's 开始开发, ACP-799's 部署), shaped like ProjectCommitBar:
// one control, both
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
import { BrainCircuit, Hammer, Rocket, Upload } from 'lucide-react'
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
  act?: 'release' | 'distill' | 'dev' | 'deploy'
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

  // one table for the three acts: testid + the i18n keys each reads. The
  // pending label falls back to the act's own "…ing" when it declares no
  // phase walk (distill/dev resolve straight into the snapshot's own
  // running frame; release passes three phase labels and walks them).
  //
  // 三个字段存的是**完整 key**（`apps.aiStudio.` 前缀写全），不是裸后缀：调用点原来
  // 写 `i18nT(\`apps.aiStudio.${conf.key}\`)`，拼出来的 key 在源码里不存在，抽取器和
  // 死键工具都看不见，缺键时按钮直接渲染原始 key（`src/i18n/dynamicKeys.test.ts`
  // 钉这个）。写法参照 McpToolsPanel 的 `STATUS_LABEL_KEY`：字面量表 + 索引。
  const ACTS = {
    release: { testid: 'release-btn', key: 'apps.aiStudio.release', pending: 'apps.aiStudio.releasing', hint: 'apps.aiStudio.release_hint', Icon: Rocket },
    distill: { testid: 'distill-btn', key: 'apps.aiStudio.distill', pending: 'apps.aiStudio.distill_running', hint: 'apps.aiStudio.distill_hint', Icon: BrainCircuit },
    // the `dev` i18n key is taken by the sidebar's run label — the button
    // reads dev_start
    dev: { testid: 'dev-btn', key: 'apps.aiStudio.dev_start', pending: 'apps.aiStudio.dev_running', hint: 'apps.aiStudio.dev_hint', Icon: Hammer },
    // ACP-799's act is the 部署 tab's own: the same button, moved onto the tab
    // that performs it (动作按钮跟着页签走). Its words are SHIPPED catalogue
    // keys — 部署 is the tab's own name and 发布中 is what the product calls an
    // in-flight publish job — so this act adds no i18n key and no new word.
    deploy: { testid: 'deploy-btn', key: 'apps.aiStudio.tool_deploy', pending: 'apps.aiStudio.release_job_status_running', hint: 'apps.aiStudio.tool_deploy', Icon: Upload },
  } as const
  const conf = ACTS[act]
  const label = pending
    ? (phases?.[phase] ?? i18nT(conf.pending))
    : i18nT(conf.key)
  const Icon = conf.Icon

  return (
    <Btn
      onClick={release}
      disabled={disabled || pending}
      data-testid={conf.testid}
      data-release-pending={pending ? 'true' : undefined}
      title={i18nT(conf.hint)}
    >
      <Icon size={13} className="lucide-inline" />
      {label}
    </Btn>
  )
}
