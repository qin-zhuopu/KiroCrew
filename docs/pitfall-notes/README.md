# 填坑笔记（Pitfall Notes）

按 `{YYYYMMDD-HHMMSS}-{英文主题}.md` 命名，一篇记一次踩坑：现象 → 根因 → 修法 → 怎么避免。

这里是**工程复盘**，不是契约：改代码不需要"同一提交更新它"（那是
[system-specs/](../system-specs/README.md) 的规矩）；也不进发布包（用户文档在
[`../../src/kiro_crew/docs/`](../../src/kiro_crew/docs/README.md)）。

写这里的内容，标准只有一条：**当时的我查了多久才挖到的东西**。报错信息看不出根因的、
试错才排除掉的、文档里没写的，都值得记一行。

## 目录

- [20260922-154851-ai-studio-tiptap.md](20260922-154851-ai-studio-tiptap.md) —
  AI Studio 可视化文档编辑器：@tiptap/markdown 没有默认导出、ChatEmbed 的槽 404、
  模式切换时编辑器实例的生命周期。
- [20260922-170210-builtin-app-registration-and-csrf.md](20260922-170210-builtin-app-registration-and-csrf.md) —
  builtin 路由 404 但 REPL 全绿（没进 BUILTIN_NAMES）、反代域名 GET 通 POST 403
  （CSRF 只拦写方法，Origin 不在白名单）。
- [20260923-090621-kiro-dev-login-and-topology.md](20260923-090621-kiro-dev-login-and-topology.md) —
  登录 kiro-dev：容器名 ≠ 域名归宿（nginx-proxy 多域名）、dashboard 令牌用
  `kirocrew token` 现签不扒浏览器、vite 冷启动假加载错误。
- [20260923-103512-tmux-send-keys-enter.md](20260923-103512-tmux-send-keys-enter.md) —
  tmux send-keys 括号粘贴模式吞回车：文本与 Enter 必须拆两条发，发完 capture-pane 自证。
- [20260923-110012-tmux-claude-session-ops.md](20260923-110012-tmux-claude-session-ops.md) —
  tmux claude 会话运维：会话名先 tmux ls 查真名、换 settings=杀进程原目录重启、派活
  三件套（文本/单独回车/capture 自证）、resume 要 cd 对目录。
- [20260923-120325-ai-studio-demo-route-and-first-run-gate.md](20260923-120325-ai-studio-demo-route-and-first-run-gate.md) —
  AI Studio 真机取证：`?demo=` 只认 `/ai-studio` 前缀、fresh home 应用默认 disabled、
  首启引导模态链异步拦截点击（服务端权威，清 localStorage 没用）、token 5 分钟现签、
  HttpOnly 端口名 cookie、networkidle 永不满足、Raw textarea 是再序列化。
- [20260923-122306-t7-frontend-gate-baseline-drift.md](20260923-122306-t7-frontend-gate-baseline-drift.md) —
  证明红灯前端门禁（ai-studio vitest、i18n parity/deadKeys）是继承来的不是自己引入的：
  共享 stash 安全的基线对照法，以及 happy-dom 缺 EventSource。
- [20260923-135214-apparmor-userns-multi-instance-launcher.md](20260923-135214-apparmor-userns-multi-instance-launcher.md) —
  源码多实例沙箱 EPERM 两个坑：路径附着档案要求直接 exec 启动脚本（`python 脚本` 起法白装）、
  `install-profile` 只写一个文件会互相覆盖（多实例各起独立命名档案）；判据看 `/proc/pid/attr/current`。
- [20260923-144042-dev-origin-sw-turns-a-dropped-module-into-a-hard-failure.md](20260923-144042-dev-origin-sw-turns-a-dropped-module-into-a-hard-failure.md) —
  dev 域名上「代码没送到」：`index.html` 在 dev 也注册了 `sw.js`，而 `sw.js` 只给
  `/assets/`、`/vendor/` 重试、`/src/*` 落到 `caches.match(request) || Response.error()`
  ——前面那一跳的偶发丢包被翻成必然的 `net::ERR_FAILED`（curl 同路径 40 并发全 200 即判据）。
