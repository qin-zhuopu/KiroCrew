/**
 * ACP-2222: every operation of the AI Studio user journey carries a stable
 * `data-testid`, and this file is what stops one from quietly disappearing.
 *
 * Why a static source check instead of rendering: the journey is 14 steps long
 * and spans seven right-hand tabs, a dialog, three approval buttons and the
 * chat composer. Rendering every owner of every id to prove the id exists would
 * mean standing up every one of those screens with its fixtures — and the suite
 * already does that, per component, where it matters. What the suite does NOT do
 * is hold the CONTRACT: nothing anywhere said "the deploy button is called
 * `prod-server-deploy`", so a rename inside one component passed its own test
 * (which was updated in the same commit) and broke the journey script, the
 * smoke run and the实战 walkthrough that read the id from the browser. A string
 * check over the source is the cheapest thing that pins the name itself.
 *
 * Two known blind spots, both accepted:
 *  - it checks the id is written, not that it renders. The per-component tests
 *    cover rendering; a testid that is written into an unreachable branch is a
 *    different bug than the one this guards, and it is caught by its own test.
 *  - a computed id (`data-testid={`x-${t}`}`) is invisible to it. That is why
 *    `TOOL_TESTIDS` in ToolSidebar spells its seven ids out key by key, and why
 *    there is a wiring assertion below: a map the JSX never reads is caught there.
 *
 * If you renamed an id on purpose: update BOTH this table and
 * `docs/request-for-change/rfc-ai-studio-req-flow-final-journey.md` (the third
 * assertion here checks they still agree — the doc is what the human walkthrough
 * is read from).
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { TOOL_TESTIDS } from './ToolSidebar'

// `new URL('..', import.meta.url).pathname` is a URL path, not a filesystem
// path — resolve through fileURLToPath so the walk does not depend on cwd.
const HERE = dirname(fileURLToPath(import.meta.url))
// website/ — HERE is website/src/apps/ai-studio, so three levels up.
const WEBSITE = resolve(HERE, '..', '..', '..')
// repo root (the RFC lives here, outside website/)
const REPO = resolve(WEBSITE, '..')

/** One operation of the journey, and the testid handle it is clicked by.
 *  A trailing `-` means "prefix": the control exists once per row/task/version,
 *  so the source carries `data-testid={`project-delete-${…}`}` and a script
 *  matches `[data-testid^="project-delete-"]`. */
interface JourneyId {
  /** the journey step, as the RFC numbers it — this is what a failure names */
  step: string
  id: string
  /** true when the source builds the id per item, so only the prefix is literal */
  perItem?: boolean
}

