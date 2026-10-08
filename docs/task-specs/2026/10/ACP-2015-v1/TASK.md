# 派工单 ACP-2015-V1：起开发服务器 + 验证「网页聊天里的 Claude 会话能否以 requirement-writer 为主助手」

> 需求依据：`docs/request-for-change/rfc-ai-studio-req-flow.md` §9.3「要先验证的技术点（V1）」、§13 第 1 步。
> 本单**不写业务代码**。只做三件事：①把开发服务器起来 ②做 V1 实验 ③把结论写回 RFC。
> 每一步做完，在聊天里说一句「第 N 步完成：<结果>」。卡住超过 10 分钟，停下来把报错原文贴出来，不要乱改。

## 你的地盘（只许用这些，别的端口/目录一律不碰）

| 东西 | 值 |
|---|---|
| 工作目录 | `/home/jereh/repo/github.com/kirodotdev/KiroCrew-wt-kc-v1`（你现在就在这里） |
| 分支 | `feature/ACP-2015-v1` |
| 网关端口 | `6790` |
| 前端（vite）端口 | `6791` |
| 域名 | `https://kc-v1-14409-dev.gb10.jereh-pe.cn/`（已配好，转发到 6791） |
| 开发数据目录 | `/home/jereh/repo/github.com/kirodotdev/KiroCrew-wt-kc-v1/.kirocrew-dev`（不进 git） |
| V1 测试目录 | `/home/jereh/repo/jc/webapp-template-wt-kc-v1-probe`（里面已放好 `.claude/agents/requirement-writer.md` 和 `.claude/settings.local.json`，**只读，不许改**） |

`.venv` 和 `website/node_modules` 已软链到主仓，**不要**运行 `pip install` / `npm install`。

## 第 1 步：起网关（后端）

在一个新的 tmux 窗口里跑（让它一直开着）：

```bash
tmux new-window -t claude-kc-v1 -n gw
tmux send-keys -t claude-kc-v1:gw 'cd /home/jereh/repo/github.com/kirodotdev/KiroCrew-wt-kc-v1 && eval "$(python3 -c "import json;e=json.load(open(\"/home/jereh/.claude/settings.jqw.json\"))[\"env\"];print(\" \".join(\"export %s=%s;\"%(k,json.dumps(str(v))) for k,v in e.items()))")" && KIROCREW_PORT=6790 KIROCREW_HOME=$PWD/.kirocrew-dev ./dev-backend.sh 2>&1 | tee .kirocrew-dev-gw.log' Enter
```

（前面那段 `eval` 是把千问模型的接入配置放进网关进程的环境变量里，网关起的 Claude 会话才连得上模型。）

**判据**：`curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:6790/` 返回 200 或 401（401 也算起来了）。

## 第 2 步：设置域名白名单和默认用 Claude

```bash
cd /home/jereh/repo/github.com/kirodotdev/KiroCrew-wt-kc-v1
export KIROCREW_HOME=$PWD/.kirocrew-dev PYTHONPATH=$PWD/src PY=$PWD/.venv/bin/python
$PY -m kiro_crew config set dashboard.url https://kc-v1-14409-dev.gb10.jereh-pe.cn
$PY -m kiro_crew config set agent.acp_backend claude
$PY -m kiro_crew config get agent.acp_backend
```

**判据**：最后一行打印 `claude`。然后**重启网关**（在 gw 窗口 Ctrl+C，再按上箭头回车），设置才生效。

## 第 3 步：起前端（vite）

```bash
tmux new-window -t claude-kc-v1 -n vite
tmux send-keys -t claude-kc-v1:vite 'cd /home/jereh/repo/github.com/kirodotdev/KiroCrew-wt-kc-v1/website && KIROCREW_PORT=6790 __VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS=kc-v1-14409-dev.gb10.jereh-pe.cn npx vite --port 6791 --strictPort --host 0.0.0.0 2>&1 | tee ../.kirocrew-dev-vite.log' Enter
```

**判据**：`curl --noproxy '*' -s -o /dev/null -w '%{http_code}' https://kc-v1-14409-dev.gb10.jereh-pe.cn/` 返回 200。

## 第 4 步：拿登录链接给用户

```bash
cd /home/jereh/repo/github.com/kirodotdev/KiroCrew-wt-kc-v1
KIROCREW_HOME=$PWD/.kirocrew-dev PYTHONPATH=$PWD/src .venv/bin/python -m kiro_crew token --port 6790
```

它会打印一个 `http://...:6790/?token=xxxx` 的链接。把前面的 `http://<主机>:6790` 换成 `https://kc-v1-14409-dev.gb10.jereh-pe.cn`，**把换好的完整链接写进本目录 `docs/task-specs/2026/10/ACP-2015-v1/LOGIN.txt`（这个文件不许提交）**，并在聊天里说「登录链接已写进 LOGIN.txt」。不要把 token 贴进聊天。

**判据**：用 `curl --noproxy '*' -s -o /dev/null -w '%{http_code}' "<换好的链接>"` 返回 200 或 302。

## 第 5 步：V1 实验（不改代码，用 Spec Builder 起一个在测试目录里跑的会话）

