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
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import ErrorNotice from '../../../components/ErrorNotice'
import { i18nT } from '../../../i18n/t'
import CodeGenView from '../CodeGenView'
import GraphView from '../GraphView'
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
  // main-10's live release act: the click walks the step's phase labels and
  // then lands — "landed" means swapping the bottom panel to the after-fix
  // snapshot's payload (the release cut + the generated files). Like
  // liveCommit, it belongs to the step: leaving the step re-derives the
  // whole picture from that step's own snapshot, never from leftovers.
  const [liveRelease, setLiveRelease] = useState(false)

  // state-layer swap: a new step means a new fake, so every cached
  // ai-studio read (project docs, both histories) is stale by construction.
  // Removing the prefix — rather than invalidating — is the honest move:
  // the old fake is gone, nothing about it can still be served.
  const stepIndex = ctl?.stepIndex
  useEffect(() => {
    queryClient.removeQueries({ queryKey: ['ai-studio'] })
    setLiveCommit(null)
    setLiveRelease(false)
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
  const canRelease = ctl.afterFixFixture?.release !== undefined
  const showRelease = liveRelease || ctl.fixture.release !== undefined
  // which snapshot the bottom panel speaks: once the click has landed, the
  // after-fix one (release + generated files); until then, the step's own.
  // Computed inline (not hooks) — these sit below the ctl null-guard, so
  // wrapping them in useMemo/useCallback would violate rules-of-hooks.
  const landed: DemoFixture = liveRelease && ctl.afterFixFixture ? ctl.afterFixFixture : ctl.fixture
  const nodeLabels = Object.fromEntries((landed.graph?.nodes ?? []).map((n) => [n.id, n.label]))
  const onRelease = async () => {
    if (!ctl.afterFixFixture) return
    const phases = ctl.step.releasePhases ?? []
    await new Promise((r) => setTimeout(r, Math.max(phases.length, 1) * RELEASE_PHASE_MS))
    setLiveRelease(true)
  }

  return (
    <div className="flex flex-col h-full min-h-0" data-testid="ai-studio-demo" data-demo-scenario={ctl.scenario}>
      <header className="flex items-center gap-3 px-4 h-[44px] shrink-0 border-b border-border bg-card">
        <span className="text-sm font-semibold text-text-strong">{ctl.fixture.project.name}</span>
        <span className="text-[12px] text-muted truncate">{ctl.fixture.project.description}</span>
        <span className="flex-1" />
        {/* the same project-level commit bar the ordinary workbench renders
         * (§4: the demo acts on the real business path, through the fake's
         * data), running against the snapshot fake */}
        <div className="relative flex items-center gap-2">
          <ProjectCommitBar projectId={ctl.fixture.project.id} api={ctl.api} onCommitted={onDocCommitted} />
          {/* the release button appears only on the step whose after-fix
           * snapshot actually carries a release (main-10) — nowhere else,
           * so no step ever offers a button whose click lands on nothing */}
          {canRelease && (
            <ReleaseControl
              onRelease={onRelease}
              phases={ctl.step.releasePhases}
              phaseMs={RELEASE_PHASE_MS}
              disabled={showRelease}
            />
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
        >
          <GraphView
            graph={landed.graph}
            addedNodeIds={landed.graphDelta?.nodes}
            addedEdges={landed.graphDelta?.edges}
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
      <DemoOverlay ctl={ctl} />
    </div>
  )
}
