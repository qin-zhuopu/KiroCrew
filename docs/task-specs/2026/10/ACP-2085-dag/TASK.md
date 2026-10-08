# 派工单 ACP-2085-S4：开始开发 → 按需求生成任务 → 每个任务开一个助手会话写代码 → 看板看进度 → 跑验收

> 设计依据：`raw/ai-studio-acceptance/07-dev-dag-two-phase.md`（定稿）、`07-dev-dag-two-phase-right-tab.md`（入口放右栏「开发」页签）、`docs/request-for-change/rfc-ai-studio-req-flow.md` §9.4、§13。先通读。
> **本单做最小可用版**，和 07 的差别（照这个做，不要多做）：
> - 只有一个阶段 `full`（不做演示版/完整版两阶段、不做 tag、不做回退、不接 Jira）。
> - 任务**串行**跑（同一个工作区目录，一次只跑一个任务），不建 worktree。
> - 不用 TaskRunner，自己写一个几十行的调度循环（照 spec_builder 开会话、发一轮的写法）。
> 每完成一步说「N 完成：<判据结果>」。卡住超过 10 分钟停下贴报错原文。开工先在 ACP-2085 下建子任务（标签 sid-kc-dag）。

## 地盘

- 工作目录 `/home/jereh/repo/github.com/kirodotdev/KiroCrew-wt-kc-dag`，分支 `feature/ACP-2085-dag`。`.venv`、`website/node_modules` 是链接，不许 pip/npm install。
- 没有自己的网关/前端服务：只做单测；真跑由 master 合并后做。
- 只许新增/改：`backend/devplan.py`（新）、`backend/devdag.py`（新）、`backend/accept.py`（新）、`backend/routes.py`（只加本单路由）、`test/test_ai_studio_devplan.py`、`test/test_ai_studio_devdag.py`、`test/test_ai_studio_accept.py`（新）、`website/src/apps/ai-studio/DevDagPanel.tsx` 和 `.test.tsx`（新）、`ToolSidebar.tsx`（加「开发」页签）、`studioApi.ts`、i18n 中英两份。（backend 指 `src/kiro_crew/apps/builtins/ai_studio/backend/`）
- 不许推 origin（只推 fork）、不许 --no-verify、不许合进 feature/ACP-2015-v1。

## 1. `backend/devplan.py`（纯函数，不碰 IO 以外的东西）

```python
KINDS = ("api", "web")
def build_plan(ws: Path, pages: list[str]) -> dict:
    """每页两个任务：<page>:api（后端接口）、<page>:web（前端页面，dependsOn=[<page>:api]）。
    pages 按传入顺序；任务总顺序 = 第1页 api, 第1页 web, 第2页 api, ...
    返回 {"tasks":[{"id","page","kind","title","prompt","dependsOn"}], "graphHashes":{page: requirements.graph_hash(...)}}
    title：「<页名>：后端接口」/「<页名>：前端页面」。prompt 用 task_prompt()。"""
def task_prompt(page: str, kind: str) -> str:
    """一字不差返回下面这段（<页名> 换掉；kind=api 用第一段要求，web 用第二段要求）：
    你在这个工作区里开发「<页名>」页面的<后端接口|前端页面>。
    只看 docs/需求图谱/<页名>.md（需求文档）和 docs/需求图谱/<页名>.json（需求图谱），不要参考任何旧系统。
    先读工作区根目录的 CLAUDE.md 和 docs/需求标准/使用说明.md（有就读）。
    api：在 apps/api/src/ 下照现有台账模块（如 review-flow-store）的写法新建本页的模块并在 app.module.ts 注册；接口地址、入参出参照需求文档「接口」一节。写单测。
    web：在 apps/web/src/features/ 下照现有台账页（如 review-flow-store）的写法做本页，路由加进 main.tsx，菜单加进 app/domains.ts 的「业务示例」域；字段、按钮、提示文案照需求文档原文。写单测。
    做完跑 pnpm typecheck 和本页单测，都过了再 git commit，提交说明「feat: <页名> <后端接口|前端页面>」。
    最后一句只回复：完成 或 失败：<原因>。"""
```
测试 `test_ai_studio_devplan.py`：两页夹具 → 4 个任务、顺序和 dependsOn 对；prompt 不含「原页面」「.vue」；graphHashes 两个键。

## 2. `backend/devdag.py`（调度）

状态文件 `<工作区>/.ai-studio/dev-run.json`：
`{"runId","phase":"full","runState":"idle|running|done|failed","startedAt","nodes":[{"jiraKey":任务id,"title","dependsOn","state":"queued|running|done|failed","slotKey","startCommit","endCommit","message"}]}`

