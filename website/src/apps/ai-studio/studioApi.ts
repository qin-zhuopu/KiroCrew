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

/** One step of the derive job (ACP-2085). `name` is the backend's Chinese
 * step label — it is data, so it is rendered verbatim and never re-labelled
 * here (the dialog's row order is the backend's array order). */
export interface StudioWorkspaceStep {
  name: string
  state: StudioWorkspaceStepState
  /** set only while this step is the one that failed */
  message: string | null
}

export type StudioWorkspaceStepState = 'pending' | 'running' | 'done' | 'failed'

export interface StudioProject {
  id: string
  name: string
  description: string
  createdAt: number
  // --- workspace fields (ACP-2085) -------------------------------------------
  // OPTIONAL on the wire on purpose: a project created before this change — and
  // a plain non-workspace project created after it — carries none of them, and
  // the whole UI branches on `code` being there rather than on a status a
  // missing field would have to fake. `status` is `creating` until every derive
  // step is done, `failed` alongside `failedStep`/`message` while one is broken.
  code?: string | null
  template?: string | null
  status?: 'creating' | 'ready' | 'failed' | null
  failedStep?: string | null
  /** verbatim tail of the failing step's output — shown as written */
  message?: string | null
  workspaceDir?: string | null
  repoUrl?: string | null
  steps?: StudioWorkspaceStep[]
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
 * the bar expands.
 *
 * Two optimistic-concurrency hashes, deliberately different (ACP-2104):
 * `graphHash` gates 开始开发 (readiness is a property of the graph), `docHash`
 * gates 直改 (the contention there is over the view the owner is typing in).
 * `devState`/`changedAfterStart` come from the start ledger re-read against the
 * CURRENT graph hash, so the「已开工」button is the backend's answer, and a graph
 * that moved after a start shows up as `changedAfterStart` rather than as a
 * silently vanished record (R3). */
export interface StudioRequirementPage {
  page: string
  graph: unknown
  markdown: string | null
  graphHash: string
  docHash: string
  verdict: StudioVerdict
  errors: string[]
  missing: string[]
  tiers: { api: string[]; ui: string[]; parts: string[] }
  /** true while a direct edit sits in the ledger and the graph has not moved
   * since: the on-screen verdict describes a graph that no longer matches what
   * the owner asked for. */
  pendingEdit: boolean
  devState: 'editing' | 'started'
  changedAfterStart: boolean
  stale: boolean
}

/** 直改's answer (ACP-2104). `changed: false` is not an error and carries no
 * diff: an edit that changes nothing must not notify anyone. When it did change,
 * the diff is recorded and relayed to the 需求会话 — the graph itself is written
 * only by that session, so `pending` says the change is a REQUEST still waiting
 * to land. */
export interface StudioDirectEditResult {
  changed: boolean
  diff?: string
  pending?: boolean
}

/** 开始开发's answer: the request is recorded, nothing is generated here. */
export interface StudioStartRequestResult {
  ok: boolean
  page: string
  graphHash: string
  verdict: StudioVerdict
}

// ---------------------------------------------------------------------------
// requirement session (ACP-2085 S2, RFC rfc-ai-studio-req-flow §9.3): the left
// column's chat is the workspace's 需求会话, so the SLOT IS THE BACKEND'S —
// only it can scope the session at the workspace directory and send the opening
// prompt. `created` says whether THIS call sent that prompt, which is why the
// caller must not assume a slot it just opened is a fresh conversation.
// ---------------------------------------------------------------------------

/** One idempotent open of a workspace's requirement session. */
export interface StudioReqSession {
  slotKey: string
  created: boolean
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
// production server (ACP-2085-S5, 08-publish-app): the same pair as above on its
// OWN domain pair (a stable one plus a per-version one), reachable only after an
// acceptance pass with no commits after it. `step` is which of the seven deploy
// steps is running; `failedStep`/`message` are populated ONLY while failed.
// ---------------------------------------------------------------------------

/** Grey / amber / green / red, same four the dev-server control renders. */
export type StudioProdServerState = 'stopped' | 'deploying' | 'running' | 'failed'

export interface StudioProdServer {
  state: StudioProdServerState
  /** the stable URL: https://<代号>-<工号>.gb10.jereh-pe.cn */
  url: string
  /** the per-version URL: https://v<N>-<代号>-<工号>.… */
  versionUrl: string
  /** 「v<N>」, from the release ledger's row count */
  version: string
  ports: { web: number | null; api: number | null }
  /** which of the seven steps is running, ONLY while deploying */
  step: string | null
  failedStep: string | null
  /** the failing step's one-line reason — shown verbatim, never rephrased */
  message: string | null
  /** ISO timestamp of the last successful deploy, null before it */
  deployedAt: string | null
  /** the commit the version tag was put on */
  commit: string
}

// ---------------------------------------------------------------------------
// development board + acceptance (ACP-2085-S4): the serial per-page task run
// and the workspace's own checks. Real-store only, on the same footing as the
// publish client below: the demo runtime implements StudioApi exactly and never
// fakes these, so they are an OPTIONAL member of StudioApi (an interface member
// the demo object cannot omit would break that file, which is not this ticket's
// territory) and a standalone object holding the implementations.
//
// The board's whole picture comes from ONE read: the backend's state file is the
// truth (a gateway restart must still render the last run), so nothing here
// derives state client-side.
// ---------------------------------------------------------------------------

/** The four node states the board renders, and the only four (07 §〇-1). */
export type StudioDevNodeState = 'queued' | 'running' | 'done' | 'failed'

/** The run's own state; `idle` is the no-file-yet answer, not a phase.
 * `planned` (ACP-2085-S6) is a split that has not been started: the tasks and
 * their Jira issues exist and no session has been dispatched, which is exactly
 * why a gateway restart cannot orphan it — nothing was running. */
export type StudioDevRunState = 'idle' | 'planned' | 'running' | 'done' | 'failed'

/** One task node: one page's 后端接口 or 前端页面, scheduled in plan order.
 * `jiraKey` is the field name 07 §三 B1 fixed and holds the TASK id
 * (`<page>:<kind>`) in this version — nothing here talks to Jira. */
export interface StudioDevNode {
  jiraKey: string
  title: string
  dependsOn: string[]
  state: StudioDevNodeState
  /** the assistant session this task ran on, '' before it started */
  slotKey: string
  startCommit: string
  endCommit: string
  /** the failure's own line, verbatim from the assistant or the scheduler */
  message: string
  // ACP-2085-S6: this task's Jira sub-issue. All three are optional because a
  // deployment with no `AI_STUDIO_JIRA_CMD` configured has none of them, and a
  // board must be able to tell 「Jira is not configured」 (no fields) apart from
  // 「Jira is broken」 (`jiraError` with the command's own line).
  /** the Jira key, '' when no issue was created */
  jira?: string
  /** its browse URL, '' with the key */
  jiraUrl?: string
  /** why there is no issue, verbatim from the command */
  jiraError?: string
}

/** `GET …/dev/dag` — the whole board in one read. */
export interface StudioDevDag {
  runId?: string
  phase?: string
  runState: StudioDevRunState
  startedAt?: string
  graphHashes?: Record<string, string>
  nodes: StudioDevNode[]
  /** the project's parent Jira issue and its URL, paired by the backend */
  jiraParent?: string
  jiraParentUrl?: string
}

/** One acceptance command's outcome. `id` is the command text, `tail` the last
 * 40 lines of its output — the only place the real error exists. */
export interface StudioAcceptResult {
  id: string
  ok: boolean
  tail: string
}

/** One acceptance record (`POST …/accept/run`). `voided` is always present and
 * always false in this version: 07 §三 B4 requires the field to EXIST so a
 * downstream reader never guesses at a missing default. */
export interface StudioAcceptRecord {
  id: string
  phase: string
  result: 'passed' | 'failed'
  voided: boolean
  results: StudioAcceptResult[]
  requirementVersion: string
  commitHash: string
  at: string
}

export type StudioDevBoardApi = {
  /** 202 as soon as the run is scheduled — a page's front and back end is
   * minutes to an hour of work and no request may wait for it. `pages` omitted
   * = every page whose requirement verdict allows it. */
  startDev: (id: string, pages?: string[]) => Promise<{ runId: string; phase: string }>
  /** 〔拆分任务〕 (ACP-2085-S6): build the task list AND its Jira sub-issues,
   * runState `planned`, nothing dispatched. Same page rules and the same
   * refusals as `startDev` (422 `not_ready`, 409 `run_active`); 201 with the
   * whole board, which is what lets the caller repaint without a second read. */
  planDev: (id: string, pages?: string[]) => Promise<StudioDevDag>
  getDevDag: (id: string) => Promise<StudioDevDag>
  getDevLog: (id: string, lines?: number) => Promise<{ lines: string[] }>
  /** 409 `dev_not_done` until every node is done; 201 with the new record. */
  runAccept: (id: string) => Promise<{ record: StudioAcceptRecord }>
  listAcceptRecords: (id: string) => Promise<{ records: StudioAcceptRecord[] }>
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
  /** `staffId` is the gateway's `KIROCREW_STAFF_ID` (the 工号 the new-workspace
   * dialog shows read-only and the dev domain is built from). Optional on the
   * type because the demo snapshot has no login to report — the dialog shows an
   * empty field rather than inventing one. */
  listProjects: () => Promise<{ projects: StudioProject[]; staffId?: string }>
  /** A `code` in `opts` is what makes this a WORKSPACE create (ACP-2085): the
   * backend then answers `status: "creating"` and derives the repo in the
   * background, so the caller opens the progress dialog instead of navigating.
   * Without a `code` nothing changes — including the 2-argument call shape,
   * which is what a plain project create still sends. */
  createProject: (
    name: string,
    description: string,
    opts?: { code?: string; template?: string },
  ) => Promise<{ project: StudioProject }>
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
  // ACP-2085 S2: open (idempotently) the workspace's 需求会话 and get the slot
  // key to mount. The backend owns the key because only it can scope the slot
  // at the workspace directory; a 409 `workspace_missing` means the recorded
  // workspace directory is gone, which no retry can fix by itself.
  ensureReqSession: (id: string) => Promise<StudioReqSession>
  // 直改 / 开始开发 (ACP-2104) are NOT members of this interface, and that is a
  // deliberate seam, not an omission: `createDemoApi` returns `StudioApi`, so a
  // new required member would force the snapshot demo to fake a write it cannot
  // perform (faking a ledger it does not own is exactly the dishonesty the demo
  // doctrine forbids). They live on `requirementWriteApi` below, which the real
  // page calls and the demo never renders.
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

/** The production server's four calls (ACP-2085-S5). A separate client object —
 * `publishApi` / `requirementWriteApi` precedent, same reason: the demo runtime
 * implements `StudioApi` exactly, and a snapshot deploys nothing, tags nothing
 * and owns no domain, so faking 「正式运行中」 would be precisely the dishonesty the
 * demo doctrine forbids. `deployProdServer` answers 409 `not_accepted` when the
 * workspace has no passing acceptance record at HEAD; that is a refusal the
 * panel shows as one grey line, never as an error dialog. */
export type StudioProdServerApi = {
  getProdServer: (id: string) => Promise<StudioProdServer>
  /** 202 with the state AFTER the seven steps ran (running / failed) or, while a
   * background deploy is still in flight, `deploying`. */
  deployProdServer: (id: string) => Promise<StudioProdServer>
  stopProdServer: (id: string) => Promise<StudioProdServer>
  getProdServerLog: (id: string, lines?: number) => Promise<{ lines: string[] }>
}

/** The derive job's two reads (ACP-2085). A separate client object, the
 * `publishApi` precedent and for the same reason: the demo runtime implements
 * `StudioApi` exactly, and a snapshot fakes no clone, no repo and no push — so
 * these calls are real-store only and never belong on that type. */
export type StudioWorkspaceApi = {
  /** Re-run the FAILED step in the background. 202 with the fresh record; a 409
   * `not_failed` when the job is not failed, which the dialog shows rather than
   * swallows (it means someone else already retried, or the job moved on). */
  retryWorkspace: (id: string) => Promise<{ project: StudioProject }>
  /** Tail the derive command's merged output. The backend keeps the file next to
   * `project.json`, not in the workspace, so this answers after a failed clone —
   * which is exactly when it is the only evidence left. */
  getWorkspaceLog: (id: string, lines?: number) => Promise<{ lines: string[] }>
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
  listProjects: () => request<{ projects: StudioProject[]; staffId?: string }>('/projects'),
  createProject: (name, description, opts) =>
    request<{ project: StudioProject }>('/projects', {
      method: 'POST',
      // `{ ...undefined }` spreads to nothing, so a plain create posts exactly
      // the two keys it always did
      body: JSON.stringify({ name, description, ...opts }),
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
  // ACP-2085 S2: idempotent — the backend sends the opening prompt only on the
  // first call, so remounting the pane or reloading the page is free.
  ensureReqSession: (id: string) =>
    request<StudioReqSession>(`/projects/${encodeURIComponent(id)}/req-session`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),
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

// ---------------------------------------------------------------------------
// requirement writes (ACP-2104): 直改 and 开始开发.
//
// A separate object rather than two more `StudioApi` members, for the reason in
// the interface's comment: `createDemoApi` returns `StudioApi`, and a demo
// snapshot has no graph, no ledger and no session to notify — so it could only
// implement these two by inventing a success. The write surface is where a fake
// would do real damage (it would teach the page that a save works), so it stays
// off the demo's type and the demo never renders the buttons that call it.
// ---------------------------------------------------------------------------

export const requirementWriteApi = {
  /** 直改 one requirement page: the backend re-derives the diff from the file, so
   * `baseDocHash` is the hash of the view the text was typed against, and a
   * mismatch is 409 `doc_changed` — the assistant landed something mid-typing. */
  directEditRequirement: (id: string, page: string, baseDocHash: string, markdown: string) =>
    request<StudioDirectEditResult>(
      `/projects/${encodeURIComponent(id)}/requirements/${encodeURIComponent(page)}/direct-edit`,
      { method: 'POST', body: JSON.stringify({ baseDocHash, markdown }) },
    ),
  /** 开始开发: re-check + record. 409 `graph_changed` / 422 `not_ready` both mean
   * the on-screen verdict was stale, so the caller re-reads rather than arguing. */
  startRequirement: (id: string, page: string, graphHash: string) =>
    request<StudioStartRequestResult>(
      `/projects/${encodeURIComponent(id)}/requirements/${encodeURIComponent(page)}/start`,
      { method: 'POST', body: JSON.stringify({ graphHash }) },
    ),
}

export const prodServerApi: StudioProdServerApi = {
  getProdServer: (id: string) =>
    request<StudioProdServer>(`/projects/${encodeURIComponent(id)}/prod-server`),
  deployProdServer: (id: string) =>
    request<StudioProdServer>(`/projects/${encodeURIComponent(id)}/prod-server/deploy`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),
  stopProdServer: (id: string) =>
    request<StudioProdServer>(`/projects/${encodeURIComponent(id)}/prod-server/stop`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),
  // 80 is the ticket's default and the backend's own: the file holds the build
  // output plus both children's stdout, so the interesting part is the end.
  getProdServerLog: (id: string, lines = 80) =>
    request<{ lines: string[] }>(
      `/projects/${encodeURIComponent(id)}/prod-server/log?lines=${encodeURIComponent(String(lines))}`,
    ),
}

export const workspaceApi: StudioWorkspaceApi = {
  retryWorkspace: (id: string) =>
    request<{ project: StudioProject }>(`/projects/${encodeURIComponent(id)}/retry`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),
  // 80 lines matches the backend's own default: the file is a command's merged
  // output, and the interesting part is the end of it.
  getWorkspaceLog: (id: string, lines = 80) =>
    request<{ lines: string[] }>(
      `/projects/${encodeURIComponent(id)}/workspace-log?lines=${encodeURIComponent(String(lines))}`,
    ),
}

/** ACP-2085-S4: the development board and its acceptance run. Its own client
 * object for the publishApi reason — the demo runtime implements StudioApi
 * exactly and never fakes a dev run, so these stay outside that interface and
 * a caller passes its own stand-in in as a prop. */
export const devBoardApi: StudioDevBoardApi = {
  startDev: (id: string, pages?: string[]) =>
    request<{ runId: string; phase: string }>(
      `/projects/${encodeURIComponent(id)}/dev/start`,
      { method: 'POST', body: JSON.stringify(pages?.length ? { pages } : {}) },
    ),
  planDev: (id: string, pages?: string[]) =>
    request<StudioDevDag>(
      `/projects/${encodeURIComponent(id)}/dev/plan`,
      { method: 'POST', body: JSON.stringify(pages?.length ? { pages } : {}) },
    ),
  getDevDag: (id: string) =>
    request<StudioDevDag>(`/projects/${encodeURIComponent(id)}/dev/dag`),
  getDevLog: (id: string, lines = 100) =>
    request<{ lines: string[] }>(
      `/projects/${encodeURIComponent(id)}/dev/log?lines=${encodeURIComponent(String(lines))}`,
    ),
  runAccept: (id: string) =>
    request<{ record: StudioAcceptRecord }>(
      `/projects/${encodeURIComponent(id)}/accept/run`,
      { method: 'POST', body: JSON.stringify({}) },
    ),
  listAcceptRecords: (id: string) =>
    request<{ records: StudioAcceptRecord[] }>(`/projects/${encodeURIComponent(id)}/accept/records`),
}
