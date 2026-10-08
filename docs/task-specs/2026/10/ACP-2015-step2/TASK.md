# 派工单 ACP-2015 第 2 步：需求页只读（右栏「需求」标签 + 中栏需求页 + 判定条）

> 需求依据：`docs/request-for-change/rfc-ai-studio-req-flow.md` §7 B1/B2、§8、§9.4（只做 GET 两条）、§10 验收 4/13/14、§13 第 2 步。
> 本步**只读**：不做直改、不做开始开发、不改聊天。那是第 3、4 步。
> 每完成一小步在聊天里说「2.N 完成：<判据结果>」。卡住超过 10 分钟，停下贴报错原文。

## 地盘（和 V1 一样，只许用这些）

- 工作目录 `/home/jereh/repo/github.com/kirodotdev/KiroCrew-wt-kc-v1`，分支 `feature/ACP-2015-v1`
- 网关 6790（tmux 窗口 `claude-kc-v1:gw`），vite 6791（`claude-kc-v1:vite`），域名 `https://kc-v1-14409-dev.gb10.jereh-pe.cn/`
- **两个服务器一直开着**。改了后端 Python 要重启网关：在 gw 窗口 Ctrl+C，再跑 `.kirocrew-dev/run-gw.sh`（你上一轮写的那个）。前端改了会热更新，不用重启。
- 不许 `pip install` / `npm install`；不许推 `origin`；不许 `--no-verify`。

## 2.1 后端：新文件 `src/kiro_crew/apps/builtins/ai_studio/backend/requirements.py`

只放纯逻辑 + 调外部命令，不碰 aiohttp。照下面的签名写（函数名一个字都别改，测试按这个名字找）：

```python
"""需求页（RFC rfc-ai-studio-req-flow §9.4）：读工作区 docs/需求图谱/*.json，调需求标准 v34 命令出文档和判定。"""
from __future__ import annotations
import hashlib, json, os, shlex, subprocess
from pathlib import Path
from typing import Any

REQ_DIR = "docs/需求图谱"
DEFAULT_CMD = "jc fe reqdoc"
VERDICTS = ("不齐", "可以开工但有已知缺口", "全齐")

class RequirementError(Exception):
    def __init__(self, message: str, code: str, status: int) -> None:
        super().__init__(message); self.code = code; self.status = status

def workspace_dir(project: dict[str, Any], project_path: Path) -> Path:
    """工作区目录：project.json 里有 workspaceDir（绝对路径且存在）就用它，否则用项目目录本身。"""

def reqdoc_cmd() -> list[str]:
    """环境变量 AI_STUDIO_REQDOC_CMD（shlex 拆分），没设用 DEFAULT_CMD。"""

def _run(args: list[str], timeout: int = 60) -> dict[str, Any]:
    """跑 reqdoc_cmd() + args，读 stdout 的 JSON 信封返回 data。
    命令找不到（FileNotFoundError）→ RequirementError(..., "reqdoc_cmd_unavailable", 503)
    超时 → RequirementError(..., "reqdoc_timeout", 504)
    stdout 不是 JSON 或 success!=true 且不是图谱不合格 → RequirementError(原 message, "reqdoc_failed", 502)"""

def graph_hash(path: Path) -> str:
    """sha256(文件字节) 前 16 位十六进制。"""

def list_pages(ws: Path) -> list[dict[str, Any]]:
    """列 ws/REQ_DIR/*.json（按文件名排序），每个跑一次 check，返回
    [{"page": 文件名去 .json, "graphHash", "verdict", "missingCount": len(missing)+len(errors), "updatedAt": mtime 的 ISO 字符串（UTC，带 Z）}]
    目录不存在 → []。"""

def get_page(ws: Path, page: str) -> dict[str, Any]:
    """page 不合法（含 / \\ 或 .. 或不以字母/数字/中文开头）→ RequirementError("page not found","page_not_found",404)
    文件不存在 → 同上 404。
    读图谱 JSON（解析失败 → RequirementError(...,"graph_invalid_json",422)），跑 check 得判定；
    跑 render（不带 --out）得 markdown；render 因图谱不合格失败时 markdown=None。
    返回 {"page","graph","markdown","graphHash","verdict","errors","missing","tiers","devState":"editing","stale":False}"""
```

