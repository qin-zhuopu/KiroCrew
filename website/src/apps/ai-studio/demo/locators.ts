// Named UI positions the demo script talks to, and the acts the guidance
// layer performs on the business page (§4: opening a panel is the overlay's
// job, not the step's). The script names a locator — `draft_history_btn`,
// `version_row:newest` — never a CSS selector, so a class rename inside the
// business components cannot silently rot a script: the lookup fails loudly
// (the overlay logs and the script test fails at 引导落位) instead of
// highlighting the wrong pixel.
//
// Everything here reads the business components' test hooks (data-testid) —
// the same contract vitest uses — and acts through plain DOM clicks / the
// native value setter, i.e. exactly what a user's click and typing produce
// for React. No business component imports anything from this file.

/** What a locator's `act` may need from the runtime beyond the element. */
export interface LocatorCtx {
  /** the focused doc's buffer in the CURRENT step's snapshot — what the
   * `set_buffer` act types into the Raw view */
  buffer: string
  /** the buffer the PREVIOUS step landed on, when the current step's event
   * is itself a live act (alt1-6 "restore" types the pre-restore buffer
   * first, then presses the real Restore button on top of it) */
  prevBuffer?: string
}

export interface DemoLocator {
  /** resolve against the document; null = not (yet) present, the open
   * sequence retries until the business DOM settles */
  find: (arg: string | undefined, ctx: LocatorCtx) => HTMLElement | null
  /** what the overlay DOES with it; defaults to a plain click */
  act?: (el: HTMLElement, arg: string | undefined, ctx: LocatorCtx) => void
}

const byTestid = (id: string) => document.querySelector<HTMLElement>(`[data-testid="${id}"]`)

export function clickEl(el: HTMLElement): void {
  // pointer/mouse sequence mirrors a real press; a bare .click() is what
  // Radix's trigger reads event.detail for, so send the detail=1 gesture.
  el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, cancelable: true, pointerId: 1, isPrimary: true, button: 0 }))
  el.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, cancelable: true, pointerId: 1, isPrimary: true, button: 0 }))
  el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, detail: 1, button: 0 }))
}

/** Programmatic typing through the path React owns: the prototype value
 * setter (bypassing React's tracked value) plus the bubbling `input` event —
 * the same two moves testing-library's userEvent makes. The demo types the
 * snapshot's buffer text, never a fabricated string (§5). */
export function typeInto(textarea: HTMLElement, text: string): void {
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set
  if (setter) setter.call(textarea, text)
  else (textarea as HTMLTextAreaElement).value = text
  textarea.dispatchEvent(new Event('input', { bubbles: true }))
}

function editorTextarea(): HTMLTextAreaElement | null {
  return document.querySelector<HTMLTextAreaElement>('textarea[aria-label$=".md"]')
}

/** Rows of one open history popover, newest first (the API's order). */
function popoverRows(testid: string, arg?: string): HTMLElement | null {
  const list = byTestid(testid)
  if (!list) return null
  const rows = Array.from(list.querySelectorAll<HTMLElement>('[role="button"]'))
  if (rows.length === 0) return null
  if (arg === 'oldest') return rows[rows.length - 1]
  if (arg === 'older' && rows.length > 1) return rows[1]
  return rows[0] // newest (also the default)
}

export const LOCATORS: Record<string, DemoLocator> = {
  // toolbar trio and its parts
  diff_btn: { find: () => byTestid('diff-btn') },
  draft_history_btn: { find: () => byTestid('draft-history-btn') },
  versions_btn: { find: () => byTestid('version-history-btn') },
  // ACP-727 moved the commit to the project top bar. The button renders
  // disabled until the drafts read lands, and a synthetic click FIRES on a
  // disabled button (dispatchEvent bypasses the user-interaction guard)
  // while commitAll's own `draftDocs.length === 0` check would silently
  // no-op — so the locator waits for the enabled state before clicking.
  commit_all_btn: {
    find: () => {
      const el = byTestid('commit-all-btn')
      return el && !el.hasAttribute('disabled') ? el : null
    },
  },
  // the top bar's commit summary: which docs the click would promote
  commit_summary: { find: () => byTestid('drafts-pending') },
  markdown_toggle: { find: () => byTestid('markdown-toggle') },

  // editor / takeover bodies (targets to ring, not to click)
  doc_editor: { find: () => document.querySelector<HTMLElement>('[data-testid^="doc-"]') },
  version_view: { find: () => document.querySelector<HTMLElement>('[data-testid^="version-view-"]') },
  toolbar_trio: { find: () => byTestid('toolbar-trio') },
  diff_dialog: { find: () => document.querySelector<HTMLElement>('[role="dialog"][aria-modal="true"]') },
  draft_history_list: { find: () => byTestid('draft-history-list') },
  version_history_list: { find: () => byTestid('version-history-list') },

  // the requirement-graph panel (ACP-729): rendered by the demo workbench
  // from the snapshot's graph; the script rings it and the added nodes it
  // highlights are the snapshot diff, not a claim
  graph_view: { find: () => byTestid('graph-view') },
  // the release cut + generated-code panel (ACP-730), same snapshot-driven
  // doctrine; the release button waits for its enabled state like
  // commit_all_btn (a synthetic click on a disabled button fires but no-ops)
  release_btn: {
    find: () => {
      const el = byTestid('release-btn')
      return el && !el.hasAttribute('disabled') ? el : null
    },
  },
  codegen_view: { find: () => byTestid('codegen-view') },

  // row picks inside an open popover / dialog
  version_row: { find: (arg) => popoverRows('version-history-list', arg) },
  draft_row: { find: (arg) => popoverRows('draft-history-list', arg) },
  restore_btn: {
    find: () => document.querySelector<HTMLElement>('[data-testid="restore-version-btn"]'),
  },

  // the replayed keystrokes: flip to Raw if needed, then type the snapshot
  // buffer (main-4 "user appended two lines" lands through the real editor
  // path — dirty, footer, diff icon all flip as a consequence of real state)
  set_buffer: {
    find: (_arg, ctx) => (ctx.buffer ? editorTextarea() : null),
    act: (el, _arg, ctx) => typeInto(el, ctx.buffer),
  },
  // type the PREVIOUS step's buffer — for steps whose event happens live on
  // top of the prior state (alt1-6's restore): the buffer is set to where
  // the story stood, then the real Restore button moves it from there
  set_before_buffer: {
    find: (_arg, ctx) => (ctx.prevBuffer !== undefined ? editorTextarea() : null),
    act: (el, _arg, ctx) => typeInto(el, ctx.prevBuffer ?? ''),
  },
}

/** Resolve one script locator (`key` or `key:arg`). */
export function resolveLocator(
  spec: string,
  ctx: LocatorCtx,
): { el: HTMLElement; locator: DemoLocator } | null {
  const [key, arg] = spec.split(':')
  const locator = LOCATORS[key]
  if (!locator) {
    // A script naming a locator nobody implements is a broken script, not a
    // missing element — say so in the console for the human watching.
    console.warn(`[ai-studio demo] unknown locator "${key}"`)
    return null
  }
  const el = locator.find(arg, ctx)
  return el ? { el, locator } : null
}
