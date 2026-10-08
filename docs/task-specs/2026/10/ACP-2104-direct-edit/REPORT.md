# ACP-2104（S3）结束报告（会话 kc-v1）

判据原文在 `TASK.md`。这份报告只放**结果与证据**，第 5 步的证据全部是文本（DOM 状态行、
服务端账本行、会话 transcript），截图只当交付物落盘 —— 本机硬约定禁止把图片喂给模型，
所以每张图下面都另有一份可读的证据。

## 提交

一个提交（at most two per PR，本单只有一个逻辑变更）：

- 后端 `requirements.py`（直改/开工/两套哈希/pendingEdit/devState）、`reqsession.py`
  （只加发消息的 `send_to_req_session`）、`routes.py`（两个新路由）
- 后端测试 `test/test_ai_studio_requirements.py`（35 passed）
- 前端 `RequirementPage.tsx`（+22 用例）、`studioApi.ts`、i18n `en` / `zh-CN` / `en-XA`
- 本 `REPORT.md` + `shot-1.png` / `shot-2.png`
- 填坑笔记 `docs/pitfall-notes/20261009-032851-ai-studio-live-run-silent-blockers.md` + README 索引

需求文档不在本提交里：它在 webapp-template 仓，见下面「第 6 步」。

## 各判据结果

| 判据 | 命令 | 结果 |
|---|---|---|
| 前端单测 | `cd website && npx vitest run src/apps/ai-studio/` | 25 files / **269 passed**，exit=0 |
| 类型 | `cd website && npx tsc --noEmit -p .` | 无输出，exit=0 |
| 后端单测 | `.venv/bin/python -m pytest test/test_ai_studio_*.py -q` | 35 passed（本单文件）/ 216 passed（ai_studio 全部 11 个文件），exit=0 |
| 格式 | `black --check`（只跑改过的 4 个文件）、`isort --check-only`、`flake8` | 全 0 |
| 类型检查 | `mypy --platform linux src/kiro_crew` | exit=0 |
| 格式门禁脚本 | `scripts/check_black_formatting.py` | exit=0 |
| harness 奇偶 | `HARNESS_BASE_REF=origin/main scripts/check_harness_parity.py` | exit=0（新增行里 Kiro 身份是正向判定） |
| i18n 键覆盖 | `node scripts/check-i18n-keys.mjs` | exit=0 |
| 文档索引 | `scripts/docs-lint.sh` | exit=1，**3 条 FINDING 全在 `ACP-2085-req-session/TASK.md`**，见下面归属 |

step 3 要求的 5 条测试逐条对上（`test/test_ai_studio_requirements.py`）：

1. 直改 → `test_direct_edit_records_the_diff` / `test_direct_edit_rejects_a_stale_base_hash`
   / `test_direct_edit_identical_text_is_not_a_change`
2. pendingEdit → `test_pending_edit_clears_when_the_graph_moves`
   （外加 `test_pending_edit_survives_a_broken_ledger_line`：账本坏行不能把整页打死）
3. start → `test_start_records_the_request` / `test_start_rejects_a_stale_graph_hash`
   / `test_start_refuses_an_unqualified_graph_with_its_gaps`
4. devState → `test_dev_state_tracks_the_graph`（editing → started → 改图谱后 editing +
   `changedAfterStart` → 重新 start 又回 started，四段一个用例走到底）、
   `test_dev_state_ignores_other_pages`（一页开工不污染另一页）、
   `test_dev_state_tolerates_a_broken_ledger`
5. 路由发消息 → `test_route_direct_edit`（`send_to_req_session` 打替身，断言消息含 diff）
   ，另加 `test_direct_edit_notice_never_overtakes_the_opening_prompt`（改动通知不能盖掉首条 prompt）

step 4 要求的 6 条前端用例都在 `RequirementPage.test.tsx`（22 用例里含这 6 条，
`ai-studio:start-dev` 事件用 `expect(seen).toEqual([{ projectId: 'p1', page: '设备清单' }])`
钉住 detail 的形状，不只是「发过」）。

## 门禁红的归属（逐条在干净对照 worktree 复现，不是本单改的）

