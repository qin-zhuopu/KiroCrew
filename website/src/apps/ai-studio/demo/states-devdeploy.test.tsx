// ACP-792 / ACP-799: the dev + deploy state frames (V1~V3 / P1~P2).
//
// WHAT THIS PROVES, AND HOW. The renderer (AiStudioPage's demo wiring, ACP-794)
// is not mine to touch, so mounting the full `?demo=states` route and asserting
// my frames paint there is not possible from inside this file — but a state
// frame is only as real as the components it feeds, so every render assertion
// here mounts the REAL business component the wired surface will use, with MY
// snapshot's payload: `DevRunPanel` / `RunPreviewScreen` (DevRunView.tsx) from
// `fixture.devRun` / `fixture.runPreview`, and — since ACP-799 moves this slice
// into the sidebar — the real `ToolSidebar` with the same injection ACP-796 is
// told to hand it. That is the outline's hard rule (testid 与文案必须和真实组件
// 一致，不许另造长得像的) enforced at the data layer: if these frames ever drive
// a branch, they provably produce dev-run-panel / dev-phase-* / dev-artifacts /
// dev-runnable-version / run-preview / run-line exactly as the outline names
// them, inside 开发 / 部署 tab that renders them.
//
// What ACP-799 adds: the content lives in a SIDEBAR tab (owner's layout rule —
// 中间列只显示文字内容), so each frame names its tab (`activeSidebarTab`), the
// history that goes UNDER the 过程, and the tab-top action button's state. The
// cases below drive the shipped `ToolSidebar` with those fields and assert the
// uniform shape it owes every tab: action on top, 过程, then 历史记录.
//
// The deploy frames have no pure-props business component to mount (the real
// DeployLog streams SSE, which a zero-fetch demo cannot drive — 任务书:
// 「部署段先按快照帧做」), so P1~P2 are asserted at the payload-contract level:
// the `deploy-log-<deploymentId>` keying, the 进行中→完成 status pair, the
// prefix-extension growth of the log lines, the URL template, and the 单实例
// replacement facts. A later renderer branch consumes exactly these fields.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { i18nT } from '../../../i18n/t'
import DevRunPanel, { RunPreviewScreen } from '../DevRunView'
import ReleaseControl from '../ReleaseControl'
import ToolSidebar from '../ToolSidebar'
import DeployFramePanel from './DeployFramePanel'
import { COMMIT_STATES } from './states-commit'
import {
  DEPLOY_PAYLOADS,
  DEV_DEPLOY_STATES,
  isDevDeployState,
  type DevDeploySnapshot,
} from './states-devdeploy'

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
    // ACP-803 finished the move: the subject is observed in the tab, so the
    // CENTER of every frame is the open document — 'doc', like every other slice
    expect(DEV_DEPLOY_STATES.map((s) => s.activeSurface)).toEqual(['doc', 'doc', 'doc', 'doc', 'doc'])
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

// ---------------------------------------------------------------------------
// ACP-799: the same content, rendered where the owner wants it — the sidebar's
// 开发 / 部署 tab. `injectFor` builds exactly what the frame's contract tells
// ACP-796 to pass, so these cases measure the real seam rather than a
// re-implementation of it: the panels are the shipped components, the button is
// ReleaseControl's own, and the layout is ToolSidebar's.
// ---------------------------------------------------------------------------

/** what the renderer hands `ToolSidebar` for one frame (the contract's snippet;
 * `onRelease` defaults to a no-op — cases that watch the press pass their own) */
function injectFor(f: DevDeploySnapshot, onRelease?: () => Promise<void>) {
  const action = (
    <ReleaseControl
      act={f.activeSidebarTab}
      disabled={f.actionDisabled}
      onRelease={onRelease ?? (async () => {})}
    />
  )
  return f.activeSidebarTab === 'dev'
    ? { action, current: <DevRunPanel run={f.fixture.devRun!} />, history: f.history }
    : { action, current: <DeployFramePanel frame={DEPLOY_PAYLOADS[f.id]} />, history: f.history }
}

