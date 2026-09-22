// The demo runtime: URL-driven scenario loading, the snapshot-backed fake
// data layer, and the step controller (methodology §4/§5/§6).
//
// Two layers, kept apart on purpose:
//   - STATE  — every step OWNS a complete snapshot (fixtures/state-*.json);
//     entering a step loads its snapshot wholesale. Next and prev are both
//     "load state n" — there is no reverse computation anywhere (§5), and
//     entering the same step twice always yields the same picture (§6).
//   - VIEW — the step script says what to ring and which panel to open; the
//     overlay replays that onto the freshly remounted business page.
//
// The fake data layer has the exact shape of `studioApi`, so the business
// components run their real code paths against it and never learn a demo
// exists (no `if (demo)` anywhere in them — they simply receive a different
// `api`). It is rebuilt from the step's snapshot on every step, so any live
// mutation a curious presenter makes (e.g. clicking Commit) is discarded on
// the next step change exactly like a real snapshot load.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { StudioApiError, type StudioApi } from '../studioApi'
import type { DemoFixture, DemoScript, DemoStep } from './types'

// Eager globs: the demo JSON rides inside the already-lazy ai-studio chunk
// (the whole page is behind a lazy route), so the non-demo first paint never
// pays for it. Keys are stable ('./steps/<scenario>.json').
const STEP_FILES = import.meta.glob('./steps/*.json', { eager: true }) as Record<
  string,
  { default: DemoScript }
>
const FIXTURE_FILES = import.meta.glob('./fixtures/*.json', { eager: true }) as Record<
  string,
  { default: DemoFixture }
>

export const DEMO_SCENARIOS: Record<string, DemoScript> = Object.fromEntries(
  Object.entries(STEP_FILES).map(([path, mod]) => [
    path.replace('./steps/', '').replace(/\.json$/, ''),
    mod.default,
  ]),
)

/** `?demo=<scenario>` off a search string; null outside demo mode. The query
 * param is the whole injection point (§4) — remove it and the page is the
 * ordinary workbench. Harness-only knobs (used by the script test, never by
 * a presenter): `demoAutoMs` (autoplay dwell, default 4000) and
 * `demoSettleMs` (pause after each guidance act, default 250). */
export function parseDemoScenario(search: string): {
  scenario: string
  autoMs: number
  settleMs: number
} | null {
  const params = new URLSearchParams(search)
  const scenario = params.get('demo')
  if (!scenario) return null
  const num = (key: string, dflt: number) => {
    const v = Number(params.get(key))
    return Number.isFinite(v) && v > 0 ? v : dflt
  }
  return { scenario, autoMs: num('demoAutoMs', 4000), settleMs: num('demoSettleMs', 250) }
}

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v) as string) as T

/** Naive line diff for presenter-made commits during a live demo (the
 * scripted path never needs it — the fixtures' diffs were computed by the
 * real difflib in generate_fixtures.py). Approximation by design; it only
 * feeds the version panel of a manual click nobody scripted. */
function naiveLineDiff(oldText: string, newText: string): string {
  const o = oldText.split('\n')
  const n = newText.split('\n')
  let start = 0
  while (start < o.length && start < n.length && o[start] === n[start]) start += 1
  let oe = o.length
  let ne = n.length
  while (oe > start && ne > start && o[oe - 1] === n[ne - 1]) { oe -= 1; ne -= 1 }
  let out = `@@ -${start + 1},${oe - start} +${start + 1},${ne - start} @@\n`
  for (let i = start; i < oe; i += 1) out += `-${o[i]}\n`
  for (let i = start; i < ne; i += 1) out += `+${n[i]}\n`
  return out
}

/** A demo step's whole backend: four endpoints, in-memory, semantics mirrored
 * from projects.py (dedupe-on-identical autosave, commit-clears-drafts,
 * row N diffs against row N-1). Listeners let the provider bounce React Query
 * so live mutations surface without a remount. */
export function createDemoApi(fixture: DemoFixture): StudioApi & { subscribe: (cb: () => void) => () => void } {
  const store = {
    project: clone(fixture.project),
    docs: fixture.docs.map((d) => ({ ...d })),
    // newest-first, exactly the API order (the store's own read order)
    drafts: clone(fixture.draftVersions),
    versions: new Map(Object.entries(fixture.versions).map(([k, v]) => [k, clone(v)])),
  }
  const listeners = new Set<() => void>()
  const notify = () => listeners.forEach((l) => l())
  const focus = fixture.focusDoc

  return {
    subscribe(cb) {
      listeners.add(cb)
      return () => listeners.delete(cb)
    },
    async listProjects() {
      return { projects: [clone(store.project)] }
    },
    async createProject(): Promise<{ project: never }> {
      // the demo never writes new projects — there is no real home to write
      // them to (§5: nothing leaves the snapshot)
      throw new StudioApiError(400, 'demo_mode', 'demo mode does not create projects')
    },
    async getProject() {
      return { project: clone(store.project), docs: clone(store.docs) }
    },
    async saveDoc(_id: string, name: string, content: string) {
      const row = store.docs.find((d) => d.name === name)
      const old = row?.content ?? ''
      if (row) row.content = content
      else store.docs.push({ name, content })
      if (content !== old) {
        const rows = store.versions.get(name) ?? []
        // the previous row's content IS the pre-write docs entry (§2)
        rows.unshift({ name: `demo-${Date.now()}.md`, time: Date.now() / 1000, diff: naiveLineDiff(old, content) })
        store.versions.set(name, rows)
      }
      if (name === focus) store.drafts = [] // commit clears the draft records
      notify()
      return { doc: { name, content } }
    },
    async listDraftDocs() {
      // the top bar's project-level commit work list: only the focused doc
      // carries drafts in a snapshot (the fixture's draftVersions are its
      // records); `changed` compares the newest record against the commit.
      const latest = store.drafts[0]
      const doc = store.docs.find((d) => d.name === focus)
      const changed = latest !== undefined && latest.content !== (doc?.content ?? '')
      const drafts = latest
        ? [{ name: focus, content: latest.content, changed }]
        : []
      return { drafts: clone(drafts) }
    },
    async saveDraft(_id: string, name: string, content: string) {
      // projects.save_draft: append unless identical to the newest record
      const deduped = store.drafts.length > 0 && store.drafts[0].content === content
      if (!deduped) {
        store.drafts.unshift({ name, time: Date.now() / 1000, content })
        notify()
      }
      return { ok: true }
    },
    async listDraftVersions(_id: string, name: string) {
      return { versions: name === focus ? clone(store.drafts) : [] }
    },
    async listVersions(_id: string, name: string) {
      return { versions: clone(store.versions.get(name) ?? []) }
    },
  }
}

