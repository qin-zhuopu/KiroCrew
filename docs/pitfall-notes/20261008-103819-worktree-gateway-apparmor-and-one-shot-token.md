# 派工单跑通实验时撞到的两个坑：worktree 里起网关、`kirocrew token` 的链接票只有 300 秒

日期：2026-10-08 10:38
场景：按派工单（`docs/task-specs/2026/10/ACP-2015-v1/TASK.md`）在 worktree
`KiroCrew-wt-kc-v1` 里起开发网关 + vite，然后用接口跑一个「Claude 会话能否以
工作区里的 requirement-writer 为主 agent」的实验。两个坑的报错都不指向根因。

## 坑 1：照 `./dev-backend.sh` 起网关，会话一律起不来

### 现象

- 网关**本身起来了**：`curl 127.0.0.1:6790/` 回 200，`/` 页面正常。看起来完全健康。
- 但日志里有 `SandboxUnavailableError: unshare(CLONE_NEWNS) failed with errno 1
  (EPERM)`，栈是 `session_background._ensure_background → providers.acp.start →
  acp.client._spawn → sandbox.wrap_argv`。
- 后果到第 5 步才爆：任何 ACP 会话都起不来，实验无从做起。第一次重启网关后端口
  干脆空了，从外面看只是「服务没起来」，没有任何指向沙箱的提示。

### 根因

本机 Ubuntu 开了 `kernel.apparmor_restrict_unprivileged_userns=1`，非特权进程建
user namespace 必须命中一个带 `userns,` 的 AppArmor 档案，而档案是**按被 execve 的
文件路径**附着的。

`dev-backend.sh` 最后一行是 `exec "$RUNTIME_PYTHON" -m kiro_crew gateway` ——
被 exec 的是 **python 解释器**，档案永不命中，`unshare` 吃 EPERM。仓里
`20260923-135214-apparmor-userns-multi-instance-launcher.md` 记过这个坑（结论：
直接 exec 带 shebang 的 `kirocrew` 启动脚本），但它有个**worktree 下才出现的新细节**：

- 本 worktree 的 `.venv` 是**软链**到主检出（派工单要求不重装依赖），所以
  `.venv/bin/kirocrew` 的真实路径是主检出的
  `/home/jereh/.../KiroCrew/.venv/bin/kirocrew`；
- 现成档案 `kirocrew-launcher` 附的正是那条主检出路径。于是**照 dev-backend.sh 的
  python 起法换成 exec 启动脚本也不够**——execve 目标是 argv[0] 拼出来的路径，
  必须写成档案里那条**真实路径**才算命中，写软链路径不认。
- 给这个 worktree 单独写一份档案要 `sudo apparmor_parser`，而派工单没给这个授权。

### 修法

不拆沙箱、不动 sysctl、不开 `sandbox_allow_unsandboxed_exec`（那是 owner 专属决定）。
在 gitignore 目录里放一个启动脚本，exec 档案已覆盖的**真实路径**，源码仍然用本
worktree 的：

```bash
export PYTHONPATH=/…/KiroCrew-wt-kc-v1/src       # 关键：editable 装的是主检出
export KIROCREW_HOME=/…/KiroCrew-wt-kc-v1/.kirocrew-dev
export KIROCREW_PORT=6790
exec /home/jereh/repo/github.com/kirodotdev/KiroCrew/.venv/bin/kirocrew gateway --no-open
```

验三件事，缺一不可：

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:6790/     # 200
cat /proc/<网关pid>/attr/current                                     # kirocrew-launcher (unconfined) = 命中
PYTHONPATH=$PWD/src .venv/bin/python -c "import kiro_crew;print(kiro_crew.__file__)"  # 必须是本 worktree 的 src
```

改完日志里 `SandboxUnavailableError` 归零，会话正常起。

## 坑 2：`kirocrew token` 给的链接票只有 300 秒，`--ttl` 管不着它

### 现象

- 用 `…?token=` 调接口，前几分钟一切正常，之后**突然**全变
  `{"error": "token expired", "code": "forbidden"}`。
- 更误导的是中间态：某个时刻 messages 接口返回的是 `{"messages": [], …}` 里
  `n=0`、`running=None`，看起来像「会话没了 / 实验失败」，其实是鉴权已经失败后
  的降级响应。整个实验一度被判成「会话起不来」。
- 按 `--help` 写的「default: 20h」给了 `--ttl 3h`，票**照样 300 秒过期**。

### 根因

那个票是**一次性握手票**，`exp` 恒为签发时刻 +300 秒，浏览器拿它换 `mc_token_<port>`
会话 cookie。`--ttl` 只搬 `session_exp`（换到的会话票寿命），不动 `exp`。
把票当长期 API 凭据用，必然在使用中途失效。

顺带一条同源误导：网关日志

```
WARNING … session MCP: withholding the whole mcpServers array …
This session runs without Crew's MCP tools; remove or rename the project's own
.claude/settings.local.json to restore them.
```

写的是「把工作区那份 settings.local.json 删掉就能恢复」。**实验目录不许改**，
所以这条无从执行；它同时解释了为什么写文件要人在网页上点批准（Crew 不是该文件的
作者，就把审批权还给用户），无人应答 180 秒后自动拒绝：

```
Tool approval for 'Write …' went unanswered for 180s; declining
```

### 修法

- 脚本化调用**不要用链接票**：先 `curl -c jar "<链接>"` 换 cookie，之后一律 `-b jar`。
  两个细节：换到的 `mc_token_<port>` / `mc_refresh_<port>` 都是 **HttpOnly**，在 jar
  里带 `#HttpOnly_` 前缀，用 `grep mc_token` 之外再随手 `grep -v '^#'` 自查会看成
  「一个 cookie 都没拿到」（其实拿到了）；cookie 的 **Domain 是签发时用的那个主机名**，
  用 `http://localhost:6790` 换的就只对 `localhost` 生效，回头拿它请求
  `http://127.0.0.1:6790` 一样 403 `Token required` —— 换和用必须同一个主机名。
- 轮询一个会话的回复，最省事的读法是直接看落盘 transcript，绕开鉴权与分页：
  `$KIROCREW_HOME/sessions/dashboard_<slot>.jsonl`；要看**模型真正收到的提示词**与
  内部事件（如 `agent-setting`、`prompt_snapshot`），看内层
  `~/.claude/projects/<cwd 编码>/<sessionId>.jsonl`，`$KIROCREW_HOME/session_map.json`
  存着 slot → sessionId + cwd 的映射。
- 无人值守跑要写文件的会话，提前在网页上把批准点掉，或按需接受「被拒后继续」。

## 怎么避免

- **worktree 里起网关：先看 `/proc/<pid>/attr/current`，别看服务是否 200。**
  服务 200 与会话能不能起是两件事；档案没命中时前者好得很。`ls /etc/apparmor.d/ |
  grep kirocrew` 找现成档案附的真实路径，exec 那条路径，用 `PYTHONPATH` 换源码树。
- **`kirocrew token` 的链接票 = 浏览器一次性入场券**，300 秒，`--ttl` 改不了它。
  脚本一律换 cookie 或用 transcript。
- 用 `tmux send-keys -l` 送长命令时，**-l 只是把字打进去，不提交**。要显式再发一次
  `Enter`，否则命令停在提示符里，下一轮「重启」看起来毫无反应，其实两次都没执行。