- check 用 `["check", <图谱绝对路径>]`；render 用 `["render", <图谱绝对路径>]`。环境变量 `AI_STUDIO_REQDOC_FRAME` 有值时两条都追加 `["--frame", 值]`，没值不加。
- `jc fe reqdoc` 的输出是一个 JSON 信封：`{"success":true,"data":{...}}`；check 的 data 里有 `verdict/errors/missing/tiers`，render 的 data 里有 `markdown`。render 图谱不合格时信封是 `{"success":false,"errorType":"BusinessError",...}`，退出码 20——这种情况 get_page 里 markdown 置 None，不抛错。
- 自己先在终端跑一次看真实输出：`jc fe reqdoc check /home/jereh/repo/jc/jereh-cli/src/domains/fe/reqstd-v34/sample/供应商退货单.json`

**判据**：`PYTHONPATH=src .venv/bin/python -c "from kiro_crew.apps.builtins.ai_studio.backend import requirements as r; print(r.list_pages(__import__('pathlib').Path('/home/jereh/repo/jc/webapp-template-wt-req-tpl')))"` 打印两页（设备清单、设备点检记录），verdict 都是「全齐」。

## 2.2 后端路由：改 `src/kiro_crew/apps/builtins/ai_studio/backend/routes.py`

照文件里 `_handle_project_get`（第 75 行附近）的写法加两个处理函数，在 `register_routes` 里跟其它 `projects/{project_id}/...` 路由放一起注册，都包 `_require_enabled`：

- `GET {_BASE}/projects/{project_id}/requirements` → `{"pages": requirements.list_pages(ws)}`
- `GET {_BASE}/projects/{project_id}/requirements/{page}` → `requirements.get_page(ws, page)` 的结果
- 项目不存在 → `_error("project not found","project_not_found",404)`（照抄现有写法）
- `ws = requirements.workspace_dir(record, projects.projects_root() / project_id)`
- `RequirementError` → `_error(str(exc), exc.code, exc.status)`
- 都用 `await asyncio.to_thread(...)` 调（它会跑子进程，不能卡事件循环）

## 2.3 后端测试：新文件 `test/test_ai_studio_requirements.py`

照 `test/test_ai_studio_projects.py` 的夹具写法（看它怎么设 `KIROCREW_HOME`、怎么起测试客户端）。**不要依赖真 jc**：在 `tmp_path` 里写一个假命令脚本 `fake_reqdoc.py`，用 `monkeypatch.setenv("AI_STUDIO_REQDOC_CMD", f"{sys.executable} {脚本路径}")` 指过去。假脚本：
- `check <path>`：读图谱，图谱里 `goal` 含「待定」打印 `{"success":true,"data":{"verdict":"不齐","errors":[],"missing":["有待定"],"tiers":{"api":[],"ui":[],"parts":[]}}}`，否则 verdict=「全齐」、missing=[]。
- `render <path>`：打印 `{"success":true,"data":{"markdown":"# 需求：" + 图谱 page.title}}`。

至少这些测试（函数名照写）：
1. `test_list_empty_when_no_dir`：工作区没有 docs/需求图谱 → `[]`
2. `test_list_two_pages_sorted`：放两个图谱 → 两条，按名字排，verdict 对
3. `test_get_page_ok`：返回 markdown 以「# 需求：」开头、graphHash 16 位、devState=editing
4. `test_get_page_not_ready`：goal 含「待定」→ verdict=不齐，missing 非空
5. `test_get_page_traversal_404`：page=`../x` → 404 `page_not_found`
6. `test_cmd_unavailable_503`：`AI_STUDIO_REQDOC_CMD=/nonexistent/cmd` → 503 `reqdoc_cmd_unavailable`
7. `test_workspace_dir_override`：project.json 写 `workspaceDir` 指向另一个 tmp 目录 → 读的是那个目录
8. `test_routes_get_requirements`：走 HTTP 路由，`GET .../requirements` 200 且 pages 长度对；未知项目 404

