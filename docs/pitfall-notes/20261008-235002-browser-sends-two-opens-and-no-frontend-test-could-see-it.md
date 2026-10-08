# 浏览器把「开一次会话」发了两遍，前后端 251 条用例全绿

时间：2026-10-08 23:50　会话：kc-v1　单子：ACP-2085-S2（需求会话上页面）

## 现象

真跑第一轮：网页左栏的写需求助手**把同一个问题问了两遍**（同一句话、两个气泡，
紧接着第二轮又问了一遍）。界面其余部分全对：会话连上了、标题对、批准卡出现了。

看代码怎么读都看不出问题：

- 后端 `POST /projects/{id}/req-session` 有幂等标记（项目记录里的 `reqSessionStarted`），
  发过开场白就不再发；
- 后端 13 条用例绿，里面就有「第二次开同一项目不再发提示语」那条；
- 前端 24 文件 / 238 条用例绿，里面有「一个 sessionKey 上只 mount 一次」那条。

也就是说：**测试全绿，线上错乱**。这两组绿都真的测不到这件事。

## 根因

### 1. 幂等标记写在动作**之后**，中间隔着一整个 agent turn

```python
run_turn(state, slot, first_prompt(record, ws))          # ← 一次完整 agent 回合，几秒到几十秒
await asyncio.to_thread(update_project, project_id, **{STARTED_FLAG: True})
```

标记的语义是「发完了」，不是「轮到我发了」。两个请求先后进来：

```
请求A 读标记=False ──发开场白(几秒)──> 写标记=True
请求B      └── 在 A 写标记之前就读到了 False ──也发了一遍
```

后端那条「第二次不发」的用例是**串行**调两次，所以永远测不出来——串行时第一个
`await` 早就跑完了。

### 2. 首屏 mount effect 确实会跑两遍

`website/src/main.tsx` 整个 app 包在 `<StrictMode>` 里，开发模式下 React 会**故意**
把 mount effect 跑两遍（用来暴露不干净的 effect）。于是 `ChatPane` 里那个
「挂载即开会话」的 effect 真发两次 POST。这不是 bug（StrictMode 的设计如此），
生产构建不双跑，但**网关 dev 模式下真跑就是双跑**，而幂等是服务端的责任，
不该指望浏览器只发一次。

### 3. 前端测试看不见这件事，是架构性的

六个 ai-studio 套件都整份塞假 `api`（`vi.hoisted` 一堆 `vi.fn`），
`ChatPane` 用的 `useChatSocket` 也被桩掉。前端测试能断言「同一个 key 只挂一次」，
但「我朝后端发了几次开会话请求」在桩掉的 api 上根本不构成可观测事实。
两边各自green，组合起来错乱。

## 怎么挖到的

**不是看界面挖到的，是 `git grep` 服务端 transcript。** 会话落盘在

```
$KIROCREW_HOME/sessions/dashboard_<slot>.jsonl
```

第 0 行是 `_type: metadata`（带 `project` / `app` / `title`），
工具调用行的 `meta.input.command` 是**真实命令行**。grep 这个文件看到开场白
文本出现两次、`jc fe reqdoc check` 跑了 4 次（我只让它查过 1 次）。
服务端记录比界面诚实：界面上两个气泡看着像「它话多」，服务端计数直接是 2。

顺带这条也值一行：同一份 transcript 还自证了 `slot.project → CLI cwd` 那一跳是通的
（相对路径跑出来的 `data.file` 指向工作区），省了我一轮猜测。

## 修法

服务端加**进程内**在飞集合，「查 + 占」之间**不放 await**：

```python
if created and project_id in _starting:
    created = False                      # 别人正在发，我这一路不算首次
if created:
    _starting.add(project_id)
    try:
        run_turn(...); await asyncio.to_thread(update_project, ...)
    finally:
        _starting.discard(project_id)
```

- 持久标记仍是**跨重启**的权威（网关重启后 in-flight 集合是空的，靠它）
- in-flight 集合只负责关掉「读标记 → 写标记」这段窗口，放 finally 里清，异常不漏
- 用例必须**并发**打：`asyncio.gather(ensure(...), ensure(...))`，
  断言 `created` 一个是 True 一个是 False、dispatch 只被调一次、集合已清空。
  串行两个调用永远测不出来。

