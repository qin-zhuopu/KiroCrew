// DocEditor behavior under the Tiptap surface: the Markdown renders rich, a
// toolbar action serializes into the Markdown buffer (proved through the Raw
// view, which shows the same buffer as text), the Raw→Rich flip re-parses an
// edited source, and Commit POSTs the buffer once and clears the dirty footer.
// The ACP-722 toolbar trio is covered too: the diff button gates on dirty,
// edits autosave a draft on a ~2s debounce, the autosave-history popover
// lists records and restores one, and the version-history popover opens the
// read-only version diff. The editor now reads history through React Query,
// so every render goes through the router/provider wrapper (renderStudio).
// UI strings assert the English catalog (tests pin i18next to en); doc
// content is Chinese by design and asserted as data. Tiptap is created in an
// effect (immediatelyRender false), so every first read goes through findBy.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const saveDoc = vi.hoisted(() => vi.fn(async () => ({ name: 'workflow.md', content: 'x' })))
const saveDraft = vi.hoisted(() => vi.fn(async () => ({ ok: true })))
const listDraftVersions = vi.hoisted(() => vi.fn(async () => ({ versions: [] as unknown[] })))
const listVersions = vi.hoisted(() => vi.fn(async () => ({ versions: [] as unknown[] })))
vi.mock('./studioApi', async () => {
  const actual = await vi.importActual('./studioApi')
  return { ...actual, studioApi: { saveDoc, saveDraft, listDraftVersions, listVersions } }
})

import DocEditor from './DocEditor'
import { renderStudio } from './testUtils'

const WF = '# 流程设计\n\n阶段流转\n'

beforeEach(() => {
  saveDoc.mockClear()
  saveDraft.mockClear()
  listDraftVersions.mockResolvedValue({ versions: [] })
  listVersions.mockResolvedValue({ versions: [] })
})

