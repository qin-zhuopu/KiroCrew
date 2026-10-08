# 派工单 ACP-2085-S2：网页里跟写需求助手聊（需求会话）+ 图谱一变页面自动刷新

> 需求依据：`docs/request-for-change/rfc-ai-studio-req-flow.md` §7 B3/B4、§8 左栏一行、§9.3（含 V1 结论和三条实测边界）、§10 验收 5~8。先通读。
> 调研结论（master 已查实，照用）：
> - 工作区里**不要**放 `.claude/settings.local.json`（放了 Crew 就整份扣住工具不发，见 `providers/mirrors/claude_code.py:229-241`）。新模板已经不带它。
> - 写文件要人批准是故意的安全设计。**不许**加自动放行、不许 bypass、不许 yolo。界面上告诉用户点一次〔信任会话〕即可（ChatEmbed 里已有 Approve / Trust / Reject，`components/ApprovalCard.tsx`）。
> - 会话**不能**标成后台会话（`slot.unattended` 为真时批准 180 秒就超时拒绝，见 `dashboard/state.py:5658-5675`）。需求会话是前台会话。
> - 开会话照抄 `apps/builtins/spec_builder/backend/runtime.py`：`_ensure_worker_slot`（:543-675，`state.get_or_create_slot(name=..., app=APP_NAME)`、设 `slot.project`、`slot.model`）、标题写法（`handlers.py:862-866`）、发一轮 `_dispatch_turn`（:1539-1612）。
> 每完成一步说「N 完成：<判据结果>」。卡住超过 10 分钟停下贴报错原文。开工先在 ACP-2085 下建子任务（标签 sid-kc-v1）。

## 地盘

和上一单一样：工作目录 `/home/jereh/repo/github.com/kirodotdev/KiroCrew-wt-kc-v1`，分支 `feature/ACP-2015-v1`，网关 6790（gw 窗口，改 Python 要重启）、vite 6791、域名 `https://kc-v1-14409-dev.gb10.jereh-pe.cn/`。
只许改/新增：`backend/reqsession.py`（新）、`backend/routes.py`、`test/test_ai_studio_reqsession.py`（新）、`website/src/apps/ai-studio/ChatPane.tsx`、`RequirementsTool.tsx`、`RequirementPage.tsx`、`studioApi.ts`、它们的 `.test.tsx`、i18n 中英两份。
不许推 origin、不许 --no-verify。

## 1. 后端 `backend/reqsession.py`

```python
SLOT_PREFIX = "ai-studio-req-"
def slot_key(project_id: str) -> str: ...            # "ai-studio-req-<id>"
def first_prompt(project: dict, ws: Path) -> str:
    """返回这段话（一字不差，<> 换成值）：
    你在工作区「<项目名>」（目录 <ws>）。先完整读 .claude/agents/requirement-writer.md，之后完全按它工作。
    需求图谱放 docs/需求图谱/，需求标准在 docs/需求标准/。现在先问我这次要做什么页面。
    ws 下没有 .claude/agents/requirement-writer.md 时，把第二句换成：工作区里没有写需求助手的说明，请告诉用户「这个工作区缺少写需求助手，请联系管理员」。"""
async def ensure_req_session(state, project: dict, ws: Path) -> dict:
    """幂等。照 spec_builder `_ensure_worker_slot`：get_or_create_slot(name=slot_key(id), app="ai-studio")，
    slot.project=str(ws)，slot.title=f"需求：{项目名}"（并 push_slot_title），不设 unattended。
    第一次创建时（判据：项目记录里没有 reqSessionStarted）用 _dispatch_turn 照 spec_builder 发 first_prompt，
    然后 projects.update_project(id, reqSessionStarted=True)（没有 update_project 就在本文件写一个：读 project.json 合并字段原子写回）。
    返回 {"slotKey": ..., "created": bool}。"""
```

## 2. 路由

`POST /projects/{id}/req-session` → `ensure_req_session`，返回 200 `{slotKey, created}`。项目不存在 404；`workspaceDir` 不存在 409 `workspace_missing`。

## 3. 后端测试 `test/test_ai_studio_reqsession.py`

用替身 state（记录 get_or_create_slot 调用、slot 对象可写属性）和替身 dispatch，不起真会话：
1. `slot_key("sbgl") == "ai-studio-req-sbgl"`。
2. 第一次：slot.project = 工作区目录、title = 「需求：<名>」、`unattended` 没被设成 True、dispatch 被调一次且消息 = first_prompt。
3. 第二次调用：不再 dispatch，返回同一 slotKey，created=False。
4. 工作区没有 requirement-writer.md 时 first_prompt 含「这个工作区缺少写需求助手」。
5. 路由：项目不存在 404；工作区目录不存在 409。

## 4. 前端

- `ChatPane.tsx`：挂 ChatEmbed 前先 `studioApi.ensureReqSession(projectId)` 拿 slotKey，用它挂（不再自己建 slot）。拿到之前显示「正在连接写需求助手…」；失败显示错误原文 + 〔重试〕。
  会话上方一条提示（testid `req-session-tip`）：「助手要写需求文件时会请你批准。点一次〔信任会话〕，它就能自己写，不用每次点。」
- `RequirementsTool.tsx`：每 5 秒重新拉列表；某页 graphHash 变了，徽标和时间跟着变。
- `RequirementPage.tsx`：每 5 秒拉本页；graphHash 变了就重新渲染文档和判定条，刷新期间判定条显示「生成中…」。
- testid 已有的不改。新文案中英两份。
- 测试：ChatPane 先调 ensureReqSession 再挂 ChatEmbed（用 mock 断言顺序）、失败显示重试；RequirementPage 用假计时器推 5 秒、第二次返回新 hash 时判定条从「需求已齐，可以开发」变成「不齐：还不能开发」。
- 判据：`npx vitest run src/apps/ai-studio/` 全过；`npx tsc --noEmit -p .` 无输出。

## 5. 真跑（必须做，结果原样写进报告）

1. 重启网关，浏览器（或你已有的探针脚本）打开 `https://kc-v1-14409-dev.gb10.jereh-pe.cn/workspaces/p261008-151745/ai-studio`。
2. 左栏应出现助手的第一句（它读了 requirement-writer.md，开始问你要做什么页面）。截图存 `docs/task-specs/2026/10/ACP-2085-req-session/shot-1.png`。
3. 在聊天里发：「加一页：设备分类。字段只有 分类编码、分类名称、备注。其它都按你的建议。」照它问题回答（全部选它的建议项），直到它说要写文件。
4. 出现批准卡片时点〔信任会话〕。之后它应自己写出 `docs/需求图谱/设备分类.json`。
5. 判据：10 秒内右栏「需求」列表出现「设备分类」；打开它判定条有颜色；`jc fe reqdoc check` 那个文件的结果与界面一致。截图 `shot-2.png`。
6. 跑不通就停在那一步，把屏幕原文/网关日志相关行贴出来，不要绕。

## 6. 收尾

只 stage 本单文件；提交 `feat(ai-studio): requirement session in the chat pane + live graph refresh (ACP-2085)`；推 fork。报告：提交号、各判据结果、第 5 步原文、没做到的事。
