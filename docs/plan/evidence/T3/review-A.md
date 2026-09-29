# T3 复核记录 · Reviewer A（改动纪律与可维护性）

- 复核员：主编排派出的子代理，Opus 5.5 · high，只读
- target：base `5c08a61`（main），head `c444d6ae39adcbed751b14a8c5c347632d40b367`（line-B）；提交 `5864fc1`、`190c255`、`c444d6a`；28 个文件，+3246 行
- 复核位置：主编排临时目录里的克隆（分离 HEAD），没有动 `D:\lawbench-B`
- 时间：2026-09-29 19:25–19:31
- 本文件由主编排据复核员的最终报告整理，发现、证据和结论未作删改，只调整了排版

## Verdict：AMEND

## 要求的行为（复核员的一句话）

在 `service\` 里起一个只监听 127.0.0.1、要令牌的 Python 工作台服务：7 个界面接口全部按契约校验；Spec 4.2 六条规则的路径闸门；只连设置里两台服务器的统一 HTTP 客户端（先试所内、不通再试所外，缓存 60 秒）；只放行两个路径的本机转发；日志只记元数据。

## Findings

### P1-1 设置文件或胶囊文件坏了，整个服务起不来，"恢复默认"接口也够不着

- 问题：`create_app()` 启动时同步调用 `st.settings.get()`（`app.py:47`）和 `st.capsules.ensure()`（`app.py:50`）。遇到 `v != 1` 抛 `ApiError("INTERNAL")`（`settings.py:47-48`、`capsules.py:45-46`），JSON 损坏抛 `JSONDecodeError`，异常冒出 `create_app`，进程退出。
- 影响：Host 按 Spec 1.3 连续重启 3 次后放弃；案件打开、设置、`/api/capsules/reset` 全部不可用，律师只能手工删 `%APPDATA%` 里的文件。运行时 GET `/api/settings` 读到不认识的 `v` 返回 HTTP 200 + `INTERNAL`，而 Spec 20.1 规定内部异常用 HTTP 500。
- 违反的不变量：Spec 20.1"落盘的 JSON 文件带 `"v": 1`，读到不认识的 `v` 时只读、不写"。
- 证据：探针脚本输出
  ```
  capsules v=2 -> STARTUP FAILED: ApiError INTERNAL
  capsules bad json -> STARTUP FAILED: JSONDecodeError
  settings v=2 -> STARTUP FAILED: ApiError INTERNAL
  cases v=2 -> started OK
  ```
  没有测试覆盖这条路径。
- 最小修复：`capsules.ensure()` 的异常只按类名记日志、不阻断启动；`settings.get()` 失败时 `Net` 用 `DEFAULTS["servers"]` 初始化，接口照常返回错误。补 2 个测试：坏 `capsules.json`、坏 `settings.json` 时 `/health` 仍 200，且 `/api/capsules/reset` 能恢复。

### P2-1 投机性的生产代码，删掉后没有任何验收会失败，且都没有测试

- `CaseRegistry.root_of`（`registry.py:89-94`）：全仓零调用。
- `gate.resolve_internal`（`gate.py:226-229`）：零调用、零测试。
- `CaseRegistry._upgrade`（`registry.py:151-163`）：当前 `SCHEMA_VERSION="1"`，升级路径走不到；含备份和重跑建表脚本，没有测试。
- `ApiError.reason`（`errors.py:42`）：约 20 处 raise 传了原因代号，没有任何地方读它；`on_api_error` 只记 `exc.code`（`app.py:69`）。
- `Net.close()`、`Net.invalidate(None)` 清空全部缓存的分支：生产代码没用到。
- 违反的不变量：工单 T3 的步骤和验收不含 case.db 升级、按 case_id 取根目录、内部读接口。
- 最小修复：删掉 `root_of`、`resolve_internal`、`_upgrade`（连同 `registry.py:137-139` 的版本比较分支）和 `Net.close`；`ApiError.reason` 二选一：在 `on_api_error` 里记成 `error=f"{code}:{reason}"`（原因都是固定代号），或删掉这个参数。

### P3-1 胶囊的工具白名单写了两份

`capsules.py:16` 的 `TOOLS` 和第 84 行的 `unknown_tool` 分支，与契约 `skill/capsules.schema.json` 的 `tool.enum` 重复；请求先过契约校验就被拒（`ui.py:43`），这个分支走不到。证据：探针 `contract rejects unknown tool before _check: True`；`redgreen.txt` 第 [19] 项改坏 `capsules.py` 后 `_bad_unknown_tool`、`_bad_custom_tool` 没有变红。最小修复：删掉 `TOOLS` 和对应分支，或在测试注释里写明由契约拦截。

### P3-2 走不到或静默吞掉问题的防御分支

- `net.py:198-200`：`if op is None: return 404` 走不到；`_FORWARD_ROUTES` 与 Route 列表重复声明。
- `net.py:81`：`response.is_redirect or 300 <= status < 400`，前半句多余。
- `logs.py:43-44`：状态值不认识就静默改成 `"fail"`，会掩盖编程错误。

### P3-3 转发端口占用、钥匙串读取失败，被转成"看起来正常"

- `__main__.py:42-46`：`run_forward` 吞掉 `OSError` / `SystemExit`。转发端口被占用时 `/health` 仍报 ok，Host 不会重启，而 Agent 的模型请求整条链是断的。没有测试。
- `app.py:27-34`：keyring 读取出现任何异常都返回 `None`，"测试连接"把读取故障误报成"没设 Key"。
- 最小修复：转发端口监听失败时让进程退出，交给 Host 按 Spec 1.3 处理，或至少补测试钉住当前行为并列为待主编排定；keyring 读取异常时提示改成"Key 暂时无法验证"。

### P3-4 重复的事实源没有同步检查

`errors.MESSAGES`（抄 Spec 20.1 和契约错误码枚举）、`settings.DEFAULTS`（抄 `contracts/examples/file_settings.json`）、`registry.TEMPLATES`（抄 formats.md 1.1）。复核员核对目前全部一致（错误码 26 对 26），但没有测试守着。最小修复：加一个测试断言 `set(MESSAGES) == enum` 且 `DEFAULTS == file_settings.json`。

### NOTE

- `pyproject.toml` 声明了 `fastapi`、`pyyaml`，代码里没有 import（服务直接用 Starlette）。工单步骤 1 点名要这些依赖，不算作者的问题。
- `LB_SKILLS_DIRS`、`LB_CONTRACTS_DIR`、`LB_VALIDATE_RESPONSES` 超出工单规定的环境变量，有 Spec 10.1、20.11 依据，交付说明已披露；`validate_responses=False` 分支没有测试。
- 交付说明第 5 节列的 10 条"待 ORCH 定"与代码一致。
- `redgreen.py` 原地改写源码再复原，属证据工具，可以保留。

## 八项清单

| # | 项 | 结论 |
|---|---|---|
| 1 | 契约一致 | 通过。没改契约；每个返回都在测试里按 `$defs/response` 校验；错误码 26 对 26 |
| 2 | 边界输入 | 通过。缺口：3 个符号链接用例本机跳过 |
| 3 | 错误路径 | **不通过**（P1-1；另有 P3-3 两处静默降级） |
| 4 | 日志不含正文 | 通过 |
| 5 | 路径闸门未被绕过 | 通过（本卡范围内）。案件目录内的写入都经过 `mkdir_work`、`mkdir_original`、`resolve_write` |
| 6 | 无外连 | 通过。白名单钩子、`follow_redirects=False`、`trust_env=False`；测试只连 127.0.0.1 或走 MockTransport |
| 7 | 测试覆盖新代码 | 部分。未覆盖：`_upgrade`、`root_of`、`resolve_internal`、`validate_responses=False`、转发端口监听失败、keyring 异常、`TOOLS` 分支、应用数据文件坏了再启动 |
| 8 | 无机密入库 | 通过 |

## 复核员实际跑过的

- `git rev-parse HEAD` = `c444d6a…`；`merge-base --is-ancestor 5c08a61 HEAD` 退出码 0。
- `import lawbench` 指向克隆里的路径，没有落到线 B 的施工目录。
- `python -m pytest -q -rs -p no:cacheprovider`：**165 passed, 3 skipped, 1 warning，114 秒，退出码 0**。
- 探针脚本（应用数据用临时目录，不落文件）：P1-1、P3-1。
- 用契约核对重复事实源；在 diff 里扫 URL 和机密模式；搜投机符号的调用方。

## 证据缺口

- 3 个符号链接用例（`test_gate.py:117/124/199`）本机没有权限，未实测；junction 变体都跑通，只能算静态推断。
- 没有在真实 6000D、395 上验证（不在复核范围）。
- 没有复跑 `redgreen.py`（它会改写源码），只读了它的产物。
