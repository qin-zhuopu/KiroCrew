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
// Edit persistence is two-tier (ACP-722, and ACP-727 moved the second tier
// out of this component): a burst of keystrokes autosaves a DRAFT ~2s after
// the last change (POST docs/draft — the backend dedupes a record identical
// to the previous one), and that is ALL the editor does. Committing is a
// PROJECT-level operation now — the workspace top bar commits every doc with
// a draft at once, because a commit feeds the requirements graph for the
// whole project, not for one file. The doc's name is not shown either (the
// tab already carries it). The toolbar's right side carries the three
// read-backs of the model:
//   - diff: current buffer vs the last commit, only clickable while dirty;
//   - autosave history: draft records since the last commit, each opening a
//     diff against the current buffer with a restore action;
//   - version history: committed snapshots, each opening a read-only unified
//     diff against its predecessor ("back to editing" exits).
// The two lists are React Query reads; while the backend endpoints are still
// landing (ACP-721) a failed query reads as empty, which keeps the icons grey
// without an error surface. The tab is keyed on project+doc+commitRev in
// WorkArea, so switching tabs — and a project-level commit from the top bar,
// which bumps the rev — re-mounts with fresh content, while an un-autosaved
// edit in a closed tab is honestly lost (the footer says so).
import { forwardRef, useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { EditorContent, useEditor, type Editor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
// named, not default: @tiptap/markdown ships no default export (its barrel
// exports Markdown/MarkdownManager only) — a default import resolves to
// undefined under ESM and the extension silently vanishes from the manager.
import { Markdown } from '@tiptap/markdown'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Bold, Code, GitCompareArrows, GitCommit, Heading1, Heading2, History, Italic,
  List, ListOrdered, Quote, Redo2, RotateCcw, Strikethrough, Undo2, X,
} from 'lucide-react'
import Clickable from '../../components/Clickable'
import { useDialogFocusTrap } from '../../hooks/useDialogFocusTrap'
import { Btn } from '../../components/ui'
import { Popover, PopoverContent, PopoverTrigger } from '../../components/ui/popover'
import { fmtDateTimeNumeric } from '../../i18n/format'
import { i18nT } from '../../i18n/t'
import { LineDiff, UnifiedDiffText } from './DiffView'
import { studioApi, type StudioApi, type StudioDraftVersion, type StudioVersion } from './studioApi'
import './DocEditor.css'

/** Debounce for the draft autosave: long enough that a typing burst is one
 * POST, short enough that closing the tab within a couple seconds of the last
 * keystroke still loses nothing. */
const DRAFT_DEBOUNCE_MS = 2000

/** One open diff dialog: two buffers plus the title; `restore` is present
 * only for draft-history diffs (the "restore to this version" action). */
interface DiffModal {
  heading: string
  oldText: string
  newText: string
  restore?: () => void
}

export default function DocEditor({ projectId, docName, initialContent, api = studioApi }: {
  projectId: string
  docName: string
  initialContent: string
  /** the data source, injectable for the demo's snapshot fake; the ordinary
   * path uses the real client and never passes this */
  api?: StudioApi
}) {
  const [draft, setDraft] = useState(initialContent)
  // The committed baseline IS the initial buffer: since ACP-727 nothing in
  // this component commits, so nothing moves the baseline — a project-level
  // commit from the top bar re-mounts the tab (new WorkArea content) rather
  // than mutating this state.
  const saved = initialContent
  const [raw, setRaw] = useState(false)
  const [diffModal, setDiffModal] = useState<DiffModal | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [versionsOpen, setVersionsOpen] = useState(false)
  // Which version-history row is open in the read-only diff body (the version
  //'s timestamp); null while editing. Draft-history diffs render in a modal
  // instead — they are transient, a body takeover would hide the editor.
  const [versionView, setVersionView] = useState<number | null>(null)
  const queryClient = useQueryClient()

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

  const dirty = draft !== saved
  const draftContent = raw || !editor || editor.isDestroyed ? draft : editor.getMarkdown()

  // Draft autosave: `draft` is the single source of truth in both modes, so
  // one debounced effect over it covers the Rich surface and the textarea
  // alike. The timer is re-armed on every change (a burst is one POST), and
  // an identical-to-last-save tick no-ops via the ref, so toggling modes —
  // which re-serializes but may not change a character — writes nothing.
  // Best-effort by design: a failed autosave leaves the timer ref empty so
  // the next edit retries; the buffer itself can never be lost from here.
  const lastAutosavedRef = useRef<string | null>(null)
  useEffect(() => {
    if (!dirty) return
    const t = setTimeout(() => {
      if (draft === lastAutosavedRef.current) return
      api.saveDraft(projectId, docName, draft)
        .then(() => {
          lastAutosavedRef.current = draft
          // the autosave list's new entry should be there when next opened
          queryClient.invalidateQueries({ queryKey: ['ai-studio', 'draft-versions', projectId, docName] })
        })
        .catch(() => { /* next keystroke retries */ })
    }, DRAFT_DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [draft, dirty, projectId, docName, queryClient])

  const draftVersionsQuery = useQuery({
    queryKey: ['ai-studio', 'draft-versions', projectId, docName],
    queryFn: () => api.listDraftVersions(projectId, docName).then((r) => r.versions),
  })
  const versionsQuery = useQuery({
    queryKey: ['ai-studio', 'versions', projectId, docName],
    queryFn: () => api.listVersions(projectId, docName).then((r) => r.versions),
  })
  const draftVersions = draftVersionsQuery.data ?? []
  const versions = versionsQuery.data ?? []

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

  // Restore one autosave record: the buffer takes its text, which re-marks the
  // doc dirty (the autosave debounce then records the restored text as the
  // newest draft entry — the undo-the-undo stays recoverable). The committed
  // baseline does NOT move: restore is an edit, not a commit.
  const restoreDraft = useCallback((content: string) => {
    sourceRef.current = content
    if (editor && !editor.isDestroyed) {
      editor.commands.setContent(content, { contentType: 'markdown', emitUpdate: false })
    }
    setDraft(content)
    setHistoryOpen(false)
    setDiffModal(null)
  }, [editor])

  const viewingVersion = versions.find((v) => v.time === versionView) ?? null

  // The three counts below mirror the state machine the toolbar reads
  // (dirty / draft records since last commit / committed versions). They are
  // plain business observability — the same facts the icons already render,
  // readable from the DOM without simulating icon semantics.
  return (
    <div
      className="flex flex-col h-full min-h-0"
      data-testid={`doc-${docName}`}
      data-doc-dirty={dirty ? 'true' : 'false'}
      data-draft-count={draftVersions.length}
      data-version-count={versions.length}
    >
      <div className="flex items-center gap-1.5 px-4 h-[38px] shrink-0 border-b border-border">
        {/* ACP-727 layout: formatting left, the read-back trio right. The
            flex-1 spacer sits between the two groups (it used to sit before
            the format group, which is what pushed it right). */}
        {!raw && !viewingVersion && (
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
        <span className="flex-1" />
        <span className="w-px h-4 bg-border mx-1" aria-hidden />
        {/* The history trio is one addressable group: its three icons are the
         * read-backs of the draft/version model, so tests (and the demo's
         * guidance layer) ring the group, not three separate lookups. */}
        <span className="flex items-center gap-0.5" data-testid="toolbar-trio">
        <ToolbarBtn
          label={i18nT('apps.aiStudio.diff_vs_committed')}
          icon={<GitCompareArrows size={14} />}
          disabled={!dirty || !!viewingVersion}
          data-testid="diff-btn"
          onClick={() => setDiffModal({ heading: i18nT('apps.aiStudio.diff_vs_committed'), oldText: saved, newText: draftContent })}
        />
        <HistoryPopover
          open={historyOpen}
          onOpenChange={setHistoryOpen}
          disabled={draftVersions.length === 0 || !!viewingVersion}
          entries={draftVersions}
          onPick={(v) => {
            setHistoryOpen(false)
            setDiffModal({
              heading: `${i18nT('apps.aiStudio.draft_history')} · ${fmtDateTimeNumeric(v.time * 1000)}`,
              oldText: v.content,
              newText: draftContent,
              restore: () => restoreDraft(v.content),
            })
          }}
        />
        <VersionsPopover
          open={versionsOpen}
          onOpenChange={setVersionsOpen}
          disabled={versions.length === 0 || !!viewingVersion}
          entries={versions}
          onPick={(t) => { setVersionsOpen(false); setVersionView(t) }}
        />
        </span>
        {!viewingVersion && (
          <button
            type="button"
            className={`ml-1 rounded-md border border-border px-2 py-1 text-[12px] cursor-pointer transition-colors ${raw ? 'bg-bg-hover text-text' : 'text-muted hover:text-text'}`}
            aria-pressed={raw}
            data-testid="markdown-toggle"
            onClick={raw ? flipToRich : flipToRaw}
          >
            Markdown
          </button>
        )}
      </div>
      {viewingVersion ? (
        // Read-only takeover: the version's diff against its predecessor,
        // exactly what the sidebar row showed on hover-list; "back to
        // editing" (or closing the takeover) returns to the live buffer.
        <div className="flex-1 min-h-0 overflow-auto" data-testid={`version-view-${docName}`}>
          <div className="p-5 max-w-[820px]">
            <div className="flex items-center gap-3 mb-3">
              <h2 className="text-[15px] font-semibold text-text-strong">
                {i18nT('apps.aiStudio.version_diff')} · {fmtDateTimeNumeric(viewingVersion.time * 1000)}
              </h2>
              <Btn className="ml-auto" onClick={() => setVersionView(null)}>
                {i18nT('apps.aiStudio.back_to_editing')}
              </Btn>
            </div>
            <UnifiedDiffText patch={viewingVersion.diff} />
          </div>
        </div>
      ) : (
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
      )}
      <div className="px-4 py-1.5 border-t border-border text-[11px] text-muted shrink-0">
        {dirty ? i18nT('apps.aiStudio.draft_dirty') : i18nT('apps.aiStudio.draft_saved')}
      </div>
      {diffModal && <DiffDialog modal={diffModal} onClose={() => setDiffModal(null)} />}
    </div>
  )
}

// The button stays one component across its two jobs (format command vs
// history opener) and is ref-forwarding so it can sit under a Radix popover
// trigger via asChild — which is why it spreads rest props onto the DOM node.
const ToolbarBtn = forwardRef<HTMLButtonElement, {
  label: string
  icon: ReactNode
  active?: boolean
  disabled?: boolean
  onRun?: (e: Editor) => void
  run?: (fn: (e: Editor) => void) => void
  /** when present the button is a plain click (the diff button owns its own
   * action); otherwise with onRun+run it is a formatting command. Under a
   * Radix popover trigger via asChild the injected onClick lands HERE, and
   * the event must be forwarded — Radix's handler reads event.detail. */
  onClick?: (e?: React.MouseEvent<HTMLButtonElement>) => void
} & Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, 'aria-label'>>(
  function ToolbarBtn({ label, icon, active, disabled, onRun, run, onClick, ...rest }, ref) {
    const fire = (e: React.MouseEvent<HTMLButtonElement>) => {
      if (onClick) onClick(e)
      else if (onRun && run) run(onRun)
    }
    return (
      <button
        ref={ref}
        type="button"
        title={label}
        aria-label={label}
        aria-pressed={active}
        disabled={disabled}
        onClick={fire}
        className={`inline-flex items-center justify-center w-7 h-7 rounded-md transition-colors disabled:opacity-40 disabled:cursor-default ${
          active ? 'bg-bg-hover text-text' : 'text-muted hover:text-text hover:bg-bg-hover'
        }`}
        {...rest}
      >
        {icon}
      </button>
    )
  },
)

// One popover per history button. Both are Radix popovers anchored to their
// trigger (the shared ui/popover wrapper); the trigger click is the Radix
// trigger's own (asChild clones it), so the ToolbarBtn carries no handler —
// only the disabled gate. Lists render newest-first, which is what the
// backend returns for both (filename timestamps descending).
function HistoryPopover({ open, onOpenChange, disabled, entries, onPick }: {
  open: boolean
  onOpenChange: (o: boolean) => void
  disabled: boolean
  entries: StudioDraftVersion[]
  onPick: (v: StudioDraftVersion) => void
}) {
  return (
    <Popover open={disabled ? false : open} onOpenChange={onOpenChange}>
      <PopoverTrigger asChild>
        <ToolbarBtn label={i18nT('apps.aiStudio.draft_history')} icon={<History size={14} />} disabled={disabled} data-testid="draft-history-btn" />
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[320px] p-1.5">
        {entries.length === 0 ? (
          <p className="px-2 py-3 text-[12px] text-muted">{i18nT('apps.aiStudio.draft_history_empty')}</p>
        ) : (
          <div className="max-h-[320px] overflow-auto" data-testid="draft-history-list">
            {entries.map((e) => (
              <Clickable
                key={e.time}
                onClick={() => onPick(e)}
                className="block w-full text-left rounded-md px-2.5 py-2 hover:bg-bg-hover cursor-pointer"
              >
                <div className="text-[12px] text-text">{fmtDateTimeNumeric(e.time * 1000)}</div>
                <div className="text-[11px] text-muted mt-0.5 truncate">{draftSummary(e.content)}</div>
              </Clickable>
            ))}
          </div>
        )}
      </PopoverContent>
    </Popover>
  )
}

function VersionsPopover({ open, onOpenChange, disabled, entries, onPick }: {
  open: boolean
  onOpenChange: (o: boolean) => void
  disabled: boolean
  entries: StudioVersion[]
  onPick: (t: number) => void
}) {
  return (
    <Popover open={disabled ? false : open} onOpenChange={onOpenChange}>
      <PopoverTrigger asChild>
        <ToolbarBtn label={i18nT('apps.aiStudio.version_history')} icon={<GitCommit size={14} />} disabled={disabled} data-testid="version-history-btn" />
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[320px] p-1.5">
        {entries.length === 0 ? (
          <p className="px-2 py-3 text-[12px] text-muted">{i18nT('apps.aiStudio.version_history_empty')}</p>
        ) : (
          <div className="max-h-[320px] overflow-auto" data-testid="version-history-list">
            {entries.map((v) => (
              <Clickable
                key={v.time}
                onClick={() => onPick(v.time)}
                className="block w-full text-left rounded-md px-2.5 py-2 text-[12px] text-text hover:bg-bg-hover cursor-pointer"
              >
                {fmtDateTimeNumeric(v.time * 1000)}
              </Clickable>
            ))}
          </div>
        )}
      </PopoverContent>
    </Popover>
  )
}

/** First non-empty line of a draft, truncated — the row's one-line summary. */
function draftSummary(content: string): string {
  const line = content.split('\n').map((l) => l.trim()).find((l) => l.length > 0) ?? ''
  return line.length > 60 ? line.slice(0, 60) + '…' : line
}

/** The draft-history diff dialog: the chosen autosave against the current
 * buffer, plus "restore to this version" (which hands the old text back to
 * the editor and closes). */
function DiffDialog({ modal, onClose }: { modal: DiffModal; onClose: () => void }) {
  const onRestore = modal.restore
  const dialogRef = useRef<HTMLDivElement>(null)
  useDialogFocusTrap(dialogRef, onClose)
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <Clickable className="absolute inset-0 bg-bg/50" onClick={onClose} aria-label={i18nT('apps.aiStudio.close')} />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={modal.heading}
        tabIndex={-1}
        className="relative w-full max-w-[720px] max-h-[80vh] overflow-auto border border-border rounded-[14px] bg-card p-5 shadow-2xl outline-hidden"
        onKeyDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 mb-3">
          <h2 className="text-[15px] font-semibold text-text-strong">{modal.heading}</h2>
          {onRestore && (
            <Btn className="ml-auto" onClick={onRestore} data-testid="restore-version-btn">
              <RotateCcw size={13} className="lucide-inline" /> {i18nT('apps.aiStudio.restore_version')}
            </Btn>
          )}
          <button
            type="button"
            onClick={onClose}
            aria-label={i18nT('apps.aiStudio.close')}
            className="p-1.5 rounded-md text-muted hover:text-text hover:bg-bg-hover cursor-pointer bg-transparent border-0"
          >
            <X size={16} />
          </button>
        </div>
        <LineDiff oldText={modal.oldText} newText={modal.newText} />
      </div>
    </div>
  )
}
