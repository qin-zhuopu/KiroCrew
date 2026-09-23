// ACP-791: the release-phase states (R1~R6) are REAL-COMPONENT evidence, on
// the REAL workbench (口径更正 2026-09-23: the demo renders inside the true
// three-column AiStudioPage — tool-sidebar tabs, recent-activity, chat — the
// renderer rework is ACP-794; nothing here asserts a hand-rolled shell).
//
// The ticket's hard line — testid 与文案必须与真实组件一致，不许另造一套长得
// 像的 — is proven the only way that means anything: every rendered picture
// below is the real business component mounted the way the shipped suites
// mount it. R1~R4 go through the WHOLE workbench (renderStudio + AiStudioPage
// → the 发布 tab in the real ToolSidebar → the real PublishVersionList), the
// same route-level channel PublishRun.test.tsx uses; R5 is the real
// ReleaseJobPage at its real route with the real DeployLog inside; R6 is the
// real RunPreviewScreen. The assertions anchor on workbench testids
// (`ai-studio`, `tool-sidebar`, `recent-activity`, `ai-studio-publish-entry`)
// plus the §六 publish contracts — never on an invented stand-in.
//
// The publishApi seam is mocked the way the components' own suites mock it
// (PublishRun / ReleaseJobPage.test): a hoisted object swapped into the
// module, answering from THE SNAPSHOT (`seedPublish(state.publish)`) — the
// mock is exactly the in-memory fake ACP-794's wiring needs, so this file
// doubles as the worked example for wiring note 1 in states-release.ts.
// DeployLog's SSE gets the same FakeEventSource the real page test uses
// (wiring note 3). R3's 发布中 lands through the row's own real button —
// one real click, the frame's single act (wiring note 2).
//
// Why R5/R6 mount their components rather than the full workbench: they are
// separate ROUTE surfaces of it (the result bar's new-tab links), and the
// ACP-794 renderer branch does not exist yet — what this suite can and does
// prove is that each snapshot's payload drives the real component to the
// outline's exact DOM. Zero-fetch is watched with the same global spy as
// StateDemo.test.tsx (R5's SSE goes through the stub; fetch is never touched).
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import {
  isReleaseState,
  RELEASE_STATES,
  URL_V5,
  NEW_RULE,
  type ReleasePublishPayload,
  type ReleaseStateSnapshot,
} from './states-release'
// the base type stays where the ticket says it lives (read-only import)
import type { StateSnapshot } from './states'
import AiStudioPage from '../AiStudioPage'
import PublishVersionList from '../PublishVersionList'
import ReleaseJobPage from '../ReleaseJobPage'
import { RunPreviewScreen } from '../DevRunView'
import { renderStudio } from '../testUtils'

// --- the snapshot-backed publishApi fake (wiring note 1's worked example) ---
const pub = vi.hoisted(() => ({
  listVersions: vi.fn(),
  listRecords: vi.fn(),
  preview: vi.fn(),
  listJobs: vi.fn(),
  trigger: vi.fn(),
}))
// the workbench's own reads: the demo project (a clean committed world, so
// the commit bar and the activity feed render their honest empty states)
const studio = vi.hoisted(() => ({
  listProjects: vi.fn(),
  getProject: vi.fn(),
  saveDoc: vi.fn(),
  listDraftDocs: vi.fn(async () => ({ drafts: [] })),
  saveDraft: vi.fn(async () => ({ ok: true })),
  listDraftVersions: vi.fn(async () => ({ versions: [] })),
  listVersions: vi.fn(async () => ({ versions: [] })),
}))
vi.mock('../studioApi', async () => {
  const actual = await vi.importActual<typeof import('../studioApi')>('../studioApi')
  return { ...actual, publishApi: pub, studioApi: studio }
})
// the chat column is the one part of the workbench shell that is not the
// snapshot's business: ChatPane opens its slot through the scoped api and
// ChatEmbed opens a WebSocket, so both are stubbed exactly as the workbench's
// own suites stub them (AiStudioPage.test / PublishRun.test) — otherwise the
// zero-fetch claim below would be measuring the chat column, not the release
// frames. Path depth: this file sits one level deeper than those suites.
vi.mock('../../../app-sdk/ChatEmbed', () => ({
  default: () => <div data-testid="chat-embed-stub" />,
}))
const fakeApi = vi.hoisted(() => ({ api: null as unknown }))
vi.mock('../../../app-sdk', async () => {
  const actual = await vi.importActual('../../../app-sdk')
  return { ...actual, useAppApi: () => fakeApi.api }
})
fakeApi.api = { post: vi.fn(async () => ({ key: 'x' })) }

