---
title: AI Studio 需求流水线——工作区从模板仓派生，写需求助手对话产出需求图谱，机器判齐后开始开发
status: draft
author: 14409（master 会话代写）
created: 2026-10-08
last-audited: 2026-10-08
audited-at: 2bbdb2540
doc-pr: null
implementation-prs: []
tracking-issues: [ACP-2015, ACP-2006, ACP-1992]
supersedes: []
superseded-by: []
---

# RFC：AI Studio 需求流水线

> 一句话：用户在 AI Studio 里新建一个**工作区**（从模板 Git 仓派生、前后端跑起来、有自己的网址），在工作区里**和写需求助手聊**（或直接改文档）把需求写成**需求图谱**，由**生成脚本**出需求文档并判「不齐 / 可以开工但有已知缺口 / 全齐」，判过了才能点**开始开发**。
>
> 本 RFC 只管到「开始开发」被接受为止。拆任务、派工人、看板、两阶段验收沿用已定稿的 07 设计（见 §11），不在这里重写。

## 1. 背景与病灶

在命令行里这条路已经走通过（2026-10-08，jereh-cli ACP-2006）：
- `jc webapp init` 能从模板仓派生个人仓并推送；
- 写需求助手 `requirement-writer`（Claude Code agent）在 tmux 里和用户一轮 ≤5 道选择题地聊，产出需求标准 v34 的需求图谱 JSON；
- `jc fe reqdoc check|render` 判三档、出文档。实测一个「设备点检记录」需求，助手问 25 题后写出两页图谱，两页都判「全齐」（每页 22~29 条验收）。

但这些都要人在终端里操作。AI Studio（main `2bbdb2540`）已经有工作区列表、三栏工作台、聊天、Tiptap 文档编辑器，却和这条路接不上：

| 病灶 | 证据（main） |
|---|---|
| 新建工作区只是一个普通目录 + 代码里写死的 3 份种子文档，不是 Git 仓、不从模板来 | `backend/projects.py` `create_project`、`SEED_DOCS` |
| 因为不是 Git 仓，发布永远判 `rejected` | `backend/publish.py` 用 `git for-each-ref` 读版本标签 |
| 工作区没有跑起来的前后端、没有网址 | 无相关代码 |
| 聊天会话不在工作区目录里跑，也没指定助手，跟需求无关 | `ChatPane.tsx` 只传 `name/title`；对比 spec_builder `runtime.py` 设 `slot.project` |
| 「判能不能开发」完全没有；需求图谱读的是打包在代码里的一张固定图，和工作区无关 | `backend/graph.py` `load_graph` 读 `graphs/knowledge-doc-upload-v1.json` |
| 前端调 `GET /publish/versions`，后端没注册这条路由 | `studioApi.ts` `publishApi.listVersions`；`routes.py` `register_routes` |

### 目标
1. 新建工作区 = 从模板 Git 仓派生 + 提交推送 + 前后端跑起来 + 网址写进工作区属性；打开网址能看到什么都没改时的应用框架。
2. 工作区里自带示例需求图谱和它生成的文档；用户在它们基础上改：直接改文档，或和写需求助手聊。
3. 需求的唯一事实源是需求图谱；文档由生成脚本出；能不能开发由生成脚本判（三档），不靠 AI 自评。
4. 「开始开发」只在判定为「全齐」或「可以开工但有已知缺口」时可点；后端点击时再判一次，不信前端。

### 非目标（本 RFC 不做）
- 拆任务 DAG、派开发工人、任务看板、两阶段验收——沿用 07 设计（§11）。
- 改写需求标准 v34 本身（Schema、模板、生成脚本在 jereh-cli `src/domains/fe/reqstd-v34/`）。
- 多租户与权限体系：工号取登录态，本期不做工作区共享。
- 移动端。

## 2. 铁律（来自用户定案，实现不得违背）

