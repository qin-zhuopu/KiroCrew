# 派工单 ACP-2060：项目页「启动/停止开发服务器」按钮 + 规则域名

> 需求依据：`docs/request-for-change/rfc-ai-studio-req-flow.md` **§9.6**（必须先通读）、§10 验收 15~19、§13 第 5a 步。
> 每完成一小步在聊天里说「N 完成：<判据结果>」。卡住超过 10 分钟，停下贴报错原文。
> 开工先建 Jira 子任务挂在 ACP-2060 下（标签 sid-kc-v1），完工置完成。

## 地盘（和第 2 步一样）

- 工作目录 `/home/jereh/repo/github.com/kirodotdev/KiroCrew-wt-kc-v1`，分支 `feature/ACP-2015-v1`
- 网关 6790（tmux `claude-kc-v1:gw`），vite 6791（`claude-kc-v1:vite`），域名 `https://kc-v1-14409-dev.gb10.jereh-pe.cn/`
- 改了后端 Python 要重启网关：gw 窗口 Ctrl+C，再跑 `.kirocrew-dev/run-gw.sh`。
- 演示项目 `p261008-151745`，工作区目录 `/home/jereh/repo/jc/webapp-template-wt-req-tpl`（开发服务器就在这个目录里起）。
- 开发服务器端口段 **6800~6999**（只许用这段）。
- 不许在 KiroCrew 仓里 `pip install` / `npm install`；工作区目录里的 `pnpm install` 由你写的代码去跑（要去掉代理变量）。
- 不许推 `origin`（只推 `fork`）；不许 `--no-verify`；不许改 `~/docker/web-gateways/conf.d/` 下**已有**的文件、不许重建任何容器（网关已配好，你只新增/删除 `ais-*.conf`）。

## 1. 网关带上工号

`.kirocrew-dev/run-gw.sh` 里加一行 `export KIROCREW_STAFF_ID=14409`，重启网关。
判据：`tr '\0' '\n' < /proc/<网关pid>/environ | grep KIROCREW_STAFF_ID` 有输出。

## 2. 后端新文件 `src/kiro_crew/apps/builtins/ai_studio/backend/devserver.py`

照同目录 `deploy.py` 的 `ProcessDeployer`（状态文件读写、subprocess、`platform_compat`）写。函数名照抄：

```python
"""开发服务器启停（RFC rfc-ai-studio-req-flow §9.6）。"""
DOMAIN_SUFFIX_DEFAULT = "-dev.gb10.jereh-pe.cn"
PORT_RANGE = (6800, 6999)
STATES = ("stopped", "starting", "running", "failed")

class DevServerError(Exception):  # 带 code、status，同 requirements.RequirementError

def dev_domain(project: dict, staff_id: str | None) -> str:
    """<代号>-<工号><后缀>。代号=project['code'] 否则 project['id']，先转小写；
    不匹配 ^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$ → DevServerError("代号不合规：<值>","bad_code",400)
    staff_id 空 → DevServerError("没有工号：请设置 KIROCREW_STAFF_ID","no_staff_id",400)
    staff_id 不匹配 ^[a-z0-9]+$ → 同 no_staff_id。后缀读 AI_STUDIO_DEV_DOMAIN_SUFFIX。"""

def gateway_conf(domain: str, web_port: int, upstream: str) -> str:
    """返回一份 nginx server{} 文本：listen 80; server_name <domain>; proxy_pass http://<upstream>:<web_port>;
    带 Host / X-Real-IP / http1.1 / Upgrade / Connection "upgrade" / proxy_read_timeout 300s。"""

def launch_plan(ws: Path, web_port: int, api_port: int, domain: str) -> list[dict]:
    """返回 [{"name":"后端","cmd":[...],"env":{...}}, {"name":"前端",...}]。
    ws/.ai-studio/workspace.json 有 dev.web/dev.api 就照它（cmd 字符串用 shlex 拆）；
    没有就用 §9.6 的默认两条（pnpm --filter @webapp-template/api dev / web dev 及其 env）。"""

def child_env(extra: dict) -> dict:
    """os.environ 去掉 ANTHROPIC_* / KIROCREW_* / CLAUDE_* / HTTP_PROXY / HTTPS_PROXY / http_proxy / https_proxy，再并上 extra。"""

class DevServer:
    def __init__(self, ws: Path, project: dict, *, runner=None, prober=None, ports=None, gateway=None): ...
        # runner / prober / ports / gateway 都可注入替身（测试用），默认用真的
    def status(self) -> dict      # 读 .ai-studio/dev-server.json，按「pid 活着 + 网址 200」重算
    def start(self) -> dict       # 立刻把状态写成 starting 并返回；真正启动在后台线程里跑
    def stop(self) -> dict
    def log_tail(self, lines: int = 50) -> list[str]
```

