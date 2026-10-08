# ACP-2085-S2 结束报告（会话 kc-v1）

派工单：`docs/task-specs/2026/10/ACP-2085-req-session/TASK.md` 第 1~6 步。
分支 `feature/ACP-2015-v1`，Jira 子任务 **ACP-2089**（标签 `sid-kc-v1`）。

## 提交

- **`b82740a41`** 代码提交：后端 + 前端 + 测试 + 填坑笔记 2 篇 + RFC §9.3 落地段，
  23 files changed / +1217 / -48，标题
  `feat(ai-studio): requirement session in the chat pane + live graph refresh (ACP-2085)`
- **本报告所在的那个提交**（+1 于 `b82740a41`，`git log --oneline -2` 即见它自己的 hash；
  在文档里写自己的 hash 是写不准的，改一次就作废）装本报告 + 派工单原样 + 两张交付截图，标题
  `docs(task-spec): ACP-2085-S2 end report with the live-run transcript`。
  共 2 个提交（PR 标题门「至多两提交」），拆法是照仓里 ACP-2060 那一对的写法：
  代码走 `feat(...)`（就是派工单指定的那句），报告/文档走 `docs(...)`
- 推 fork：`fork/feature/ACP-2015-v1`（不推 origin，未用 `--no-verify`）

## 交付

后端（新增 `backend/reqsession.py` + `routes.py` 一条路由）：

- `POST /api/apps/ai-studio/projects/{id}/req-session` → `200 {slotKey, created}`；
  项目不存在 `404 project_not_found`；记录里的 `workspaceDir` 不存在 `409 workspace_missing`
  （**不猜、不退回项目目录** —— 退回开会话等于让助手去写一个不存在的工作区，
  文件会落进 ai-studio 自己的记录目录）
- slot key `ai-studio-req-<id>`，`slot.project` = 工作区目录（= 会话里 CLI 的 cwd），
  标题「需求：〈项目名〉」+ `push_slot_title`，**不设 unattended**（它是 `_ChatSlot`
  只读属性，写进去 = 给会话下 180 秒批准毒咒）
- 首条提示语按派工单原文一字不差；工作区没有 `.claude/agents/requirement-writer.md`
  时换成「这个工作区缺少写需求助手，请联系管理员」那句
- 发过没有记在项目记录 `reqSessionStarted`（原子写回 tmp+fsync+os.replace）

前端：

- `ChatPane.tsx`：**先** `ensureReqSession(projectId)` 拿到 slotKey **才**挂 `ChatEmbed`。
  之前是浏览器自己编一个 `ai-studio-<id>` 挂上去 —— 那种 slot 没有 `project`，
  助手的 shell 在网关目录里跑，写出来的需求文件落在工作区外面，这就是本单修的根因。
  拿到之前显示「正在连接写需求助手…」，失败显示后端原文 + 〔重试〕；
  上方常驻提示 testid `req-session-tip`
- `RequirementsTool.tsx`：列表每 5 秒重拉（原来是 mount/focus 才拉）
- `RequirementPage.tsx`：本页每 5 秒重拉，`graphHash` 变了就重渲染文档与判定条；
  刷新中 / 后端还没重生成文档（`stale`）时判定条说「生成中…」，
  **只换字不换色**（一次轮询不该被读成就绪度在翻）
- 文案 4 条 × 中英两份（zh 原文，逐字核过）：
  `req_session_connecting`「正在连接写需求助手…」、`req_session_retry`「重试」、
  `req_session_tip`「助手要写需求文件时会请你批准。点一次〔信任会话〕，它就能自己写，不用每次点。」
  （常驻在聊天区上方，testid `req-session-tip`）、
  `req_session_no_key`「后端没有开成需求会话，请查看网关日志。」
- 顺带修掉一个真缺陷（测试逼出来的）：v34 拒绝渲染时的原因面板只列 `errors`，
  而**拒绝渲染最常见的原因是「待定」规则，它落在 `missing`** ——
  结果这个面板专门存在的意义（告诉你为什么没文档）反而是空列表。现在两个列表一起列

