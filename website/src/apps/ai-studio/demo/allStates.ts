// The whole `?demo=states` frame list, in one place (ACP-794; regrouped ACP-796).
//
// The frames themselves are authored in sibling files, each owning one slice of
// the story and importing nothing but types from `states.ts`:
//   - `states-design.ts` D6~D8 — 设计阶段收尾（提交出版本 / 图谱修订 / 下游文档同步）
//   - `states-commit.ts` C1~C2 — 「提交」页签（待提交改动 / 提交后）
//   - `states-graph.ts` G1~G2 — 「需求图谱」页签（生成中 / 生成完成），提交这一步的产物
//   - `states-release.ts` R1~R6 — 发版（发布页签 / 形态 / 发布中 / 结果条 / 详情 / 线上）
//   - `states-devdeploy.ts` V1~V3 / P1~P2 — 开发（四阶段推进 / 完成 / 试运行）与部署
//     （进行中 / 完成·线上可访问）
// (`states.ts` used to carry three opening design frames S1~S3; the owner
// retired them — see that file's header. It is the type module now.)
//
// This module only ORDERS them, re-states the owner's stage for a slice it does
// not own, and labels the big phases the dock groups by — it adds no frame of
// its own, so a slice owner can extend their file without touching the
// renderer.
//
// GROUPING (owner, ACP-796): five big stages — 设计 / 提交 / 发版 / 开发 / 部署.
// 「提交」is its own stage now (the commit page and the requirement graph it
// produces), so C1/C2 left the design group even though `states-commit.ts`
// still declares `phase: 'design'` — that file is another session's to edit, and
// the owner's stage model is this module's to state. They are re-phased HERE,
// by a spread copy: the slice keeps saying what it always said, and a slice
// owner who later moves to `'commit'` themselves changes nothing (same value).
//
// ORDER is the story order AND the group order — the dock's prev/next walks it
// literally, so frames of one stage are contiguous and a frame inserted
// anywhere upstream lands in the right place here and nowhere else needs
// editing. D7/D8 stay at the end of 设计 (their slice's own phase, not mine to
// re-phase) rather than moving after the commit group; the graph-generation
// frames, when they land, join 提交 at its end.
import { COMMIT_STATES } from './states-commit'
import { DESIGN_STATES } from './states-design'
import { GRAPH_STATES } from './states-graph'
import { RELEASE_STATES } from './states-release'
import { DEV_DEPLOY_STATES } from './states-devdeploy'
import type { DemoPhase, StateSnapshot } from './states'

export { DEPLOY_PAYLOADS, type DeployFramePayload } from './states-devdeploy'

/** The 提交 stage's slices as this module files them: the commit pair, then the
 * graph generation it produced (G1 生成中 → G2 生成完成). Same frames, under the
 * stage the owner put them in (see the header) — a copy, never an edit of a
 * file another session owns. Both slices declare `'design'` on their own: that
 * is where they were authored from, and re-stating the stage here is exactly
 * the job of the module that owns the grouping. */
const COMMIT_FRAMES: StateSnapshot[] = [...COMMIT_STATES, ...GRAPH_STATES]
  .map((s) => ({ ...s, phase: 'commit' }))

export const ALL_STATES: StateSnapshot[] = [
  ...DESIGN_STATES,
  ...COMMIT_FRAMES,
  ...RELEASE_STATES,
  ...DEV_DEPLOY_STATES,
]

/** The big phases in story order. The dock's grouping reads the ORDER from here
 * and the frames from ALL_STATES, so a slice that lands later still joins its
 * group with no edit here. */
export const PHASE_ORDER: DemoPhase[] = ['design', 'commit', 'release', 'dev', 'deploy']

/** i18n key per phase — the dock's group headers, never a hardcoded string. */
export const PHASE_LABEL_KEY: Record<DemoPhase, string> = {
  design: 'apps.aiStudio.demo_phase_design',
  commit: 'apps.aiStudio.demo_phase_commit',
  release: 'apps.aiStudio.demo_phase_release',
  dev: 'apps.aiStudio.demo_phase_dev',
  deploy: 'apps.aiStudio.demo_phase_deploy',
}

/** i18n key per phase for the stage's PRODUCT — what this stage of the chain
 * hands to the next one (owner, ACP-796): 设计→文档, 提交→需求图谱,
 * 发版→开发任务, 开发→git tag, 部署→应用 url. The dock prints it next to the
 * phase name so the grouping reads as a pipeline and not as five folders. */
export const PHASE_PRODUCT_KEY: Record<DemoPhase, string> = {
  design: 'apps.aiStudio.demo_product_design',
  commit: 'apps.aiStudio.demo_product_commit',
  release: 'apps.aiStudio.demo_product_release',
  dev: 'apps.aiStudio.demo_product_dev',
  deploy: 'apps.aiStudio.demo_product_deploy',
}

/** The frames of one phase, in ALL_STATES order — the dock's row for that
 * group. Empty for a phase with no merged frames yet (a group renders only
 * when it has frames). */
export function statesOfPhase(phase: DemoPhase): StateSnapshot[] {
  return ALL_STATES.filter((s) => s.phase === phase)
}

/** The position of a state in ALL_STATES (by id), or 0 when absent — the dock
 * passes an INDEX to the workspace, so this is the one place the id ↔ index
 * mapping lives. */
export function indexOfState(id: string): number {
  const i = ALL_STATES.findIndex((s) => s.id === id)
  return i < 0 ? 0 : i
}