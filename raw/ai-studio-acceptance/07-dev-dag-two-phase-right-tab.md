---
title: 07 · dev-dag 调度与两阶段开发（演示版→验收→完整版）— 细节验收文档
doc-id: "07"
status: 初稿
expands: dev-demo-phase, demo-acceptance, dev-full-phase
parent: 00-e2e-top-level.md
owner: qinshuguo
maintainer: sid-req-design
updated: 2026-09-23
review: 待子代理全文体检
---

# 07 · dev-dag 调度与两阶段开发 — 细节验收文档

对应顶层：`00-e2e-top-level.md` 步骤 **dev-demo-phase → demo-acceptance → dev-full-phase**（前序 review-tasks，后序 publish-app）。

## 颗粒度约定（本文档的断言锚点规则）

- **前台断言只认 `data-testid`**，不认组件名、不认文案、不认 CSS。下列 testid 是契约：前端实现时必须带上，验收测试只按 testid 定位。
- **后台断言认端点**：每个后台事实给出「端点 + 请求/响应关键字段」，断言读 JSON，不读日志措辞。
- **进程级断言**（worktree 隔离/复用、dev agent 存活）用 `git worktree list`、目录路径、PID 探活，属于第三层锚点，只有它无法用前两层表达。

## 〇、入口与两阶段契约

- **入口在应用上下文内**：用户已打开某项目的工作台（路由 `/projects/<id>/ai-studio`），任务评审（06）通过后，在**右侧边栏点「开发」页签**进入开发面板（与 08 发布页签同构：页签本体挂 `ToolSidebar`，内容在右侧边栏内展开，**不进中央工作区**）；面板内出现**「开始开发」按钮**，点击即启动 dev-dag agent，先出**演示版**。
- **两阶段是硬顺序**：演示版（纯前端，可交互演示全部业务流程）→ 演示版端到端验收通过 + 用户确认 → 完整版（含后端）。**演示版未过验收不能进完整版**：完整版入口在演示版验收通过前不渲染（不是禁用）。
- **阶段标记是契约**：每次开发运行（dev run）带 `phase: "demo" | "full"`，全链路（DAG 视图、调度日志、验收记录、git tag）都携带该标记，不允许出现无阶段归属的运行。
- **验收通过 = 打 git tag**：演示版验收通过 → 对该版本 commit 打 tag 标注「演示版」；完整版验收通过 → 打 tag 标注「完整版」。**这两个 tag 就是 08 §三 B1 形态判定的取数来源**，本文档产出、08 消费，两边断言必须对得上。
- **调度规则（Owner 已拍板，顶层 §核心机制）**：dev-dag agent 读 Jira DAG（任务阻塞/被阻塞关系），领取无阻塞任务派给 dev agent；**并行任务各自独立 worktree，串行后继任务复用前驱的 worktree 目录**；全程有调度日志。

## 〇-1、开发页签的结构（入口断言的承接物）

「在右侧边栏点「开发」页签后开发面板展开」不是一句空话——展开的是下面这个固定结构，验收逐块对（与 08 发布页签同构：页签本体挂 `ToolSidebar`，下表全部区块都渲染在右侧边栏内，不进中央工作区）：