启动步骤名（`failedStep` 用这些原文）：`装依赖`、`申请端口`、`启动后端`、`启动前端`、`挂网址`、`检查网址`。
- 装依赖：`ws/node_modules` 不存在才跑 `pnpm install`（cwd=ws，env=child_env({})，超时 900 秒）。
- 申请端口：6800~6999 里找两个能 bind 的，且 `resreg check --type port --value <p>` 返回 0；然后 `resreg claim --type port --value <p> --owner ai-studio-<id> --purpose "AI Studio 开发服务器"`。`shutil.which("resreg")` 为空就只做 bind 检查。
- 启动后端/前端：`subprocess.Popen(cmd, cwd=ws, env=..., stdout/stderr 追加写 .ai-studio/dev-server.log, start_new_session=True)`。
- 挂网址：写 `<AI_STUDIO_GATEWAY_CONF_DIR 默认 ~/docker/web-gateways/conf.d>/ais-<代号>-<工号>.conf`，跑 `AI_STUDIO_GATEWAY_RELOAD_CMD`（默认 `docker exec web-gateways nginx -s reload`，shlex 拆）。upstream 读 `AI_STUDIO_GATEWAY_UPSTREAM`，默认 `10.244.2.1`。
- 检查网址：每 2 秒 GET `https://<域名>/`（不走代理：用 urllib 时 `ProxyHandler({})`），120 秒内 200 → running。
- 任一步失败：状态 failed + failedStep + message=「<步骤名>失败：<错误原文>」，并**回滚**：杀已起的进程组、删 conf + reload、`resreg release` 端口。
- stop：`os.killpg(pgid, SIGTERM)`，5 秒后还活着就 SIGKILL；删 conf + reload；release 端口；状态 stopped。

## 3. 路由（`routes.py`，照 `_handle_requirements_list` 的写法，都套 `_require_enabled`）

`GET /projects/{id}/dev-server`、`POST .../dev-server/start`、`POST .../dev-server/stop`、`GET .../dev-server/log?lines=50`。
错误码照 §9.6 表：409 `already_running` / `not_running`，400 `bad_code` / `no_staff_id`。工作区目录用 `requirements.workspace_dir()`。

## 4. 后端测试 `test/test_ai_studio_devserver.py`

照 `test/test_ai_studio_publish_executor.py` 的写法，**不许真起进程、不许真连网关**（全用替身 runner/prober/ports/gateway）。至少这些用例：
1. `dev_domain`：code=`eqp`、工号 `14409` → `eqp-14409-dev.gb10.jereh-pe.cn`；无 code 用 id；`EQP` 转小写；`设备` → bad_code；工号空 → no_staff_id。
2. `gateway_conf` 含 `server_name eqp-14409-dev.gb10.jereh-pe.cn;` 和 `proxy_pass http://10.244.2.1:6801;` 和 `Upgrade`。
3. `launch_plan` 默认两条：前端 env 有 `PORT`、`VITE_PROXY_TARGET=http://127.0.0.1:<api>`、`__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS=<域名>`；有 workspace.json 时照它。
4. `child_env` 去掉了 `ANTHROPIC_API_KEY`、`KIROCREW_HOME`、`HTTPS_PROXY`。
5. 成功启动：状态 starting → running，url 正确，conf 写了、reload 调了。
6. 后端命令失败：failed、failedStep=`启动后端`、端口已 release、conf 没写。
7. 检查网址超时（prober 永远返回 502，超时调小）：failed、failedStep=`检查网址`、进程被杀、conf 删了。
8. stop：进程组被杀、conf 删了、端口 release、状态 stopped；未运行时 stop → 409 not_running。
9. 运行中再 start → 409 already_running。
10. status：状态文件说 running 但 pid 不在 → 不返回 running。
11. 路由层：400/409 的 JSON 里 code 正确（照 `test_ai_studio_requirements.py` 起 aiohttp 测试客户端的写法）。

