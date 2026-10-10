# `git checkout` 的「从索引区更新了 0 个路径」不是证据；顺手记它的恢复源是索引

日期：2026-10-10 10:20（ACP-2231 收尾）

## 现象

收尾时想把一个多改的文件撤干净，敲 `git checkout <file>`（**没写 `--`**），回显：

```
从索引区更新了 0 个路径
```

「0 个路径」看起来像「什么都没更新 = 我的改动还留着」。实际当时那个文件**离 HEAD
只差 0**，本来就干净。我把这句话当成了「撤销失败」的症状，接着凭印象讲出了完整一段
故事（"我早先给它加了 12 行、撤过一遍、又把它粘回来、测试还全绿"）——**写完笔记去核，
这段故事一件都不成立**（下面第三节）。真正值得记的是前两节的实测。

## 实测：三条确定的语义

`git init` 临时仓逐状态复现 + 本仓实测，git 2.43：

1. **恢复源是索引（暂存区），不是 HEAD。** 文件被 `git add` 过（`status --porcelain`
   索引位是 `M`，即 `M ` 或 `MM`）时：

   | 撤销前 | `git checkout -- <f>` 之后 |
   |---|---|
   | `MM`（索引旧版 + 工作区新版） | 内容变成**索引里那份**，`status` 仍是 `M `，离 HEAD 还差一截 |
   | ` M`（只有工作区改动） | 内容回到 HEAD，`status` 干净，**一个字回显都没有**，rc=0 |
   | 干净 | 什么都不做，**回显同样是空的**（带 `--` 时），rc=0 |

   要真回 HEAD 必须写明来源，它同时覆盖索引和工作区（实测 `MM` → `status` 干净）：

   ```bash
   git checkout HEAD -- <file>     # 或 git restore --source=HEAD -- <file>
   ```

2. **`Updated N paths from the index` / 「从索引区更新了 N 个路径」只在没写 `--` 时
   打印，且 N 是「索引 → 工作区写回了几条」**，不是「撤销生效了吗」，更不是「文件离
   HEAD 还有多远」。实测：同一个干净文件，`git checkout f.txt` 回「0 个路径」，
   `git checkout -- f.txt` 回空 —— 两者什么都没干，回显却不一样。**话多图省的那条
   并没有多做事。**

3. 所以这三句话都不构成证据：空回显、非空回显、rc=0。「撤干净了」只认：

   ```bash
   git diff HEAD --stat -- <file>   # 应当为空
   git status --porcelain -- <file> # 应当不再出现
   ```

## 核对自己的现场，别信记忆（本条才是这篇的由来）

我按记忆写下「我改过那个测试文件、撤了 12 行又粘回来」，然后逐条查：

```
git diff HEAD --stat -- test/test_ai_studio_prodserver.py   → 空
git status --porcelain -- <该文件>                          → 空（本来就干净）
四个 worktree 里该文件行数一致（1260），无 _CUT_STEPS        → 没有那份表
全仓 grep -rn "_CUT_STEPS\|cut_steps" src/ test/ website/   → 0 命中
两份 transcript 里对该文件 Edit/Write                        → 0 次
```

**一次编辑都没发生过**，那 12 行、那次撤销、那次"粘回来还全绿"全是我编的（会话被压缩
过，压缩后我会用先验把空白填成通顺的故事，同族毛病见记忆「压缩后我会编造标识符」）。
差别只在于：标识符编错了 grep 一下就露馅，**流程故事编错了没有任何东西会报错**——
没有测试变红，没有 CI 拦住，只有下一轮我去核对时才发现。

**怎么写才不再犯**：

1. 笔记里每一条"我干了 X"都要能在输出里指出**哪条命令证明的**；给不出命令的句子
   一律写成疑问，或者删掉。
2. **先跑命令，再下结论**。这篇第一版把「0 个路径」的机制也一并编了（"N 只统计写回、
   撤已 staged 的文件时 N=0"），实测才发现真正原因是那条命令**没写 `--`**。
3. 撤销/清理类动作，动手**前**跑一次 `git status --porcelain`：索引位有 `M` 就说明
   `checkout -- <f>` 到不了 HEAD，直接 `git checkout HEAD -- <f>`。

## 附带：同族的「空输出当绿」，这次栽在 `scripts/check_comment_history.py`

同一天我拿 `grep -E '^(src|test)'` 挑这个门禁的违规行，挑回 0 行就当成没事。两处会让
这个过滤器瞎掉（都实测过）：

- **默认它根本不 enforce**，只回一行报告：`comment-history report: 518 marker(s) in
  182 file(s) … Not enforced here; set COMMENT_HISTORY_BASE_REF to gate a change.`
  这行不以 `src/`、`test/` 开头，被模式滤掉；518 是**全仓存量**，跟这一刀无关。
- 真 enforce 时违规行是 `print(f"  {rel}:{line}: …")`（脚本 316 行），**行首两个空格**，
  `^src/` 永远匹配不上。

门禁自己这一刀要写明来源：`COMMENT_HISTORY_BASE_REF=HEAD python3 scripts/check_comment_history.py`
（实测这一刀过：`gate scope: HEAD..working tree (4 changed file(s))` → passed）。
挑关键行别用行首路径锚；退出码只在**直接重定向**时可信，接上管道拿到的是 grep 的码。
