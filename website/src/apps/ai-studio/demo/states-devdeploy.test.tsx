// ACP-792: the dev + deploy state frames (V1~V3 / P1~P2).
//
// WHAT THIS PROVES, AND HOW. The renderer (StateDemo, ACP-794 返工中) is not
// mine to touch, so mounting the full `?demo=states` route and asserting my
// frames paint there is not possible from inside this file — but a state frame
// is only as real as the components it feeds, so every render assertion here
// mounts the REAL business component the wired surface will use, with MY
// snapshot's payload: `DevRunPanel` / `RunPreviewScreen` (DevRunView.tsx) from
// `fixture.devRun` / `fixture.runPreview`. That is the outline's hard rule
// (testid 与文案必须和真实组件一致，不许另造长得像的) enforced at the data
// layer: if these frames ever drive a branch, they provably produce
// dev-run-panel / dev-phase-* / dev-artifacts / dev-runnable-version /
// run-preview / run-line exactly as the outline names them.
//
// The deploy frames have no pure-props business component to mount (the real
// DeployLog streams SSE, which a zero-fetch demo cannot drive — 任务书:
// 「部署段先按快照帧做」), so P1~P2 are asserted at the payload-contract level:
// the `deploy-log-<deploymentId>` keying, the 进行中→完成 status pair, the
// prefix-extension growth of the log lines, the URL template, and the 单实例
// replacement facts. A later renderer branch consumes exactly these fields.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { fireEvent, render } from '@testing-library/react'

import DevRunPanel, { RunPreviewScreen } from '../DevRunView'
import { DEPLOY_PAYLOADS, DEV_DEPLOY_STATES } from './states-devdeploy'

const byId = (id: string) => {
  const s = DEV_DEPLOY_STATES.find((x) => x.id === id)
  if (!s) throw new Error(`state ${id} missing`)
  return s
}

const attr = (testid: string, name: string) =>
  document.querySelector<HTMLElement>(`[data-testid="${testid}"]`)?.getAttribute(name)

let fetchSpy: ReturnType<typeof vi.spyOn>
beforeEach(() => {
  fetchSpy = vi.spyOn(globalThis, 'fetch')
})
afterEach(() => {
  fetchSpy.mockRestore()
})

describe('dev-deploy snapshots: shape and world', () => {
  it('ships the five frames in forward outline order, with ids/outlines/phases aligned', () => {
    expect(DEV_DEPLOY_STATES.map((s) => s.id)).toEqual(['V1', 'V2', 'V3', 'P1', 'P2'])
    expect(DEV_DEPLOY_STATES.map((s) => s.outlineRef)).toEqual(['V1', 'V2', 'V3', 'P1', 'P2'])
    expect(DEV_DEPLOY_STATES.map((s) => s.phase)).toEqual(['dev', 'dev', 'dev', 'deploy', 'deploy'])
    expect(DEV_DEPLOY_STATES.map((s) => s.activeSurface)).toEqual(['dev', 'dev', 'dev', 'deploy', 'deploy'])
  })

  it('every frame sits in the post-commit world: clean editor, commit disabled, four docs', () => {
    for (const s of DEV_DEPLOY_STATES) {
      expect(s.dirty, s.id).toBe(false)
      expect(s.commitEnabled, s.id).toBe(false)
      expect(s.diffBadge, s.id).toBe(false)
      expect(s.docs).toHaveLength(4)
      // the fake agrees with the markers: no drafts anywhere
      expect(s.fixture.draftVersions, s.id).toEqual([])
      expect(s.fixture.buffer, s.id).toBe(s.fixture.docs[0].content)
    }
  })

  it('keeps the 附一 parity rule on the visible doc labels: focus odd, downstream even', () => {
    for (const s of DEV_DEPLOY_STATES) {
      const [focus, ...downstream] = s.docs
      expect(Number(focus.version.slice(1)) % 2, focus.name).toBe(1) // V5 = manual commit (D6)
      for (const d of downstream) {
        expect(Number(d.version.slice(1)) % 2, d.name).toBe(0) // even = graph 反生 (D8)
      }
    }
  })

  it('the new rule this iteration added is in every frame committed into the doc', () => {
    for (const s of DEV_DEPLOY_STATES) {
      expect(s.fixture.buffer).toContain('大额采购需追加一级审批')
      expect(s.fixture.buffer).toContain('审批人请假时自动转交代理人')
    }
  })
})