- [20260923-142652-seccomp-allows-but-mount-denied-in-userns.md](20260923-142652-seccomp-allows-but-mount-denied-in-userns.md) —
  dev 容器内沙箱 probe 死在 mount(EACCES)：seccomp 全放行也没用，宿主内核/AppArmor 禁
  非特权 userns 挂载；宿主上裸跑同一命令十秒定性，退到 ALLOW_UNSANDBOXED 兜底。
- [20260923-142652-pip-editable-egg-info-misleading-ro-mount.md](20260923-142652-pip-editable-egg-info-misleading-ro-mount.md) —
  "Cannot update time stamp of directory *.egg-info" 实为只读树上的 EROFS：pip -e 必写
  源码根，:ro 挂载的上游要用卷内快照 + KIROCREW_DEV_SRC，参数化要覆盖安装行不只检查。
- [20260923-180255-shared-query-key-different-shape.md](20260923-180255-shared-query-key-different-shape.md) —
  同一个 React Query key 被两个组件用不同形状的 queryFn 读：谁先挂载谁定缓存内容，
  后者自己的 queryFn 根本不跑、静默拿到 undefined（无报错、无 red），
  且只渲染那个小组件的测试永远是绿的。
- [20260923-185614-website-root-tsc-noop.md](20260923-185614-website-root-tsc-noop.md) —
  `website/` 里 `npx tsc --noEmit` 是空跑（根 tsconfig 是 `files: []` 的方案配置，
  非 build 模式不编 references）：一个真错都没检查却 exit 0，要写 `-p tsconfig.app.json`。
- [20260923-193437-tsc-root-config-is-a-noop.md](20260923-193437-tsc-root-config-is-a-noop.md) —
  `website/` 根目录裸跑 `npx tsc --noEmit` 是空跑（聚合配置 `files: []`，秒退 exit 0
  的假绿）：类型自检必须 `-p tsconfig.app.json`，"tsc 过了"要能报出带的是哪个 `-p`。
- [20260923-193521-tsc-noop-and-persisted-pane-state.md](20260923-193521-tsc-noop-and-persisted-pane-state.md) —
  两个假绿：website 根 tsconfig 是 `files:[]` 引用壳，`tsc --noEmit` 空跑 exit 0
  （要用 `-p tsconfig.app.json`）；组件持久化面板显隐到 localStorage，同文件前序
  用例点隐藏后毒死后续用例（整棵子树不进 DOM，单跑却过）。
- [20260927-131130-worktree-venv-points-at-main-checkout.md](20260927-131130-worktree-venv-points-at-main-checkout.md) —
  worktree 借主检出 venv 跑代码：editable 装的是主检出绝对路径，忘带 `PYTHONPATH=src`
  就 import 到主检出的旧代码（graph 路由 404 却像「代码没错」）；`print(mod.__file__)`
  自证来源，node_modules 同理要软链回主检出。
- [20260927-134900-baseline-red-count-is-the-only-honest-ruler.md](20260927-134900-baseline-red-count-is-the-only-honest-ruler.md) —
  「基线 11 红」是上次抽样跑的数不是测量值：判定红灯归属唯一诚实的尺子是同命令在
  基线 worktree 再跑一遍 diff 失败清单；本机 eslint 配置在基线就崩（@shadcn/lint 缺）。
- [20261008-103819-worktree-gateway-apparmor-and-one-shot-token.md](20261008-103819-worktree-gateway-apparmor-and-one-shot-token.md) —
  worktree 起网关两个假健康：dev-backend.sh 的 `python -m` 起法让 AppArmor 路径档案
  不命中（服务 200 但会话全起不来，要 exec 档案附着的真实路径 + `PYTHONPATH` 换源码树，
  判据是 `/proc/<pid>/attr/current`）；`kirocrew token` 的链接票恒 300 秒（`--ttl` 只搬
  `session_exp`），中途必失效，脚本要换 cookie 且换/用同一主机名。
- [20261008-155500-ai-studio-cjk-project-id-collides-in-same-second.md](20261008-155500-ai-studio-cjk-project-id-collides-in-same-second.md) —
  同一测试里连建两个中文名项目，第二个 `KeyError: 'project'`：纯中文名 slug 为空、
  项目 id 只剩秒级时间戳，同秒撞目录 → create 回 503（没有 `project` 键）。测试改
  用能 slug 的 ASCII 名，生产语义不动。