## 各判据结果

| 判据 | 命令 | 结果 |
|---|---|---|
| 后端测试 | `.venv/bin/python -m pytest test/test_ai_studio_reqsession.py -q` | **13 passed**（派工单 5 条 + 幂等/存储/路由/并发） |
| ai-studio 相关后端 | `.venv/bin/python -m pytest test/test_ai_studio_reqsession.py test/test_ai_studio_requirements.py -q` | **27 passed** |
| 前端判据 | `cd website && npx vitest run src/apps/ai-studio/` | **24 files / 238 tests passed** |
| 前端类型 | `cd website && node_modules/typescript/bin/tsc --noEmit -p .` | 无输出（clean） |
| 格式/lint/类型 | `black --check`（只喂改动 3 个 py）/ `flake8 src/kiro_crew test` / `mypy src/kiro_crew` / `isort --check-only` / `check_black_formatting.py` / `check_harness_parity.py` | **全过**（mypy：`no issues found in 1711 source files`） |
| subprocess 编码门 | `check_subprocess_encoding.py` | `rc=1`，**1 条红不是本单的**：`ai_studio/backend/devruns.py` 里 `_run_gate` 的 `subprocess.run` 缺 `encoding=`，该文件来自更早的提交 `2bbdb2540`（本单未碰它，`git status` 里干净） |
| local-gate（后端半边） | `.venv/bin/python scripts/local-gate.py` | `rc=1`：**5 failed / 30155 passed / 155 skipped**（265.92s）—— 5 条经**干净对照 worktree** 逐条复现，一条都不是本单的（见「门禁」） |
| local-gate（前端半边） | 同上 | **没跑到**：脚本按顺序跑，后端 section 一红就整体退出 |

**跑法警告**（我自己踩了两次假红，见填坑笔记
`20261008-230527-wholesale-stub-suites-and-the-gate-that-false-reds.md`）：
vitest / tsc 必须 `cd website` 再跑，仓库根会解析到另一个 vitest 5.0.3（没 happy-dom，
`window is not defined`）和一个同名 tsc 占位包。

## 门禁

单文件级（本 worktree 的 `.venv` 是指向主仓 venv 的符号链接，所以每条命令都
显式 `cd` 到本 worktree 再跑，否则验的是主仓的脏树）：

- `check_black_formatting.py` 只喂本单改动的 py 文件 → 通过
- `check_subprocess_encoding.py`、`flake8 src/kiro_crew test`、`mypy src/kiro_crew`、
  `isort --check-only`、`HARNESS_BASE_REF=origin/main scripts/check_harness_parity.py` → 通过
- `scripts/docs-lint.sh` → `rc=1`，**唯一的 FAIL 是 `line citations in prose`**，
  4 处里 3 处在派工单正文（原始任务书，我没改它），1 处是本报告**引用**那条行号时
  自己带出来的。存量问题，见「没做到的事」

### local-gate 那 5 条红：逐条用干净对照 worktree 证明不是我改的

照仓里 `20261008-164500-*` 的打法，在**我提交前的那个提交**上造一个 detached
对照（`.venv` 与 `website/node_modules` 软链复用主仓的，不 npm install）：

```bash
git -C <主仓> worktree add ../KiroCrew-wt-ctl-a2085 66c00c4d0 --detach
ln -sfn <主仓>/.venv ../KiroCrew-wt-ctl-a2085/.venv
ln -sfn <主仓>/website/node_modules ../KiroCrew-wt-ctl-a2085/website/node_modules
cd ../KiroCrew-wt-ctl-a2085 && PYTHONPATH=$PWD/src .venv/bin/python -m pytest -q -p no:randomly \
  test/test_apps_doc_catalogue.py test/test_builtin_skill_sync_safety.py \
  test/test_ci_file_shards.py test/test_ci_pytest_progress.py
# → 5 failed, 101 passed, 23 warnings in 11.46s   ← 与脏树上那 5 条同名同因
```

