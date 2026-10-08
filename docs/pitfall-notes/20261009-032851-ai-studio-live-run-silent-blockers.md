# 真跑需求页直改：从报错本身看不出来的拦路石

日期：2026-10-09 · 关联：ACP-2104（需求页直接改文档 + 〔开始开发〕）、RFC `rfc-ai-studio-req-flow`

第 5 步要「用浏览器真跑」：在跑起来的网关上打开演示项目，改一句、保存、看判定条、看左栏会话收到消息。
这一步连着踩了五个坑，**每一个的报错都不指向根因**，都是靠交叉验证才排掉的。记下来。

## 坑一：浏览器里每个写请求都 403，curl 却 200

### 现象

页面读得出来（判定条、文档正文都正常），唯独左栏需求会话那一栏显示 `Forbidden` + 〔重试〕。
同一条 `POST /projects/{id}/req-session`，我用 curl 打：**200**。用浏览器打：**403**。

### 根因

CSRF 中间件只校验浏览器带的 `Origin`，**curl 不带 Origin 就直接放行**（安全方法 GET 也不校）。
所以我一开始用 curl 验证，验证的是「没带 Origin 的请求」，跟浏览器根本不是同一条路径——curl 绿不等于浏览器绿。

403 的正文只有一句 `CSRF check failed: request origin not allowed.`，看不出它嫌的是哪个 origin。
`build_allowed_origins`（`dashboard/urls.py`）里 origin 集合是按端口拼死的：

- `http://localhost:<网关端口>` / `127.0.0.1` / `kirocrew.localhost`
- **`KIROCREW_HOME` 设了就额外加 `http://localhost:3000` 和 `http://127.0.0.1:3000`**（开发用）
- 再加上 `dashboard_url`、`KIROCREW_CORS_ORIGINS`、`KIROCREW_ALLOWED_LOOPBACK_PORTS`

我这次用 vite 的 **6791** 端口开页面。6791 不在上面任何一条里 → 浏览器的 Origin 一律被拒。
而 3000 是代码里明写的开发端口，**不用改任何配置**。

### 修法

真跑用 `http://localhost:3000` 开页面：vite 换端口起一个（`vite --port 3000 --strictPort`），
`/api` 代理目标仍由启动时的 `KIROCREW_PORT` 决定，指到 6790 那个跑着本 worktree 后端的网关。

```bash
cd website && KIROCREW_PORT=6790 ./node_modules/.bin/vite --port 3000 --strictPort --host 127.0.0.1
```

要非 3000 的端口就得给网关加 `KIROCREW_ALLOWED_LOOPBACK_PORTS`，那是改运行环境，不是改仓。

### 怎么避免

- **浏览器里「读得出、写不进去」+ curl 全绿 = 先怀疑 Origin，不要怀疑 handler 或权限清单。**
  CSRF 只卡非安全方法、只卡带 Origin 的请求，这个不对称是设计如此（见
  [20260922-170210-builtin-app-registration-and-csrf.md](20260922-170210-builtin-app-registration-and-csrf.md)）。
- **用 curl 复现浏览器行为时，必须显式带 `Origin`**：
  `curl -H 'Origin: http://localhost:6791' ...` 一比就露。不带 Origin 的 curl 测不出 CSRF 类问题。

## 坑二：assistant 的图谱写入静静等了 10 分钟，然后自己被拒，接着网关自己退了

### 现象

第 5 步要求「等助手把改动落回图谱，判定条自己恢复」。我发完改动就挂着等，10 分钟后不仅没落，
回头看 `pending_approval` 已经没了，网关进程也没了。日志里两行关键话：

```
Tool approval for 'Edit docs/需求图谱/设备分类.json' went unanswered for 600s; declining
PERM REJECTED ... outcome='rejected' — auto-rejecting remaining batch
```

再往后：

```
event loop silent 16.5s — stall enrichment captured ... dump-then-exit
```

### 根因

两件事叠一起，都不是 bug：