| 区块 | 承载 testid | 数据来源（承接前序） |
|---|---|---|
| 开发页签本体 | `ai-studio-dev-entry`（挂在 `ToolSidebar` 内，与 `ai-studio-publish-entry` 并列） | 页签已存在（现无 testid），本文要求补挂；点击即在右侧边栏展开下表内容 |
| 阶段容器（演示版/完整版两阶段） | `dev-phases` / `dev-phase-<阶段名>`（沿用既有 testid 契约，由开发页签内容渲染） | 阶段模型见 §〇；当前阶段高亮，未解锁阶段标「未解锁」 |
| 阶段标记 | `ai-studio-dev-phase-badge` | 文本=「演示版（纯前端）」或「完整版（含后端）」，与本次 run 的 `phase` 一致 |
| 任务 DAG 图 | `ai-studio-dev-dag`；节点=`ai-studio-dev-dag-node-<jiraKey>` | **承接 06-任务评审**：节点=评审通过的任务集（Jira 标签/状态过滤），边=Jira 阻塞关系；被砍任务不出现 |
| 节点状态 | `ai-studio-dev-dag-node-state-<jiraKey>` | 四态：排队 / 进行中 / 完成 / 失败；由 dev-dag 调度状态推导 |
| 节点执行体信息 | `ai-studio-dev-dag-node-agent-<jiraKey>` / `ai-studio-dev-dag-node-worktree-<jiraKey>` | 进行中的节点显示所属 dev agent 标识与 worktree 路径；非进行中不渲染 |
| 开始开发按钮 | `ai-studio-dev-start-btn`（演示版）/ `ai-studio-dev-full-start-btn`（完整版） | 渲染规则见 §〇 两阶段硬顺序；点击即启动，无确认弹层 |
| 调度日志 | `ai-studio-dev-dag-log` | 本步自身产出；流式增长，渲染复用 `DeployLog` 形态 |
| 验收区块 | `ai-studio-accept-run-btn` / `ai-studio-accept-result-list` / `ai-studio-accept-status` | DAG 全绿后出现；见 §〇-2 |

**与顶栏 `ReleaseControl` 的关系**：`dev-btn` 是演示工作台的三态一表桩，**不复用、不改动**（与 08 对 `release-btn` 的处理一致）；真实「开始开发」按钮由开发页签自建，testid 用上表的 `ai-studio-dev-start-btn`。

## 〇-2、验收区块的结构（demo-acceptance / dev-full-phase 收口）

DAG 全绿后，验收区块出现在开发页签内（右侧边栏）：

| 区块 | 承载 testid | 说明 |
|---|---|---|
| 执行验收入口 | `ai-studio-accept-run-btn` | 点击对当前阶段产物执行端到端验收测试套件（01~09 细节文档的断言集；演示版跑纯前端可执行子集，完整版跑全集） |
| 逐条结果列表 | `ai-studio-accept-result-list`；行=`ai-studio-accept-result-row-<断言id>` | 每行含断言 id、通过/失败、证据摘要；断言 id 可回指细节文档 |
| 验收总状态 | `ai-studio-accept-status` | 两态：通过 / 失败（含失败条数）；通过后固化，不可再变 |
| 验收形态徽标 | `ai-studio-accept-form-badge` | 文本=「演示版」或「完整版」，与 run 的 `phase` 一致 |
| 用户确认（仅演示版） | `ai-studio-accept-confirm-btn`（继续开发完整版）/ `ai-studio-accept-reject-btn`（回退改需求） | 验收通过后出现；确认→渲染 `ai-studio-dev-full-start-btn`；回退→跳回需求文档编辑器（02 的 edit-requirement 入口），本轮不打「验收通过」标 |

**回边语义**：`ai-studio-accept-reject-btn` 是顶层 demo-acceptance 的回边（→edit-requirement）。回退后开发运行保留历史记录（状态=已中止），不产生验收通过记录、不打 tag。

## 一、开发前的状态前提（fixture）

| 前提 | 断言方式 |
|---|---|
| 目标项目存在已冻结需求基线与已同步 Jira 的任务集 | 04/05 的冻结记录、Jira 任务列表接口返回非空 |
| 任务集中至少含一对**并行任务**（互不阻塞）与一条**串行链**（A 阻塞 B） | Jira 阻塞关系可查；这是 worktree 隔离/复用断言的前提 |
| 全部任务已评审通过（06 完成） | 任务带评审通过标签/状态；未评审任务存在时「开始开发」不渲染 |
| 项目已有关联代码库 | dev run 启动不报仓库缺失 |

## 二、前台操作与断言（data-testid）

### 场景 A：演示版开发——DAG 调度真实发生