- [20261008-161000-headless-probe-on-dev-origin-self-inflicted-blank-page.md](20261008-161000-headless-probe-on-dev-origin-self-inflicted-blank-page.md) —
  无头探针在 dev 域名上「必定起不来」，四个自挖坑：在途请求没跑完就
  `unregister()` Service Worker（把偶发丢包做成 100% 失败）；cookie 改名到
  localhost 走 vite 直连，代理 `changeOrigin` 让 `/api` 全 403，SPA 只剩空壳；
  用 CDP 塞 cookie 头把 token 钉死在过期那份；全新 context 没 seed
  `mc-onboarded`，首启弹窗吃掉所有点击。dev 域名偶发丢模块是真的，但「必定失败」
  都是我自己造的——正解是失败就换全新 context 重试，不存在那个神奇启动参数。
- [20261008-164500-local-gate-red-list-is-mostly-not-yours.md](20261008-164500-local-gate-red-list-is-mostly-not-yours.md) —
  提交前门禁 6 红的分诊：`local-gate.py` 要用 `.venv/bin/python` 跑（系统 python3
  没 pytest）；worktree 的 venv 软链主仓、`pytest_split` 没装 → CI 专属插件用例
  本机必红；其余是存量文档目录债与并行 flake。用 `git worktree add --detach HEAD`
  造干净对照自证归属（记得 `PYTHONPATH=$PWD/src`）。前端半边同法：`src/test/` 里
  9 个红在 HEAD 前一个提交的对照 worktree 上逐条同名同数（软链 node_modules 让
  `server.fs.allow` 白名单失效 + 缺 `@shadcn/lint` + 存量断言债）。
- [20261008-170235-github-push-hangs-silent-need-proxy.md](20261008-170235-github-push-hangs-silent-need-proxy.md) —
  `git push` 到 GitHub 零输出挂死：直连不通而 git 在连接阶段不超时不报错，
  且挂住的 `git-remote-https` 不会自退，会被误读成「还在推」。推前
  `timeout 8 curl https://github.com` 探一下，不通就 `ALL_PROXY=socks5://localhost:7777`，
  成功只认输出里的 `旧hash..新hash`。
- [20261008-230527-wholesale-stub-suites-and-the-gate-that-false-reds.md](20261008-230527-wholesale-stub-suites-and-the-gate-that-false-reds.md) —
  `StudioApi` 加一个成员红 62 个用例：六个套件整份塞假 api（结构类型只在运行时炸），
  补成员要同法补 `createDemoApi`；从仓库根跑 `npx vitest`/`npx tsc` 解析到错版本错包
  （假红，必须 `cd website`）；真跑时 Chrome 起不来（报「browser has been closed」）
  是 swap 用满 + 102 个漏掉的 chrome 主进程，跟网关无关——门禁与浏览器真跑要串行；
  开场白发两遍是「持久标记 + 中间有 await」挡不住并发（StrictMode 双跑），补进程内原子闸。
- [20261009-022126-dev-trust-grant-needs-chat-utils-and-slot-key.md](20261009-022126-dev-trust-grant-needs-chat-utils-and-slot-key.md) —
  后端自己仿〔信任会话〕开关：判定不在设值处（在 `chat_runner._slot_is_trusted`，还认
  `_trust_scope` 那条带 TTL 的 Scoped 授权），策略 key 要用 `effective_session_key` 且它要
  从 `chat_utils` 导（`chat_handlers` 那份 import 一次 13.5 秒），旗按 slot 存而策略按
  session 存（共用 session 的槽要一起打），策略只在当前 asyncio 任务可见，`sel()` 没有 `noop()`。
- [20261009-030704-website-pretest-jscpd-shadows-vitest.md](20261009-030704-website-pretest-jscpd-shadows-vitest.md) —
  `npm run test` 的 `pretest` 是全仓 jscpd 且阈值 0%，而 main 自己就报 1197 个 clone：
  pretest 一红 vitest 一条都没跑，报的还全是别人的文件。本地判据改用 `npx vitest run <自己的 spec>`；
  顺带 tsc 全量构建会被存量未使用 import 挡住，契约门禁的行号会被你的改动推后 —— 判归属一律去干净基线复现。
