// Client for the ai-studio project backend
// (/api/apps/ai-studio/*, src/kiro_crew/apps/builtins/ai_studio/backend/).
//
// Plain same-origin fetch, the issue-radar precedent: a builtin page is served
// by the gateway itself, so the dashboard session cookie authenticates it —
// the scoped app api would add an allowlist check against a list this same
// app declares, buying nothing for its own namespace.
//
// Errors carry the backend's machine-readable `code` where one exists, so a
// caller can branch on "project_not_found" vs "app_disabled" without string
// matching English prose (the backend's error text is not localized; the codes
// are its stable API).

const API = '/api/apps/ai-studio'

export interface StudioProject {
  id: string
  name: string
  description: string
  createdAt: number
}

export interface StudioDoc {
  name: string
  content: string
}

/** One autosaved draft record since the last commit (ACP-720 contract:
 * drafts/<doc>/<timestamp>.md). `time` is epoch seconds from the record's
 * timestamp filename. */
export interface StudioDraftVersion {
  name: string
  time: number
  content: string
}

/** One committed version (ACP-720 contract: versions/<doc>/<timestamp>.md).
 * `diff` is the unified diff against the previous version; the earliest
 * version carries the whole document as additions. */
export interface StudioVersion {
  name: string
  time: number
  diff: string
}

/** One doc holding a current autosave draft (ACP-727: the project-level
 * commit reads the whole list to know what to promote). `changed` is the
 * draft-vs-committed comparison the top-bar summary uses to skip showing a
 * draft that no longer differs from the doc. */
export interface StudioDraftDoc {
  name: string
  content: string
  changed: boolean
}

/** One node of the requirement graph the commits feed (ACP-729). The graph
 * is not a backend endpoint yet — the shape is written here first so the
 * demo snapshots and the future `GET …/graph` response share one type, and
 * neither side invents fields the other does not have. */
export interface StudioGraphNode {
  id: string
  label: string
  /** requirement | doc | module — the three kinds the graph speaks */
  kind: 'requirement' | 'doc' | 'module'
  /** for kind=requirement: the doc whose committed text produced it */
  doc?: string
}

/** One directed edge between two graph nodes (`from` depends-on/traces-to
 * `to`; kind names which relation. Ids reference StudioGraphNode.id. */
export interface StudioGraphEdge {
  from: string
  to: string
  kind: 'trace' | 'depends'
}

export interface StudioGraph {
  nodes: StudioGraphNode[]
  edges: StudioGraphEdge[]
}

/** One release cut from the committed docs (ACP-730). Same doctrine as
 * StudioGraph: no endpoint yet, the type is written first so the demo
 * snapshot and the future release API agree on one shape. */
export interface StudioRelease {
  version: string
  time: number
  /** what this release froze, in one line — the panel's caption */
  notes: string
}

/** One structured change the AI distillation proposes for the graph
 * (ACP-733). Same "type written first" doctrine: no endpoint yet, the demo
 * snapshot and the future distillation API share one shape. `kind` names
 * what happens to `target`; `evidenceDoc` is the source paragraph the change
 * was distilled from, so every candidate is traceable to a document passage
 * (the acceptance doc's step 8 requirement). */
export interface StudioDistillCandidate {
  id: string
  kind: 'add' | 'modify' | 'remove'
  /** graph node id this candidate changes */
  target: string
  /** one-line summary shown in the candidate list */
  summary: string
  /** "doc.md § section" — the paragraph the change was distilled from */
  evidenceDoc: string
}

/** A distillation run the AI launched after a release (ACP-733): the
 * candidate structured changes derived from the frozen documents, plus the
 * status the panel shows while it runs. `appliedAt` is set once the graph
 * has absorbed the accepted candidates. */
export interface StudioDistillation {
  id: string
  /** the release whose frozen docs this distilled from */
  releaseVersion: string
  status: 'running' | 'done'
  candidates: StudioDistillCandidate[]
  /** unix seconds once status=done, absent while running */
  appliedAt?: number
}

/** A document version the system regenerated FROM the distilled structured
 * facts (ACP-734) — the acceptance doc's reverse link: docs → graph is not a
 * one-way street, the applied distillation flows back into a new document
 * version. Same "type written first" doctrine: no endpoint yet, the demo
 * snapshot and the future regeneration API share one shape. `generatedFrom`
 * names the distillation run whose facts produced `content`. */
