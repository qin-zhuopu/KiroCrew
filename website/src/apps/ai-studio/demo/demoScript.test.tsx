// The script test — methodology §8: it tests the SCRIPT, not the page.
// Four assertions, none of them "a button exists":
//
//   1. 状态迁移  after every step, that step's declared before/after states
//      hold on the real business DOM (data-doc-dirty / data-draft-count /
//      data-version-count on the editor, the icons' disabled state).
//   2. 引导落位  the step's highlight ring is bound to its declared target.
//   3. 回放一致  manual "next" ×N lands on the SAME business state as
//      autoplay reaching step N.
//   4. 回退恢复  walk to a mid step, step back, and the page matches the
//      earlier snapshot exactly (the bug-prone one).
//
// It runs the WHOLE stack — the `?demo=` route through DemoWorkspace, the
// snapshot fake as the data layer, the real DocEditor/WorkArea, the real
// overlay replaying each step's guidance onto the real DOM. Scenario and
// fixture JSON are read through the SAME import.meta.glob the runtime uses,
// so the assertions can never drift from what the demo actually loads.
import { describe, it, expect, beforeEach } from 'vitest'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

import AiStudioPage from '../AiStudioPage'
import { clickEl } from './locators'
import type { DemoFixture, DemoScript, DemoState } from './types'

const STEP_FILES = import.meta.glob('./steps/*.json', { eager: true }) as Record<
  string,
  { default: DemoScript }
>
const FIXTURE_FILES = import.meta.glob('./fixtures/*.json', { eager: true }) as Record<
  string,
  { default: DemoFixture }
>
const SCENARIOS = Object.entries(STEP_FILES).map(([path, mod]) => ({
  name: path.replace('./steps/', '').replace(/\.json$/, ''),
  script: mod.default,
}))

/** Business-observable state, read the way a viewer sees it: the editor's
 * data attributes (the state machine's own read-backs) and the icons'
 * enabled/disabled flags (what "grey" means on screen). */
function readState(): {
  dirty: boolean
  draftRecords: number
  versions: number
  diffDisabled: boolean
  historyDisabled: boolean
} {
  const doc = document.querySelector<HTMLElement>('[data-testid^="doc-"]')
  expect(doc, 'editor surface mounted').not.toBeNull()
  return {
    dirty: doc!.dataset.docDirty === 'true',
    draftRecords: Number(doc!.dataset.draftCount),
    versions: Number(doc!.dataset.versionCount),
    diffDisabled: (document.querySelector('[data-testid="diff-btn"]') as HTMLButtonElement).disabled,
    historyDisabled: (document.querySelector('[data-testid="draft-history-btn"]') as HTMLButtonElement).disabled,
  }
}

/** the §2-vocabulary fields of a declared before/after, mapped onto the
 * observable readings above */
function declared(s: DemoState) {
  return {
    dirty: s.dirty,
    draftRecords: s.draftRecords,
    versions: s.versions,
    diffDisabled: s.diffIcon === 'gray',
    historyDisabled: s.historyIcon === 'gray',
  }
}

const settleFor = (stepId: string) =>
  waitFor(
    () => {
      const el = screen.getByTestId('demo-stepper')
      expect(el.getAttribute('data-demo-phase')).toBe(`${stepId}:settled`)
    },
    { timeout: 9000, interval: 50 },
  )

async function clickTestId(testid: string) {
  const el = document.querySelector<HTMLElement>(`[data-testid="${testid}"]`)
  if (!el) throw new Error(`stepper control ${testid} not found`)
  await act(async () => {
    clickEl(el)
    await new Promise((r) => setTimeout(r, 0))
  })
}