`local-gate.py`：`5 failed, 28991 passed, 164 skipped in 259.51s` → exit=1。
造一个 HEAD（`1bd2f3a44`，未提交改动为零）的 detached worktree，只把那 5 条重跑：
**同样 5 条同名同因红**。

| 红的那条 | 干净 HEAD 上 | 能说清的 |
|---|---|---|
| `test_apps_doc_catalogue.py::test_every_shipped_app_has_a_catalogue_row` | 同名同因红 | 断言报的是「目录整块缺 `ai-studio` 这一行」——`src/kiro_crew/docs/apps.md` 里确实一行都没提，是 `bcc6240a7` 把 app 落进包里时欠的账 |
| `test_apps_doc_catalogue.py::test_both_pages_state_the_shipped_count` | 同名同因红 | 同上（两段文档的开头数量句要写 Twenty-five） |
| `test_builtin_skill_sync_safety.py::…test_child_dir_mode_change_diverges_fingerprint` | 同名同因红 | 指纹值与本机 umask/目录位有关；本单没碰 builtin_skills，也没碰指纹代码 |
| `test_ci_file_shards.py::…test_cannot_apply_item_splitting_on_top_of_file_splitting` | 同名同因红 | 报的是 `scripts/` 里分片脚本的返回值；本单没碰 CI 脚本 |
| `test_ci_pytest_progress.py::…test_split_records_only_selected_cases` | 同名同因红 | 同上 |

后三条我只做到「同名同因在干净 HEAD 上复现」+「失败测试涉及的文件都不在本单 diff 里」，
没有继续往根因挖 —— 判归属这两条就够了，挖根因是欠账那单的活。

`scripts/check_subprocess_encoding.py`：唯一 offender 是
`ai_studio/backend/devruns.py` 里 `_run_gate` 的 `subprocess.run`（`text=True` 未钉 `encoding=`），
它在**干净 HEAD 的对照 worktree 里同样红**：文件由本分支更早的
`2bbdb2540`（ACP-2060 开发四段）引入，门禁范围是 `origin/main...HEAD`，那个提交落进范围就报。
`devruns.py` 不在本单地盘里，不顺手改（动它要连它自己的测试一起，是另一单的活）。

`scripts/docs-lint.sh`：exit=1，3 条 line-citation 全指向
`docs/task-specs/2026/10/ACP-2085-req-session/TASK.md`；在干净 HEAD 的对照 worktree 里跑
**同样 3 条**（对照日志落在本机未提交的 `data/docs-lint-s3-baseline.log`）。本单新增的填坑笔记没有产生新 finding。

## 第 5 步 真跑（原样贴）

环境：网关 `:6790`（`KIROCREW_HOME` = 本 worktree 的 `.kirocrew-dev`），页面走 vite `:3000`
（`KIROCREW_PORT=6790`，`/api` 代理到该网关）。**必须 3000**：网关 CSRF 白名单里有
`localhost:3000`，没有 6791（填坑笔记坑一）。演示项目 `p261008-151745`，页面「设备分类」。

驱动是本机一次性脚本（playwright-core 连本机可见 Chrome，exit=0；未提交，副本已归档到
jereh-cli 的 `docs/requirements/20261009-034559-kirocrew-live-run-browser-driver/live-s3-dom.mjs`），
关键步逐行：

```
{"step":"target occurrences","needle":"- R-15 规则：","hits":1,
 "oldLine":"- R-15 规则：列表默认按分类编码从小到大排（字母不区分大小写），每页 20 条（用户同意建议）",
 "newLine":"…每页 50 条（用户同意建议）"}
{"step":"typed","charsBefore":43332,"charsAfter":43332,"contentChanged":true,
 "saveNow":{"text":"保存","disabled":false}}
{"step":"after save","flipped":true,
 "state":{"bar":{"text":"改动待落回需求"},"start":{"text":"已开工","disabled":true},
          "save":{"text":"保存","disabled":true}}}
{"step":"chat notice","found":true,"tail":"…用户在网页上直接改了需求页「设备分类」的文档，
 改动如下（diff）。请把这些改动落回 docs/需求图谱/设备分类.json，落不进去的地方问我。 …
 -- R-15 规则：…每页 20 条 …  ++ R-15 规则：…每页 50 条 …  10月9日 03:27"}
{"step":"shot-1 written"}
{"step":"approvals clicked","n":1}
{"step":"bar self-recovered","landed":true,
 "state":{"bar":{"text":"需求已齐，可以开发"},"start":{"text":"开始开发","disabled":false},
          "changed":{"text":"需求改了，要重新点开始开发"}}}
{"step":"start requested",
 "state":{"started":{"text":"已开工请求，等待拆任务","disabled":false},
          "start":{"text":"开始开发","disabled":true,"title":"生成中…"}}}
{"step":"shot-2 written"}
exit=0
```

