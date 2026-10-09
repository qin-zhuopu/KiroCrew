# 自查合并结果：把文件拷到 /tmp 再跑 black，会得出一份假判决

合并 ACP-2210（修完自动再验收）和 ACP-2207（并行 worktree）时，两边都重写了同一个
`_loop`。解完之后我要自查两件事：① 有没有把两边的用例弄丢；② black 有没有顺手把我
没碰的行重排掉（那会把合并提交变成一坨重排噪音）。第二个自查先给出「black 改了 132
行我没碰的代码」，据此我差点回去重做冲突解决。那 132 行是假的。

## 现象

```
$ .venv/bin/black --target-version py310 --check --diff /tmp/head_test_devdag.py | grep -c "^[+-]"
134
```

`/tmp/head_test_devdag.py` 是 `git show HEAD:test/test_ai_studio_devdag.py` 的原文，
一个字没改。它却报 134 行「要重排」，包括几十个好好的 `async def test_xxx(ws, jira)`
签名。按这个数字，我这个合并提交就顺手重排了整份文件。

## 根因

**black 的配置是「从文件所在位置往上找 pyproject.toml」，文件被拷出仓库就没配置了。**
本仓 `pyproject.toml` 里 `line-length = 100`；拷到 `/tmp` 之后 black 找不到它，退回默认
88，于是每一行超过 88 的签名都算要折行。同一个文件、同一个 black、同一个参数，只是
放的位置不同：

```
$ .venv/bin/black --target-version py310 --check --diff /tmp/head_test_devdag.py | grep -c "^[+-]"
134                      # /tmp：没配置，按 88 判
$ cp /tmp/head_test_devdag.py ./tmp_head_probe.py
$ .venv/bin/black --target-version py310 --check --diff ./tmp_head_probe.py | grep -c "^[+-]"
0                        # 仓库内：读到 line-length = 100，本来就是干净的
```

报错本身（「would reformat」）完全看不出发言依据的是哪套配置，`--verbose` 也不打印它
最终读到的 `line-length`。凡是**把仓库里的文件拷到 /tmp 去跑格式化工具**的做法都会中
这一枪：mypy、isort、eslint 同理（各找各的配置文件），只是 black 的默认列宽和仓里的
100 差得最远，最容易露出「一大片要重排」的假象。

## 修法

自查合并结果一律**在原地**做，不要拷出去：

```
$ git checkout -m -- test/test_ai_studio_devdag.py   # 重新造出带 <<<< ==== >>>> 的冲突现场
$ # 剥掉三段标记行，得到「未经处理的合并结果」
$ diff -u <剥完的现场> <我实际提交的版本>            # 这就是我对合并做的全部改动
```

`git checkout -m -- <路径>` 会用同一个策略**重新生成一遍冲突**，这是唯一能把「git 本来
会怎么合」和「我手工解成了什么」摆在一起对比的办法（`git diff HEAD` 不行，它比的是我
的解法和上一版，中间隔着我自己的编辑）。

这么量出来，black 在这份文件上真正的改动只有两处：`import subprocess` / `import threading`
换了个顺序（isort），以及几行我自己写的注释被折行。**没有重排任何我没碰的代码。**

顺手把「两边用例有没有丢」也证了，而不是数一眼说看着齐：

```
$ # 分别抽出三方（HEAD / ACP-2015-v1 / merge-base）的 test_* 名字，和合并后的文件比
ours 45 theirs 44 merged 56（去重后也是 56，无重名）
ours missing: []      theirs missing: []      new in merged: []
```

45 + 44 − 33 个共有 = 56，两边一个不丢。**不数这一遍的话，「我把 2207 的 11 个并行用例
挤掉了」这种事在 pytest 全绿的情况下是完全可能发生的**——并行用例和被挤掉的那一批都在
同一个文件里，少 11 个用例只会让总数变少，不会报错。

## 另一半：`_loop` 的冲突不是二选一，是「钩子要换个位置」

`修完自动再验收` 原来挂在「每个节点跑完」后面：

```python
await self._run_node(...)
if node.get("kind") == "fix" and node.get("state") == "done":
    await self._re_accept_after_fix()
```

照抄进并行循环会**静默测错东西**：并行时「一个节点跑完」不等于「活干完了」，修复节点的
兄弟可能还在自己的 worktree 里写代码，这时跑验收跑的是半份代码。红灯不会有——验收会
正常跑完并给出一个结论，只是那个结论对它没跑过的代码负责。所以钩子搬到整轮收口之前：

```python
if not running:
    if _round_all_done_with_fix(data):        # 全 done 且这一轮排过 fix
        await self._re_accept_after_fix(data)
    self._close_run(data)
    return
```

判定条件抽成一个模块级函数（`_round_all_done_with_fix`）而不是内联：并行之后读它的
不止一处（循环一处、测试想不问文件系统也能验它），但它是**对调用方手里那份 `data` 的
一句提问**，不重读盘，所以不会变成第二个事实来源。`_re_accept_after_fix` 也因此改成
收 `data` 参数：并行后落盘是整份覆盖，在钩子里重读只会多一个可能过期的副本。

## 怎么避免

- **格式化工具只在文件原本待的位置跑**（`black`/`isort`/`mypy`/`eslint` 全部同理）。
  要拿「改动前」做对照，用 `git checkout -m -- <路径>` 或新建一个干净 worktree，
  **不要拷到 /tmp**——配置不在那儿。
- black 报一大片要重排、而这片里有你没碰过的行，**先怀疑配置没被读到**，别先怀疑
  你改坏了。判据：`grep line-length pyproject.toml`，然后把同一个文件放回仓里再跑一次。
- 合并完带大段并列新增的测试文件，**用三方 test 名字集合证明没丢**，别用「pytest 全绿」
  证明——少几个用例永远是绿的。
- 同一个函数两边都重写了（这次是 `_loop`）：先问「我那半挂在这个函数的哪个位置」，
  再问「新结构里那个位置还成立吗」。串行循环里「节点跑完 = 这轮跑完」这个前提，并行
  之后不成立了；照搬位置就是照搬一个已经不存在的前提。