1. **开发工人只看需求文档**，不看、不参考任何旧系统页面或旧代码。需求图谱里不许出现旧系统字段（v34 Schema 直接拒收），文档里不许出现旧页面路径、原接口、代码行号。
2. **需求图谱是唯一事实源**：文档是它的视图。用户直接改文档 = 一次改需求的请求，必须落回图谱再重新生成；平台不单独存一份「权威文档」。
3. **能不能开发由机器判**：判定来自 `jc fe reqdoc check` 的 `verdict`，不来自聊天里 AI 说了什么。
4. **写需求助手要能交互**：一轮 ≤5 题、带选项和建议、可点选回答；用户确认汇总后才写图谱。

## 3. 通用语言

| 术语 | 定义 | 不要混用 |
|---|---|---|
| 工作区（Workspace） | 一个用户的一份应用：从模板 Git 仓派生出的个人 Git 仓 + 本机工作目录 + 跑起来的前后端 + 网址。沿用现有 AI Studio「项目」的 id 与路由 `/workspaces/<id>` | 不叫「项目目录」「实例」（实例专指跑着的前后端进程） |
| 模板（Template） | 用来派生工作区的 Git 仓（默认 webapp-template），自带示例页面、示例需求图谱、写需求助手 | — |
| 运行实例（DevInstance） | 工作区的前后端开发服务进程组 + 分到的端口 + 网址 | 不叫「部署」（部署专指 publish 出的版本） |
| 工作区网址（DevUrl） | 运行实例对外地址，规则 `https://<工作区代号>-<工号>-dev.gb10.jereh-pe.cn/` | — |
| 需求页（RequirementPage） | 工作区里的一个需求单元 = 一份需求图谱文件 `docs/需求图谱/<页名>.json` + 它生成的 `<页名>.md` | 不叫「文档」（文档是需求页的一个视图） |
| 需求图谱（RequirementGraph） | v34 Schema 的 JSON，需求唯一事实源，每条带来源 `from` | 不叫「画像」（画像专指老页面倒推，本流程不用） |
| 需求文档（RequirementDoc） | 生成脚本从需求图谱出的 Markdown，只读视图 + 「直改」入口 | 不叫「PRD 草稿」 |
| 判定（Verdict） | 生成脚本对需求图谱的三档结论：`不齐` / `可以开工但有已知缺口` / `全齐`，附 `errors`、`missing`、`tiers` | 不叫「就绪/未就绪」「AI 判断」 |
| 写需求助手（RequirementWriter） | 在工作区目录里运行的 Claude Code 会话，装载 `requirement-writer` agent | 不叫「需求 agent」「聊天机器人」 |
| 需求会话（RequirementSession） | 一个工作区对应的那个写需求助手聊天会话（ChatEmbed slot） | — |
| 开工请求（StartRequest） | 用户对某需求页点「开始开发」，后端复判通过后记下的一条记录 | 不叫「提交」（提交专指 Git 提交） |

状态词（一词一义）：
- 工作区状态 `WorkspaceStatus`：`creating`（派生中）→ `starting`（起服务中）→ `running`（运行中）/ `stopped`（已停止）/ `failed`（失败，附失败的步骤）。持久，权威在工作区元数据。
- 判定 `Verdict`：每次图谱变化后计算的**观测值**，可缓存，权威永远是重新跑一次 check。
- 需求页开发状态 `PageDevState`：`editing`（改需求中）→ `requested`（已开工请求，等拆任务）→ 之后由 07 的状态接管。持久。

## 4. 限界上下文

| 上下文 | 职责 | 不碰 |
|---|---|---|
| 工作区（Workspace） | 派生、提交推送、起停运行实例、分端口、挂网址、记工作区状态 | 需求内容 |
| 需求（Requirement） | 列需求页、读图谱与文档、接收直改、调生成脚本出文档与判定、记开工请求 | 怎么拆任务、怎么开发 |
| 会话（Session，复用 KiroCrew chat） | 在工作区目录里起写需求助手、传首条提示语、转发直改通知 | 判定 |
| 开发（Development，07 设计） | 消费开工请求：拆任务 DAG、派工人、看板、验收 | 需求内容（只读需求文档） |

