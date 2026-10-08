---
title: 07 · dev-dag 调度与两阶段开发（演示版→验收→完整版）— 细节验收文档
doc-id: "07"
status: 定稿
expands: dev-demo-phase, demo-acceptance, dev-full-phase
parent: 00-e2e-top-level.md
owner: qinshuguo
maintainer: sid-req-design
updated: 2026-09-23
review: 子代理第 12 轮评审：通过（无严重问题；3 条建议已采纳）；门禁 rules 57==57 / selftest 87/87 / validate 通过 / render --check 产物一致
---

# 07 · dev-dag 调度与两阶段开发 — 细节验收文档

对应顶层：`00-e2e-top-level.md` 步骤 **dev-demo-phase → demo-acceptance → dev-full-phase**（前序 review-tasks，后序 publish-app）。

## 颗粒度约定（本文档的断言锚点规则）

- **前台断言只认 `data-testid`**，不认组件名、不认文案、不认 CSS。下列 testid 是契约：前端实现时必须带上，验收测试只按 testid 定位。
- **后台断言认端点**：每个后台事实给出「端点 + 请求/响应关键字段」，断言读 JSON，不读日志措辞。
- **进程级断言**（worktree 隔离/复用、dev agent 存活）用 `git worktree list`、目录路径、PID 探活，属于第三层锚点，只有它无法用前两层表达。

## 〇、入口与两阶段契约

- **入口在应用上下文内**：用户已打开某项目的工作台（路由 `/projects/<id>/ai-studio`），任务评审（06）通过后，开发视图出现**「开始开发」按钮**；点击即启动 dev-dag agent，先出**演示版**。
- **两阶段是硬顺序**：演示版（纯前端，可交互演示全部业务流程）→ 演示版端到端验收通过 + 用户确认 → 完整版（含后端）。**演示版未过验收不能进完整版**：完整版入口要两个条件都满足才渲染（不是禁用）——① 演示版端到端验收通过，**且** ② 用户在验收区块点了「继续开发完整版」；只满足①时入口仍不渲染。**两个条件都是后台可判的事实，不是纯画面门禁**（§三 B5 的 `demoAccepted` 与 `demoConfirmed` 两个布尔字段，缺一不可）。
- **阶段标记是契约**：每次开发运行（dev run）带 `phase: "demo" | "full"`，全链路（DAG 视图、调度日志、验收记录、git tag）都携带该标记，不允许出现无阶段归属的运行。
- **验收通过 = 打 git tag**：演示版验收通过 → 对该版本 commit 打 tag 标注「演示版」；完整版验收通过 → 打 tag 标注「完整版」。**这两个 tag 就是 08 §三 B1 形态判定的取数来源**，本文档产出、08 消费，两边断言必须对得上。
- **回退即撤销（不许留记录不放行）**：用户在验收区块点「回退改需求」时，本轮验收结论一并撤销——该条 passed 记录标记作废（§三 B4 的 `voided: true`）、对应 git tag **删除**、`demoAccepted` 复位为 `false`（§三 B5）。**不能只让画面回到编辑器而把 tag 留着**：留着 tag 时 08 §三 B1 会把这个「已被打回改需求」的版本判成可发布的演示版，回边形同虚设。
- **调度规则（Owner 已拍板，顶层 §核心机制）**：dev-dag agent 读 Jira DAG（任务阻塞/被阻塞关系），领取无阻塞任务派给 dev agent；**并行任务各自独立 worktree，串行后继任务复用前驱的 worktree 目录**；全程有调度日志。

## 〇-1、开发执行视图的结构（入口断言的承接物）