export interface StudioRegeneration {
  /** the version label this regen produced (the new row in the history) */
  version: string
  /** the StudioDistillation.id whose applied facts generated this content */
  generatedFrom: string
  docName: string
  /** the full regenerated document — the "new version" is content, not a
   * badge: the version row's own diff speaks the change */
  content: string
}

/** One business point in the paired-diff review (ACP-734): the three views
 * of the SAME change shown side by side so the user can check whether the
 * system understood them — left what the USER changed (lines sliced from the
 * user's own version-row diff), middle the structured candidate the
 * distillation produced for this point (with its evidence paragraph), right
 * what the REGENERATION changed for it (lines sliced from the regen's row).
 * An empty side is data, not a gap: a purely distilled point has no user
 * lines, a graph-only removal has none on either side. The generator proves
 * every line shown here is a line its version rows' diffs carry. */
export interface StudioDiffGroup {
  /** the business point, e.g. 「兑换券 7 天有效」 — one per candidate */
  point: string
  /** the StudioDistillCandidate.id this group pairs against */
  candidateId: string
  /** the structured change(s) for this point (the candidate list's own rows) */
  structuredChanges: StudioDistillCandidate[]
  /** unified-diff lines from the user's commit for this point (may be empty) */
  userDiff: string
  /** unified-diff lines from the regeneration for this point (may be empty) */
  regenDiff: string
}

/** One phase of a development run (ACP-735): the acceptance doc's step-13
 * four-stage process — 任务生成 → 实现 → 测试 → 构建. `summary` is the
 * one-fact sentence the process view shows once the phase is done; it lives
 * in the snapshot, so the "process" is recorded data, never a timer
 * inventing progress on screen. */
export interface StudioDevPhase {
  name: 'tasks' | 'implement' | 'test' | 'build'
  status: 'pending' | 'running' | 'done'
  /** one factual line shown when done (empty while not) */
  summary: string
}

/** One product of a development run (ACP-735): the test report, the build
 * output, the runtime entry — the 结果 page of acceptance-doc step 14. */
export interface StudioDevArtifact {
  kind: 'test' | 'build' | 'runtime'
  path: string
}

/** A development run opened on a frozen design (ACP-735, acceptance-doc
 * steps 12-15): 「开始开发」records WHICH design/graph version it builds
 * (designVersion — the traceability anchor), the four phases advance as
 * snapshot frames, and the finished run names a runnableVersion the demo
 * opens as a built-in preview (never a server). Same "type written first"
 * doctrine: no endpoint yet, snapshot and future API share this shape. */
export interface StudioDevRun {
  id: string
  /** the frozen design this run implements — e.g. "v4 · graph@distill-v3";
   * the generator proves it names THIS world's regen version and
   * distillation id, so the run traces back to the applied facts */
  designVersion: string
  phases: StudioDevPhase[]
  artifacts: StudioDevArtifact[]
  /** set only when the build phase is done — the 体验 entry appears with
   * its product, not before */
  runnableVersion?: string
}

/** The built-in experience screen of a finished dev run (ACP-735,
 * acceptance-doc step 15): what 「打开可运行版本」 opens — an internal route
 * onto this data inside the demo overlay, NEVER a server, container or real
 * deployment. `lines` is the feature list the preview shows, and the
 * generator proves it is exactly the requirement-node labels of the graph
 * the run built on: the experience claims only what the structured design
 * promises. */
export interface StudioRunPreview {
  version: string
  /** the StudioDevRun.id this preview belongs to */
  devRunId: string
  title: string
  lines: string[]
}

/** One node of the project-wide history timeline (ACP-736, acceptance-doc
 * step 16): 修改/提交/发版/沉淀/开发/运行 are five-plus-one DIFFERENT kinds
 * of fact — the kind union is closed on purpose (no AI-source variant: the
 * demo models every doc edit as human-made, per the DAG's 显式不做). `links`
 * are the ids of the events this one was produced from, so any final result
 * walks back to the first edit by following real references, not by
 * re-deriving anything. `ref` names the demo snapshot the event's own view
 * lives in — jumping to an event loads THAT snapshot (回放 doctrine: 跳转=
 * 加载快照, never reverse-compute). */
export type StudioHistoryKind = 'edit' | 'commit' | 'release' | 'distill' | 'dev' | 'run'

export interface StudioProjectHistoryEvent {
  id: string
  kind: StudioHistoryKind
  /** epoch seconds, the order the timeline renders */
  at: number
  /** the demo snapshot key carrying this event's own view (the jump target) */
  ref: string
  summary: string
  /** ids of the earlier events this one was produced from */
  links: string[]
}

