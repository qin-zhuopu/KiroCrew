# 仿〔信任会话〕开关：判定处不在设值处，策略 key 不在会话 key 上

## 现象

做「开始开发」：一次跑要给自己开 3~10 个会话，每个都要像运营者在前端点了〔信任会话〕
一样不再逐条问批准。照着 `dashboard.chat_handlers.api_chat_mode` 里
`mode == "trust"` 那条分支抄了三行：

```python
slot._trust = True
sessions.set_approval_policy(effective_session_key(slot), "auto")
sel().log_api_access(...)
```

（`sessions` 在 handler 里是 `app["state"].sessions` 那个 `SessionManager`，
不是某个 `dashboard.sessions` 模块——照着名字抄会 import 到不存在的东西。）

单测里拿 `MagicMock` 当槽位，全绿。真跑（本单只做单测，交 master 合并后跑）之前心里没底，
去核判定处，发现三处对不上：

1. 我以为信任判定在 `hooks.py`——**`hooks.py` 里根本不读 `_trust`**（全仓
   `grep -rn "\._trust"`，它一次都不出现）。判定在别处，改判定的一改，我这份复制就静默失效。
2. `from kiro_crew.dashboard.chat_handlers import effective_session_key` 报 ImportError，
   而它明明就在那份文件里能用。
3. `sel().noop()` 不存在（我照某些模块的写法猜的），一调就 AttributeError。

## 根因

### 1. 判定处是 `chat_runner._slot_is_trusted`，它认两种表示，不止一面旗

```python
if getattr(slot, "_trust", False):
    return True
scope = str(getattr(slot, "_trust_scope", "") or "")
if not scope:
    return False
return bool(safety_override().is_scope_active(scope))
```

- `slot._trust` 是**人点的**旗（不过期，点击本身就是审计记录）；
- `slot._trust_scope` 是给「没人在旁边点」的无人值守 worker 用的 `SafetyOverride`
  Scoped 授权：激活时 SEL fail-closed 审计、**带 TTL**、每次批准都回查
  `safety_override().is_scope_active`。

只看设值处（`api_chat_mode`）会以为自己复制全了：那条路径是「人点」的形状，而**跑开发的
会话恰恰是「没人点」的形状**。最小可用版照旗来做没错（一次跑几十分钟、窗口里有人），
但必须知道另一条路存在：真要无人值守长跑，正确做法是 Scoped 授权，不是把旗常亮，
更不是去 `hooks.py` 加豁免（`hooks` 那道 PreToolUse 闸是 fail-open 的，它自己的注释里
就写了「决策在下游重做」）。

顺带一句：派工单让我去 `messaging/session_trust.py` 和 `messaging/approval.py`
（给了行号）里「找网页〔信任会话〕按钮最终调的那个函数」。**那两个不是网页那条**：
`session_trust.add_trusted_session` 的 `_trusted_sessions` 映射只有
`slack/handler.py`、`telegram/transport_dispatch.py`、`dashboard/server.py` 的
频道批准在读，`approval.py` 的 `_grant_session_trust` 是 IM 里点卡片批准的落点。
网页按钮落的是 `api_chat_mode` 那个分支（旗 + 策略 + 审计），判定在
`chat_runner._slot_is_trusted`。**照字面去调 IM 那个函数，我们的看板 slot 一样会逐条问批准**
（`_trusted_sessions` 里没有我们的 key，而 `_slot_is_trusted` 根本不查它）。
认「谁读这个状态」比认「谁写这个名字相近的状态」可靠。

### 2. 策略 key ≠ 槽的会话 id：必须用 `effective_session_key`，且它住在 `chat_utils`

`SessionManager.set_approval_policy(key, policy)` 是**按 key 存的**，而一个槽可能被链到
别的会话（`slot.linked_session_key`），此时它对外生效的 key 不是自己的 `slot.key`。
用 `slot.key` 存策略 → 旗插在 A 槽、批准查 B 的策略，表现就是「明明信任了还是问」。