关系：
- 工作区 →（工作区目录、DevUrl）→ 需求、会话：需求和会话都以工作区目录为根。
- 会话 →（写图谱文件）→ 需求：助手只通过写 `docs/需求图谱/*.json` 影响需求；需求上下文发现文件变了就重生成、重判。
- 需求 →（事件 `StartRequested`）→ 开发：通知型事件，开发上下文订阅。
- 判定的唯一计算者是需求上下文（调生成脚本）；会话、前端都不得自己算或缓存为权威。

## 5. 领域事件

| 事件 | 触发 | 数据 | 产生 → 消费 | 去重 |
|---|---|---|---|---|
| `WorkspaceCreated` | 派生 + 首次推送成功 | workspaceId, repoUrl, branch, commit | 工作区 → 前端列表 | workspaceId |
| `WorkspaceStarted` | 运行实例健康检查通过 | workspaceId, devUrl, ports | 工作区 → 前端 | workspaceId + 启动序号 |
| `WorkspaceFailed` | 任一步失败 | workspaceId, step, message | 工作区 → 前端 | workspaceId + step |
| `GraphChanged` | `docs/需求图谱/*.json` 内容 hash 变化 | workspaceId, page, hash | 需求（文件监视或会话一轮结束后扫描）→ 需求自身 | page + hash |
| `VerdictComputed` | 每次 GraphChanged 后跑完 check | workspaceId, page, hash, verdict, missing, tiers | 需求 → 前端 | page + hash |
| `DocDirectEdited` | 用户在编辑器里保存了对需求文档的改动 | workspaceId, page, diff | 需求 → 会话（作为一条消息发给写需求助手） | page + diff hash |
| `StartRequested` | 用户点开始开发且后端复判通过 | workspaceId, page, graphHash, verdict, user, at | 需求 → 开发（07） | page + graphHash |

命令（发给某方要它做事，不是事件）：`CreateWorkspace`、`StartDevInstance`、`StopDevInstance`、`OpenRequirementSession`、`RequestStart`。

## 6. 聚合与不变式

**工作区（聚合根）**
- W1：`status=running` ⇒ 运行实例进程活着 且 DevUrl 返回 200 且 端口已登记给本工作区。
- W2：工作区目录是 Git 仓，`origin` 指向个人仓，首次创建后至少有一次已推送的提交。
- W3：一个工作区同一时刻最多一个运行实例；端口不与任何其他工作区或本机已登记占用重叠。
- W4：删除工作区不删个人远端仓（只停实例、释放端口、删本机目录前要求二次确认）。

**需求页（聚合根，按工作区 + 页名唯一）**
- R1：需求文档 = render(需求图谱)；图谱 hash 变了而文档没重生成 ⇒ 界面显示「文档过期，重新生成中」，不显示旧判定。
- R2：`StartRequested` 只在后端当场 check 的 verdict ∈ {全齐, 可以开工但有已知缺口} 时产生；记录里的 graphHash = 当场判定所用的图谱 hash。
- R3：`PageDevState=requested` 之后图谱再改 ⇒ 回到 `editing` 并提示「需求改了，要重新点开始开发」（开工请求作废标记，不删除）。
- R4：需求图谱里没有旧系统字段；生成文档里不含旧系统字样（由 v34 生成脚本保证，平台不另做）。

## 7. 用户旅程（逐步）

### A. 工作区
1. **A1 打开 `/workspaces`**：看到自己的工作区列表（卡片或表格：名称、状态、网址、最近修改）。右上 **〔新建工作区〕**。
2. **A2 新建对话框**：填 **工作区名称**（必填，2~40 字）、**代号**（必填，小写英文数字短横线 3~24 位，默认由名称转拼音缩写，可改，用于仓名和网址）、**描述**（选填，≤2000 字）；**模板**下拉（默认「webapp-template」，本期只有一个）。工号取登录态，只读显示。点 **〔创建〕**。
3. **A3 派生**：对话框变进度条，逐步显示「克隆模板 → 建个人仓 → 推送 → 起服务 → 挂网址」，每步 ✓/✗。任一步 ✗：显示该步错误原文 + **〔重试这一步〕**（幂等）。
4. **A4 起服务并挂网址**：后端给工作区分两个端口（前端、后端），按模板的启动契约（§9.2）起前后端，挂网址，健康检查通过后状态变「运行中」，网址写进工作区属性。
5. **A5 进入工作台 `/workspaces/<id>/ai-studio`**：顶栏显示工作区名、状态点、**网址（可点、可复制）**、〔停止〕/〔启动〕。点网址新标签打开，看到模板自带的应用框架和示例页面。