**判据**：`.venv/bin/python -m pytest test/test_ai_studio_requirements.py -q` 全过，并且 `.venv/bin/python -m pytest test/test_ai_studio_projects.py -q` 不回归。

## 2.4 前端接口：改 `website/src/apps/ai-studio/studioApi.ts`

- 加类型：
```ts
export type StudioVerdict = '不齐' | '可以开工但有已知缺口' | '全齐'
export interface StudioRequirementSummary { page: string; graphHash: string; verdict: StudioVerdict; missingCount: number; updatedAt: string }
export interface StudioRequirementPage { page: string; graph: unknown; markdown: string | null; graphHash: string; verdict: StudioVerdict; errors: string[]; missing: string[]; tiers: { api: string[]; ui: string[]; parts: string[] }; devState: 'editing' | 'requested'; stale: boolean }
```
- `StudioApi` 接口加 `listRequirements(id)` → `{ pages: StudioRequirementSummary[] }`，`getRequirement(id, page)` → `StudioRequirementPage`；`studioApi` 对象里照 `listFreezes` 的写法实现（page 用 `encodeURIComponent`）。
- 演示模式那份假 api（`demo/runtime.ts` 的 `createDemoApi`）如果 TypeScript 报缺方法，加两个返回空列表 / 抛 `demo_mode` 的实现即可。

## 2.5 前端界面

**右栏**：改 `ToolSidebar.tsx`
- `type Tool` 加 `'requirements'`，并让它在 `TOOL_KEYS` 里排**第一个**，标签文字 `i18nT('apps.aiStudio.tool_requirements')`。
- **默认选中**改成 `'requirements'`（看现有 `useState<Tool>(...)` 的初值）。
- 新组件 `RequirementsTool`（可以写在新文件 `RequirementsTool.tsx`）：用 `useQuery` 调 `listRequirements(projectId)`；每行显示页名 + 判定徽标 + 更新时间；点一行 `onOpenTab({ id: \`req-${page}\`, kind: 'req', title: page, page })`。
  - 徽标：全齐 = 绿底「全齐」，可以开工但有已知缺口 = 黄底「有缺口」，不齐 = 红底「不齐」。颜色用仓里现有的主题类（看 `lint:theme-colors` 规则，别写死颜色值）。
  - 空列表显示 `i18nT('apps.aiStudio.req_empty')`。
  - 每个元素加 `data-testid`：列表 `req-list`，行 `req-row-<page>`，徽标 `req-verdict-<page>`。

**中栏**：改 `WorkArea.tsx`
- `WorkTab` 加一种：`| { id: string; kind: 'req'; title: string; page: string }`
- 新组件 `RequirementPage`（新文件 `RequirementPage.tsx`），在 WorkArea 渲染 tab 的地方按 `kind === 'req'` 挂它：
  - `useQuery` 调 `getRequirement(projectId, page)`，**每 5 秒自动刷新一次**（`refetchInterval: 5000`），这样别人改了图谱你这里会自己变。
  - 顶部**判定条** `data-testid="req-verdict-bar"`：
    - 全齐：绿，文字「需求已齐，可以开发」
    - 可以开工但有已知缺口：黄，文字「可以开工，但有 N 处已知缺口」（N = tiers 三组条数之和）
    - 不齐：红，文字「不齐：还不能开发」
    - 条右边一个「展开缺口」按钮，展开后分三组列出 `errors` / `missing` / `tiers`（只列非空组）
    - 接口报 503 `reqdoc_cmd_unavailable`：条显示「判定服务不可用」
  - 判定条下面显示 `markdown`：**只读**。用仓里已有的 Markdown 渲染方式（先找 DocEditor 或别的组件怎么渲染 markdown 的，复用，不许新装库）。markdown 为 null 时显示「需求图谱不合格，没生成文档」+ errors 列表。
  - 右上角两个按钮先放着、本步**置灰不可点**：「开始开发」（`data-testid="req-start"`，title 提示「第 4 步实现」）、「看需求图谱」（`data-testid="req-graph-toggle"`，这个**本步就做成可点**：切换成 `<pre>` 显示 `JSON.stringify(graph, null, 2)`）。
