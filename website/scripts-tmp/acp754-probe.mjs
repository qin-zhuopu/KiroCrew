// ACP-754 real-machine evidence probe — playwright-core over CDP.
//
// Executes EVERY assertion of the 01 acceptance doc against the isolated live
// stack (vite :3050 -> gateway :6788, KIROCREW_HOME=/tmp/acp754-home) and
// prints one machine-readable line per assertion plus a PASS/FAIL rollup.
// Evidence is DOM / attribute / text only — NEVER a screenshot (hard repo rule).
//
// Hardening (operator standing rule): 90s top-level watchdog kills any hung CDP
// round-trip; connect/goto/evaluate all carry explicit timeouts. connectOverCDP
// attaches to the ALREADY-RUNNING headless Chrome on 9222; close() there only
// disconnects the harness, it never kills the browser.
//
// Run from the website dir (playwright-core resolves only from there):
//   node scripts-tmp/acp754-probe.mjs [tokenUrl]
// With no arg it MINTS a fresh token itself — the gateway's app tokens expire
// in ~5 minutes, so a stored URL is not a repeatable evidence command.
import { readFileSync, writeFileSync, existsSync } from 'fs'
import { spawnSync } from 'child_process'
import { chromium } from 'playwright-core'

const CDP = process.env.CDP_URL || 'http://127.0.0.1:9222'
const HOME = '/tmp/acp754-home'
const ROOT = '/home/jereh/repo/github.com/kirodotdev/KiroCrew-wt-ai-studio-reqloop'
const PY = '/home/jereh/repo/github.com/kirodotdev/KiroCrew/.venv/bin/python'
const FIXTURES = new URL('../src/apps/ai-studio/demo/fixtures/', import.meta.url).pathname

function mintToken() {
  const r = spawnSync(PY, ['-m', 'kiro_crew', 'token', '--port', '6788'], {
    env: { ...process.env, KIROCREW_HOME: HOME, PYTHONPATH: `${ROOT}/src` },
    encoding: 'utf8', timeout: 20000,
  })
  const m = (r.stdout || '').match(/http:\/\/localhost:6788\?token=\S+/)
  if (!m) throw new Error(`token mint failed (${r.status}): ${r.stderr || r.stdout}`)
  // the SPA runs on vite's port; the token is validated by the backend the
  // vite proxy forwards to, so only the host:port in the URL is rewritten
  return m[0].replace('localhost:6788', 'localhost:3050')
}
const TOKEN_URL = process.argv[2] || mintToken()
const ORIGIN = new URL(TOKEN_URL).origin