「点击开始开发后进入开发执行视图」不是一句空话——展开的是下面这个固定结构，验收逐块对：
| 区块 | 承载 testid | 数据来源（承接前序） |
|---|---|---|
| 阶段容器（演示版/完整版两阶段） | 复用 `DevRunView` 的 `dev-phases` / `dev-phase-<阶段名>` | 阶段模型见 §〇；当前阶段高亮，未解锁阶段标「未解锁」 |
| 阶段标记 | `ai-studio-dev-phase-badge` | 文本=「演示版（纯前端）」或「完整版（含后端）」，与本次 run 的 `phase` 一致 |
| 任务 DAG 图 | `ai-studio-dev-dag`；节点=`ai-studio-dev-dag-node-<jiraKey>` | **承接 06-任务评审**：节点=评审通过的任务集（Jira 标签/状态过滤），边=Jira 阻塞关系；被砍任务不出现 |
| 节点状态 | `ai-studio-dev-dag-node-state-<jiraKey>` | 四态：排队 / 进行中 / 完成 / 失败；由 dev-dag 调度状态推导 |
| 节点执行体信息 | `ai-studio-dev-dag-node-agent-<jiraKey>` / `ai-studio-dev-dag-node-worktree-<jiraKey>` | 进行中的节点显示所属 dev agent 标识与 worktree 路径；非进行中不渲染 |
| 开始开发按钮 | `ai-studio-dev-start-btn`（演示版）/ `ai-studio-dev-full-start-btn`（完整版） | 渲染规则见 §〇 两阶段硬顺序；点击即启动，无确认弹层 |
| 调度日志 | `ai-studio-dev-dag-log` | 本步自身产出；流式增长，渲染复用 `DeployLog` 形态 |
| 验收区块 | `ai-studio-accept-run-btn` / `ai-studio-accept-result-list` / `ai-studio-accept-status` | DAG 全绿后出现；见 §〇-2 |
**与顶栏 `ReleaseControl` 的关系**：`dev-btn` 是演示工作台的三态一表桩，**不复用、不改动**（与 08 对 `release-btn` 的处理一致）；真实「开始开发」按钮由开发执行视图自建，testid 用上表的 `ai-studio-dev-start-btn`。

## 〇-2、验收区块的结构（demo-acceptance / dev-full-phase 收口）

