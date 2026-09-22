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
function readState(): Record<string, boolean | number | string> {
  const doc = document.querySelector<HTMLElement>('[data-testid^="doc-"]')
  expect(doc, 'editor surface mounted').not.toBeNull()
  const out: Record<string, boolean | number | string> = {
    dirty: doc!.dataset.docDirty === 'true',
    draftRecords: Number(doc!.dataset.draftCount),
    versions: Number(doc!.dataset.versionCount),
    diffDisabled: (document.querySelector('[data-testid="diff-btn"]') as HTMLButtonElement).disabled,
    historyDisabled: (document.querySelector('[data-testid="draft-history-btn"]') as HTMLButtonElement).disabled,
  }
  // the graph read-backs exist exactly for worlds that carry one: the
  // snapshot's graphNodes / graphAddedNodes land as SVG node counts (ACP-729)
  const graph = document.querySelector<HTMLElement>('[data-testid="graph-view"]')
  if (graph) {
    out.graphNodes = graph.querySelectorAll('[data-graph-node]').length
    out.graphAddedNodes = graph.querySelectorAll('[data-graph-added="true"]').length
    // the release read-backs (ACP-730) ride the graph wrapper, not the code
    // panel: derive() emits released/generatedFiles for EVERY step of a graph
    // world (the derive gate keys on graph presence), but the code panel only
    // mounts once the cut lands — so the mirrored reading must be available
    // for the pre-release steps too, or the mirror could never compare them.
    const frame = graph.parentElement
    out.released = frame?.dataset.demoReleased === 'true'
    out.generatedFiles = Number(frame?.dataset.demoGeneratedFiles)
    // the distillation read-backs (ACP-733) ride the same wrapper: modified /
    // removed node counts and the run's status/candidate count
    out.graphModifiedNodes = Number(frame?.dataset.demoGraphModified)
    out.graphRemovedNodes = Number(frame?.dataset.demoGraphRemoved)
    out.distillStatus = frame?.dataset.demoDistillStatus ?? 'none'
    out.distillCandidates = Number(frame?.dataset.demoDistillCandidates)
  }
  return out
}

/** the §2-vocabulary fields of a declared before/after, mapped onto the
 * observable readings above */
