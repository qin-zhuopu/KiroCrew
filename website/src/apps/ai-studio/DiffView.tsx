// Uncommitted-change diff for one file, from the fixture CHANGED rows. Real
// diffs come from the project's git layer later; the row shape matches what a
// unified-diff summary would give us (one added / one removed line per file).
import { i18nT } from '../../i18n/t'
import { CHANGED } from './fixtures'

export default function DiffView({ file }: { file: string }) {
  const d = CHANGED.find((x) => x.file === file)
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
