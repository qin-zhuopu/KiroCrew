// 左栏 = 本工作区的需求会话（ACP-2085 S2，RFC §9.3）。这些用例钉的是顺序与失败
// 形态：先问后端要 slotKey，拿到之后才挂 ChatEmbed —— 顺序反过来（或干脆自己编
// 一个 key）就是这次改动要修的那个 bug：浏览器自己命名的 slot 没有 `project`，
// 助手的 shell 在网关目录里跑，写出来的需求文件落在工作区外面。
//
// ChatEmbed 是桩（真组件会开 WebSocket）。UI 字符串断言英文目录（测试钉 en），
// 错误原文是后端的，按原文断言。
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const ensureReqSession = vi.hoisted(() => vi.fn())
vi.mock('./studioApi', async () => {
  const actual = await vi.importActual('./studioApi')
  return { ...actual, studioApi: { ensureReqSession } }
})
// the embed's own surface is not this unit: it opens a WebSocket and reads the
// transcript, neither of which the pane controls. The stub records the key it
// was mounted with, which IS the contract under test.
const mountedKeys: string[] = []
vi.mock('../../app-sdk/ChatEmbed', () => ({
  default: ({ slotKey }: { slotKey: string }) => {
    mountedKeys.push(slotKey)
    return <div data-testid="chat-embed-stub" data-slot={slotKey} />
  },
}))

import ChatPane from './ChatPane'
import { StudioApiError } from './studioApi'
import { renderStudio } from './testUtils'

beforeEach(() => {
  ensureReqSession.mockReset()
  mountedKeys.length = 0
  ensureReqSession.mockResolvedValue({ slotKey: 'ai-studio-req-p1', created: true })
})

describe('ChatPane', () => {
  it('asks the backend for the session, and only then mounts the embed on its key', async () => {
    let resolveWith: (v: { slotKey: string; created: boolean }) => void = () => {}
    ensureReqSession.mockReturnValue(
      new Promise((r) => {
        resolveWith = r
      })
    )
    renderStudio(<ChatPane projectId="p1" />)

    // the key has not arrived: the column says so and mounts NOTHING. Mounting
    // a guessed key here is the bug — it reads some other session's transcript.
    expect(ensureReqSession).toHaveBeenCalledWith('p1')
    expect(screen.getByTestId('req-session-connecting')).toBeInTheDocument()
    expect(screen.queryByTestId('chat-embed-stub')).not.toBeInTheDocument()

    resolveWith({ slotKey: 'ai-studio-req-p1', created: true })
    const stub = await screen.findByTestId('chat-embed-stub')
    expect(stub).toHaveAttribute('data-slot', 'ai-studio-req-p1')
    expect(mountedKeys).toEqual(['ai-studio-req-p1'])
  })

  it('carries the 〔信任会话〕 tip above the conversation', async () => {
    renderStudio(<ChatPane projectId="p1" />)
    const tip = await screen.findByTestId('req-session-tip')
    expect(tip).toHaveTextContent('Click 〔Trust session〕 once')
    // the tip is not a one-shot banner: it must survive the session opening
    await screen.findByTestId('chat-embed-stub')
    expect(screen.getByTestId('req-session-tip')).toBeInTheDocument()
  })

  it('a failed open shows the backend error verbatim and a 〔重试〕 that asks again', async () => {
    const user = userEvent.setup()
    ensureReqSession.mockRejectedValue(
      new StudioApiError(409, 'workspace_missing', 'workspace directory is missing: /tmp/ws'),
    )
    renderStudio(<ChatPane projectId="p1" />)

    const box = await screen.findByTestId('req-session-error')
    // 原文照抄，不改写：409 的话是「工作区目录没了」，改成人话就丢掉了路径
    expect(box).toHaveTextContent('workspace directory is missing: /tmp/ws')
    expect(screen.queryByTestId('chat-embed-stub')).not.toBeInTheDocument()

    ensureReqSession.mockResolvedValue({ slotKey: 'ai-studio-req-p1', created: false })
    await user.click(screen.getByTestId('req-session-retry'))
    await waitFor(() => expect(ensureReqSession).toHaveBeenCalledTimes(2))
    expect(await screen.findByTestId('chat-embed-stub')).toBeInTheDocument()
    expect(screen.queryByTestId('req-session-error')).not.toBeInTheDocument()
  })

  it('an open that answers no key is an error, not an empty session', async () => {
    // ChatEmbed mounted on `undefined` does not render nothing — it falls back to
    // the dashboard's own slot and shows SOME transcript under this project's
    // title. That is precisely the failure this change removes, so a key-less 200
    // (a proxy that swallowed the body, a backend that forgot the field) has to
    // take the error branch instead.
    ensureReqSession.mockResolvedValue({ created: true } as unknown as { slotKey: string; created: boolean })
    renderStudio(<ChatPane projectId="p1" />)
    const box = await screen.findByTestId('req-session-error')
    expect(box).toHaveTextContent('opened no requirement session')
    expect(mountedKeys).toEqual([])
  })

  it('switching project re-opens for the new id and mounts only the new key', async () => {
    // the key is derived backend-side from the id, so re-running the open per id
    // is what keeps project B from showing project A's transcript. Asserted
    // through the mount log rather than the DOM: the old stub unmounts as the
    // new open starts, and which of two stubs a query sees first is a race.
    const { rerender } = renderStudio(<ChatPane projectId="p1" />)
    await waitFor(() => expect(mountedKeys).toEqual(['ai-studio-req-p1']))
    ensureReqSession.mockResolvedValue({ slotKey: 'ai-studio-req-p2', created: true })

    rerender(<ChatPane projectId="p2" />)
    await waitFor(() => expect(mountedKeys).toEqual(['ai-studio-req-p1', 'ai-studio-req-p2']))
    expect(ensureReqSession).toHaveBeenLastCalledWith('p2')
  })
})
