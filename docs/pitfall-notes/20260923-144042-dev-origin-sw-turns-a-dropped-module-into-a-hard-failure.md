# dev 域名上「页面代码没送到」：SW 把一次偶发丢包变成硬失败，报错却指向网络

## 现象

在 `https://kiro-dev.gb10.zhuopu.net/...` 上打开任意页面（`/chat`、`/workspaces`、
`/projects` 都一样），**时好时坏**地落到启动失败面板：

> This page could not finish loading / Part of its code never arrived … That is almost
> always the network or a proxy in front of it … `Could not load: <域名>/src/main.tsx`

CDP 实测到的证据：

- 一次加载要拉 900~1300 个模块，其中 **1~40 个随机路径** `net::ERR_FAILED`——没有 HTTP
  状态码，连响应都没拿到；失败路径与模块本身无关（SVG、工具函数、页面组件都出现过）
- 同一时刻 curl 打**同一个**域名同一个文件：串行 20 次全 200，**40 并发也全 200**
- 换 vite 直连 `http://localhost:3000/<同一路径>`：模块失败数 **0**，页面正常
- 用户屏幕上 kiro-dev 标签页开得多时更容易复现；关掉一批后成功率明显回升
- 报错面板上的「Clear cache and retry」点一次**有时**立刻恢复——注意这时
  `caches.keys()` 本来就是空的

## 根因（三段，缺一不可）

1. **dev 源上也注册了 Service Worker**。`website/index.html` 里那段注册脚本无条件执行
   `navigator.serviceWorker.register('/sw.js')`，没有 DEV 判断；CDP 里
   `navigator.serviceWorker.controller != null` 为真。
2. **一次页面加载是上千请求的并发波峰，前面的那一跳顶不住**。`website/public/sw.js`
   在 `fetchAssetWithRetry` 上方的注释里就写着：网关前面那一跳「宣称 250 条 HTTP/2
   流、实际 140 上下开始答 502」，实测 200 流 → 140 成功 + 60 个 502。dev 域名正是
   这条链路（nginx-proxy → vite），于是每一波里总有**少数几个**模块请求被丢。
3. **SW 只对 `/assets/`、`/vendor/` 做重试，`/src/` 没有**。`sw.js` 里那两条
   `fetchAssetWithRetry` 分支只管构建产物与 vendor 桩；dev 的 `/src/*.tsx` 模块不在
   其中，落到后面那个网络优先的壳处理器（`Shell navigation` 那段），而它的兜底是
   `caches.match(e.request).then(r => r || Response.error())`——缓存里只有壳、没有模块，
   于是**一次偶发丢包被翻译成 `Response.error()`**，浏览器报的就是那个没有状态码的
   `net::ERR_FAILED`，整个模块图在 `main.tsx` 那一环断掉，页面只能显示启动失败面板。

一句话：**偶发丢包是概率事件，SW 的兜底把它变成了必然的硬失败**，而报错文案把责任推给
网络——curl 全绿就是「网络没坏」的判据。点「Clear cache and retry」能好，是因为它
`unregister()` 掉了这层拦截，改由浏览器自己取模块。

与本次路由改名**无关**：对照组 `/chat`（没碰过）失败模式一模一样。

## 修法（当下）

- 页面上：点「Clear cache and retry」，或在 DevTools → Application → Service Workers
  点 Unregister 再刷新
- 自动化/取证探针走 vite 直连 `http://localhost:3000/<路径>`（先
  `KIROCREW_HOME=<仓库>/.kirocrew-dev kirocrew token --port 6777` 现签 token，
  访问 `/?token=…` 完成握手拿 cookie），那条路上模块加载零失败
- 每个探针脚本记得 `page.close()`：自己留一屏标签页会抬高失败率

## 怎么避免

- **dev 不该挂 SW**。生产壳要 SW 是原意，dev 上拦 `/src/*` 纯属自伤：可以让
  `index.html` 的注册按环境跳过，或让 dev 不提供 `public/sw.js`。这是待办，不在本次
  改动范围内。
- **判「网络坏了」先做两个对照**：同一 URL 用 curl 打一遍；再打开一个**没改过的页面**
  看是否同样失败。两者都正常 → 是浏览器侧（SW/缓存/扩展），不是链路。
- **SW 应当对**所有**模块请求一视同仁地重试**，或干脆对 `/src/` 也走 skip 规则交给
  浏览器（dev 专用）。只给构建产物加重试，恰好漏掉了 dev 里数量最多、最密集的那一类。
- **CDP 探针别等错信号**：外壳（导航、`dashboard-shell`）先于页面内容渲染，「看到任意
  testid 就算开机」会把「还没渲染完」误判成失败；要么等**目标 testid**，要么等正文里
  没有启动失败文案。