const JOURNEY: JourneyId[] = [
  // 1-3 工作区列表与卡片
  { step: '工作区列表', id: 'ai-studio-projects' },
  { step: '新建工作区：对话框', id: 'new-ws-dialog' },
  { step: '新建工作区：名称', id: 'new-ws-name' },
  { step: '新建工作区：代号', id: 'new-ws-code' },
  { step: '新建工作区：提交', id: 'new-ws-submit' },
  { step: '新建工作区：每步', id: 'new-ws-step-', perItem: true },
  { step: '新建工作区：重试', id: 'new-ws-retry' },
  { step: '新建工作区：日志', id: 'new-ws-log' },
  { step: '新建工作区：进入', id: 'new-ws-enter' },
  { step: '卡片：状态', id: 'project-status-', perItem: true },
  { step: '卡片：开发网址', id: 'project-dev-url' },
  { step: '卡片：删除', id: 'project-delete-', perItem: true },
  // 4 开发服务器
  { step: '开发服务器：启停', id: 'dev-server-toggle' },
  { step: '开发服务器：网址', id: 'dev-server-url' },
  { step: '开发服务器：日志', id: 'dev-server-log-toggle' },
  // 5 右栏页签 —— 7 个页签统一命名，2 个历史名保留
  { step: '右栏页签：需求', id: 'ai-studio-tool-requirements' },
  { step: '右栏页签：文档', id: 'ai-studio-tool-docs' },
  { step: '右栏页签：提交', id: 'ai-studio-tool-commits' },
  { step: '右栏页签：发布', id: 'ai-studio-tool-releases' },
  { step: '右栏页签：图谱', id: 'ai-studio-tool-graph' },
  { step: '右栏页签：开发', id: 'ai-studio-tool-dev' },
  { step: '右栏页签：部署', id: 'ai-studio-tool-deploy' },
  { step: '右栏页签：发布入口（历史名）', id: 'ai-studio-publish-entry' },
  { step: '右栏页签：开发入口（历史名）', id: 'ai-studio-dev-entry' },
  // 6-7 需求
  { step: '需求：列表行', id: 'req-row-', perItem: true },
  // 判定条 exists twice and never as a bare `req-verdict`: `req-verdict-bar`
  // (the strip above the open page) and `req-verdict-${page}` (each row's
  // colour). A script reaches either with [data-testid^="req-verdict"], which is
  // exactly what a prefix entry means — so it is declared as one, not as an
  // exact id it never was.
  { step: '需求：判定条', id: 'req-verdict', perItem: true },
  { step: '需求：保存', id: 'req-save-btn' },
  { step: '需求：开始开发', id: 'req-start-btn' },
  // 6 聊需求（含第一次写文件时的批准卡片）
  { step: '聊需求：提示', id: 'req-session-tip' },
  { step: '聊需求：输入', id: 'chat-input' },
  { step: '聊需求：发送', id: 'chat-send' },
  { step: '批准卡片：容器', id: 'approval-card' },
  { step: '批准卡片：批准', id: 'approval-approve' },
  { step: '批准卡片：信任会话', id: 'approval-trust' },
  { step: '批准卡片：拒绝', id: 'approval-reject' },
  // 8-9 开发
  { step: '开发：拆分', id: 'ai-studio-dev-plan-btn' },
  { step: '开发：开始', id: 'ai-studio-dev-start-btn' },
  { step: '开发：确认', id: 'ai-studio-dev-confirm' },
  { step: '开发：任务行', id: 'ai-studio-dev-dag-node-', perItem: true },
  { step: '开发：任务行 Jira', id: 'ai-studio-dev-dag-node-jira-', perItem: true },
  { step: '开发：日志', id: 'ai-studio-dev-dag-log' },
  // 10 验收
  { step: '验收：跑', id: 'ai-studio-accept-run-btn' },
  { step: '验收：结果', id: 'ai-studio-accept-status' },
  { step: '验收：让助手修复', id: 'ai-studio-accept-fix-btn' },
  // 11 部署
  { step: '部署：部署', id: 'prod-server-deploy' },
  { step: '部署：停止', id: 'prod-server-stop' },
  { step: '部署：网址', id: 'prod-server-url' },
  { step: '部署：版本', id: 'prod-server-version' },
  { step: '部署：日志', id: 'prod-server-log-toggle' },
]

/** The files a journey id is allowed to live in, per the task spec: the app's
 *  own components plus the two shared ones the journey walks through.
 *  Excluded on purpose:
 *   - `*.test.tsx` — a test naming an id proves nothing about the product.
 *   - `demo/` — the guided-tour overlay and its stubs carry their own
 *     `demo-*` ids and stub ChatEmbed out entirely
 *     (`states-release.test.tsx` renders a `chat-embed-stub`), so letting the
 *     overlay tree answer for a real control would be a false green. */
function journeySources(): Map<string, string> {
  const out = new Map<string, string>()
  const add = (abs: string) => {
    out.set(rel(abs), readFileSync(abs, 'utf8'))
  }
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const full = join(dir, name)
      if (statSync(full).isDirectory()) {
        if (name !== 'demo') walk(full)
        continue
      }
      if (!name.endsWith('.tsx') || name.includes('.test.')) continue
      add(full)
    }
  }
  walk(join(WEBSITE, 'src', 'apps', 'ai-studio'))
  // `components/ApprovalCard.tsx` is named by the task; `TrustDropdown.tsx` is
  // where 〔信任会话〕 actually renders (the card passes the id down as a prop),
  // so the union has to include it or the guard would fail on correct code.
  add(join(WEBSITE, 'src', 'components', 'ApprovalCard.tsx'))
  add(join(WEBSITE, 'src', 'components', 'TrustDropdown.tsx'))
  add(join(WEBSITE, 'src', 'app-sdk', 'ChatEmbed.tsx'))
  return out
}

