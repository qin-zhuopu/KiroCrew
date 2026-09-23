// A historical commit: message, timestamp, and per-file diff summary. Files
// with a current pending change reuse the same added/removed pair the commit
// introduced (fixture simplification — real history will carry its own hunks).
import { i18nT } from '../../i18n/t'
import { CHANGED, COMMITS } from './fixtures'

export default function CommitView({ commitId }: { commitId: string }) {
  const c = COMMITS.find((x) => x.id === commitId)
  if (!c) return null
  return (
    <div className="p-5 max-w-[820px]" data-testid={`commit-${c.id}`}>
      <h1 className="text-[15px] font-semibold text-text-strong">{i18nT('apps.aiStudio.commit')} {c.id}</h1>
      <p className="text-[13px] text-text mt-2">{c.message}</p>
      <p className="text-[11px] text-muted mt-1">{c.time}</p>
      <h2 className="text-[13px] font-semibold text-text-strong mt-4 mb-1">{i18nT('apps.aiStudio.diff_title')}</h2>
      {c.files.map((f) => {
        const d = CHANGED.find((x) => x.file === f)
        return (
          <div key={f} className="mb-3">
            <h3 className="text-[13px] font-medium text-text">{f}</h3>
            {d ? (
              <>
                <div className="rounded-md px-2.5 py-1.5 my-1 text-[12px] font-mono bg-danger-subtle text-danger">{d.removed}</div>
                <div className="rounded-md px-2.5 py-1.5 my-1 text-[12px] font-mono bg-accent-subtle text-accent">{d.added}</div>
              </>
            ) : (
              <p className="text-[12px] text-muted mt-1">{i18nT('apps.aiStudio.historical_diff_demo')}</p>
            )}
          </div>
        )
      })}
    </div>
  )
}
