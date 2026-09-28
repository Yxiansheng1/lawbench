# lawbench — 律师本地 AI 工作台

| 位置 | 内容 |
|---|---|
| `docs/PRD.html`、`docs/Spec.html` | 需求（第三版）和技术方案（第二版）；由 `docs/src/*.md` 生成，改文档改 md 再运行 `python scripts/build_docs.py` |
| `docs/src/业务编排.md` | 五个业务能力的编排 |
| `contracts/` | 契约（接口和数据格式，Spec 第 20 节）；自检 `python contracts/check_examples.py --skills skills` |
| `skills/` | 13 个业务 Skill、共用规则、入口清单、校验脚本；改完运行 `python skills/_scripts/build_skills.py --root skills` |
| `scripts/check_6000d.py` | 检查 6000D 网关、Key 校验和测试 Key |

其余目录（`dsh/`、`dsh-ext/`、`service/`、`prep395/`、`tools/`、`packaging/`、`tests/`）按 Spec 1.4 由开发工单创建。

机密不进仓库：测试 Key 写在 `.env.local`（格式见 `.env.example`），真实案卷一律不放进仓库，测试用虚构样本。
