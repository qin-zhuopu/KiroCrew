# AI Studio 最终形态：用户全流程与验收（2026-10-09 盘点版）

> 本文是 `rfc-ai-studio-req-flow.md` 的验收补充：把「做完以后用户上来怎么用」从头到尾写成一条可点的路，
> 每一步写清**按钮/页面、做完的判据、现状**。现状三档：✅ 已做且在网页上实测过 / 🟡 已做但还没在网页上实测 / ❌ 没做或与设计有偏离（附 Jira）。
> 实战项目：「设备管理」（代号 eqp，工号 14409）。父单 ACP-2085。

## 产品形态（一句话）

一个网页工作台。用户每做一个应用就建一个**工作区**（= 复制一份模板、在自己名下建 Git 仓库）。在工作区里：
**跟写需求助手聊出需求 → 机器判「齐不齐」→ 点开始开发，平台拆任务、派助手写代码、跑验收 → 一键部署成正式网站**。
全程只在网页上点，不用碰命令行。

## 全流程

| # | 用户做什么（按钮 / testid） | 判据 | 现状 |
|---|---|---|---|
| 1 | 打开 `https://kc-v1-14409-dev.gb10.jereh-pe.cn/` 登录 | 进得去，看到工作区列表 | 🟡 只能用一次性登录链接；工号登录 ❌ ACP-2114（待需求方定） |
| 2 | `/workspaces` 点〔新建工作区〕，填名称、代号（小写字母开头 3~24 位）、描述 → 〔创建〕 | 进度四步全 ✓：克隆模板、建个人仓、推送、启动开发服务器；失败那步显示原文 +〔重试这一步〕 | ✅ eqp、wscopy1 实测；个人仓 `~14409/<代号>` 全量历史 |
| 3 | 卡片上看状态（创建中 / 创建失败 / 运行中 + 开发网址） | 状态与真实一致 | ✅；网关重启后「创建中」卡死 ❌ ACP-2111（在修） |
| 4 | 进工作区 `/workspaces/<代号>/ai-studio`，顶栏〔启动开发服务器〕/〔停止开发服务器〕 | 绿点运行中，网址 `<代号>-<工号>-dev.gb10.jereh-pe.cn` 打开模板首页；停止后进程/端口/网址都收回 | ✅；刚打开时闪一下「已停止」❌ ACP-2112（在修） |
| 5 | 右栏「需求」页签：看模板自带的 19 页现有功能需求（都「全齐」）和自己新写的页 | 列表 + 三色判定 | ✅ |
| 6 | 左栏和写需求助手聊（第一次写文件时点一次〔信任会话〕） | 助手按 v34 问问题，写出 `docs/需求图谱/<页>.json`，10 秒内右栏出现、判定有颜色 | ✅ 设备分类、设备清单、设备点检记录实测 |
| 7 | 打开某页需求，直接改文档 →〔保存〕 | 判定条「改动待落回需求」，助手把改动落回图谱 | ✅ ACP-2104 实测 |
| 8 | 需求页〔开始开发〕或右栏「开发」页签〔拆分任务〕 | 只拆**新需求**（模板原有页不算），每页 后端/前端 两个任务，每个任务一张 Jira 子单 | ✅（当晚修了两处：开发看板没装上网页、不点名会把模板 21 页都拆进来）；Jira 开工不流转 ❌ ACP-2203（已改配置待验证） |
| 9 | 〔开始开发〕→ 确认框〔开始〕 | 看板逐个任务 排队→进行中→完成，每 3 秒自动刷新；每个任务一次提交；失败显示原因 +〔从失败处继续〕/〔重新拆分任务〕 | 🟡 实战进行中（ACP-2109） |
| 10 | 全部完成后〔跑验收〕；没过就点〔让助手修复〕 | 平台统一跑类型检查 + 单测，通过/失败条数 + 明细（开发助手自己不跑测试）；没过时每条命令的**完整输出**落 `.ai-studio/accept/<记录id>-<序号>.log`，〔让助手修复〕按这些文件追加一个修复任务（也在父单下建 Jira 子单），修完**自动再验收一次**；连续修 3 次仍不过就只提示「已修 3 次仍未通过，请人工处理」 | 🟡 ACP-2210 已做，待实战 |
| 11 | 顶栏〔部署到正式服务器〕 | 先过验收；构建 → 起正式实例 → 网址 `<代号>-<工号>.gb10.jereh-pe.cn`（另有 `v<N>-<代号>-<工号>`）→ 打版本标签 v<N> → 记发布记录；〔停止正式服务器〕 | 🟡 已做未实测（ACP-2202） |
| 12 | 打开正式网址，菜单「业务示例」下新页面能增删改查 | 两页可用 | 🟡 待实战 |
| 13 | 升版 | 代码变了才升版：最新那条发布记录的提交 == 本次提交时沿用现版本号（不打新标签、不新增发布记录，实例照常重启）；提交变了才 v<N>+1 | 🟡 ACP-2219 已做未实测；是否要单独〔升版〕按钮待需求方定（ACP-2205） |
| 14 | 删除工作区 | — | ❌ 没做（ACP-2206） |