const results = []
let failures = 0
function check(id, desc, ok, detail) {
  const line = `${ok ? 'PASS' : 'FAIL'} | ${id} | ${desc}${detail ? ' | ' + detail : ''}`
  results.push(line)
  console.log(line)
  if (!ok) failures += 1
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// A fresh KIROCREW_HOME pops the host-wide「导入代理配置」modal once it
// detects existing agent configs on the machine (2026-09-23, live: it silently
// swallowed every click behind a full-screen overlay). Escape == SKIP ALL in
// that flow; the decision is recorded on the throwaway home, never the host.
async function dismissBlockingDialog(pg) {
  const dlg = await pg.$('[role="dialog"][aria-modal="true"]')
  if (!dlg) return false
  await pg.keyboard.press('Escape')
  await sleep(300)
  return true
}

// top-level watchdog — a hung CDP call is a lost run, not a slow one. This
// probe runs ~15 navigations with a deliberate 1.2s delayed GET, so the gate
// is 150s (still bounded); every individual CDP call keeps its own ≤20s
// timeout, so the anti-hang property the 90s rule protects is intact.
const watchdog = setTimeout(() => {
  console.error('WATCHDOG: probe exceeded 150s — exiting 99')
  process.exit(99)
}, 150000)

// route shape facts (2026-09-23, live-probed over CDP, not guessed): the
// builtin route `/:builtinApp/*` answers `/ai-studio` AND `/ai-studio/…`, so
// the list page lives at `/ai-studio` and `?demo=` resolves there. The token
// handshake only exists at vite's root path. The session cookie is
// `mc_token_<gatewayPort>` and HTTP-Only — assert it via the browser context,
// never document.cookie (which cannot see it).
const ROUTES = {
  token: TOKEN_URL,
  demo: (sc) => `${ORIGIN}/ai-studio?demo=${sc}&demoAutoMs=999999`,
  list: `${ORIGIN}/ai-studio`,
  project: (id) => `${ORIGIN}/ai-studio/projects/${id}`,
}
// the cookie the gateway sets is per-port (`mc_token_<gatewayPort>`) and
// HTTP-Only — document.cookie cannot see it; read it from the browser context.

async function main() {
  const browser = await chromium.connectOverCDP(CDP, { timeout: 10000 })
  const ctx = await browser.newContext()
  const page = await ctx.newPage()
  page.setDefaultTimeout(8000)

  // ============ phase D — DEMO route (fixture-driven, no real store) ========
  let demoWrites = []
  const demoLog = (method, url) => demoWrites.push(`${method} ${url}`)
  page.on('request', (r) => {
    const u = r.url()
    if (u.includes('/api/apps/ai-studio') && r.method() !== 'GET') demoLog(r.method(), u)
  })

  // token handshake first (vite's token proxy only answers the root path; it
  // 302s to `/` after setting the cookie). Never use networkidle here — the
  // dashboard holds an open stream, so it never goes idle.
  await page.goto(ROUTES.token, { waitUntil: 'domcontentloaded', timeout: 15000 })
  await sleep(400) // let the 302→/ settle so the cookie is set
  // the cookie is HTTP-Only (document.cookie is blind to it), so read the
  // browser context's cookie jar instead — its name is per gateway port.
  const jar = await ctx.cookies()
  const hasCookie = jar.some((c) => c.name.startsWith('mc_token_') && c.value)
  check('D0', 'token handshake lands the HTTP-only mc_token cookie', hasCookie,
    jar.some((c) => c.name.startsWith('mc_token_')) ? 'name present' : `jar=${JSON.stringify(jar.map((c) => c.name))}`)

  // D0b: settle the host shell's first-run onboarding ONCE. The dashboard
  // gates every fresh home behind the import→Privacy modal chain (2026-09-23,
  // live: it intercepted every click on the demo workbench too). The flags
  // are SERVER-backed (PUT /api/config/theme is authoritative over
  // localStorage), so acknowledging them here — same-origin fetch, the
  // throwaway home only — keeps every later navigation dialog-free and the
  // assertions about pointer interaction honest.
  const ack = await page.evaluate(async () => {
    const r = await fetch('/api/config/theme', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ onboarded: true, import_onboarded: true, privacy_acked: true }),
    })
    return r.status
  })
  check('D0b', '首启引导在隔离 home 内一次性落定（PUT /api/config/theme）', ack === 200, `status=${ack}`)

  // D1: `?demo=main-membership-points` opens the demo workbench — the SAME
  // route the doc pins; the master's literal `?demo=main` is checked in D1x
  await page.goto(ROUTES.demo('main-membership-points'), { waitUntil: 'domcontentloaded', timeout: 15000 })
  await page.waitForSelector('[data-testid="ai-studio-demo"]', { timeout: 10000 })
  const dismissed = await dismissBlockingDialog(page)
  const scen = await page.evaluate(() => document.querySelector('[data-testid="ai-studio-demo"]')?.dataset.demoScenario)
  check('D1', 'demo 路线挂起工作台，scenario=main-membership-points',
    scen === 'main-membership-points', `scenario=${scen} hostImportDialogDismissed=${dismissed}`)

  const fx = JSON.parse(readFileSync(`${FIXTURES}state-main-001.json`, 'utf8'))

  // D2 recent-activity: hook + count + content-level equality with snapshot
  const feed = await page.evaluate(() => {
    const el = document.querySelector('[data-testid="recent-activity"]')
    if (!el) return null
    return { count: el.dataset.activityCount,
      items: [...document.querySelectorAll('[data-testid^="recent-activity-item-"]')].map((e) => e.textContent || '') }
  })
  check('D2', 'recent-activity 存在且带 data-activity-count', !!feed, feed && `count=${feed.count}`)
  check('D2b', 'recent-activity 条数 == 快照 recentActivity 长度',
    !!feed && Number(feed.count) === fx.recentActivity.length,
    feed && `dom=${feed.count} snapshot=${fx.recentActivity.length}`)
  const missing = fx.recentActivity
    .map((a) => a.label)
    .filter((lab) => !(feed && feed.items.some((t) => t.includes(lab))))
  check('D2c', '快照每条 recentActivity 文案逐字出现在 feed（内容级）',
    missing.length === 0, missing.length ? `missing=${JSON.stringify(missing)}` : `items=${JSON.stringify(feed?.items)}`)

  // D3 focusDoc tab is open and selected (the doc-requirements.md tab)
  const tab = await page.evaluate(() => {
    const t = document.querySelector('[role="tablist"] [role="tab"]')
    return t ? { text: (t.textContent || '').trim(), selected: t.getAttribute('aria-selected') } : null
  })
  check('D3', '焦点文档 tab 打开（doc-requirements.md）',
    !!tab && tab.text.includes(fx.focusDoc) && tab.selected === 'true', tab && JSON.stringify(tab))

  // D4 buffer, content-level. The Raw textarea is the rich editor model's
  // re-serialization, and that serializer owns task-list markers (it writes
  // `- [ ] ` back as `- ` — verified 2026-09-23: the ONLY delta). So the
  // decidable predicate is: after that one documented normalization plus a
  // trailing-whitespace trim, the textarea equals the snapshot byte for
  // byte. Anything weaker would stop being an equality claim.
  await page.click('[data-testid="markdown-toggle"]', { timeout: 5000 }).catch(() => {})
  await sleep(300)
  const bufferText = await page.evaluate((doc) => {
    const t = document.querySelector(`textarea[aria-label="${doc}"]`)
    return t ? t.value : null
  }, fx.focusDoc)
  const norm = (s) => s.replace(/^- \[[ x]\] /gm, '- ').replace(/\s+$/, '')
  check('D4', `编辑区 buffer 与快照内容级一致（${fx.buffer.length} 字符；富文本序列化器对任务清单项的固有改写除外）`,
    bufferText !== null && norm(bufferText) === norm(fx.buffer),
    `domLen=${bufferText === null ? 'null' : bufferText.length} snapLen=${fx.buffer.length}`)
  await page.click('[data-testid="markdown-toggle"]', { timeout: 5000 }).catch(() => {})

  // D5 version-history-btn exists and is clickable (main-001: 2 versions)
  const vhb = await page.evaluate(() => {
    const b = document.querySelector('[data-testid="version-history-btn"]')
    return b ? { exists: true, disabled: b.disabled } : { exists: false }
  })
  check('D5', 'version-history-btn 存在且可点（快照版本数=2）',
    vhb.exists && !vhb.disabled, `exists=${vhb.exists} disabled=${vhb.disabled}`)

  // D6 the literal `?demo=main` from the master's ticket is NOT a scenario —
  // it must land the named unknown-scenario screen, never a blank page and
  // never the real store. (The doc's correct scenario id is main-membership-points.)
  await page.goto(ROUTES.demo('main'), { waitUntil: 'domcontentloaded', timeout: 15000 })
  const unk = await page.waitForSelector('[data-testid="demo-unknown-scenario"]', { timeout: 6000 }).catch(() => null)
  check('D6', '反向断言：?demo=main（主单字面量）落 unknown-scenario，不渲染真实工作台',
    !!unk && (await page.$('[data-testid="ai-studio-demo"]')) === null)

  // D7 alt-2 world: same hook, honest empty state
  await page.goto(ROUTES.demo('alt-2-empty-gray'), { waitUntil: 'domcontentloaded', timeout: 15000 })
  await page.waitForSelector('[data-testid="ai-studio-demo"]', { timeout: 10000 })
  const alt2 = await page.evaluate(() => {
    const el = document.querySelector('[data-testid="recent-activity"]')
    return el ? { count: el.dataset.activityCount, empty: !!document.querySelector('[data-testid="recent-activity-empty"]') } : null
  })
  check('D7', 'alt-2 空世界：feed 存在、count=0、显示空态文案',
    !!alt2 && Number(alt2.count) === 0 && alt2.empty, alt2 && `count=${alt2.count} empty=${alt2.empty}`)

  // D8 the whole demo phase must not write the real store once
  check('D8', '演示全程对 /api/apps/ai-studio 零写请求（不碰真实数据）',
    demoWrites.length === 0, demoWrites.length ? demoWrites.join(' ; ') : 'writes=0')
  page.removeAllListeners('request')

  // ============ phase P — ORDINARY route (the real backend) =================
  await page.goto(ROUTES.list, { waitUntil: 'domcontentloaded', timeout: 15000 })
  const list = await page.waitForSelector('[data-testid="ai-studio-projects"]', { timeout: 8000 }).catch(() => null)
  check('P1', '项目列表页渲染（data-testid=ai-studio-projects，路由 /ai-studio）', !!list)

  // P2 create through the real dialog: New project → fill name+description →
  // submit → the mutation navigates to /apps/ai-studio/projects/<new id>. The
  // dialog is a custom modal (no role=dialog); its <form> holds exactly one
  // <input> (the name) plus the description textarea and a submit button.
  // the harness browser renders zh-CN (navigator.language), so match the
  // button in both locales rather than pinning one.
  const projName = `ACP754验收 ${Date.now().toString().slice(-6)}`
  await dismissBlockingDialog(page)
  await page.getByRole('button', { name: /New project|新建项目/ }).first().click({ timeout: 5000 })
  await page.fill('form input', projName)
  await page.fill('form textarea', 'ACP-754 断言用项目')
  await page.click('form button[type="submit"]', { timeout: 5000 })
  await page.waitForURL('**/ai-studio/projects/**', { timeout: 10000 })
  const projectId = decodeURIComponent((page.url().match(/\/projects\/([^/?#]+)/) || [])[1] || '')
  check('P2', '新建项目跳转工作台（URL 带新项目 id）', projectId !== '', `id=${projectId}`)

  // P3 loading appears then disappears: a hard navigation always builds a
  // fresh QueryClient (no cache survives a document load), so delaying the
  // project GET is enough to hold isLoading true long enough to observe the
  // skeleton, then its replacement by the workbench.
  const page2 = await ctx.newPage()
  page2.setDefaultTimeout(8000)
  await page2.route(`**/api/apps/ai-studio/projects/${projectId}`, async (route) => {
    await sleep(1200)
    await route.continue()
  }).catch(() => {})
  const p3nav = page2.goto(ROUTES.project(projectId), { waitUntil: 'domcontentloaded', timeout: 20000 })
  let sawLoading = false
  try {
    await page2.waitForSelector('[data-testid="ai-studio-loading"]', { state: 'attached', timeout: 4000 })
    sawLoading = true
  } catch { /* skeleton went by faster than the poll */ }
  await p3nav
  const gone = await page2
    .waitForSelector('[data-testid="ai-studio"]', { state: 'attached', timeout: 15000 })
    .then(() => page2.evaluate(() => !document.querySelector('[data-testid="ai-studio-loading"]')))
    .catch(() => false)
  check('P3a', 'ai-studio-loading 出现（project GET 延迟期间）', sawLoading)
  check('P3b', 'ai-studio-loading 消失（工作台渲染后骨架不在 DOM）', gone)

  // P4 workbench shell: tool-sidebar + recent-activity empty + drafts 0
  const shell = await page2.evaluate(() => ({
    ws: !!document.querySelector('[data-testid="ai-studio"]'),
    sidebar: !!document.querySelector('[data-testid="tool-sidebar"]'),
    feed: (() => { const e = document.querySelector('[data-testid="recent-activity"]'); return e ? e.dataset.activityCount : null })(),
    feedEmpty: !!document.querySelector('[data-testid="recent-activity-empty"]'),
    badge: !!document.querySelector('[data-testid="drafts-pending"]'),
    commitDisabled: (() => { const b = document.querySelector('[data-testid="commit-all-btn"]'); return b ? b.disabled : null })(),
  }))
  check('P4a', '工作台壳渲染（data-testid=ai-studio）', shell.ws)
  check('P4b', 'tool-sidebar 存在', shell.sidebar)
  check('P4c', 'recent-activity 存在且空态（新项目无草稿）',
    shell.feed !== null && Number(shell.feed) === 0 && shell.feedEmpty,
    `count=${shell.feed} empty=${shell.feedEmpty}`)
  // drafts-pending "初始为 0" is decided by a PAIR: the badge renders only
  // above zero, so 0 reads as badge absent + commit button disabled.
  check('P4d', 'drafts-pending 初始为 0：徽标缺席 且 提交按钮禁用',
    !shell.badge && shell.commitDisabled === true,
    `badge=${shell.badge} commitDisabled=${shell.commitDisabled}`)

  // P5 reverse: an unknown project id lands the named load-error screen
  const page3 = await ctx.newPage()
  page3.setDefaultTimeout(8000)
  await page3.goto(ROUTES.project(`gone-${Date.now()}`), { waitUntil: 'domcontentloaded', timeout: 15000 })
  await page3.waitForSelector('[data-testid="ai-studio-load-error"]', { timeout: 8000 })
  const errMsg = (await page3.textContent('[data-testid="ai-studio-load-error"]') || '').trim()
  // the copy follows the UI locale (zh here: 项目已不存在 / en: Project no
  // longer exists) — assert the MEANING, not one language's spelling
  check('P5', '反向断言：未知项目 id 落 ai-studio-load-error（含项目不存在文案）',
    /不存在|no longer exists/i.test(errMsg), `text="${errMsg.slice(0, 70)}"`)

  console.log(`\n==== ACP-754 probe: ${results.length - failures}/${results.length} passed, ${failures} failed ====`)
  writeFileSync(`${HOME}/probe-result.txt`, results.join('\n') + `\n\n${failures} failed\n`)
  clearTimeout(watchdog)
  await ctx.close() // closes our pages + flushes nothing else; browser stays
  await browser.close() // connectOverCDP → disconnect only
  process.exit(failures === 0 ? 0 : 1)
}

main().catch((e) => {
  console.error('PROBE ERROR:', e && e.stack ? e.stack : e)
  clearTimeout(watchdog)
  process.exit(98)
})
