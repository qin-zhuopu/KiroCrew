# 开机恢复挂在 `register_routes` 里：一条老测试变 202，以及「不知道」被当成「已停止」

日期：2026-10-09　相关：ACP-2111（creating 永远卡住）、ACP-2112（闪一下「已停止」）、`ai_studio/backend/{workspace,routes}.py`、`website/src/apps/ai-studio/DevServerControl.tsx`

## 现象一：改动没碰路由，`test_route_retry` 却从 409 变成 202

```
async def test_route_retry(home, monkeypatch):
    _create()                       # status=creating
    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        resp = await client.post(".../projects/sbgl/retry")
>       assert resp.status == 409
E       AssertionError: assert 202 == 409
```

这条测试测的是 retry 路由的 409 语义，`_create()` 建的记录 `status=creating`，
按契约「非 failed 一律 409」它就该被拒。改动只在 `workspace.py` 里加了一个
`recover_interrupted()` 函数——**函数没人调是不会改数据的**。

## 根因一

`register_routes` 里加了开机恢复（派生任务跑在本进程线程里，网关重启就没了，
记录永远停在 `creating`：界面转圈、retry 409、重建代号又 409）。恢复跑在
**daemon 线程**里（注册路径在事件循环上，全盘扫目录不能同步跑），于是：

`_make_app()` → `register_routes()` → 线程起 → 扫到这条 `creating` 且无活任务
→ 判 `failed` → 后面那次 POST 读到的是 failed → 202。

竞态的本质不是「恢复错了」，恰恰相反，**恢复做的事是对的**：一个 `creating`
且本进程没在跑的记录，在线程模型里已经没有任何主体会让它结束了。是那条老测试
**默认了这个谎永远不会被改**——它的 `_create()` 造的就是一条「没人认领的
creating」，而它要的现场是「派生还在跑」。在加恢复之前这两种现场长得一模一样，
加了之后不一样了，测试就暴露出来。

顺带一条只有踩了才知道的事实：**`register_routes` 是 14 个 ai-studio 测试文件
共用的**（`grep -l register_routes test/test_ai_studio_*.py | wc -l`；全仓 39 个）。
往注册里加任何副作用，都不只是「我这一单的行为变了」，而是这 14 个文件里每一个
HTTP 用例都可能多一个和它抢同一批记录的线程。

## 修法一

1. 那条老测试**正文一个字没改**——它本来就写了「creating → 409，手动
   `update_project(status="failed")` → 202」两半，坏的是它赖以成立的前提。要修的
   是前提：`_make_app` 默认关掉恢复，409 那一半才重新成立。
2. `_make_app(monkeypatch, recover=False)`：默认把开机恢复打桩掉，恢复本身由
   `test_register_routes_recovers_on_boot(recover=True)` 单独验一次。
   理由不是「怕慢」，是**它跑多快由调度器定、不由测试定**，留着就是一场挂钟赛跑。
3. 验「开机扫过一遍但不许碰普通项目」那条，不能只是 `_make_app(recover=True)`
   然后断言没变——线程还没跑到当然也没变，那是**假绿**。要放一条该被改判的记录
   当栅栏：它翻成 `failed` 才证明那一趟扫完了，这时再断普通项目一个字段没动。

## 现象二：打开工作台，开发服务器按钮先显示「已停止」再跳到「运行中」

后端状态一直是对的（`status()` 每次现算 pid + HTTP 探针），红的是**前端在没拿到
答案之前先替它答了**：

```ts
const state = view?.state ?? 'stopped'   // view 是 useQuery 的 data
```

首次 GET 在飞的时候 `view === undefined`，这行把「还不知道」写成「已停止」，
于是灰点 + 〔启动〕按钮闪一帧，然后绿点 + 〔停止〕。

## 根因二

`?? 'stopped'` 是一个**关于世界的断言**，被拿来当缺省值用。同一句在
`ProdServerControl` 里是分开写的（`querying = view === undefined`），开发控件
少了这一半。同一天里同一个症状（闪「已停止」）有两个完全不同的根因：正式服务器
那边是状态文件原地写读到半份（见
`20261009-065213-nonatomic-state-write-flashes-stopped.md`），这边是前端缺省值
——**症状相同不代表原因相同，两边都要各自读一遍**。

## 修法二

`querying` 单独一态：灰点 `dev-server-dot-unknown` + 文案「查询中…」+ 按钮禁用
（testid 不变，照 `ProdServerControl` 抄）。按钮禁用的理由要单独说清：这颗按钮是
「一态一方向」，`view` 为空时点它永远等于点〔启动〕，对一个马上要被报成 running
的项目就是去讨一趟 409。

测试要**让接口挂着不返回**（`mockReturnValue(new Promise(...))` 自己攥 resolve），
断「查询中…」+ 禁用 + **没有**「已停止」，再放行断真状态。写「返回 stopped 之后
才出现已停止」很容易顺手写成 `mockResolvedValue`，那样首帧就过去了，恰好测不到
要测的那一帧。

## 怎么避免

1. **往 `register_routes` / `on_startup` 里加副作用之前，先 `grep -l` 谁在挂它。**
   注册函数在测试里就是「起一个壳子」的意思，任何副作用都会送进每一个 HTTP 用例；
   加了就要同时给测试一个关掉它的口子，并且**单独**验一次它是开着的。
2. **写恢复逻辑时先想清楚：老测试里那些"造一条坏记录"的现场，会不会正是我要改判
   的对象。**如果会，那条测试要的现场多半需要显式声明（在本进程里登记一个活任务、
   或关掉恢复），而不是靠「反正没人改」。
3. **异步数据没有「未知」这一态，就会把未知渲染成某个具体状态。**组件里凡有
   `data ?? <某个真状态>`，问一句：这个缺省值是在给用户兜底显示，还是在替后端
   宣布一件还没发生的事？后者要单独一态。
4. 新增 i18n 键之后 `npm run i18n:pseudo` 重新生成 `en-XA.json`（`[pseudolocale]`
   是全仓硬零门禁）。生成器可能顺带修掉别人留下的过期条目——那是它该做的，
   留在同一个提交里。
