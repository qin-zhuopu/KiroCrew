# 派工单 S5：〔部署到正式服务器〕——验收通过后构建、启动正式实例、套正式域名

> Jira：在 ACP-2085 下找标题以「[S5]」开头的子单（`jc jira issue children ACP-2085`），开工评论「开工」，完工评论结论并置完成。
> 依据：`raw/ai-studio-acceptance/08-publish-app.md`（发布设计，域名模板 `{version}-{app}-{operator}.gb10.jereh-pe.cn`）、`docs/request-for-change/rfc-ai-studio-req-flow.md` §9.6（开发服务器，本单照它的做法做正式版）。
> 每完成一步说「N 完成：<判据结果>」，一步接一步做完，不要停下来等确认。卡住超过 10 分钟停下贴报错原文。

## 地盘

- 工作目录 `/home/jereh/repo/github.com/kirodotdev/KiroCrew-wt-kc-prod`，分支 `feature/ACP-2085-prod`（从 feature/ACP-2015-v1 拉的，已含开发服务器、开始开发、验收）。`.venv`、`website/node_modules` 是链接，不许 pip/npm install。
- 没有自己的网关：只做单测。真跑由 master 合并后做。
- 只许新增/改：`backend/prodserver.py`（新）、`backend/routes.py`（只加本单路由）、`test/test_ai_studio_prodserver.py`（新）、`website/src/apps/ai-studio/ProdServerControl.tsx` 和 `.test.tsx`（新）、`AiStudioPage.tsx`（顶栏放控件）、`studioApi.ts`、i18n 中英两份。（backend = `src/kiro_crew/apps/builtins/ai_studio/backend/`）
- 不许推 origin、不许 --no-verify、不许合进 feature/ACP-2015-v1。

## 1. `backend/prodserver.py`

**复用 `devserver.py`**（import 它的 `child_env`、`gateway_conf_dir`、`gateway_reload_cmd`、`gateway_upstream`、`staff_id`、端口/进程/探活的写法）。不要复制粘贴一份，能 import 的都 import；需要改动 devserver 才能复用的，只许把私有函数改成公开（加不带下划线的别名），不许改它的行为。

```python
PORT_RANGE = (7000, 7199)
STEPS = ("检查验收", "构建", "停旧实例", "启动后端", "启动前端", "挂网址", "检查网址")
STABLE_SUFFIX = ".gb10.jereh-pe.cn"

def prod_domains(project: dict, staff: str, version: str) -> tuple[str, str]:
    """返回 (固定正式网址, 版本网址)：
    固定 = f"{代号}-{工号}.gb10.jereh-pe.cn"；版本 = f"{version}-{代号}-{工号}.gb10.jereh-pe.cn"（08 的模板）。
    代号/工号规则和 devserver.dev_domain 一样（不合规同样 400 bad_code / no_staff_id）。version 必须匹配 ^v[0-9]+$。"""

def gateway_conf_two(domains: tuple[str, str], web_port: int, upstream: str) -> str:
    """和 devserver.gateway_conf 一样，只是 server_name 写两个域名。"""

def build_cmds(ws) -> list[list[str]]:
    """.ai-studio/workspace.json 有 "prod": {"build": [...字符串]} 就用它（shlex 拆）；
    否则 [["pnpm","--filter","@webapp-template/core","build"], ["pnpm","build:api"], ["pnpm","--filter","@webapp-template/web","build"]]。"""

def launch_plan(ws, web_port, api_port, domains) -> list[dict]:
    """默认两条：
    后端 {"name":"启动后端","cmd":["pnpm","start:api"],"env":{"PORT":api, "APP_DB_PATH": str(ws/".ai-studio/prod/app.db"), "DWS_BIN_PATH": str(ws/"e2e/dws-mock/dws")}}
    前端 {"name":"启动前端","cmd":["pnpm","--filter","@webapp-template/web","preview","--","--port",str(web),"--strictPort","--host"],"env":{"VITE_PROXY_TARGET": f"http://127.0.0.1:{api}"}}
    workspace.json 有 "prod": {"web":{"cmd"}, "api":{"cmd"}} 就照它（端口照 dev 的 portEnv 约定注入 PORT）。"""

class ProdServer:   # 构造参数同 DevServer（runner/prober/ports/gateway 可注入替身）
    def status(self) -> dict
        # {state: stopped|deploying|running|failed, url(固定网址), versionUrl, version, ports, step, failedStep, message, deployedAt, commit}
    def deploy(self) -> dict      # 立刻置 deploying 返回；后台线程跑 STEPS
    def stop(self) -> dict
    def log_tail(self, lines=80) -> list[str]
```
状态文件 `<ws>/.ai-studio/prod-server.json`，日志 `<ws>/.ai-studio/prod-server.log`，数据库目录 `<ws>/.ai-studio/prod/`（先 mkdir）。