DAG 全绿后，验收区块出现在开发执行视图内：
| 区块 | 承载 testid | 说明 |
|---|---|---|
| 执行验收入口 | `ai-studio-accept-run-btn` | 点击对当前阶段产物执行端到端验收测试套件（01~09 细节文档的断言集；演示版跑纯前端可执行子集，完整版跑全集） |
| 逐条结果列表 | `ai-studio-accept-result-list`；行=`ai-studio-accept-result-row-<断言id>` | 每行含断言 id、通过/失败、证据摘要；断言 id 可回指细节文档 |
| 验收总状态 | `ai-studio-accept-status` | 两态：通过 / 失败（含失败条数）；通过后固化，不可再变 |
| 验收形态徽标 | `ai-studio-accept-form-badge` | 文本=「演示版」或「完整版」，与 run 的 `phase` 一致 |
| 用户确认（仅演示版） | `ai-studio-accept-confirm-btn`（继续开发完整版）/ `ai-studio-accept-reject-btn`（回退改需求） | 验收通过后出现；确认→渲染 `ai-studio-dev-full-start-btn`；回退→跳回需求文档编辑器（02 的 edit-requirement 入口），并**撤销本轮验收结论**（见下方回边语义：记录作废、tag 删除、`demoAccepted` 复位） |
**回边语义**：`ai-studio-accept-reject-btn` 是顶层 demo-acceptance 的回边（→edit-requirement）。确认/回退按钮**只在验收套件通过后出现**（见上表），也就是说点击之前已经先落过 passed 记录、打过 tag——**回退必须把它们撤销掉，而不是「从未发生」**：① 本轮 run 状态=已中止（§三 B5 的 `runState:"aborted"`）；② §三 B4 里该条 passed 记录标记 `voided: true`（作废，重新跑验收会产生新记录，不回填旧记录）；③ 该版本 commit 上的「演示版」tag **删除**，`git tag` 查不到；④ `demoAccepted` 复位为 `false`（§三 B5）。四件事必须同时成立，缺一件回边就不成立（留 tag 会让 08 把这个版本判成可发布）。**⑤ 已经被 08 抢先发布过的情况**（tag 在用户确认前就落地，所以「过验收 → 08 发布 → 用户回退」是合法时序）：回退**不吊销已发布的结果**——release 保留、实例继续服务、08 侧该行状态仍「已发布」；回退只做上面①~④，效果是**阻断后续发布**（该版本在 08 侧因无 tag 判 `rejected`、按钮不渲染）。要再发布必须重新过验收、重新打 tag。 **确认与回退同轮互斥**：两者在同一轮验收通过后同时出现，用户只能点其一——点了回退，本轮即结束（①~④ 全部生效、编辑器回边已发生），本轮不会再有确认按钮；要确认必须先**重新通过验收**（产品路径是经 02→…→07 重跑；本套验收的轮 2 捷径见 §五 自检第 1 条）。所以「已发布、尚未确认」这个现场窗口**在同一轮里只有一次**，事后无法重建，08 场景 H 只能插在那一轮的回边之前。

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
| A1 | 打开开发执行视图 | `dev-phases` / `dev-phase-<阶段名>` | `dev-phases` 可见；两阶段容器可见；演示版阶段=当前，完整版阶段标「未解锁」；`ai-studio-dev-start-btn` 可见；渲染 |
| A2 | 点击「开始开发」 | `ai-studio-dev-start-btn` | 点击后直接进入调度（无确认弹层）；`ai-studio-dev-phase-badge` 的 phase=「演示版（纯前端）」 |
| A3 | DAG 渲染 | `ai-studio-dev-dag` | `ai-studio-dev-dag-node-<jiraKey>` 可见；节点集=评审通过任务集（逐个 jiraKey 对得上，被砍任务不在）；边与 Jira 阻塞关系一致 |
| A4 | 节点状态流转 | `ai-studio-dev-dag-node-state-<jiraKey>` | `ai-studio-dev-dag-node-state-<jiraKey>` 的 state=「进行中」；无阻塞节点先「进行中」，被阻塞节点保持「排队」；前驱完成后后继自动流转（轮询刷新，非一次性文案） |
| A5 | 执行体信息 | `ai-studio-dev-dag-node-agent-<jiraKey>` / `ai-studio-dev-dag-node-worktree-<jiraKey>` | `ai-studio-dev-dag-node-agent-<jiraKey>` 可见；进行中节点两者可见且非空；`ai-studio-dev-dag-node-worktree-<jiraKey>` 可见；worktree 路径与进程级断言（§四）实测一致 |
| A6 | 调度日志流式 | `ai-studio-dev-dag-log` | `ai-studio-dev-dag-log` 两次采样递增；日志文本随时间增长（两次采样行数递增）；含派单、完成、worktree 分配事件 |
| A7 | DAG 全绿 | `ai-studio-dev-dag-node-state-<jiraKey>`（全部实例） | `全部 ai-studio-dev-dag-node-state-<jiraKey>` 的 state=「完成」；DAG 全绿：全部节点都翻到「完成」，不留排队/进行中；`ai-studio-accept-run-btn` 可见；验收区块出现 |

### 场景 B：演示版验收与用户确认

| # | 操作 | 定位 | 断言 |
|---|---|---|---|
| B1 | 点击「执行验收」 | `ai-studio-accept-run-btn` | `ai-studio-accept-result-list` 内出现 `ai-studio-accept-result-row-<断言id>`；`ai-studio-accept-form-badge` 的 form=「演示版」 |
| B2 | 验收全绿 | `ai-studio-accept-status` | `ai-studio-accept-status` 的 result=「通过」；文本=「通过」；刷新后 `ai-studio-accept-status` 仍为「通过」；状态固化（刷新页面后仍为通过）；后台验收记录生成（§三 B4） |
| B3 | tag 落地 | —（后台断言，见 §三 B4） | 该版本 commit 已打「演示版」tag——08 B1 形态判定由此取数 |
| B4 | 用户确认（**本步之前插入 D6**：演示版验收已通过、尚未确认的那个现场只存在于 B2 与本步之间，点下去就回不去了——顺序安排见 §五 自检第 1 条） | `ai-studio-accept-confirm-btn` / `ai-studio-accept-reject-btn` | `ai-studio-accept-confirm-btn` 可见；验收通过后两者出现；`ai-studio-accept-reject-btn` 可见；点确认→后台 §三 B5 `demoConfirmed=true`（`demoAccepted` 仍为 true，两条件齐备）→ `ai-studio-dev-full-start-btn` 渲染，完整版阶段解锁 |
| B5 | 回边（另起一轮跑） | `ai-studio-accept-reject-btn` | `doc-<文档名>` 可见；点击后回到需求文档编辑器（DocEditor 的 `doc-<文档名>` 可见）；回退**撤销**本轮结论（§〇-2）：① §三 B5 的 `runState="aborted"`；② §三 B4 该条 passed 记录 `voided=true`；③ 该 commit 的「演示版」tag 已删除，`git tag` 查不到；④ `demoAccepted` 复位 `false`——四件事缺一不可（留 tag 会让 08 把它判成可发布的演示版） |