1. **工具批准有 600 秒有效期**。超时是**自动替你拒绝**（会话里明写「nothing was rolled back，想跑就重发」），
   不是无限等。`config.json` 的 `approval_mode=auto` **不覆盖工作区外的 Edit**——图谱在模板仓，不在 crew home，
   所以它每次都问人。这正好是功能要的设计：平台永不写图谱，写图谱是会话的活，而且要点一次批准。
2. 批准后事件循环卡了一段，loop-watchdog 按「dump-then-exit」把网关整进程退了。**所以「等」的时候网关可能已经没了**，
   从外面看只是「页面没反应」，没有任何前端报错。

### 修法

浏览器驱动里加一个 `drainApprovals()`：轮询会话里的〔批准〕按钮，出现就点，直到 pending 消失。
真跑必须**在 600 秒内点掉**，否则改动会被自动拒。网关退了就用 `.kirocrew-dev/run-gw.sh` 重启
（必须 exec 真 launcher 路径，否则 AppArmor profile 不匹配、userns EPERM，见
[20260923-135214-apparmor-userns-multi-instance-launcher.md](20260923-135214-apparmor-userns-multi-instance-launcher.md)）。

### 怎么避免

- **等人工批准的流程，自动化脚本必须自己当那个「人」**，并且知道批准会过期（600s）。
- **判断「卡住」之前先看网关还在不在**：`ss -tln | grep :6790` + 看网关日志末行有没有 `dump-then-exit`。
  进程没了，前端只会表现为「转圈 / 502」，不会说「网关退出了」。

## 坑三：改文档不改变文档——「拿旧 docHash 重试」根本测不出陈旧

### 现象

真跑脚本第 5 步想验「文档被别人改过 → 409」，做法是「用刚才那次直改之前的 docHash 再提一次」。
结果 **200，还往账本里多写了一行**。看起来像「409 没生效」。

### 根因

**直改成功故意不改渲染文档**：它只追加一行账本 + 把 diff 发给会话，图谱和由图谱渲染的文档一个字节都不动
（改视图不等于改需求，落回图谱是会话的活）。所以直改之后 `docHash` 和之前**一模一样**，
「用旧 hash 重试」里的 hash 其实一点都不旧 → 服务端判你没错，正常接受。

我的测试假设错了，不是产品错了。而且它还**真的往演示工作区的账本里写了一行垃圾数据**，
把判定条钉在「改动待落回需求」上，害得下一次真跑一开局就是脏的。

### 修法

- 测 409 用**当前页面上确实不存在的 hash**（把 live hash 改一个字符），那才是「浏览器拿的是落回前的旧视图」的真实形态。
  这个分支单测里本来就有，真跑脚本改成不写账本的只读法。
- 脚本往演示工作区写东西前想清楚能不能撤；我这次是把多出来的那行删掉、把会话 transcript 备份出来，
  才敢重跑（`.ai-studio/*.jsonl` 是产品账本，不是我的临时文件）。

### 怎么避免

- **写「测拒绝路径」的用例前，先确认那个凭证真的会变旧**。这里会改 hash 的是**图谱**（会话落回之后），
  不是文档；两套乐观并发凭据（`docHash` 门直改 / `graphHash` 门开始开发）争用对象不同，是刻意的。
- **真跑脚本尽量只读**；必须写就要能复原（先 `cp` 出来）。

## 坑四：视图里带「生成时间」，哈希每渲染一次变一次

### 现象

`docHash` 本该是「这份需求视图现在的样子」的指纹。真跑里它有两种不该有的表现：

1. 网关重启后同一个页面的 `docHash` 变了（需求一个字没动）
2. 更早就出现过：用户刚在编辑器里打一个字，下一次 5 秒轮询回来，界面就亮「你的未保存修改已保留」——
   其实那是渲染器自己换了个日期，跟人打的字无关

报的都不是「时间戳」，看起来像「哈希算错了」或者「前端脏判定写错了」。

### 根因