function state(id: string): ReleaseStateSnapshot {
  const s = RELEASE_STATES.find((x) => x.id === id)
  if (!s) throw new Error(`state ${id} missing`)
  return s
}

/** Answer every publish read from THIS frame's payload — listVersions,
 * listRecords, preview per version, jobs. The one thing the payload does not
 * carry is the trigger response, which each frame's story decides (R3's never
 * resolves; the settled frames read the run off the records instead). */
function seedPublish(p: ReleasePublishPayload) {
  pub.listVersions.mockResolvedValue({ versions: p.versions })
  pub.listRecords.mockResolvedValue({ records: p.records })
  pub.preview.mockImplementation((_id: string, v: string) =>
    Promise.resolve(p.previews[v] ?? { form: 'demo' as const, reason: '' }),
  )
  pub.listJobs.mockResolvedValue({ jobs: p.jobs ?? [] })
}

/** the REAL three-column workbench on the demo project — the exact channel
 * PublishRun.test.tsx drives (route → AiStudioPage → ToolSidebar → the 发布
 * tab). The frame's own docs ride getProject so the sidebar/empty states are
 * the same world the snapshot holds. */
function renderWorkbench() {
  const world = state('R1')
  studio.getProject.mockResolvedValue({ project: world.fixture.project, docs: world.fixture.docs })
  studio.listProjects.mockResolvedValue({ projects: [world.fixture.project] })
  return renderStudio(<AiStudioPage />, '/workspaces/p1/ai-studio')
}

const clickByTestId = (testid: string) => {
  const el = document.querySelector<HTMLElement>(`[data-testid="${testid}"]`)
  if (!el) throw new Error(`control ${testid} not found`)
  fireEvent.click(el)
}

async function openPublishList() {
  // the workbench paints a loading skeleton until getProject resolves; the
  // sidebar (and with it the 发布 entry) only exists after that
  await screen.findByTestId('tool-sidebar')
  // the entry IS in the real tool-sidebar tab strip (R1's contract row)
  clickByTestId('ai-studio-publish-entry')
  await screen.findByTestId('ai-studio-publish-version-list')
}

/** FakeEventSource, same shape as ReleaseJobPage.test.tsx — the page's log
 * half IS DeployLog, so the SSE frames land on this instance list. */
const FakeES = vi.hoisted(() => {
  class Fake {
    static instances: Fake[] = []
    onmessage: ((ev: MessageEvent) => void) | null = null
    onerror: (() => void) | null = null
    closed = false
    constructor(public url: string) {
      Fake.instances.push(this)
    }
    close() {
      this.closed = true
    }
    emit(frame: unknown) {
      this.onmessage?.({ data: JSON.stringify(frame) } as MessageEvent)
    }
  }
  return Fake
})

let fetchSpy: ReturnType<typeof vi.spyOn>
beforeEach(() => {
  vi.clearAllMocks()
  FakeES.instances = []
  fetchSpy = vi.spyOn(globalThis, 'fetch')
})
afterEach(() => {
  fetchSpy.mockRestore()
  vi.unstubAllGlobals()
})

// ---------------------------------------------------------------------------
// A. the snapshot DATA: the six frames are one world's reads, and the fields
// the components will derive their rules from agree frame to frame.
// ---------------------------------------------------------------------------