const rel = (abs: string) => abs.slice(WEBSITE.length + 1)

const SOURCES = journeySources()

/** Where a declared id was found, and how it reaches the DOM.
 *  `attr` is the ordinary case. The other two are the two places a handle is
 *  written as DATA and then spread onto an element in a loop or through a prop —
 *  forms a purely attribute-scoped scan cannot see, and which a computed
 *  `data-testid={…}` cannot be blamed for missing. Each is paired with an
 *  assertion below that the carrier actually reaches the DOM, so the pair proves
 *  what `attr` proves on its own; the `via` label is printed on failure. */
interface DeclaredId {
  file: string
  id: string
  via: 'attr' | 'tab-map' | 'testId-prop'
}

/** Every id a source file declares, in every supported form.
 *  Attribute-scoped where possible rather than a bare substring search, so a
 *  comment that merely mentions an id cannot satisfy the guard for a control
 *  that lost it. */
function declaredIds(file: string, source: string): DeclaredId[] {
  const found: DeclaredId[] = []
  const push = (id: string, via: DeclaredId['via']) => found.push({ file, id, via })
  const collect = (re: RegExp, via: DeclaredId['via']) => {
    let m: RegExpExecArray | null
    while ((m = re.exec(source)) !== null) {
      const raw = m.slice(1).find(s => s !== undefined)
      if (raw !== undefined) push(raw, via)
    }
  }
  // `data-testid="x"`, `data-testid={'x'}`, `data-testid={`x-${…}`}`,
  // and the `data-tool` twin of the same attribute.
  collect(
    /data-(?:testid|tool)\s*=\s*(?:"([^"]*)"|'([^']*)'|`([^`]*)`|\{\s*(?:`([^`]*)`|"([^"]*)"|'([^']*)'))/g,
    'attr',
  )
  // Object literals whose entries ARE the ids, spread onto elements in a loop.
  // Wiring is asserted in the describe block below.
  for (const carrier of TAB_ID_CARRIERS) {
    const block = objectLiteral(source, carrier)
    if (!block) continue
    let m: RegExpExecArray | null
    const re = /:\s*'([^']*)'/g
    while ((m = re.exec(block)) !== null) push(m[1], 'tab-map')
  }
  // `testId="x"` on a component that renders it as the attribute (wired below).
  collect(/\btestId=\{?"([^"]*)"\}?/g, 'testId-prop')
  return found
}

/** Names of the object literals in this directory that carry tab handles. */
const TAB_ID_CARRIERS = ['TOOL_TESTIDS', 'TOOL_LEGACY_TESTIDS']

/** The `{ … }` text of the object literal assigned to `name`, or null.
 *  Brace-matched rather than regex'd because a nested object would otherwise
 *  end the match early. */
function objectLiteral(source: string, name: string): string | null {
  const decl = new RegExp(`${name}[^=]*=`).exec(source)
  if (!decl) return null
  const open = source.indexOf('{', decl.index)
  if (open < 0) return null
  let depth = 0
  for (let i = open; i < source.length; i++) {
    if (source[i] === '{') depth++
    else if (source[i] === '}' && --depth === 0) return source.slice(open, i)
  }
  return null
}

const ALL_IDS: DeclaredId[] = [...SOURCES.entries()].flatMap(([file, src]) =>
  declaredIds(file, src),
)

