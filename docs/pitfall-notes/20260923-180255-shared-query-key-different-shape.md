# 同一个 React Query key、两个不同的 queryFn：静默拿到 undefined

## 现象

给 AI Studio 项目列表页加「演示」入口按钮。按钮只在列表里至少有一个项目时才
渲染（它要拿第一个项目的 id 去接管演示）。加完后：

- 单独打开 `/workspaces`：按钮**不出现**，页面本身正常，一个报错都没有；
- 同一个测试里把列表页组件单独渲染：按钮**能出现**。

也就是说页面没坏、请求也没失败，只是那段读数据的代码永远拿到 `undefined`。
没有任何 red，靠读代码也看不出来。

## 根因

两个组件用了**同一个 query key `['ai-studio','projects']`**，但 `queryFn` 的
返回形状不一样：

```ts
// ProjectsListPage（先挂载的那个，或者缓存里已有的那个）
useQuery({ queryKey: ['ai-studio','projects'],
           queryFn: () => studioApi.listProjects().then((r) => r.projects) })   // → StudioProject[]

// 我新加的 ProjectsList
useQuery({ queryKey: ['ai-studio','projects'],
           queryFn: () => studioApi.listProjects() })                            // → { projects: [...] }
```

React Query 缓存的是**以 key 为索引的一份数据**，不记它是哪个 queryFn 拿回来的。
两个观察者 key 相同 ⇒ 命中同一份缓存：

- 谁先在缓存里放了值，后挂载的那个就直接吃这份值，**自己的 queryFn 根本不会跑**；
- 我那份代码写的是 `data?.[0]?.id`（当成数组），拿到的是 `{projects:[...]}`
  ⇒ `[0]` 是 `undefined` ⇒ `first` 为 undefined ⇒ 按钮不渲染。

于是「按顺序哪个组件先渲染」变成了隐藏的全局状态。

## 修法

让**同 key 的 queryFn 返回同一个形状**——照抄先存在的那一份：

```ts
queryFn: () => studioApi.listProjects().then((r) => r.projects)
```

（或者换一个不同的 key / 用 `select` 做投影。要点是 key 与形状必须一一对应。）

## 怎么避免

- **同一个 query key 只能有一种数据形状。** 新写 `useQuery` 之前，先把 key 在
  仓库里 grep 一遍，看到同 key 的现成调用就**复制它的 queryFn 返回形状**，别只
  复制 key 字符串。
- 这一类不变量没有任何测试会替你守住：它不报错、不警告、请求也正常，只是数据
  是 `undefined`。加功能性入口（「有数据才显示」的那种）时，**测试要从真实的
  页面路径进入**（本坑的用例就是从 `/workspaces` 整页起，才暴露了按钮不出现），
  单独渲染那个小组件的测试会一直是绿的。

相关：[20260923-122306-t7-frontend-gate-baseline-drift.md](20260923-122306-t7-frontend-gate-baseline-drift.md)
（同样属于「测试绿但页面不对」的一类）。