纯函数 `effective_session_key(slot)` 有**两份同名实现**：`dashboard.chat_utils` 里一份、
`dashboard.chat_handlers` 里一份。导 `chat_handlers` 那份能跑，但那份文件一万三千行，
`import kiro_crew.dashboard.chat_handlers` 实测十几秒，测试收集期白付这笔钱——
**能从 `chat_utils` 拿的就从 `chat_utils` 拿**。（我原先记成「`chat_handlers` 末尾有
`exec()` 所以不能 import」，那是记错了，`grep -c 'exec('` 是 0；慢是真慢，理由要写对。）

### 3. 旗按 slot 存，策略按 session 存：共用一个会话的槽要一起打旗

`api_chat_mode` 的 trust 分支不是「给我这一个槽打旗」，它先算
`_granted_key = effective_session_key(slot)`，再遍历 `state._slots` 把
**每个 effective key 相同的槽**都打旗，最后只设一次策略。只给自己手上这一个槽打旗，
两个共用同一会话的槽就各执一词，之后的传播按 `_slots` 的迭代顺序决定谁覆盖谁——
不是按运营者（这里是我们自己）要什么决定。`devdag.grant_trust` 里那段
`for sharing in state._slots.values()` 就是补这一课，
`test_grant_trust_does_what_the_web_trust_button_does` 拿「自己的槽 / 链到同一会话的槽 /
别人的槽」三个一起验：前两个要打旗，第三个不能被打旗。

### 4. 策略只在当前 asyncio 任务里可见

`set_approval_policy` 存的是 `contextvars.ContextVar`：**换任务跑就看不见**。
调度器必须在**同一个任务栈**里「建槽 → 开信任 → 发 prompt → 等结果」，不能把
`grant_trust` 丢到别的 task / thread 里预热。

### 5. 顺带两个

- 审计只有一条路：`sel()` 回的是 `SecurityEventLog`，方法叫
  `log_api_access`——**整个包里没有任何 `noop()`**（`grep -rn "def noop" src/kiro_crew/`
  只命中某个内置 skill 脚本里的 `noop_ratio`），别指望有个「关掉审计」的口子。
  照 `api_chat_mode` trust 分支与 `_deny_trust_pattern` 的写法：`sel().log_api_access(...)`
  外面包 `try/except` + `logger.warning`，审计挂了不连累已授出去的权。
  `caller=` 也别照抄 `audit_caller("dashboard:mode")`——那是 `api_chat_mode` **里面的嵌套函数**，
  导不出来，我们这种非 dashboard 调用方直接写字面量（`caller="ai-studio:dev"`）。
- `mcp_manage_claude._call_with_id_handling` 见 `id is not None` 就直接回
  `already_submitted`，**而带 `sessions[]` 的响应只在 `id is None` 那条路径产生**。
  要拿会话 id 只能 `session_id=None` 发，且**发之前先把槽建好**——`session_id=None`
  会走 `resolve_session_id` 另派生一个，槽没建好就会话对不上。

## 修法

`backend/devdag.grant_trust(state, slot)` 把三件事收进同一个调用栈，调用点再回读自证：

```python
slot._trust = True
state.sessions.set_approval_policy(effective_session_key(slot), "auto")  # 从 chat_utils 导
sel().log_api_access(caller="ai-studio:dev", operation="mode_change:trust",
                     outcome="enabled", resources=...)
```

`DevRun._run_node` 在**发 prompt 之前**、同一任务里调用它，然后
`if not slot._trust:` 记「这个会话没能进入信任模式」。测试里 `monkeypatch` 掉模块级
`grant_trust`，就能验「授权完不成时这一轮绝不发出去」；审计只断言
`operation == "mode_change:trust"` 这条**有没有落**，不数日志条数。

## 怎么避免

1. **仿一个前端开关时，去读它的判定处，不要只读它的设值处。**
   〔信任会话〕设值在 `api_chat_mode`，判定在 `chat_runner._slot_is_trusted`
   （`dashboard/server.py` 的批准循环另有一处直接读 `slot._trust`）——只看设值会漏掉 Scoped 那半。
2. **`from kiro_crew.dashboard.X import` 之前先 grep 这个名字还在哪出现**，
   能拿轻模块（`chat_utils`）就不拖一万三千行的 `chat_handlers`。
3. **contextvar 存的策略活不过任务切换**：授权与使用同栈，用之前回读一次。
