# 顶栏加一个控件，demo 的「零请求」契约就红了

日期：2026-10-09　相关：ACP-2149（S5 正式服务器部署）、`ProdServerControl.tsx`、
`demo/states-release.test.tsx`

## 现象

在 `AiStudioPage` 顶栏加了正式服务器控件（`ProdServerControl`，并且已经用
`!demoStates` 挡住 demo 模式），自己的 8 条测试全过、`tsc` 干净。跑
`src/apps/ai-studio/` 全量，`demo/states-release.test.tsx` 红了 4 条，报错只有一句：

```
AssertionError: expected "Mock" to not be called at all, but actually been called 1 times
```

四条全是同一句，看不出是哪来的请求。

## 根因

这个文件是**「demo 画面一个网络请求都不许发」**的证据（`fetchSpy =
vi.spyOn(globalThis, 'fetch')` + `expect(fetchSpy).not.toHaveBeenCalled()`）。它把
顶栏壳子的接口面都换成了替身：

```js
return { ...actual, publishApi: pub, studioApi: studio }
```

`DevServerControl` 用的 `studioApi.getDevServer` 正好在被换掉的 `studio` 里，所以它
一声不响。**而 `prodServerApi` 是 `studioApi.ts` 里另一个 export**（当初就不挂在
`StudioApi` 接口上，理由和 `publishApi` 一样：demo runtime 精确实现 `StudioApi`，
绝不假扮一次部署），这一句 spread 里没有它，于是它走真实的 `request()`，发出
`GET /api/apps/ai-studio/projects/p1/prod-server` —— 就是那第 1 次 fetch。

两个坑叠在一起才难查：

1. **`!demoStates` 挡不住它**。`states-release.test.tsx` 是**非 demo 路径**渲染真的
   `AiStudioPage`（要证明的是「真壳子 + 真组件」），所以顶栏的两个服务器控件都会挂载。
   demo 模式那个开关管的是「画面用快照驱动」，不是「这个组件不渲染」。
2. **一个模块里的多个 export，`vi.mock` 只换你点名的那几个。**新加一个独立 export
   的 api 面，等于给所有「整壳子渲染 + 断言零请求」的测试悄悄加了一条新请求。

## 修法

按这个文件自己的先例补 stub —— ACP-2085 S2 加 `ensureReqSession` 时就是同一个局面
（聊天列在壳子里，会开真会话），当时也是在 hoisted 里给一个假函数并注明理由：

```js
const prod = vi.hoisted(() => ({ getProdServer: vi.fn(async () => ({...})), ... }))
vi.mock('../studioApi', async () => {
  const actual = await vi.importActual<typeof import('../studioApi')>('../studioApi')
  return { ...actual, publishApi: pub, studioApi: studio, prodServerApi: prod }
})
```

改完 18/18 过。

## 怎么避免

1. **新加一个独立的 api export（publishApi / devBoardApi / prodServerApi 这类），第
   一件事是 grep 谁在断言零请求**：
   `grep -rn "spyOn(globalThis, 'fetch')" website/src`。这些文件的契约是「一次 fetch
   都不许有」，任何新接口面都必须在这里登记成替身，否则会红，而且红得看不出来源。
   实测这类文件有：`demo/states-{commit,design,devdeploy,graph,release}.test.tsx`、
   `DevDagPanel.test.tsx`。
2. **定位「哪来的第 N 次 fetch」不要靠猜**：spy 会把它收到的参数原样打出来
   （`"/api/apps/ai-studio/projects/p1/prod-server"` 一行就锁定了控件）。先跑一次看
   URL，比读半小时组件代码快。
3. 顶栏加控件时，**判据跑全量 `src/apps/ai-studio/`，不要只跑自己那个测试文件**。
   本次自己的 8 条全绿、全量红 4 条，红的还是别人的文件——「我只加了自己那块」在这
   个壳子里不成立。
4. 顺带一条纪律：**改动落在派工单划定的地盘之外时，如实报出去**。这单的地盘写的是
   `AiStudioPage.tsx`（放控件）等文件，没写 `demo/states-release.test.tsx`；但把控件
   放进顶栏**必然**动到那条零请求契约。要么改那个测试，要么别放顶栏——没有第三种。