`jc fe reqdoc render`（`reqstd-v34/render.js`）在每份文档里都盖一行 `生成时间：<ISO>`。
视图文本本身**每渲染一次就不逐字节相同**，直接对返回文本取哈希 = 对「现在几点」取哈希。
而这一行落在文档中段的正文里（不是页脚注释），肉眼比对 diff 时也不会注意到它。

### 修法

`requirements.stable_doc()`：用 `_STAMP_RE` 把那一行抹掉之后再往下发。三个下游都吃这个去戳文本
——`docHash`、发给会话的 diff、前端的「有没有未保存改动」。落点见 `requirements.py` 里
`_STAMP_RE` / `doc_hash` / `read_page` 的注释。改完的实证：网关重启前后同一个页面 `docHash` 不变。

### 怎么避免

- **凡是要拿一个「别人生成的文本」当乐观并发凭据，先确认那段文本自己是不是幂等的**：
  带时间戳/随机 id/绝对路径的生成物都不是。判法很简单——同一个输入渲染两次，`cmp` 一下。
- 抹戳的正则是**整行模式**（`生成时间：<ISO>`），别改成通配整段——那会把正文里带日期的需求句子一起吃掉。

## 坑五：两本账本不在 crew home，跟着工作区走

### 现象

真跑后要贴 `direct-edits.jsonl` / `start-requests.jsonl` 的新一行。我在 `KIROCREW_HOME`
（本次是 worktree 下的 `.kirocrew-dev/`）里翻，`projects/` 下压根没有 `.ai-studio/`，
全盘 `find` 才找到。

### 根因

两个「家」不是一回事：`KIROCREW_HOME` 是**网关/会话**的家；需求工作区是**另一个仓的 checkout**
（本次演示项目的 `ws_path` 指向 webapp-template 的一个 worktree），账本写在
`<ws_path>/.ai-studio/` 下，和 devserver 的状态文件同一目录（`requirements.DIRECT_EDITS_FILE`）。
所以「演示项目的需求页」的账本在模板仓里，与 crew home 无关。

### 修法

先读页面接口返回里的 `wsPath`（或直接看 projects 接口），再去那个目录下找 `.ai-studio/*.jsonl`。
这两个文件是**产品账本、不进 Git**（模板仓里它们就是 untracked），别顺手提交。

### 怎么避免

- 找「某功能写到哪了」不要按 `KIROCREW_HOME` 猜，先 grep 常量（`DIRECT_EDITS_FILE` 这类），
  从常量往上读一次基准路径是谁。

## 附带记下（同一个真跑里撞的次要项）

- **需求会话会拒绝不像需求的改动**（这是对的行为）。我第一版在 R-15 后面加了句「这一条是真跑时手工加的备注」，
  助手回：这半句讲的是文档自己的来历、不是页面该怎么表现、没法判定也没法写进验收，问我要不要照抄/不写/挪走
  —— 正是协议里「落不进去的地方问我」。真跑要改就改**文档里已有的可判定值**（这次改成「每页 20 条 → 每页 50 条」）。
- **`每页 20 条` 在文档里有 4 处**（v34 各页共用这套措辞）。按文本搜会替换错的那条；
  要用唯一的行前缀 `- R-15 规则：` 定位整行。
- **playwright 在 1280×720 之外的三栏工作台里点不到编辑器**：左右两个 `aside` 和拖拽分隔条会
  `intercepts pointer events`，报的是「click 超时」，看不出是布局遮挡。`setViewportSize({1920,1080})` 就有了。
- **`page.keyboard.type` 前要先 `setSelectionRange`**：直接点 textarea 会把光标放到点击处，
  替换整行的正确做法是先框选再打字（打字本身即替换选区，也能让 React 的 onChange 正常触发）。
- **cookie 名字带端口**（`mc_token_6790`），且作用域是 `localhost`；cookie 不分端口，
  所以同一份 cookie 在 3000 上照样能用。用 127.0.0.1 访问会 403「Token required」。