describe('AI Studio journey testids (ACP-2222)', () => {
  it('the corpus is loaded (an empty scan would pass every assertion below)', () => {
    // The whole guard fails toward green if the walk ever resolves to nothing —
    // a path change or a moved directory. Prove it is looking at real files.
    expect(SOURCES.size).toBeGreaterThan(20)
    expect(ALL_IDS.length).toBeGreaterThan(100)
    for (const must of [
      'src/apps/ai-studio/ToolSidebar.tsx',
      'src/components/ApprovalCard.tsx',
      'src/components/TrustDropdown.tsx',
      'src/app-sdk/ChatEmbed.tsx',
    ]) {
      expect(SOURCES.has(must), must).toBe(true)
    }
  })

  for (const { step, id, perItem } of JOURNEY) {
    it(`${step} → ${id}`, () => {
      // Prefix ids are written as `data-testid={`new-ws-step-${i}`}`, so the
      // literal in source ENDS with the prefix and continues into the template.
      const hits = ALL_IDS.filter(h =>
        perItem ? h.id.startsWith(id) : h.id === id,
      )
      expect(
        hits.map(h => `${h.file} → ${h.id} (${h.via})`),
        `${step}: 没有任何组件把 "${id}"${perItem ? '（前缀）' : ''} 声明成 testid。` +
          '改名的话三处要一起改：组件、本表、RFC 的「每个操作的 testid」一节。',
      ).not.toHaveLength(0)
    })
  }
})

describe('the tab handles are wired, not merely declared', () => {
  it('TOOL_TESTIDS spells out one ai-studio-tool-<key> per tab', () => {
    // Importing the map is what proves the tabs and the ids cannot drift: the
    // key set is typed against `Tool`, so a tab added to the sidebar with no
    // handle here is a type error, and a handle no tab uses fails here.
    expect(Object.keys(TOOL_TESTIDS).sort()).toEqual([
      'commits',
      'deploy',
      'dev',
      'docs',
      'graph',
      'releases',
      'requirements',
    ])
    for (const [key, id] of Object.entries(TOOL_TESTIDS)) {
      expect(id, key).toBe(`ai-studio-tool-${key}`)
    }
  })

  it('the tab button reads the map (a declared id the JSX never renders is no handle)', () => {
    const src = SOURCES.get('src/apps/ai-studio/ToolSidebar.tsx') ?? ''
    expect(src).toMatch(/data-tool=\{\s*TOOL_TESTIDS\[t\]\s*\}/)
    expect(src).toMatch(/data-testid=\{\s*TOOL_LEGACY_TESTIDS\[t\]\s*\?\?\s*TOOL_TESTIDS\[t\]\s*\}/)
  })

  it('the two legacy tab ids stay reachable, and 〔信任会话〕 reaches the dropdown by prop', () => {
    // A wrapper element would satisfy a presence check while making
    // `getByTestId('ai-studio-dev-entry')` return something whose
    // `aria-selected` belongs to no tab (DevDagPanel.test.tsx asserts on it).
    const sidebar = SOURCES.get('src/apps/ai-studio/ToolSidebar.tsx') ?? ''
    expect(sidebar).toContain("releases: 'ai-studio-publish-entry'")
    expect(sidebar).toContain("dev: 'ai-studio-dev-entry'")
    // The card owns the name; TrustDropdown is what renders it, on BOTH of its
    // shapes (single-tier plain button and multi-tier dropdown trigger).
    const card = SOURCES.get('src/components/ApprovalCard.tsx') ?? ''
    expect(card).toContain('testId="approval-trust"')
    const dropdown = SOURCES.get('src/components/TrustDropdown.tsx') ?? ''
    expect(
      [...dropdown.matchAll(/data-testid=\{\s*testId\s*\}/g)].length,
      'TrustDropdown 的两种形态（单档按钮 / 下拉触发器）都要渲染 testId',
    ).toBe(2)
  })
})

describe('the RFC carries the same table', () => {
  const RFC = 'docs/request-for-change/rfc-ai-studio-req-flow-final-journey.md'

  it('every id in the table is documented for the human walkthrough', () => {
    // The doc is outside website/ (precedent: src/test/decisionStripContract.test.ts
    // pins itself to docs/system-specs the same way). The walkthrough is read off
    // this table, so a table that drifted from the code sends a human to a
    // button that does not exist.
    const text = readFileSync(join(REPO, RFC), 'utf8')
    const section = text.slice(text.indexOf('每个操作的 testid'))
    expect(section, `RFC 里要有「每个操作的 testid」一节`).not.toBe(text)
    const missing = JOURNEY.filter(({ id }) => !section.includes(id)).map(
      ({ step, id }) => `${step} → ${id}`,
    )
    expect(missing, 'RFC 的 testid 一节缺这些（与测试表不一致）').toEqual([])
  })
})