describe('V1~V3 development run payload', () => {
  it('V1 is mid-walk: tasks done with a summary, implement running, test/build pending, no products yet', () => {
    const run = byId('V1').fixture.devRun!
    expect(run.id).toBe('dev-v5')
    expect(run.designVersion).toBe('v5 · graph@distill-v4')
    expect(run.phases.map((p) => [p.name, p.status])).toEqual([
      ['tasks', 'done'],
      ['implement', 'running'],
      ['test', 'pending'],
      ['build', 'pending'],
    ])
    // a done phase carries its factual summary; an unfinished one carries none
    expect(run.phases[0].summary).not.toBe('')
    expect(run.phases[1].summary).toBe('')
    expect(run.artifacts).toEqual([])
    expect(run.runnableVersion).toBeUndefined()
  })

  it('V2 finishes: all four phases done, the three artifacts, and the runnable version appears', () => {
    const run = byId('V2').fixture.devRun!
    expect(run.phases.every((p) => p.status === 'done')).toBe(true)
    expect(run.artifacts.map((a) => a.kind)).toEqual(['test', 'build', 'runtime'])
    expect(run.runnableVersion).toBe('0.5.0')
    expect(byId('V2').fixture.runPreview).toBeUndefined()
  })

  it('V3 opens the experience screen: the preview names V2-run 0.5.0 and its feature list carries the new rule', () => {
    const v3 = byId('V3')
    const preview = v3.fixture.runPreview!
    expect(preview.devRunId).toBe(v3.fixture.devRun!.id)
    expect(preview.version).toBe(v3.fixture.devRun!.runnableVersion)
    expect(preview.lines).toContain('大额采购需追加一级审批')
    expect(preview.lines).toContain('审批人请假时自动转交代理人')
  })
})

describe('P1~P2 deployment payload contract', () => {
  it('P1 runs and P2 completes, sharing one 发布号 (the deploy-log-<id> testid key)', () => {
    const p1 = DEPLOY_PAYLOADS.P1
    const p2 = DEPLOY_PAYLOADS.P2
    expect(p1.status).toBe('running')
    expect(p2.status).toBe('success')
    expect(p1.deploymentId).toBe(p2.deploymentId)
    expect(p1.url).toBe('') // the address exists only after 发布完成
  })

  it('the log grows between the frames: P2 extends P1 verbatim as a prefix (零 fetch 的「边发边长」)', () => {
    const p1 = DEPLOY_PAYLOADS.P1
    const p2 = DEPLOY_PAYLOADS.P2
    expect(p2.logLines.length).toBeGreaterThan(p1.logLines.length)
    expect(p2.logLines.slice(0, p1.logLines.length)).toEqual(p1.logLines)
    expect(p1.logLines.some((l) => l.includes('发布完成'))).toBe(false)
    expect(p2.logLines[p2.logLines.length - 1]).toBe('发布完成')
  })

  it('P2 opens onto 线上: URL follows the store template, and the live feature list equals V3 试运行', () => {
    const p2 = DEPLOY_PAYLOADS.P2
    expect(p2.url).toMatch(/^v5-.+-14409\.gb10\.jereh-pe\.cn$/)
    expect(p2.onlineFeatureLines).toEqual(byId('V3').fixture.runPreview!.lines)
    expect(p2.onlineFeatureLines!.join('\n')).toContain('大额采购需追加一级审批')
  })

  it('单实例替换: the old v4 instance is named stopped in the running log and confirmed replaced in P2', () => {
    const p1 = DEPLOY_PAYLOADS.P1
    const p2 = DEPLOY_PAYLOADS.P2
    expect(p1.replaced).toEqual(p2.replaced)
    expect(p2.replaced!.version).toBe('v4')
    expect(p1.logLines.join('\n')).toContain('停止旧实例 v4')
    expect(p2.logLines.join('\n')).toContain('旧实例已替换')
    expect(p2.logLines.join('\n')).toContain('启动新实例 v5')
  })
})

