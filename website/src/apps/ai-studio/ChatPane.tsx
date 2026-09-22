// The studio's left column: the native Kiro Crew chat, embedded frameless.
// slotKey is stable per project so a refresh returns to the same transcript,
// and two projects never share one chat (the workbench context IS the
// project once projects exist).
//
// The slot is opened up-front, not left to the first send: ChatEmbed's
// history read (`GET /api/chat/slots/{key}`) 404s on a slot that does not
// exist yet, and the embed renders that as an error bar — a brand-new
// workspace would open on "could not load messages". `POST /api/chat/slots`
// is the established precedent (design-critique, design-tweak do the same):
// with an explicit `name` it is idempotent — an already-open slot is handed
// back unchanged — and a slot minted under the app token is stamped
// `_app = 'ai-studio'`, which is what keeps this app's later GETs past the
// cross-app deny. ChatEmbed mounts only once the open settles so its first
// GET does not race the create; a failed open still mounts it, where its
// own retry stands.
import { useEffect, useState } from 'react'
import { useAppApi } from '../../app-sdk'
import ChatEmbed from '../../app-sdk/ChatEmbed'
import { i18nT } from '../../i18n/t'

export default function ChatPane({ slotKey }: { slotKey: string }) {
  const api = useAppApi()
  const [settledKey, setSettledKey] = useState<string | null>(null)
  useEffect(() => {
    // keyed on slotKey: switching projects inside a mounted pane re-runs the
    // open for the new slot before the embed mounts against it.
    let cancelled = false
    setSettledKey(null)
    api
      .post('/api/chat/slots', { name: slotKey, title: 'AI Studio' })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setSettledKey(slotKey)
      })
    return () => {
      cancelled = true
    }
  }, [api, slotKey])
  return (
    <div className="flex-1 min-h-0 flex flex-col" data-testid="ai-studio-chat">
      <div className="px-3 h-[38px] shrink-0 flex items-center border-b border-border text-[13px] font-semibold text-text-strong">
        {i18nT('apps.aiStudio.chat_title')}
      </div>
      <div className="flex-1 min-h-0 flex flex-col p-2">
        {settledKey === slotKey ? (
          <ChatEmbed
            key={slotKey}
            slotKey={slotKey}
            placeholder={i18nT('apps.aiStudio.chat_placeholder')}
            frameless
            startAtBottom
          />
        ) : null}
      </div>
    </div>
  )
}