### B. 需求
6. **B1 需求页列表**：右栏工具栏新增 **「需求」** 标签（放在第一个），列出 `docs/需求图谱/*.json`，每项：页名、判定徽标（红 不齐 / 黄 有缺口 / 绿 全齐）、最近修改时间。模板自带的示例需求页一开始就在。底部 **〔新建需求页〕**（填页名，在会话里让助手从零问起）。
7. **B2 打开一个需求页**：中栏打开「需求页」标签：顶部**判定条**（三色 + 缺口清单，可展开）；中间是生成的需求文档（DocEditor，Tiptap 富文本/源码双模式）；顶部右侧 **〔开始开发〕**、**〔看需求图谱〕**（切到 JSON 只读视图）。
8. **B3 和助手聊**：左栏聊天就是本工作区的需求会话（写需求助手）。打开某需求页时，会话收到一条系统消息「用户正在看需求页 <页名>」。助手按 v34 规则提问（每轮 ≤5 题，A–E+其它，带建议）；用户点选或打字回答。助手确认汇总后写图谱。
9. **B4 自动刷新**：图谱文件一变（助手写入或用户直改落回），需求上下文重生成文档、重判；中栏文档和判定条刷新，列表徽标同步。刷新期间判定条显示「生成中…」，〔开始开发〕置灰。
10. **B5 直改文档**：用户在编辑器里改文字，点 **〔保存〕**：改动作为 `DocDirectEdited` 发给助手，助手落回图谱（落不进的在聊天里问用户），之后走 B4。保存后、助手落回前，判定条显示「改动待落回需求」，〔开始开发〕置灰。
11. **B6 开始开发**：判定为「全齐」或「可以开工但有已知缺口」时 〔开始开发〕可点；点击后若是「有缺口」先弹确认「这页有 N 处已知缺口，开发会按统一做法先落。确定开始？」。后端复判通过 → 记开工请求 → 需求页显示「已开工请求，等待拆任务」，并进入 07 的开发页。复判不过 → 提示「需求刚刚变了，判定为不齐，请先补齐」并刷新判定条。

## 8. 界面清单

| 位置 | 新增/改动 | 组件与交互 |
|---|---|---|
| `/workspaces` 列表 | 改 | 卡片加「状态点 + 网址」；新建对话框加 代号、模板、工号（只读）字段；创建过程分步进度 + 每步重试 |
| 工作台顶栏 | 新增 | 工作区名、状态点（creating/starting/running/stopped/failed 五色）、网址（链接 + 复制）、〔停止〕〔启动〕 |
| 右栏 ToolSidebar | 新增「需求」标签（第一个） | 需求页列表 + 判定徽标 + 〔新建需求页〕 |
| 中栏 WorkArea | 新增 `req` 标签类型 | 判定条（三色 + 可展开缺口：errors / missing / tiers 三组）+ DocEditor（文档）+ 〔开始开发〕〔看需求图谱〕；文档过期/待落回时有遮罩提示 |
| 左栏 ChatPane | 改 | 改为连本工作区的需求会话（§9.3）；会话忙时显示「助手在想…」；助手提问的选项可点选（点选 = 发送该选项字母） |

