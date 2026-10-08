// The studio's left column: 本工作区的需求会话（ACP-2085 S2，RFC §9.3）。
//
// The slot used to be minted here (`POST /api/chat/slots` with a browser-chosen
// name). That is why the assistant could never write a requirement graph: a
// slot the browser named has no `project`, so the agent's shell started in the
// GATEWAY's directory and every approved write landed outside the workspace.
// `POST /projects/{id}/req-session` now opens the session, scopes it at the
// workspace and sends the opening prompt; this component only mounts onto the
// key it hands back.
//
// A failed open is an error with a 〔重试〕, never a silent mount: the honest
// reading of "we could not get a session" is that the column cannot talk to
// anything, and mounting an embed on a guessed key would look identical to a
// working session while reading a transcript that has nothing to do with this
// workspace.
import { useCallback, useEffect, useState } from 'react'
import ErrorNotice from '../../components/ErrorNotice'
import { Btn } from '../../components/ui'
import { i18nT } from '../../i18n/t'
import ChatEmbed from '../../app-sdk/ChatEmbed'
import { studioApi, type StudioApi } from './studioApi'

export default function ChatPane({ projectId, api = studioApi }: {
  /** the workspace whose 需求会话 this column is; also the session's key */
  projectId: string
  /** data source, injectable for the demo's snapshot fake */
  api?: StudioApi
}) {
  const [settled, setSettled] = useState<{ slotKey: string } | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  // bumping this re-runs the open; the open itself is not a callback of it, so
  // a retry is one click even when the error text is identical
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    // keyed on projectId: switching workspaces inside a mounted pane must drop
    // the previous workspace's session before the new one resolves, or the
    // first frame would show project A's transcript under project B's title.
    let cancelled = false
    setSettled(null)
    setFailure(null)
    api
      .ensureReqSession(projectId)
      .then((r) => {
        if (cancelled) return
        // A response without a key is a failure, not an empty session: mounting
        // the embed on `undefined` reads SOME slot's transcript and shows it
        // under this project's title, which is the failure mode this whole
        // change exists to remove. So it takes the error branch.
        const key = typeof r?.slotKey === 'string' ? r.slotKey : ''
        if (!key) setFailure(i18nT('apps.aiStudio.req_session_no_key'))
        else setSettled({ slotKey: key })
      })
      .catch((e: unknown) => {
        if (!cancelled) setFailure(e instanceof Error ? e.message : String(e))
      })
    return () => {
      cancelled = true
    }
  }, [api, projectId, attempt])

  const retry = useCallback(() => setAttempt((n) => n + 1), [])

  return (
    <div className="flex-1 min-h-0 flex flex-col" data-testid="ai-studio-chat">
      <div className="px-3 h-[38px] shrink-0 flex items-center border-b border-border text-[13px] font-semibold text-text-strong">
        {i18nT('apps.aiStudio.chat_title')}
      </div>
      {/* 写文件要人批准是安全设计，不是 bug：批准卡片就在下面的会话里，点一次
          〔信任 → 信任本会话的所有工具〕就不再每次问。不许为它加自动放行。 */}
      <div
        data-testid="req-session-tip"
        className="shrink-0 px-3 py-1.5 text-[11px] leading-relaxed text-muted border-b border-border bg-bg-elevated"
      >
        {i18nT('apps.aiStudio.req_session_tip')}
      </div>
      <div className="flex-1 min-h-0 flex flex-col p-2">
        {failure !== null && (
          <div data-testid="req-session-error" className="flex flex-col gap-2">
            <ErrorNotice message={failure} />
            <div>
              <Btn data-testid="req-session-retry" onClick={retry}>
                {i18nT('apps.aiStudio.req_session_retry')}
              </Btn>
            </div>
          </div>
        )}
        {failure === null && settled === null && (
          <div data-testid="req-session-connecting" className="text-[12px] text-muted px-1 py-2">
            {i18nT('apps.aiStudio.req_session_connecting')}
          </div>
        )}
        {settled !== null ? (
          <ChatEmbed
            key={settled.slotKey}
            slotKey={settled.slotKey}
            placeholder={i18nT('apps.aiStudio.chat_placeholder')}
            frameless
            startAtBottom
          />
        ) : null}
      </div>
    </div>
  )
}

