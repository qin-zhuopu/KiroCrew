# 派工单 ACP-2210（优先，今晚要用）：验收失败 →〔让助手修复〕→ 自动再验收

> 先把手上 ACP-2113 的改动提交到本分支（没做完也提交，说明里写「未完成」），再 `git merge --ff-only feature/ACP-2015-v1`（不行就 `git merge feature/ACP-2015-v1`）。
> 开工在 ACP-2210 评论「开工」，完工评论结论并置完成。一步接一步做，不停下等确认。
> **测试纪律**：只跑你新增/改的那一个测试文件；不跑全量、不跑 e2e、不开浏览器。

## 背景
「设备管理」4 个开发任务都完成了，〔跑验收〕失败（2 条单测红）。现在页面上验收失败后**没有任何出路**，用户只能干看着。

## 1. 后端 `backend/accept.py`
- 每条验收命令的**完整输出**另存 `<ws>/.ai-studio/accept/<记录id>-<序号>.log`；记录里每条结果加 `logPath`（相对工作区的路径）。`tail` 照旧 40 行。

## 2. 后端 `backend/devdag.py` + `routes.py`
- `DevRun.fix(accept_record: dict) -> dict`：前提 runState=="done" 且该记录 result=="failed"，否则 409 `nothing_to_fix`；在 nodes 末尾追加一个节点 `{"jiraKey": "fix:<n>", "title": "修复验收失败（第 n 次）", "kind": "fix", "dependsOn": [], "state": "queued"}`，runState=running，起循环（和 start 共用 `_loop`）。Jira：照普通节点在父单下建子单。
- 修复节点的提示语（`_prompt_for` 里按 kind=="fix" 分支，一字不差，<> 换掉）：
  ```
  平台验收没通过。失败的命令和完整输出在这些文件里：<逐条列出失败命令 + logPath>。
  先读这些输出，找到失败的测试，改代码让它们通过（只改代码，不许删测试、不许改测试的断言，除非测试本身和需求文档 docs/需求图谱/ 矛盾——那样要在提交说明里写清理由）。
  可以单独运行失败的那几个测试文件来确认（一次只跑一个文件），不许运行全量测试、e2e 或开发服务器。
  改完 git commit，提交说明「fix: 验收失败修复（第 <n> 次）」。最后一句只回复：完成 或 失败：<原因>。
  ```
- 修复节点 done 后自动跑一次验收（`accept.run_accept`，放线程），结果写进新记录；连续 3 次修复后仍失败 → 不再提供修复，看板显示「已修 3 次仍未通过，请人工处理」。
- 路由：`POST /projects/{id}/accept/fix`（取最新一条验收记录）。

## 3. 前端 `DevDagPanel.tsx`
- 验收结果「失败 N 条」时，下面出现〔让助手修复〕（testid `ai-studio-accept-fix-btn`）；点了调 accept/fix，看板出现修复节点并照常刷新；修复完自动出现新验收结果。超过 3 次显示上面那句原文、按钮不出现。
- 中英 + en-XA 文案。

## 4. 测试（各只跑一个文件）
- `test/test_ai_studio_accept.py` 加：完整输出落 log 文件、记录有 logPath。
- `test/test_ai_studio_devdag.py` 加：fix 在非 done/非 failed 时 409；fix 追加节点并跑、prompt 含 logPath；修复 done 后自动验收被调用；3 次上限。
- `DevDagPanel.test.tsx` 加：失败时出现按钮、点了调 fix；3 次后不出现。

## 收尾
提交 `feat(ai-studio): let the assistant fix a failed acceptance, then re-accept (ACP-2210)`，推 fork。只回复「2210 全部完成」。
