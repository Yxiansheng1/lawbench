# 线 B T18 计量工具（`1227306`）与线 C 395 运维两坑（`894704f`、`d7bd596`）· 主编排亲核记录

- 复核人：主编排（ORCH）；用户在场
- 来件：`致ORCH-B-交回-T18计量工具-1421.md`、`致ORCH-C-交回-395运维两坑-1440.md`
- target → main：cherry-pick 三提交，末为 `182b5db`
- 落件时刻：2026-10-03 14:27 (+08:00)
- 分级：联调/运维工具与文档，无产品代码改动（`service\lawbench`、`prep395`、`contracts`、`engines` diff 为空），主编排亲核

## 核过
| 项 | 结果 |
|---|---|
| 机密 / 用户名 | 全部新增文件扫 Key 片段、密钥赋值、本机用户名：0 命中；`install_service_395.ps1` 密钥走 Read-Host 隐藏输入，脚本内无值 |
| T18 `t18_budget.py` | `--selftest` 12 项过；读代码核实只取 DSH 会话事件的 type/time/tool name，不读 arguments 与正文（第 14、92 行）；线 B 发现服务日志无 task_id/工具名，只能作旁证——如实记入 T18 口径 |
| T27 `check_servers.py` | 主编排实跑：四项全部通过（395 所内/所外 /health ok 契约 1.3、6000D 两路 /v1/models 200） |
| T27 三个 ps1 | PowerShell 解析器 0 错；用 EasyTier 2.6.4 自带 `service install`（依据 help 原文存证），默认自启与失败重启；**未在 395 上跑过**，首次运行以 `check_service_395.ps1` 结果为准 |
| T11 两份操作单 | 两条铁律在；网关/DNS 注明"按现场核对"；DHCP 地址保留一节在；395 关 WLAN 建议在 |
| 线 C 顺手发现 | **开发机"以太网"网卡被手动配了 192.168.8.124（Tentative）**——用户 10-03 中午改 IP 时命令跑在了本机。已请用户在本机改回 DHCP；主编排不动用户电脑网络设置 |

## 结论
**三件均通过。** 进 main。