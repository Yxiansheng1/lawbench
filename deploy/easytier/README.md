# 所外访问（EasyTier）部署记录

依据：甲方《EasyTier 律所工作台远程接入方案 V2》；Spec 第 15 节；编排计划工单 T27。
**本目录不放任何密钥**：网络密钥、私钥、服务器密码只写存放位置。

## 1. 现状（2026-09-29 实测）

| 节点 | 机器 | 虚拟 IP | 版本 | 运行方式 | 代理的地址 | 端口白名单 |
|---|---|---|---|---|---|---|
| relay | 阿里云 `47.107.140.75`（律所提供） | 无（不加入网络，只做见面和中转） | 2.6.4 | systemd `easytier-relay.service` | — | — |
| firm-gw | 6000D `192.168.8.77`（Ubuntu） | `10.126.126.1` | 2.6.4 | systemd `easytier-gw.service`，开机自启 | 不代理 | TCP 8000 |
| node-395 | 395 `192.168.8.124`（Windows 11） | `10.126.126.3` | 2.6.4 | 9-29 记为 Windows 服务 `easytier`、自动启动；10-03 停电恢复后实际是否自启**未查清**（见第 6 节，改用 `easytier-cli service install` 重装） | 不代理 | TCP 9000；Windows 防火墙规则 `EasyTier-9000-In` 只允许 `10.126.126.0/24` 访问 9000 |

- 网络名：`lawbench`。
- 访问地址：**所内**用局域网地址（6000D `http://192.168.8.77:8000`，395 `http://192.168.8.124:9000`）；**所外**用虚拟 IP（`http://10.126.126.1:8000`、`http://10.126.126.3:9000`）。客户端设置里两套地址都填，先连所内地址、连不上自动改连所外地址（Spec 第 15 节）。
- **不使用子网代理（`-n`）**：2026-09-29 实测，经子网代理进来的访问不受 `--tcp-whitelist` 限制（所外能连到 6000D 的 22 等全部端口），与甲方方案 V2"本方案不用 `-n`"一致，已去掉。
- 6000D 与 395 之间直连（DIRECT）。395 的 NAT 类型为 Symmetric，所外电脑与它打洞不成功时经阿里云中转；中转节点不持有网络密钥，只能看到密文。

## 2. 各节点启动参数（密钥已去掉）

relay（`/etc/systemd/system/easytier-relay.service`）：
```
/usr/local/bin/easytier-core -l tcp://0.0.0.0:11010 -l udp://0.0.0.0:11010 --relay-network-whitelist lawbench --hostname relay
```

firm-gw（`/etc/systemd/system/easytier-gw.service`；密钥在 `/etc/easytier.secret`）：
```
/usr/local/bin/easytier-core --network-name lawbench --network-secret "$(cat /etc/easytier.secret)" -i 10.126.126.1 -l udp://0.0.0.0:11010 -p tcp://47.107.140.75:11010 --hostname firm-gw --tcp-whitelist 8000
```

node-395（Windows 服务 `easytier`，程序在 `C:\EasyTier\`；密钥目前写在服务参数里）：
```
C:\EasyTier\easytier-core.exe --network-name lawbench --network-secret <密钥> -i 10.126.126.3 -l udp://0.0.0.0:11010 -p tcp://47.107.140.75:11010 --hostname node-395 --tcp-whitelist 9000
```

## 3. 变更记录

| 日期 | 节点 | 改动 | 回退方法 |
|---|---|---|---|
| 2026-09-29 | firm-gw | 加 `--tcp-whitelist 8000` | `sudo sed -i 's| --tcp-whitelist 8000||' /etc/systemd/system/easytier-gw.service && sudo systemctl daemon-reload && sudo systemctl restart easytier-gw` |
| 2026-09-29 | node-395 | 加 `-n 192.168.8.124/32` 和 `--tcp-whitelist 9000` | 用 `sc.exe config easytier binPath= "<去掉这两项的原命令>"` 后 `Restart-Service easytier` |
| 2026-09-29 | firm-gw、node-395 | 实测发现经子网代理的访问绕过白名单，两台都去掉 `-n`；所外改用虚拟 IP | 需要恢复时把 `-n <本机地址>/32` 加回启动参数（不建议） |
| 2026-09-29 | node-395 | Windows 防火墙新增入站规则 `EasyTier-9000-In`：TCP 9000，来源 `10.126.126.0/24` | `Remove-NetFirewallRule -DisplayName "EasyTier-9000-In"` |

## 4. 验收（T27）

在**律所外的网络**（手机热点）上，用一台已加入 `lawbench` 网络的笔记本运行：
```
python deploy\easytier\check_remote.py --save docs\plan\evidence\T27\remote-check.txt
```
通过标准：`10.126.126.1:8000` 可连通且 `/v1/models` 返回 200；`10.126.126.3:9000` 可连通且 `/health` 返回 200（T11 已部署，2026-10-02 起是必过项）；两台虚拟 IP 上的 22、3389 等其他端口全部不通；局域网地址 `192.168.8.x` 从所外不可达。结果用 `--save` 直接存到 `docs\plan\evidence\T27\remote-check.txt`。上线前的完整操作见同目录 `操作单-上线前.md`。

## 5. 上线前还要做的（换正式密钥时一次做完，只停网一次）

1. **换正式密钥**：测试密钥已在聊天记录中出现过。生成 32 位以上随机密钥；6000D 写入 `/etc/easytier.secret`（权限 600）；395 改为从只有管理员可读的配置文件读取，不再写在服务参数里。
2. **加固中转节点**（方案 V2 的 G-1 至 G-5）：三台都加 `--secure-mode true`；中转节点用固定私钥 `--local-private-key`（私钥只存律所的密码管理器）；按方案决定中转节点是否加入 `lawbench` 并开 `--private-mode true`、`--relay-all-peer-rpc`。这几项要三台同时改、并先在测试时间窗验证，改前准备好第 3 节的回退命令。
3. **律师电脑接入**：按方案 V2 为每位律师发放单独凭据，不分发主密钥。
4. 改完重跑第 4 节的检查。

## 6. 395 服务化与检查（2026-10-03，停电后补）

- `install_service_395.ps1`：用 EasyTier 2.6.4 自带的 `easytier-cli service install`（依据：`docs\plan\evidence\T27\easytier-service-help.txt`，默认开机自启、失败自动重启）把 easytier-core 装成服务 `easytier`，参数只有 `--config-file C:\EasyTier\lawbench.toml`（只有管理员可读，脚本里不写密钥）；另用 `sc.exe` 明确设自动启动和失败重启。没选 WinSW：EasyTier 自带、版本支持、少一层包装。
- `check_service_395.ps1`（只读）：服务在、在跑、自启、失败重启、命令行无密钥、配置文件只有管理员可读、`et_*` 网卡上有 `10.126.126.3`、经虚拟网能到 6000D:8000、局域网地址 `.124` 是静态。
- `uninstall_service_395.ps1`：回退，按安装时的备份恢复原来的服务定义或手动进程。
- 用户在 395 上的完整步骤：`deploy\操作单-395停电后恢复.md`；固定 IP：`deploy\操作单-服务器固定IP.md`。
- 两台服务器一键检查（开发机）：`python deploy\check_servers.py`。
