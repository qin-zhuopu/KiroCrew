// The whole `?demo=states` frame list, in one place (ACP-794).
//
// The frames themselves are authored in four sibling files, each owning one
// slice of the story and importing nothing but types from `states.ts`:
//   - `states-commit.ts` C1~C2 — 设计阶段的「提交」页签（待提交改动 / 提交后）
//   - `states-design.ts` D6~D8 — 设计阶段收尾（提交出版本 / 图谱修订 / 下游文档同步）
//   - `states-release.ts` R1~R6 — 发版（发布页签 / 形态 / 发布中 / 结果条 / 详情 / 线上）
//   - `states-devdeploy.ts` V1~V3 / P1~P2 — 开发（四阶段推进 / 完成 / 试运行）与部署
//     （进行中 / 完成·线上可访问）
// (`states.ts` used to carry three opening design frames S1~S3; the owner
// retired them — see that file's header. It is the type module now.)
//
// This module only ORDERS them and labels the big phases the dock groups by —
// it adds no frame of its own, so a slice owner can extend their file without
// touching the renderer.
//
// Order is the story order, not the file order: the dock's prev/next walk it
// literally, so a frame inserted anywhere upstream lands in the right place
// here and nowhere else needs editing. The one insertion `allStates` itself
// owns is C1/C2, which stand at D6's moment — before and after the commit it
// shows the result of — so they go immediately in front of D6 rather than
// after the design slice's tail.
import { COMMIT_STATES } from './states-commit'
import { DESIGN_STATES } from './states-design'
import { RELEASE_STATES } from './states-release'
import { DEV_DEPLOY_STATES } from './states-devdeploy'
import type { DemoPhase, StateSnapshot } from './states'

export { DEPLOY_PAYLOADS, type DeployFramePayload } from './states-devdeploy'

export const ALL_STATES: StateSnapshot[] = [
  ...COMMIT_STATES,
  ...DESIGN_STATES,
  ...RELEASE_STATES,
  ...DEV_DEPLOY_STATES,
]

/** The big phases in story order. Every phase now holds frames; the dock's
 * grouping reads the ORDER from here and the frames from ALL_STATES, so a
 * slice that lands later still joins its group with no edit here. */
export const PHASE_ORDER: DemoPhase[] = ['design', 'release', 'dev', 'deploy']

/** i18n key per phase — the dock's group headers, never a hardcoded string. */
export const PHASE_LABEL_KEY: Record<DemoPhase, string> = {
  design: 'apps.aiStudio.demo_phase_design',
  release: 'apps.aiStudio.demo_phase_release',
  dev: 'apps.aiStudio.demo_phase_dev',
  deploy: 'apps.aiStudio.demo_phase_deploy',
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