- [20261008-235002-browser-sends-two-opens-and-no-frontend-test-could-see-it.md](20261008-235002-browser-sends-two-opens-and-no-frontend-test-could-see-it.md) —
  同一个页面发两次「开需求会话」，两个请求都 200、两个会话都活着，前端 238 条用例全绿、
  后端 13 条全绿：幂等标记落在项目记录里，而写它之前隔着一整个 agent turn 的 await；
  只有 `git grep` 服务端那份 transcript 才发现开场白被发了两遍（前端测试的架构性盲区）
- [20261009-001429-keepalive-ring-the-same-prompt-forever.md](20261009-001429-keepalive-ring-the-same-prompt-forever.md) —
  单早交付了，同一条派工提示却重复到达十三次：crontab 里每分钟的 `jc agent keepalive tick`
  只看会话忙不忙、不看做没做完，而「自己说做完了」不会自动摘牌，目标文本里那句
  「不要停下来等我确认」把死结焊死。同一句话第二次原样到达就先查谁在发，
  完工收尾要把 `keepalive remove` 当成和 Jira 流转同级必做项
- [20261008-185041-devserver-stop-409-leaks-live-ports.md](20261008-185041-devserver-stop-409-leaks-live-ports.md) —
  开发服务器启动失败后点〔停止〕回 409「没在运行」，而进程 / 端口 / 网关 conf 三样都还在：
  `stop()` 拿状态字符串当「有没有活要清」，而 `stopped` 只说明「网址没通」（vite 5.4 拦陌生
  Host 回 403 恰好就是这个现场）。判据改成查三件资源；顺带 vite 5.4 没有
  `__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS`、`.ai-studio/` 下放 vite 配置找不到 vite、
  以及「停止后网址还 200」是网关默认 vhost 兜底（别拿网址当清理证据）。
- [20261009-064853-judgement-that-never-ran-empty-log-and-arity.md](20261009-064853-judgement-that-never-ran-empty-log-and-arity.md) —
  四条「看着像结论其实没发生过」：仓库根跑 vitest 时路径过滤匹配不到文件（139 条红全是别人的，
  我改的那个压根没跑）；后台任务被会话退出打断 → 日志只剩 592 字节，「grep 没命中」被当成全绿；
  `toHaveBeenCalledWith('p1')` 对 `('p1', undefined)` 是失败的（比较完整实参列表）；
  断「某状态下按钮不存在」却等的是首帧（状态块首帧就渲染成 idle，正是提供按钮那一支）
- [20261009-064900-injected-reactnode-receives-context-not-events.md](20261009-064900-injected-reactnode-receives-context-not-events.md) —
  〔开始开发〕的 `window` 事件「没人接」：接的 `DevDagPanel` 是注入节点，只在开发页签渲染，
  事件到达时它压根没挂载，`useEffect` 里的 `addEventListener` 从未执行；prop 又被创建方定死、
  克隆元素是把结构问题伪装成一行代码。正解是「切页签归页签的主人 + Context 按树中位置读取」，
  再用 `seq` + `served()` 挡住板子每次重渲染重放同一个请求（模块级队列那版已删）
- [20261008-211710-vitest-from-repo-root-runs-without-a-dom.md](20261008-211710-vitest-from-repo-root-runs-without-a-dom.md) —
  前端测试 17 条全红、报错只提 testing-library（`document is not defined` +
  `Symbol(Node prepared with document state workarounds)`）：根因是**从仓库根跑的**——
  工作目录每次调用都重置，根目录没有 `vite.config.ts` 就没有 jsdom。同法假绿的还有
  根目录 `tsc -p .`（solution tsconfig 一个文件都不查）。修法：`cd <绝对路径> && pwd && <命令>`
