# contracts/ — 契约 1.2

模块之间约定好、谁都不能单方面改的接口和数据格式。说明见 Spec 第 20 节。

| 目录 / 文件 | 内容 | Spec |
|---|---|---|
| `common.schema.json` | 编号、时间、错误体、出处、位置、参数、核对结果、覆盖清单等共用类型 | 20.1、20.2 |
| `core/` | Agent 插件 → 工作台服务 `/core/*` | 20.3 |
| `tools/` | AI 工具 `case_*` 的参数（`$defs/args`）和返回（`$defs/result`）；1.1 新增刑期计算、归档匹配、归档方案 | 20.4 |
| `api/` | 界面 → 工作台服务 `/api/*` 的请求（`$defs/request`）和返回（`$defs/response`）；1.1 新增导入、胶囊、归档生成、发票、委托材料驱动 | 20.5 |
| `prep395/` | 工作台服务 → 395 | 20.6 |
| `files/` | 案件目录和应用数据目录中的 JSON 文件 | 20.8 |
| `case_db.sql` | `工作区/case.db` 表结构 | 20.8 |
| `formats.md` | 目录树（含标准案件目录、日常办公文件夹、归档文件夹）、材料文本、出处、wiki、草稿、流水线提示词等文本格式 | 20.8、20.9 |
| `skill/` | SKILL.md 头部、胶囊配置（替代 1.0 的入口清单）、归档目录 | 20.10 |
| `examples/` | 每个主要契约的样例（含应当校验失败的反例），`manifest.json` 列出对应关系 | 20.11 |
| `_build/` | `gen_schemas.py` 生成全部 `*.schema.json`，`gen_examples.py` 生成样例；改契约改这里 | 20.1 |
| `check_examples.py` | 契约自检：`python contracts/check_examples.py --skills <Skill 根目录>` | 20.11 |

规则：
1. 改契约 = 改 `_build/gen_schemas.py` 并运行 + 升 `VERSION` + 在 Spec 20.12 记一行；不手改生成的 `*.schema.json`，不许只改代码。
2. Python 用 `jsonschema`（Draft 2020-12）、TypeScript 用 `ajv`（`ajv/dist/2020`）校验同一份文件；类型可以由 schema 生成，但不许手写一份和 schema 不一致的类型。
3. 所有 `$id` 以 `lawbench://contracts/` 开头，引用一律用完整 `$id`，校验时先把整个目录注册进去（见 `check_examples.py` 的 `registry()`）。
