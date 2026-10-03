# T14 第二次实跑派修 · 测试连接的 Key 判定与耗时读数（线 B，`23fc350`，T3）· 主编排亲核记录

- 来件：`致ORCH-B-交回-Key校验判定-1756.md`；target → main cherry-pick `3600d0c`
- 落件时刻：2026-10-03 18:02 (+08:00)
- 改动：`api\ui.py` +26/−12（真 Key 200 时再发一次随机无效 Key：被拒→true；也 200→null 并提示"网关当前未校验 Key，无法确认 Key 是否正确"；其他→null）；`perf_counter` 向上取整修"0 毫秒"；假 6000D 加 `valid_keys` 模式；三态用例。契约未改（null 已允许）；无效 Key 不进日志（读代码核）。
- 测试：main 上 `test_api_case -k connection` 6 passed；我把"假 Key 回 200 也算有效"改回去 → 1 红；复原干净。
- 界面侧：Host 首次配置判定 `key_valid !== false`，null 不挡——T14 第三次实跑时核显示文字。
- **通过。**