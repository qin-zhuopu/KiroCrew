// The requirement freeze (ACP-755 / 00 doc 需求冻结): mark a graph version
// immutable as this round's sole baseline. The rule has two halves and this
// component is only the visible one: the HARD rejection of re-freezing the
// same version (409) lives in the data layer (the demo fake's
// freezeBaseline); the UI shows the same fact as data — a disabled button
// once a baseline exists (00 doc: 再次冻结按钮变为不可用) and a duplicate
// hint on the frozen record — so the greying-out is the display of the rule,
// never the enforcement of it.
//
// Both surfaces ride the same seam as ReleaseControl: the demo workbench
// offers the button only where its after-fix snapshot carries the freeze
// payload (no step offers a click that lands on nothing), the confirm is a
// real dialog the user reads the version in, and the callback lands the
// declared snapshot. A frozen frame renders the button disabled with the
// duplicate message as its title — the button stays visible so the frozen
// state reads as "the action exists and is refused", not "the action is
// gone".
import { useRef, useState } from 'react'
import { Snowflake } from 'lucide-react'
import Clickable from '../../components/Clickable'
import { useDialogFocusTrap } from '../../hooks/useDialogFocusTrap'
import { Btn } from '../../components/ui'
import { i18nT } from '../../i18n/t'
import type { StudioFreeze } from './studioApi'

export default function FreezeControl({ onFreeze, frozen, version }: {
  /** performs the freeze; the frame switches when this resolves. Absent on
   * a frame whose baseline already exists — the button is then the frozen
   * state's disabled witness, clickable by nobody */
  onFreeze?: () => Promise<void>
  /** the frame's existing baseline, when one is frozen */
  frozen?: StudioFreeze
  /** the version the confirm dialog names (this round's newest regen row) */
  version?: string
}) {
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [pending, setPending] = useState(false)
  const disabled = frozen !== undefined || onFreeze === undefined || pending

  const confirm = async () => {
    if (!onFreeze || pending) return
    setPending(true)
    try {
      await onFreeze()
      setConfirmOpen(false)
    } finally {
      setPending(false)
    }
  }

  return (
    <>
      <Btn
        // a click on the offered button opens the confirmation — freezing an
        // entire round's baseline on one click is exactly the mistake the
        // confirm exists to prevent (00 doc: 用户=点需求冻结、确认版本)
        onClick={onFreeze ? () => setConfirmOpen(true) : undefined}
        disabled={disabled}
        data-testid="freeze-btn"
        data-freeze-frozen={frozen ? 'true' : 'false'}
        title={
          frozen
            ? i18nT('apps.aiStudio.freeze_duplicate', { version: frozen.version })
            : i18nT('apps.aiStudio.freeze_hint')
        }
      >
        <Snowflake size={13} className="lucide-inline" />
        {i18nT('apps.aiStudio.freeze')}
      </Btn>
      {confirmOpen && (
        <FreezeConfirmDialog
          version={version ?? frozen?.version ?? ''}
          pending={pending}
          onCancel={() => setConfirmOpen(false)}
          onConfirm={confirm}
        />
      )}
    </>
  )
}

// The confirm as its own component so the focus trap mounts and unmounts
// with the dialog (the trap's open/close focus juggling is per-mount work).
function FreezeConfirmDialog({ version, pending, onCancel, onConfirm }: {
  version: string
  pending: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  const dialogRef = useRef<HTMLDivElement>(null)
  useDialogFocusTrap(dialogRef, onCancel)
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <Clickable className="absolute inset-0 bg-bg/50" onClick={onCancel} aria-label={i18nT('apps.aiStudio.close')} />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={i18nT('apps.aiStudio.freeze_confirm_title')}
        tabIndex={-1}
        className="relative w-full max-w-[420px] border border-border rounded-[14px] bg-card p-5 shadow-2xl outline-hidden"
        onKeyDown={(e) => e.stopPropagation()}
      >
        <h2 className="text-[15px] font-semibold text-text-strong mb-2">
          {i18nT('apps.aiStudio.freeze_confirm_title')}
        </h2>
        <p className="text-[13px] leading-6 text-text">
          {i18nT('apps.aiStudio.freeze_confirm_body', { version })}
        </p>
        <div className="mt-4 flex items-center justify-end gap-2">
          <Btn onClick={onCancel}>{i18nT('apps.aiStudio.freeze_confirm_cancel')}</Btn>
          <Btn onClick={onConfirm} disabled={pending} data-testid="freeze-confirm">
            <Snowflake size={13} className="lucide-inline" />
            {i18nT('apps.aiStudio.freeze_confirm_ok')}
          </Btn>
        </div>
      </div>
    </div>
  )
}

/** The frozen baseline as the frame's own record (00 doc: 用户看到基线版本号、
 * 冻结说明、不可变标识). Pure props — it displays what the snapshot's freeze
 * record holds, and the duplicate line states the rule the data layer
 * enforces: same-version re-freeze is refused, visibly and permanently. */
export function FreezeRecordView({ freeze }: { freeze: StudioFreeze }) {
  return (
    <div data-testid="freeze-record" data-frozen-version={freeze.version} className="p-3 flex flex-col gap-1.5">
      <div className="flex items-center gap-2 text-[12px]">
        <Snowflake size={13} className="text-accent shrink-0" />
        <span
          data-testid={`freeze-badge-${freeze.version}`}
          className="rounded-full bg-accent-subtle px-2 py-0.5 text-[11px] font-semibold text-accent"
        >
          {i18nT('apps.aiStudio.freeze_badge', { version: freeze.version })}
        </span>
        <span className="text-[11px] text-muted">{new Date(freeze.time * 1000).toLocaleString()}</span>
      </div>
      <div className="text-[12px] text-text">{freeze.notes}</div>
      <div data-testid="freeze-duplicate-hint" className="text-[11px] text-muted">
        {i18nT('apps.aiStudio.freeze_duplicate', { version: freeze.version })}
      </div>
    </div>
  )
}
