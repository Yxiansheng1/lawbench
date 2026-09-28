---
name: litigation-retainer-generator-offline
version: 3.4.1
craft-toolchain: rust+go
craft-source: skill-crafting
description: 完整离线诉讼委托材料工具，双击启动.html，支持案件表单、Excel逐案导入、13份Word模板（按主体分 个人委托/公司委托/刑事 三组，合同第六条收费条款按 固定/半风险/全风险 自动注入）生成与维护、工作包备份和本地自检。
---

# 离线诉讼委托材料工具

双击 `启动.html` 使用。浏览器业务运行只需要本文件夹，不依赖技能执行环境、Python、命令行或网络。

| 任务/产出物 | 策略 | 方法 | 模板/实操 | 规范 | 衔接 |
| --- | --- | --- | --- | --- | --- |
| 案件文书与目录 | 使用说明.md | app/core.js | resources/templates/ | data/config.json | app/ui.js |
| Excel案件录入 | 使用说明.md | app/excel.js | 标准案件录入.xlsx | data/config.json | 案件录入页面 |
| 模板维护 | docs/能力迁移对照.md | app/core.js | data/rules.json | 使用说明.md | 模板处理工具页面 |
| 本地备份 | 使用说明.md | app/packages.js | 工作包与资源包 | docs/验收报告.md | 保存与资源页面 |
| 构建与验证 | docs/架构审查.md | tools/build.go | tests/ | CHANGELOG.md | Rust verify / Go stamp / package |

起草时阅读使用说明并核对案件；重写时重新核对全部案件字段与所选模板；修订时核对受影响字段并重新生成。版本不一致的资源包由校验器拒绝。

原技能全部文件存档在 original-skill，迁移关系详见 docs/能力迁移对照.md，验收证据与未核销项目详见 docs/验收报告.md。源码备份用于追溯，运行能力由 app 中 JavaScript 提供。