对应任务书的五小步：

1. **改一句 → 保存 → 判定条变「改动待落回需求」**：`step after save` 的 `bar.text`
   就是这一句；改的是**文档里已有的可判定值**（R-15 的每页 20 条 → 50 条）。第一版加的是
   「这一条是真跑时手工加的备注」，被助手按协议退回（「落不进去的地方问我」——它讲的是文档自己的
   来历，不是页面该怎么表现），那次的记录在填坑笔记附带项。
2. **左栏需求会话收到改动消息**：`step chat notice` 的 `tail` 是会话里真实出现的那条用户消息，
   带完整 diff 与「落回 docs/需求图谱/设备分类.json」这句话。截图 `shot-1.png`（411467 字节）。
3. **等助手落回后判定条恢复**：`approvals clicked: 1` —— 它的 `Edit` 是**待批准**状态，
   浏览器驱动点了〔批准〕（工具批准 600 秒会自动替你拒绝，脚本必须自己当那个人）。
   落回之后 `bar self-recovered` → `需求已齐，可以开发`。图谱侧的实证：
   `docs/需求图谱/设备分类.json` 里 R-15 的规则文本是 `"…每页 50 条"`，AC-01 的验收文本也跟着
   改成 50 条，`grep -c '每页 20 条'` = **0**。平台自己没写图谱（`direct_edit` 只追加账本 + 发消息），
   写图谱的是会话 + 人点的那一次批准。
4. **点〔开始开发〕→「已开工请求，等待拆任务」**：`step start requested` 的 `started.text`。
   截图 `shot-2.png`（411445 字节）。
5. **`start-requests.jsonl` 多一行**（贴原文）。账本在工作区（模板仓 worktree）的
   `.ai-studio/` 下，不在 `KIROCREW_HOME`（填坑笔记坑五）：

```
{"at": "2026-10-08T18:59:18.520659Z", "page": "设备分类", "graphHash": "cb8bfa5a2028247c", "verdict": "全齐"}
{"at": "2026-10-08T19:27:39.752673Z", "page": "设备分类", "graphHash": "8408d2ba2f7e2b7b", "verdict": "全齐"}
```

第二条是本次真跑新写的（第一条是上一单 ACP-2085 留下的）。同一时刻的直改账本只剩这一行
（之前那条假 409 写进去的脏行已删，删除前的原样备份在本机未提交的
`data/live-s3-direct-edits.*.jsonl`）：

```
{"at": "2026-10-08T19:27:04.907320Z", "page": "设备分类", "baseDocHash": "3dd21394dd02d251",
 "diff": "--- 当前文档\n+++ 改后文档\n@@ -38,5 +38,5 @@\n…
-- R-15 规则：列表默认按分类编码从小到大排（字母不区分大小写），每页 20 条（用户同意建议）\n
+- R-15 规则：列表默认按分类编码从小到大排（字母不区分大小写），每页 50 条（用户同意建议）\n…"}
```

### 拒绝路径（真跑上补的只读验证）

拒绝路径脚本（只读，不写账本；同目录归档名 `live-s3-stale.py`）在同一个活网关上：

```
[0] GET 设备分类 -> 200 verdict=全齐 docHash=130a8713c2262db4 graphHash=16089f48fafa16d8
    pendingEdit=False devState=editing changedAfterStart=True
[1] POST direct-edit with a STALE docHash (030a… 改一个字符) -> 409
    {"error": "文档已被别人改过，请刷新", "code": "doc_changed"}
[2] POST start with a BOGUS graphHash -> 409
    {"error": "需求刚刚变了", "code": "graph_changed"}
[3] GET /requirements -> 200（4 页全部 verdict 齐，无「不齐」页）
RESULT: stale-doc=True bogus-graph=True not-ready=True
```

