# ACP-2085 现场记录（S4：开始开发 → 每任务一个助手会话 → 看板 → 验收）

- `TASK.md` —— 派工单（需求与七步判据）。本单是**最小可用版**：单阶段 `full`、任务串行、
  同一工作区不开 worktree、手写调度循环而非 TaskRunner；没有 tag / 回退 / Jira 挂接。
- 落地的文件：后端 `devplan.py`（需求 → 任务清单）、`devdag.py`（调度循环 + 状态文件 +
  看板取数）、`accept.py`（跑验收 + 记录）、`routes.py` 只加本单五条路由；前端
  `DevDagPanel.tsx`（开发页签里的看板与验收区块）、`ToolSidebar.tsx` 加页签、
  `studioApi.ts` 加接口、中英与 en-XA 三份文案。

## 判据结果（单测面）

| 判据 | 怎么判的 | 结果 |
| --- | --- | --- |
| 1 需求 → 任务清单 | `test/test_ai_studio_devplan.py`：每页出 web/api 两条、标题带页名、提示词两端共用一份 | 过 |
| 2 每任务一个助手会话 + 串行 | `test/test_ai_studio_devdag.py`：slot 名序列即「哪个节点跑过」，`api` 先于 `web` | 过 |
| 3 看板看进度 | 同上 + `DevDagPanel.test.tsx`（`data-testid` 契约：节点态 / 日志 / 验收区块） | 过 |
| 4 失败不假绿、中断只补那一个 | 失败节点 `failed` + 后继留 `queued` + 本轮 `runState=failed`；中断用注入点造「会话已提交、状态未落盘」的现场，续跑后**只有那个节点被派第二次**（断的是派发次数，不是画面） | 过 |
| 5 〔信任会话〕等价 | `grant_trust` 对齐 `dashboard/chat_handlers.api_chat_mode` 的 `mode == "trust"` 分支：同会话的 slot 一起打旗 + 一次 `set_approval_policy(key,"auto")` + SEL 审计；测试直接比对该分支的动作序列 | 过（坑见填坑笔记） |
| 6 跑验收 | `test/test_ai_studio_accept.py`：DAG 未全绿拒跑、逐条断言结果、通过/失败都不假绿 | 过 |
| 7 提交并推 fork | 见本单提交 | 过 |

## 门禁里三条**不是我造成**的红（合并时别再查一遍）

对照面是主检出 `main`（`2bbdb2540`），命令与输出都在下面：

- `test/test_error_code_contract.py` —— `routes.py: dynamic_status 0 -> 1`。
  报的是 `_handle_publish_trigger` 里那行 `status=200 if result.get("idempotent") else 201`
  （ACP-2060 之前就在了，本单没碰那个函数）。在 `main` 上跑同一条测试报**同一个文件同一个
  bucket**，行号从 274 被本单改动推到 284 —— 数字差是行号，不是计数。
- `scripts/check_subprocess_encoding.py` —— `devruns.py` 里 `_run_gate` 的
  `subprocess.run` 缺 `encoding=`。`git blame` 指到 `2bbdb25407`（2026-09-27），
  本单没碰这个文件。
- 前端门禁两处：`npm run build` 红在 `DevServerControl.tsx` 的 `StudioApiError`
  导入未使用（`git status` 显示该文件本单未改，HEAD 里就是这个样子）；`npm run test` 的
  `pretest` 是 `jscpd .`，阈值 0% 而 `main` 全仓实测 1197 个 clone / 0.82% 重复行，
  本单只加了两个 tsx 文件，`pretest` 就红在阈值上，vitest 根本没跑到。所以本单的前端
  测试是**直接 `npx vitest run`** 验的（`DevDagPanel` + `AiStudioPage` 共 33 例全过）。
  i18n 门禁按 `I18N_BASE_REF=<本单父提交>` 跑，19 项里 18 过，唯一红的
  `manifest-sync`（ai-studio manifest 的 7 个键不在 `locales/en.json`）在 `main` 上
  单独跑 `check-app-manifest-sync.mjs` 输出一模一样。

## 真跑（端到端）留给 master

本单没有自己的网关与前端服务，全程只做单测。合进 `feature/ACP-2015-v1` 之后请按
`docs/guides/worktree-verification-recipes.md` 起一个隔离网关验这四条：点〔开始开发〕→
看板节点逐个翻状态 → 中途杀网关再看看板（应判失败并给出「网关重启，中断」，续跑只补那一个）
→ 全绿后点〔执行验收〕出逐条结果。
