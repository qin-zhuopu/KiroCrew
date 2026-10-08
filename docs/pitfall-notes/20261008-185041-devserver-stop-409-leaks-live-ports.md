# 开发服务器「停止」回 409，进程 / 端口 / 域名三条全泄漏

日期：2026-10-08　单子：ACP-2060（`docs/task-specs/2026/10/ACP-2060-devserver/`）
代码：`src/kiro_crew/apps/builtins/ai_studio/backend/devserver.py`

## 现象

真跑（工作区 `/home/jereh/repo/jc/webapp-template-wt-req-tpl`，域名
`sbgl-14409-dev.gb10.jereh-pe.cn`）：启动卡在「检查网址」超时，状态「启动失败」。
想按〔停止开发服务器〕收拾现场，接口回 **409 `not_running`「开发服务器没在运行」**。
而此刻机器上真实存在：

- 两个活进程（前端 vite 占 6801、后端 nest 占 6800）
- `resreg` 里 6800 / 6801 两条 `CLAIMED` 登记
- 网关 `conf.d/ais-sbgl-14409.conf` 挂着的 server 块

前端按钮这时显示「已停止」，唯一能点的〔启动开发服务器〕会跳过被占的那两个口、再要两个新口
（`ResregPorts.free` = 能 bind 且 `resreg check` 空闲），所以重试不会报错，只是每试一次多漏两口。
最后只能手工收：`kill -- -<pgid>` + `resreg release --type port --value 6800`（6801 同理）
+ 手删 conf。**6800~6999 一共 200 个口，这么漏十次就没端口了。**

## 根因

`stop()` 的准入判据当时写的是「`status()` 说 running / starting 才准停」，而
**`stopped` 的含义只是「网址没通」**（`status()` 的口径：pid 都活 **且** 网址 200 才 running）。
这次的现场恰好是「进程活着 + 端口占着 + conf 挂着，只是网址不通」：

- vite 5.4.21 的 `hostCheckMiddleware` 拦下陌生 Host，域名上回的是 **403 `This host is not allowed`**
- 所以 `status()` 如实报 stopped，`stop()` 就如实报「没在运行」

两个函数都没说谎，**是「没在运行」这个词被当成了两种意思**：一个说「网址打不开」，
一个要问「有没有东西要我清」。用前一个当后一个，就成了永远清不掉的泄漏——而且界面上
一点痕迹都没有（按钮显示已停止），从外面看只是「启动失败了一次」。

顺带挖到的四个小坑（都是「错误本身看不出原因」）：

1. **`__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS` 在 vite 5.4 里根本不存在。**
   RFC §9.6 写的这个环境变量是 vite 6 才有的（读 `node_modules/vite/dist` 里的
   `getAdditionalAllowedHosts` 证实：5.4 只认 `server.host` / `server.hmr.host` / `server.origin`
   三处派生）。想走 CLI 也不行：`vite --server.allowedHosts x` 直接
   `CACError: Unknown option --server`。唯一的门是配置里的 `server.allowedHosts`
   （字符串前导点 = 后缀匹配）。
2. **补的 vite 配置放进 `<工作区>/.ai-studio/` 会 `ERR_MODULE_NOT_FOUND: 'vite'`。**
   配置里要 `import { mergeConfig } from 'vite'`，而 ESM 是按**配置文件自己所在目录**往上找
   `node_modules` 的，`.ai-studio/` 这层下面没有。放到 `apps/web/` 里（和它 merge 的
   `vite.config` 同一层）就好了。
3. **接口探针 403 `Token required`，但 token 是刚拿的新 token。** cookie jar 是按
   `Set-Cookie` 的域记的：登录时用的是 `localhost:6790`，后面拿 `127.0.0.1:6790` 打就不送
   cookie。改回 `localhost` 立刻通。
4. **`resreg check` 的位置参数写法是错的**：必须 `resreg check --type port --value 6800`
   （`release` 同形）。手工清理时敲 `resreg check 6800` 会报缺参数，容易误判成「登记没了」。

## 修法

`stop()` 不再问状态，改问三件具体的事，任一成立就有活可干（`_anything_to_clean`）：

```python
if self._children_ok(state):   # 有没有活进程
    return True
if self._launching():          # 本进程有没有一个后台启动正跑着
    return True
if ports:                      # 状态文件里有没有记着的端口
    return True
if conf is not None:
    return conf.exists()       # 网关上有没有挂着的 conf
return False
```

清理顺序不变：先 `_generation += 1` 作废后台线程（否则它会在回滚后写回 running）→
杀进程组 → 删 conf + reload → release 端口 → 状态落 stopped（`procs: []`，让下一次
409 是诚实的）。真没东西可清才 409。

回归用例：`test/test_ai_studio_devserver.py::test_stop_clears_a_broken_but_live_server`
（直接把泄漏现场摆出来：活 pid + 记着的端口 + 挂着的 conf，`status()` 断言是 stopped，
`stop()` 必须把三样都清干净）、
`test_stop_releases_ports_when_the_processes_are_already_gone`（进程已经没了也要退端口、摘 conf）。

vite 侧不是我们的代码，走 §9.2 的模板契约：工作区 `.ai-studio/workspace.json` 把前端命令换成
`pnpm --filter @webapp-template/web exec vite --config vite.dev-hosts.config.mts`，
`apps/web/vite.dev-hosts.config.mts` 里 `mergeConfig(base, { server: { allowedHosts:
['.gb10.jereh-pe.cn', '.gb10.zhuopu.net'] } })`。

## 怎么避免

- **判「有没有活要清」不许用状态字符串**。状态是给人看的（`stopped` = 网址没通），
  清理要问的是资源：进程、端口、域名。凡是写了「状态不是 X 所以什么都不用做」的地方，
  先问一遍「资源都退了吗」——漏的都是要钱的资源（端口尤其）。
- **失败态必须留一条能收拾的路径**。启动失败 + 状态显示已停止，界面上就一个按钮都点不动，
  等于把泄漏留给手工。「失败」和「没在运行」不能共用一个 409。
- **别照抄 RFC 里的环境变量名**：先在被依赖的那版代码里 grep 一遍（这里 `vite/dist`），
  新版本才有的开关在旧版本上是静默无效——静默无效比报错难查得多。
- **验收 6.4「停止后网址不再 200」实测不成立**：网关有个 docker-gen 维护的**默认 vhost**
  （不在 `conf.d/` 里，不是我写的）兜住所有 `*.gb10.jereh-pe.cn`，删掉项目 conf 之后
  域名仍 200，只是内容换成了默认页。要证「摘干净」得看 `conf.d/ais-*.conf` 消失 +
  `nginx -T` 里没有那条 `server_name` + `resreg check` 回 0，**不能只看网址**。
  （标题「杰瑞制造管理平台」和 `fe-frame.gb10.jereh-pe.cn` 完全一致，就是兜底的证据。）
