// The `?demo=` branch of the AI Studio route: a stripped workbench that runs
// the real DocEditor/WorkArea/ProjectCommitBar against the snapshot fake,
// plus the guidance overlay. AiStudioPage mounts this ONLY when the URL
// carries `?demo=`; the ordinary StudioWorkspace — chat column, resizers,
// localStorage pane state — never sees a demo line, which is the §4 rule
// held literally: the demo lives beside the business components, not inside
// them.
//
// One step = one wholesale load (§6): the runtime swaps the fixture (state
// layer), the ai-studio query cache is dropped so every read re-serves from
// the new fake, the doc tab is keyed on the step so the editor re-mounts
// with that step's committed baseline, and the overlay replays the step's
// open acts onto it (view layer). Back and next are the same operation on a
// different index — never a reverse mutation.
//
// The two live business acts the scripts are allowed run through the SAME
// controls the ordinary workbench renders, only backed by the fake: main-8's
// commit click (ProjectCommitBar — the committed content re-points the open
// tab), and main-10's release click (ReleaseControl — landing swaps in the
// release cut + generated-code panel from the step's after-fix snapshot,
// which is the same snapshot the script test's after-state was derived
// from, so the panel shows data, not a promise).
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import ErrorNotice from '../../../components/ErrorNotice'
import { i18nT } from '../../../i18n/t'
import CodeGenView from '../CodeGenView'
import DevRunPanel, { RunPreviewScreen } from '../DevRunView'
import ProjectHistoryView from '../ProjectHistoryView'
import DistillPanel from '../DistillPanel'
import GraphView from '../GraphView'
import { RegenDiffPair, RegenDocView } from '../RegenDiffView'
import ProjectCommitBar from '../ProjectCommitBar'
import ReleaseControl from '../ReleaseControl'
import WorkArea, { type WorkTab } from '../WorkArea'
import type { DemoFixture } from './types'
import type { StudioDoc } from '../studioApi'
import DemoOverlay from './overlay'
import { useDemoRuntime } from './runtime'

// the release walk: each phase label holds for this long before the landing
// swaps the panel in — a presenter-visible "AI 按图谱生成" beat, timed here
// in the demo layer so the control itself stays a plain button (and a
// harness can shorten it through the control's own prop if it ever needs to)
const RELEASE_PHASE_MS = 600

