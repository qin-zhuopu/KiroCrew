# 08 · 发布应用（按验收状态定形态）— 细节验收文档

对应顶层：`00-e2e-top-level.md` 步骤 **publish-app**（前序 dev-full-phase，后序 view-history）。

## 颗粒度约定（本文档的断言锚点规则）

- **前台断言只认 `data-testid`**，不认组件名、不认文案、不认 CSS。下列 testid 是契约：前端实现时必须带上，验收测试只按 testid 定位。
- **后台断言认端点**：每个后台事实给出「端点 + 请求/响应关键字段」，断言读 JSON，不读日志措辞。
- **进程级断言**（停旧起新）用 PID/端口/HTTP 探活，属于第三层锚点，只有它无法用前两层表达。

## 〇、发布入口与域名契约

- **入口在应用上下文内**：用户已打开某项目的工作台（路由 `/projects/<id>/ai-studio`），在**右侧边栏点「发布」页签**进入发布视图，对着**版本列表里的某一行**发版；版本号是前序步骤（提交/开发/验收）产生的，本步**没有任何版本选择器或手输框**——用户看到的就是版本列表，点哪行发哪行。
- **域名模板**：`{版本号}-{应用名}-{工号}.gb10.jereh-pe.cn`
  - 版本号在域名最前段；例：应用 `crm`、版本 `v3`、工号 `14409` → `v3-crm-14409.gb10.jereh-pe.cn`
  - 断言：`ai-studio-publish-url-<版本号>` 的 href 必须逐字匹配该模板；版本号/应用名/工号三段都要与当前上下文一致，不允许出现与所发版本不符的域名。
- **发布按钮按「版本 hash vs 最新发布 hash」对比决定渲染**（Owner 已拍板）：每个版本对应一个 commit hash。对列表里的每一行，将其 hash 与**当前最新一次成功发布的 hash** 对比：相同 → 该行**不渲染发布按钮**、行状态标「已发布」（不渲染，不是禁用）；不同 → 该行正常渲染发布按钮（含 hash 发布过但非最新的旧版本——那是一次回滚式重发）。再发与最新 hash 相同的版本不产生新实例、不产生新记录。

## 〇-1、发布视图的结构（入口断言的承接物）

「点击发布页签后发布视图在右侧边栏展开」不是一句空话——展开的是下面这个固定结构，验收逐块对：

| 区块 | 承载 testid | 数据来源（承接前序） |
|---|---|---|
| 版本列表（每版本一行） | `ai-studio-publish-version-list`；行=`ai-studio-publish-version-row-<版本号>` | **承接 02-需求文档修改与提交**：行=该项目已提交的版本，与 DocEditor `version-history-list` 同源数据（版本快照接口），不是另造的版本来源；行内含版本号与其 commit hash |
| 行内发布状态 | `ai-studio-publish-version-state`（行内） | 已发布/未发布两态；由发布记录推导（无记录=未发布） |
| 行内发布按钮 | `ai-studio-publish-btn-<版本号>` | 渲染与否=hash 对比规则（见 §〇）；点击即发布，无确认弹层、无表单 |
| 行内形态判定与原因 | `ai-studio-publish-reason-<版本号>`（行内） | 承接 07 的验收记录（demo/full 通过状态）；未过验收的行在这里给出不可发的原因 |
| 行内发布结果 | `ai-studio-publish-status-<版本号>` / `ai-studio-publish-form-badge-<版本号>` / `ai-studio-publish-url-<版本号>` / `ai-studio-publish-record-<版本号>` | 本步自身产出，发布后出现在该行内 |
| 行内发布号链接 | `ai-studio-publish-id-<版本号>`（链接，指向发布详情页） | 点击发布后行状态=「发布中」并出现发布号；点它在新页签打开 `/release-jobs/<发布号>`（见 §〇-2） |

**行内空间规划（侧栏窄，逐列排布，不许折行堆叠）**：

| 列 | 内容 | 承载 |
|---|---|---|
| 版本 | 版本号 + 短 hash | 行本体文本 |
| 状态 | 未发布 / 发布中 / 已发布 / 失败 | `ai-studio-publish-version-state` |
| 动作 | 发布按钮（hash 规则决定渲染）或形态判定原因（挤不进时收进行内 title/悬浮提示） | `ai-studio-publish-btn-<版本号>` / `ai-studio-publish-reason-<版本号>` |
| 链接 | **发布地址写在 `<a href>` 里**（列内显示短文案如「打开」，不裸贴长 URL）；发布号同理是 `<a href>` 指向 `/release-jobs/<发布号>` | `ai-studio-publish-url-<版本号>` / `ai-studio-publish-id-<版本号>` |

