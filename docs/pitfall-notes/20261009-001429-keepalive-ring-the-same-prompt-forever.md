# 完工的会话被 keepalive 反复催同一句话：十三次「全部完成」

## 现象

一张单（ACP-2085-S2）早就做完了：两个提交在、fork 上远端 hash 对得上、报告写完、
Jira 子单已流转「完成」。之后同一个派工提示（「继续做 …TASK.md，从你没做完的那一步
接着做…全部完成后只回复『ACP-2085-S2 全部完成』」）**一字不差地重复到达十三次**。
每次我都当成新指令，重新跑一遍复核（pytest / vitest / tsc / ls-remote），重新回一句
「ACP-2085-S2 全部完成」。中间有一次真的去查「是哪来的」，但只查了 cron 里我自己那个
`CronList`（空）就放过了，于是继续被催。

副作用不是假的：第 4、5 次重复时我为了「找没做完的那一步」又跑了一轮全量 vitest
（238 用例，机器当时正被 `fe autopilot` 的满负荷跑占着），白占 CPU 与内存，
并且往同一台已经紧张的机器上再加了一份负载。

## 根因

本机 crontab 里有一条**每分钟**的任务：

```
* * * * * cd /home/jereh/repo/jc/jereh-cli && node jereh-cli.js agent keepalive tick
```

它读一张「工作目录 → 目标」登记表（`jc agent keepalive list` 看），
**会话一空闲就把它的目标原文再发一遍**，目的是把中途停摆的 agent 拽回来继续干。
问题在两处设计：

1. **判活只看忙闲，不看做完没做完**。会话空了 = 「停了，去催」，
   而「已经交付完毕、正在等人来验收」在它眼里同样是空闲。
2. **自己说做完了不会自动摘牌**。帮助原文：
   `A session self-claiming 'done' does NOT auto-remove.`
   也就是说 agent 回多少句「全部完成」都没用，**必须有人跑 `remove`**。

我这一单的目标文本里还带「不要停下来等我确认」，于是形成一个闭环死结：
它自己说不要停 → 我确实没停 → 但活已经干完 → 于是我只能反复回答同一句话。
登记表里这条是 22:15 加的，我完工（约 00:05）之后没人摘它。

日志里能直接看出来，`~/.jereh-cli/keepalive-cron.log` 每分钟一段，本仓目录长期是
`idle-progressing`（推进过 = 又发了一次目标），而不是任何「已完成」状态：

```
keepalive tick：检查 10 个会话
  idle-progressing  /home/jereh/repo/github.com/kirodotdev/KiroCrew-wt-kc-v1
```

## 修法

一条命令摘牌，摘完 `list` 里就查不到了（我当时做的）：

```bash
jc agent keepalive remove /home/jereh/repo/github.com/kirodotdev/KiroCrew-wt-kc-v1
# {"data":{"removed":1,"total":7}}
jc agent keepalive list | grep -c KiroCrew-wt-kc-v1   # 0
```

只摘自己这一条，**别的会话的登记一条没动**（那些 worker 还在跑，摘了才是真停摆）。
要整台机器停下来是另一条命令 `jc agent stop-all`，本次没用。

## 怎么避免

- **同一句话第二次原样到达时，先查「谁在发」，不要先复核。** 第一次可以当新指令，
  第二次就该怀疑是自动重放。判断成本极低：`crontab -l` 加 `jc agent keepalive list`，
  两条命令，几十毫秒。我前面八九次都省了这一步，纯浪费。
- **派活的人登记了 keepalive，收活的人就要负责摘牌。** 完工收尾的清单里，
  `keepalive remove` 和「Jira 流转完成」是同一级别的必做项；只要目标文本里写着
  「不要停下来等我确认」，那它**必须**被显式摘掉，否则机器永远不会认为你结束了。
- 报告/评论里说「已交付」的同时，把摘牌也做掉，别留给别人。
- 反面教训一条：**不要用重跑全量测试来回应一句重复的指令**。
  真需要自证时，一条 `git rev-parse <remote>/<branch>` 的远端 hash 就够了。
