// Shared test scaffolding for the ai-studio page tests: the workbench renders
// through the /ai-studio/projects/<id> route (AiStudioPage dispatches on the
// pathname), so the router wrapper has to match. Backend reads are mocked per
// test file (vi.mock does not hoist across modules — each file mocks
// ./studioApi and ../../app-sdk/ChatEmbed itself); this holds only the
// providers and the fixture data.
import type { ReactElement } from 'react'
import { render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

export function renderStudio(ui: ReactElement, initialEntry = '/ai-studio/projects/p1') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialEntry]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}

// The doc set the workbench's Docs tool and editor see. Names match the old
// fixture so tool-tab assertions read the same; content is minimal.
export const TEST_DOCS = [
  { name: 'requirements.md', content: '# 需求说明\n\n商机阶段\n' },
  { name: 'workflow.md', content: '# 流程设计\n\n阶段流转\n' },
  { name: 'ui-spec.md', content: '# 界面设计\n' },
]

export const TEST_PROJECT = {
  id: 'p1',
  name: '测试项目',
  description: '一个项目',
  createdAt: Date.now() / 1000,
}