export type DemoApi = StudioApi & { subscribe: (cb: () => void) => () => void }

export interface DemoController {
  scenario: string
  script: DemoScript
  step: DemoStep
  stepIndex: number
  fixture: DemoFixture
  /** the previous step's buffer (undefined at step 0) — the live-act replay
   * seeds the editor with it before performing the step's real business act */
  prevBuffer: string | undefined
  api: DemoApi
  /** 'open' = the overlay is still replaying this step's guidance acts;
   * 'settled' = done — autoplay's dwell timer starts only from here, which
   * is also what the script test waits on before asserting. */
  phase: 'open' | 'settled'
  playing: boolean
  atStart: boolean
  atEnd: boolean
  settleMs: number
  next: () => void
  prev: () => void
  restart: () => void
  togglePlay: () => void
  markSettled: (stepId: string) => void
}

/** The step machine, mounted by StudioWorkspace when the URL carries
 * `?demo=`. Returns null (everything the non-demo path needs stays exactly
 * as it was) when there is no scenario or the name does not resolve. */
export function useDemoRuntime(
  params: { scenario: string; autoMs: number; settleMs: number } | null,
): { ctl: DemoController | null; unknown: string | null } {
  const [stepIndex, setStepIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  // "which step's guidance replay has finished" — held as a step ID rather
  // than a boolean phase so the settled/open reading is a pure derivation
  // from the current step: there is no render window in which a fresh step
  // could still carry the previous step's settled (a test that reads
  // `data-demo-phase` must never be able to observe a stale settled).
  const [settledFor, setSettledFor] = useState<string | null>(null)
  const script = params ? DEMO_SCENARIOS[params.scenario] ?? null : null

  // clamped so a hand-typed index cannot strand the controller past the end
  // of a shorter script
  const index = script ? Math.min(stepIndex, script.steps.length - 1) : 0
  const step = script?.steps[index] ?? null
  // NB: no scenario-change reset — the `?demo=` branch keys DemoWorkspace on
  // the scenario name (AiStudioPage), so switching a demo remounts this hook
  // fresh. A reset effect here would run AFTER the child overlay's mount
  // effects and wipe the settled report of a step-0 with an empty open list.

  const fixture = useMemo(
    () => (step ? FIXTURE_FILES[`./fixtures/state-${step.fixture}.json`]?.default ?? null : null),
    [step],
  )
  const api = useMemo(() => (fixture ? createDemoApi(fixture) : null), [fixture])
  // the previous step's buffer: the starting point for a step whose event
  // happens live on top of the prior state (alt1-6's real Restore click)
  const prevBuffer = useMemo(() => {
    const prevStep = script?.steps[index - 1]
    if (!prevStep) return undefined
    return FIXTURE_FILES[`./fixtures/state-${prevStep.fixture}.json`]?.default?.buffer
  }, [script, index])

  const next = useCallback(() => {
    if (!script) return
    setStepIndex((i) => Math.min(i + 1, script.steps.length - 1))
  }, [script])
  const prev = useCallback(() => setStepIndex((i) => Math.max(i - 1, 0)), [])
  const restart = useCallback(() => setStepIndex(0), [])
  const togglePlay = useCallback(() => {
    setPlaying((p) => {
      // pressing play on the last frame restarts — a presenter's "replay"
      if (!p && script && index >= script.steps.length - 1) setStepIndex(0)
      return !p
    })
  }, [script, index])
  // the overlay reports completion FOR A NAMED STEP; a late report for a
  // step already replaced can never mark the current step settled
  const markSettled = useCallback((stepId: string) => setSettledFor(stepId), [])
  const phase: 'open' | 'settled' = step && settledFor === step.id ? 'settled' : 'open'

  // autoplay = dwell after settle, then advance; stops at the end so the
  // final frame (the committed state) stays on screen
  const timerRef = useRef<number | null>(null)
  useEffect(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
    if (!playing || !script || phase !== 'settled') return
    if (index >= script.steps.length - 1) {
      setPlaying(false)
      return
    }
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null
      next()
    }, params?.autoMs ?? 4000)
    return () => {
      if (timerRef.current !== null) clearTimeout(timerRef.current)
    }
  }, [playing, phase, index, script, next, params?.autoMs])

  if (!params || !script || !step || !fixture || !api) {
    return { ctl: null, unknown: params && !script ? params.scenario : null }
  }
  return {
    ctl: {
      scenario: params.scenario,
      script,
      step,
      stepIndex: index,
      fixture,
      prevBuffer,
      api,
      phase,
      playing,
      atStart: index === 0,
      atEnd: index >= script.steps.length - 1,
      settleMs: params.settleMs,
      next,
      prev,
      restart,
      togglePlay,
      markSettled,
    },
    unknown: null,
  }
}
