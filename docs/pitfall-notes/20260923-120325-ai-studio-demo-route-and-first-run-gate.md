# ACP-754 真机取证：demo 路线、首启门禁、隔离栈的四组静默坑

日期：2026-09-23。场景：给 AI Studio 细节验收文档 01 写 playwright-core-over-CDP
真机探针，对 `?demo=` 演示路线 + 普通路线执行全部断言。探针第一次跑就红了，
挖了四个互相独立的坑，每个的报错都指不到真因。

## 1. `?demo=` 在 `/apps/ai-studio` 和根路径下静默渲染别的页面

- **现象**：`/apps/ai-studio?demo=main-membership-points` 渲染出项目列表（demo 参数
  被吃），`/?demo=…` 渲染聊天页。都不报错，就是"没进演示"。
- **根因**：内置应用路由注册为 `/:builtinApp/*`（App.tsx），只命中 `/ai-studio` 与
  `/ai-studio/…`；`/apps/ai-studio` 命中的是通用 `/apps/:name`（AppPage）；根路径落到
  `ChatRedirect`。`?demo=` 只在 AiStudioPage 内部解析，路由没进它参数就丢了。
- **修法**：文档与探针全部钉到 `/ai-studio?demo=<场景id>`。
  （2026-09-23 更新：页面路由已改名，**现在钉 `/workspaces?demo=<场景id>`**；旧
  `/ai-studio` 仍可用，由 App.tsx 的静态路由重定向到 `/workspaces` 且 query 保留，
  工作台旧拼写 `/projects/<id>/ai-studio` 由 ProjectsPage 的垫片重定向。）
- **避免**：验收文档里路由契约要**实测钉死**写进正文，别从"惯例 URL"推。

## 2. fresh KIROCREW_HOME 上 ai-studio 默认 disabled，403 文案不说"怎么开"

- **现象**：`GET /api/apps/ai-studio/projects` → 403 `{"error": "ai-studio is disabled"}`。
- **根因**：builtin app 安装即 enabled=False 的元数据（manager.py），要显式启用。
- **修法**：`kiro_crew app enable ai-studio`（注意子命令是 **app** 不是 apps；enable
  走运行中的网关生效，无需重启）。已固化进 `scripts-tmp/up-stack.sh`。
- **避免**：隔离环境脚本把"开应用"写成启动步骤，别留给下一次现挖。

## 3. 首启引导模态链异步弹出，拦截一切点击（最阴的一个）

- **现象**：demo 页面 DOM 都渲染了，但 `page.click` 全部超时，重试日志显示被
  `role="dialog" aria-label="导入代理配置"` / `"隐私"` 拦截。更阴的是：**页面刚
  goto 完立刻 dismiss 是漏的**——弹窗在 theme-boot 请求返回之后才异步出现，
  而且第一个（导入）关掉后还会链式弹出第二个（隐私，强制不可跳）。
- **根因**：fresh home 视为首次启动，App.tsx 挂 onboarding 章节链
  （AgentImportFlow → PrivacyChapter）；标志位是**服务端权威**（useTheme 拉
  theme-boot 后覆盖 localStorage），所以纯清 localStorage 也会被服务端拉回。
- **修法**：token 握手后对同一次会话补一发
  `PUT /api/config/theme {"onboarded":true,"import_onboarded":true,"privacy_acked":true}`
  （写的是临时 home，不碰真人数据），此后全程无弹窗。
- **避免**：自动化脚本对 dashboard 的第一件事是"落定首启"，写成探针的 D0b 断言，
  弹窗出现与否记录在证据行里。

## 4. 其余三个小坑（各卡了十分钟级）

- **token 5 分钟就死**：`kiro_crew token` 的 URL token `exp` 实测只有 300s（`--ttl`
  可控）。存下来的 token-url.txt 下一条命令就 403。证据命令必须**现签**，探针里
  用 `spawnSync` 现调再改写端口。
- **鉴权 cookie 是 HttpOnly 且按网关端口命名**（`mc_token_6788`）：
  `document.cookie` 永远看不见它，断言要读 `context.cookies()`。
- **vite `/?token=` 握手后禁止 `waitUntil:'networkidle'`**：dashboard 有长连接，
  networkidle 永不满足直接超时；用 `domcontentloaded`。

## 5. 附带发现：Raw 视图 textarea 不是源文逐字

DocEditor 的 Markdown(Raw) textarea 是富文本模型的**再序列化**：任务清单项
`- [ ] x` 会被写回 `- x`（实测唯一 delta）。对快照做 buffer"逐字符一致"断言前，
先分清比对对象是源文还是序列化产物；谓词要显式声明这个归一（见 01 文档 D4）。

## 6. 背景栈被系统按内存压力点杀

后台任务起的网关+vite 组合两次被 "running low on memory" 直接 kill。长驻隔离栈
改用 `setsid nohup bash up-stack.sh &` 脱离会话生命周期，探针自带重连，栈死了
看 `/tmp/acp754-home/stack.out`。
