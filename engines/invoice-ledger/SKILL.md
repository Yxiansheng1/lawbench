---
name: invoice-ledger-db
description: 发票下载、归档、PDF分类统计、图片OCR、查重、台账入账与报销标记。
version: 3.9.4.1
author: 周海沺律师
source: 周海沺律师
agent_created: true
---

# 发票全流程管理

制作者、来源：**周海沺律师**。第三方组件署名及许可独立保留。

> **lawbench 律所内部版**：本目录是律师本地 AI 工作台"发票整理"胶囊的引擎，由工作台服务按白名单调用（Spec 13.3），AI 不直接执行这里的命令。经周海沺律师同意已移除设备授权；工作台内不使用邮箱联网收取（IMAP、MCP、正文链接下载），只处理律师导入的 PDF、ZIP、图片和导出的 EML 文件。

业务数据默认用技能根目录的发票主台账.xlsx（可用 `--ledger` 或 `INVOICE_LEDGER_DIR` 指定）；更新技能不得覆盖用户台账。缺原票的历史记录只能核查内部一致性，不得宣称完成票面核验。

**购买方名称需配置**（技能根目录 `buyer.json` 或环境变量 `INVOICE_BUYER`）；未配置时抬头核验一律判「待核」并提示配置方式，不猜测放行。

收集、购买方核验与纸质贴票流程见 [收集与纸质贴票](references/10-collection-and-paper.md)，优先走 `workflow.py run` 统一入口；`run` 不会自动确认已报。

## 收集前必须确认

每次实际收集前先问用户三件事：①报销年月；②邮件搜索范围（开始日含、结束日不含）；③历史未标已报的票据哪些纳入本期。不得以当前日期、开票日期、邮件日期或“未报”标记代替用户回答；已明确回答的不重复询问。

历史票先导出候选清单再记 plan：不纳入的原处留存，纳入的须给完整票号清单。本期只复制归类，不改写原归档与来源批次，也不自动标记已报。

MCP 渠道按[连接器说明](references/qq-mail-connector.md)接入，可达窗口须实测判定（区分滚动月、30 天、自然月），超出部分列为未覆盖，另用 EML、本地原票或只读 IMAP 补齐；渠道变更须用户确认。详见[年月与历史票安排](references/11-period-and-history.md)。

## 操作前读取

|任务|必读资源|
|---|---|
|来源与分发|[来源与分发](references/09-license-and-provenance.md)|
|导入、统计、查重、标记已报、冲突处理|[当前工作流与门禁](references/08-current-workflow.md)|
|下载邮箱发票|[QQ连接器适用说明](references/qq-mail-connector.md)、[来源模式](references/invoice-sources.md)|
|类别核定|[分类规则](references/invoice_categories.md)、[排序规则](references/sorting_rules.md)|
|环境展开、诊断和迁移|[环境管理](references/05-env-and-deps.md)|

## 命令入口

命令统一用 `python scripts/invoke.py <脚本> <参数>`；Windows AMD64、宿主 Python 3.10+，业务依赖按指纹展开到技能外缓存；中文图片 OCR 另需 Windows 对应语言功能。

|任务|脚本与参数|
|---|---|
|解码附件响应|decode_results.py <工具响应目录> <输出目录>|
|归档附件|archive_files.py <归档目录> --raw <解码目录> --mapping <映射.json>|
|展开ZIP并分类PDF|classify_archived.py <归档目录>|
|导入分类PDF|invoice_db.py import --src <分类目录> --batch <批次>|
|导入图片OCR|invoice_db.py import --src <图片目录> --batch <批次> --img|
|初次建库|invoice_db.py init --src <统计表与原票目录> --batch <批次>|
|体检|invoice_db.py check-schema --ledger <台账目录>|
|报表|invoice_db.py report --ledger <台账目录>|
|标记已报|invoice_db.py mark-reimbursed --batch <批次> --apply|
|冲突裁定|invoice_db.py resolve-conflict --id <冲突ID> --decision <维持台账/采纳新值/剔除> --apply|
|环境诊断|env_check.py --deep --ocr|

## 结果与处理边界

- 同批、跨批均查重；同号异值冻结待裁；待核字段不得猜测补齐；OCR 待人工不计入有效合计。
- 文件统计表是附件口径；本次新增看 `_审计` 的 `new_active_amount`，冲突冻结旧行的金额变化另行核对。
- 退出 0 表示本命令成功，2 表示有重复／冲突／待核／部分失败，须读明细，不视作全量成功。
- 原票、提取结果、审计记录持久保留，发布时排除；不得因升级或清理缓存删除业务证据。
- 发布用 `package_skill.py`，默认不含个人数据，个人迁移加 `--include-ledger`。

沿革：由 invoice-mail-downloader、invoice-pdf-renamer 及 invoice-ledger-db 合并维护；当前规则以 3.9.4 为准，旧参考材料中的案例与验证记录不代替本版验收。