部署步骤：
1. **检查验收**：`accept.list_records(ws)` 最新一条 `result=="passed"` 且 `voided` 为假，且它的 `commitHash` == 现在 `git rev-parse HEAD`；不满足 → `ProdServerError("先通过验收（最新一次验收要通过，且之后没有新提交）","not_accepted",409)`，**在 deploy() 里同步检查**，直接 409，不置 deploying。
2. **构建**：逐条跑 build_cmds（cwd=ws，env=child_env({})，每条超时 900 秒，输出进日志）；非 0 → failed。
3. **停旧实例**：上一次 running 的进程组杀掉、旧 conf 删掉（端口不退，第 4 步重新申请）。
4~5. 申请两个端口（7000~7199，规则同 devserver），起后端、起前端（start_new_session=True）。
6. **挂网址**：写 `ais-prod-<代号>-<工号>.conf`（两个 server_name），reload。
7. **检查网址**：GET `https://<固定网址>/` 200（不走代理，最长 120 秒）。
成功后：
- 版本号 `v<N>`：N = `publish.list_release_records(项目id)` 条数 + 1。
- 打标注 tag：`git -C ws tag -a v<N> -m "完整版通过验收（验收记录 <id>）"`，再 `git -C ws push origin v<N>`（push 失败只写日志，不算部署失败）。
- `publish.record_release(项目id, version=v<N>, commit_hash=HEAD, form="full", requirement_version=验收记录的 requirementVersion, jira_task_ids=[], url=固定网址, deployment_id=<prod-server.json 里的部署 id>)`。
任一步失败：failed + failedStep + message「<步骤名>失败：<原文>」，回滚本次新起的进程、新 conf；旧实例已停的就保持停（message 里写明「旧实例已停」）。

## 2. 路由（都套 _require_enabled）

`GET /projects/{id}/prod-server`、`POST .../prod-server/deploy`（409 not_accepted / 409 already_deploying）、`POST .../prod-server/stop`（409 not_running）、`GET .../prod-server/log?lines=80`。

## 3. 后端测试 `test/test_ai_studio_prodserver.py`（全替身，不真起进程、不连网关、不真 git）

1. prod_domains：`eqp`/`14409`/`v1` → (`eqp-14409.gb10.jereh-pe.cn`, `v1-eqp-14409.gb10.jereh-pe.cn`)；`v1.0` 400；代号不合规 400。
2. gateway_conf_two 有两个 server_name、proxy_pass 到前端端口、有 Upgrade 头。
3. 没有验收记录 / 最新验收 failed / 验收后有新提交 → deploy 409 not_accepted，不写状态文件。
4. 成功：七步顺序对、state=running、url/versionUrl/version=v1、tag 命令被调、record_release 被调一次且 url=固定网址。
5. 第二次部署：旧进程组被杀、旧 conf 删、版本 v2。
6. 构建失败：failed、failedStep=构建、没起进程。
7. 检查网址超时：failed、新起的进程被杀、新 conf 删。
8. tag push 失败：部署仍 running，日志里有原因。
9. stop：进程杀掉、conf 删、端口释放、stopped；没运行 → 409。
10. 路由层 409/400 的 code 正确。

## 4. 前端 `ProdServerControl.tsx`（放 AiStudioPage 顶栏，开发服务器控件右边）

- testid：容器 `prod-server-control`，按钮 `prod-server-deploy`、`prod-server-stop`，网址 `prod-server-url`，版本 `prod-server-version`，进度 `prod-server-step`，错误 `prod-server-error`，日志开关 `prod-server-log-toggle`，日志 `prod-server-log`。
- 进页面先查状态（拿到前显示「查询中…」，按钮禁用）；deploying 时每 2 秒查一次。
- stopped：〔部署到正式服务器〕。点了若 409 not_accepted → 显示「先通过验收再部署」（不弹错误框，就在控件下方一行灰字）。
- deploying：黄点 +「部署中：<当前步骤名>」。
- running：绿点「正式运行中」+ 网址链接（固定网址，新标签打开）+「版本 v<N>」+〔重新部署〕〔停止正式服务器〕。
- failed：红点「部署失败」+「<步骤名>失败：<原文>」+〔查看日志〕+〔重新部署〕。
- 文案键 `apps.aiStudio.prodServer.*`，中英两份，中文照抄上面。
- 测试：查询中禁用；not_accepted 显示提示；deploying 显示步骤；running 显示网址 href 正确和版本；failed 显示原文；点停止调 stop。
- 判据：`cd website && npx vitest run src/apps/ai-studio/` 全过；`npx tsc --noEmit -p .` 无输出；`.venv/bin/python -m pytest test/test_ai_studio_*.py -q` 全过。

## 5. 收尾

只 stage 本单文件；提交 `feat(ai-studio): deploy to a production server with its own domain (ACP-2085 S5)`；`git push -u fork feature/ACP-2085-prod`。报告：提交号、判据结果、没做到的事。最后只回复「S5 全部完成」。