断言不变：`ai-studio-publish-url-<版本号>` 的 **href** 逐字匹配域名模板（显示文案可以短，href 必须全量）。

后序文档（09 view-history）承接本步的产出：发布记录、应用地址——已在其视图内列为可跳转节点。

## 〇-2、发布详情页（Jenkins 式发布历史 + 流式日志）

**两个概念，不许混用**（Owner 已拍板）：

- **release-job（发布任务）**：点一次发布按钮产生的一个**执行体**——有发布号、有状态（发布中/成功/失败）、有流式日志。失败的任务不产生任何对外结果。侧栏行内出现、以及详情页 `/release-jobs/<发布号>` 列出的历史，都是 release-job。
- **release（发布结果）**：release-job **成功后**产生的对外事实——某版本的应用以某形态在某个 URL 上服务。侧栏行内的「已发布」状态、`ai-studio-publish-url-<版本号>`、「最新发布 hash」的判定，都读 release，不读任务。

点击发布后，行状态=「发布中」，行内出现**发布号**；点发布号**在新页签打开** `/release-jobs/<发布号>`——一个独立页面，像 Jenkins 一样：

- **发布历史列表**：该项目全部 **release-job** 逐条列出（含本条），进行中的置顶；每条含发布号、版本号、形态、状态、时间。
- **流式日志**：对**正在发布**的那条，页面下方流式输出发布日志（边发边长，非完成后一次性展示）；已完成的记录打开则是完整日志回放。

| 断言点 | testid / 端点 |
|---|---|
| 详情页路由 | 新页签 URL=`/release-jobs/<发布号>`；断言 `window.location.pathname` 匹配 |
| 页面本体 | `ai-studio-release-job-page` |
| 发布历史列表 | `ai-studio-release-job-history-list`；行=`ai-studio-release-job-row-<发布号>` |
| 行内状态 | `ai-studio-release-job-status-<发布号>`：发布中/成功/失败 |
| 流式日志 | `ai-studio-release-job-log-<发布号>`：进行中的记录，日志文本随时间增长（断言两次采样行数递增且最终含完成标记）；日志渲染复用 `DeployLog` 形态 |
| 后台日志流 | `GET /publish/<deploymentId>/log`（流式；最终路径以实现为准，调整须同提交改本文档） |

## 一、发布前的状态前提（fixture）

| 前提 | 断言方式 |
|---|---|
| 目标项目存在至少一个已提交版本 | 版本列表接口返回该版本 |
| 每个候选版本有验收记录，且记录里演示版/完整版各自带 通过/未通过 状态 | 验收记录端点（见 §三 B1） |
| 当前存在一个"旧实例"在跑（已发布过的应用） | 旧实例探活 URL 返回 200 |

## 二、前台操作与断言（data-testid）

### 场景 A：完整版已过验收 → 发布完整版

| # | 操作 | 定位 | 断言 |
|---|---|---|---|
| A1 | 在右侧边栏点「发布」页签 | `ai-studio-publish-entry`（页签本体，挂在 ToolSidebar 内） | 可见、可点击；点击后发布视图在右侧边栏展开，展开结构=§〇-1 的固定区块表：版本列表逐行列出前序提交产生的版本（每行可见版本号），无任何版本下拉或手输框 |
| A2 | 找到目标版本行 | `ai-studio-publish-version-row-<版本号>` | 该行渲染 `ai-studio-publish-btn-<版本号>`（其 hash ≠ 最新发布 hash）；行状态 `ai-studio-publish-version-state` 文本=「未发布」 |
| A3 | 点击该行的发布按钮 | `ai-studio-publish-btn-<版本号>` | 点击后**直接进入发布**（无确认弹层、无表单提交）；行状态改为「发布中」，行内出现发布号链接 `ai-studio-publish-id-<版本号>`；`ai-studio-publish-status-<版本号>` 文本含「发布中」（轮询刷新，非一次性文案） |
| A4 | 发布成功 | `ai-studio-publish-status-<版本号>` | 文本含「发布成功」 |
| A5 | 形态标识 | `ai-studio-publish-form-badge-<版本号>` | 文本=「完整版」 |
| A6 | 发布地址可点 | `ai-studio-publish-url-<版本号>`（链接） | 发布成功后该行内可见；href 匹配域名模板 `{版本号}-{应用名}-{工号}.gb10.jereh-pe.cn`；点击在**新页签**打开发布好的应用地址（见 §四探活） |
| A7 | 发布记录可见 | `ai-studio-publish-record-<版本号>` | 含：版本号、形态、需求版本号、关联 Jira 任务号 |
| A8 | 行状态回写 | — | 该行「未发布」→「已发布」，且 `ai-studio-publish-btn-<版本号>` **从 DOM 消失**（其 hash 已成最新发布 hash）；其余版本行的按钮与状态不变 |