/** The whole project history as one snapshot field (the timeline panel's
 * data; `events` newest-first is not assumed — the view sorts by `at`). */
export interface StudioProjectHistory {
  events: StudioProjectHistoryEvent[]
}

/** One source file a release generated (ACP-730). `derivedFrom` names the
 * graph nodes (requirements) the file implements — the demo generator
 * cross-checks that set against the graph delta, so "generated code matches
 * the graph change" is a derived fact of the snapshots. `content` is the
 * whole (short, demonstrative) file so the preview needs no second read. */
export interface StudioGeneratedFile {
  path: string
  language: 'python' | 'sql'
  content: string
  derivedFrom: string[]
}

export class StudioApiError extends Error {
  readonly code: string
  readonly status: number
  constructor(status: number, code: string, message: string) {
    super(message)
    this.code = code
    this.status = status
  }
}

/** The client's method shape, so the demo runtime can hand the workbench a
 * snapshot-backed stand-in (website/src/apps/ai-studio/demo/runtime.ts)
 * without a type fork at every call site. */
export type StudioApi = {
  listProjects: () => Promise<{ projects: StudioProject[] }>
  createProject: (name: string, description: string) => Promise<{ project: StudioProject }>
  getProject: (id: string) => Promise<{ project: StudioProject; docs: StudioDoc[] }>
  saveDoc: (id: string, name: string, content: string) => Promise<{ doc: StudioDoc }>
  listDraftDocs: (id: string) => Promise<{ drafts: StudioDraftDoc[] }>
  saveDraft: (id: string, name: string, content: string) => Promise<{ ok: boolean }>
  listDraftVersions: (id: string, name: string) => Promise<{ versions: StudioDraftVersion[] }>
  listVersions: (id: string, name: string) => Promise<{ versions: StudioVersion[] }>
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // Demo mode replaces this whole client with the snapshot-backed fake; the
  // guard is the §5 promise written down — if a code path still reaches for
  // the network while a demo snapshot is loaded, it fails here instead of
  // quietly writing into the operator's real project store.
  if (window.location.search.includes('demo=')) {
    throw new StudioApiError(400, 'demo_mode', 'demo mode never reads or writes the real store')
  }
  const res = await fetch(API + path, {
    credentials: 'same-origin',
    headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
    ...init,
  })
  if (!res.ok) {
    let code = 'request_failed'
    let message = res.statusText
    try {
      const body = await res.json()
      if (typeof body?.code === 'string') code = body.code
      if (typeof body?.error === 'string') message = body.error
    } catch {
      /* non-JSON error body: keep statusText */
    }
    throw new StudioApiError(res.status, code, message)
  }
  return res.json() as Promise<T>
}

export const studioApi: StudioApi = {
  listProjects: () => request<{ projects: StudioProject[] }>('/projects'),
  createProject: (name: string, description: string) =>
    request<{ project: StudioProject }>('/projects', {
      method: 'POST',
      body: JSON.stringify({ name, description }),
    }),
  getProject: (id: string) =>
    request<{ project: StudioProject; docs: StudioDoc[] }>(
      '/projects/' + encodeURIComponent(id),
    ),
  saveDoc: (id: string, name: string, content: string) =>
    request<{ doc: StudioDoc }>(`/projects/${encodeURIComponent(id)}/docs`, {
      method: 'POST',
      body: JSON.stringify({ name, content }),
    }),
  // Every doc with a current draft in one read — the project-level commit's
  // work list (ACP-727).
  listDraftDocs: (id: string) =>
    request<{ drafts: StudioDraftDoc[] }>(`/projects/${encodeURIComponent(id)}/drafts`),
  // Autosave one draft (ACP-721: overwrites drafts/<doc>.md and appends a
  // record unless identical to the last one). Best-effort from the editor's
  // debounce — a failed autosave is not user-visible, the next tick retries.
  saveDraft: (id: string, name: string, content: string) =>
    request<{ ok: boolean }>(`/projects/${encodeURIComponent(id)}/docs/draft`, {
      method: 'POST',
      body: JSON.stringify({ name, content }),
    }),
  listDraftVersions: (id: string, name: string) =>
    request<{ versions: StudioDraftVersion[] }>(
      `/projects/${encodeURIComponent(id)}/docs/${encodeURIComponent(name)}/draft-versions`,
    ),
  listVersions: (id: string, name: string) =>
    request<{ versions: StudioVersion[] }>(
      `/projects/${encodeURIComponent(id)}/docs/${encodeURIComponent(name)}/versions`,
    ),
}