describe('the snapshots feed the REAL business components', () => {
  it('V1 renders the four-phase panel: dev-run-panel / dev-design-version / dev-phase-* statuses', () => {
    render(<DevRunPanel run={byId('V1').fixture.devRun!} />)
    expect(attr('dev-run-panel', 'data-dev-run-id')).toBe('dev-v5')
    expect(document.querySelector('[data-testid="dev-design-version"]')).toHaveTextContent('v5 · graph@distill-v4')
    expect(attr('dev-phase-tasks', 'data-dev-phase-status')).toBe('done')
    expect(attr('dev-phase-implement', 'data-dev-phase-status')).toBe('running')
    expect(attr('dev-phase-test', 'data-dev-phase-status')).toBe('pending')
    expect(attr('dev-phase-build', 'data-dev-phase-status')).toBe('pending')
    // finished phases show their summary; the running/pending ones do not
    expect(document.querySelector('[data-dev-phase-summary="tasks"]')).toHaveTextContent('审批')
    expect(document.querySelector('[data-dev-phase-summary="implement"]')).toBeNull()
    // mid-walk: no artifact list, no runnable entry, and no 体验 button
    expect(document.querySelector('[data-testid="dev-artifacts"]')).toBeNull()
    expect(document.querySelector('[data-testid="dev-runnable-version"]')).toBeNull()
    expect(document.querySelector('[data-testid="run-open-btn"]')).toBeNull()
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('V2 renders the finished run: dev-artifacts trio, dev-runnable-version, and 打开可运行版本', () => {
    const onOpenRun = vi.fn()
    render(<DevRunPanel run={byId('V2').fixture.devRun!} onOpenRun={onOpenRun} />)
    expect(document.querySelector('[data-testid="dev-artifacts"]')).toBeInTheDocument()
    const testRow = document.querySelector<HTMLElement>('[data-testid="dev-artifact-test"]')
    expect(testRow).toHaveTextContent('reports/test-v5.json')
    expect(document.querySelector('[data-testid="dev-artifact-build"]')).toHaveTextContent('points-service-0.5.0.tar.gz')
    expect(document.querySelector('[data-testid="dev-artifact-runtime"]')).toHaveTextContent('runtime/points-service')
    expect(document.querySelector('[data-testid="dev-runnable-version"]')).toHaveTextContent('0.5.0')
    fireEvent.click(document.querySelector<HTMLElement>('[data-testid="run-open-btn"]')!)
    expect(onOpenRun).toHaveBeenCalledTimes(1)
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('V3 renders the experience screen: run-preview[data-run-version] with the new rule in run-line rows', () => {
    const v3 = byId('V3')
    const onClose = vi.fn()
    render(<RunPreviewScreen preview={v3.fixture.runPreview!} onClose={onClose} />)
    expect(attr('run-preview', 'data-run-version')).toBe('0.5.0')
    const lines = document.querySelectorAll('[data-run-line]')
    expect(lines).toHaveLength(v3.fixture.runPreview!.lines.length)
    expect(v3.fixture.runPreview!.lines.map((l) => `[data-run-line="${l}"]`).join(','))
      .toContain('[data-run-line="大额采购需追加一级审批"]')
    expect(document.querySelector('[data-testid="run-preview-lines"]')).toHaveTextContent('大额采购')
    fireEvent.click(document.querySelector<HTMLElement>('[data-testid="run-preview-close"]')!)
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})