原理：Spec Builder 新建规格时要填工作目录，后端会把会话的工作目录（`slot.project`）设成它（代码：`src/kiro_crew/apps/builtins/spec_builder/backend/runtime.py` 第 627–660 行）。我们借它看「Claude 会话在一个带 requirement-writer 的目录里跑时，是不是以 requirement-writer 身份说话」。

5.1 先确认机器能跑 Claude 后端：

```bash
cd /home/jereh/repo/github.com/kirodotdev/KiroCrew-wt-kc-v1
KIROCREW_HOME=$PWD/.kirocrew-dev PYTHONPATH=$PWD/src .venv/bin/python -c "from kiro_crew.agent_sdk.backend_install import probe_backend; print(probe_backend('claude'))"
```

**判据**：打印里有 `installed='installed'`（master 已核过）。如果报错说找不到 `claude-agent-acp`：**停下来，把报错原文贴到聊天里**，不要自己装。

5.2 用接口建规格（工作目录 = 测试目录）。先读 `src/kiro_crew/apps/builtins/spec_builder/backend/handlers.py` 里 `_handle_create`（约 439 行）看要传哪些字段，然后：

```bash
TOKEN=<LOGIN.txt 里 token= 后面那串>
curl -s -X POST http://127.0.0.1:6790/api/apps/spec-builder/specs \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"v1-probe","working_dir":"/home/jereh/repo/jc/webapp-template-wt-kc-v1-probe","spec_type":"feature","description":"V1 probe"}'
```

如果接口要的字段和上面不一样，以 `_handle_create` 为准。如果鉴权方式不是 Bearer，以 `src/kiro_crew/dashboard/` 里 token 中间件为准。**也可以直接在网页里操作**：打开登录链接 → 进 Spec Builder → 新建，工作目录填测试目录。两种都行，选一种做成就行。

5.3 给这个会话发一句话（网页聊天框里打，或调 `/api/apps/spec-builder/specs/v1-probe/message`）：

> 我想做一个「设备点检记录」页面。帮我把需求理清楚。

5.4 等它回复（最多 5 分钟）。按下表判：

| 看到的 | 结论 |
|---|---|
| 回复是**一轮 ≤5 道选择题**，每题有 A/B/C… 和「X. 其它」，带「[我的建议：…]」 | **V1 通过**：Claude 会话认了工作区里的 requirement-writer |
| 回复是普通助手的样子（直接写方案、或开始按 Spec Builder 的 Requirements→Design→Tasks 走） | **V1 不通过** |
| 会话起不来 / 报错 | **V1 未完成**，记下报错原文 |

5.5 不管结果如何，再查一件事并记录：会话进程的工作目录是不是测试目录。

```bash
ps -eo pid,args | grep -E "claude-agent-acp|claude " | grep -v grep
# 对上面每个 pid：
readlink /proc/<pid>/cwd
```

**判据**：至少一个 Claude 相关进程的 cwd 是 `/home/jereh/repo/jc/webapp-template-wt-kc-v1-probe`。

5.6 **如果 V1 不通过**，再试一次退路：在同一个会话里发

> 先读 .claude/agents/requirement-writer.md，从现在起完全照它的规则和我对话。我想做一个「设备点检记录」页面。

记录这次是否变成选择题形式。

## 第 6 步：把结论写回 RFC 并提交

打开 `docs/request-for-change/rfc-ai-studio-req-flow.md`，在 §9.3「要先验证的技术点（V1）」那一段**下面**加一小节，格式照抄，方括号换成真实内容：

```markdown
**V1 结论（2026-10-08，ACP-2015-V1）**：[通过 / 不通过 / 未完成]
- 环境：网关 6790、vite 6791，`agent.acp_backend=claude`，模型来自 settings.jqw.json
- 做法：Spec Builder 建规格，working_dir=`/home/jereh/repo/jc/webapp-template-wt-kc-v1-probe`
- Claude 进程 cwd：[实际值]
- 首轮回复是否为 ≤5 道选择题：[是 / 否]，回复开头原文：「[前 100 字]」
- 退路（让会话先读 agent 文件）：[未试 / 有效 / 无效]
- 结论对实现的影响：[一句话]
```

然后：

```bash
cd /home/jereh/repo/github.com/kirodotdev/KiroCrew-wt-kc-v1
git add docs/request-for-change/rfc-ai-studio-req-flow.md docs/task-specs/2026/10/ACP-2015-v1/TASK.md
git commit -m "docs(rfc): V1 result — Claude session vs workspace requirement-writer (ACP-2015)"
git push fork feature/ACP-2015-v1
```

**只 add 这两个文件**。`LOGIN.txt` 不许 add。禁止 `--no-verify`。只推 `fork`，不许推 `origin`。

## 第 7 步：完成报告

在聊天里写：
1. 第 1~6 步每步一行：完成/未完成 + 判据结果
2. V1 结论（通过/不通过/未完成）
3. 提交号
4. 两个开发服务器**保持开着**，不要停（用户要继续看）

## 禁止
- 改任何 `src/`、`website/src/` 代码
- 用 6790/6791 以外的端口；改 web-gateways / nginx 配置
- 改测试目录里的文件
- 运行 `pip install`、`npm install`、`git push origin`、`git push --force`
