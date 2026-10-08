# 一个测试里连建两个中文名项目，第二个报的不是名字错而是 `KeyError: 'project'`

## 现象

ACP-2015 第 2 步新写的 `test/test_ai_studio_requirements.py::test_routes_get_requirements`
（`-n 0` 单进程跑）里，第二个 `POST /api/apps/ai-studio/projects` 之后：

```
empty_pid = (await resp.json())["project"]["id"]
E           KeyError: 'project'
```

第一个项目（「设备管理（演示）」）建得好好的，第二个（「空项目」）就拿不到 `project`。
单跑这一条能复现，跑整个文件也只有这一条红。

## 根因（两段，缺一不可）

1. **项目 id 的唯一性只靠秒级时间戳。**
   `projects.create_project` 里 `project_id = f"{fragment}-p{time.strftime('%y%m%d-%H%M%S')}"`
   —— 没有随机后缀，没有毫秒。
2. **中文名的 slug 是空的。** `_slug()` 那条 `_NAME_SAFE` 正则只留 ASCII，
   纯中文名逐字符被换成 `-` 再 `strip("-")`，结果是空串，于是 id 退化成
   纯 `p<秒>`。「设备管理（演示）」和「空项目」**slug 都是空**，同一秒内两次创建
   → 同一个目录 → `docs_dir.mkdir(parents=True, exist_ok=False)` 抛 `FileExistsError`
   → 路由按设计回 **503**（注释里写着「the honest reading … is a retry」），
   响应体是 `{"error":…, "code":…}`，**没有 `project` 键**。

所以测试看到的 `KeyError: 'project'` 和真因隔了两层：**中文名 → 空 slug → 同秒 id
相同 → 目录已存在 → 503**。报错指向「响应形状不对」，实际指向「名字太像」。

## 修法

测试侧改用**能 slug 出东西的 ASCII 名**（`"empty"`），两次创建的 id 天然不同：

```python
# no docs/需求图谱 yet is an empty list, not a 404. The name is ASCII on
# purpose: a pure-CJK name slugs to an empty fragment, so both ids would
# be `p<second>` and the second create inside the same second would
# collide on the directory (a 503 from create_project, not our bug).
resp = await client.post(".../projects", json={"name": "empty", "description": ""})
```

没有去改 `projects.py`：本步的派工单明确禁止改它的现有行为，而且**产品上这不是 bug**
——同秒两个人建同名项目撞到 503，重试就好，返回体里 `code` 说清楚了。测试不该顺手
把生产语义改了。

## 怎么避免

- **同一个测试里连建两个项目，名字给 ASCII 且互不相同**（中文名在这套 id 方案下
  等价于「只剩时间戳」）。要验中文名就单独建一个，别在同秒建第二个
- 撞到 `KeyError: 'project'` 这类**响应形状**错，先把 status 和 body 打出来再看：
  这里 503 + `code` 一眼就能定位，比猜「路由注册坏了吧」快得多
- 想在一个用例里安全地建多个项目，可以直接调 `projects.create_project()` 拿 id，
  绕开 HTTP 层的重试语义；但走 HTTP 才有路由覆盖价值，所以改名字是更划算的那一步
