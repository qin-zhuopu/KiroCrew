// The `?demo=` branch of the AI Studio route: a stripped workbench that runs
// the real DocEditor/WorkArea against the snapshot fake, plus the guidance
// overlay. AiStudioPage mounts this ONLY when the URL carries `?demo=`; the
// ordinary StudioWorkspace — chat column, resizers, localStorage pane state —
// never sees a demo line, which is the §4 rule held literally: the demo lives
// beside the business components, not inside them.
//
// One step = one wholesale load (§6): the runtime swaps the fixture (state
// layer), the ai-studio query cache is dropped so every read re-serves from
// the new fake, the doc tab is keyed on the step so the editor re-mounts
// with that step's committed baseline, and the overlay replays the step's
// open acts onto it (view layer). Back and next are the same operation on a
// different index — never a reverse mutation.
import { useEffect, useMemo } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import ErrorNotice from '../../../components/ErrorNotice'
import { i18nT } from '../../../i18n/t'
import WorkArea, { type WorkTab } from '../WorkArea'
import DemoOverlay from './overlay'
import { useDemoRuntime } from './runtime'

export default function DemoWorkspace({ params }: {
  params: { scenario: string; autoMs: number; settleMs: number }
}) {
  const { ctl, unknown } = useDemoRuntime(params)
  const queryClient = useQueryClient()

  // state-layer swap: a new step means a new fake, so every cached
  // ai-studio read (project docs, both histories) is stale by construction.
  // Removing the prefix — rather than invalidating — is the honest move:
  // the old fake is gone, nothing about it can still be served.
  const stepIndex = ctl?.stepIndex
  useEffect(() => {
    queryClient.removeQueries({ queryKey: ['ai-studio'] })
  }, [stepIndex, queryClient])

  // the focused doc tab, re-keyed on the step: the editor re-mounts into the
  // new snapshot's committed baseline every step (the buffer arrives later,
  // typed by the overlay through the real editor path — §5's business-event
  // replay, not a prop pretending to be dirty)
  const tabs: WorkTab[] = useMemo(() => {
    if (!ctl) return []
    const committed = ctl.fixture.docs.find((d) => d.name === ctl.fixture.focusDoc)?.content ?? ''
    return [{
      id: `demo-doc-${ctl.fixture.focusDoc}-${stepIndex}`,
      kind: 'doc',
      title: ctl.fixture.focusDoc,
      docName: ctl.fixture.focusDoc,
      initialContent: committed,
    }]
  }, [ctl, stepIndex])

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
      </header>
      <div className="flex-1 min-h-0">
        <WorkArea
          tabs={tabs}
          activeId={tabs[0]?.id ?? null}
          onSelect={() => { /* single scripted tab: nothing to select */ }}
          onClose={() => { /* the script owns the tab strip */ }}
          projectId={ctl.fixture.project.id}
          onDocSaved={() => { /* demo commits touch only the snapshot fake */ }}
          api={ctl.api}
        />
      </div>
      <DemoOverlay ctl={ctl} />
    </div>
  )
}