describe('states-release: data contract', () => {
  it('ships R1~R6 as StateSnapshot members (master can concatenate without a cast)', () => {
    const asBase: StateSnapshot[] = RELEASE_STATES // compile-time assignability
    expect(asBase.map((s) => s.id)).toEqual(['R1', 'R2', 'R3', 'R4', 'R5', 'R6'])
    for (const s of RELEASE_STATES) {
      expect(s.phase).toBe('release')
      expect(s.activeSurface).toBe('release')
      expect(s.outlineRef).toBe(s.id) // 提纲阶段二行号逐字
      expect(isReleaseState(s)).toBe(true)
      expect(s.label).toBeTruthy()
      expect(s.title).toBeTruthy()
      expect(s.caption).toBeTruthy()
      // every release frame stands on the committed design: the four Chinese
      // doc names (口径), clean markers — and the fixture AGREES (empty draft
      // store, same rule states.ts holds for its clean frame)
      expect(s.docs.map((d) => d.name)).toEqual([
        '产品需求设计文档.md',
        '用户旅程设计.md',
        '业务模型设计.md',
        '页面交互设计.md',
      ])
      expect(s.docs[0].version).toBe('V5')
      expect(s.dirty).toBe(false)
      expect(s.commitEnabled).toBe(false)
      expect(s.fixture.draftVersions).toHaveLength(0)
      // the committed V5 is an ODD row → manual provenance (附一)
      expect(s.versionHistory).toEqual([
        { version: 'V5', parity: 'odd', source: 'manual', time: expect.any(Number) },
      ])
    }
  })

  it('the version list and previews cover every row the release tab will show', () => {
    const p = state('R1').publish
    expect(p.versions.map((v) => v.version)).toEqual(['v5', 'v4', 'v3'])
    for (const v of p.versions) {
      expect(p.previews[v.version]?.reason).toBeTruthy() // R2's reason span needs it
    }
  })

  it('the hash rule has real data on both sides: before the settle v5 is new, after it v4 is superseded', () => {
    const latestOf = (p: ReleasePublishPayload) => p.records.find((r) => r.status === 'success')!.commitHash
    const v5Hash = state('R4').publish.versions.find((v) => v.version === 'v5')!.commitHash
    expect(latestOf(state('R1').publish)).not.toBe(v5Hash) // R1~R3: v5 gets its button
    expect(latestOf(state('R4').publish)).toBe(v5Hash) // R4 on: v5's button retires
  })

  // ACP-798: ① 历史版本 (above) ② 本版修改过的文件 ③ 每个文件的图谱拆解状态三态.
  it('every frame carries 本版修改过的文件, and R4 is the frame where all three 拆解 states are on screen at once', () => {
    for (const s of RELEASE_STATES) {
      const files = s.publish.files
      expect(files, `${s.id} carries no file list`).toBeTruthy()
      expect(files!.version).toBe('v5') // the list is THIS version's changes
      expect(files!.files.length).toBeGreaterThan(0)
      for (const f of files!.files) {
        expect(f.name).toMatch(/\.md$/)
        expect(['added', 'modified', 'deleted']).toContain(f.change)
        expect(['done', 'running', 'pending']).toContain(f.distill)
      }
    }
    // 尚未: nothing is distilled yet right after the release lands
    expect(state('R1').publish.files!.files.map((f) => f.distill)).toEqual([
      'pending',
      'pending',
      'pending',
    ])
    // R4 is the frame the outline needs: 已 / 正在 / 尚未 each appear at least
    // once, so one frame reads the whole three-state vocabulary
    const settling = state('R4').publish.files!.files.map((f) => f.distill)
    expect(settling).toEqual(['done', 'running', 'pending'])
    // and it only moves forward: R5 has 正在 left, R6 is all 已
    expect(state('R5').publish.files!.files.map((f) => f.distill)).toEqual(['done', 'done', 'running'])
    expect(state('R6').publish.files!.files.map((f) => f.distill)).toEqual(['done', 'done', 'done'])
    // a real mix of change kinds, so the 新增/修改/删除 labels are all readable
    expect(new Set(state('R1').publish.files!.files.map((f) => f.change))).toEqual(
      new Set(['added', 'modified', 'deleted']),
    )
  })

  it('R3→R4→R5 carry ONE job: the in-flight run is the record is the selected job', () => {
    expect(state('R3').publish.inFlight?.deploymentId).toBe('job-v5')
    expect(state('R4').publish.records[0].deploymentId).toBe('job-v5')
    expect(state('R5').publish.selectedJobId).toBe('job-v5')
    expect(state('R5').publish.jobs?.map((j) => j.id)).toEqual(['job-v5', 'job-v4', 'job-v3'])
    // the log replay terminates honestly (DeployLog closes on done; a stream
    // left open would reconnect and duplicate every line)
    const frames = state('R5').publish.logFrames!
    expect(frames.length).toBeGreaterThanOrEqual(2) // 边发边长 needs growth
    expect(frames[frames.length - 1].done).toBe(true)
    expect(frames[frames.length - 1].status).toBe('success')
  })

  it('the serving address is the 08 §〇 template, and the R4 record and R6 preview name the same release', () => {
    const rec = state('R4').publish.records[0]
    expect(rec.url).toBe(URL_V5)
    // 版本号-应用名-工号.gb10.jereh-pe.cn, scheme-less exactly as publish_url stores it
    expect(rec.url).toMatch(/^v5-points-14409\.gb10\.jereh-pe\.cn$/)
    expect(state('R6').publish.runPreview?.version).toBe('v5')
    // R6's feature list names this iteration's rule…
    expect(state('R6').publish.runPreview?.lines).toContain(NEW_RULE)
    // …and that rule is real committed text in the frame's own doc (the
    // experience claims only what the documents hold — same doctrine as the
    // dev-phase preview checking against graph labels)
    expect(state('R6').fixture.docs[0].content).toContain('大额采购')
  })
})