| 红的用例 | 对照里也红 | 真相（对照输出里的断言） |
|---|---|---|
| `test_apps_doc_catalogue::test_every_shipped_app_has_a_catalogue_row` | 是 | `apps.md` 的目录里没有 `ai-studio` 这一行 |
| `test_apps_doc_catalogue::test_both_pages_state_the_shipped_count` | 是 | `apps.md` 首段仍写「Twenty-four」，实际 25 个 |
| `test_builtin_skill_sync_safety::test_child_dir_mode_change_diverges_fingerprint` | 是 | 本机文件系统行为，本机必红 |
| `test_ci_file_shards::test_cannot_apply_item_splitting_on_top_of_file_splitting` | 是 | 本机没装 `pytest_split` 插件（CI 才有） |
| `test_ci_pytest_progress::test_split_records_only_selected_cases` | 是 | 同上 |

前两条是 ai-studio 落主干时**没登记 `src/kiro_crew/docs/apps.md`** 的存量债
（早于本单），要修属于另一单的地盘。对照 worktree
`../KiroCrew-wt-ctl-a2085`（detached 在 66c00c4d0）用完已 `git worktree remove` 掉。

`local-gate.py` 是 `main()` 里**顺序**跑 `plan.commands`，任何一条非零**直接 return**，
所以后端半边一条存量红就把前端半边整半边跳过 ——
前端的判据我用 `npx vitest run src/apps/ai-studio/` 单独跑足（238 全绿）。

## 第 5 步 真跑（原样贴）

网关重启（`setsid bash .kirocrew-dev/run-gw.sh`，`/proc/<pid>/attr/current` =
`kirocrew-launcher`），域名 `https://kc-v1-14409-dev.gb10.jereh-pe.cn/workspaces/p261008-151745/ai-studio`。
探针 `.kirocrew-dev/scripts/drive{,2,3,4}_s2.mjs`（DOM 文本与服务端 transcript 是证据，
截图只当交付物；本机禁看图）。项目 `p261008-151745`（设备管理（演示）），
工作区 `/home/jereh/repo/jc/webapp-template-wt-req-tpl`。

**证据口径先说清楚**：`shot-1.png` / `shot-2.png` 是交付物，**不是我判据的依据**
（本机硬性禁截图识图）。下面每条结论后面给的是**服务端 transcript 原文**或
**探针 dump 的 DOM 文本**。另有一处口径要挑明：`shot-1.png` 是 23:09 那轮真跑截的，
**早于 5.6 的并发修复**（`shot-2.png` 是 23:56 修复之后的）。它证明的是「首条消息渲染在
会话气泡里」这一现象，不代表最终代码状态 —— 修复后的行为以 5.6 的测试与服务端 transcript
的 user 行数为准。

### 5.1 会话开起来了，`slot.project` 真的指向工作区

服务端落盘 `.kirocrew-dev/sessions/dashboard_ai-studio-req-p261008-151745.jsonl` 第 0 行：

```
{"_type":"metadata","project":"/home/jereh/repo/jc/webapp-template-wt-req-tpl",
 "app":"ai-studio","title":"需求：设备管理（演示）"}
```

`project` = 工作区、`title` = 「需求：〈项目名〉」、**没有 `unattended` 字段**
（前台会话，写文件不会 180 秒被自动拒）。这三样都是本单后端该做到的，逐条对上。

### 5.2 左栏出现助手第一句（shot-1.png）

第 1 行是我方发的开场白（与 `first_prompt` 原文一致），第 2 行是它的第一句回话，原样：

> 手册我已读完，现场也看过了。
> - 工作区已有两页需求，判定都是「全齐」：`…/docs/需求图谱/设备清单.json`、`…/设备点检记录.json`
> - `docs/需求标准/` 这个目录还没有；需求标准在 `~/repo/jc/jereh-cli/src/domains/fe/reqstd-v34/`，我按那里读，判定命令跑得通
>
> **这次要做什么页面？** 说个名字就行（比如「设备报修单」），或者告诉我改已有哪一页、改哪里。
> [OPTIONS: 新建「设备报修单」页面 | 新建「备件库存」页面 | 改「设备清单」这一页 | 改「设备点检记录」这一页]