文案原文（实现照抄，验收按原文核对）：
- 判定条：「不齐：还不能开发」/「可以开工，但有 N 处已知缺口」/「需求已齐，可以开发」/「生成中…」/「改动待落回需求」/「文档过期，重新生成中」
- 〔开始开发〕置灰提示：「还不能开发：<第一条缺口>」
- 复判不过：「需求刚刚变了，判定为不齐，请先补齐」
- 开工后：「已开工请求，等待拆任务」
- 需求改了：「需求改了，要重新点开始开发」
- 创建失败：「<步骤名>失败：<错误原文>」

## 9. 接口与契约

### 9.1 工作区（前缀 `/api/apps/ai-studio`，沿用现有 `_require_enabled`）

| 方法 路径 | 做什么 | 关键响应/错误 |
|---|---|---|
| `POST /projects` | **改**：入参加 `code`、`template`；同步返回 `{id, status:"creating"}`，派生在后台跑 | 400 代号不合法；409 代号已被本人占用 |
| `GET /projects/{id}` | **改**：返回加 `status`、`failedStep`、`repoUrl`、`devUrl`、`ports`、`steps[]`（每步 name/state/message） | — |
| `POST /projects/{id}/retry` | 重试失败的那一步（幂等） | 409 当前不是 failed |
| `POST /projects/{id}/dev-instance/start` · `/stop` | 起停运行实例 | 409 已在跑 / 已停 |

派生实现：调用可配置命令 `AI_STUDIO_WORKSPACE_CMD`（默认 `jc webapp init <模板url> --name <代号> --uid <工号> --base <projects_root> --no-init-sessions`），按其 JSON 信封里每步 `steps` 更新进度；命令不可用时返回 503 `workspace_cmd_unavailable`。工作区目录 = 该命令产出的目录，`project.json` 写在其 `.ai-studio/` 下（不进 Git）。

### 9.2 模板启动契约（模板仓要满足，属模板仓的需求）
- 模板根目录提供 `.ai-studio/workspace.json`：`{"dev":{"web":{"cmd":"pnpm dev:web","portEnv":"PORT"},"api":{"cmd":"pnpm dev:api","portEnv":"PORT"},"webProxyEnv":"VITE_PROXY_TARGET","health":"/"}}`。
- 前后端端口必须能由环境变量覆盖。**现状不满足**：webapp-template 的 `dev:web` / `dev:api` 在 package.json 里写死 `PORT=5199` / `PORT=3011`，多工作区会撞端口——需模板仓改成读环境变量、未设才用默认。
- 前端 dev 服务要允许工作区网址的 Host（vite `server.allowedHosts`）。
- 模板自带示例需求页 `docs/需求图谱/*.json` + `.md`（至少 1 页判「全齐」）和 `.claude/agents/requirement-writer.md`。

运行实例：后端按契约起两个进程（cwd=工作区目录，注入端口环境变量），端口从本机资源登记处申请（jereh 环境用 `resreg`），网址经共享网关 `web-gateways` 挂（每工作区一个 `server{}`，`proxy_pass` 到前端端口）；健康检查 `GET <devUrl><health>` 200 才算 running。挂网址的实现可配置 `AI_STUDIO_DEVURL_CMD`，未配置则只给本机地址 `http://127.0.0.1:<前端端口>/` 并在顶栏标「仅本机」。

### 9.3 需求会话
- `POST /projects/{id}/req-session`：幂等，返回 `{slotKey}`（`ai-studio-req-<id>`）。后端照 spec_builder `runtime.py` 的做法 `get_or_create_slot` 并设：`slot.project = 工作区目录`、`slot.title = "需求：<工作区名>"`、harness = Claude（`agent.acp_backend=claude`，经 `claude-agent-acp` 适配器）、agent = `requirement-writer`。首次创建时发首条提示语：「你在工作区 <名>（目录 <路径>）。需求图谱放 docs/需求图谱/。先读需求标准 v34 再开始。」
- `ChatPane` 改为先调这个接口拿 slotKey，再挂 ChatEmbed（不再自己 `POST /api/chat/slots`）。
- **要先验证的技术点（V1）**：Claude ACP 适配器下，会话是否加载工作区里的 `.claude/agents/requirement-writer.md` 并以它为主 agent（命令行下靠 `.claude/settings.local.json` 的 `"agent"` 生效，已实测）。验证不过的退路：首条提示语里让会话先读该 agent 文件并照做，界面显示「助手未以专用模式启动」。

