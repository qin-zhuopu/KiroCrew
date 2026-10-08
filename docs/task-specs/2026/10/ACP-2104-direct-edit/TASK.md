# 派工单 ACP-2104（S3）：需求页直接改文档 + 〔开始开发〕

> 需求依据：`docs/request-for-change/rfc-ai-studio-req-flow.md` §7 B5/B6、§8 文案、§9.4 `direct-edit` 与 `start` 两行、§10 验收 9~12。先通读。
> 开工先在 ACP-2104 上评论「开工」（它已是 ACP-2085 的子任务，标签 sid-master，你不用另建），完工置完成。
> 每完成一步说「N 完成：<判据结果>」。不要停下来等确认，一步接一步做完。卡住超过 10 分钟停下贴报错原文。

## 地盘

同上一单（kc-v1 工作区、网关 6790、vite 6791）。本分支刚合进了 kc-ws 的「新建工作区」改动，先 `git log --oneline -5` 看一眼。
只许改/新增：`backend/requirements.py`、`backend/reqsession.py`（只加发消息的函数）、`backend/routes.py`、`test/test_ai_studio_requirements.py`、`website/src/apps/ai-studio/RequirementPage.tsx`（及 .test）、`studioApi.ts`、i18n 中英两份。
不许推 origin、不许 --no-verify。

## 1. 后端：直改

`requirements.py` 加：
```python
def doc_hash(markdown: str) -> str            # sha256 前 16 位
def direct_edit(ws: Path, page: str, base_doc_hash: str, markdown: str) -> dict:
    """当前文档（get_page 的 markdown）doc_hash != base_doc_hash → RequirementError("文档已被别人改过，请刷新","doc_changed",409)。
    算 unified diff（旧 → 新，difflib，n=2）；diff 为空 → 返回 {"changed": False}。
    把 {"at", "baseDocHash", "diff"} 追加到 <ws>/.ai-studio/direct-edits.jsonl。
    返回 {"changed": True, "diff": diff, "pending": True}。"""
```
`get_page` 的返回加 `docHash`；如果 `direct-edits.jsonl` 里最后一条的时间晚于图谱文件 mtime → 返回 `"pendingEdit": True`，否则 False。
`reqsession.py` 加 `async def send_to_req_session(state, project, ws, text)`：会话已存在就照 `_dispatch_turn` 发一条消息（会话忙会自动排队）。
路由 `POST /projects/{id}/requirements/{page}/direct-edit` body `{baseDocHash, markdown}`：调 direct_edit；changed 时发给需求会话这段话：
```
用户在网页上直接改了需求页「<页名>」的文档，改动如下（diff）。请把这些改动落回 docs/需求图谱/<页名>.json，落不进去的地方问我。
<diff 原文>
```
返回 200 结果；409 原样返回。

## 2. 后端：开始开发（只做「记开工请求」，拆任务由别的单做）

`requirements.py` 加 `start(ws, page, graph_hash) -> dict`：
- 当场重跑 check；当前 graphHash != 传入 → `RequirementError("需求刚刚变了","graph_changed",409)`；
- 判定是「不齐」→ `RequirementError("需求不齐","not_ready",422)`，并把 verdict、missing 放进错误响应体；
- 否则追加一行 `{"at","page","graphHash","verdict"}` 到 `<ws>/.ai-studio/start-requests.jsonl`，返回 `{"ok":True,"page","graphHash","verdict"}`。
`get_page` 的 `devState`：start-requests 里本页最后一条的 graphHash == 当前 → `"started"`；有记录但 hash 不同 → `"editing"` 且加 `"changedAfterStart": True`；没记录 → `"editing"`。
路由 `POST /projects/{id}/requirements/{page}/start` body `{graphHash}`。

## 3. 测试（`test/test_ai_studio_requirements.py` 里加）