function mountSidebar(f: DevDeploySnapshot) {
  const injected = injectFor(f)
  return render(
    <ToolSidebar
      onOpenTab={vi.fn()}
      docs={[]}
      projectId={f.fixture.project.id}
      initialTool={f.activeSidebarTab}
      {...(f.activeSidebarTab === 'dev' ? { dev: injected } : { deploy: injected })}
    />,
  )
}

/** DOM order: `a` must come before `b`. */
const precedes = (a: Element, b: Element) =>
  Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING)

describe('ACP-799 the frames name their sidebar tab', () => {
  it('every frame is a dev/deploy frame, and its tab IS its phase', () => {
    for (const s of DEV_DEPLOY_STATES) {
      expect(isDevDeployState(s), s.id).toBe(true)
      expect(s.activeSidebarTab, s.id).toBe(s.phase)
    }
    // the commit pair declares the SAME field name for its own tab, so the
    // guard keys on the VALUE: C1/C2 are not ours, or the 提交 frames would
    // light 开发/部署 and lose their tab (ACP-803)
    expect(COMMIT_STATES.every((s) => !isDevDeployState(s))).toBe(true)
    // 开发 frames light 开发, 部署 frames light 部署 — V1~V3 and P1~P2
    expect(DEV_DEPLOY_STATES.map((s) => s.activeSidebarTab))
      .toEqual(['dev', 'dev', 'dev', 'deploy', 'deploy'])
  })

  it('过程 and 历史记录 do not overlap: the current run / deployment is never also a history row', () => {
    const v1 = byId('V1')
    expect(v1.history.map((r) => r.id)).not.toContain(v1.fixture.devRun!.id)
    const p2 = byId('P2')
    expect(p2.history.map((r) => r.id)).not.toContain(DEPLOY_PAYLOADS.P2.deploymentId)
    for (const s of DEV_DEPLOY_STATES) expect(s.history.length, s.id).toBeGreaterThan(0)
  })

  it('单实例替换 and 历史 agree on one number: v4’s deployment is the row the tab already lists', () => {
    for (const id of ['P1', 'P2']) {
      const replaced = DEPLOY_PAYLOADS[id].replaced!
      expect(byId(id).history.map((r) => r.id), id).toContain(replaced.deploymentId)
      expect(byId(id).history.find((r) => r.id === replaced.deploymentId)!.status, id).toBe('已替换')
    }
  })

  it('③ the middle column stays a document: every frame opens the focus doc', () => {
    for (const s of DEV_DEPLOY_STATES) {
      expect(s.selectedDoc, s.id).toBe('产品需求设计文档.md')
      expect(s.fixture.docs.map((d) => d.name), s.id).toContain(s.selectedDoc)
      expect(s.buffer.length, s.id).toBeGreaterThan(0)
    }
  })

  it('the action button follows the frame honestly (ACP-803): each group\'s FIRST frame is live, the rest are done', () => {
    // V1 / P1: the act has not landed yet, so its button is live — pressing it
    // is what the caller wires to "land the next frame". Not a live no-op.
    expect(byId('V1').actionDisabled).toBe(false)
    expect(byId('P1').actionDisabled).toBe(false)
    // V2 / V3 / P2: the act already ran (开发 完成 / 已上线), so the button is
    // disabled — a frozen design is developed once, a version deployed once.
    for (const id of ['V2', 'V3', 'P2']) expect(byId(id).actionDisabled, id).toBe(true)
  })
})