- 所有文字都走 `i18nT`，在 `website/src/i18n/locales/zh-CN.json` 和 `en.json` 的 `apps.aiStudio` 下加 key（上面用到的每条都要加；英文随便给个对应翻译）。加完跑 `cd website && npm run lint:i18n`。

## 2.6 前端测试：新文件 `website/src/apps/ai-studio/RequirementPage.test.tsx`

照 `DocEditor.test.tsx` 怎么 mock api、怎么包 QueryClient 写。至少：
1. 全齐 → 判定条文字「需求已齐，可以开发」，markdown 里的标题渲染出来
2. 不齐 → 「不齐：还不能开发」；点「展开缺口」看到 missing 那句
3. 有缺口 tiers ui 两条 → 「可以开工，但有 2 处已知缺口」
4. markdown=null → 显示「需求图谱不合格，没生成文档」
5. 「开始开发」按钮是 disabled

再给 `RequirementsTool` 写一个：两页、一绿一红，徽标文字对。

**判据**：`cd website && npx vitest run src/apps/ai-studio/RequirementPage.test.tsx src/apps/ai-studio/RequirementsTool.test.tsx` 全过；`npx vitest run src/apps/ai-studio/` 整个目录不回归；`npx tsc -p tsconfig.app.json --noEmit` 0 错（太慢就只看 ai-studio 下的报错）。

## 2.7 让用户在域名上能看到真东西

现有项目目录里没有需求图谱。做法：
1. 打开登录链接（LOGIN.txt，过期就重新 `kiro_crew token` 生成并更新 LOGIN.txt）进 `/workspaces`，新建一个项目，名称「设备管理（演示）」，描述随便写。
2. 找到它的目录 `.kirocrew-dev/ai-studio/projects/<id>/project.json`，加一个字段 `"workspaceDir": "/home/jereh/repo/jc/webapp-template-wt-req-tpl"`（那里有两页真需求：设备清单、设备点检记录）。**只改这个 project.json，不许动 webapp-template-wt-req-tpl 里的任何文件。**
3. 进这个项目的工作台，右栏「需求」应列出两页、都是绿「全齐」；点开「设备点检记录」看到判定条和文档。
4. 截一张图存 `docs/task-specs/2026/10/ACP-2015-step2/shot.png`（用仓里的 playwright 脚本或 `npx playwright screenshot`，连本机 6791 即可；截不了就跳过，在报告里说）。

**判据**：`curl` 带登录 cookie 调 `https://kc-v1-14409-dev.gb10.jereh-pe.cn/api/apps/ai-studio/projects/<id>/requirements` 返回两页且 verdict 都是「全齐」（命令和输出贴进报告）。

## 2.8 提交

```bash
git add src/kiro_crew/apps/builtins/ai_studio/backend/requirements.py \
        src/kiro_crew/apps/builtins/ai_studio/backend/routes.py \
        test/test_ai_studio_requirements.py \
        website/src/apps/ai-studio/ \
        website/src/i18n/locales/zh-CN.json website/src/i18n/locales/en.json \
        docs/task-specs/2026/10/ACP-2015-step2/
git status --short   # 确认没带上 LOGIN.txt、.kirocrew-dev、别的无关文件
git commit -m "feat(ai-studio): read-only requirement pages with v34 verdict bar (ACP-2015 step 2)"
git push fork feature/ACP-2015-v1
```

如果仓里的提交钩子要求别的（比如 system-specs 同步、填坑笔记），照钩子提示做，不许跳过。

## 2.9 完成报告（聊天里写）
1. 2.1~2.8 每步一行：完成/未完成 + 判据结果
2. 两个测试命令的通过条数
3. 演示项目 id 和它的工作台网址
4. 提交号
5. 没做/有疑问的地方，一条条列出来

## 禁止
- 做直改、开始开发、聊天改造（第 3、4 步的事）
- 改 `graph.py` / `projects.py` 的现有行为（只许读 project.json 的新字段 workspaceDir）
- 动 `/home/jereh/repo/jc/webapp-template-wt-req-tpl` 里的文件
- 用 6790/6791 以外的端口
