# 线 C 服务端"独立后续"清扫（令 20261002-2140）· 主编排亲核记录

- 复核人：主编排（ORCH）；用户已回话
- 来件：`致ORCH-C-交回-独立后续清扫-2200.md`
- target：line-C `9cf94a6`（T12）、`ac542ec`（T25）→ cherry-pick 到 main `866ee9a`、`cf752c2`
- 落件时刻：2026-10-02 22:28 (+08:00)
- 分级：来源均为既往复核记录的 P3/NOTE 小项，产品代码改动 3 行 + 2 行，按"PASS 后小项"口径主编排亲核

## 核过
| 项 | 结果 |
|---|---|
| 改动面 | `ocr\queue.py` submit 3 行（395 已连不上时新任务直接记 paused/prep_down，由探测线程放回）；`invoice\runner.py` 2 行（购买方副本读不到批次记录/清单时记 `buyer_copy_read:<类名>`，不含内容）；用例 +80 行；证据与交付说明 |
| 契约 | `ocr_jobs.status/pause_reason` 取值在契约枚举内（paused / prep_down 已有）；日志只记元数据 |
| 测试 | main 上 ocr_queue + invoice + pipeline **179 passed**（线 C 报 108 + 83） |
| 变异（我自己做） | 去掉"连不上即 paused"→ 1 红；去掉日志行 → 3 红；复原后 `git status` 干净 |
| 抖动修复 | `test_buyer_copy_write_failure_returns_original`：假引擎 utime 推后 5 秒，线 C 报原 HEAD 3 跑 2 失败、改后 10 跑全过——合理 |
| 未动清单 | 线 C 按五类（已修好 / 价值太低 / 复核员判无害 / 已定已知限制 / 要改契约或全项目口径 / 要真机或用户）逐条列了理由，核对无误；无遗漏需我派的 |

## 结论
**通过。** 进 main。