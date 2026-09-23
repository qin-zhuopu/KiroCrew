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
- [20260923-193521-tsc-noop-and-persisted-pane-state.md](20260923-193521-tsc-noop-and-persisted-pane-state.md) —
  两个假绿：website 根 tsconfig 是 `files:[]` 引用壳，`tsc --noEmit` 空跑 exit 0
  （要用 `-p tsconfig.app.json`）；组件持久化面板显隐到 localStorage，同文件前序
  用例点隐藏后毒死后续用例（整棵子树不进 DOM，单跑却过）。