| # | 操作 | 定位 | 断言 |
|---|---|---|---|
| A1 | 在右侧边栏点「开发」页签 | `ai-studio-dev-entry`（页签本体，挂在 `ToolSidebar` 内） | 可见、可点击；点击后开发面板在右侧边栏展开；`dev-phases` / `dev-phase-<阶段名>` 两阶段容器可见，演示版阶段=当前、完整版阶段标「未解锁」；`ai-studio-dev-start-btn` 渲染 |
| A2 | 点击「开始开发」 | `ai-studio-dev-start-btn` | 点击后直接进入调度（无确认弹层）；`ai-studio-dev-phase-badge` 文本=「演示版（纯前端）」 |
| A3 | DAG 渲染 | `ai-studio-dev-dag` | 节点集=评审通过任务集（逐个 jiraKey 对得上，被砍任务不在）；边与 Jira 阻塞关系一致 |
| A4 | 节点状态流转 | `ai-studio-dev-dag-node-state-<jiraKey>` | 无阻塞节点先「进行中」，被阻塞节点保持「排队」；前驱完成后后继自动流转（轮询刷新，非一次性文案） |
| A5 | 执行体信息 | `ai-studio-dev-dag-node-agent-<jiraKey>` / `ai-studio-dev-dag-node-worktree-<jiraKey>` | 进行中节点两者可见且非空；worktree 路径与进程级断言（§四）实测一致 |
| A6 | 调度日志流式 | `ai-studio-dev-dag-log` | 日志文本随时间增长（两次采样行数递增）；含派单、完成、worktree 分配事件 |
| A7 | DAG 全绿 | `ai-studio-dev-dag-node-state-<jiraKey>`（全部） | 全部节点=「完成」；验收区块出现（`ai-studio-accept-run-btn` 可见） |

### 场景 B：演示版验收与用户确认

| # | 操作 | 定位 | 断言 |
|---|---|---|---|
| B1 | 点击「执行验收」 | `ai-studio-accept-run-btn` | 结果列表逐条出现 `ai-studio-accept-result-row-<断言id>`；`ai-studio-accept-form-badge`=「演示版」 |
| B2 | 验收全绿 | `ai-studio-accept-status` | 文本=「通过」；状态固化（刷新页面后仍为通过）；后台验收记录生成（§三 B4） |
| B3 | tag 落地 | —（后台断言，见 §三 B4） | 该版本 commit 已打「演示版」tag——08 B1 形态判定由此取数 |
| B4 | 用户确认 | `ai-studio-accept-confirm-btn` / `ai-studio-accept-reject-btn` | 验收通过后两者出现；点确认→`ai-studio-dev-full-start-btn` 渲染，完整版阶段解锁 |
| B5 | 回边（另起一轮跑） | `ai-studio-accept-reject-btn` | 点击后回到需求文档编辑器（DocEditor 的 `doc-<文档名>` 可见）；本轮 run 状态=已中止；无验收通过记录、无 tag |

### 场景 C：完整版开发（复用 A 的调度规则）

| # | 操作 | 定位 | 断言 |
|---|---|---|---|
| C1 | 点击「开发完整版」 | `ai-studio-dev-full-start-btn` | 仅在 B4 确认后可见可点；`ai-studio-dev-phase-badge`=「完整版（含后端）」 |
| C2 | DAG 调度 | 同 A3~A6 | 后端任务出现在 DAG 中并按阻塞关系流转；worktree 隔离/复用规则同演示版 |
| C3 | 全绿后验收 | 同 B1~B3 | `ai-studio-accept-form-badge`=「完整版」；通过后 commit 打「完整版」tag |

### 场景 D：门禁与失败路径

| # | 操作 | 断言 |
|---|---|---|
| D1 | 演示版未验收通过时看完整版入口 | `ai-studio-dev-full-start-btn` **不存在于 DOM**（不是禁用，是不渲染）；直接调 §三 B2 带 `phase:"full"` 返回 409 |
| D2 | 制造一个任务失败（如断言必败的子任务） | 该节点 `ai-studio-dev-dag-node-state-<jiraKey>`=「失败」；`ai-studio-dev-dag-log` 含失败原因；被它阻塞的后继停留「排队」；验收区块不出现（不许假全绿） |
| D3 | 存在未评审任务时 | `ai-studio-dev-start-btn` 不渲染 |

## 三、后台断言（端点）

> 端点路径前缀 `/api/apps/ai-studio`；最终路径以实现为准，实现时若调整必须同步改本文档（同一提交）。

