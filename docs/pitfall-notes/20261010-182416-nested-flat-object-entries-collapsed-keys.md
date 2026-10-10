# `Object.entries(flat(x))` 把 15061 个键塌成 6659，我的审计于是全绿

## 现象

为了写 ACP-2250 的收尾说明，我想知道每个语种还缺多少键。写了个审计脚本遍历 11 个语种，
输出：

```
locale     keys    absent   no-script  reads-english
bn          6659         0           0               0
hi          6659         0           0               0
...  11 个语种 absent 全 0
```

**同一时刻，`catalogParity.test.ts` 正报红**：

```
FAIL src/i18n/catalogParity.test.ts > catalog parity > hi
AssertionError: missing 181 key(s), e.g. apps.aiStudio.back_to_editing, …
```

我的审计说「一个都不缺」，仓库的门禁说「hi 缺 181」。**审计是错的那一方**，
而且它错的方式是**报绿**。

## 根因

`flat()` 自己已经返回**键值对数组** `[[key, value], …]`，我在递归处又套了一层
`Object.entries()`：

```js
const flat = (o, p = '') => Object.entries(o).flatMap(([k, v]) =>
  (v && typeof v === 'object' && !Array.isArray(v))
    ? Object.entries(flat(v, `${p}${k}.`)).map(([a, b]) => [a, b])   // ← 错
    : [[`${p}${k}`, v]])
```

`Object.entries([['a.b', 1], ['a.c', 2]])` 得到的是 **`[['0',…], ['1',…]]`——数组下标**，
不是键。于是所有嵌套层的点号全名被换成 `"0"`、`"1"`、`"2"`…，
`Object.fromEntries()` 再按后写覆盖前写，**15061 个叶子静默塌成 6659 个键**。

`6659` 正好是 `en` 的键数（`15242` 是 `en.json` + `en.manual.json` 合成后的真实值，
两个数我当时都见过，谁都没提醒我 6659 可疑）。

**为什么它一定报绿**：塌完之后每个语种的键集都变成同一小撮 `"0"…"N"`，
`absent = en 有而 locale 没有`自然全 0；`keys` 列 11 个语种全是 6659，
看着像「大家齐平」，实际上是我的哈希表被自己的键名冲突压平了。

第二个坑叠在上面：**`en` 是两个文件**。运行时英文是
`enCatalog.ts` 里 `mergeCatalogs(en.json, en.manual.json)` 合成的，
`en.manual.json` 有 6538 个叶子。我第一次比对只读 `en.json`（8704 叶），
于是「英文侧根本没有这个键」被算成「谁都不缺」。
`i18n-shard.mjs` 头上写着这就是它当年修过的真 bug，我没读那段注释。

## 修法

1. 递归结果**直接用**，不要再 `Object.entries()`：
   ```js
   ? flat(v, `${p}${k}.`)
   ```
2. 比对英文一律用**合成后**的 `merge(en.json, en.manual.json)`，和
   `catalogParity.test.ts` 读的 `CATALOGS` 同源。
3. 审计脚本加了**自证**，把「全绿」变成会自己喊话的东西：
   ```js
   const countLeaves = o => Object.values(o).reduce(
     (n, v) => n + (v && typeof v === 'object' && !Array.isArray(v) ? countLeaves(v) : 1), 0)
   if (viaFlat !== viaWalk) {
     console.error(`AUDIT IS BROKEN: flatten yields ${viaFlat} but a structural walk finds ${viaWalk}`)
     process.exit(3)
   }
   ```
   两条路径（摊平计数 / 结构化遍历计数）算法不同，一致才继续输出。
   修好后自证打印 `flatten 15061 == structural 15061`，`absent` 立刻变回
   hi 181 / ja,ko,zh-CN 各 212（那 212 全是复数后缀，门禁按各自
   `Intl.PluralRules` 放行，是真绿）。

## 怎么避免

- **审计/统计脚本要有一条与主逻辑不同源的自检**，并且**在报绿之前**跑。
  「全 0」是最危险的输出：它和「真的没问题」长得一模一样。
- **手上已经有一个红的门禁时，任何说「没问题」的自造工具都要先假定自己坏了**。
  这次的正确动作是去查我的脚本，我的第一反应却是「可能测试口径和我不同」——
  去给红门禁找解释，而不是怀疑绿的那个。
- 摊平/展平这类「两种算法该给同一个数」的地方，**就把那个等式写进代码**，
  别写进脑子里。
- 语种目录比对，**英文侧永远用合成后的 `CATALOGS`**，不要用 `locales/en.json` 单文件。
