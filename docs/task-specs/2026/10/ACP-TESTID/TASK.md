# 派工单：用户全流程每个操作都要有 testid（做完 ACP-2219 接着做）

> Jira：ACP-2085 下「[testid]」开头的子单。开工评论「开工」，完工评论并置完成。不停下等确认。
> **测试纪律**：只跑你新增/改的测试文件（每次一个）。

master 盘点了 `docs/request-for-change/rfc-ai-studio-req-flow-final-journey.md` 全流程 14 步的每个操作，缺这些：

1. **右栏页签**（`ToolSidebar.tsx` 约 296 行）：现在只有 `releases`、`dev` 两个页签有 testid。给每个页签都加：`ai-studio-tool-<key>`（key = requirements / docs / commits / releases / graph / dev / deploy）；已有的 `ai-studio-publish-entry`、`ai-studio-dev-entry` **保留**（老测试和实战脚本在用），新 id 加在外层或用 `data-testid` + `data-tool` 两个属性都行，但两个旧 id 必须还能找到。
2. **批准卡片**（`website/src/components/ApprovalCard.tsx`）：〔批准〕〔信任会话〕〔拒绝〕按钮加 `approval-approve`、`approval-trust`、`approval-reject`（卡片容器 `approval-card`）。
3. **聊天输入**：确认 `ChatEmbed` 的输入框和发送按钮有稳定 testid（没有就加 `chat-input`、`chat-send`）。
4. **防退化测试**：新建 `website/src/apps/ai-studio/journeyTestids.test.ts`：列出全流程每个操作的 testid（见下表），逐个断言在 `website/src/apps/ai-studio/**/*.tsx` 或 `components/ApprovalCard.tsx` / `app-sdk/ChatEmbed.tsx` 的源码里出现（读文件做字符串检查即可，不渲染）。以后谁删了 testid 这个测试就红。

| 操作 | testid |
|---|---|
| 工作区列表 | ai-studio-projects |
| 新建工作区：对话框/名称/代号/提交/每步/重试/日志/进入 | new-ws-dialog / new-ws-name / new-ws-code / new-ws-submit / new-ws-step- / new-ws-retry / new-ws-log / new-ws-enter |
| 卡片：状态/开发网址/删除 | project-status- / project-dev-url / project-delete- |
| 开发服务器：启停/网址/日志 | dev-server-toggle / dev-server-url / dev-server-log-toggle |
| 右栏页签 | ai-studio-tool-requirements … ai-studio-tool-deploy、ai-studio-dev-entry、ai-studio-publish-entry |
| 需求：列表行/判定条/保存/开始开发 | req-row- / req-verdict / req-save-btn / req-start-btn |
| 聊需求：提示/输入/发送/信任会话 | req-session-tip / chat-input / chat-send / approval-trust |
| 开发：拆分/开始/确认/任务行/Jira/日志 | ai-studio-dev-plan-btn / ai-studio-dev-start-btn / ai-studio-dev-confirm / ai-studio-dev-dag-node- / ai-studio-dev-dag-node-jira- / ai-studio-dev-dag-log |
| 验收：跑/结果/让助手修复 | ai-studio-accept-run-btn / ai-studio-accept-status / ai-studio-accept-fix-btn |
| 部署：部署/停止/网址/版本/日志 | prod-server-deploy / prod-server-stop / prod-server-url / prod-server-version / prod-server-log-toggle |

5. 把这张表追加进 `docs/request-for-change/rfc-ai-studio-req-flow-final-journey.md` 末尾一节「每个操作的 testid」。

提交 `test(ai-studio): every journey step has a stable testid, with a regression guard`，推 fork。只回复「testid 全部完成」。
