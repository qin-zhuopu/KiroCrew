# 派工单 ACP-2085-ws：新建工作区 = 复制模板（后台分步进度 + 重试 + 建好自动起开发服务器）

> 需求依据：`docs/request-for-change/rfc-ai-studio-req-flow.md` §7 A1~A5、§8 第 1 行、§9.1、§9.6、§10 验收 1~3。必须先通读这几节。
> 每完成一步在聊天里说「N 完成：<判据结果>」。卡住超过 10 分钟，停下贴报错原文。
> 开工先用 jira 技能在 ACP-2085 下给自己建子任务（标签 sid-kc-ws），完工置完成。

## 地盘

- 工作目录 `/home/jereh/repo/github.com/kirodotdev/KiroCrew-wt-kc-ws`，分支 `feature/ACP-2085-ws`（从 feature/ACP-2015-v1 拉的）。`.venv` 和 `website/node_modules` 是链接，**不许** pip/npm install。
- 你**没有**自己的网关和前端服务。只用单测验证；真跑由 master 合并后在 kc-v1 环境里做。
- 只许改：`src/kiro_crew/apps/builtins/ai_studio/backend/projects.py`、新文件 `backend/workspace.py`、`backend/routes.py`（只加/改本单的路由）、`test/test_ai_studio_workspace.py`（新）、`website/src/apps/ai-studio/ProjectsListPage.tsx`、新文件 `website/src/apps/ai-studio/NewWorkspaceDialog.tsx` 和 `.test.tsx`、`website/src/apps/ai-studio/studioApi.ts`、i18n `zh-CN.json`/`en.json`。
- 不许推 `origin`（只推 `fork`）；不许 `--no-verify`；不许合进 feature/ACP-2015-v1（master 来合）。

## 1. 后端 `backend/workspace.py`（新）

```python
"""新建工作区 = 复制模板（RFC §9.1）。派生命令可配，默认 jc webapp init。"""
CODE_RE = re.compile(r"^[a-z][a-z0-9-]{1,22}[a-z0-9]$")   # 3~24 位，小写开头
STEPS = ("克隆模板", "建个人仓", "推送", "启动开发服务器")
DEFAULT_TEMPLATE_URL = "https://bitbucket.jereh.cn/scm/~14409/webapp-template.git"

class WorkspaceError(Exception): ...   # 带 code、status，同 devserver.DevServerError

def workspaces_root() -> Path:
    """环境变量 AI_STUDIO_WORKSPACES_ROOT，默认 /workspaces。"""

def check_code(code: str) -> str:
    """不匹配 CODE_RE → WorkspaceError("代号不合规：<值>","bad_code",400)。"""

def derive_cmd(template_url: str, code: str, staff_id: str, root: Path) -> list[str]:
    """环境变量 AI_STUDIO_WORKSPACE_CMD（shlex 拆）设了就用它，并把 {template} {code} {uid} {base} 四个占位换掉；
    没设用：["jc","webapp","init",template_url,"--name",code,"--uid",staff_id,"--base",str(root),"--no-init-sessions"]"""

def run_derive(cmd: list[str], log_path: Path, timeout: int = 900) -> dict:
    """跑命令（env 去掉 ANTHROPIC_* KIROCREW_* CLAUDE_*，同 devserver.child_env），stdout+stderr 追加写 log_path。
    读 stdout 最后一个 JSON 信封：success!=true → WorkspaceError(信封 message, "derive_failed", 502)；
    命令找不到 → WorkspaceError(..., "workspace_cmd_unavailable", 503)；超时 → "derive_timeout" 504。
    返回信封 data（里面有 target、personalRepo）。"""

class WorkspaceJob:
    """一个工作区的派生任务。状态写在项目记录里（projects.py 的 project.json）：
    status: creating | ready | failed；failedStep；message；steps: [{name, state: pending|running|done|failed, message}]；
    workspaceDir；repoUrl；code。"""
    def __init__(self, project_id: str, *, runner=None, devserver_factory=None): ...   # 可注入替身
    def run(self) -> None:      # 同步跑完所有步骤（路由层用线程跑它）
    def retry(self) -> None:    # 只有 status==failed 才允许，否则 WorkspaceError("not failed","not_failed",409)
```

步骤与命令的对应（jc webapp init 一条命令做完前三步，它的 data.plannedSteps 是 clone/create-repo/set-remote/develop-branch/push）：
- 跑派生命令前把「克隆模板」「建个人仓」「推送」三步都置 running；命令成功 → 三步都 done，记 `workspaceDir = data.target`、`repoUrl = data.personalRepo`；命令失败 → 按信封 message 里出现的词判哪步失败（含 `clone` → 克隆模板；含 `create-repo` 或 `repo` → 建个人仓；其余 → 推送），该步 failed、之后的 pending，`message = "<步骤名>失败：<错误原文>"`。
- 重试：如果 `workspaceDir` 目录已存在且是 Git 仓，就**不重新克隆**，改跑 `git -C <dir> push -u origin develop`；否则整条命令重跑。
- 「启动开发服务器」：调 `devserver.DevServer(Path(workspaceDir), project).start()`（project 里带 `code`，所以网址是 `<代号>-<工号>-dev...`）。start 只是置成 starting 就返回，这一步就算 done；它后面成不成看 devserver 自己的状态。
- 全部成功 → status=ready。

## 2. `projects.py` 改 `create_project`