1. direct_edit：hash 对 → changed、jsonl 多一行；hash 旧 → 409；内容没变 → changed False。
2. pendingEdit：写 jsonl 后为 True；之后 touch 图谱文件 → False。
3. start：合格 → 200 且 jsonl 多一行、graphHash 对；hash 旧 → 409 graph_changed；不齐图谱 → 422 not_ready 且响应带 missing。
4. devState：start 后 started；改图谱后 editing + changedAfterStart。
5. 路由 direct-edit 成功时 send_to_req_session 被调一次（替身），消息含 diff。

## 4. 前端 `RequirementPage.tsx`

- DocEditor 改成可编辑；右上加〔保存〕（testid `req-save-btn`），没改动时置灰。点了调 direct-edit（带 docHash）。409 → 提示「文档已被别人改过，请刷新」+〔刷新〕。
- `pendingEdit` 为真时判定条显示「改动待落回需求」（黄），〔开始开发〕置灰。
- 〔开始开发〕（testid `req-start-btn`）：判定「不齐」时置灰，悬停提示「还不能开发：<第一条缺口>」；「可以开工但有已知缺口」时先弹确认「这页有 N 处已知缺口，开发会按统一做法先落。确定开始？」；「全齐」直接调。
  - 调 `start`（带 graphHash）：200 → 页面显示「已开工请求，等待拆任务」，并 `window.dispatchEvent(new CustomEvent('ai-studio:start-dev', { detail: { projectId, page } }))`（开发页签会听这个事件，由别的单接）。
  - 409 → 「需求刚刚变了，判定为不齐，请先补齐」并立刻重拉本页；422 → 同样文案。
  - `devState=started` 时按钮显示「已开工」置灰；`changedAfterStart` 时提示「需求改了，要重新点开始开发」，按钮恢复可点。
- 文案照 RFC §8 原文，中英两份。
- 测试：保存调 direct-edit 带 docHash；409 显示原文；不齐时开始按钮置灰且有提示；有缺口先弹确认；成功后显示「已开工请求，等待拆任务」且派发了 ai-studio:start-dev 事件；changedAfterStart 提示出现。
- 判据：`cd website && npx vitest run src/apps/ai-studio/` 全过；`npx tsc --noEmit -p .` 无输出；`.venv/bin/python -m pytest test/test_ai_studio_*.py -q` 全过。

## 5. 真跑

重启网关。用浏览器打开演示项目的「设备分类」需求页：改一句备注文字 → 保存 → 判定条变「改动待落回需求」→ 左栏需求会话收到改动消息（截图 `shot-1.png`）→ 等助手落回后判定条恢复；点〔开始开发〕→ 显示「已开工请求，等待拆任务」（`shot-2.png`），`start-requests.jsonl` 多一行（贴出来）。

## 6. 收尾

**需求文档随代码一起提交**（负责人 2026-10-09 追加）：本功能自身的需求 + 验收文档落在 webapp-template 仓的 `docs/需求图谱/`，格式照仓里已有的需求图谱（v34 图谱 JSON 是事实源，同名 `.md` 由 `jc fe reqdoc render` 生成，不手写）：

- `docs/需求图谱/ai-studio-requirement-direct-edit.json`
- `docs/需求图谱/ai-studio-requirement-direct-edit.md`

文件名用英文（本机硬约定：禁止中文文件名；内容与仓里已有的 `设备分类.json` 等一样照旧，不改名）。判定用 `jc fe reqdoc check <json>` 验：本次结论是「可以开工但有已知缺口」，唯一缺口是零件可达一档的 `MarkdownSourceEditor`（框架组件池里确实没有「可编辑的 Markdown 正文区」这个零件，如实登记为缺口，不假装全齐）。这份文档在模板仓，**连模板仓的代码一起提交并推模板仓的 origin**，不进 KiroCrew 的提交。

KiroCrew 侧：只 stage 本单文件；提交 `feat(ai-studio): direct-edit the requirement doc and request start (ACP-2104)`；推 fork；Jira ACP-2104 评论结论 + 置完成。最后只回复「ACP-2104 全部完成」。