// ---------------------------------------------------------------------------
// B. the REAL workbench rendering each frame from that data.
// ---------------------------------------------------------------------------

describe('R1/R2 · 发版页签·版本列表·发版形态（真实工作台 + 真实 PublishVersionList 直出）', () => {
  it('R1: the workbench chrome is real, and opening the 发布 tab lists every version with its short hash', async () => {
    seedPublish(state('R1').publish)
    renderWorkbench()
    // the real three-column shell (口径更正): workbench root, the tool
    // sidebar, the recent-activity feed (honest empty state — a committed
    // world has no pending drafts), and the chat column (the embed only
    // mounts once ChatPane's slot open settles, hence findBy) — all present
    // BEFORE any publish interaction
    expect(await screen.findByTestId('ai-studio')).toBeInTheDocument()
    expect(screen.getByTestId('tool-sidebar')).toBeInTheDocument()
    expect(screen.getByTestId('recent-activity')).toBeInTheDocument()
    expect(screen.getByTestId('recent-activity-empty')).toBeInTheDocument()
    expect(await screen.findByTestId('chat-embed-stub')).toBeInTheDocument()
    await openPublishList()
    expect(screen.getByTestId('ai-studio-publish-version-list')).toBeInTheDocument()
    for (const v of state('R1').publish.versions) {
      const row = screen.getByTestId(`ai-studio-publish-version-row-${v.version}`)
      expect(row).toHaveTextContent(v.version)
      expect(row).toHaveTextContent(v.commitHash.slice(0, 7))
    }
    // states are DERIVED, not painted: no success record for v5 → 未发布;
    // v4/v3 have records → 已发布
    expect(
      within(screen.getByTestId('ai-studio-publish-version-row-v5')).getByTestId('ai-studio-publish-version-state'),
    ).toHaveTextContent('Unpublished')
    expect(
      within(screen.getByTestId('ai-studio-publish-version-row-v4')).getByTestId('ai-studio-publish-version-state'),
    ).toHaveTextContent('Published')
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('R2: the v5 row shows its 形态判定原因 and its publish button; the hash rule keeps v4 button-less', async () => {
    seedPublish(state('R2').publish)
    renderWorkbench()
    await openPublishList()
    const v5 = screen.getByTestId('ai-studio-publish-version-row-v5')
    // reason text is the component's own span, worded by B1's preview read
    // (a separate per-row query → findBy, not a synchronous get)
    expect(await within(v5).findByTestId('ai-studio-publish-reason-v5')).toHaveTextContent('git tag 标注：完整版')
    expect(within(v5).getByTestId('ai-studio-publish-btn-v5')).toBeEnabled()
    // v4: hash == latest success hash → NO button at all (not a disabled one)
    expect(
      within(screen.getByTestId('ai-studio-publish-version-row-v4')).queryByTestId('ai-studio-publish-btn-v4'),
    ).not.toBeInTheDocument()
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})

describe('R3 · 触发发版·发布中（真实工作台里的一次真实点击落地）', () => {
  it('clicking the v5 row 发布 button lands the frame on 发布中 with no release facts yet', async () => {
    seedPublish(state('R3').publish)
    // the frame's one act (wiring note 2): the trigger stays in flight, so
    // the component's own run state paints 发布中 and nothing else
    pub.trigger.mockReturnValue(new Promise(() => {}))
    renderWorkbench()
    await openPublishList()
    const row = screen.getByTestId('ai-studio-publish-version-row-v5')
    fireEvent.click(within(row).getByTestId('ai-studio-publish-btn-v5'))
    // the real trigger path fired with the real args (project, version, hash)
    const v5 = state('R3').publish.versions[0]
    expect(pub.trigger).toHaveBeenCalledWith('p1', 'v5', v5.commitHash)
    // 提纲 R3 关键点: the status testid reads 发布中 — and the lifecycle chip
    // says the same in its own element (§〇-1 分工). The button stays but
    // DISABLED while running — the honest behavior, recorded here so the
    // outline's "按钮消失" prose cannot quietly drift from the component.
    expect(within(row).getByTestId('ai-studio-publish-status-v5')).toHaveTextContent('Publishing…')
    expect(within(row).getByTestId('ai-studio-publish-version-state')).toHaveTextContent('Publishing…')
    expect(within(row).getByTestId('ai-studio-publish-btn-v5')).toBeDisabled()
    // badge/url are RELEASE facts — a running row never shows them (T6 rule)
    expect(within(row).queryByTestId('ai-studio-publish-form-badge-v5')).not.toBeInTheDocument()
    expect(within(row).queryByTestId('ai-studio-publish-url-v5')).not.toBeInTheDocument()
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})

describe('R4 · 发版成功·结果条（真实工作台直出：成功记录即本帧数据）', () => {
  it('the v5 row carries form badge + serving-url link + release-job link, all derived from the record', async () => {
    seedPublish(state('R4').publish)
    renderWorkbench()
    await openPublishList()
    const row = screen.getByTestId('ai-studio-publish-version-row-v5')
    // 完整版 badge — the record's form through the component's own i18n key
    expect(within(row).getByTestId('ai-studio-publish-form-badge-v5')).toHaveTextContent('Full')
    // the address verbatim (08 §四 探活 opens this), new tab
    const link = within(row).getByTestId('ai-studio-publish-url-v5')
    expect(link).toHaveAttribute('href', URL_V5)
    expect(link).toHaveAttribute('target', '_blank')
    // the 发布号 link opens the release-job page — the same job R5 shows
    const id = within(row).getByTestId('ai-studio-publish-id-v5')
    expect(id).toHaveAttribute('href', '/release-jobs/job-v5?project=p1')
    expect(id).toHaveTextContent('job-v5')
    // state re-derived: v5 is 已发布 with its button retired by the hash rule
    expect(within(row).getByTestId('ai-studio-publish-version-state')).toHaveTextContent('Published')
    expect(within(row).queryByTestId('ai-studio-publish-btn-v5')).not.toBeInTheDocument()
    // superseded v4: still 已发布, and its button is BACK (the rollback
    // re-publish case — proof the strip is data, not a decoration)
    const v4 = screen.getByTestId('ai-studio-publish-version-row-v4')
    expect(within(v4).getByTestId('ai-studio-publish-btn-v4')).toBeInTheDocument()
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})

// ---------------------------------------------------------------------------
// C. ACP-798: 发版页签 = ① 历史版本 ② 本版修改过的文件 ③ 每个文件的图谱拆解
// 状态三态. Two 口径 the ticket states as hard lines: 演示的中间列只放文档编辑器
// (发版的东西都在「发版」页签里看), and the file list is a LIST — never a
// box-and-arrow diagram. Both are asserted below on the real components.
// ---------------------------------------------------------------------------

/** Enter the demo the way the owner does (StatesWorkspace.test.tsx): from a
 * workbench whose project has ALREADY loaded, through the entry button, then
 * pick the frame on the dock. This is the channel ACP-798's wiring must work
 * on — the frame's own payload, no mocked publish client in the path. */
async function openDemoFrame(id: string) {
  renderWorkbench()
  fireEvent.click(await screen.findByTestId('demo-entry-btn'))
  await screen.findByTestId('demo-states-dock')
  fireEvent.click(screen.getByTestId(`demo-states-select-${id}`))
  await waitFor(() =>
    expect(screen.getByTestId('demo-states-dock')).toHaveAttribute('data-demo-state', id),
  )
  await openPublishList()
}

describe('ACP-798 · 发版页签·本版修改过的文件与三态拆解（真实工作台 + 真实 PublishVersionList）', () => {
  it('R1: 历史版本 readable, 本版修改的文件 listed above it — 过程在上, 历史在下', async () => {
    await openDemoFrame('R1')
    const sidebar = screen.getByTestId('tool-sidebar')
    // ② the changed-file list of this version — and it lives in the 发版 tab,
    // i.e. inside the right sidebar, not in the center column (口径)
    const files = screen.getByTestId('ai-studio-publish-files')
    expect(sidebar.contains(files)).toBe(true)
    expect(files).toHaveTextContent('Files changed in this version')
    // ③ one row per file, each with its own 名称 / 变更 / 拆解状态 testids
    for (const f of state('R1').publish.files!.files) {
      const row = screen.getByTestId(`release-file-${f.name}`)
      expect(row).toHaveTextContent(f.name)
      const change = screen.getByTestId(`release-file-change-${f.name}`)
      expect(change).toHaveTextContent(
        { added: 'Added', modified: 'Modified', deleted: 'Deleted' }[f.change],
      )
      const distill = screen.getByTestId(`release-file-distill-${f.name}`)
      expect(distill).toHaveAttribute('data-distill-state', f.distill)
      expect(distill).toHaveTextContent('Not distilled into the graph yet')
    }
    // ① 历史版本 is still there, read off the same tab
    expect(screen.getByTestId('ai-studio-publish-version-list')).toBeInTheDocument()
    // owner's sidebar layout rule: 过程 (the current task list + each task's
    // state) sits ABOVE 历史记录 — the file block precedes the version list
    const versions = screen.getByTestId('ai-studio-publish-version-list')
    expect(files.compareDocumentPosition(versions) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    // 口径: 演示状态下中间列只放文档编辑器 — the center shows the frame's doc,
    // the release rows stay in the sidebar, and nothing here is a 方框箭头图
    // (every file is a row in a list, so no svg overlay exists in the tab)
    expect(await screen.findByTestId('doc-产品需求设计文档.md')).toBeInTheDocument()
    expect(files.querySelector('svg')).toBeNull()
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('R4: one frame reads all three 拆解 states — 已 / 正在 / 尚未 each readable by testid', async () => {
    await openDemoFrame('R4')
    const seen: string[] = []
    for (const f of state('R4').publish.files!.files) {
      const distill = screen.getByTestId(`release-file-distill-${f.name}`)
      const s = distill.getAttribute('data-distill-state')!
      seen.push(s)
      expect(distill).toHaveTextContent(
        {
          done: 'Distilled into the graph',
          running: 'Distilling into the graph…',
          pending: 'Not distilled into the graph yet',
        }[s as 'done' | 'running' | 'pending'],
      )
    }
    // 三态都要有独立 testid, 帧里各出现至少一次 — R4 is that frame
    expect(seen).toEqual(['done', 'running', 'pending'])
    // the release itself is unaffected by where its files are in the 拆解:
    // v5 is published, and the version list still reads it (① keeps working)
    expect(
      within(screen.getByTestId('ai-studio-publish-version-row-v5')).getByTestId(
        'ai-studio-publish-version-state',
      ),
    ).toHaveTextContent('Published')
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  // ---- ACP-798 (owner 追加): 「发版」页签顶部要有「发版」按钮 ----------------

  it('R1: the 发版 tab opens with its OWN 发版 button at the very top, above the file list and the versions', async () => {
    await openDemoFrame('R1')
    const btn = screen.getByTestId('release-btn') // ReleaseControl's own contract
    expect(btn).toBeEnabled()
    // 动作按钮跟着页签走: the button is the FIRST thing in the 发版 tab — it
    // precedes both halves of the tab, and it lives in the sidebar, never in
    // the center column (which stays the doc editor)
    const files = screen.getByTestId('ai-studio-publish-files')
    const versions = screen.getByTestId('ai-studio-publish-version-list')
    expect(within(screen.getByTestId('tool-sidebar')).getByTestId('release-btn')).toBeInTheDocument()
    expect(btn.compareDocumentPosition(files) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(btn.compareDocumentPosition(versions) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    // it is ReleaseControl itself — the same control the top bar's act uses,
    // so it carries that component's hint title
    expect(btn).toHaveAttribute(
      'title',
      'Cut a release and generate code from the requirement graph',
    )
    expect(await screen.findByTestId('doc-产品需求设计文档.md')).toBeInTheDocument()
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('R1: clicking it fires the SAME act a row button fires — the version goes 发布中', async () => {
    await openDemoFrame('R1')
    fireEvent.click(screen.getByTestId('release-btn'))
    const v5 = screen.getByTestId('ai-studio-publish-version-row-v5')
    // the publish ran through PublishVersionList's own publish(): the status
    // testid reads 发布中 and the record never lands (R1's world has no v5
    // success record), so the frame rests honestly on the running state
    expect(within(v5).getByTestId('ai-studio-publish-status-v5')).toHaveTextContent('Publishing…')
    expect(within(v5).getByTestId('ai-studio-publish-btn-v5')).toBeDisabled()
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('R4: the button is present but retired by the hash rule — v5 is already the published version', async () => {
    await openDemoFrame('R4')
    // present (owner: 页签顶部要有发版按钮) …
    const btn = screen.getByTestId('release-btn')
    // … and disabled for the SAME reason that row's own 发布 button vanished:
    // the row lost its button, so the tab control mirrors it, not a second rule
    expect(within(screen.getByTestId('ai-studio-publish-version-row-v5')).queryByTestId('ai-studio-publish-btn-v5')).not.toBeInTheDocument()
    expect(btn).toBeDisabled()
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('an ordinary workbench passes no releaseFiles and renders exactly what the tab rendered before', async () => {
    // the default path: PublishVersionList mounted the way the app mounts it
    // — no prop, real (mocked-client) reads, versions on screen, NO file list
    pub.listVersions.mockResolvedValue({ versions: state('R1').publish.versions })
    pub.listRecords.mockResolvedValue({ records: [] })
    pub.preview.mockResolvedValue({ form: 'demo', reason: '' })
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <PublishVersionList projectId="p1" />
      </QueryClientProvider>,
    )
    await screen.findByTestId('ai-studio-publish-version-list')
    expect(screen.getByTestId('ai-studio-publish-version-row-v5')).toBeInTheDocument()
    expect(screen.queryByTestId('ai-studio-publish-files')).not.toBeInTheDocument()
    expect(screen.queryByTestId('release-btn')).not.toBeInTheDocument() // no tab action either
    expect(document.querySelector('[data-distill-state]')).toBeNull()
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})

describe('R5 · 发布详情页·历史与流式日志（真实 ReleaseJobPage + DeployLog）', () => {
  it('opens the selected job, lists the project history, and replays the log frame by frame', async () => {
    const p = state('R5').publish
    seedPublish(p)
    vi.stubGlobal('EventSource', FakeES as unknown as typeof EventSource)
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[`/release-jobs/${p.selectedJobId}?project=demo-product`]}>
          <Routes>
            <Route path="/release-jobs/:jobId" element={<ReleaseJobPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(await screen.findByTestId('ai-studio-release-job-page')).toBeInTheDocument()
    // 发布历史列表 + every row (read-only: the rows are the contract)
    const list = await screen.findByTestId('ai-studio-release-job-history-list')
    for (const j of p.jobs!) {
      expect(within(list).getByTestId(`ai-studio-release-job-row-${j.id}`)).toBeInTheDocument()
    }
    expect(within(list).getByTestId('ai-studio-release-job-status-job-v5')).toHaveTextContent('Completed')
    // the log wrapper (contract) holds the reused DeployLog (its own testid),
    // streaming the URL the log endpoint answers
    await screen.findByTestId(`ai-studio-release-job-log-${p.selectedJobId}`)
    const es = FakeES.instances[FakeES.instances.length - 1]
    expect(es.url).toBe(`/api/apps/ai-studio/publish/${p.selectedJobId}/log?project=demo-product`)
    const log = screen.getByTestId(`deploy-log-${p.selectedJobId}`)
    // the inner pre is the a11y contract: role=log + aria-live
    expect(within(log).getByRole('log')).toHaveAttribute('aria-live', 'polite')
    // 边发边长: each frame APPENDS (the wire shape is new-lines-only)
    const seen: string[] = []
    for (const frame of p.logFrames!) {
      es.emit(frame)
      seen.push(...frame.lines)
      await waitFor(() => expect(log).toHaveTextContent(seen[seen.length - 1]))
    }
    expect(within(log).getByRole('log').textContent).toBe(seen.join('\n'))
    // the done frame closes the stream (a live EventSource left open would
    // reconnect and re-play, duplicating every line)
    await waitFor(() => expect(es.closed).toBe(true))
    // the header offers the app URL — the R4 address, https-prefixed by the page
    const url = await screen.findByTestId('ai-studio-release-job-open-url')
    expect(url).toHaveAttribute('href', `https://${URL_V5}`)
    expect(fetchSpy).not.toHaveBeenCalled() // SSE went through the stub, fetch never
  })
})

describe('R6 · 线上可访问（真实体验页承载这一版的功能清单）', () => {
  it('the preview screen renders the frame list including this iteration new rule', () => {
    const preview = state('R6').publish.runPreview!
    // the overlay's positioning context is the workbench center (same as
    // DemoWorkspace mounts it); RunPreviewScreen itself needs no providers
    render(
      <div style={{ position: 'relative' }}>
        <RunPreviewScreen preview={preview} />
      </div>,
    )
    // the existing 体验页 contract (ACP-735): version attr + the lines list
    expect(screen.getByTestId('run-preview')).toHaveAttribute('data-run-version', 'v5')
    const lines = screen.getByTestId('run-preview-lines')
    for (const l of preview.lines) {
      expect(lines.querySelector(`[data-run-line="${l}"]`)).not.toBeNull()
    }
    // the acceptance point: 界面里能看到本次新增的规则
    expect(lines).toHaveTextContent('大额采购需追加一级审批')
    expect(lines).toHaveTextContent('消费 1 元累积 1 积分') // the old rules still run
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})