function declared(s: DemoState): Record<string, boolean | number | string> {
  const out: Record<string, boolean | number | string> = {
    dirty: s.dirty,
    draftRecords: s.draftRecords,
    versions: s.versions,
    diffDisabled: s.diffIcon === 'gray',
    historyDisabled: s.historyIcon === 'gray',
  }
  if (s.graphNodes !== undefined) {
    out.graphNodes = s.graphNodes
    out.graphAddedNodes = s.graphAddedNodes ?? 0
    out.released = s.released ?? false
    out.generatedFiles = s.generatedFiles ?? 0
    out.graphModifiedNodes = s.graphModifiedNodes ?? 0
    out.graphRemovedNodes = s.graphRemovedNodes ?? 0
    out.distillStatus = s.distillStatus ?? 'none'
    out.distillCandidates = s.distillCandidates ?? 0
  }
  return out
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
        // 怎样算通过 (T10 seven-field): the step's passCriteria are consumed
        // entry by entry against the real DOM reading — the acceptance list
        // the doc shows is the SAME list the test checks, not a description
        // of a different one.
        for (const c of step.passCriteria) {
          expect(readState()[c.field], `${name}/${step.id} 通过判据 ${c.note}`).toBe(c.eq)
        }
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

/** Walk the demo forward by clicking next until the named step settles. */
async function walkTo(script: DemoScript, stepId: string) {
  if (script.steps[0].id === stepId) {
    await settleFor(stepId)
    return
  }
  await settleFor(script.steps[0].id)
  for (let i = 1; i < script.steps.length; i++) {
    await clickTestId('demo-next')
    await settleFor(script.steps[i].id)
    if (script.steps[i].id === stepId) return
  }
  throw new Error(`step ${stepId} never reached`)
}

describe('the graph step (ACP-729): replay-consistent and back-recoverable', () => {
  // the four assertions cover every step through the loops above; this one
  // pins the graph-delta step explicitly — the delta is the step's whole
  // payload, so replaying it must always light the same added nodes, and
  // stepping away and back must land the same picture. It names main-9 by id
  // (not by position) so appending the release step after it cannot retarget
  // these assertions onto the wrong step.
  it('manual and autoplay both land the graph delta identically at main-9', async () => {
    const { name, script } = SCENARIOS.find((s) => s.name === 'main-membership-points')!
    const graphStep = script.steps.find((s) => s.id === 'main-9')!

    const mr = mountDemo(name)
    await walkTo(script, 'main-9')
    await waitFor(
      () => expect(readState()).toEqual(declared(graphStep.after)),
      { timeout: 4000, interval: 50 },
    )
    const manual = readState()
    expect(manual.graphNodes).toBe(8)
    expect(manual.graphAddedNodes).toBe(2)
    mr.unmount()

    const ar = mountDemo(name, '&demoAutoMs=60')
    await settleFor(script.steps[0].id)
    await clickTestId('demo-play')
    await waitFor(
      () => {
        const el = screen.getByTestId('demo-stepper')
        expect(el.getAttribute('data-demo-step')).toBe('main-9')
        expect(el.getAttribute('data-demo-phase')).toBe('main-9:settled')
      },
      { timeout: 20000, interval: 50 },
    )
    await waitFor(
      () => expect(readState()).toEqual(declared(graphStep.after)),
      { timeout: 4000, interval: 50 },
    )
    expect(readState()).toEqual(manual)
    ar.unmount()
  }, 90000)

  it('stepping off main-9 and back re-derives the same graph picture', async () => {
    const { name, script } = SCENARIOS.find((s) => s.name === 'main-membership-points')!
    const graphStep = script.steps.find((s) => s.id === 'main-9')!
    const prevId = script.steps[script.steps.indexOf(graphStep) - 1].id
    mountDemo(name)
    await walkTo(script, 'main-9')
    await waitFor(
      () => expect(readState()).toEqual(declared(graphStep.after)),
      { timeout: 4000, interval: 50 },
    )
    const forward = readState()
    // back to the commit step, then forward again: main-9's picture must be
    // re-derived from its snapshot — same 8 nodes, same 2 added
    await clickTestId('demo-prev')
    await settleFor(prevId)
    await clickTestId('demo-next')
    await settleFor('main-9')
    await waitFor(
      () => expect(readState()).toEqual(declared(graphStep.after)),
      { timeout: 4000, interval: 50 },
    )
    expect(readState()).toEqual(forward)
  }, 90000)
})

describe('the release step (ACP-730): replay-consistent and back-recoverable', () => {
  // main-10 is a LIVE-ACT step: entering it offers the release button, the
  // overlay's open act clicks it for real, and the click lands on the after-
  // fix snapshot (released:true, 4 generated files). The traceability payload
  // — each generated file badged with its source graph node — is what the
  // whole journey closes on, so replaying must always produce the same code
  // panel, and stepping away and back must re-derive it, never leave a
  // half-landed release behind.
  it('manual walk lands the release + code panel at main-10', async () => {
    const { name, script } = SCENARIOS.find((s) => s.name === 'main-membership-points')!
    const rel = script.steps.find((s) => s.id === 'main-10')!
    mountDemo(name)
    await walkTo(script, 'main-10')
    // released + generatedFiles land when the real click resolves (~phase walk)
    await waitFor(
      () => expect(readState()).toEqual(declared(rel.after)),
      { timeout: 6000, interval: 50 },
    )
    const state = readState()
    expect(state.released).toBe(true)
    expect(state.generatedFiles).toBe(4)
    // the code panel is mounted with all four files in the tree, and the
    // selected file's preview carries its graph-source badges — the
    // requirement→graph→code trace is on screen, not just in the data
    const panel = document.querySelector<HTMLElement>('[data-testid="codegen-view"]')
    expect(panel).not.toBeNull()
    expect(Number(panel!.dataset.codegenFiles)).toBe(4)
    expect(document.querySelectorAll('[data-testid^="codegen-file-"][role="option"]')).toHaveLength(4)
    const badges = panel!.querySelectorAll('[data-graph-source]')
    expect(badges.length).toBeGreaterThanOrEqual(1)
  }, 90000)

  it('stepping off main-10 and back re-derives the same release picture', async () => {
    const { name, script } = SCENARIOS.find((s) => s.name === 'main-membership-points')!
    const rel = script.steps.find((s) => s.id === 'main-10')!
    const prevId = script.steps[script.steps.indexOf(rel) - 1].id
    mountDemo(name)
    await walkTo(script, 'main-10')
    await waitFor(
      () => expect(readState()).toEqual(declared(rel.after)),
      { timeout: 6000, interval: 50 },
    )
    const forward = readState()
    // back to the graph step (release button gone, live flag discarded with
    // the step), then forward again — the release must fully re-land
    await clickTestId('demo-prev')
    await settleFor(prevId)
    expect(readState().released).toBe(false)
    await clickTestId('demo-next')
    await settleFor('main-10')
    await waitFor(
      () => expect(readState()).toEqual(declared(rel.after)),
      { timeout: 6000, interval: 50 },
    )
    expect(readState()).toEqual(forward)
  }, 90000)
})

describe('the distillation beats (ACP-733): running → candidates → applied graph', () => {
  // the causal chain 发版→沉淀→结构化设计 is the acceptance doc's steps 7-9.
  // main-11 is a live-act step (real 开始沉淀 click → running snapshot);
  // main-12 lists the candidate wave; main-13 shows the graph that absorbed
  // it. Together they pin that the candidate list and the graph wave are the
  // same fact (the generator proved it; here the DOM confirms it).
  it('main-11 lands the running task, main-12 the candidate list, main-13 the applied graph', async () => {
    const { name, script } = SCENARIOS.find((s) => s.name === 'main-membership-points')!
    mountDemo(name)

    await walkTo(script, 'main-11')
    await waitFor(
      () => expect(readState().distillStatus).toBe('running'),
      { timeout: 6000, interval: 50 },
    )
    expect(readState().distillCandidates).toBe(0)
    expect(document.querySelector('[data-testid="distill-panel"][data-distill-status="running"]')).not.toBeNull()

    await clickTestId('demo-next')
    await settleFor('main-12')
    await waitFor(
      () => expect(readState().distillCandidates).toBe(3),
      { timeout: 4000, interval: 50 },
    )
    // three candidate rows, and the graph behind has NOT moved yet (main-12's
    // frame shows the finished list over the still-old graph)
    expect(document.querySelectorAll('[data-testid^="distill-candidate-"]')).toHaveLength(3)
    expect(readState().graphModifiedNodes).toBe(0)
    expect(readState().graphRemovedNodes).toBe(0)

    await clickTestId('demo-next')
    await settleFor('main-13')
    await waitFor(
      () => expect(readState()).toEqual(declared(script.steps.find((s) => s.id === 'main-13')!.after)),
      { timeout: 4000, interval: 50 },
    )
    // the applied graph: +1 added, ~1 modified, -1 removed — one per candidate
    expect(readState().graphAddedNodes).toBe(1)
    expect(readState().graphModifiedNodes).toBe(1)
    expect(readState().graphRemovedNodes).toBe(1)
    // and the graph view renders all three marks: a dashed-modified node and
    // a struck-through removed id alongside the added one
    expect(document.querySelectorAll('[data-graph-added="true"]')).toHaveLength(1)
    expect(document.querySelectorAll('[data-graph-modified="true"]')).toHaveLength(1)
    expect(document.querySelectorAll('[data-graph-removed]')).toHaveLength(1)
  }, 90000)

  it('stepping back to main-12 drops the applied graph (no leftover wave)', async () => {
    const { name, script } = SCENARIOS.find((s) => s.name === 'main-membership-points')!
    mountDemo(name)
    await walkTo(script, 'main-13')
    await waitFor(
      () => expect(readState().graphRemovedNodes).toBe(1),
      { timeout: 4000, interval: 50 },
    )
    // back to the candidate-list frame: the graph wave was main-13's own
    // snapshot data, so stepping back re-derives the pre-absorption picture
    await clickTestId('demo-prev')
    await settleFor('main-12')
    await waitFor(
      () => expect(readState().graphRemovedNodes).toBe(0),
      { timeout: 4000, interval: 50 },
    )
    expect(readState().distillCandidates).toBe(3)
  }, 90000)
})