它自己去读了工作区的 `.claude/agents/requirement-writer.md`（「手册我已读完」），
并且第一句就是问要做哪个页面 —— 这正是开场白要求的那件事。

同一时刻页面上的 DOM 证据（探针 dump，`data-testid` 清单节选）：

```
ai-studio-chat, req-session-tip, message-bubble, turn-stats, turn-model,
req-list, req-row-设备清单, req-verdict-设备清单, req-row-设备点检记录, req-verdict-设备点检记录
```

`req-session-tip` 常驻文案（zh 原文）也在页面上：
「助手要写需求文件时会请你批准。点一次〔信任会话〕，它就能自己写，不用每次点。」
—— 即「先向后端开会话、拿到 key 才挂 embed」这条链路在真页面上是通的
（`ai-studio-chat` 里有 `message-bubble`，说明挂上的是**真会话**，不是错误分支）。

### 5.3 发「加一页：设备分类…」

第 3 行（user，`ts=2026-10-08T15:15:13Z`）原文：

> 加一页：设备分类。字段只有 分类编码、分类名称、备注。其它都按你的建议。

第 4~12 行是它的工具调用（读 reqstd-v34 的 README/schema/validate.js、
读现有图谱 `设备清单.json`、核对组件目录里的组件名）。第 13 行（assistant）
**没有立刻写文件**，而是按手册先把整套建议摊开请我点头，末尾带就绪判定：

> …（4 列列表 / 1 个查询条件 / 弹窗 3 项 / 4 个按钮 / 规则 / 权限 / 状态 / 本期不做 全文）
> 有一处需要你点头：本期「设备挂分类」到底要不要一起做（要的话「设备清单」页要加一列一栏，那是改另一页）。
>
> 就绪判定：不齐 缺口：本期范围（设备要不要挂分类）未确认；汇总未确认
> [OPTIONS: 对，按你说的写 | 对，但同时给设备清单加分类 | 要改：字数和提示文案我来定]

也就是说「回答它的问题、并且选它的建议」这句话，在它这边是**一轮**综合确认
（不是 4 轮追问），要选的建议就是「对，按你说的写」这一条。

### 5.4 点〔信任会话〕→ 它自己写文件（成功，`shot-2.png`）

**先记一次假失败**（第一版探针 `drive3_s2.mjs` 跑出来的）：等批准卡等满 6 分钟，
最后 `Target page, context or browser has been closed`，进程被 OOM 侧打死（`rc=137`）：

```
+157s unchanged (approval=[])   +172s unchanged (approval=[])   …
+364s unchanged (approval=[])   +379s unchanged (approval=[])
SNAP ERR page.evaluate: Target page, context or browser has been closed
```

事后核对：那一轮**确认句根本没发出去**（服务端 transcript 里 user 行只有 2 条）。
根因是探针自己的幂等判断用错了证据 —— 它用「屏幕上有没有『对，按你说的写』」
判断「是不是已经答过」，而那几个字从助手给出 `[OPTIONS: …]` 起**就在屏幕上**
（选项 chip 是渲染在 transcript 里的按钮）。教训见填坑笔记 `20261008-235002-*.md`。

第二版 `drive4_s2.mjs` 改成**用服务端 transcript 的 user 行计数**证明发出去了，原样：

```
OPEN attempt=1 tip="助手要写需求文件时会请你批准。点一次〔信任会话〕，它就能自己写，不用每次点。" rows=2 approval=[]
SENT after 3s transcript users 2→3 (server-confirmed)
+15s approval=[] rows=2
+45s approval=[] rows=2
+60s approval=["批准","信任","拒绝"] rows=2
  … Write docs/需求图谱/设备分类.json 需要审批 编辑 需求图谱/设备分类.json 批准 信任 拒绝
CLICKED 信任 (scope menu)
!! scope item missing, menu closed
after trust: approval=[]
+0s ROW PRESENT
FILE …/docs/需求图谱/设备分类.json bytes=16561 mtime=2026-10-08T15:52:51.908Z
```

