// A project doc as a WYSIWYG editor: Tiptap (MIT) with the official Markdown
// extension, so the store stays Markdown and the author edits rich text.
//
// Why Tiptap and not a vendored editor: docmost's editor is the same engine
// (Tiptap over ProseMirror) but ships AGPL-3.0, which cannot be copied into
// this Apache-2.0 public fork. Tiptap itself is MIT, so it is the clean source
// — the same result, no copyleft in the tree.
//
// Two modes over one buffer of Markdown:
//   - Rich (default): a contenteditable Tiptap surface; edits serialize back
//     to Markdown via editor.getMarkdown().
//   - Raw: the Markdown source in a textarea for direct text control.
// Switching modes re-parses the buffer (setContent({contentType:'markdown'})),
// so the two views never drift — the source of truth is always `draft`.
//
// Saving is explicit (the Save button), not autosave-on-keystroke: the buffer
// is compared against `savedAt` to show dirty state, and a save POSTs the whole
// buffer to /docs (the store replaces the file). The tab is keyed on
// project+doc in WorkArea, so switching tabs re-mounts with fresh content and
// an un-saved edit in a closed tab is honestly lost — the footer says so.
import { useCallback, useRef, useState, type ReactNode } from 'react'
import { EditorContent, useEditor, type Editor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
// named, not default: @tiptap/markdown ships no default export (its barrel
// exports Markdown/MarkdownManager only) — a default import resolves to
// undefined under ESM and the extension silently vanishes from the manager.
import { Markdown } from '@tiptap/markdown'
import {
  Bold, Code, Heading1, Heading2, Italic, List, ListOrdered,
  Quote, Redo2, Save, Strikethrough, Undo2,
} from 'lucide-react'
import ErrorNotice from '../../components/ErrorNotice'
import { Btn } from '../../components/ui'
import { i18nT } from '../../i18n/t'
import { studioApi, StudioApiError } from './studioApi'
import './DocEditor.css'

export default function DocEditor({ projectId, docName, initialContent, onSaved }: {
  projectId: string
  docName: string
  initialContent: string
  onSaved?: () => void
}) {
  const [draft, setDraft] = useState(initialContent)
  const [saved, setSaved] = useState(initialContent)
  const [saving, setSaving] = useState(false)
  const [saveErr, setSaveErr] = useState<string | null>(null)
  const [raw, setRaw] = useState(false)
  // The Rich surface mounts and unmounts with the mode, and useEditor follows
  // it: a `gen` bump on every flip re-creates the instance bound to the fresh
  // EditorContent (the hook's own cleanup destroys the previous one — keeping
  // one editor across the unmount would hand ProseMirror a detached element).
  // `gen` only changes on a flip, so an ordinary keystroke re-render never
  // rebuilds the editor. `sourceRef` carries the Markdown buffer INTO the new
  // instance's create options — the flip handlers write it before setRaw, so
  // the create always reads the just-edited text, never a stale initial.
  const [gen, setGen] = useState(0)
  const sourceRef = useRef(initialContent)
  const editor = useEditor(
    {
      immediatelyRender: false,
      extensions: [StarterKit, Markdown],
      contentType: 'markdown',
      content: sourceRef.current,
      editorProps: { attributes: { class: 'ai-studio-doc' } },
      onUpdate: ({ editor: e }) => {
        // Only the Rich surface drives the buffer; the Raw textarea owns it
        // while shown, and the flip handlers snapshot getMarkdown() there,
        // so a hidden/destroyed editor never has to be read.
        setDraft(e.getMarkdown())
      },
    },
    [gen],
  )

  const flipToRaw = useCallback(() => {
    // Snapshot the Rich buffer into the shared draft before the surface (and
    // with it the editor instance) goes away.
    if (editor && !editor.isDestroyed) {
      sourceRef.current = editor.getMarkdown()
      setDraft(sourceRef.current)
    }
    setGen((g) => g + 1)
    setRaw(true)
  }, [editor])

  const flipToRich = useCallback(() => {
    // The textarea has been writing `draft` all along; hand it to the editor
    // about to be created for the Rich surface.
    sourceRef.current = draft
    setGen((g) => g + 1)
    setRaw(false)
  }, [draft])

  const run = useCallback((fn: (e: Editor) => void) => {
    if (editor && !editor.isDestroyed) fn(editor)
  }, [editor])

  const dirty = draft !== saved

  const save = useCallback(async () => {
    setSaving(true)
    setSaveErr(null)
    try {
      // Snapshot the Rich buffer first: while Raw is shown the textarea owns
      // the buffer and `draft` is current, but from Rich the textarea does
      // not exist — same reasoning as the flip handlers.
      const content = raw || !editor || editor.isDestroyed ? draft : editor.getMarkdown()
      await studioApi.saveDoc(projectId, docName, content)
      setDraft(content)
      setSaved(content)
      onSaved?.()
    } catch (err) {
      setSaveErr(
        err instanceof StudioApiError && err.code === 'project_not_found'
          ? i18nT('apps.aiStudio.err_project_missing')
          : err instanceof Error ? err.message : String(err),
      )
    } finally {
      setSaving(false)
    }
  }, [draft, editor, onSaved, projectId, docName, raw])

  return (
    <div className="flex flex-col h-full min-h-0" data-testid={`doc-${docName}`}>
      <div className="flex items-center gap-1.5 px-4 h-[38px] shrink-0 border-b border-border">
        <span className="text-[13px] text-muted">{docName}</span>
        <span className="flex-1" />
        {!raw && (
          <div className="flex items-center gap-0.5" role="toolbar" aria-label={i18nT('apps.aiStudio.format_toolbar')}>
            <ToolbarBtn label={i18nT('apps.aiStudio.fmt_bold')} icon={<Bold size={14} />}
              active={editor?.isActive('bold')} onRun={(e) => e.chain().focus().toggleBold().run()} run={run} />
            <ToolbarBtn label={i18nT('apps.aiStudio.fmt_italic')} icon={<Italic size={14} />}
              active={editor?.isActive('italic')} onRun={(e) => e.chain().focus().toggleItalic().run()} run={run} />
            <ToolbarBtn label={i18nT('apps.aiStudio.fmt_strikethrough')} icon={<Strikethrough size={14} />}
              active={editor?.isActive('strike')} onRun={(e) => e.chain().focus().toggleStrike().run()} run={run} />
            <ToolbarBtn label={i18nT('apps.aiStudio.fmt_code')} icon={<Code size={14} />}
              active={editor?.isActive('code')} onRun={(e) => e.chain().focus().toggleCode().run()} run={run} />
            <span className="w-px h-4 bg-border mx-1" aria-hidden />
            <ToolbarBtn label={i18nT('apps.aiStudio.fmt_h1')} icon={<Heading1 size={14} />}
              active={editor?.isActive('heading', { level: 1 })} onRun={(e) => e.chain().focus().toggleHeading({ level: 1 }).run()} run={run} />
            <ToolbarBtn label={i18nT('apps.aiStudio.fmt_h2')} icon={<Heading2 size={14} />}
              active={editor?.isActive('heading', { level: 2 })} onRun={(e) => e.chain().focus().toggleHeading({ level: 2 }).run()} run={run} />
            <ToolbarBtn label={i18nT('apps.aiStudio.fmt_bullet')} icon={<List size={14} />}
              active={editor?.isActive('bulletList')} onRun={(e) => e.chain().focus().toggleBulletList().run()} run={run} />
            <ToolbarBtn label={i18nT('apps.aiStudio.fmt_ordered')} icon={<ListOrdered size={14} />}
              active={editor?.isActive('orderedList')} onRun={(e) => e.chain().focus().toggleOrderedList().run()} run={run} />
            <ToolbarBtn label={i18nT('apps.aiStudio.fmt_quote')} icon={<Quote size={14} />}
              active={editor?.isActive('blockquote')} onRun={(e) => e.chain().focus().toggleBlockquote().run()} run={run} />
            <span className="w-px h-4 bg-border mx-1" aria-hidden />
            <ToolbarBtn label={i18nT('apps.aiStudio.fmt_undo')} icon={<Undo2 size={14} />}
              disabled={!editor?.can().undo()} onRun={(e) => e.chain().focus().undo().run()} run={run} />
            <ToolbarBtn label={i18nT('apps.aiStudio.fmt_redo')} icon={<Redo2 size={14} />}
              disabled={!editor?.can().redo()} onRun={(e) => e.chain().focus().redo().run()} run={run} />
          </div>
        )}
        <button
          type="button"
          className={`ml-1 rounded-md border border-border px-2 py-1 text-[12px] cursor-pointer transition-colors ${raw ? 'bg-bg-hover text-text' : 'text-muted hover:text-text'}`}
          aria-pressed={raw}
          onClick={raw ? flipToRich : flipToRaw}
        >
          Markdown
        </button>
        <Btn primary onClick={save} disabled={!dirty || saving} className="ml-1">
          <Save size={13} className="lucide-inline" /> {i18nT('apps.aiStudio.save')}
        </Btn>
      </div>
      <div className="flex-1 min-h-0 overflow-auto">
        {raw ? (
          <textarea
            className="w-full h-full resize-none bg-transparent p-4 text-[13px] leading-6 font-mono text-text outline-none"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            aria-label={docName}
          />
        ) : (
          <div className="p-5 max-w-[820px]">
            <EditorContent editor={editor} />
          </div>
        )}
      </div>
      {saveErr && (
        <div className="px-4 pt-2 shrink-0">
          {/* askAgent stays off: there is an unsaved buffer right here that
              the hand-off's navigation would destroy. */}
          {/* No hand-off: the draft buffer in this component dies with it. */}
          <ErrorNotice message={saveErr} askAgent={false} onDismiss={() => setSaveErr(null)} />
        </div>
      )}
      <div className="px-4 py-1.5 border-t border-border text-[11px] text-muted shrink-0">
        {dirty ? i18nT('apps.aiStudio.draft_dirty') : i18nT('apps.aiStudio.draft_saved')}
      </div>
    </div>
  )
}

function ToolbarBtn({ label, icon, active, disabled, onRun, run }: {
  label: string
  icon: ReactNode
  active?: boolean
  disabled?: boolean
  onRun: (e: Editor) => void
  run: (fn: (e: Editor) => void) => void
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-pressed={active}
      disabled={disabled}
      onClick={() => run(onRun)}
      className={`inline-flex items-center justify-center w-7 h-7 rounded-md transition-colors disabled:opacity-40 disabled:cursor-default ${
        active ? 'bg-bg-hover text-text' : 'text-muted hover:text-text hover:bg-bg-hover'
      }`}
    >
      {icon}
    </button>
  )
}
