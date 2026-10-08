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
 * version carries the whole document as additions.
 *
 * ACP-755 adds the 00-doc parity vocabulary, same "type written first"
 * doctrine as StudioGraph — no endpoint emits these yet, so they are
 * optional on the wire and the demo snapshots are the first carrier:
 * `version` is the vN label the odd/even rule speaks, `parity` says which
 * side of the rule the row sits on, and `source` is the provenance that
 * parity asserts (manual = 人工提交, regen = 图谱反向生成). The generator's
 * precheck locks the three against each other, so a UI badge can only ever
 * display a provenance the data holds. */
export interface StudioVersion {
  name: string
  time: number
  diff: string
  version?: string
  parity?: 'odd' | 'even'
  source?: 'manual' | 'regen'
}

/** The frozen requirement baseline (ACP-755): a graph version marked
 * immutable as this round's sole basis for task breakdown and development.
 * No endpoint yet — demo-first type, shared shape with the future freeze
 * API. Re-freezing the same version is a 409 at the backend, so one record
 * per version exists, period; the UI's greyed-out button is the visible half
 * of that hard rule, not the enforcement. */
export interface StudioFreeze {
  /** the frozen version label (an even, regen-sourced row) */
  version: string
  /** the doc whose version trail holds it */
  docName: string
  /** the distillation/graph generation this baseline pins */
  generatedFrom: string
  /** unix seconds of the freeze */
  time: number
  /** one-line record shown beside the frozen badge */
  notes: string
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

/** One semantic requirement of the source graph (kg-sem-poc/v0
 * `semanticRequirements`) — T7/ACP-851 closes ACP-847's measured loss: the
 * SR layer had NO kind on the wire and the projection dropped all 20 of them
 * with their CONTRACT_REALIZES edges. The SR is a SEMANTIC layer over the
 * canvas nodes (page/component/contract/scenario), not one more box-and-arrow
 * kind, so it rides as its own optional array rather than faking a fourth
 * node kind — every existing consumer (GraphView's layout table, the demo
 * frames, GraphTool's kind groups) stays byte-identical. `realizes` names
 * the canvas node ids this SR is realised by (the CONTRACT_REALIZES /
 * structure edges that pointed at this SR id); an empty list is data — an SR
 * no contract realises yet, not a mapping gap. */
export interface StudioSemanticRequirement {
  id: string
  /** the requirement in one sentence, the graph's own text */
  text: string
  /** verbatim quote from the doc this SR was distilled from ("ref § quote") */
  anchor?: { ref: string; quote: string }
  /** an open question this SR waits on (OPEN-3 …), absent when adopted */
  openRef?: string
  /** the source's own adoption flag (adopted = accepted into this round) */
  adopted?: boolean
  /** which canvas node ids (modules/docs/requirements) realise this SR */
  realizes: string[]
}

export interface StudioGraph {
  nodes: StudioGraphNode[]
  edges: StudioGraphEdge[]
  /** the semantic-requirement layer (T7): absent on a graph that has none,
   * present and complete (zero-loss from the source) when the backend emits
   * it — optional so pre-T7 carriers (demo snapshots, older responses) keep
   * parsing unchanged */
  srs?: StudioSemanticRequirement[]
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
  /** unix seconds once the graph has ABSORBED the accepted candidates — the
   * real endpoint (T7) leaves it absent on purpose: it records proposals,
   * absorbing them into the graph is the LLM step this endpoint never fakes */
  appliedAt?: number
  /** T7 wire additions (POST …/distill emits both): the doc the candidates
   * were distilled from and the graph they were compared against */
  distilledFromDoc?: string
  graphId?: string
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
  // 'failed' is T7's addition (ACP-851): a real gate run can FAIL, and a
  // run that stops at a failed gate must SAY so — the snapshot vocabulary
  // had no word for a refusal, which left an honest adapter no way to
  // record one. Absent from every shipped frame (they are all-green
  // snapshots), present the first time a gate exits non-zero.
  status: 'pending' | 'running' | 'done' | 'failed'
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
  /** T7 wire addition (POST …/dev-runs): the release this run was opened
   * for, when the caller named one; runnableVersion then names THAT */
  releaseVersion?: string
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
export type StudioHistoryKind = 'edit' | 'commit' | 'release' | 'distill' | 'freeze' | 'dev' | 'run'

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

// ---------------------------------------------------------------------------
// requirement pages (ACP-2015 step 2, RFC rfc-ai-studio-req-flow §9.4): the
// read-only view onto the workspace's docs/需求图谱/*.json. Read-only on
// purpose — 直改 and 开始开发 are steps 3 and 4.
// ---------------------------------------------------------------------------

/** The v34 verdict, verbatim from ``jc fe reqdoc check``. Three values, and
 * the backend coerces anything else onto '不齐' (fail closed: an unknown
 * verdict must never read as 'ready'). */
export type StudioVerdict = '不齐' | '可以开工但有已知缺口' | '全齐'

/** One page row in the right-hand 需求 tab. */
export interface StudioRequirementSummary {
  page: string
  graphHash: string
  verdict: StudioVerdict
  missingCount: number
  updatedAt: string
}

/** One page's whole read: the raw graph, the rendered doc (null when the
 * graph is unqualified — v34 refuses to render those), and the verdict detail
 * the bar expands. `devState`/`stale` are step-2 constants, step 3 moves them. */
export interface StudioRequirementPage {
  page: string
  graph: unknown
  markdown: string | null
  graphHash: string
  verdict: StudioVerdict
  errors: string[]
  missing: string[]
  tiers: { api: string[]; ui: string[]; parts: string[] }
  devState: 'editing' | 'requested'
  stale: boolean
}

// ---------------------------------------------------------------------------
// dev server (ACP-2060, RFC rfc-ai-studio-req-flow §9.6): one pnpm dev pair per
// project, published on its rule domain. The state is recomputed by the backend
// on every read (pid alive AND the URL answers 200), so polling it is honest.
// ---------------------------------------------------------------------------

/** The four states the top bar renders: grey / amber / green / red. */
export type StudioDevServerState = 'stopped' | 'starting' | 'running' | 'failed'

/** One read of a project's dev server. `failedStep`/`message` are populated
 * ONLY while `state === 'failed'` — the backend nulls them otherwise, so a
 * stale failure never lingers on screen after a successful start. */
export interface StudioDevServer {
  state: StudioDevServerState
  /** the rule domain (https://<代号>-<工号>-dev.…), '' before the first start */
  url: string
  ports: { web: number | null; api: number | null }
  /** which of the six steps broke, e.g. "pnpm install" */
  failedStep: string | null
  /** the tail of that step's output — shown verbatim, never rephrased */
  message: string | null
  /** ISO timestamp of the last successful start, null before it */
  startedAt: string | null
}

// ---------------------------------------------------------------------------
// publish (08-publish-app): version rows, release records, form preview and
// the publish trigger. A separate client object (not a StudioApi member) on
// purpose: the demo runtime implements StudioApi exactly, and the demo never
// fakes a publish entry — these calls are real-store only.
// ---------------------------------------------------------------------------

/** One publishable version row: a version label (a bare git tag name — the
 * same id the preview endpoint takes) with the commit hash it froze. */
export interface StudioPublishVersion {
  version: string
  commitHash: string
  time: number
}

/** One release record (B3/B4): the outward fact a SUCCESSFUL publish created.
 * The publish view derives the per-version published states and the "latest
 * published hash" (the newest success record's hash) from this one read. */
export interface StudioPublishRecord {
  deploymentId: string
  version: string
  commitHash: string
  form: string
  requirementVersion: string
  jiraTaskIds: string[]
  status: string
  url: string
  ts: number
}

/** B1's per-version form verdict. A `rejected` form is a 200 verdict body,
 * not an error — the row renders `reason` inline. */
export interface StudioPublishPreview {
  form: 'full' | 'demo' | 'rejected'
  reason: string
}

/** One release-job (08 §〇-2): one execution of the publish button — an id
 * (which IS the deploymentId the log endpoint takes), a version, a form, one
 * of three statuses, and the publish time. `commitHash` is absent on jobs the
 * store wrote before the trigger began recording it. */
export interface StudioPublishJob {
  id: string
  version: string
  form: string
  status: string
  ts: number
  commitHash?: string
}

/** One file a version changed (ACP-798): its name, HOW this version changed
 * it, and where the file stands in the distillation that turns a changed
 * design document into requirement-graph nodes. The three distill states are
 * the owner's 口径 read as data: 已/正在/尚未拆解成图谱 — the release tab
 * renders one ROW per file (a list, never a graph diagram). */
export interface StudioReleaseFile {
  name: string
  change: 'added' | 'modified' | 'deleted'
  distill: 'done' | 'running' | 'pending'
}

/** The files ONE version changed, as the release tab reads them: the version
 * they belong to plus its list. */
export interface StudioReleaseFiles {
  version: string
  files: StudioReleaseFile[]
}

export type StudioPublishApi = {
  /** The project's publishable versions (tag + hash), newest first. */
  listVersions: (id: string) => Promise<{ versions: StudioPublishVersion[] }>
  /** The project's release records, newest first (B3/B4). */
  listRecords: (id: string) => Promise<{ records: StudioPublishRecord[] }>
  /** B1: the form one version publishes as, from its git tag annotation. */
  preview: (id: string, version: string) => Promise<StudioPublishPreview>
  /** B2: fire the publish. Same-hash-while-running answers 409; an
   * idempotent re-publish answers the existing deploymentId. A job that
   * already ran to failure answers ``status: "failed"`` with the reason —
   * the only carrier of that reason, since a failed job writes no record. */
  trigger: (id: string, version: string, commitHash: string) =>
    Promise<{ deploymentId: string; idempotent?: boolean; status?: string; reason?: string }>
  /** The project's release-jobs, newest first (§〇-2 history list; T8). */
  listJobs: (id: string) => Promise<{ jobs: StudioPublishJob[] }>
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
  // ACP-847 (BGDD PoC): the graph endpoints. getGraph reads the requirement
  // graph mapped onto StudioGraph — the real data the graph view renders once
  // the workspace stops passing fixtures (GraphView's own header comment).
  getGraph: () => Promise<{ graphId: string; graph: StudioGraph }>
  freeze: (
    id: string,
    version: string,
    docName: string,
    notes?: string,
  ) => Promise<{ freeze: StudioFreeze }>
  regen: (id: string, docName: string) => Promise<{ doc: string; content: string; generatedFrom: string }>
  distill: (id: string, docName: string, releaseVersion?: string) =>
    Promise<{ distillation: StudioDistillation }>
  listFreezes: (id: string) => Promise<{ freezes: StudioFreeze[] }>
  listDistills: (id: string) => Promise<{ distillations: StudioDistillation[] }>
  // ACP-2015 step 2: the workspace's requirement pages and one page's read.
  listRequirements: (id: string) => Promise<{ pages: StudioRequirementSummary[] }>
  getRequirement: (id: string, page: string) => Promise<StudioRequirementPage>
  // T7 step 4 (ACP-851): the four development phases run the BGDD gate
  // (bgdd repo tools/gate.ts, ACP-848) through the backend. startDevRun is
  // the whole run — it resolves once every phase that got to run has an
  // outcome; a 503 means this instance is not wired to a gate checkout,
  // which the 开发 tab shows as the refusal it is, never as a fake run.
  startDevRun: (id: string, designVersion: string, releaseVersion?: string) =>
    Promise<{ run: StudioDevRun }>
  listDevRuns: (id: string) => Promise<{ runs: StudioDevRun[] }>
  // ACP-2060: the project's dev server. getDevServer is cheap (one state read
  // plus one loopback probe), which is what makes the 2s poll while starting
  // affordable. start answers 202 `starting` at once — a pnpm install is
  // minutes long and never blocks a request; a 400 `code_required` /
  // `staff_id_required` means the domain rule rejected the project before a
  // single process spawned.
  getDevServer: (id: string) => Promise<StudioDevServer>
  startDevServer: (id: string) => Promise<StudioDevServer>
  stopDevServer: (id: string) => Promise<StudioDevServer>
  getDevServerLog: (id: string, lines?: number) => Promise<{ lines: string[] }>
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

export const publishApi: StudioPublishApi = {
  listVersions: (id: string) =>
    request<{ versions: StudioPublishVersion[] }>(
      `/publish/versions?project=${encodeURIComponent(id)}`,
    ),
  listRecords: (id: string) =>
    request<{ records: StudioPublishRecord[] }>(
      `/publish/records?project=${encodeURIComponent(id)}`,
    ),
  preview: (id: string, version: string) =>
    request<StudioPublishPreview>(
      `/publish/preview?project=${encodeURIComponent(id)}&version=${encodeURIComponent(version)}`,
    ),
  trigger: (id: string, version: string, commitHash: string) =>
    request<{ deploymentId: string; idempotent?: boolean }>('/publish', {
      method: 'POST',
      body: JSON.stringify({ project: id, version, commitHash }),
    }),
  listJobs: (id: string) =>
    request<{ jobs: StudioPublishJob[] }>(`/publish/jobs?project=${encodeURIComponent(id)}`),
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
  getGraph: () => request<{ graphId: string; graph: StudioGraph }>('/graph'),
  // 409 already_frozen on a duplicate label is the backend's rule (ACP-847);
  // the caller surfaces it, the client does not swallow it.
  freeze: (id: string, version: string, docName: string, notes?: string) =>
    request<{ freeze: StudioFreeze }>(`/projects/${encodeURIComponent(id)}/freeze`, {
      method: 'POST',
      body: JSON.stringify({ version, docName, notes }),
    }),
  regen: (id: string, docName: string) =>
    request<{ doc: string; content: string; generatedFrom: string }>(
      `/projects/${encodeURIComponent(id)}/regen`,
      { method: 'POST', body: JSON.stringify({ docName }) },
    ),
  // T7 (ACP-851): the doc→graph direction. Proposals only — the endpoint
  // never mutates the graph, so `appliedAt` stays absent on its records.
  distill: (id: string, docName: string, releaseVersion?: string) =>
    request<{ distillation: StudioDistillation }>(
      `/projects/${encodeURIComponent(id)}/distill`,
      { method: 'POST', body: JSON.stringify({ docName, releaseVersion }) },
    ),
  listFreezes: (id: string) =>
    request<{ freezes: StudioFreeze[] }>(`/projects/${encodeURIComponent(id)}/freezes`),
  listDistills: (id: string) =>
    request<{ distillations: StudioDistillation[] }>(`/projects/${encodeURIComponent(id)}/distills`),
  // Read-only requirement reads (step 2). A 503 `reqdoc_cmd_unavailable` is a
  // real answer the verdict bar renders, not something to retry away.
  listRequirements: (id: string) =>
    request<{ pages: StudioRequirementSummary[] }>(`/projects/${encodeURIComponent(id)}/requirements`),
  getRequirement: (id: string, page: string) =>
    request<StudioRequirementPage>(
      `/projects/${encodeURIComponent(id)}/requirements/${encodeURIComponent(page)}`,
    ),
  startDevRun: (id: string, designVersion: string, releaseVersion?: string) =>
    request<{ run: StudioDevRun }>(
      `/projects/${encodeURIComponent(id)}/dev-runs`,
      { method: 'POST', body: JSON.stringify({ designVersion, releaseVersion }) },
    ),
  listDevRuns: (id: string) =>
    request<{ runs: StudioDevRun[] }>(`/projects/${encodeURIComponent(id)}/dev-runs`),
  // ACP-2060: the domain rule lives on the backend, so a project with no 代号
  // is a 400 the caller shows verbatim — retrying cannot fix a missing code.
  getDevServer: (id: string) =>
    request<StudioDevServer>(`/projects/${encodeURIComponent(id)}/dev-server`),
  startDevServer: (id: string) =>
    request<StudioDevServer>(`/projects/${encodeURIComponent(id)}/dev-server/start`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),
  stopDevServer: (id: string) =>
    request<StudioDevServer>(`/projects/${encodeURIComponent(id)}/dev-server/stop`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),
  getDevServerLog: (id: string, lines = 50) =>
    request<{ lines: string[] }>(
      `/projects/${encodeURIComponent(id)}/dev-server/log?lines=${encodeURIComponent(String(lines))}`,
    ),
}
