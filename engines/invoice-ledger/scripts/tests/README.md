# 当前测试

- test_integrity_v38.py：独立合成规则及签名正反例，不依赖真实台账。
- ocr_acceptance.py：生成合成图片，验证Windows真实OCR与人工待核状态；需要中文OCR系统能力。
- env_acceptance.py：在临时副本测试冷启动、缓存损坏、升级同步与分发排除；（lawbench 版已移除设备授权，不再需要许可证。）

统一以 `python scripts/invoke.py tests/<文件名>` 运行。后两项需要现有台账，执行仅修改临时副本。旧批次测试依赖已删除的私人原票，已转移到维护者外部历史档案，不计为当前通过项。

- test_workflow_v39.py：固定购买方、OCR格式、邮件附件/链接枚举、ZIP仅选PDF及完整性状态的合成回归。
