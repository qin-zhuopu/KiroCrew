// The whole `?demo=states` frame list, in one place (ACP-794).
//
// The frames themselves are authored in three sibling files, each owning one
// slice of the story and importing nothing but types:
//   - `states.ts`        S1~S3  — 设计阶段开局（文档列表 / 未提交修改 / 当前 Diff）
//   - `states-design.ts` D6~D8  — 设计阶段收尾（提交出版本 / 图谱修订 / 下游文档同步）
//   - `states-devdeploy.ts` V1~V3 / P1~P2 — 开发（四阶段推进 / 完成 / 试运行）与部署
//     （进行中 / 完成·线上可访问）
// This module only ORDERS them and labels the big phases the dock groups by —
// it adds no frame of its own, so a slice owner can extend their file without
// touching the renderer.
//
// Order is the story order, not the file order: the dock's prev/next walk it
// literally, so a frame inserted anywhere upstream lands in the right place
// here and nowhere else needs editing.
import { DEMO_STATES } from './states'
import { DESIGN_STATES } from './states-design'
import { DEV_DEPLOY_STATES } from './states-devdeploy'
import type { DemoPhase, StateSnapshot } from './states'

export { DEPLOY_PAYLOADS, type DeployFramePayload } from './states-devdeploy'

export const ALL_STATES: StateSnapshot[] = [
  ...DEMO_STATES,
  ...DESIGN_STATES,
  ...DEV_DEPLOY_STATES,
]

/** The big phases in story order. `release` currently holds no frame (the
 * 发版 slice is not merged yet); it stays in the list because the dock's
 * grouping reads the ORDER from here and the frames from ALL_STATES — when
 * that slice lands its frames join the group with no edit here. */
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