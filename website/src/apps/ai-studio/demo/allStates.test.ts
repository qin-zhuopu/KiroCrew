// The compose rules `allStates.ts` owns (ACP-796) — asserted without rendering.
//
// The dock's rendering is covered by `StatesWorkspace.test.tsx`; what is pinned
// HERE is the one thing the renderer cannot show: this module is the single
// place that decides which big stage a frame belongs to and in what order the
// story walks. Two claims in particular are easy to break silently:
//
//   - the walk order IS the group order. The dock prints groups top to bottom
//     from PHASE_ORDER and walks prev/next through ALL_STATES, so a frame
//     appended outside its group's run would make 「下一步」 jump backwards into
//     a group the user already left.
//   - C1/C2 are re-phased here, not in `states-commit.ts` (that slice belongs
//     to another session). The slice must keep saying 'design' — if it ever
//     starts saying 'commit' itself the override is a no-op, which is fine, but
//     a slice that drifts to something else must not silently take the pair out
//     of the commit group.
import { describe, it, expect } from 'vitest'

import { ALL_STATES, PHASE_LABEL_KEY, PHASE_ORDER, PHASE_PRODUCT_KEY, indexOfState, statesOfPhase } from './allStates'
import { COMMIT_STATES } from './states-commit'
import { GRAPH_STATES } from './states-graph'
import type { DemoPhase } from './states'

describe('the demo dock groups (ACP-796)', () => {
  it('is the owner\'s five stages, in the owner\'s order', () => {
    expect(PHASE_ORDER).toEqual(['design', 'commit', 'release', 'dev', 'deploy'])
  })

  it('labels every stage and names the product it hands on', () => {
    // a stage with no key would render its raw key path as the header
    for (const phase of PHASE_ORDER) {
      expect(PHASE_LABEL_KEY[phase], `no label key for ${phase}`).toBeTruthy()
      expect(PHASE_PRODUCT_KEY[phase], `no product key for ${phase}`).toBeTruthy()
    }
    // the chain the owner pinned, as catalog keys — the words live in en/zh-CN
    expect(PHASE_PRODUCT_KEY).toEqual({
      design: 'apps.aiStudio.demo_product_design',
      commit: 'apps.aiStudio.demo_product_commit',
      release: 'apps.aiStudio.demo_product_release',
      dev: 'apps.aiStudio.demo_product_dev',
      deploy: 'apps.aiStudio.demo_product_deploy',
    })
  })

  it('gives every one of the five stages frames (a group with none does not render)', () => {
    for (const phase of PHASE_ORDER) {
      expect(statesOfPhase(phase).length, `no frames for ${phase}`).toBeGreaterThan(0)
    }
  })

  it('walks the story in the same order it prints the groups', () => {
    // each stage's frames must be one CONTIGUOUS run of ALL_STATES, and the runs
    // must appear in PHASE_ORDER — otherwise prev/next and the group rows
    // disagree about what "next" means
    const runs = ALL_STATES.map((s) => s.phase).filter((p, i, all) => p !== all[i - 1])
    expect(runs).toEqual(PHASE_ORDER)
  })

  it('files the commit pair and the graph pair under 提交, editing neither slice', () => {
    // both slices' own declarations are untouched (other sessions' files)
    expect(COMMIT_STATES.every((s) => s.phase === 'design')).toBe(true)
    expect(GRAPH_STATES.every((s) => s.phase === 'design')).toBe(true)
    // ...and the dock still shows them in 提交, by id
    const commitIds = statesOfPhase('commit').map((s) => s.id)
    for (const s of [...COMMIT_STATES, ...GRAPH_STATES]) expect(commitIds).toContain(s.id)
    // the commit pair stands before the graph generation it produced
    expect(commitIds).toEqual(['C1', 'C2', ...GRAPH_STATES.map((s) => s.id)])
    // the design group holds none of them
    const designIds = statesOfPhase('design').map((s) => s.id)
    for (const s of [...COMMIT_STATES, ...GRAPH_STATES]) expect(designIds).not.toContain(s.id)
  })

  it('maps an id back to its position, and an unknown id to the first frame', () => {
    ALL_STATES.forEach((s, i) => expect(indexOfState(s.id)).toBe(i))
    expect(indexOfState('no-such-frame')).toBe(0)
    // every phase value a frame carries is one the dock groups by
    const known = new Set<DemoPhase>(PHASE_ORDER)
    for (const s of ALL_STATES) expect(known.has(s.phase), `${s.id} has an ungrouped phase`).toBe(true)
  })

  it('has no duplicate frame id (two frames with one id would share a dock button)', () => {
    const ids = ALL_STATES.map((s) => s.id)
    expect(new Set(ids).size).toBe(ids.length)
  })
})