// A deployment run's log. Static fixture text for the demo deploy; the real
// version will stream from the workflow/task-runner log endpoint.
import { DEPLOYMENTS } from './fixtures'

export default function DeployLog({ deployId }: { deployId: string }) {
  const d = DEPLOYMENTS.find((x) => x.id === deployId)
  if (!d) return null
  const lines = [
    '[11:20:01] Started by AI Studio',
    '[11:20:02] Checkout source... OK',
    '[11:20:05] npm ci... OK',
    '[11:20:12] npm run build... OK',
    '[11:20:18] Building container image... OK',
    `[11:20:25] Deploying to ${d.env}...`,
    '[11:20:31] Health check /api/health... 200 OK',
    `[11:20:34] Deployment ${d.id} is RUNNING`,
  ]
  return (
    <div className="p-5 max-w-[820px]" data-testid={`deploy-log-${d.id}`}>
      <h1 className="text-[15px] font-semibold text-text-strong">{d.id}</h1>
      <p className="text-[12px] text-muted mt-1">{d.env} · {d.version}</p>
      <pre className="mt-3 rounded-lg bg-bg-elevated border border-border font-mono text-[12px] leading-6 p-4 whitespace-pre-wrap overflow-auto text-muted">
        {lines.join('\n')}
      </pre>
    </div>
  )
}
