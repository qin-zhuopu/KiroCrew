# `git push` 到 GitHub 一点输出都没有地挂死：直连不通，要挂代理

## 现象

第 2 步收尾推 fork，同一条命令 `git push fork feature/ACP-2015-v1`：

- 16:38 那次成功，输出正常（`c34de7a38..81ae41221`）
- 16:57 再推第二个提交：**30 秒没动静**，被工具挪到后台；再过 3 分钟仍然是 0 字节输出，
  没有报错、没有进度条、没有 `To https://...`，看着像「还在传」

```
$ cat .kirocrew-dev/push2.txt      # 重定向的文件
0 字节
```

## 根因

直连 GitHub 不通，而 `git` 在 TCP 连接阶段**不超时也不吭声**：

```
$ timeout 8 curl -s -o /dev/null -w '%{http_code}' https://github.com
（无任何输出）退出码 124        # 超时，连 TCP 都没建起来
$ timeout 8 curl -s -o /dev/null -w '%{http_code}' https://clients3.google.com
（同上）124
$ timeout 10 curl -s --proxy socks5://localhost:7777 -o /dev/null -w '%{http_code}' https://github.com
200 用时 5.1s                   # 代理这条路是通的
```

git 侧没有任何代理配置（`git config --get-regexp proxy` 只回 credential helper），
所以它走的是内核路由，直接被吞。表现就是「静默挂住」而不是 `Could not resolve host`。

顺带一个坑：挂住的进程**不会自己退**。两次失败后机器上留着

```
/usr/lib/git-core/git-remote-https fork https://github.com/qin-zhuopu/KiroCrew   # ×2
```

从外面看只是「有个 git 在跑」，容易被误读成「上一次推送还没结束，再等等」。

至于 16:38 那次为什么能成：没有留下任何证据说明当时走的是哪条路（没记环境），
本机出口本身也在变。**不要把「上一次直连成功」当成规律**，推送前先探一次。

## 修法

```bash
# 1. 先探直连（8 秒不通就别硬试）
timeout 8 curl -s -o /dev/null -w '%{http_code}\n' https://github.com || echo 直连不通

# 2. 清掉挂住的旧连接，否则会一直误判「还在推」
pkill -f "git-remote-https fork"

# 3. 挂代理推，输出重定向到文件，后台跑（推送输出可能长，且前台不该干等）
ALL_PROXY=socks5://localhost:7777 timeout 120 git -C <仓库> push fork <分支> > .kirocrew-dev/push.txt 2>&1

# 4. 只认这两处实证，不要凭「命令返回 0」下结论
cat .kirocrew-dev/push.txt          # 要有 81ae41221..dfae699a0 这行
git -C <仓库> log --oneline fork/<分支>..HEAD | grep -c .   # 0 = 真同步了
```

实测：清完旧进程 + 挂代理，同一条命令几秒完成（`81ae41221..dfae699a0`）。

## 怎么避免

- **推 GitHub 前 `timeout 8 curl -s https://github.com` 探一下**，不通就直接挂
  `ALL_PROXY=socks5://localhost:7777`，别用「上次能直连」当依据
- **推送一律重定向到文件 + 后台跑**，判成功看文件里的 `旧hash..新hash` 那行，
  或跑 `git log @{u}..HEAD` 数差值；「命令没报错」不等于推上去了
- **重试前先 `pkill -f "git-remote-https <remote名>"`**：残留连接会让下一轮判断全错
- 内网仓库（内网 GitLab/Bitbucket、内网 npm/nexus）**一律直连，不挂代理**——
  代理只用于国外源；判定顺序永远是先内网/国内镜像，再国外直连，最后才代理