- [20261008-213039-gate-failure-attribution-read-the-name-list.md](20261008-213039-gate-failure-attribution-read-the-name-list.md) —
  `local-gate` 后端段 5 条红被我误当成自己的债：它说的「related」是改动面的传递闭包
  （实测跑到近三万用例），红不代表红在相关处。`apps.md` 缺 `ai-studio` 目录行与数量
  是 `bcc6240a7` 的账；判归属只认「失败测试涉及的文件在不在本单 diff 里」+ 断言报的是
  整块缺失还是局部写错。另记：后端段一红 `local-gate` 就整体退出，前端两段根本不跑
  一条写完。附 `[pseudolocale]` 要求 `en-XA.json` 随 `en.json` 一起重新生成提交。
- [20261009-032851-ai-studio-live-run-silent-blockers.md](20261009-032851-ai-studio-live-run-silent-blockers.md) —
  真跑需求页直改连撞五个「报错不指向根因」的坑：① 浏览器写请求全 403 而 curl 200——CSRF 只校
  `Origin`，vite 的 6791 不在 `build_allowed_origins` 里，而 `KIROCREW_HOME` 设了就白名单
  `localhost:3000`（真跑要用 3000，且复现浏览器必须显式带 Origin）；② 工具批准 600 秒**自动替你拒绝**，
  `approval_mode=auto` 不覆盖工作区外的 Edit，随后 loop-watchdog dump-then-exit 把网关整进程带走，
  外面只见「页面没反应」；③ 直改成功**故意不改渲染文档**，所以「拿刚才的 docHash 重试」测不出陈旧
  （会改 hash 的是图谱不是文档），那个假 409 还往演示账本里写了脏行；④ 渲染视图里带
  `生成时间：<ISO>`，直接拿它对 `docHash` 等于对「现在几点」取指纹（重启就变、刚打字就误报未保存），
  要过 `stable_doc` 抹戳；⑤ 两本需求账本（`direct-edits` / `start-requests`）写在**工作区**的
  `.ai-studio/` 下（本次即模板仓 worktree），不在 `KIROCREW_HOME` 里，全盘 find 才找得到。
  附：需求会话会拒不像需求的改动
  （行为正确）、`每页 20 条` 全文 4 处要按 `- R-15 规则：` 定位、窄视口下三栏布局遮挡点击。
- [20261009-065213-nonatomic-state-write-flashes-stopped.md](20261009-065213-nonatomic-state-write-flashes-stopped.md) —
  正式服务器状态文件原地 `write_text` 不是原子的：部署线程一边写、`deploy()` 自己一边读，
  读到半份 JSON 被容错成 `{}`，于是「部署中」判成「已停止」。三个证据互相矛盾（文件写着
  deploying、`_busy_gen` 也设上了、返回的却是 stopped），且 **`-n 0` 串行全绿、并发才红**——
  先找第二个线程，别先怀疑测试隔离。修法：写临时文件 + `os.replace`；注意别复用
  `merge_json_file`（它自己就把真路径原地写了一遍，rename 等于白做）。
- [20261009-070012-demo-zero-fetch-breaks-on-a-separate-api-export.md](20261009-070012-demo-zero-fetch-breaks-on-a-separate-api-export.md) —
  顶栏加 `ProdServerControl` 之后 `demo/states-release.test.tsx` 红 4 条，只报
  「fetch 被调了 1 次」：该文件把 `studioApi`/`publishApi` 换成替身来证明 demo 零请求，而
  `prodServerApi` 是同一模块里**另一个 export**，spread 没覆盖到，于是发了真请求。
  `!demoStates` 挡不住它（那些用例走的就是非 demo 的真壳子）。新加独立 api export 先
  grep `spyOn(globalThis, 'fetch')` 去登记替身；定位来源直接看 spy 打出的 URL。
- [20261009-225512-boot-side-effect-in-a-shared-register-routes.md](20261009-225512-boot-side-effect-in-a-shared-register-routes.md) —
  往 `register_routes` 加开机恢复，`test_route_retry` 就从 409 变 202：`register_routes`
  是 20 个 ai-studio 测试文件共用的壳子，恢复线程和它们抢同一批记录，而那条老测试默认
  「没人认领的 creating 永远不会被改判」。给测试一个 `_make_app(recover=False)` 的口子，
  恢复单独验；验「扫过但不碰普通项目」要放一条该改判的记录当栅栏，否则是线程没跑到的假绿。
  附同一症状的第二个根因：`view?.state ?? 'stopped'` 把「还不知道」写成「已停止」，
  需要 `querying` 单独一态（测试得让接口挂着不返回才测得到那一帧）。
