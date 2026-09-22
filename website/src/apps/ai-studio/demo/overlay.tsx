// The visual guidance layer (§4): one independent overlay carrying the
// highlight ring, the hint bar and the prev/next/autoplay stepper. Mounted
// ONLY by the `?demo=` branch of StudioWorkspace — no business component
// imports anything from this file, and none of them grew a single demo
// branch: the overlay acts ON the page from outside, through the same
// data-testid contract the test suite uses (locators.ts).
//
// The open/ phase is this layer's job, not the step's: entering a step means
// (1) the runtime loaded the step's snapshot — the state layer, done;
// (2) this effect replays the step's `open` locator list onto the freshly
// remounted page (each act clicked through the real event path, polled
// because the business DOM mounts asynchronously), then settles. Replaying
// on every entry — including a step RETURNED TO — is what makes back/next
// idempotent (§6): the same step always re-derives the same picture from
// snapshot + script, never from leftovers.
import { useEffect, useMemo, useState } from 'react'
import { ChevronLeft, ChevronRight, Pause, Play, RotateCcw } from 'lucide-react'
import { i18nT } from '../../../i18n/t'
import Clickable from '../../../components/Clickable'
import { clickEl, resolveLocator } from './locators'
import type { DemoController } from './runtime'

/** How long one `open` locator may poll for its element before the script
 * admits the UI it names is not there (broken script or broken page — both
 * worth a console line, neither worth a frozen demo). Generous because a
 * locator can legitimately wait on the editor's real 2s autosave debounce
 * (main-5 enables the history button through that very timer). */
const LOCATOR_DEADLINE_MS = 6000

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))