export default function DemoWorkspace({ params }: {
  params: { scenario: string; autoMs: number; settleMs: number }
}) {
  const { ctl, unknown } = useDemoRuntime(params)
  const queryClient = useQueryClient()
  // A live commit inside a step re-mounts the editor onto the committed
  // baseline (the same commitRev mechanism StudioWorkspace uses); leaving
  // the step discards it — the next step loads its own snapshot.
  const [liveCommit, setLiveCommit] = useState<{ docs: StudioDoc[]; rev: number } | null>(null)
  const onDocCommitted = useCallback((fresh: StudioDoc[]) => {
    setLiveCommit((c) => ({ docs: fresh, rev: (c?.rev ?? 0) + 1 }))
  }, [])
  // A live act (main-10's release, main-11's distillation, main-18's dev,
  // main-21's experience) lands by swapping the bottom panel to the step's
  // after-fix snapshot — the same snapshot the script test derived the
  // after-state from, so the panel shows data, not a promise. "Which step's
  // act has landed" is held as DATA stamped with the step index, and
  // `liveLanded` is DERIVED from it — deliberately not a boolean an effect
  // clears: the overlay replays the act click from a CHILD effect, which runs
  // before this component's own step-change reset effect, so a reset-style
  // flag gets wiped inside the very commit the click landed in (measured:
  // the landing renders, then reverts 4ms later, and the frame silently
  // shows the pre-click snapshot). Deriving costs the reset effect nothing —
  // stepping to N+1 makes a stamp of N read false, which IS the "belongs to
  // the step" semantics, enforced by data rather than by effect timing.
  const [landedStep, setLandedStepRaw] = useState<number | null>(null)
  // A landing write must belong to the step that is CURRENT, not merely
  // arrive: the release act awaits its phase walk before stamping, so on a
  // fast walk (or a replayed chain where several acts queue) the continuation
  // can fire long after the presenter moved on — measured: main-10's release
  // timer landed `set(9)` while main-23's own 继续设计 landing (stamp 22) had
  // just rendered, clobbering it back to the pre-click frame. The stamp
  // compare is the same data-derived discipline as `liveLanded`: a write for
  // a step already left is not a fact about the current frame, so it is
  // dropped. The step index is read through a ref (the async continuations
  // close over stale render values).
  const stepIndexRef = useRef(0)
  stepIndexRef.current = ctl?.stepIndex ?? 0
  const setLandedStep = (v: number) => {
    if (stepIndexRef.current !== v) return
    setLandedStepRaw(v)
  }

  // state-layer swap: a new step means a new fake, so every cached
  // ai-studio read (project docs, both histories) is stale by construction.
  // Removing the prefix — rather than invalidating — is the honest move:
  // the old fake is gone, nothing about it can still be served.
  const stepIndex = ctl?.stepIndex
  useEffect(() => {
    queryClient.removeQueries({ queryKey: ['ai-studio'] })
    setLiveCommit(null)
    // NB: no liveLanded reset — `liveLanded` is DERIVED from landedStep,
    // which the act click stamps with its own step index. Stepping to a new
    // index already reads it false; and because this effect no longer writes
    // it, the child-overlay click that lands in the same commit as this
    // effect can never be wiped by it (the old reset-effect flag WAS that
    // race: child replay effect → parent reset effect, same flush, the
    // landing reverted 4ms later and the step silently showed its pre-click
    // snapshot — reproduced at main-21, where the demo's own next/prev could
    // never open the experience page).
  }, [stepIndex, queryClient])

  // the fake notifies on every live mutation (a presenter clicking Commit
  // outside the script, an autosave landing); bounce the reads so the page
  // surfaces them without a remount — the DocEditor's own invalidation
  // covers its two lists, this covers the rest (the top bar's drafts read).
  const api = ctl?.api
  useEffect(() => {
    if (!api) return
    return api.subscribe(() => {
      queryClient.invalidateQueries({ queryKey: ['ai-studio'] })
    })
  }, [api, queryClient])

  // the focused doc tab, re-keyed on the step: the editor re-mounts into the
  // new snapshot's committed baseline every step (the buffer arrives later,
  // typed by the overlay through the real editor path — §5's business-event
  // replay, not a prop pretending to be dirty)
  const focusDoc = ctl?.fixture.focusDoc
  const tabs: WorkTab[] = useMemo(() => {
    if (!ctl || !focusDoc) return []
    const committed = liveCommit?.docs.find((d) => d.name === focusDoc)?.content
      ?? ctl.fixture.docs.find((d) => d.name === focusDoc)?.content
      ?? ''
    return [{
      id: `demo-doc-${focusDoc}-${stepIndex}${liveCommit ? `:c${liveCommit.rev}` : ''}`,
      kind: 'doc',
      title: focusDoc,
      docName: focusDoc,
      initialContent: committed,
    }]
  }, [ctl, focusDoc, stepIndex, liveCommit])

  if (unknown) {
    // a typo'd ?demo= must not open a blank workbench or fall through to the
    // real store — name the unknown scenario and stop
    return (
      <div className="h-full p-6 flex flex-col gap-3 max-w-[560px]" data-testid="demo-unknown-scenario">
        <ErrorNotice message={i18nT('apps.aiStudio.demo_unknown', { scenario: unknown })} askAgent={false} />
      </div>
    )
  }
  if (!ctl) return null

  // The release act (main-10): the step declares the phase labels and its
  // after-fix snapshot carries the payload, so the button is only offered
  // where the script actually has a release to land — every other step and
  // every other world renders the header without it, exactly as before.
  // Each live-act step offers its button only when its after-fix snapshot
  // actually carries the payload that button lands (release → main-10,
  // distillation → main-11), so no step ever offers a button whose click
  // lands on nothing. Both acts land on the SAME after-fix snapshot read —
  // one `liveLanded` flag, one `landed` fixture — because "the click has
  // landed" means the same thing for both: show what the snapshot holds.
  const canRelease = ctl.afterFixFixture?.release !== undefined && ctl.fixture.release === undefined
  const canDistill = ctl.afterFixFixture?.distillation !== undefined && ctl.fixture.distillation === undefined
  // the dev act (main-18) lands the opened run; the experience act (main-21)
  // lands the frame whose preview is open — both ride the same liveLanded
  // mechanism, and 打开可运行版本 is offered only where the after-fix frame
  // actually carries the preview its click opens.
  const canDev = ctl.afterFixFixture?.devRun !== undefined && ctl.fixture.devRun === undefined
  const canOpenRun = ctl.afterFixFixture?.runPreview !== undefined && ctl.fixture.runPreview === undefined
  // the 继续设计 act (main-23) lands the fresh-round frame: the editor stands
  // clean on v4 while the history keeps the whole round. Offered only where
  // the after-fix frame actually declares newRound — same rule as every other
  // transition button, so no step offers a click that lands on nothing.
  const canContinue = ctl.afterFixFixture?.newRound === true && ctl.fixture.newRound !== true
  // the after-fix snapshot takes the panel once its act lands; before that
  // (and in every world without an act) the step's own fixture speaks.
  const liveLanded = landedStep === ctl.stepIndex
  const landed: DemoFixture = liveLanded && ctl.afterFixFixture ? ctl.afterFixFixture : ctl.fixture
  const nodeLabels = Object.fromEntries((landed.graph?.nodes ?? []).map((n) => [n.id, n.label]))
  const onRelease = async () => {
    if (!ctl.afterFixFixture) return
    const phases = ctl.step.releasePhases ?? []
    await new Promise((r) => setTimeout(r, Math.max(phases.length, 1) * RELEASE_PHASE_MS))
    setLandedStep(ctl.stepIndex)
  }
  const onDistill = async () => {
    // no phase walk: the landing snapshot's own running frame carries the
    // "进行中" state, so the click resolves straight into it
    if (!ctl.afterFixFixture) return
    setLandedStep(ctl.stepIndex)
  }
  const onDev = async () => {
    // same as distill: the landing frame's own run carries the in-flight
    // phase — the process advances across snapshots, not on a timer here
    if (!ctl.afterFixFixture) return
    setLandedStep(ctl.stepIndex)
  }
  const onOpenRun = async () => {
    // the 体验 entry is an internal frame swap onto the after-fix snapshot's
    // runPreview data — no server, no container, nothing leaves the page
    if (!ctl.afterFixFixture) return
    setLandedStep(ctl.stepIndex)
  }
  const onContinue = () => {
    // 继续设计 lands the fresh-round frame the same way every other live act
    // does: the step's own snapshot says where the click goes
    if (!ctl.afterFixFixture) return
    setLandedStep(ctl.stepIndex)
  }

  return (
    // `relative` is the positioning context for the run-preview overlay —
    // the experience screen covers the workbench, never escapes to a page
    // ancestor (the stepper/ring are fixed overlays above it, so guidance
    // still works while the experience page is open)
    <div className="relative flex flex-col h-full min-h-0" data-testid="ai-studio-demo" data-demo-scenario={ctl.scenario}>
      <header className="flex items-center gap-3 px-4 h-[44px] shrink-0 border-b border-border bg-card">
        <span className="text-sm font-semibold text-text-strong">{ctl.fixture.project.name}</span>
        <span className="text-[12px] text-muted truncate">{ctl.fixture.project.description}</span>
        <span className="flex-1" />
        {/* the same project-level commit bar the ordinary workbench renders
         * (§4: the demo acts on the real business path, through the fake's
         * data), running against the snapshot fake */}
        <div className="relative flex items-center gap-2">
          <ProjectCommitBar projectId={ctl.fixture.project.id} api={ctl.api} onCommitted={onDocCommitted} />
          {/* the release / distill buttons appear only on the step whose
           * after-fix snapshot actually carries that payload (main-10 /
           * main-11) — nowhere else, so no step ever offers a button whose
           * click lands on nothing. Once the act has landed the button sits
           * disabled: the frame it produced is on screen, re-clicking would
           * replay a business event the snapshot has already absorbed. */}
          {canRelease && (
            <ReleaseControl
              onRelease={onRelease}
              phases={ctl.step.releasePhases}
              phaseMs={RELEASE_PHASE_MS}
              disabled={liveLanded}
            />
          )}
          {canDistill && (
            <ReleaseControl act="distill" onRelease={onDistill} disabled={liveLanded} />
          )}
          {canDev && (
            <ReleaseControl act="dev" onRelease={onDev} disabled={liveLanded} />
          )}
        </div>
      </header>
      <div className="flex-1 min-h-0">
        <WorkArea
          tabs={tabs}
          activeId={tabs[0]?.id ?? null}
          onSelect={() => { /* single scripted tab: nothing to select */ }}
          onClose={() => { /* the script owns the tab strip */ }}
          projectId={ctl.fixture.project.id}
          api={ctl.api}
          commitRev={liveCommit?.rev ?? 0}
        />
      </div>
      {/* the requirement graph the commits feed (ACP-729). Rendering is
       * snapshot-driven, not step-driven: this world's snapshots carry a
       * graph, so the panel is part of the frame from step 1 — the commit
       * step's payoff is the delta lighting up, not a panel appearing out
       * of nowhere. Worlds without a graph (the alt lines) never render it.
       * Sourced from `landed`, not `fixture`: identical until main-10's
       * release click lands, after which the graph shown is the released
       * snapshot's own (delta cleared — the new-requirement story was
       * main-9's shot, and the script test's after-state was derived from
       * exactly this snapshot). */}
      {landed.graph && (
        <div
          className="shrink-0 max-h-[300px] overflow-auto border-t border-border bg-bg"
          // the release read-backs ride the graph wrapper because the
          // script test's mirror reads them wherever the derive gate emits
          // them — every step of a graph world, not just the frames where
          // the code panel is mounted; same source as the panel (`landed`)
          data-demo-released={landed.release !== undefined ? 'true' : 'false'}
          data-demo-generated-files={String(landed.generatedFiles?.length ?? 0)}
          data-demo-graph-modified={String(landed.graphDelta?.modified?.length ?? 0)}
          data-demo-graph-removed={String(landed.graphDelta?.removed?.length ?? 0)}
          data-demo-distill-status={landed.distillation?.status ?? 'none'}
          data-demo-distill-candidates={String(landed.distillation?.candidates.length ?? 0)}
          // the regeneration read-backs (ACP-734) ride the same always-mounted
          // wrapper: derive() emits regenVersion/diffGroups for EVERY step of a
          // graph world, but the regen panels only mount once the doc is
          // regenerated — so the mirror reads them off the wrapper, present for
          // the pre-regen steps too
          data-demo-regen={landed.regeneration !== undefined ? 'true' : 'false'}
          data-demo-diff-groups={String(landed.diffGroups?.length ?? 0)}
          // the development-run read-backs (ACP-735) ride the same wrapper:
          // devActive / done-phase count / runnable / preview-open are stated
          // for EVERY step of a graph world by derive(), so the mirror must
          // read them even before the dev panel mounts (and while the preview
          // overlay covers the page — the wrapper stays in the DOM)
          data-demo-dev={landed.devRun !== undefined ? 'true' : 'false'}
          data-demo-dev-phases-done={String(
            (landed.devRun?.phases ?? []).filter((p) => p.status === 'done').length,
          )}
          data-demo-dev-runnable={landed.devRun?.runnableVersion ? 'true' : 'false'}
          data-demo-run-open={landed.runPreview !== undefined ? 'true' : 'false'}
          // the history read-backs (ACP-736) ride the same wrapper: the
          // closing frames are the first to carry `history`, but derive()
          // states the count for every step of a graph world
          data-demo-history-events={String(landed.history?.events.length ?? 0)}
          data-demo-new-round={landed.newRound === true ? 'true' : 'false'}
        >
          <GraphView
            graph={landed.graph}
            addedNodeIds={landed.graphDelta?.nodes}
            addedEdges={landed.graphDelta?.edges}
            modifiedNodeIds={landed.graphDelta?.modified}
            removedNodeIds={landed.graphDelta?.removed}
          />
        </div>
      )}
      {/* the release payoff (ACP-730): once the click has landed, the cut
       * version and the files AI generated from the graph — each file
       * badged with the graph node it implements, so the requirement→
       * graph→code trace reads off the screen. Snapshot-driven like the
       * graph panel: it exists exactly where the loaded frame carries a
       * release, so no step shows a payoff its data does not hold. */}
      {landed.release && (
        <div className="shrink-0 max-h-[320px] overflow-auto border-t border-border bg-bg">
          <div className="sticky top-0 flex items-center gap-2 px-3 py-1.5 bg-card border-b border-border">
            <span
              data-testid="release-cut"
              className="rounded-full bg-accent-subtle px-2 py-0.5 text-[11px] font-semibold text-accent"
            >
              {i18nT('apps.aiStudio.release_cut', { version: landed.release.version })}
            </span>
            <span className="text-[11px] text-muted">
              {new Date(landed.release.time).toLocaleString()}
            </span>
            <span className="text-[11px] text-text truncate">{landed.release.notes}</span>
          </div>
          <CodeGenView files={landed.generatedFiles ?? []} nodeLabels={nodeLabels} />
        </div>
      )}
      {/* the distillation panel (ACP-733): the AI's proposed structured
       * changes to the graph after the release froze the docs. Snapshot-
       * driven like every other panel here — it exists exactly where the
       * loaded frame carries a run, and what it lists (status, candidates,
       * evidence) is the run's own data, machine-proven to equal the graph
       * wave the panel above highlights. */}
      {landed.distillation && (
        <div className="shrink-0 max-h-[280px] overflow-auto border-t border-border bg-bg">
          <DistillPanel distillation={landed.distillation} />
        </div>
      )}
      {/* the regenerated document (ACP-734, step 10): the applied distillation
       * flowed back into a new doc version, badged with the run that produced
       * it. Snapshot-driven like every panel here — it exists exactly where the
       * loaded frame carries a regeneration, and what it shows (the content,
       * the generatedFrom source) is that frame's own data. The version row's
       * real diff is the business 版本历史 view above; this panel is the demo-
       * layer annotation of where the version came from (§4: the business
       * component stays free of any demo/origin concept). */}
      {landed.regeneration && (
        <div className="shrink-0 max-h-[320px] overflow-auto border-t border-border bg-bg">
          <RegenDocView regen={landed.regeneration} />
        </div>
      )}
      {/* the three-segment paired diff (step 11): one row per business point,
       * 用户改动 / 结构化变化 / 重生成差异 side by side. Every line here was
       * sliced out of the fixture's own version rows (the generator proved it),
       * so the review shows the snapshots' difference, never a claim. */}
      {landed.diffGroups && landed.diffGroups.length > 0 && (
        <div className="shrink-0 max-h-[360px] overflow-auto border-t border-border bg-bg">
          <RegenDiffPair groups={landed.diffGroups} />
        </div>
      )}
      {/* the development run (ACP-735, steps 12-14): record anchored to the
       * frozen design, the four-phase walk, and once every phase is done the
       * artifacts + runnable entry. Phase statuses are the loaded frame's own
       * data — autoplay advancing frames IS the process advancing, and manual
       * stepping shows the identical pictures. 打开可运行版本 is offered only
       * on the step whose after-fix frame carries the preview it opens (the
       * real frame already shows it open, so the button never re-appears
       * there); its click is a frame swap onto that snapshot's own data. */}
      {landed.devRun && (
        <div className="shrink-0 max-h-[340px] overflow-auto border-t border-border bg-bg">
          <DevRunPanel run={landed.devRun} onOpenRun={canOpenRun && !liveLanded ? onOpenRun : undefined} />
        </div>
      )}
      {/* the runnable experience (step 15): an internal overlay route onto
       * the frame's runPreview data — no server, no container, the ticket's
       * hard rule. Rendered under the same overlay the guidance layer rings. */}
      {landed.runPreview && (
        <RunPreviewScreen preview={landed.runPreview} />
      )}
      {/* the project-wide history (ACP-736, steps 16-17): this round's facts
       * as one linked chain, snapshot-driven like every panel above — it
       * exists exactly where the loaded frame carries `history`. A node's
       * jump loads the script step that SHOWS its ref snapshot (回放 doctrine:
       * 跳转=加载快照, never reverse-compute); 继续设计 is offered only on
       * the step whose after-fix frame declares the new round. */}
      {landed.history && (
        <div className="shrink-0 max-h-[400px] overflow-auto border-t border-border bg-bg">
          <ProjectHistoryView
            history={landed.history}
            onJump={ctl.jumpToRef}
            onContinue={canContinue && !liveLanded ? onContinue : undefined}
          />
        </div>
      )}
      <DemoOverlay ctl={ctl} />
    </div>
  )
}
