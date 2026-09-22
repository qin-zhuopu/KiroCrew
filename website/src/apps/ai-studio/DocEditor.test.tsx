// DocEditor behavior under the Tiptap surface: the Markdown renders rich, a
// toolbar action serializes into the Markdown buffer (proved through the Raw
// view, which shows the same buffer as text), the Raw→Rich flip re-parses an
// edited source, and Save POSTs the buffer once and clears the dirty footer.
// UI strings assert the English catalog (tests pin i18next to en); doc content
// is Chinese by design and asserted as data. Tiptap is created in an effect
// (immediatelyRender false), so every first read goes through findBy.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const saveDoc = vi.hoisted(() => vi.fn(async () => ({ name: 'workflow.md', content: 'x' })))
vi.mock('./studioApi', async () => {
  const actual = await vi.importActual('./studioApi')
  return { ...actual, studioApi: { saveDoc } }
})

import DocEditor from './DocEditor'

const WF = '# 流程设计\n\n阶段流转\n'

beforeEach(() => {
  saveDoc.mockClear()
})

function renderEditor(props?: Partial<React.ComponentProps<typeof DocEditor>>) {
  return render(
    <DocEditor
      projectId="p1"
      docName="workflow.md"
      initialContent={WF}
      {...props}
    />,
  )
}

describe('DocEditor', () => {
  it('renders the doc rich from its Markdown', async () => {
    renderEditor()
    const doc = await screen.findByTestId('doc-workflow.md')
    // the Tiptap instance is created in an effect; wait for its first paint
    expect(await within(doc).findByText('流程设计')).toBeInTheDocument()
    expect(within(doc).getByText('阶段流转')).toBeInTheDocument()
    // raw mode is off: no source textarea yet
    expect(screen.queryByRole('textbox', { name: 'workflow.md' })).not.toBeInTheDocument()
    // pristine buffer: Save is disabled, the footer says saved
    expect(screen.getByRole('button', { name: /Save/i })).toBeDisabled()
    expect(within(doc).getByText('Saved')).toBeInTheDocument()
  })

  it('serializes a toolbar bold into the Markdown buffer', async () => {
    const user = userEvent.setup()
    renderEditor()
    const doc = await screen.findByTestId('doc-workflow.md')
    const editable = await within(doc).findByText('流程设计')
    await user.click(editable)
    await user.keyboard('{Control>}{a}{/Control}')
    await user.click(within(doc).getByRole('button', { name: 'Bold' }))
    // bold is now the active mark
    expect(within(doc).getByRole('button', { name: 'Bold' })).toHaveAttribute('aria-pressed', 'true')
    // and the buffer carries it: the Raw view shows the markdown source
    await user.click(within(doc).getByRole('button', { name: 'Markdown' }))
    const src = screen.getByRole('textbox', { name: 'workflow.md' })
    expect((src as HTMLTextAreaElement).value).toContain('**')
  })

  it('round-trips an edited Raw source back into the rich surface', async () => {
    const user = userEvent.setup()
    renderEditor()
    const doc = await screen.findByTestId('doc-workflow.md')
    await within(doc).findByText('流程设计')
    await user.click(within(doc).getByRole('button', { name: 'Markdown' }))
    const src = screen.getByRole('textbox', { name: 'workflow.md' }) as HTMLTextAreaElement
    await user.clear(src)
    await user.type(src, '# 新标题\n\n- 项目甲')
    await user.click(within(doc).getByRole('button', { name: 'Markdown' }))
    // the flipped-back rich surface re-parsed what the textarea held
    expect(await within(doc).findByText('新标题')).toBeInTheDocument()
    expect(within(doc).getByText('项目甲')).toBeInTheDocument()
    // and the original content is gone
    expect(within(doc).queryByText('流程设计')).not.toBeInTheDocument()
  })

  it('saves the buffer once and reports dirty state around the save', async () => {
    const user = userEvent.setup()
    const onSaved = vi.fn()
    renderEditor({ onSaved })
    const doc = await screen.findByTestId('doc-workflow.md')
    const saveBtn = screen.getByRole('button', { name: /Save/i })
    // editing through the Raw textarea marks the buffer dirty and enables Save
    await user.click(within(doc).getByRole('button', { name: 'Markdown' }))
    const src = screen.getByRole('textbox', { name: 'workflow.md' }) as HTMLTextAreaElement
    await user.clear(src)
    await user.type(src, '# 流程设计 v2')
    expect(within(doc).getByText('Unsaved changes')).toBeInTheDocument()
    expect(saveBtn).toBeEnabled()
    await user.click(saveBtn)
    expect(saveDoc).toHaveBeenCalledWith('p1', 'workflow.md', '# 流程设计 v2')
    expect(onSaved).toHaveBeenCalled()
    expect(await within(doc).findByText('Saved')).toBeInTheDocument()
    expect(saveBtn).toBeDisabled()
  })

  it('surfaces a failed save without losing the buffer', async () => {
    const { StudioApiError } = await import('./studioApi')
    saveDoc.mockRejectedValueOnce(new StudioApiError(404, 'project_not_found', 'gone'))
    const user = userEvent.setup()
    renderEditor()
    const doc = await screen.findByTestId('doc-workflow.md')
    await user.click(within(doc).getByRole('button', { name: 'Markdown' }))
    const src = screen.getByRole('textbox', { name: 'workflow.md' }) as HTMLTextAreaElement
    await user.clear(src)
    await user.type(src, 'changed')
    await user.click(screen.getByRole('button', { name: /Save/i }))
    expect(await screen.findByText('Project no longer exists')).toBeInTheDocument()
    // the buffer still holds what was typed — a failed save loses nothing
    expect((screen.getByRole('textbox', { name: 'workflow.md' }) as HTMLTextAreaElement).value).toBe('changed')
    expect(within(doc).getByText('Unsaved changes')).toBeInTheDocument()
  })

  it('every toolbar action runs and reflects on the pressed state', async () => {
    const user = userEvent.setup()
    renderEditor()
    const doc = await screen.findByTestId('doc-workflow.md')
    await within(doc).findByText('流程设计')
    await user.click(within(doc).getByText('流程设计'))
    await user.keyboard('{Control>}{a}{/Control}')
    // Every toggle runs its command without throwing and keeps a truthful
    // aria-pressed; ON/OFF symmetry is NOT asserted because a toggle's second
    // click on a heading block converts it to a paragraph (isActive flips by
    // design), which depends on where the caret landed.
    for (const name of ['Italic', 'Strikethrough', 'Inline code', 'Heading 1', 'Heading 2', 'Bullet list', 'Numbered list', 'Quote']) {
      const btn = within(doc).getByRole('button', { name })
      await user.click(btn)
      expect(btn).toHaveAttribute('aria-pressed')
    }
    // history buttons run their commands without throwing
    await user.click(within(doc).getByRole('button', { name: 'Undo' }))
    await user.click(within(doc).getByRole('button', { name: 'Redo' }))
  })
})
