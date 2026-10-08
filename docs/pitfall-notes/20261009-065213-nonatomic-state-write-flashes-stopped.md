# 状态文件原地写：部署中会被读成「已停止」

日期：2026-10-09　相关：ACP-2149（S5 正式服务器部署）、`prodserver.py`

## 现象

路由层单测 `test_prod_route_deploy_gate_is_409_then_202` 断言「第二次点部署立刻返回
deploying」，实际返回 `stopped`：

```
AssertionError: assert 'stopped' == 'deploying'
```

诡异的地方在于**证据互相矛盾**。在断言前把三个输入打出来：

```
DBG stopped {'state': 'deploying', 'step': '构建', ...} busy 2 gen 2
```

磁盘上的状态文件明明写着 `deploying`，进程内的「我在部署」凭据（`_busy_gen`）也确实
是 2，可 `status()` 返回的就是 `stopped`。读代码怎么读都是对的。

还有一个迷惑现象：**`-n 0` 串行跑 37 条全绿，只有 xdist 并发跑才红**。第一反应是
「测试之间互相污染」或者「xdist 的锅」，于是去查 fixture 隔离、查 `_SERVERS` 缓存
有没有清干净——全是白费劲。

## 根因

`_write_state` 走的是 `devserver.merge_json_file`，它内部是

```python
path.write_text(json.dumps(merged, ...), encoding="utf-8")
```

**原地写，不是原子的。**部署线程每进一步就写一次（七步 + 端口 + 成功），而部署方法
自己最后又 `return self.status()` 读同一个文件。这一次写正好落进那一次读的中途：
读到的是**截断的 JSON**，而 `read_json_file` 是容错的（读不出就返回 `{}`），
`status()` 拿到 `{}` 之后 `state` 不在 `STATES` 里 → 判定 `stopped`。

所以三个证据没一个在说谎：文件后来是完整的（写完就是完整的），凭据也确实设上了，
只有**读的那一刻**文件是半份。

为什么串行跑不犯：串行测试里七步是**同步跑完**的（`inline`），一次写完之后才有人读；
只有真的起线程（那条测试为了「部署还在跑」特意把 inline 关掉）、并且写和读真的交错
起来，窗口才撞得上。跟 xdist 本身没关系，跟「有没有第二个线程」有关系。

## 修法

写临时文件 + `os.replace`（同目录内 rename 是原子的），读侧永远只会看到完整的一份：

```python
tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
payload = devserver.read_json_file(path)   # ← 注意不是 merge_json_file
payload.update(fields)
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
os.replace(tmp, path)
```

**踩坑二连**：第一版我写的是 `payload = devserver.merge_json_file(path)` —— 复用现成
函数看起来更干净，但它自己就把真路径原地写了一遍，rename 只是多此一举，测试照旧红。
要复用「读旧 → 改几个键」的语义，只能复用**读**（`read_json_file`），写必须自己来。

临时文件名带 pid + 线程 id：停止按钮和部署线程可能同时在写，共用一个名字会互相盖掉
对方的临时文件。

## 怎么避免

1. **一个文件被两个线程读写，写就必须是「写临时 + rename」**，不管这份内容多小、
   写得多快。`read_json_file` 这类「读不出来就当空」的容错，会把截断从「报错」变成
   「静默丢状态」——容错越好，越难查。
2. **串行绿、并发红，先找第二个线程，不要先怀疑测试隔离。**判据很便宜：`-n 0` 跑一
   遍，绿了就说明是时序问题不是污染问题，别去翻 fixture。
3. 这种 bug 加测试要**两条一起加**：一条钉做法（必须走 `os.replace`，一次原地写都不
   许有），一条钉症状（轮询线程一边读一边部署，读不出状态就算红）。写完要做**反向
   验证**——把实现改回原地写，两条测试必须都红。实测第二条真能抓到截断
   （`blanks == [None]`），说明这个窗口是真实存在的，不是纸面担忧。
