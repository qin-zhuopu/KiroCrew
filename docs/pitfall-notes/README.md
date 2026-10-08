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
- [20261008-185041-devserver-stop-409-leaks-live-ports.md](20261008-185041-devserver-stop-409-leaks-live-ports.md) —
  开发服务器启动失败后点〔停止〕回 409「没在运行」，而进程 / 端口 / 网关 conf 三样都还在：
  `stop()` 拿状态字符串当「有没有活要清」，而 `stopped` 只说明「网址没通」（vite 5.4 拦陌生
  Host 回 403 恰好就是这个现场）。判据改成查三件资源；顺带 vite 5.4 没有
  `__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS`、`.ai-studio/` 下放 vite 配置找不到 vite、
  以及「停止后网址还 200」是网关默认 vhost 兜底（别拿网址当清理证据）。
- [20261009-022126-dev-trust-grant-needs-chat-utils-and-slot-key.md](20261009-022126-dev-trust-grant-needs-chat-utils-and-slot-key.md) —
  后端自己仿〔信任会话〕开关：判定不在设值处（在 `chat_runner._slot_is_trusted`，还认
  `_trust_scope` 那条带 TTL 的 Scoped 授权），策略 key 要用 `effective_session_key` 且它要
  从 `chat_utils` 导（`chat_handlers` 那份 import 一次 13.5 秒），旗按 slot 存而策略按
  session 存（共用 session 的槽要一起打），策略只在当前 asyncio 任务可见，`sel()` 没有 `noop()`。
- [20261009-030704-website-pretest-jscpd-shadows-vitest.md](20261009-030704-website-pretest-jscpd-shadows-vitest.md) —
  `npm run test` 的 `pretest` 是全仓 jscpd 且阈值 0%，而 main 自己就报 1197 个 clone：
  pretest 一红 vitest 一条都没跑，报的还全是别人的文件。本地判据改用 `npx vitest run <自己的 spec>`；
  顺带 tsc 全量构建会被存量未使用 import 挡住，契约门禁的行号会被你的改动推后 —— 判归属一律去干净基线复现。
