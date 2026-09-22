// Diff rendering for the workbench. The default export keeps the fixture mode
// (the Commits tab): `file` looks the row up in CHANGED — the same added/
// removed pair a unified-diff summary would give us. The named exports render
// the editor's real diffs (ACP-722): LineDiff compares two Markdown buffers
// line by line with the `diff` package (the chat tool-diff's library), and
// UnifiedDiffText colours a unified-diff STRING as the version API returns it
// (the backend computes it with difflib; prefix determines colour).
import { diffLines } from 'diff'
import { i18nT } from '../../i18n/t'
import { CHANGED } from './fixtures'

export default function DiffView({ file }: { file?: string }) {
  const d = file ? CHANGED.find((x) => x.file === file) : undefined
  if (!d) return null
  return (
    <div className="p-5 max-w-[820px]" data-testid={`diff-${file}`}>
      <h1 className="text-[15px] font-semibold text-text-strong mb-3">
        {file} · {i18nT('apps.aiStudio.diff_title')}
      </h1>
      <div className="rounded-md px-2.5 py-1.5 my-1 text-[12px] font-mono bg-danger-subtle text-danger">{d.removed}</div>
      <div className="rounded-md px-2.5 py-1.5 my-1 text-[12px] font-mono bg-accent-subtle text-accent">{d.added}</div>
    </div>
  )
}

/** Colour a unified-diff STRING (what GET …/versions carries per entry, the
    backend's difflib output): +/- lines red/green, @@ hunk headers and the
    ---/+++ file headers muted-small, everything else context. */
export function UnifiedDiffText({ patch }: { patch: string }) {
  const lines = patch.replace(/\n$/, '').split('\n')
  if (lines.every((l) => !l.startsWith('+') && !l.startsWith('-'))) {
    return <p className="text-[12px] text-muted">{i18nT('apps.aiStudio.diff_no_change')}</p>
  }
  return (
    <div className="text-[12px] font-mono leading-5 whitespace-pre-wrap break-words">
      {lines.map((l, i) => {
        let cls = 'text-muted px-2.5 py-0.5'
        if (l.startsWith('+++') || l.startsWith('---') || l.startsWith('@@')) {
          cls = 'text-muted opacity-70 px-2.5 py-0.5'
        } else if (l.startsWith('+')) {
          cls = 'rounded-sm bg-accent-subtle text-accent px-2.5 py-0.5'
        } else if (l.startsWith('-')) {
          cls = 'rounded-sm bg-danger-subtle text-danger px-2.5 py-0.5'
        }
        return <div key={i} className={cls}>{l || ' '}</div>
      })}
    </div>
  )
}

/** Line-by-line diff of two Markdown buffers. Removed chunks red, added
    chunks green, unchanged lines muted; a chunk with no change renders as one
    summary line so a long document stays scannable. */
export function LineDiff({ oldText, newText }: { oldText: string; newText: string }) {
  const parts = diffLines(oldText, newText)
  const hasChange = parts.some((p) => p.added || p.removed)
  if (!hasChange) {
    return <p className="text-[12px] text-muted">{i18nT('apps.aiStudio.diff_no_change')}</p>
  }
  return (
    <div className="text-[12px] font-mono leading-5 whitespace-pre-wrap break-words">
      {parts.map((p, i) => {
        const lines = p.value.replace(/\n$/, '').split('\n')
        if (!p.added && !p.removed) {
          // Collapse runs of unchanged text to their first line + a count,
          // matching how a unified diff elides context.
          if (lines.length > 2) {
            return (
              <div key={i} className="text-muted px-2.5 py-1">
                {lines[0]}
                <span className="opacity-60"> … {lines.length - 2} </span>
                {lines[lines.length - 1]}
              </div>
            )
          }
          return lines.map((l, j) => (
            <div key={`${i}:${j}`} className="text-muted px-2.5 py-0.5">{l || ' '}</div>
          ))
        }
        const cls = p.added
          ? 'bg-accent-subtle text-accent'
          : 'bg-danger-subtle text-danger'
        return lines.map((l, j) => (
          <div key={`${i}:${j}`} className={`rounded-sm px-2.5 py-0.5 ${cls}`}>
            {`${p.added ? '+' : '-'} ${l}`}
          </div>
        ))
      })}
    </div>
  )
}