- [20261009-234224-parallel-worktrees-four-silent-nos.md](20261009-234224-parallel-worktrees-four-silent-nos.md) —
  并行 worktree 四个「什么都不报」的坑：① **拿 git 的英文原文当判据**（本机
  `LANG=zh_CN.utf8`，`fatal: 一个名为 'dev/x' 的分支已经存在` 让 `if "already exists" in out`
  永不成立，续跑在中文部署机 100% 失败而英文 CI 全绿）→ 只认退出码和 `--porcelain`/
  `--diff-filter=U`；② `status --porcelain` 默认折叠目录 + 转义非 ASCII，两个参数都得加；
  ③ 新增同方向接缝时默认值悄悄回落真实现（注入假 HEAD 的测试去跑了真 git）；④ 并行派发
  要三趟线程池往返，`asyncio.sleep(0)` 不推进时钟所以等不出来 → 有界真实时间轮询。
  附一条反面：我先给①编了个「忙等饿死 selector」的根因，探针实测把它否了 —— 根因没做
  最小复现就别写进笔记。
- [20261009-235147-dnt-case-insensitive-and-replicated-gates.md](20261009-235147-dnt-case-insensitive-and-replicated-gates.md) —
  预判 `git tag` 会被 `untranslated-script` 判红，实跑不红：`glossary.json` 里有 `Git`，而
  `doNotTranslate` 剥离正则是**忽略大小写**的，小写 `git` 早被剥掉了——我按 `t === 'git'` 比才漏。
  推论：单子里点名要防的 `App URL` 之所以命中，是因为 `App` 恰好也在表里，换个没登记的词就漏。
  主坑是「自己复刻一份判据」：中英西意 440 条里 139 条带拉丁词，用复刻规则算出 12 条必红，
  直接 import 仓里的 `CHECKS` 判是 **0** 条（引号嵌套、括号内英文、代码跨度都不算违规）。
  教训：门禁在本地跑不了的语种，检查脚本必须 import 真模块 + 配反向对照（故意写坏一条必须变红）。
- [20261009-235859-dead-proxy-tunnel-still-listens-push-hangs.md](20261009-235859-dead-proxy-tunnel-still-listens-push-hangs.md) —
  `git push` 推 fork 静默挂死几分钟：`ss` 显示 7777 在听、DNS 能解析、隧道主机 ping 得通，
  但那条 `ssh -D` 的**上游已经断了** —— 本地监听端口与上游健康是两件事，客户端连上后等一个
  永远建不起来的远端拨号，于是「连上了但一个字都不回」（`curl --max-time 8` 也会挂过 8 秒，
  因为 TCP 已连上）。判代理只认一条硬指标：拿它打真请求看状态码。修法是另开一条一次性隧道
  + `git -c http.proxy=`，不动用户那条；`-D` 转发不是立刻可用，要轮询端口。
- [20261009-235900-i18n-check-prints-no-catalogparity-row.md](20261009-235900-i18n-check-prints-no-catalogparity-row.md) —
  任务书让记 `i18n:check` 里 catalogParity 每语种缺几个键，可 826 行输出里这词命中 0 次：
  它是 `src/i18n/catalogParity.test.ts`（前端测试），门禁脚本链里根本没有，最容易被误当成
  `[key-refs]` 顶替（方向相反，语种缺键它永远绿）→ 复刻判据只度量。同单另一坑：退路写
  「没翻译脚本就按英文原文填」，实测会被零容忍的 `changed-passthrough` 新增 **1041** 条
  （非拉丁文种各 146 条：去噪后 ≥4 字母 ≥2 词且本族文字为 0 即判红，`"App URL"` 照抄就中）。
  另有两条不报错的约束：语种目录键序须保持 en 的子序列（`i18n-translate.mjs merge` 会把
  233 键的补丁炸成 7800 行重排），以及 `*Style.test.ts` 那 1474 行风格断言 `i18n:check`
  完全不看（`qa.test.ts` 的 `edge-whitespace` 15/15、`doubled-space` 10/10 已顶格）。