describe('ACP-799 the real sidebar renders the frames', () => {
  it('V1: the 开发 tab carries the four-phase panel as its 过程, the history below it, and the 开发 button on top', () => {
    mountSidebar(byId('V1'))

// the tab-top action button is ReleaseControl's own (testid + shipped word).
    // V1 is the group's first frame — its act has not landed, so the button is
    // LIVE (ACP-803: pressing it lands the next frame, see the case below).
    const button = screen.getByTestId('dev-btn')
    expect(button).toHaveTextContent(i18nT('apps.aiStudio.dev_start'))
    expect(button).toBeEnabled()

    // 过程 = the shipped four-phase panel, fed by THIS frame's run
    expect(attr('dev-run-panel', 'data-dev-run-id')).toBe('dev-v5')
    expect(attr('dev-phase-implement', 'data-dev-phase-status')).toBe('running')

    // the uniform shape the owner asked for: action → 过程 → 历史记录
    const action = screen.getByTestId('dev-btn')
    const panel = screen.getByTestId('dev-run-panel')
    const history = screen.getByText(i18nT('apps.aiStudio.history'))
    expect(precedes(action, panel)).toBe(true)
    expect(precedes(panel, history)).toBe(true)

    // and the history rows are the frame's, not the shipped DEV_HISTORY fixture
    for (const r of byId('V1').history) expect(screen.getByText(r.id)).toBeInTheDocument()
    expect(screen.queryByText('dev-309')).not.toBeInTheDocument()

    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('V1 的「开发」按钮按下去真的会发生：onRelease 被调用（落到下一帧由接线做）', async () => {
    const onRelease = vi.fn(async () => {})
    const f = byId('V1')
    const injected = injectFor(f, onRelease)
    render(
      <ToolSidebar
        onOpenTab={vi.fn()}
        docs={[]}
        projectId={f.fixture.project.id}
        initialTool="dev"
        dev={injected}
      />,
    )
    fireEvent.click(screen.getByTestId('dev-btn'))
    await waitFor(() => expect(onRelease).toHaveBeenCalledTimes(1))
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('P1 的「部署」按钮同样可点，按下即落下一帧（发布完成）', async () => {
    const onRelease = vi.fn(async () => {})
    const f = byId('P1')
    const injected = injectFor(f, onRelease)
    render(
      <ToolSidebar
        onOpenTab={vi.fn()}
        docs={[]}
        projectId={f.fixture.project.id}
        initialTool="deploy"
        deploy={injected}
      />,
    )
    fireEvent.click(screen.getByTestId('deploy-btn'))
    await waitFor(() => expect(onRelease).toHaveBeenCalledTimes(1))
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('P2: the 部署 tab carries the deploy record + log as its 过程, the 部署 button on top, history below', () => {
    mountSidebar(byId('P2'))

    const button = screen.getByTestId('deploy-btn')
    expect(button).toHaveTextContent(i18nT('apps.aiStudio.tool_deploy'))
    expect(button).toBeDisabled()

    // 过程 = the shipped deploy panel: the record, the live feature list, the log
    expect(screen.getByTestId(`deploy-log-${DEPLOY_PAYLOADS.P2.deploymentId}`)).toBeInTheDocument()
    expect(screen.getByTestId('deploy-online-features')).toHaveTextContent('大额采购需追加一级审批')
    expect(screen.getByTestId('ai-studio-release-job-status-' + DEPLOY_PAYLOADS.P2.deploymentId))
      .toHaveTextContent(i18nT('apps.aiStudio.release_job_status_success'))

    const history = screen.getByText(i18nT('apps.aiStudio.history'))
    expect(precedes(screen.getByTestId('deploy-frame-' + DEPLOY_PAYLOADS.P2.deploymentId), history)).toBe(true)
    for (const r of byId('P2').history) expect(screen.getByText(r.id)).toBeInTheDocument()
    expect(screen.queryByText('deploy-024')).not.toBeInTheDocument()

    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('a caller that injects nothing keeps today’s fixture-backed tab (零行为变化)', () => {
    render(<ToolSidebar onOpenTab={vi.fn()} docs={[]} projectId="demo-product" initialTool="dev" />)
    // the shipped DEV / DEV_HISTORY fixtures, and no action button at all
    expect(screen.queryByTestId('dev-btn')).not.toBeInTheDocument()
    expect(screen.getByText('dev-309')).toBeInTheDocument()
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})
