# 整份替换 studioApi 的测试套件 + 门禁假红的三个坑（ACP-2085 S2）

改 `ChatPane` 让它在挂 `ChatEmbed` 前先调 `studioApi.ensureReqSession(projectId)`，
前端全量跑一次红了 **62 个**用例。三个坑都不是「我的代码坏了」，但每一个都花了
二十分钟才排掉，记下来。

## 坑 1：`TypeError: api.ensureReqSession is not a function`（62 个红，一个原因）

- **现象**：`AiStudioPage.test.tsx` / `Views.test.tsx` / `PublishRun.test.tsx` /
  `PublishView.test.tsx` / `demo/StatesWorkspace.test.tsx` / `demo/states-release.test.tsx`
  里 62 个用例同时红，报错都一样；而我自己的 `ChatPane.test.tsx` 15 个用例单独跑全绿。
- **根因**：这些套件为了不起真网络，**整份**塞一个假 `api` 对象（`{listProjects: vi.fn(), …}`），
  `StudioApi` 是**结构类型**，TS 只在被测文件真的引用它时报缺字段；`ChatPane` 是新调用方，
  运行时才炸。`demo/runtime.ts` 里的 `createDemoApi` 同理——它也是整份假实现，
  `StudioApi` 加成员必须同时补它。
- **修法**：六个套件各补一行 `ensureReqSession: vi.fn(async (id) => ({ slotKey: 'ai-studio-req-' + id, created: false }))`，
  并在注释里写清「左栏在这些用例里是背景板，顺序契约归 `ChatPane.test` 管」。
- **怎么避免**：给 `StudioApi` 加成员的收尾动作固定三条——真实现、`createDemoApi`、
  全仓 `grep -rln "listProjects: vi.fn" website/src`（整份假 api 的套件清单），一次补完再跑全量。
  只看自己那个新测试文件绿了就报「前端过了」，报的一定是假绿。

## 坑 2：门禁命令在错的目录跑，红是环境造的

- **现象**：从**仓库根**跑 `npx vitest run` → `Test Files 23 failed`、
  `window is not defined`，vitest 版本显示 5.0.3；`npx tsc --noEmit -p .` 打印
  「this is not the tsc command you are looking for」；`./node_modules/.bin/tsc` 干脆不存在。
- **根因**：仓库根**没有** website 的 node_modules。`npx` 在那儿解析到另一个 vitest
  （5.0.3，没装 happy-dom → 没有 `window`），`tsc` 解析到同名占位包。
  而 `website/vitest.config.ts` 的 `environment: 'happy-dom'` 只有从 `website/` 跑才生效。
- **修法**：`cd website && pwd && npx vitest run …`（`cd` 与命令**必须同一条调用**，
  本机的 Bash 每次调用都把目录重置回项目根），类型检查用
  `node_modules/typescript/bin/tsc --noEmit -p .`。
- **怎么避免**：判据是「全量红」时先自证两件事——**在哪个目录跑的**、
  **用的是哪个二进制**（输出里 `pwd` 和 vitest 版本号）。我差点把 62 个红的锅
  背成「ChatPane 设计有问题」，实际那两次跑连 happy-dom 都没加载上。

## 坑 3：真跑时浏览器起不来，是我自己把机器用满了

- **现象**：探针发一条聊天消息，4 个全新 context 全部失败——前三次
  `Timeout 45000ms` 等不到 `[data-testid="ai-studio-chat"]`，第四次直接
  `browserContext.addCookies: Target page, context or browser has been closed`
  （Chrome 启动就没了）。同一个脚本 20 分钟前刚成功 dump 过整栏文字。
- **当时排除掉的**：网关（`/api/health` 200）、域名（curl 索引页 72ms、`/src/main.tsx` 32ms
  都 200）、网关日志（零 traceback）。所以不是服务端，也不是「dev 域名丢模块」那档事。
- **根因**：机器被我用满了。那时**同机并跑**着全量 vitest + `tsc` 全量类型检查；
  `free -m` 显示 **swap 16G 用满**、`/opt/google/chrome/chrome` 主进程 **102 个 / RSS 合计 38G**
  （历史 CDP 会话漏的）。无头 Chrome 在这种盘子和内存压力下起不来，
  而 playwright 报的是「browser has been closed」，一个字都没提内存。