- [20261010-001858-worktree-venv-pth-imports-the-main-checkout.md](20261010-001858-worktree-venv-pth-imports-the-main-checkout.md) —
  worktree 里的 `.venv` 是指向主仓的符号链接，其可编辑安装的 `.pth` 写死
  `<主仓>/src`：`python -c "import kiro_crew…"` 加载的是**主仓**那份（新模块根本不在），
  而 pytest 因为 conftest 先插本地 `src` 所以是对的 → 「主仓没有这个模块」不等于「你改坏了」，
  判 import 归属一律走 pytest 或压住 `.pth`。附带一条：带 `{{n}}` 的文案若走
  `NOTICE_KEY` → `i18nT(key)`（不带参数），占位符会原样印在界面上
- [20261010-002120-i18n-parity-debt-masquerades-as-your-diff.md](20261010-002120-i18n-parity-debt-masquerades-as-your-diff.md) —
  `catalogParity.test.ts` 12 语种全红，看着像新加的 4 条文案改坏了目录，其实 HEAD 上就红
  （ACP-2113 欠的 233 键）。但数过才知道自己有没有让它更糟：按**同一份 en 键集**度量是
  233 → 237（10 个语种各多缺 4），直接对各自的新 en 比会把这 4 个从「改前」扣掉，
  得出「一条没加」的假结论。对照用新建的干净 worktree 不要 `git stash`；
  `en-XA.json` 是 `gen-pseudolocale.mjs` 的生成物（要在 `website/` 下跑），别手写
- [20261010-003700-inherited-green-copy-merge-red-and-the-wrong-fix.md](20261010-003700-inherited-green-copy-merge-red-and-the-wrong-fix.md) —
  审计报告说 `destructiveConfirm` 在 main 上本来就红、本分支「丢了 9 个豁免」、合并会复活成红，
  修法是搬回那 22 行。三点全错，同一个根因：把「本分支 en 目录没这些键」当成「测试丢了豁免」。
  本分支**一次没碰过**该测试文件（`git diff <merge-base> HEAD --` 为空 → 合并直接取 main 那份，丢不了），
  而照那修法会把 main 的 9 个键名搬进一个「没有这 9 个键」的目录，撞上同文件的
  `exists in English` → 造 9 个新红。教训：**「合并会不会红」别推理，用一次性 worktree
  `merge --no-commit` + 软链 node_modules 真跑整目录**（main 0 红 / 本分支 6 文件 16 红 /
  合并树 8 文件 18 红）。我第一遍只跑「相关的那几个文件」、还把分支目录拷进合并结果，
  于是报了个假数：既多出 5 条假红又藏掉 1 条真红。唯一「只在合并里红」的是
  `localeFormatting` —— main 把 `BASELINE` 从 25 收到 16，本地绿不代表合并绿
- [20261010-010304-audit-a-merge-in-place-black-outside-the-repo-lies.md](20261010-010304-audit-a-merge-in-place-black-outside-the-repo-lies.md) —
  自查合并结果时把 `git show HEAD:…` 拷到 `/tmp` 跑 black，报「134 行要重排」，据此差点
  回去重做冲突解决。假的：**black 的配置是从文件所在位置往上找 `pyproject.toml`**，拷出
  仓库就读不到 `line-length = 100`，退回默认 88，于是每个超 88 列的签名都算违规（同一个
  文件放回仓里再跑 = 0 行）。自查合并一律原地做：`git checkout -m -- <路径>` 重新造出冲突
  现场，再和已提交版本 diff，才是「我对合并做的全部改动」。同一轮顺手证明两边用例没丢
  （三方 test 名字集合：45 + 44 − 33 共有 = 56，无重名）——**「pytest 全绿」证明不了这个**。
  另一半：`_loop` 的冲突不是二选一，「修完自动再验收」原来挂在「每个节点跑完」后面，并行
  时那个位置等于测半份代码（不报错，只是结论对它没跑过的代码负责），要搬到整轮收口之前