```python
class DevRun:
    def __init__(self, state, project: dict, ws: Path, *, dispatcher=None, git=None, clock=None): ...  # 都可注入替身
    def get(self) -> dict                       # 读状态文件；没有 → {"runState":"idle","nodes":[]}
    async def start(self, pages: list[str]) -> dict
        """runState==running → DevDagError("already running","run_active",409)。
        上一轮 failed：沿用节点，done 的保持 done，其余改回 queued（失败后续跑）。否则用 build_plan 生成新节点。
        写状态文件 runState=running，起后台 asyncio 任务跑 _loop()，立即返回 {"runId","phase"}。"""
    async def _loop(self):
        """按顺序取第一个 queued 且 dependsOn 全 done 的节点：
        1. state=running，startCommit=git rev-parse HEAD，写文件。
        2. 开会话：照 spec_builder runtime._ensure_worker_slot：get_or_create_slot(name=f"ai-studio-dev-{项目id}-{序号}", app="ai-studio")，
           slot.project=工作区，slot.title=f"开发：{title}"；**不设 unattended**。
        3. 授权：调用 Crew 现有的「信任会话」那个函数给这个 slot 开信任（找 messaging/session_trust.py / messaging/approval.py:398 里网页〔信任会话〕按钮最终调的那个函数，照它调；审计日志会照常记）。
           这一条受环境变量控制：AI_STUDIO_DEV_TRUST=1 才做；没设就不做（那样批准要人点，看板上节点会一直 running）。
        4. 用 _dispatch_turn 发 task_prompt，await 这一轮结束（最长 2400 秒，超时 → failed「超时」）。
        5. 判结果：endCommit=git rev-parse HEAD；endCommit != startCommit 且回复最后一行以「完成」开头 → done；否则 failed，message=回复最后一行。
        6. 某节点 failed → runState=failed，停止（后面的保持 queued）。全部 done → runState=done。每次状态变化都写文件。
        日志：每个事件追加一行到 <工作区>/.ai-studio/dev-run.log（时间 + 事件 + 任务id）。"""
```
测试 `test_ai_studio_devdag.py`（替身 dispatcher 立即返回「完成」并让替身 git 的 HEAD 变；替身 state 记录 slot 属性）：
1. start → 4 节点按顺序 done，runState=done，每个 slot 的 project=工作区、unattended 没被设。
2. 运行中再 start → 409。
3. 第 2 个节点 HEAD 没变 → failed，runState=failed，第 3、4 个仍 queued。
4. failed 后 start → 第 1 个仍 done、不再调 dispatcher；从第 2 个开始跑。
5. AI_STUDIO_DEV_TRUST 未设 → 信任函数没被调；设 1 → 每个 slot 调一次。
6. 回复「失败：xxx」→ failed 且 message=「失败：xxx」。

## 3. `backend/accept.py`（验收）

```python
DEFAULT_CMDS = [["pnpm","typecheck"], ["pnpm","test:unit"]]
def accept_cmds(ws) -> list[list[str]]   # .ai-studio/workspace.json 的 "acceptCmds"（字符串列表，shlex 拆）有就用，否则 DEFAULT_CMDS
def run_accept(ws: Path, run: dict, *, runner=None) -> dict
    """run["runState"]!="done" → AcceptError("dev not done","dev_not_done",409)。
    逐条跑（cwd=ws，env 去掉 ANTHROPIC_*/KIROCREW_*/CLAUDE_*/代理变量，超时 900 秒），只认退出码。
    记录 {"id","phase":"full","result":"passed|failed","voided":False,"results":[{"id":命令文本,"ok","tail":输出最后 40 行}],
         "requirementVersion": 本轮各页 graphHash 拼起来,"commitHash": git rev-parse HEAD,"at"}
    写 <工作区>/.ai-studio/accept/<id>.json。"""
def list_records(ws) -> list[dict]   # 按时间倒序
```
测试：替身 runner 两条都 0 → passed；一条 1 → failed 且 tail 有内容；runState 不是 done → 409；voided 字段一定在。

## 4. 路由（前缀 /api/apps/ai-studio，都套 _require_enabled）

| 方法 路径 | 做什么 |
|---|---|
| `POST /projects/{id}/dev/start` body `{pages:[...]}`（不给 = 本工作区所有判定为「全齐」或「可以开工但有已知缺口」的页） | DevRun.start；所选页有判定「不齐」的 → 422 `not_ready`（附页名） |
| `GET /projects/{id}/dev/dag` | DevRun.get |
| `GET /projects/{id}/dev/log?lines=100` | dev-run.log 尾巴 |
| `POST /projects/{id}/accept/run` | run_accept（放线程跑） |
| `GET /projects/{id}/accept/records` | list_records |

DevRun 每个项目只能有一个实例：在 routes 里用 `{项目id: DevRun}` 字典缓存（网关重启后 get 读文件即可；重启时 runState 是 running 的，get 里改成 failed 并 message=「网关重启，中断」）。

## 5. 前端 `DevDagPanel.tsx`（放 ToolSidebar 新页签「开发」，testid `ai-studio-dev-entry`）

- 顶部：〔开始开发〕（testid `ai-studio-dev-start-btn`；runState=running 时禁用）。点击先弹确认框：「开始后，助手会在这个工作区里自动写代码并提交（不再逐次请你批准）。确定开始？」〔开始〕〔取消〕。
- 任务列表 testid `ai-studio-dev-dag`；每个节点一行 `ai-studio-dev-dag-node-<id>`：标题、状态文字 `ai-studio-dev-dag-node-state-<id>`（排队/进行中/完成/失败 四种，只这四种）、失败时 message 原文。
- 整体状态一行：空闲 / 开发中 / 已完成 / 失败（失败时按钮文字变「从失败处继续」）。
- 日志区 testid `ai-studio-dev-dag-log`（折叠，展开显示 dev/log）。
- 全部完成后出现验收区：〔跑验收〕`ai-studio-accept-run-btn`、结果 `ai-studio-accept-status`（通过 / 失败 N 条）、明细 `ai-studio-accept-result-list` 每条 `ai-studio-accept-result-row-<序号>`（命令、✓/✗、失败时输出尾巴）。
- running 时每 3 秒拉 dev/dag。
- 测试：四种状态文字；确认框取消不调接口；running 时按钮禁用；全 done 才出现验收区；验收失败显示条数。
- 判据：`npx vitest run src/apps/ai-studio/` 全过；`npx tsc --noEmit -p .` 无输出；`.venv/bin/python -m pytest test/test_ai_studio_*.py -q` 不回归。

## 6. 收尾

只 stage 本单文件；提交 `feat(ai-studio): start development — plan from requirements, one assistant session per task, board, acceptance (ACP-2085)`；推 fork。报告：提交号、判据结果、你找到的「信任会话」函数名和文件行号、没做到的事。
