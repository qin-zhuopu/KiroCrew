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
// The one live business act the scripts are allowed (main-8's real commit
// click) runs through the SAME ProjectCommitBar the ordinary workbench
// renders, only backed by the fake: after it lands, the freshly committed
// doc content re-points the open tab, so the re-mounted editor is clean
// against its new baseline instead of showing a stale dirty buffer.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import ErrorNotice from '../../../components/ErrorNotice'
import { i18nT } from '../../../i18n/t'
import GraphView from '../GraphView'
import ProjectCommitBar from '../ProjectCommitBar'
import WorkArea, { type WorkTab } from '../WorkArea'
import type { StudioDoc } from '../studioApi'
import DemoOverlay from './overlay'
import { useDemoRuntime } from './runtime'

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

  // state-layer swap: a new step means a new fake, so every cached
  // ai-studio read (project docs, both histories) is stale by construction.
  // Removing the prefix — rather than invalidating — is the honest move:
  // the old fake is gone, nothing about it can still be served.
  const stepIndex = ctl?.stepIndex
  useEffect(() => {
    queryClient.removeQueries({ queryKey: ['ai-studio'] })
    setLiveCommit(null)
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
       * of nowhere. Worlds without a graph (the alt lines) never render it. */}
      {ctl.fixture.graph && (
        <div className="shrink-0 max-h-[300px] overflow-auto border-t border-border bg-bg">
          <GraphView
            graph={ctl.fixture.graph}
            addedNodeIds={ctl.fixture.graphDelta?.nodes}
            addedEdges={ctl.fixture.graphDelta?.edges}
          />
        </div>
      )}
      <DemoOverlay ctl={ctl} />
    </div>
  )
}