| # | 事实 | 端点 | 断言字段 |
|---|---|---|---|
| B1 | DAG 取数 | `GET /dev/dag?project&phase` | 节点含 `jiraKey`、`dependsOn`、`state: "queued"|"running"|"done"|"failed"`、`agent`、`worktree`；节点集=评审通过任务集；`dependsOn` 与 Jira 阻塞关系一致 |
| B2 | 启动开发 | `POST /dev/start` body `{project, phase}` | 响应含 `runId` 与 `phase`；演示版未过验收时 `phase:"full"` → 409；同 phase 运行中再调 → 409 |
| B3 | 调度日志流 | `GET /dev/run/<runId>/log`（流式） | 日志行随时间增长；含 worktree 分配事件（可与 §四 实测路径互证） |
| B4 | 验收执行与记录 | `POST /accept/run` body `{project, version, phase}`；`GET /accept/records?project` | 记录含 `phase`、`result: "passed"|"failed"`、逐条断言结果、`requirementVersion`（关联冻结基线）、`commitHash`；passed 记录生成后对应 commit 的 git tag 可查（演示版/完整版标注）——**08 §三 B1 的判定来源就是这里的 tag** |
| B5 | 阶段门禁 | `GET /dev/state?project` | 含 `demoAccepted: bool`、`fullAccepted: bool`；`demoAccepted=false` 时 B2 的 full 请求必 409 |

## 四、进程级断言（worktree 隔离/复用）

1. **并行隔离**：A4 出现两个并行「进行中」节点时，`git worktree list`（项目代码库）含两条不同路径，与两节点的 `ai-studio-dev-dag-node-worktree-<jiraKey>` 文本逐字一致。
2. **串行复用**：串行链前驱完成、后继进行中时，后继节点的 worktree 路径与前驱**相同**（复用，不新开目录）；`git worktree list` 不新增条目。
3. **dev agent 存活**：进行中节点的 `agent` 标识对应真实进程（PID 探活）；节点转「完成」后该 PID 允许消失。
4. **无目录爆炸**：整轮 run 结束后，`git worktree list` 条目数 ≤ 并行度峰值（串行链不累积目录）。

## 五、自检清单（本文档验收 = 以下全勾）

- [ ] 场景 A/B/C/D 各跑一遍，前台断言全部只依赖 data-testid
- [ ] 开发面板是右侧边栏页签（`ai-studio-dev-entry`，与发布页签并列），内容在边栏内展开、不进中央工作区（与 08 发布页签同构）
- [ ] DAG 节点集与 06 评审通过任务集一致，边与 Jira 阻塞关系一致（无中生有的节点/边 = 造假）
- [ ] 并行任务 worktree 隔离、串行任务 worktree 复用，§四 四条全过
- [ ] 调度日志流式增长，含派单/完成/worktree 分配事件
- [ ] 演示版未过验收：完整版入口不渲染、B2 full 请求 409（D1）
- [ ] 演示版验收通过：`ai-studio-accept-status` 固化、commit 打「演示版」tag（08 B1 可读到）
- [ ] 回边可用：reject 后回到 DocEditor，本轮无验收记录、无 tag（B5）
- [ ] 完整版验收通过：commit 打「完整版」tag；08 的形态判定据此发完整版
- [ ] 失败路径不假绿：节点「失败」+ 日志含原因 + 验收区块不出现（D2）
- [ ] 验收记录可追溯到 requirementVersion（冻结基线）

## 六、前端组件枚举与复用（防膨胀）

原则：**先复用现有组件，再新建**；本文档的 testid 挂在组件渲染出的 DOM 元素上——验收只认 testid，组件重构不毁断言，但 testid 不许丢。

### 复用与澄清（本文不新建的部分）