### 场景 C：完整版开发（复用 A 的调度规则）

| # | 操作 | 定位 | 断言 |
|---|---|---|---|
| C1 | 点击「开发完整版」 | `ai-studio-dev-full-start-btn` | `ai-studio-dev-full-start-btn` 可见；仅在（场景 B4）确认后可见可点；`ai-studio-dev-phase-badge` 的 phase=「完整版（含后端）」 |
| C2 | DAG 调度 | 同 A3~A6 | `ai-studio-dev-dag-node-<jiraKey>` 可见；后端任务逐个出现在 DAG 中，jiraKey 对得上；`ai-studio-dev-dag-node-state-<jiraKey>` 的 state=「完成」；调度跑完；worktree 隔离/复用规则同演示版（§四 进程级断言） |
| C3 | 全绿后验收 | 同 §三 B1~B3 | `ai-studio-accept-form-badge` 的 form=「完整版」；通过后 commit 打「完整版」tag |

### 场景 D：门禁与失败路径

| # | 操作 | 断言 |
|---|---|---|
| D1 | 演示版未验收通过时看完整版入口 | `ai-studio-dev-full-start-btn` **不存在于 DOM**；不是禁用，是不渲染；直接调 §三 B2 带 `phase:"full"` 返回 409 |
| D2 | 制造一个任务失败（如断言必败的子任务） | `ai-studio-dev-dag-node-state-<jiraKey>` 的 state=「失败」；该节点状态文本=「失败」；被它阻塞的后继停留「排队」；`ai-studio-dev-dag-log` 含失败原因；被它阻塞的后继停留「排队」；后台 §三 B5 的 `runState="failed"`：本轮收口于失败——既不是 `done`（不许把失败轮当跑完），也不是 `running`（不许永远转圈）；恢复只走 §三 B2 的失败重启；`ai-studio-accept-run-btn` **不存在于 DOM**；验收区块不出现（不许假全绿） |
| D3 | 存在未评审任务时 | `ai-studio-dev-start-btn` **不存在于 DOM**；不渲染 |
| D4 | 让验收套件中一条断言失败（如临时改坏一个 testid 后重跑验收） | `ai-studio-accept-status` 的 result=「失败」；`ai-studio-accept-status` 文本=「失败」+失败条数；`ai-studio-accept-confirm-btn` **不存在于 DOM**；验收未通过不进入用户确认（确认/回退按钮都不出现）；不产生验收通过记录、commit 不打 tag（`git tag` 查不到「演示版」标注）；`ai-studio-dev-full-start-btn` 保持不渲染（门禁不放行） |
| D5 | 开发运行中，对同 phase 再调一次启动 | 返回 409（§三 B2）；不产生第二轮 run（调度日志不出现第二次启动事件） |
| D6 | 演示版验收已通过、但用户还没点「继续开发完整版」时，绕过前端直接启动完整版 | `ai-studio-dev-full-start-btn` **不存在于 DOM**；验收通过只解锁确认按钮，入口仍不渲染——不是禁用；`ai-studio-accept-confirm-btn` 可见；确认按钮此时才出现（验收通过即出现）；`ai-studio-accept-run-btn` **不存在于 DOM**；「执行验收」入口不再渲染（验收已通过、结果固化，不许重跑）；后台 `demoAccepted=true` 但 `demoConfirmed=false`（§三 B5），直调返回 **409**（§三 B2）——条件②是后台门禁，不只在画面上 |

## 三、后台断言（端点）

> 端点路径前缀 `/api/apps/ai-studio`；最终路径以实现为准，实现时若调整必须同步改本文档（同一提交）。