export default function DemoOverlay({ ctl }: { ctl: DemoController }) {
  const { step, fixture, prevBuffer, settleMs, markSettled } = ctl
  const ctx = useMemo(() => ({ buffer: fixture.buffer, prevBuffer }), [fixture, prevBuffer])
  const [ring, setRing] = useState<{ key: string; top: number; left: number; width: number; height: number } | null>(null)
  const stepId = step.id

  // replay this step's guidance acts, then declare THAT step settled (the
  // report names the step: a report that finishes after the presenter
  // already moved on marks nothing)
  useEffect(() => {
    let cancelled = false
    const run = async () => {
      for (const spec of step.highlight.open) {
        const deadline = Date.now() + LOCATOR_DEADLINE_MS
        let hit = resolveLocator(spec, ctx)
        while (!hit && Date.now() < deadline) {
          await sleep(40)
          hit = resolveLocator(spec, ctx)
        }
        if (cancelled) return
        if (!hit) {
          console.warn(`[ai-studio demo] step "${step.id}": locator "${spec}" never appeared`)
          continue
        }
        ;(hit.locator.act ?? clickEl)(hit.el, spec.split(':')[1], ctx)
        await sleep(settleMs)
      }
      if (!cancelled) markSettled(stepId)
    }
    void run()
    return () => { cancelled = true }
    // one replay per step ENTRY (id), not per render of the controller
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stepId])

  // keep the ring on its target: re-measured on a slow tick (popovers open
  // async, the editor reflows), with a scrollIntoView once per step
  useEffect(() => {
    const target = step.highlight.target
    let raf = 0
    let scrolled = false
    const measure = () => {
      const hit = resolveLocator(target, ctx)
      if (!hit) {
        setRing(null)
        return
      }
      const style = window.getComputedStyle(hit.el)
      if (style.display === 'none' || style.visibility === 'hidden') {
        setRing(null)
        return
      }
      if (!scrolled) {
        scrolled = true
        hit.el.scrollIntoView?.({ block: 'center', behavior: 'auto' })
      }
      // geometry is a real-browser concern; a headless DOM reports a
      // zero rect, and the ring still binds to (and reports) its target —
      // a Playwright run reads the same measured box for real pixels
      const r = hit.el.getBoundingClientRect()
      setRing({ key: target, top: r.top - 4, left: r.left - 4, width: r.width + 8, height: r.height + 8 })
    }
    measure()
    const iv = window.setInterval(measure, 250)
    const onScroll = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(measure) }
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', measure)
    return () => {
      window.clearInterval(iv)
      cancelAnimationFrame(raf)
      window.removeEventListener('scroll', onScroll, true)
      window.removeEventListener('resize', measure)
    }
    // re-anchored per step (target may repeat; the scroll flag resets here)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stepId, ctx])

  const idx = ctl.stepIndex + 1
  const total = ctl.script.steps.length

  return (
    <>
      {ring && (
        <div
          data-testid="demo-ring"
          data-demo-ring-target={ring.key}
          aria-hidden
          className="pointer-events-none fixed z-[10000] rounded-lg border-2 border-accent shadow-[0_0_0_9999px_rgba(0,0,0,0.35)]"
          style={{ top: ring.top, left: ring.left, width: ring.width, height: ring.height }}
        />
      )}
      <div
        data-testid="demo-stepper"
        // the phase attribute names the step it describes: a render that
        // happens between the step change and the effect re-arming the
        // 'open' phase still carries the PREVIOUS step's 'settled' — the
        // test must never read a settled that belongs to a stale step.
        data-demo-phase={ctl.phase === 'settled' ? `${step.id}:settled` : `${step.id}:open`}
        data-demo-step={step.id}
        className="fixed bottom-4 right-4 z-[10001] w-[340px] rounded-xl border border-border bg-card p-3 shadow-2xl"
      >
        <div className="flex items-center gap-2">
          <span className="rounded-full bg-accent-subtle px-2 py-0.5 text-[10px] text-accent">
            {i18nT('apps.aiStudio.demo_badge')}
          </span>
          <span className="text-[12px] font-semibold text-text-strong truncate">{ctl.script.title}</span>
          <span className="ml-auto shrink-0 text-[11px] text-muted">
            {i18nT('apps.aiStudio.demo_counter', { n: idx, total })}
          </span>
        </div>
        <div className="mt-2 text-[12px] font-semibold text-text">{step.title}</div>
        <div className="mt-1 text-[11px] text-muted">
          {i18nT('apps.aiStudio.demo_event', { event: step.action.event })}
        </div>
        <div data-testid="demo-hint" className="mt-2 text-[12px] leading-5 text-text">
          {step.highlight.hint}
        </div>
        <div className="mt-3 flex items-center gap-1.5">
          <Clickable
            data-testid="demo-prev"
            onClick={() => ctl.prev()}
            disabled={ctl.atStart}
            className={`rounded-md border border-border px-2.5 py-1 text-[12px] ${ctl.atStart ? 'text-muted opacity-50' : 'text-text hover:bg-bg-hover cursor-pointer'}`}
          >
            <span className="flex items-center gap-0.5"><ChevronLeft size={13} />{i18nT('apps.aiStudio.demo_prev')}</span>
          </Clickable>
          <Clickable
            data-testid="demo-next"
            onClick={() => ctl.next()}
            disabled={ctl.atEnd}
            className={`rounded-md border border-border px-2.5 py-1 text-[12px] ${ctl.atEnd ? 'text-muted opacity-50' : 'text-text hover:bg-bg-hover cursor-pointer'}`}
          >
            <span className="flex items-center gap-0.5">{i18nT('apps.aiStudio.demo_next')}<ChevronRight size={13} /></span>
          </Clickable>
          <Clickable
            data-testid="demo-play"
            onClick={() => ctl.togglePlay()}
            className="flex items-center gap-1 rounded-md border border-border px-2.5 py-1 text-[12px] text-text hover:bg-bg-hover cursor-pointer"
          >
            {ctl.playing ? <Pause size={12} /> : <Play size={12} />}
            {i18nT(ctl.playing ? 'apps.aiStudio.demo_pause' : 'apps.aiStudio.demo_play')}
          </Clickable>
          <Clickable
            data-testid="demo-restart"
            onClick={() => ctl.restart()}
            className="ml-auto flex items-center gap-0.5 rounded-md border border-border px-2 py-1 text-[12px] text-muted hover:text-text hover:bg-bg-hover cursor-pointer"
            aria-label={i18nT('apps.aiStudio.demo_restart')}
          >
            <RotateCcw size={12} />
          </Clickable>
        </div>
      </div>
    </>
  )
}
