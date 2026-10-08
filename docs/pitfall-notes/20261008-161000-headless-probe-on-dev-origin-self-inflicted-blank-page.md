# 无头探针在 dev 域名上「页面永远起不来」：四个坑都是我自己挖的

> 一句话结论：**dev 域名偶发丢一个模块是真的**（20260923 那篇记的就是它），但
> 「必定起不来」全是我自己造的。我一度把「这份脚本能跑、那份必挂」当成参数差异
> 的规律，最后同一份简单脚本也开始挂——**那个对比是运气，不是规律**。真正要的
> 是「失败就换全新 context 重来」，不是找到那个神奇参数。

## 现象

ACP-2015 第 2 步要在工作台上截一张证据图。用 playwright-core + 系统 chrome
（`/opt/google/chrome/chrome`，`headless: true`）打开
`https://kc-v1-14409-dev.gb10.jereh-pe.cn/workspaces/<id>/ai-studio`，等
`[data-testid="req-list"]`：

- 连跑 8 次以上全部超时，一条 `console error` 都没有——页面就是不动
- 同一个 URL、同一份 cookie，**同一个脚本的另一版本**（只做一次普通 `goto`，
  什么都不额外做）**那一次起来了**，DOM 里 `req-row-设备清单`、两个「全齐」徽标
  齐全 → 我据此以为找到了「能跑的写法」，见坑 3：**那是运气**
- 改走 vite 直连 `http://localhost:6791`（仓里 20260923 那篇填坑笔记推荐的
  「绕开 SW」正道）：10 秒后 `dashboard-shell` 出来了，但 `/workspaces` 那一栏
  **始终是空的**，`console` 里两条 `/api` 403 + `/api/ws` 403

## 根因（四个独立坑，都跟业务代码无关）

### 坑 1：`unregister()` 掉 Service Worker 的时机不对，等于亲手砍断模块图

`20260923-144042-dev-origin-...` 那篇笔记的修法是「点 Clear cache and retry」，
它做的是 `unregister()` + 清 cache + **重新加载**。我照抄时把 `unregister()` 放在
了 `goto()` **之后立刻**执行——此时页面正排队拉上千个 `/src/*.tsx`：

- SW 正在为这些请求做兜底，中途注销会让**在途请求**一起作废
- 于是每次都是「必定失败」，而不是原本那个偶发丢包。**失败率从偶发变成 100%**，
  看起来却像「dev 域名坏了」

判据：把 `unregister()` 挪到两次尝试**之间**（上一轮已经失败、没有在途请求），
一次普通 `goto` 就能起来。也就是说 **dev 域名上普通加载本来就是够用的**，
注销 SW 只是失败后的兜底，绝不能放进正常路径。

### 坑 2：把登录 cookie 改名到 localhost，`/api` 全 403，SPA 只剩空壳

vite 直连那条路上，我把 `mc_token_6790` 的 `domain` 从 dev 域名改成 `localhost`
（不然浏览器不发这个 cookie）。结果：

- 用 `curl -b "mc_token_6790=…"` 直接打 `http://localhost:6791/api/...`：**200**，
  数据正常——所以「cookie 有效」这条证据是真的
- 但浏览器里同一次会话的 `/api` 请求 **403**：vite 的 `/api` 代理开了
  `changeOrigin: true`，`Origin`/`Host` 与网关给这个 token 绑的来源不再一致，
  网关按 CSRF 规则拒掉；ws 同理 403
- 前端外壳（导航、shell）不依赖这些接口，所以页面**看起来起来了**，
  `/workspaces` 里却什么都没有——最骗人的一种半死状态

判据：`console` 里那两条 403 才是主线，`body` 空白只是后果。结论是
**探针对象就是 dev 域名本身**（用户看的那个源），不要为了躲坑换源，换了就把
CSRF 语义换掉了。

顺带一句：探针**不要**用 CDP 的 `Network.setExtraHTTPHeaders` 塞 cookie。它比
cookie jar 更「硬」——会盖过 jar 里刚刷新的 token，页面里 `/api` 全 401，
React 查询挂住，DOM 一直空（`ids: []`），看起来像前端坏了。用
`context.addCookies`，域名按当前 base 重绑。

顺带一个免费的同款假象：把 URL 写成 `/apps/ai-studio/<id>`（那是**后端 API 前缀**，
SPA 路由是 `/workspaces/<id>/ai-studio`，见 `website/src/App.tsx`），页面同样落在
「could not finish loading」错误边界上。URL 拼错和构建坏了，长得一模一样。

### 坑 3：`req-list` 出来了就动手——两分钟一次的「同一页面第二遍必挂」

`diag_requirements_page.mjs` 那份（`headless: true` + `ignoreHTTPSErrors: true` +
`goto` 后固定 `waitForTimeout(6000)` 再一次性 dump）**每次都过**。我把它改成
「`waitForSelector` + 点击 + 再 dump」，同一份 cookie、同一个 URL，就变成
**前 1~2 次必定停在「This page could not finish loading」**，第 3 次自己好，
再跑又是这个形状。`requestfailed` 里是十来条 `net::ERR_FAILED` 的 `/src/*.ts(x)`，
**每次还不是同一批**，页面报的是 SPA 自己的错误边界，不是 vite 报错。