**V1 结论（2026-10-08，ACP-2015-V1）**：通过（有条件——机制通了，但身份会与 Crew 人格竞争，不能当作已稳）
- 环境：网关 6790、vite 6791，`agent.acp_backend=claude`，模型来自 settings.jqw.json（会话实际解析到的模型 `Jereh-Qwen3.8-Flash-Next`）
- 做法：Spec Builder 建规格，working_dir=`/home/jereh/repo/jc/webapp-template-wt-kc-v1-probe`
- Claude 进程 cwd：`/home/jereh/repo/jc/webapp-template-wt-kc-v1-probe`（沙箱包装进程 3827563 → `claude-agent-acp` 3827575 → `claude` 子进程 3827701，三层 cwd 全是该目录）
- 首轮回复是否为 ≤5 道选择题：**是（就 §5.3 那句话而言）**，回复开头原文：「明白，做「设备点检记录」页。第一轮先问 4 件大的，每题最后一项都是「X. 其它」，可以直接文字回。 **问题 1：这页主要给谁用、拿来干什么？** - A. 车间班组长：现场填当天的设备点检情况 -」
- 退路（让会话先读 agent 文件）：未试（不需要——首轮即按 agent 规则说话）
- 结论对实现的影响：§9.3 不必再加退路，但**必须把 agent 身份当作可被覆盖的软约束**——见下三条实测边界

实测边界（三条，都影响 §9.3 的实现）：

1. **加载是真的**：`claude-agent-acp` 会把工作区 `.claude/settings.local.json` 的 `"agent"` 键透给 Claude CLI，内层 transcript 里能看到 `{"type":"agent-setting","agentSetting":"requirement-writer"}`（会话第 0 行，早于任何工具调用）与 `prompt_snapshot.systemPrompt` = 该 agent 文件正文。所以 §9.3「设 agent = requirement-writer」这条**不需要新接口**，靠工作区里那份 `settings.local.json` 就到位。
2. **但它压在 Crew 自己的提示词下面**：Crew 的 9.4 万字符人格提示词（`You are Kiro 👻`）是作为**第一条 user 消息**下发的，agent 正文只在 CLI 的 system prompt 槽里，两者会抢。实测同一个会话里，Spec Builder 的种子提示那一轮**没**走 agent 格式（一题、无「X. 其它」、按 Requirements→Design→Tasks 走），下一轮才回到 agent 格式。所以 §9.3 的首条提示语**不要再教它怎么工作**（只报工作区路径与图谱目录，别写「先写 requirements.md」这类工序指令），否则等于给竞争加砝码。界面也不宜按「首轮是否选择题」判定专用模式——那个信号本身会抖。
3. **工作区自带 `settings.local.json` 有两个副作用**：Crew 会**整份扣住 `mcpServers` 不发**（网关日志明写：该文件不是 Crew 写的，放行会绕过 `session/request_permission`），需求会话因此**拿不到 Crew 的 MCP 工具**；同时写文件要人在网页上点批准，无人应答 180 秒即自动拒绝（实测写 `.spec-state.json` 被这样拒掉）。§9.3 要写清这两条，或在 UI 上把「等待批准」显出来。

### 9.4 需求页

| 方法 路径 | 做什么 | 关键响应/错误 |
|---|---|---|
| `GET /projects/{id}/requirements` | 列需求页 | `[{page, graphHash, verdict, missingCount, updatedAt, devState}]` |
| `GET /projects/{id}/requirements/{page}` | 取一页 | `{graph, markdown, graphHash, docHash, verdict, errors, missing, tiers, devState, stale}`；`stale=true` = 文档还没按最新图谱重生成 |
| `POST /projects/{id}/requirements/{page}/direct-edit` | 直改：`{baseDocHash, markdown}` → 算出 diff，作为一条消息发给需求会话 | 409 `baseDocHash` 不是最新（别人或助手刚改过） |
| `POST /projects/{id}/requirements/{page}/start` | 开始开发：`{graphHash}`。后端当场跑 check；verdict 合格且 graphHash 一致才记开工请求、发 `StartRequested` | 409 `graph_changed`（hash 不一致）；422 `not_ready`（附 verdict、missing） |