## 怎么避免

- **凡是「第一次进来做一次某事」的端点，并发是默认假设**，不是异常。
  幂等标记要么在动作**之前**占位（并处理进程中途死掉的悬挂），要么配一个
  覆盖这段窗口的进程内闸；写在动作之后的标记只能防「下次」，防不了「同时」。
- **补这种用例要用 `asyncio.gather`，不是连着调两次。** 串行重复调用是这种 bug 的
  天然掩护。
- **真跑必须查服务端 transcript，别只看界面。** 界面把「发了两遍」渲染成「它话多」，
  把「工具跑了 4 次」渲染成一条折叠行；服务端计数一眼就看出来。
  本机禁看图，本来就是靠 DOM/JSON 取证，顺手把 transcript 也当成一等证据。
- **`pkill -f <脚本名>` 会把自己的 Bash 调用一起杀掉**（我 `pkill -f 'drive_s2.mjs'`
  之后自己这条命令 exit 144 死掉，因为命令文本里含该模式，pkill 匹配到自己的父进程）。
  要杀就按 pid 杀，或者先 `pgrep` 看清单再挑，别用「模式匹配整个命令行」的省事写法。
  同一族：`pgrep -cf <模式>` 写在 Bash 命令文本里也会把这条 zsh 数进去，数出来偏大。

## 补（同一晚，同一个真跑）：探针的「已经答过了」用了**屏幕上有没有这几个字**

`drive3_s2.mjs` 等批准卡等满 6 分钟什么都没等到，事后核对发现**确认句根本没发出去**。
它的判断是：

```js
if (!s.chat.includes('对，按你说的写')) { await send(page, ANSWER) }
else say('answer already in the transcript, not re-sending')
```

而「对，按你说的写」这几个字，从助手给出
`[OPTIONS: 对，按你说的写 | 对，但同时给设备清单加分类 | …]` 那一刻起**就在屏幕上**
（选项 chip 是渲染在 transcript 里的按钮）。所以第一次快照就判成「已答过」，
跳过发送，去等一张永远不会出现的批准卡，6 分钟后浏览器被 OOM 侧打死，看起来像
「环境拖死了」，其实是**幂等判断用错了证据**。

- 幂等判断只能建立在**只有我这个动作能改变**的事实上。这里正确的事实是
  「服务端 transcript 的 user 行数变了 / 多了一条含这句话的 user 行」，
  不是「这句话出现在界面上」——**对方也可能把同一句话打在屏幕上**（选项、引用、
  回显、翻译、面包屑，全都是这种）
- 「发出去了没有」优先问**服务端**，不要问 DOM。`drive4_s2.mjs` 改成读
  transcript 计数，DOM 只做辅助
- 探针写「跳过」分支时要留一条大声的证据：这里如果当时把「为什么判定为已答过」
  打出来，第一眼就能看见是选项 chip 撞的

## 再补：同一份探针 15 分钟前能起页面，现在两次都「textarea 没出现」

改好的 `drive4_s2.mjs` 反而**连页面都起不来**（等 `[data-testid="ai-studio-chat"] textarea`
45 秒超时 ×2），而我 15 分钟前用同 URL 同 jar 的 `diag_page_s2.mjs` 拿到的是一页**全文**
（转写本文 5.2 那段就是从它来的）。对照着看只有一个差别：**探针脚本自己在 dev 域名上
只试 1~2 次**。这就是 `20261008-161000-*` 记的那个偶发丢模块（同机几十个 vite/vitest
并发时必现），跟前端代码无关——`curl -k .../src/main.tsx` 同期 200 / 43 KB。

所以「探针起不来」的第一反应应该是**换全新 context 多试几次**（同一 context 里 reload
救不回已断的模块图），不要顺手怀疑刚改的前端。同族假象，那篇笔记里都记了：
`/api/instances` 403、`@pierre/diffs` 一批 `ERR_ABORTED`、`/api/file-read` 404 ——
在 dev 域名上这些都是噪声，唯一可信的是**DOM 断言**。