- **修法**：脚本一个字没改。等门禁跑完、机器空下来再跑，`ATTOK attempt=1` 一次过。
  判据是**空闲状态下最小复现**（`launch → newContext → goto(data:) → textContent`，
  1 秒回 `ok`）。
- **怎么避免**：把「全量门禁」和「浏览器真跑」当**串行**动作排，别当并行。
  真跑起不来时先看 `free -m` 的 swap 和 `ps` 里 chrome 主进程个数——
  这比翻网关日志便宜，而且这次它才是真的。**别照我第一版的判断写「CPU 吃满」**：
  我当时也是猜的，最小复现跑通才知道是内存/swap。

## 坑 4：开场白发两遍，助手把同一个问题问了两遍

- **现象**：真跑第一次 dump 左栏，看到两段**几乎一字不差**的开场回答（都是
  「读完了手册…请告诉我这次做什么页面」），中间还夹着**重复的**首条提示语。
  没有任何报错，页面上看着像「助手抽风」。
- **根因**：`ensure_req_session` 用项目记录里的 `reqSessionStarted` 判「第一次」，
  但**读标记 → 发提示语 → 写标记**中间有一个真 `await`（`asyncio.to_thread`）。
  前端首屏的 mount effect 会跑两遍（`website/src/main.tsx` 整个 app 包在
  `<StrictMode>` 里，dev 下 effect 双跑；生产下首屏慢时的重试同理），
  两个 POST 都读到「没有标记」，于是各发一遍。标记是持久的，挡得住重启，
  **挡不住并发**——这在读代码时看不出来，只有真跑才看得见。
- **修法**：加一个进程内的 in-flight 集合（`reqsession._starting`），
  「查 + 占」之间不放任何 `await`，输的那个直接当 `created=False` 返回；
  标记落盘照旧（它是重启后的判据，两者职责不同）。用例
  `test_concurrent_opens_send_the_prompt_once` 用 `asyncio.gather` 把两条并发
  路径钉住。判据：重新打开后 transcript 里只有**一行** user 提示语。
- **怎么避免**：任何「只做一次」的持久标记，都要问一句
  **「两个请求同时进来会怎样」**。凡是判据要过 `await` 才写得上的，
  就得再加一个同事件循环内的原子闸；顺手把这类幂等性写成
  `gather(同一个调用, 同一个调用)` 的用例，一次就钉死。

## 坑 5：满屏 502 不是「网关坏了」，是它自己把命交了

- **现象**：真跑跑到一半，`/api/*` 全变 **502**（连 `/api/health` 都 502），
  浏览器里是 SPA 自己的「This page could not finish loading」，
  而同一时刻 `/src/main.tsx` 用 curl 拿还是 200。第一反应是「nginx / vite 坏了」。
- **根因**：网关进程**没了**。`ss -tln | grep 6790` 是空的，502 只是 nginx 默认
  vhost 找不到上游时替它撒的谎（仓里 `20261008-185041` 记过「别拿网址当清理证据」，
  反过来同理：**别拿 502 当「服务坏」的证据**）。它为什么没：日志最后几行是
  `event-loop heartbeat: lag 16.6s (loop was blocked)` →
  `event loop silent 21.6s — stall enrichment captured` →
  「captured by watchdog daemon thread **before dump-then-exit**」。
  即宿主机被 cron 的全量 vitest 压满（swap 16G 全满）→ 网关事件循环连续停摆 →
  **loop_watchdog 抓完 dump 自己退出**。
  我一开始赖 OOM killer，去 `/var/log/kern.log` 查到 5 条
  `Out of memory: Killed process`——全是前天的 chrome，23 点一条都没有，**差点写进笔记当结论**。
- **修法**：`setsid bash .kirocrew-dev/run-gw.sh` 重启（会话都在盘上，transcript 一行没丢），
  起完自证 `/proc/<pid>/attr/current` 仍是 `kirocrew-launcher`。
- **怎么避免**：`/api/*` 一律 502 时**第一步跑 `ss -tln`** 看上游在不在，再翻日志。
  日志出现 `dump-then-exit` 就是自杀：**先减负载再重启**，不然重启完还是同一条死法。
  甩锅给内核 OOM 之前，先看那条记录的**时间戳和进程名**对不对得上。