| 组件（`website/src/apps/ai-studio/`） | 现有 testid | 本文如何用 |
|---|---|---|
| `ToolSidebar.tsx` | `tool-sidebar` | 开发页签挂在它内（与发布页签 `ai-studio-publish-entry` 并列），不新建侧栏壳 |
| `DevRunView.tsx`（仅阶段容器 testid 契约） | `dev-phases` / `dev-phase-<阶段名>` | 两阶段容器沿用其 testid 契约（演示版/完整版各占一个 `dev-phase-<阶段名>`），但**渲染位置改到右侧边栏开发页签内**——开发不再是中央工作区视图，`DevRunView` 这个中央视图组件不再作为开发的家；其 `dev-run-panel` / `dev-artifact-<种类>` / `dev-runnable-version` / `run-*` 等中央视图专属 testid 本文不用 |
| `DeployLog.tsx` | `deploy-log-<部署id>` | 调度日志渲染复用它（同 08 对发布日志的处理），`runId` 对接 §三 B3 |
| `DocEditor.tsx` | `doc-<文档名>` | 回边（B5）的落点断言用它，不新建编辑器入口 |
| `ReleaseControl.tsx` | `dev-btn` | **不复用、不改动**：它是顶栏演示桩；真实开始开发按钮由开发页签自建（`ai-studio-dev-start-btn`） |

### 新建（仅此四件，超出需先改本文档）

| 新组件 | 承载 testid | 理由 |
|---|---|---|
| 开发页签（现有 `ToolSidebar` 的 dev 页签） | `ai-studio-dev-entry` | 页签本体已存在（现无 testid），**本条只要求补挂 testid**；其内容从现有 fixture 桩（`ReleasesTool` + `DEV`/`DEV_HISTORY`）换成真实开发执行内容（见下行）——与 08 发布页签把 fixture 桩换成 `PublishVersionList` 同构 |
| 开发页签内容（阶段容器 + 任务 DAG + 调度日志区，挂 dev 页签内） | `dev-phases` / `dev-phase-<阶段名>`（沿用 `DevRunView` 契约）/ `ai-studio-dev-dag` / `ai-studio-dev-dag-node-<jiraKey>` / `ai-studio-dev-dag-node-state-<jiraKey>` / `ai-studio-dev-dag-node-agent-<jiraKey>` / `ai-studio-dev-dag-node-worktree-<jiraKey>` / `ai-studio-dev-dag-log` | 现无按 Jira 阻塞关系渲染的任务 DAG；`GraphView` 是需求图谱视图，数据源与语义都不同，不许挪用；调度日志条渲染复用 `DeployLog` 形态 |
| 开发运行控制条（开始开发/开发完整版/阶段徽标） | `ai-studio-dev-start-btn` / `ai-studio-dev-full-start-btn` / `ai-studio-dev-phase-badge` | 现无真实开发启动入口（`dev-btn` 是桩）；两阶段门禁的渲染规则是本文新语义 |
| 验收区块（执行验收/逐条结果/确认与回退） | `ai-studio-accept-run-btn` / `ai-studio-accept-result-list` / `ai-studio-accept-result-row-<断言id>` / `ai-studio-accept-status` / `ai-studio-accept-form-badge` / `ai-studio-accept-confirm-btn` / `ai-studio-accept-reject-btn` | 现无端到端验收的执行与结果视图；「验收通过」状态是 08 形态判定的上游事实，必须有自己的承载处 |

**禁止**：为调度再造第二套日志视图、把需求 `GraphView` 挪来画任务 DAG、把开发塞回中央工作区视图（开发是右侧边栏页签，与发布页签同构，不是 `WorkArea` 视图）、给 `dev-btn` 接真实端点、任何绕过阶段门禁的直达入口。发现要新建第五个组件时，先回来改本节。

## 七、与相邻文档的衔接

- **承接 06（review-tasks）**：DAG 节点集=评审通过任务集；未评审/被砍任务不进入本文任何视图。
- **产出给 08（publish-app）**：① 版本 commit 的 git tag（演示版/完整版）——08 §〇-1 行内形态判定与 §三 B1 的取数来源；② 验收记录（§三 B4）——08 形态判定「完整版过→发完整版 / 仅演示版过→只发演示版 / 都没过→拒发」的事实依据。两边字段（`phase`/`form`、`commitHash`）必须同名同义。
- **回边给 02（edit-requirement）**：B5 回退的落点是 DocEditor，产生新一轮奇数版本走 02→…→07 重跑。