### 场景 B：仅演示版过验收 → 只发演示版

在 A 的基础上：A5 徽标文本=「演示版」；该行 `ai-studio-publish-reason-<版本号>` 含「完整版未通过验收」。其余步骤同 A。

### 场景 C：都没过验收 → 该行不可发布

| # | 操作 | 断言 |
|---|---|---|
| C1 | 看该版本行 | `ai-studio-publish-btn-<版本号>` **不存在于 DOM**（不可点击发布）；行内 `ai-studio-publish-reason-<版本号>` 可见且含「验收未通过」 |
| C2 | — | `ai-studio-publish-version-state` 文本=「未发布」（不可发布≠已发布） |

### 场景 D：版本 hash 与最新发布 hash 相同 → 无发布按钮（幂等）

| # | 操作 | 断言 |
|---|---|---|
| D1 | 看一个版本行，其 commit hash 与最新一次成功发布的 hash 相同 | `ai-studio-publish-btn-<版本号>` **不存在于 DOM**（不是禁用，是不渲染）；`ai-studio-publish-url-<版本号>` 仍可见可点（指向已有发布地址） |
| D2 | — | 该行 `ai-studio-publish-version-state`=「已发布」；重复进入发布视图，不产生第二条发布记录（B3 记录数不变） |
| D3 | 看一个 hash 发布过但**非最新**的旧版本行（发新版后回看旧版） | `ai-studio-publish-btn-<版本号>` 正常渲染（回滚式重发允许）；点击后走 A3~A8；成功后最新发布 hash 指向旧 hash，原最新版本行的按钮恢复渲染（其 hash 不再是最新发布 hash）。**（语义待 owner 确认）** |

## 三、后台断言（端点）

> 端点路径前缀 `/api/apps/ai-studio`；最终路径以实现为准，实现时若调整必须同步改本文档（同一提交）。

| # | 事实 | 端点 | 断言字段 |
|---|---|---|---|
| B1 | 逐版本形态判定 | `GET /publish/preview?project&version` | `form: "full"|"demo"|"rejected"`；`reason` 非空；判定来源=验收记录（`acceptanceRef` 指向具体验收记录 id）。发布视图的行内 reason/按钮渲染取数于此 |
| B2 | 触发发布（行按钮点击） | `POST /publish` body `{project, version, commitHash}` | 响应含 `deploymentId`；`commitHash` 与最新成功发布的 hash 相同 → 不新建部署，返回既有 `deploymentId` 与 `idempotent: true`；hash 非最新（含发布过的旧 hash）→ 正常新建部署（回滚式重发）；同 hash 发布进行中再调返回 409 |
| B3 | 发布记录 | `GET /publish/records?project` | 最新记录含：`form`、`version`、`requirementVersion`（关联冻结的需求版本）、`jiraTaskIds` 非空、`status: "success"`、`url`（url 逐字符合域名模板） |
| B4 | 行内两态来源 | `GET /publish/records?project` | 每个版本可由记录推导出 已发布/未发布 两态；行渲染与该数据一致（无记录=未发布）；「最新发布 hash」也由该接口推导（最新 `status:"success"` 记录的 hash） |
| B5 | 旧实例被替换 | 探活（无端点，见 §四） | 发布前记录旧 URL 的进程标识，发布后该实例不复存在 |

**幂等与并发**：B2 返回 409 的场景必须有（发布进行中重复触发）；发布失败（构建失败/端口占用）时 B2 响应 `status:"failed"` 且 `ai-studio-publish-status-<版本号>` 文本含「失败」+原因。

## 四、进程级断言（停旧起新）