生成与判定实现：调用可配置命令 `AI_STUDIO_REQDOC_CMD`（默认 `jc fe reqdoc`），`check <图谱> --frame <框架目录>` 与 `render <图谱> --out <同名.md>`；命令不可用返回 503 `reqdoc_cmd_unavailable`，界面判定条显示「判定服务不可用」，〔开始开发〕置灰。图谱变化检测：会话每轮结束时扫一次 `docs/需求图谱/`，并每 5 秒轮询文件 mtime（两者都触发 `GraphChanged`，按 hash 去重）。

开工请求存 `<工作区>/.ai-studio/start-requests.jsonl`（追加写，一行一条，不进 Git）。

### 9.5 顺手修
- 注册 `GET /publish/versions`（前端已在调，main 上缺），或从前端移除调用；二选一，以能列出工作区 Git 标签为准。

## 10. 验收标准（每条可自动测，括号里是测法）

1. 新建工作区「设备管理」代号 `eqp`：列表出现、进度五步全 ✓；工作区目录是 Git 仓，`git remote get-url origin` 指向个人仓，`git log origin/develop -1` 有提交。（后端集成测：用本地裸仓当模板和个人远端）
2. 同时建两个工作区，两者端口不同、都能 200 打开各自网址。（集成测）
3. 派生第 2 步故意失败（个人仓创建命令返回非 0）：状态 `failed`、`failedStep` = 该步、显示「<步骤名>失败：<错误原文>」；点〔重试这一步〕成功后继续。（集成测，替身命令）
4. 打开工作台：顶栏网址可点；右栏「需求」标签列出模板自带示例需求页，徽标为绿「全齐」。（前端 vitest + 后端集成）
5. 需求会话：`GET` 会话 slot 的 `project` = 工作区目录；agent = requirement-writer。（后端单测断言 slot 字段）
6. 让助手在图谱里加一条「待定」的规则（或测试直接写文件）：≤10 秒内判定条变红「不齐：还不能开发」，缺口清单含该句，〔开始开发〕置灰且提示「还不能开发：<第一条缺口>」。（e2e，测试直接改文件模拟助手）
7. 删掉那条规则：≤10 秒内回到绿「需求已齐，可以开发」。（e2e）
8. 把示例图谱的页面权限码清空：判定变黄「可以开工，但有 1 处已知缺口」；点〔开始开发〕先弹确认框。（e2e）
9. 直改：在编辑器里改一个按钮的提示语并保存 → 需求会话收到包含该 diff 的消息；判定条显示「改动待落回需求」直到图谱文件变化。（前端 + 后端集成，断言会话收到消息）
10. 开始开发：合格时 `POST .../start` 返回 200，`start-requests.jsonl` 多一行且 graphHash = 当时图谱 hash；页面显示「已开工请求，等待拆任务」。（集成测）
11. 并发改：前端带旧 graphHash 调 start → 409 `graph_changed`；图谱不齐时调 start → 422 `not_ready`。前端不得只凭自己显示的判定放行。（集成测）
12. 开工后再改图谱 → `devState` 回到 `editing`，显示「需求改了，要重新点开始开发」。（集成测）
13. 判定命令不可用 → 503 `reqdoc_cmd_unavailable`，判定条「判定服务不可用」，按钮置灰。（集成测，PATH 去掉命令）
14. 任一工作区生成的需求文档里搜不到「原页面」「旧页面」「.vue」「原接口」。（集成测扫 `docs/需求图谱/*.md`）

## 11. 与已有设计的关系

