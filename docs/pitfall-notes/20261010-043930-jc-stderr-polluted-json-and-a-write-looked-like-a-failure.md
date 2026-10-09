# `2>&1` 混进 JSON 解析：写操作其实成功了，我却当失败重跑了一遍

ACP-2222 开工时踩的。给 Jira 单子流转状态，我习惯把 stderr 一起收进来好看清报错：

```bash
JC_JIRA_SID=kc-prod jc jira issue transition ACP-2222 --to 开始进行 --force 2>&1 \
  | python3 -c "import sys,json; d=json.load(sys.stdin); ..."
```

结果：

```
json.decoder.JSONDecodeError: Expecting value: line 1 column 2 (char 1)
```

我读成「命令失败了，状态没流转成」，于是**又跑了一遍**。第二遍报：

```
[jira] --force 越过归属护栏：ACP-2222 归属 sid-master，不是你（sid-kc-prod）。
{"success":false,...,"message":"无可用流转 \"开始进行\"；可选: 停止进行→待办, 完成→完成"}
```

`--to 开始进行` 不见了、只剩「停止进行 / 完成」——**因为第一遍已经成功了**，单子当时
已经在「测试中」。真实情况是：写操作一次就成了，我的解析失败纯属自找，而「失败了」的
误判让我把一条**不幂等的写操作重跑了一遍**。这次重跑恰好无害（第二遍什么都没改成，
只是报错），换个场景就是重复评论、重复建单、重复部署。

## 根因（两条叠在一起）

1. **`jc` 的输出是分道的**：人类可读的提示走 **stderr**，机器可读的 JSON 走 **stdout**。
   实测（拿一个不存在的 issue 试，无副作用）：

   ```bash
   jc jira issue comment DOES-NOT-EXIST --body x --force 2>/dev/null   # → 干净 JSON，能 parse
   jc jira issue comment DOES-NOT-EXIST --body x --force 2>&1 >/dev/null  # → 护栏提示在这条流里
   ```

   `--force` 那句 `[jira] --force 越过归属护栏…` 就在 stderr。`2>&1` 把它拼到 JSON 前面，
   第一个字符是 `[`，于是 `Expecting value: line 1 column 2`。
   报错文案完全没提「有第二股输出」，所以第一反应总是「命令挂了」。

2. **解析失败 ≠ 写操作失败**。`jc` 在打印之前早就把写请求发完了。JSON 解析是我这边的
   后处理，它挂了不影响服务端已经发生的事实。

## 修法

- **要解析就只吃 stdout**：管道里不要写 `2>&1`。要同时看 stderr，就分两次跑，或者
  `cmd 2>/dev/null | python3 …` 先拿结论，需要诊断时再单独跑一次 `cmd 2>&1 >/dev/null`
  专门看 stderr。
- **写操作解析失败时，先查状态，再决定要不要重发**。这次正确做法是
  `jc jira issue get ACP-2222` 看 `status`——一条只读命令就知道「其实已经到了测试中」。
- 顺带：`--force` 的归属护栏在**任何写请求发出前**就拒（ACP-63 的设计），所以「护栏提示
   + success:false」= 确实没写；而「只有解析失败、没有 success:false」= **多半写了**。
   这两种「失败」要在脸上区分开，别都当「没做成」。

## 怎么避免

- 固定习惯：**解析 JSON 的管道一律不带 `2>&1`**。需要 stderr 就单独取。
- 任何非幂等的写（建单、评论、部署、推送），重试前先跑一次只读的「它到底成了没」。
  这比给命令加 `--retry` 便宜，也不会把「重复」变成既成事实。
- `jc` 的这类提示以后尽量也走 stdout 的 JSON（作为 `warnings` 字段），这样管道天然不会
  被污染 —— 已作为 jereh-cli 的改进项记在 ACP-2222 的评论里。
