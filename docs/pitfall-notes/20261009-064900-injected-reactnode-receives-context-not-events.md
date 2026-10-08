# 注入的 ReactNode：`window` 事件收不到，Context 才收得到（ACP-2150/2151）

时间：2026-10-09 06:49　工单：ACP-2085 S6「需求页〔开始开发〕发出的事件没接到开发页签」

## 现象

`RequirementPage` 的〔开始开发〕成功后 `window.dispatchEvent(new CustomEvent('ai-studio:start-dev', {detail:{projectId, page}}))`，
开发页签上没有任何反应：不切页签、不调 `dev/plan`。单子写的是「DevDagPanel 没监听」，
照着在 `DevDagPanel` 里 `useEffect` + `window.addEventListener` 加了一个 —— **测试里仍然一次都不触发**，
`planDev` 调用数恒为 0，而页签确实切过去了（`aria-selected="true"`）。

## 根因

两句话：

1. **监听的人干活的时候不在场。** `DevDagPanel` 是 `ToolSidebar` 的 `devBoard` prop（注入节点），
   只在 `tool === 'dev'` 那个分支里渲染。事件到达时用户还在「需求」页签，板子**根本没挂载**，
   它的 `useEffect` 也就从未执行 —— 挂在一个不存在的组件上的监听器，等于没有监听器。
2. **`devBoard` 是「页面创建的元素」，但「侧栏决定渲染位置」。** 所以不能靠给 `DevDagPanel`
   多传一个 prop 解决：那个元素是 `AiStudioPage` 里 `<DevDagPanel projectId=… />` 创建好的，
   `ToolSidebar` 拿到的是已经定好 props 的 `ReactElement`，**外部再想塞 prop 就得克隆元素**，
   而克隆出来的 prop 只有创建方知道值 —— 创建方恰恰不知道侧栏什么时候想切页签。

中途我还写了一版**模块级队列**（`Map<projectId, request[]>` + 过期时间）让板子挂载后自己去捞，
测试能过，但那是把组件状态搬到模块全局：热更新/多项目/卸载重挂都要额外清理，且「谁拥有这份状态」
变得没人回答。已删。

## 修法

- **切页签归 `ToolSidebar`**：它拥有 `tool` 状态，它来 `addEventListener`，收到就 `setTool('dev')`，
  并把请求存进**自己的 state**（`{projectId, pages, seq}`，`seq` 自增）。
- **干活归板子，靠 Context 递下去**：`StartDevContext` 的 Provider 包在 `{devBoard}` 外面。
  **Context 是按节点在树里的位置读取的，不是按元素在哪里创建的** —— 页面创建的节点，
  被侧栏渲染在 Provider 内部，就照样读得到。这一点是整件事的关键，也是最容易想不到的一条。
- **`seq` + `served()` 保证只服务一次**：板子的 `servedRef` 记住已服务到的 `seq`，
  服务完回调 `served(seq)` 让侧栏清掉请求。没有这套，板子每次重渲染（拿到数据、10 秒自动刷新）
  都会把同一个请求再打一遍 `dev/plan` —— 服务端幂等，但那是白跑一轮 Jira。
- **卸载即干净**：请求存在侧栏 state 里，组件卸载就没了，不需要 TTL，也不会有跨测试残留。

## 怎么避免

- 看到「A 触发的东西 B 没收到」，先问 **B 在触发的那一刻挂载了吗**。
  没挂载的组件上的 `addEventListener` 不存在，这是「事件丢了」最阴的一种。
- **注入节点（injected `ReactNode`）的通信只有 Context 这一条正道**：prop 已经被创建方定死，
  ref 拿不到，`React.cloneElement` 是把结构问题伪装成一行代码。
- 一个组件「只在某个页签存在」是常态（懒渲染的 tab 内容都是），这类组件想要跨页签的信息，
  就只能由**页签的主人**向下提供。