服务端 transcript 对得上（时间是 UTC，+8 即上面墙钟）：

```
[14] user  15:51:31  对，按你说的写
[15] tool  15:51:47  🔧 Read completeness tiers logic
[16] tool  15:52:07  🔧 Inspect portrait naming rules
[17] tool  15:52:33  🔧 Write docs/需求图谱/设备分类.json      ← 批准卡就在这一步出现
[18] tool  15:52:35  ✅ Write docs/需求图谱/设备分类.json      ← 我点〔信任〕之后放行
[19] tool  15:52:51  🔧 Edit docs/需求图谱/设备分类.json
[20] tool  15:53:01  🔧 Read docs/需求图谱/设备分类.json (60 - 89)
```

**没有**任何自动放行：批准卡出现 60 秒期间 `approval=[]`→`["批准","信任","拒绝"]`，
是探针按人的那一下点掉的（派的单明令不许 bypass / yolo）。
点的是卡片上那个「信任」按钮，点完 `approval=[]`、写入立即执行；
探针随后去找「信任本会话的所有工具」这个二级菜单项没找到（说明这张卡的「信任」
是**直接动作**，不是开菜单），它多补了一次点击把话说成「menu closed」，无副作用。

### 5.5 右栏自动出现「设备分类」+ 判定条有颜色 + `jc fe reqdoc check` 与界面一致

文件落盘（最后一次 Edit）`23:52:51.908`，右栏在**下一个轮询周期**就命中
（探针 10 秒窗口的第一次 `waitFor` 直接返回 present；前端列表 5 秒一拉，
所以最坏 ~5 秒 + 一次请求，亚秒级延迟探针没测）：

```
ROWS [
 { "p": "设备分类",     "txt": "设备分类\n全齐\n2026/10/8 23:52:51" },
 { "p": "设备清单",     "txt": "设备清单\n全齐\n2026/10/8 9:27:41" },
 { "p": "设备点检记录", "txt": "设备点检记录\n全齐\n2026/10/8 9:33:58" }
]
```

判定条（DOM，含 class —— 有颜色是靠 class 证的，不是靠看图）：

```
BAR  "需求已齐，可以开发"
BAR_CLASS "flex-1 rounded-lg border px-3 py-2 text-[12px] font-semibold border-ok bg-ok-subtle text-ok"
DOC  {"doc": true, "noMd": "", "head": "需求：设备分类（设备管理/设备分类） 需求标准 v34 …
      生成时间：2026-10-08T15:53:22.234Z … 判定：全齐 完整度：接口齐 ✓ 交互齐 ✓ 零件可达 ✓，可直接开发 …"}
```

命令行侧（在工作区目录里跑，与后端用的是同一条 `jc fe reqdoc check`，
即 `requirements.py` 的 `DEFAULT_CMD`）：

```
$ cd /home/jereh/repo/jc/webapp-template-wt-req-tpl && jc fe reqdoc check "docs/需求图谱/设备分类.json"
{"success":true,"version":"1.0.35","data":{
  "file":"/home/jereh/repo/jc/webapp-template-wt-req-tpl/docs/需求图谱/设备分类.json",
  "version":34,"frame":"/home/jereh/repo/jereh-fe-frame",
  "verdict":"全齐","errors":[],"missing":[],"tiers":{"api":[],"ui":[],"parts":[]},"warnings":[]}}
```

**界面与命令行一致**：命令行 `verdict=全齐 / errors=0 / missing=0`，
界面徽标「全齐」、判定条「需求已齐，可以开发」+ `border-ok bg-ok-subtle text-ok`（绿）、
文档头「判定：全齐 完整度：接口齐 ✓ 交互齐 ✓ 零件可达 ✓」。
另外两页作对照（`设备点检记录.json` 命令行也是 `全齐 / 0 / 0`，界面同）。