`not-ready` 那条标 `True` 的含义是「**本工作区没有不齐的页可打**」，422 分支由单测
`test_start_refuses_an_unqualified_graph_with_its_gaps` +
`test_route_start_not_ready_422_carries_the_gaps` 覆盖 —— 不为凑数去把演示图谱改坏。

**为什么 stale 的 hash 是「改一个字符」而不是「用上一次那个」**：直改成功故意不动渲染文档
（只追加账本 + 发消息），所以直改之后 `docHash` 一模一样，拿旧 hash 重试根本测不出陈旧
（填坑笔记坑三）。会改 hash 的是**图谱**（会话落回之后）——两套乐观并发凭据争用的对象不同，
是设计如此。网关重启后 `docHash` 不变（`130a8713c2262db4`），因为哈希吃的是抹掉
`生成时间：<ISO>` 之后的文本（坑四）。

## 第 6 步 需求文档（在模板仓，不进本提交）

webapp-template 仓 worktree `feature/ACP-2006-req-tpl`，提交 `8f2e65b`
`docs(req-graph): AI Studio 需求页直改+开工请求的验收文档(ACP-2104)`，
已推该仓 origin（`feature/ACP-2006-req-tpl` 新建远端分支）：

- `docs/需求图谱/ai-studio-requirement-direct-edit.json`（v34 图谱，事实源）
- `docs/需求图谱/ai-studio-requirement-direct-edit.md`（`jc fe reqdoc render` 产物，未手写）

`jc fe reqdoc check` 复现判定：

```
{"success":true,"version":"1.0.35","version":34,"verdict":"可以开工但有已知缺口","errors":[],
 "tiers":{"parts":["节点 edit 用的零件 MarkdownSourceEditor 还没做（缺口 markdown-source-edit…）"]}}
```

唯一缺口 = 可编辑 Markdown 正文区那个零件（框架组件池里确实没有），如实登记，没假装全齐。
md 与 render(json) 的一致性验过：`--out` 到别处再 `cmp`，只差 `生成时间` 那一行（每渲染必变，
所以整体 `diff` 必然不等，这是视图的性质不是文档没同步）。同目录里演示页的
`设备*.json` / `.md` 保持 untracked（真跑时被会话写过的现场，不属于本单提交）。

## 六步逐条对账

| 步 | 判据 | 状态 |
|---|---|---|
| 1 | `doc_hash` / `direct_edit` / `docHash` / `pendingEdit` / `send_to_req_session` / direct-edit 路由 | 做齐 |
| 2 | `start` / `devState`（started、editing+changedAfterStart）/ start 路由 | 做齐 |
| 3 | 5 类测试 | 做齐（35 passed，逐条见上） |
| 4 | 可编辑文档 + 〔保存〕+ 409 提示 + pendingEdit 黄条 + 开始开发三段判定 + 事件 + i18n 中英 | 做齐（vitest 269 / tsc 0） |
| 5 | 浏览器真跑 + 两张截图 + 账本新行 | 做齐（DOM 状态行 + 账本原文 + transcript 片段在上） |
| 6 | 模板仓需求文档提交并推其 origin；KiroCrew 只 stage 本单文件；提交 + 推 fork；Jira 评论 + 置完成 | 做齐 |

## 没做到的事 / 留给下一单

- `ai-studio:start-dev` 事件的**接收方**（开发页签）是别的单，本单只发不收；
  前端测试只钉「发对了」。
- `check_subprocess_encoding` 报的 `devruns.py` 里 `_run_gate`、`apps.md` 缺 `ai-studio` 目录行与数量句、
  ACP-2085 TASK.md 的 3 条 line-citation —— 都是存量债，本单没顺手改（地盘外）。
- 缺口零件 `MarkdownSourceEditor` 没做（已按实登记进需求图）。
- 真跑用的 4 个一次性脚本**不进本提交**（一次性、带本机路径），已连需求文档归档到 jereh-cli 的
  `docs/requirements/20261009-034559-kirocrew-live-run-browser-driver/`，等沉淀成 `jc` 子命令。