| 已有 | 关系 |
|---|---|
| `raw/ai-studio-acceptance/00-e2e-top-level.md`（main，定稿 v0.2）13 步主线 | 本 RFC 填的是 open-project、edit-requirement 两步，并把「判就绪」补进 freeze-requirement 之前。00 里「需求 agent 是唯一和用户说话的入口」与本 RFC 一致 |
| 07 `07-dev-dag-two-phase.md`（定稿第 12 轮，**只在 `KiroCrew-wt-req-design` 工作区未提交**） | 开发上下文的规格：DAG 视图、`/dev/dag`、`/dev/start`、两阶段验收门槛。本 RFC 的 `StartRequested` 是它的入口。**风险：该文件未入库，工作区一删就丢，需先提交** |
| `backend/devruns.py`（main，跑 BGDD 四关门禁、不派 AI） | 与 07 冲突（门禁顺序 vs DAG 调度）；本 RFC 不碰，开发上下文落地时二选一 |
| Spec Builder（`spec_builder/backend/runtime.py`） | 复用它「后端开会话并设 `slot.project`/`slot.model`/首条提示语」的写法；不复用它的 `.kiro/specs` 存储与批准流（我们的「批准」= 机器判定） |
| AI Studio `graph.py` 的 freeze/regen/distill（基于打包固定图） | 和需求图谱 v34 不是一回事。本 RFC 不删它，需求页走新接口；后续收敛另议 |
| jereh-cli `jc webapp init`、`jc fe reqdoc`、需求标准 v34、`requirement-writer` | 后端通过可配置命令调用，不把 jereh 专有逻辑写进 KiroCrew 代码 |

## 12. 复用与待建盘点（对 main `2bbdb2540`）

| 能力 | 状态 | 做法 |
|---|---|---|
| 工作区列表/路由/新建对话框 | 已有 | 改：加字段、分步进度、状态 |
| 派生 Git 仓 | 待建（命令侧已有） | 后端调 `AI_STUDIO_WORKSPACE_CMD` |
| 运行实例、端口、网址 | 待建 | 新 `backend/devinstance.py`；模板需改端口读环境变量 |
| 三栏布局、ChatEmbed | 已有 | ChatPane 改连需求会话 |
| 会话在工作区目录 + 指定 agent + Claude | 待建（底层支持） | 照 spec_builder 写 `req-session` 接口；V1 先验证 |
| Tiptap 文档编辑器 | 已有 | 新 `req` 标签复用 DocEditor；保存改走 direct-edit |
| 生成文档、三档判定 | 已有（jereh-cli） | 后端调 `AI_STUDIO_REQDOC_CMD` |
| 需求页列表、判定条、开始开发 | 待建 | 新 `backend/requirements.py` + 前端组件 |
| `GET /publish/versions` | 坏 | 顺手修（§9.5） |

## 13. 实施顺序（每步可单独合并）

1. **V1 验证**（半天）：Claude ACP 会话能否以工作区里的 `requirement-writer` 为主 agent。结论写回本 RFC §9.3。
2. **需求页只读**：`GET requirements`、判定条、DocEditor 只读显示、右栏「需求」标签。用 jereh-cli 自带样例当夹具。验收 4、13、14。
3. **需求会话**：`req-session` + ChatPane 改造 + 图谱变化检测。验收 5、6、7、8。
4. **直改与开始开发**：`direct-edit`、`start`、开工请求记录。验收 9~12。
5. **工作区派生与运行实例**：`POST /projects` 改造、`retry`、devinstance、顶栏。依赖模板仓改端口契约。验收 1~3。
6. 顺手修 `GET /publish/versions`。

先做 2~4 是因为它们只依赖已有的 jereh-cli 命令和一个已有目录，能最快在界面里把「聊需求 → 判齐 → 开始开发」跑一遍；5 依赖模板仓改动。

## 14. 留待决定（需求方拍板，不阻塞 2~4 步）
- 工作区代号默认怎么从中文名生成（拼音首字母 / 让用户必填）——本 RFC 暂按「默认拼音首字母、可改」。
- 删除工作区时是否连个人远端仓一起删——本 RFC 暂按「不删远端」（W4）。