| # | 事实 | 端点 | 断言字段 |
|---|---|---|---|
| B1 | DAG 取数 | `GET /dev/dag?project&phase` | 节点含 `jiraKey`、`dependsOn`、`state: "queued"|"running"|"done"|"failed"`、`agent`、`worktree`；节点集=评审通过任务集；`dependsOn` 与 Jira 阻塞关系一致；**UI 四态 ↔ 端点枚举映射**：排队=queued、进行中=running、完成=done、失败=failed（前端文案与端点值一一对应，不许新造第五态） |
| B2 | 启动开发 | `POST /dev/start` body `{project, phase}` | 响应含 `runId` 与 `phase`；**演示版未过验收（`demoAccepted=false`）或 已过验收但用户没点确认（`demoConfirmed=false`）时，`phase:"full"` → 409**（两条件缺一不可，见 §三 B5，场景 D1/D6）；同 phase `runState:"running"` 中再调 → 409，但 **`runState:"failed"` 时同 phase 再调不 409**——起新一轮 run（响应 `runId` 与上一轮不同、`phase` 不变），DAG 从**失败节点**继续（已 `done` 的节点保持完成、不回退重跑），这是失败任务唯一的恢复路径 |
| B3 | 调度日志流 | `GET /dev/run/<runId>/log（流式）` | 日志行随时间增长；含 worktree 分配事件（可与 §四 实测路径互证） |
| B4 | 验收执行与记录 | `POST /accept/run` body `{project, version, phase}`；`GET /accept/records?project` | 记录含 `phase`、`result: "passed"|"failed"`、**`voided: bool`**（生成时必为 `false`（字段必须存在，不许靠缺省），用户点 reject 回退后该条 passed 记录置 `true`——作废记录不计入 `demoAccepted`、对应 tag 同时删除）、逐条断言结果、`requirementVersion`（关联冻结基线）、`commitHash`；**未作废**的 passed 记录生成后对应 commit 的 git tag 可查（演示版/完整版标注）——**08 §三 B1 的判定来源就是这里的 tag**，tag 被撤销删除后该版本在 08 侧按 `rejected` 处理 |
| B5 | 阶段门禁 | `GET /dev/state?project` | 含 `demoAccepted: bool`（演示版验收通过=存在**未作废**的 passed 记录且「演示版」tag 在）、`demoConfirmed: bool`（用户点过「继续开发完整版」）、`fullAccepted: bool`、`runState: "idle"|"running"|"done"|"failed"|"aborted"`（**全局最近一轮** run 的状态——两阶段是硬顺序、run 串行，不会有两轮同时在跑；**`failed`** = 本轮 run 内有任务终态失败（§三 B1 节点的 `state:"failed"`），本轮收口于失败：后继任务不再流转、验收区块不出现；它既不是 `done`（不许把失败轮当跑完）也不是 `running`（不许永远转圈），恢复只走 §三 B2 的**失败重启**；用户点 reject 回退后该轮 run=`aborted`，同时 `demoAccepted` 复位为 false，可据此查证 §〇-2 的回边语义）。**完整版门禁 = `demoAccepted && demoConfirmed`**：任一为 false 时 B2 的 full 请求必 409 |

## 四、进程级断言（worktree 隔离/复用）

1. **并行隔离**：A4 出现两个并行「进行中」节点时，`git worktree list`（项目代码库）含两条不同路径，与两节点的 `ai-studio-dev-dag-node-worktree-<jiraKey>` 文本逐字一致。
2. **串行复用**：串行链前驱完成、后继进行中时，后继节点的 worktree 路径与前驱**相同**（复用，不新开目录）；`git worktree list` 不新增条目。
3. **dev agent 存活**：进行中节点的 `agent` 标识对应真实进程（PID 探活）；节点转「完成」后该 PID 允许消失。
4. **无目录爆炸**：同一 phase 的全部 run（含失败重启——D2 失败那轮与随后的重启轮）结束后，`git worktree list` 条目数 ≤ 并行度峰值（串行链不累积目录）。

## 五、自检清单（本文档验收 = 以下全勾）