排除业务代码的证据链（三条都指向「探针自己踩的」）：

- 同一时刻 `curl -k https://<dev域名>/src/main.tsx` → **200，43 KB**，走 nginx-proxy
  和直连 vite 都一样
- vite 的依赖预构建目录**没在重写**：`website/node_modules/.vite/deps/_metadata.json`
  的 mtime 还是早上 10:24，`browserHash` 一个没变（预构建被改过才会让在途的
  `?v=<hash>` 请求集体作废，这条排除了）
- 本机 `website/node_modules` 是**跨 worktree 软链**到 `KiroCrew/website/node_modules`，
  同时刻另有 20+ 个别的仓的 vite/vitest 在跑（`/tmp/fe-accept-*`、
  `jereh-fe-frame*` 等）。同机这么多 node 并发，dev origin 上「丢一个模块」
  就是 20260923 那篇笔记记的那个偶发行为——**跟探针写什么无关**

所以真正的规律是：**偶发丢包 + 我在同一页面里连续操作**，第一遍失败之后模块图
已经断了，同一 context 里再 `goto` 也救不回来（这就是为什么「第 3 次自己好」——
那次的运气好而已）。修法不是调参数，是**失败就换全新 context 重来**，最多 4 次。

### 坑 4：首启弹窗把点击全吃了，`req-list` 在数据之前 attach

同一次脚本里两个「假失败」，都跟业务代码无关：

1. **点击超时**：重试日志里明写 `<div role="dialog" aria-label="导入代理配置"
   class="fixed inset-0 z-[120] …"> intercepts pointer events`。全新 context =
   全新 localStorage，首次运行的导入/隐私弹窗盖在最上层。**E2E 套件的正规解法**
   就是 seed `localStorage['mc-onboarded']='1'`（`website` 的
   `playwright/auth.setup.ts` 同源，`App.tsx` 那里有注释说明这个门是给 E2E 留的），
   `context.addInitScript` 一行解决
2. **清单是空的**：`req-list` 这个容器**在请求发出前就 attach**（`isLoading`
   时也渲染），`waitForSelector('req-list')` 之后立刻 dump 得到空列表，看起来像
   「后端没数据」，其实一行之后就到了。判据要等 **行**（`[data-testid^="req-row-"]`），
   不是等容器

## 修法（可复用的探针骨架）

`.kirocrew-dev/scripts/shot_requirements.mjs`（本仓 gitignore 目录里）：

1. **只在 dev 域名上跑**，cookie 用它原本绑定的域名、用 `context.addCookies`
   注入（`secure` 按协议给），不要用 CDP 塞 header
2. **`headless: true` + `ignoreHTTPSErrors: true`**，playwright-core 用
   `KiroCrew/website/node_modules` 那份（CJS：`import pw from ...` 再解构，
   具名 import 在模块实例化阶段就抛）——照抄现成的，别自创变体
3. **`addInitScript` seed `mc-onboarded`**，否则首启弹窗吃掉全部点击
4. **循环最多 4 次：每次失败就换全新 context + 新 page 重 `goto`**；在同一页面
   里刷新或注销 SW 都救不回已断的模块图
5. **判据等「行」不等「容器」**：容器在 loading 期就在 DOM 里
6. 注销 SW + 清 cache 只作为**两次尝试之间**的兜底，正常路径不放
7. CDP 一律带总闸：脚本级 `setTimeout(..., 180000) → process.exit(99)`，
   每个调用带 `timeout`（本机硬性纪律，CDP 卡住没有报错就是整条会话静默停摆）
8. 别去 `page.screenshot()`：本机禁止把图片喂给模型，`data-testid` + 文案的
   DOM dump 是更强的证据（能断言字数、表格数、按钮 disabled）

## 怎么避免

- **偶发失败面前，「一次 A 过 / 一次 B 挂」不构成规律**：我为此写下过「headed
  变体必挂」的结论，写完 20 分钟就被同一份简单脚本的第二次失败推翻。偶发现象
  要么重复 5 次以上再下结论，要么直接写容错（重试），别把运气当参数差异
- **抄别人填坑笔记里的修法，要连「时机」一起抄**：「注销 SW 再刷新」里那句
  「再刷新」是关键——注销之后必须重新加载，在半路注销只会自己制造失败
- **同一份代码换个源行为不同，先怀疑身份/CSRF，不要怀疑页面**：换 origin 就是
  换安全语义；`curl` 手上有 200 只证明凭据有效，不证明浏览器那一路的
  `Origin`/`Host` 组合被接受
- **半死的 SPA（外壳在、内容空）先看 console 的 4xx**，不要盯着 DOM 猜渲染问题
- 探针成功的判据永远是 **DOM 断言**（`data-testid`、文本），截图只是留证——
  本机禁止把图片喂给模型看图