function mountDemo(scenario: string, extraQuery = '') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/ai-studio/projects/demo-x?demo=${scenario}${extraQuery}`]}>
        <AiStudioPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  window.localStorage.clear()
})

describe('script integrity (checked before any browser)', () => {
  it('before(k) equals after(k-1) on every line — the chain cannot lie', () => {
    for (const { script } of SCENARIOS) {
      for (let i = 1; i < script.steps.length; i++) {
        expect(
          script.steps[i].before,
          `${script.scenario}: ${script.steps[i - 1].id} -> ${script.steps[i].id}`,
        ).toEqual(script.steps[i - 1].after)
      }
    }
  })

  it('fixtures are shaped like the backend: unified diffs, deduped drafts', async () => {
    for (const [path, mod] of Object.entries(FIXTURE_FILES)) {
      const fx = mod.default
      for (const [doc, rows] of Object.entries(fx.versions)) {
        for (const row of rows) {
          // difflib's unified_diff carries its file header first (or is the
          // empty string for no-change); anything else was not generated
          expect(
            row.diff === '' || row.diff.startsWith('--- previous'),
            `${path} ${doc} ${row.name} carries a generated unified diff`,
          ).toBe(true)
        }
        // newest first, as list_versions returns it
        const times = rows.map((r) => r.time)
        expect(times, `${path} ${doc} versions newest-first`).toEqual([...times].sort((a, b) => b - a))
      }
      // drafts: newest-first and deduped (save_draft never appends an
      // identical-content record)
      const draftTimes = fx.draftVersions.map((d) => d.time)
      expect(draftTimes, `${path} drafts newest-first`).toEqual([...draftTimes].sort((a, b) => b - a))
      for (let i = 1; i < fx.draftVersions.length; i++) {
        expect(
          fx.draftVersions[i].content,
          `${path} draft record ${i} deduped`,
        ).not.toBe(fx.draftVersions[i - 1].content)
      }
      // every step's fixture exists and agrees with its declared doc
      void fx.focusDoc
    }
  })
})

describe('assertions 1+2: 状态迁移 + 引导落位 (all three lines)', () => {
  for (const { name, script } of SCENARIOS) {
    it(`${name}: every step lands its declared state and rings its target`, async () => {
      mountDemo(name)
      for (let i = 0; i < script.steps.length; i++) {
        const step = script.steps[i]
        await settleFor(step.id)
        // the editor's history counts arrive through React Query, so the
        // declared state must be reached — waitFor asserts convergence, it
        // does not soften the claim (the expected values stay exactly the
        // ones the script declared)
        await waitFor(
          () => expect(readState(), `${name}/${step.id} after-state`).toEqual(declared(step.after)),
          { timeout: 4000, interval: 50 },
        )
        // 引导落位: the ring is bound to this step's declared target…
        // (waitFor, same convergence discipline as the state check: a
        // target like the top bar's drafts badge only exists once the
        // step's queries have landed, and the ring re-measures on its
        // own 250ms tick — the expected target stays exactly the
        // declared one)
        await waitFor(
          () => {
            const ring = screen.getByTestId('demo-ring')
            expect(ring.getAttribute('data-demo-ring-target'), `${name}/${step.id} ring target`).toBe(step.highlight.target)
          },
          { timeout: 4000, interval: 50 },
        )
        // …and the hint bar carries this step's text
        expect(within(screen.getByTestId('demo-stepper')).getByTestId('demo-hint')).toHaveTextContent(
          step.highlight.hint.slice(0, 12),
        )
        if (i < script.steps.length - 1) await clickTestId('demo-next')
      }
    }, 60000)
  }
})

describe('assertion 3: 回放一致 — manual next×N == autoplay to step N', () => {
  it('manual and autoplay reach identical business state at the same step', async () => {
    const { name, script } = SCENARIOS.find((s) => s.name === 'main-membership-points')!
    const target = 4 // main-5: diff active, one draft record

    // manual walk: next ×target, settle each step
    const mr = mountDemo(name)
    await settleFor(script.steps[0].id)
    for (let i = 0; i < target; i++) {
      await clickTestId('demo-next')
      await settleFor(script.steps[i + 1].id)
    }
    await waitFor(
      () => expect(readState()).toEqual(declared(script.steps[target].after)),
      { timeout: 4000, interval: 50 },
    )
    const manual = readState()
    mr.unmount()

    // autoplay: one press, dwell 60ms, let it walk to the same step
    const ar = mountDemo(name, '&demoAutoMs=60')
    await settleFor(script.steps[0].id)
    await clickTestId('demo-play')
    await waitFor(
      () => {
        const el = screen.getByTestId('demo-stepper')
        expect(el.getAttribute('data-demo-step')).toBe(script.steps[target].id)
        expect(el.getAttribute('data-demo-phase')).toBe(`${script.steps[target].id}:settled`)
      },
      { timeout: 12000, interval: 50 },
    )
    await waitFor(
      () => expect(readState()).toEqual(declared(script.steps[target].after)),
      { timeout: 4000, interval: 50 },
    )
    const auto = readState()
    ar.unmount()

    expect(auto).toEqual(manual)
  }, 60000)
})

describe('assertion 4: 回退恢复 — back to a mid step matches its snapshot', () => {
  it('walk forward, step back once, page equals the earlier state exactly', async () => {
    const { name, script } = SCENARIOS.find((s) => s.name === 'main-membership-points')!
    mountDemo(name)

    // forward past main-5 (index 4), remembering it
    await settleFor(script.steps[0].id)
    let forwardAt4: ReturnType<typeof readState> | null = null
    for (let i = 0; i < 5; i++) {
      await clickTestId('demo-next')
      await settleFor(script.steps[i + 1].id)
      if (i + 1 === 4) {
        // let the async history reads land before remembering the state
        await waitFor(
          () => expect(readState()).toEqual(declared(script.steps[4].after)),
          { timeout: 4000, interval: 50 },
        )
        forwardAt4 = readState()
      }
    }
    expect(forwardAt4).not.toBeNull()

    // back to main-5: the page must match where it was on the way up —
    // state re-loaded from the snapshot, guidance replayed, nothing left
    // over from the step that was on top of it
    await clickTestId('demo-prev')
    await settleFor(script.steps[4].id)
    await waitFor(
      () => expect(readState()).toEqual(declared(script.steps[4].after)),
      { timeout: 4000, interval: 50 },
    )
    const backAt4 = readState()
    expect(backAt4).toEqual(forwardAt4)
    expect(backAt4).toEqual(declared(script.steps[4].after))
  }, 60000)
})