1. 发布前：`curl -s -o /dev/null -w '%{http_code}' <旧实例URL>` = 200，记录其 PID（或容器 id）。
2. 发布后：旧 PID 不存在（`kill -0` 报错）或旧端口无监听（`ss -tln` 不含旧端口）。
3. 新实例：`ai-studio-publish-url-<版本号>` 的 href 探活 = 200，且页面能完成一次核心操作（用被发布形态自己的验收断言集跑最小一条，完整版用完整版断言、演示版用演示版断言）。
4. **单实例替换语义**：同一时刻同一项目只有一个实例在服务；不允许新旧并存。

## 五、自检清单（本文档验收 = 以下全勾）

- [ ] 场景 A/B/C/D 各跑一遍，前台断言全部只依赖 data-testid
- [ ] 发布视图无版本选择器、无手输框：版本列表逐行呈现，操作只发生在行内
- [ ] 发布地址逐字匹配 `{版本号}-{应用名}-{工号}.gb10.jereh-pe.cn`
- [ ] 每行已发/未发两态；A 场景发布后对应行从未发布翻成已发布、按钮消失，其余行不变
- [ ] B1 的 `form` 与场景设置的验收记录一一对应（改验收记录→行内判定与按钮渲染跟着变）
- [ ] B3 发布记录可追溯到 requirementVersion 与 jiraTaskIds
- [ ] §四 的停旧起新四条全过，且有「发布前旧实例 200」的前置证据
- [ ] 场景 D：版本 hash 与最新发布 hash 相同 → 行内不渲染按钮，重复进入不新增发布记录；旧 hash（非最新）→ 按钮正常渲染，可回滚式重发（D3）
- [ ] 失败路径：制造一次构建失败，`status:"failed"` + 行内失败提示可见
- [ ] 并发路径：发布进行中再触发，409 + 该行不出现两个「发布中」
- [ ] §〇-2 发布详情页：发布号链接新页签打开 `/release-jobs/<发布号>`；历史列表齐全；进行中记录日志流式增长、完成后可回放

## 六、前端组件枚举与复用（防膨胀）

原则：**先复用现有组件，再新建**；本文档的 testid 挂在组件渲染出的 DOM 元素上——验收只认 testid，组件重构不毁断言，但 testid 不许丢。

### 复用（不新建）

| 组件（`website/src/apps/ai-studio/`） | 现有 testid | 本文如何用 |
|---|---|---|
| `ReleaseControl.tsx` | `release-btn` / `distill-btn` / `dev-btn` | **行内发布按钮复用它**，即 `ai-studio-publish-btn-<版本号>` = `release-btn` 所在实例（每版本行一份）；不另造发布按钮 |
| `DeployLog.tsx` | `deploy-log-{id}` | 发布过程日志直接用它渲染，`deploymentId` 对接 §三 B2 |
| `CommitView.tsx` / 版本列表相关 | `version-history-list` 等 | 版本列表数据来源（前序产生），发布视图的版本列表从这里取数，不重复实现版本来源 |
| `ToolSidebar.tsx` | `tool-sidebar` | 发布页签挂在它内，不新建侧栏壳 |

### 新建（仅此四件，超出需先改本文档）

| 新组件 | 承载 testid | 理由 |
|---|---|---|
| 发布页签（ToolSidebar 内新页签） | `ai-studio-publish-entry` | 右边栏现有页签不含发布 |
| 发布版本列表（行=版本+状态+按钮+原因） | `ai-studio-publish-version-list` / `ai-studio-publish-version-row-<版本号>` / `ai-studio-publish-version-state` / `ai-studio-publish-reason-<版本号>` | 现无「每行可发布」的版本列表；列表数据复用版本接口，但行内发布语义是新内容 |
| 行内发布结果条（状态+徽标+地址+记录） | `ai-studio-publish-status-<版本号>` / `ai-studio-publish-form-badge-<版本号>` / `ai-studio-publish-url-<版本号>` / `ai-studio-publish-record-<版本号>` / `ai-studio-publish-id-<版本号>` | 现无对应物 |
| 发布详情页 ReleaseJobPage（独立路由 `/release-jobs/<发布号>`，历史列表+流式日志） | `ai-studio-release-job-page` / `ai-studio-release-job-history-list` / `ai-studio-release-job-row-<发布号>` / `ai-studio-release-job-status-<发布号>` / `ai-studio-release-job-log-<发布号>` | Jenkins 式发布历史与流式日志，现无对应页面；日志渲染复用 `DeployLog` 形态，不另造日志组件 |

**禁止**：为发布再造第二套版本列表、第二套日志视图、第二套确认按钮、任何版本选择器/手输框。发现要新建第五个组件时，先回来改本节。
