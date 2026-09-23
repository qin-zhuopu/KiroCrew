# 填坑：tmux claude 会话的新建/重启/切 settings 与 send-keys 派活

日期：2026-09-23。给 req-design 会话换 glm settings 时把三件事一次踩齐：会话名对不上、settings 换不了、回车发不进去。

## 现象

- `tmux kill-session -t claude-jereh-cli-req-design` 报 can't find session——jc spawn 起的会话名带了 jereh-cli 前缀（`claude-jereh-cli-req-design`），凭记忆写名必错。
- 想把跑着的会话从 jqw 换成 glm：往运行中的会话里「改设置」是不存在的操作——settings 只在 claude 进程启动时读取。
- 用 `tmux send-keys "..." Enter` 一条命令派活，文字进框、回车被吞（本仓已有笔记
  [20260923-103512-tmux-send-keys-enter.md](20260923-103512-tmux-send-keys-enter.md)，实操中仍连吞三次，必须 capture 自证）。

## 根因

- **会话名三方对齐**：tmux 会话名 = claude `--name` = `claude agents --json` 的 name，但 jc worktree spawn 会给 name 再加仓前缀——操作前先 `tmux ls` 看真名，别拼。
- **settings 是启动参数**：换 settings = 杀进程重启，没有热切换。会话运行态随 tmux/进程消失，重启丢当前对话上下文（必要时先让它把状态写进 Jira 评论/文件再重启）。
- **回车必须单独一发**：括号粘贴模式吞跟在文本后的回车；且要发完 capture-pane 验证，一次不自证就可能白等。

## 修法（标准流程）

### 新建

```bash
jc worktree spawn --branch <名>          # 派生 worktree + 分支 + tmux 会话（settings 目前固定 jqw，--settings 参数立项开发中）
# 或手工：
tmux new -d -s claude-<名> -c <工作目录> \
  "claude --allow-dangerously-skip-permissions --dangerously-skip-permissions \
   --effort low --settings /home/jereh/.claude/settings.<预设>.json --name '<名>'"
```

### 重启/切换 settings（同一套，三步）

```bash
tmux ls | grep <名>                       # 1. 查真实会话名
tmux kill-session -t <真实会话名>          # 2. 杀掉（claude 进程随之结束）
tmux new -d -s <真实会话名> -c <原工作目录> "claude ... --settings <新预设> --name <名>"   # 3. 原目录重启
```

要点：**`-c` 必须给回原工作目录**（worktree 路径），否则 claude 按错误目录解析项目，resume/文件全错。

### 派活（发指令）

```bash
tmux send-keys -t <会话> "指令文本"
sleep 1
tmux send-keys -t <会话> Enter
sleep 3
tmux capture-pane -t <会话> -p | grep -m 5 ""    # 自证：看到转圈/工具调用才算发出
```

回车被吞的补救：再单独发一次 `tmux send-keys -t <会话> Enter`，再 capture。

## 怎么避免

- 动任何 tmux claude 会话前先 `tmux ls`，名字一律以它为准。
- 把「换 settings=重启」当常识记住，别找热切换；重启前让 worker 先落盘状态。
- 派活三件套（文本、sleep、单独回车）+ capture 自证，写进手指记忆。
- resume 历史会话等 jc `worktree resume` 子命令落地后用它（已立项，jc master 开发中）；落地前按全局 CLAUDE.md 手写三步：查 cwd → cd 对目录 → `claude --resume <sessionId>`。