判据：`.venv/bin/python -m pytest test/test_ai_studio_devserver.py -q` 全过，且 `.venv/bin/python -m pytest test/test_ai_studio_*.py -q` 不回归。

## 5. 前端

- `website/src/apps/ai-studio/studioApi.ts`：加 `getDevServer(id)`、`startDevServer(id)`、`stopDevServer(id)`、`getDevServerLog(id, lines)`，写法照文件里已有的 requirements 调用。
- 新文件 `website/src/apps/ai-studio/DevServerControl.tsx`，放进 `AiStudioPage.tsx` 顶栏（约 544~570 行那段工具条的右侧）。
  - 进页面就查一次状态；`starting` 时每 2 秒查一次，直到不是 starting。
  - 圆点颜色：stopped 灰 / starting 黄 / running 绿 / failed 红。
  - testid：容器 `dev-server-control`，按钮 `dev-server-toggle`，网址链接 `dev-server-url`，复制 `dev-server-copy`，失败信息 `dev-server-error`，日志按钮 `dev-server-log-toggle`，日志区 `dev-server-log`。
  - 网址链接 `target="_blank" rel="noopener noreferrer"`。
- `ProjectsListPage.tsx` 卡片：项目运行中时显示绿点 + 网址（testid `project-dev-url`）。列表接口没有状态就逐个调 `getDevServer`（项目少，可以）。
- 文案（zh-CN.json / en.json 的 `apps.aiStudio.devServer.*`，中文照抄）：
  - 状态：「已停止」「启动中…」「运行中」「启动失败」
  - 按钮：「启动开发服务器」「停止开发服务器」「复制」「查看日志」「收起日志」
- 测试 `DevServerControl.test.tsx`（照 `RequirementsTool.test.tsx` 用假接口）：stopped 显示启动按钮；点了调 start 并显示「启动中…」；running 显示网址链接且 href 正确、按钮变停止；failed 显示「<步骤名>失败：…」原文；点停止调 stop。
- 判据：`cd website && npx vitest run src/apps/ai-studio/` 全过；`npx tsc --noEmit -p .` 无新增报错。

## 6. 真跑一遍（必须做，写进结束报告）

1. 给演示项目加代号：在 `/home/jereh/repo/github.com/kirodotdev/KiroCrew-wt-kc-v1/.kirocrew-dev/ai-studio/projects/p261008-151745/project.json` 加 `"code": "sbgl"`（设备管理）。
2. 重启网关，用接口（不是浏览器）：`POST start` → 每 5 秒 `GET dev-server`，直到 running。贴出最终 JSON。
3. `curl --noproxy '*' -s -o /dev/null -w '%{http_code}' https://sbgl-14409-dev.gb10.jereh-pe.cn/` 是 200；贴首页 `<title>`。
4. `POST stop` → 贴：pid 已不在（`ps -p`）、`ls ~/docker/web-gateways/conf.d/` 里没有 `ais-sbgl-14409.conf`、两个端口 `resreg check` 返回 0、网址不再 200。
5. 最后**再启动一次并保持运行**，让 master 在浏览器里验收。

## 7. 收尾

- 提交（只 stage 本单相关文件），推 `fork`。
- 结束报告列：提交号、每个判据的命令和结果、第 6 步的原始输出、没做到的事（诚实写）。