function renderEditor(props?: Partial<React.ComponentProps<typeof DocEditor>>) {
  renderStudio(
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
    // pristine buffer: Commit is disabled, the footer says saved
    expect(screen.getByRole('button', { name: /Commit version/i })).toBeDisabled()
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

  it('commits the buffer once and reports dirty state around the commit', async () => {
    const user = userEvent.setup()
    const onSaved = vi.fn()
    renderEditor({ onSaved })
    const doc = await screen.findByTestId('doc-workflow.md')
    const commitBtn = screen.getByRole('button', { name: /Commit version/i })
    // editing through the Raw textarea marks the buffer dirty and enables Commit
    await user.click(within(doc).getByRole('button', { name: 'Markdown' }))
    const src = screen.getByRole('textbox', { name: 'workflow.md' }) as HTMLTextAreaElement
    await user.clear(src)
    await user.type(src, '# 流程设计 v2')
    expect(within(doc).getByText('Unsaved changes')).toBeInTheDocument()
    expect(commitBtn).toBeEnabled()
    await user.click(commitBtn)
    expect(saveDoc).toHaveBeenCalledWith('p1', 'workflow.md', '# 流程设计 v2')
    expect(onSaved).toHaveBeenCalled()
    expect(await within(doc).findByText('Saved')).toBeInTheDocument()
    expect(commitBtn).toBeDisabled()
  })

  it('surfaces a failed commit without losing the buffer', async () => {
    const { StudioApiError } = await import('./studioApi')
    saveDoc.mockRejectedValueOnce(new StudioApiError(404, 'project_not_found', 'gone'))
    const user = userEvent.setup()
    renderEditor()
    const doc = await screen.findByTestId('doc-workflow.md')
    await user.click(within(doc).getByRole('button', { name: 'Markdown' }))
    const src = screen.getByRole('textbox', { name: 'workflow.md' }) as HTMLTextAreaElement
    await user.clear(src)
    await user.type(src, 'changed')
    await user.click(screen.getByRole('button', { name: /Commit version/i }))
    expect(await screen.findByText('Project no longer exists')).toBeInTheDocument()
    // the buffer still holds what was typed — a failed commit loses nothing
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

  // ---- ACP-722: diff / autosave history / version history ----------------

  it('the diff button is disabled pristine and opens current-vs-commit when dirty', async () => {
    const user = userEvent.setup()
    renderEditor()
    const doc = await screen.findByTestId('doc-workflow.md')
    await within(doc).findByText('流程设计')
    const diffBtn = within(doc).getByRole('button', { name: /Diff against last commit/i })
    expect(diffBtn).toBeDisabled()
    // one edit in the Raw surface flips it enabled, and the click opens the dialog
    await user.click(within(doc).getByRole('button', { name: 'Markdown' }))
    const src = screen.getByRole('textbox', { name: 'workflow.md' }) as HTMLTextAreaElement
    await user.clear(src)
    await user.type(src, '# 流程设计 v2')
    expect(diffBtn).toBeEnabled()
    await user.click(diffBtn)
    const dialog = await screen.findByRole('dialog', { name: /Diff against last commit/i })
    // removed lines (old committed text) and added lines (current buffer) show
    expect(within(dialog).getByText('- # 流程设计')).toBeInTheDocument()
    expect(within(dialog).getByText('+ # 流程设计 v2')).toBeInTheDocument()
    // no restore affordance on this one — restoring the committed text is Undo's job
    expect(within(dialog).queryByRole('button', { name: /Restore/i })).not.toBeInTheDocument()
  })

  it('autosaves the draft on a ~2s debounce, one POST per burst', async () => {
    // real timers: the debounce is 2s, so this test spends ~3s of wall clock.
    // (user.type itself ticks each keystroke well inside that, and the timer
    // re-arms per change — a burst stays one POST.)
    const user = userEvent.setup()
    renderEditor()
    const doc = await screen.findByTestId('doc-workflow.md')
    await within(doc).findByText('流程设计')
    await user.click(within(doc).getByRole('button', { name: 'Markdown' }))
    const src = screen.getByRole('textbox', { name: 'workflow.md' }) as HTMLTextAreaElement
    await user.clear(src)
    await user.type(src, 'abc')
    // mid-window: nothing posted yet
    expect(saveDraft).not.toHaveBeenCalled()
    await waitFor(() => expect(saveDraft).toHaveBeenCalled(), { timeout: 4000, interval: 100 })
    expect(saveDraft).toHaveBeenCalledWith('p1', 'workflow.md', 'abc')
    // idling changes nothing, so nothing re-posts (the client should not even
    // send a duplicate the backend would dedupe)
    await new Promise((r) => setTimeout(r, 2500))
    expect(saveDraft).toHaveBeenCalledTimes(1)
  }, 15000)

  it('the autosave history lists records, opens one as a diff, and restores it', async () => {
    listDraftVersions.mockResolvedValue({
      versions: [
        { name: 'workflow.md', time: 1758500000, content: '# 中途稿\n\n旧内容' },
      ],
    })
    const user = userEvent.setup()
    renderEditor()
    const doc = await screen.findByTestId('doc-workflow.md')
    await within(doc).findByText('流程设计')
    const histBtn = within(doc).getByRole('button', { name: /Autosave history/i })
    // records exist: the button is enabled and opens the list
    expect(histBtn).toBeEnabled()
    await user.click(histBtn)
    const list = await screen.findByTestId('draft-history-list')
    // the row shows the record's first line as its one-line summary
    expect(within(list).getByText('# 中途稿')).toBeInTheDocument()
    // picking the row opens its diff-vs-current with a restore action
    await user.click(within(list).getByText('# 中途稿'))
    const dialog = await screen.findByRole('dialog', { name: /Autosave history/i })
    expect(within(dialog).getByText('- 旧内容')).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: /Restore this version/i }))
    // restore hands the old text to the buffer: the dirty footer flipped and
    // the rich surface now shows the restored content
    expect(within(doc).getByText('Unsaved changes')).toBeInTheDocument()
    expect(await within(doc).findByText('旧内容')).toBeInTheDocument()
  })

  it('the autosave and version buttons are disabled while their lists are empty', async () => {
    renderEditor()
    const doc = await screen.findByTestId('doc-workflow.md')
    await within(doc).findByText('流程设计')
    expect(within(doc).getByRole('button', { name: /Autosave history/i })).toBeDisabled()
    expect(within(doc).getByRole('button', { name: /Version history/i })).toBeDisabled()
  })

  it('the version history opens a read-only diff and returns to editing', async () => {
    listVersions.mockResolvedValue({
      versions: [
        { name: 'workflow.md', time: 1758600000, diff: '@@ -1 +1 @@\n-旧版内容\n+新版内容\n' },
      ],
    })
    const user = userEvent.setup()
    renderEditor()
    const doc = await screen.findByTestId('doc-workflow.md')
    await within(doc).findByText('流程设计')
    const verBtn = within(doc).getByRole('button', { name: /Version history/i })
    expect(verBtn).toBeEnabled()
    await user.click(verBtn)
    const list = await screen.findByTestId('version-history-list')
    // row body click switches the main area to that version's diff vs previous
    await user.click(within(list).getAllByRole('button')[0])
    const view = await screen.findByTestId('version-view-workflow.md')
    expect(within(view).getByText('+新版内容')).toBeInTheDocument()
    expect(within(view).getByText('-旧版内容')).toBeInTheDocument()
    // read-only takeover: no editor surface, "back to editing" returns it
    expect(screen.queryByRole('textbox', { name: 'workflow.md' })).not.toBeInTheDocument()
    expect(within(doc).queryByRole('button', { name: /Commit version/i })).not.toBeInTheDocument()
    await user.click(within(view).getByRole('button', { name: /Back to editing/i }))
    expect(await within(doc).findByText('流程设计')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Commit version/i })).toBeInTheDocument()
  })
})
