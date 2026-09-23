# 填坑：tmux send-keys 文本+Enter 一条命令发不出去

日期：2026-09-23。给后台 claude 会话（`claude-jereh-cli-req-design`）发首单指令，字全打上了却不出车。

## 现象

```bash
tmux send-keys -t claude-xxx "长指令……" Enter
```

目标 pane 的输入框里指令一字不差，但**没有提交**，会话干等。

## 根因

claude 输入框开启了**括号粘贴（bracketed paste）模式**。send-keys 把文本和 `Enter` 排在一条命令里时，文本作为一次粘贴进入，紧随其后的回车在粘贴收尾处理中被吞掉——只有文本落进输入框，回车事件丢了。

## 修法

文本与回车拆成两条，中间隔一秒：

```bash
tmux send-keys -t <会话> "要发的话"
sleep 1
tmux send-keys -t <会话> Enter
```

发完 `tmux capture-pane -t <会话> -p` 看到转圈/动效才算发出去了。

## 怎么避免

- 凡给 tmux 里的 TUI 程序（claude、vim、less…）派活，**回车永远单独一发**。
- 发完必须 capture-pane 自证，别假设发出去了。