顺带一个闭环证据：助手自己收尾时也跑了**同一条**判定命令（transcript
`[22] Run requirement graph check` → `[23] Generate requirement document from graph`，
生成出 `设备分类.md` 70 KB），它给人类的最后一句原文：

> 「设备分类」这页需求已写好并出了文档，机器判定「全齐」。
> - 图谱：`…/docs/需求图谱/设备分类.json`
> - 文档（676 行，开发工人看这份）：`…/docs/需求图谱/设备分类.md`
> - 内容：3 个字段（编码 / 名称 / 备注）、4 个按钮（新增、修改、删除、导出）、1 个查询条件、18 条验收、6 个接口
> - 按你点头的范围：本期不给设备挂分类，所以「设备清单」那页没动，文件也没提交 git（要提交跟我说）
>
> 就绪判定：全齐 缺口：无

—— 字段/按钮/查询条件与我发过去的那一句（「字段只有 分类编码、分类名称、备注」）
逐项对得上，且它**没**顺手改另一页，也**没**自己提交 git。

## 真跑环境的硬约束（不是本单缺陷，但直接影响复现，读代码看不出来）

真跑期间同一台机器上有个 **cron 任务**（`jc fe autopilot`）在跑全量 vitest，
~20 个 worker × ~1.5G，把 16G swap 打满。后果链（都实测到，细节见填坑笔记
`20261008-230527-*.md` 坑 3/5）：

- headless Chrome 起不来，或起来后 `browserContext.addCookies: … browser has been closed`；
- 网关事件循环连续停摆 17~21 秒 → **loop_watchdog 抓完 dump 自己退出**
  （日志末尾 `…before dump-then-exit`），此时 nginx 把**所有** `/api/*` 打成 502，
  而 `/src/*.tsx` 仍 200 —— 极易误判成「nginx/vite 坏了」；
- 浏览器里看到的是 SPA 自己的「This page could not finish loading」，
  也就是仓里 `20261008-161000-*` 记的「dev 域名丢模块」被从偶发压成必现。

还有一条**同款偶发**（同机并发把概率顶高了）：同一 URL 同一 jar，
`diag_page_s2.mjs` 一次就把整页渲染出来（本文 5.2 那段 DOM 就是它给的），
15 分钟后 `drive4_s2.mjs` 连试两次都「textarea 没出现」。差别只有「试几次」——
就是 `20261008-161000-*` 记的 dev 域名丢模块，同期 `curl -k .../src/main.tsx` 200 / 43 KB。
`ATTEMPTS` 从 10 提到 12、每次换全新 context 后第一次就起来了。**「探针起不来」
不要顺手怀疑刚改的前端。**

对策（本单实际用的）：门禁（全量 vitest / tsc / local-gate）与浏览器真跑**串行**；
`/api/*` 全 502 先跑 `ss -tln` 确认上游进程还在不在；等 `MemAvailable` 回到 25G 以上再动浏览器。
**没有**动那个 cron（不是本单地盘），也没杀任何别人的进程。

顺手留了个工具 `.kirocrew-dev/scripts/mintjar_s2.sh`（重铸探针用的会话 cookie jar，
链接票只有 300 秒那条坑见 `20261008-103819-*`）。但要说清：**上面那两次起不来不是凭据问题**
—— 中途我重铸过一次 jar，旧 jar 有「一次就起来」的（diag），新 jar 也有「整页空白」的
（probe_composer），两边都有成败，指向偶发而不是身份。

最后还有一条**收尾环境的坑**（交付之后才撞上，同样与本单代码无关）：本仓目录在
`jc agent keepalive` 的登记表里（22:15 登记），crontab 有一条每分钟的 `keepalive tick`，
它**只看会话忙不忙、不看活干完没干完**，于是本报告写完、Jira 也流转「完成」之后，
同一条派工提示仍被原样重推（累计十三次），而帮助里明写「自己说做完了不会自动摘牌」。
已用 `jc agent keepalive remove <本仓目录>` 摘牌（只摘本仓这一条，其它 worker 的登记没动），
细节见填坑笔记 `20261009-001429-*.md`。**后果要说实话**：中间有两次我为了「找没做完的那一步」
又跑了一轮全量复核（含一次全量 vitest，24 files / 238 tests 复跑仍全绿），
在那台正被 autopilot 压满的机器上白加了一份负载 —— 这是判断失误，不是本单缺陷。