## 与原设计的偏离（都已立单）

| 偏离 | 原设计 | 现在 | Jira |
|---|---|---|---|
| 开发串行 | 07：并行任务各用一个 worktree，DAG 调度 | 一个工作区一次只跑一个任务 | ACP-2207 |
| 没有两阶段 | 07：先演示版（纯前端）验收，再完整版 | 只有一个阶段 | ACP-2208 |
| 模板自带代码类型检查不过 | 模板应「复制即绿」 | eqp 已修，模板主干未修 | ACP-2209 |
| 其它语种文案 | 全语种 | 只中英 | ACP-2113 |

## 运行纪律（当晚定案）
- 开发助手、Claude 工人**不跑全量测试 / e2e / 浏览器**，只跑自己改的那个测试文件；全量测试由 master 合并后统一跑，验收由平台〔跑验收〕统一跑。
- 每 20 分钟巡检（`~/.jereh-cli/patrol-reminder.sh`），网关/浏览器挂了自动拉起。

## 每个操作的 testid

全流程每一步在网页上点的那个控件，都有一个稳定的 `data-testid`（ACP-2222）。这是实战脚本、冒烟脚本和人工走查**唯一可以照着找元素的名字**——按钮文案是会翻译、会改的，这个名字不会。

带 `-` 结尾的是**前缀**：那种控件一行一个（每步、每个任务、每个项目），源码里是 `data-testid={`project-delete-${项目id}`}`，脚本用 `[data-testid^="project-delete-"]` 找。

| 操作 | testid |
|---|---|
| 工作区列表 | ai-studio-projects |
| 新建工作区：对话框/名称/代号/提交/每步/重试/日志/进入 | new-ws-dialog / new-ws-name / new-ws-code / new-ws-submit / new-ws-step- / new-ws-retry / new-ws-log / new-ws-enter |
| 卡片：状态/开发网址/删除 | project-status- / project-dev-url / project-delete- |
| 开发服务器：启停/网址/日志 | dev-server-toggle / dev-server-url / dev-server-log-toggle |
| 右栏页签 | ai-studio-tool-requirements / ai-studio-tool-docs / ai-studio-tool-commits / ai-studio-tool-releases / ai-studio-tool-graph / ai-studio-tool-dev / ai-studio-tool-deploy，另有历史名 ai-studio-dev-entry、ai-studio-publish-entry |
| 需求：列表行/判定条/保存/开始开发 | req-row- / req-verdict / req-save-btn / req-start-btn |
| 聊需求：提示/输入/发送/信任会话 | req-session-tip / chat-input / chat-send / approval-trust |
| 开发：拆分/开始/确认/任务行/Jira/日志 | ai-studio-dev-plan-btn / ai-studio-dev-start-btn / ai-studio-dev-confirm / ai-studio-dev-dag-node- / ai-studio-dev-dag-node-jira- / ai-studio-dev-dag-log |
| 验收：跑/结果/让助手修复 | ai-studio-accept-run-btn / ai-studio-accept-status / ai-studio-accept-fix-btn |
| 部署：部署/停止/网址/版本/日志 | prod-server-deploy / prod-server-stop / prod-server-url / prod-server-version / prod-server-log-toggle |

批准卡片（第 6 步第一次让助手写文件时会弹）：容器 `approval-card`，三个按钮 `approval-approve` / `approval-trust` / `approval-reject`。

右栏 7 个页签统一叫 `ai-studio-tool-<key>`（key = requirements / docs / commits / releases / graph / dev / deploy）。〔发布〕〔开发〕两个页签**同时**还带着改名前的老名字 `ai-studio-publish-entry` / `ai-studio-dev-entry`——老脚本和老测试在点它们，所以一个按钮上挂两个名字：老名字在 `data-testid`，统一名字在 `data-tool`（属性选择器 `[data-tool="ai-studio-tool-dev"]` 找任何页签都用这个写法）。**不要**为了统一把老名字挪到外层容器上：`ai-studio-dev-entry` 上挂着 `aria-selected` 断言（`DevDagPanel.test.tsx`），挪出去就等于让脚本读到一个不属于该页签的选中态。

这张表由 `website/src/apps/ai-studio/journeyTestids.test.ts` 把守：谁把哪个 testid 删了或改了名，那个测试就红；表里写了但本文没写的（或反过来）同样红。改名要**三处一起改**——组件、测试的表、本节。