- [ ] 场景 A/B/C/D 各跑一遍，前台断言全部只依赖 data-testid 与端点（§三）。**全程既不是一轮、也不是字母序**（按 A→B→C→D 跑会红在**时序**而不是实现，别照着编号顺序执行）：**轮 1**——场景 A 开发（其中 **D1** 要求 `demoAccepted=false`，排在 **B2 之前**跑；**D5** 要求有一轮 run 正在跑，在 run 运行期间执行；**D3** 不依赖任何前序状态，**可随时插**）→ 场景 B 的 **B1~B3**（验收通过、tag 落地）→ **D6**（要求恰好停在「验收已通过、尚未确认」，插在 **B2 之后、B4 之前**，B4 的操作说明里也留了这条路标）→ **在此插入 08 的场景 B**（见 08 §五 自检第 1 条的块一；块一跨文档拆成两步，中间夹着下面的回边点击）→ 回到本侧点 **B5 回边**（**这一次点击就是 08 场景 H 前提所需的那次 reject——两篇对这一次点击只有这一处排期**，B5 的四件事断言在此完成）→ **接着插入 08 的场景 H**，轮 1 结束（`demoAccepted` 复位、tag 撤销、passed 记录作废）；**轮 2**——**重跑验收 B1~B3**（回退后确认按钮要等验收重新通过才回来，见 §〇-2；重新通过会产生新记录、重新打上「演示版」tag，08 的 D3 现场就依赖这个 tag）。**轮 2 不改需求、对同一个版本（轮 1 发布过的那个 commit）重跑验收**：§七 的「回边产生新一轮奇数版本走 02→…→07 重跑」是产品的通用路径，本套验收不走它；走了新版本，重新打 tag 的就不是轮 1 那个 commit，08 fixture 第 4/5 行与 D3 的现场（「已发布 + tag 回来了」的同一行）随之落空→ **B4 点确认** → 场景 C 完整版开发（**D2** 穿插在这一轮——D2 把某个任务搞失败、**修复注入后**，按 §三 B2 的**失败重启**在同 phase 起新一轮、从失败节点继续，一路跑到 C3；D2 的代价只是多一轮 run，不是把轮 2 卡死）→ **C3** 完整版 tag → **在此插入 08 的场景 A/C/D/E/F/G 那一块**。**D4**（验收失败重跑）在轮 2 的验收阶段注入必败断言——B2 已写明「通过后固化」，**轮 1 的验收固化后不许在原轮重跑**（D6 自己也断言 `ai-studio-accept-run-btn` 不再渲染），所以 D2/D4 只能落在轮 2。若已经跑过 B 才发现要建 D1 的现场，用 **B5 的回边**把 `demoAccepted` 复位后再建。08 侧两块各自的顺序与插入点见 08 §五 自检第 1 条（两处同步改）
- [ ] DAG 节点集与 06 评审通过任务集一致（场景 A3）（§三 B1），边与 Jira 阻塞关系一致（无中生有的节点/边 = 造假）
- [ ] 并行任务 worktree 隔离、串行任务 worktree 复用（场景 A4）（§四）（§三 B3）
- [ ] 调度日志流式增长（场景 A6），含派单/完成/worktree 分配事件（§三 B3）
- [ ] 演示版未过验收：完整版入口不渲染、§三 B2 的 full 请求 409（D1）
- [ ] 演示版验收通过：`ai-studio-accept-status` 固化、commit 打「演示版」tag（§三 B4）（08 §三 B1 据此判定）
- [ ] 回边即撤销：reject 后回到 DocEditor，且四件事齐备——本轮 run 状态=aborted、§三 B4 该条 passed 记录 `voided=true`、commit 的「演示版」tag 已删除（`git tag` 查无）、`demoAccepted` 复位 false（场景 B5）（§〇-2）（§三 B4）（§三 B5）；已发布过的版本不吊销 release、只阻断后续发布（该时序的现场与断言见 08 场景 H）
- [ ] 完整版验收通过（场景 C3）（§三 B4）：commit 打「完整版」tag；08 的形态判定据此发完整版
- [ ] 失败路径不假绿：节点「失败」+ 日志含原因 + 验收区块不出现（场景 D2）（§三 B1）
- [ ] 验收记录可追溯到 requirementVersion（§三 B4）（冻结基线）
- [ ] 验收失败不假绿：`ai-studio-accept-status`=「失败」+失败条数，确认按钮不出现、不打 tag、完整版入口不渲染（场景 D4）（§三 B4）
- [ ] 同 phase 运行中重复调用：§三 B2 返回 409 且不产生第二轮 run（场景 D5）（§三 B2）