## 六步判据逐条对账

| 步 | 判据 | 结论 |
|---|---|---|
| 1 后端 `reqsession.py` | 开会话 / `slot.project`=工作区 / 标题 / 不设 unattended / 首条提示语 / 幂等 | 达成（5.1 的 metadata 是服务端自证） |
| 2 路由 | `200 {slotKey,created}`、404、409 `workspace_missing` | 达成（后端用例覆盖） |
| 3 后端测试 | 假 state / 假 dispatch，5 条命名断言 | 达成（13 passed，含并发那条） |
| 4 前端 | 先开会话再挂 embed + 5 秒轮询 + 生成中 + 中英文案 | 达成（238 passed / tsc clean / 5.2 的 DOM） |
| 5 真跑 | 第一句 → 加页 → 〔信任会话〕→ 它写文件 → 10 秒内右栏出现 + 判定条有色 + 与 `jc fe reqdoc check` 一致 | 达成（5.2~5.5，`shot-1.png` / `shot-2.png` 已入库） |
| 6 收尾 | 只 stage 本单文件、指定提交信息、推 fork、报告 | 见「提交」与本节 |

真跑里两点如实说明，别读成「比实际更好」：

- **「10 秒内」的下界没测到**。探针等行的 `waitFor` 是 10 秒窗口，第一次就命中，
  所以只知道 **≤10 秒**（前端 5 秒一拉，理论上界 ~5 秒 + 一次请求）。
  要说「3 秒内出现」这种话，得有毫秒戳的轮询日志，我没有。
- **〔信任〕那张卡是「直接动作」，不是先开菜单**。探针点完卡片上的「信任」之后
  `approval=[]`、后续 `Edit`/`Read` 再无批准卡 —— 说明这一次点击确实信任了整会话；
  但它随后找「信任本会话的所有工具」这个二级项没找到，多补一次点击并打了一句
  `scope item missing, menu closed`，是无副作用的探针噪声，不是界面缺东西。

## 没做到的事 / 留给下一单

- **docs-lint 存量红**（`rc=1`）：`FAIL: line citations in prose (3)`，三处**行号引用**
  全部在**派工单 TASK.md 自己**的正文里（一个 mirror 模块的两百多行区间、
  `state.py` 的一个区间、`handlers.py` 的一个区间）。不是我新增的文档，
  我也**没改派工单正文**（它是原始任务书，改了就没有原样可对账）；
  本报告正文里我一开始也写了行号引用，被 lint 顶回来之后全部改成**按符号名引**
  （`_run_gate`、`DEFAULT_CMD`、`main()` 里那个循环），已清干净。
  要不要洗 TASK.md 那三处，请 master 定
- **i18n parity**：本单只加中英两份（派工单明令「新文案中英两份」），
  于是其它 12 个语种目录缺这 4 个 key —— master 已单独立项 **ACP-2113**，不在本单地盘
- **UI 新建的工作区没有 `workspaceDir`**：`projects.create_project` 只落
  id/name/description/createdAt，`workspaceDir` 是 S1（ACP-2090 复制模板）那条路写的。
  经 UI 直接新建、没走过模板的项目，其需求会话会**退回项目记录目录**（不是 409）。
  这是既有语义（`requirements.workspace_dir` 同规矩），本单没改；
  要不要收紧成「没有 workspaceDir 就不许开会话」，属于产品口径，留给 master
- **开场白并发**：真跑第一轮看到助手把同一个问题问了两遍。根因是「读标记 → 发提示语 →
  写标记」中间有真 `await`，而首屏 mount effect 会跑两遍（`main.tsx` 整个 app 包在
  `<StrictMode>` 下）。已修（进程内原子闸 + `test_concurrent_opens_send_the_prompt_once`），
  见填坑笔记坑 4