- 签名改成 `create_project(name: str, description: str, code: str | None = None, template: str | None = None) -> dict`。
- 给了 `code`：`check_code(code)`；`list_projects()` 里已有同 code → `ProjectError("代号已被占用","code_taken",409)`；项目 id 直接用 code；记录多写 `code`、`template`、`status:"creating"`、`steps`（四步全 pending）。**不写 SEED_DOCS**（工作区里的文档来自模板）。
- 没给 `code`：行为和现在**完全一样**（老测试不能红）。
- 加 `update_project(project_id: str, **fields) -> dict`：读 project.json、合并字段、原子写回（先写 `.tmp` 再 `os.replace`）。

## 3. 路由（`routes.py`）

- `POST /projects`：body 有 `code` 就走新流程——`create_project(...)` 后起一个后台线程跑 `WorkspaceJob(id).run()`，**立刻**返回 `201 {project}`（status=creating）。没 `code` 走老流程不变。
- `POST /projects/{id}/retry`：调 `WorkspaceJob(id).retry()`（后台线程），返回 202；不是 failed → 409 `not_failed`。
- `GET /projects/{id}` 和 `GET /projects` 返回的记录里带上 status/steps/failedStep/message/workspaceDir/repoUrl/code（读 project.json 就有）。
- `GET /projects/{id}/workspace-log?lines=80`：返回派生日志尾巴 `{lines:[...]}`（日志放项目记录目录下 `workspace.log`）。

## 4. 后端测试 `test/test_ai_studio_workspace.py`

全用替身，**不许真跑 jc、不许联网、不许真起进程**。照 `test/test_ai_studio_devserver.py` 的写法。至少：
1. `check_code`：`sbgl` 过；`SBGL`、`a`、`1abc`、`设备`、25 位 都 400。
2. `derive_cmd` 默认值逐项断言；设了 `AI_STUDIO_WORKSPACE_CMD="echo {template} {code} {uid} {base}"` 时占位被替换。
3. 成功：替身 runner 返回 `{"success":true,"data":{"target":"/x/sbgl","personalRepo":"https://.../sbgl.git"}}` → 四步全 done、status=ready、workspaceDir/repoUrl 写对、替身 devserver 的 start 被调一次。
4. 建个人仓失败：替身返回 `{"success":false,"message":"create-repo: 401"}` → status=failed、failedStep=建个人仓、克隆模板 done、推送 pending、message=「建个人仓失败：create-repo: 401」、devserver 没被调。
5. 命令不存在 → failed、message 含 workspace_cmd_unavailable 的原因。
6. retry：failed 后 retry，工作区目录已存在是 Git 仓 → 跑的是 `git push` 而不是 jc；非 failed 时 retry → 409。
7. create_project 带 code：id=code、不写 docs/ 种子文档；重复 code → 409；不带 code 的老用例全部照旧通过。
8. 路由：POST /projects 带 code 立即 201 且 status=creating（后台线程用替身）；retry 409；workspace-log 返回行。

判据：`.venv/bin/python -m pytest test/test_ai_studio_workspace.py -q` 全过；`.venv/bin/python -m pytest test/test_ai_studio_*.py -q` 不回归。

## 5. 前端

- `NewWorkspaceDialog.tsx`（新）：字段 **工作区名称**（必填 2~40 字）、**代号**（必填，前端同样校验 `^[a-z][a-z0-9-]{1,22}[a-z0-9]$`，不过就在输入框下显示「代号只能用小写字母、数字、短横线，3~24 位，字母开头」）、**描述**（选填 ≤2000）、**模板**（只读显示「webapp-template」）、**工号**（只读显示，来自后端 `GET /projects` 响应里的 `staffId` 字段——请在 `_handle_projects_list` 的响应里加 `"staffId": os.environ.get("KIROCREW_STAFF_ID","")`）。按钮〔创建〕〔取消〕。
- 点〔创建〕后对话框变成进度：四步每步一行，图标 ⏳ pending / 转圈 running / ✓ done / ✗ failed，每 2 秒 `GET /projects/{id}` 刷新；失败那步下面显示 message 原文和〔重试这一步〕（调 retry）和〔查看日志〕（展开 workspace-log）；全部 done 后显示〔进入工作区〕，点了跳 `/workspaces/<id>/ai-studio`。
- `ProjectsListPage.tsx`：〔新建项目〕按钮改为打开这个对话框（文字改「新建工作区」）；卡片上 status=creating 显示「创建中」，failed 显示红字「创建失败」，点卡片可重新打开进度。
- testid：对话框 `new-ws-dialog`，输入 `new-ws-name` `new-ws-code` `new-ws-desc`，工号 `new-ws-staff`，创建 `new-ws-submit`，每步 `new-ws-step-<序号0起>`，重试 `new-ws-retry`，日志 `new-ws-log`，进入 `new-ws-enter`。
- 文案键 `apps.aiStudio.newWorkspace.*`（中英两份，中文照抄上面原文；步骤名用后端返回的中文原文）。
- 测试 `NewWorkspaceDialog.test.tsx`（照 `DevServerControl.test.tsx` 用假接口）：代号不合规时〔创建〕不可点且显示提示；创建后显示四步；某步 failed 显示原文和重试，点重试调 retry；全 done 显示进入按钮。
- 判据：`cd website && npx vitest run src/apps/ai-studio/` 全过；`npx tsc --noEmit -p .` 无输出。

## 6. 收尾

- 只 stage 本单文件；提交说明 `feat(ai-studio): new workspace = copy template, with step progress and retry (ACP-2085)`；`git push -u fork feature/ACP-2085-ws`（推不动先看 docs/pitfall-notes 里 github 推送卡住那篇）。
- 结束报告：提交号、每步判据命令和结果、没做到的事。