## 六、前端组件枚举与复用（防膨胀）

原则：**先复用现有组件，再新建**；本文档的 testid 挂在组件渲染出的 DOM 元素上——验收只认 testid，组件重构不毁断言，但 testid 不许丢。组件的全局登记在 `graph/nodes/Component-<id>.json`（id 语义化唯一，实例 testid = id 或 id-<数据id>），本表只声明本文档怎么用它们。

### 复用与澄清（本文不新建的部分）

| 组件（`website/src/apps/ai-studio/`） | 现有 testid | 本文如何用 |
|---|---|---|
| `DevRunView.tsx` | `dev-run-panel` / `dev-phases` / `dev-phase-<阶段名>` / `dev-artifact-<种类>` / `dev-runnable-version` | 两阶段容器直接用它：演示版/完整版各占一个 `dev-phase-<阶段名>`；产物与可运行版本断言沿用其现有 testid |
| `DeployLog.tsx` | `deploy-log-<部署id>` | 调度日志渲染复用它（同 08 对发布日志的处理），`runId` 对接 §三 B3 |
| `DocEditor.tsx` | `doc-<文档名>` | 回边（B5）的落点断言用它，不新建编辑器入口 |
| `ReleaseControl.tsx` | `dev-btn` | **不复用、不改动**：它是顶栏演示桩；真实开始开发按钮由开发执行视图自建（`ai-studio-dev-start-btn`） |

### 新建（仅此三件，超出需先改本文档）

| 新组件 | 承载 testid | 理由 |
|---|---|---|
| 任务 DAG 视图（挂 `DevRunView` 当前阶段内，含调度日志区） | `ai-studio-dev-dag` / `ai-studio-dev-dag-node-<jiraKey>` / `ai-studio-dev-dag-node-state-<jiraKey>` / `ai-studio-dev-dag-node-agent-<jiraKey>` / `ai-studio-dev-dag-node-worktree-<jiraKey>` / `ai-studio-dev-dag-log` | 现无按 Jira 阻塞关系渲染的任务 DAG；`GraphView` 是需求图谱视图，数据源与语义都不同，不许挪用；调度日志条渲染复用 `DeployLog` 形态 |
| 开发运行控制条（开始开发/开发完整版/阶段徽标） | `ai-studio-dev-start-btn` / `ai-studio-dev-full-start-btn` / `ai-studio-dev-phase-badge` | 现无真实开发启动入口（`dev-btn` 是桩）；两阶段门禁的渲染规则是本文新语义 |
| 验收区块（执行验收/逐条结果/确认与回退） | `ai-studio-accept-run-btn` / `ai-studio-accept-result-list` / `ai-studio-accept-result-row-<断言id>` / `ai-studio-accept-status` / `ai-studio-accept-form-badge` / `ai-studio-accept-confirm-btn` / `ai-studio-accept-reject-btn` | 现无端到端验收的执行与结果视图；「验收通过」状态是 08 形态判定的上游事实，必须有自己的承载处 |

**禁止**：为调度再造第二套日志视图、把需求 `GraphView` 挪来画任务 DAG、给 `dev-btn` 接真实端点、任何绕过阶段门禁的直达入口。发现要新建第四个组件时，先回来改本节。

## 七、与相邻文档的衔接

- **承接 06（review-tasks）**：DAG 节点集=评审通过任务集；未评审/被砍任务不进入本文任何视图。
- **产出给 08（publish-app）**：① 版本 commit 的 git tag（演示版/完整版）——08 §〇-1 行内形态判定与 §三 B1 的取数来源；② 验收记录（§三 B4）——08 形态判定「完整版过→发完整版 / 仅演示版过→只发演示版 / 都没过→拒发」的事实依据。两边对得上：`commitHash`/`requirementVersion` **同名同义**，`phase`（demo/full）与 `form`（demo/full/rejected）**值域一一对应**（不同名，但必须一一映射，见 08 §三 B1）。
- **回边给 02（edit-requirement）**：B5 回退的落点是 DocEditor，产生新一轮奇数版本走 02→…→07 重跑。
