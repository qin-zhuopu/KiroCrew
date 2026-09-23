# 填坑：登录 kiro-dev 服务（kiro-dev ≠ docker 容器；token 自签）

日期：2026-09-23。现象是「要给用户登录 https://kiro-dev.gb10.zhuopu.net」，试错中三次走偏。

## 现象

- 一上来 docker exec 进 `kirocrew-docker` 容器读配置、报「当前引擎是 claude」，被 Owner 拆穿：「这个不是从源码启动的dev服务器吗？怎么又扯到docker了」。
- 想「扒浏览器登录态」做 API 集成，绕去 playwright/CDP 抓 localStorage，被问「kirocrew自己没有cli或者mcp和你集成吗」。
- 页面偶发白屏报 "Could not load /src/main.tsx"，误以为是服务坏了。

## 根因

1. **容器名 ≠ 域名归宿**。本机一个 nginx 容器 + nginx-proxy 承载多个域名：容器用 `VIRTUAL_HOST`/`VIRTUAL_PORT` 自动注册；纯反代（后端不在容器里）则在挂载的 conf.d 里手写 `server_name` + `proxy_pass`。kiro-dev 就是纯反代：`web-gateways` 容器 conf.d/kiro.conf → 宿主 vite :3000（`vite.kirodev.config.ts`）→ 宿主网关 :6777（`KIROCREW_HOME=<仓>/.kirocrew-dev .venv/bin/kirocrew gateway --no-open`）。`kirocrew-docker` 是任务九的另一个实例，与它无关。查域名指向要 `docker inspect` 各容器 env + 翻 `/home/jereh/docker/web-gateways/conf.d/`，不能看容器名猜。
2. **dashboard 令牌不用扒，CLI 能现签**：网关自带 `kirocrew token --ttl 1h`，打印带 token 的完整 URL；API 调用带 `Authorization: Bearer <token>` 即可。扒 localStorage 既脆又多余。
3. **vite 冷启动假错**：dev server 长时间没访问后，首个请求触发按需转换，浏览器等不到 `main.tsx` 就报加载失败；再刷一次即正常，不是服务故障。

## 修法

```bash
# 现签登录 URL（KIROCREW_HOME/PORT 用该实例的真实值）
KIROCREW_HOME=$PWD/.kirocrew-dev KIROCREW_PORT=6777 .venv/bin/kirocrew token --ttl 8h
# 验 API
curl -s -H "Authorization: Bearer $TOK" https://kiro-dev.gb10.zhuopu.net/api/config
# 浏览器打开：把 URL 里 localhost:6777 换回域名即可
```

## 怎么避免

- 查任何 `*.gb10.zhuopu.net` 域名，先想 nginx-proxy 多域名机制：env 自动注册 or conf.d 手写反代，最后才落到容器/宿主进程。
- 需要网关 API 时第一反应 `kirocrew token`，不是浏览器状态。
- 读某实例配置前先确认它的数据 home（此处 `<仓>/.kirocrew-dev/config.json`），别拿同名容器顶替。
- dev server 域名报「模块加载失败」先刷新重试一次再排查。
