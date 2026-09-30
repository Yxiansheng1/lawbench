# 395 部署步骤（Spec 6.1；工单 T11）

甲方运维可照做。标"用户"的步骤需要在 395 上以管理员身份亲手操作（AI 不保存、不索要 395 的密码）。开发机上的仓库是 `D:\lawbench-C`，395 上的程序目录是 `C:\prep395\`。

## 0. 已知情况

- 395：`192.168.8.124`，Windows 11 专业版；Radeon 8060S，Vulkan 可用；**专用 GPU 内存 95.8 GB**（用户 2026-09-29 读数，`OWNER-395专用GPU内存-20260929-1828.md`）。
- 可访问 GitHub、hf-mirror.com、ModelScope、PyPI；huggingface.co 不通。
- EasyTier 已装，虚拟 IP `10.126.126.3`，已有防火墙规则 `EasyTier-9000-In`。

## 1. 准备文件（用户，在 395 上）

建目录 `C:\prep395\`，放入：

| 位置 | 内容 | 来源 |
|---|---|---|
| `llama\` | llama.cpp 的 Windows Vulkan 版发布包解压后的全部文件（含 `llama-server.exe`），记下版本号 | GitHub releases，文件名形如 `llama-bXXXX-bin-win-vulkan-x64.zip` |
| `models\` | OCR 视觉模型 GGUF（及其 `mmproj` 文件）、9B 模型 GGUF | hf-mirror.com 或 ModelScope；模型选型见 T11 的 `g5-g6.md`，许可证逐个核对（不用 AGPL、不用禁止商用的） |
| `python\` | 独立的 Python 3.12（python-build-standalone 的 `install_only` 包解压，或官方 embeddable 包并启用 pip） | python.org / GitHub |
| `winsw\WinSW-x64.exe` | WinSW（MIT） | GitHub releases |
| `src\prep395\` | 仓库 `prep395\` 目录整个复制过来（含 `pyproject.toml`、`prep395\`、`deploy\`） | 本仓库 |

## 2. 安装（用户，管理员 PowerShell）

先生成 `/admin` 口令的摘要（口令须为 16 位以上随机强口令，只在局域网内使用；不要写进任何文件）：

```powershell
$p = Read-Host -AsSecureString "管理员口令"
$plain = [Runtime.InteropServices.Marshal]::PtrToStringUni([Runtime.InteropServices.Marshal]::SecureStringToBSTR($p))
$hash = -join ([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($plain)) | ForEach-Object { $_.ToString("x2") })
```

然后：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\prep395\src\prep395\deploy\install.ps1 `
  -LanIp 192.168.8.124 -OcrModel <OCR模型.gguf> -OcrMmproj <mmproj.gguf> -LlmModel <9B模型.gguf> `
  -OcrParallel 2 -AdminUser admin -AdminPassSha256 $hash
```

`install.ps1` 做的事：

1. 检查上面的文件都在；把 `prep395` 装进 `C:\prep395\python\`。
2. 建本地低权限账号 `prep395svc`（密码由脚本随机生成、只用一次，不显示、不保存），授予"作为服务登录"。
3. 权限：`C:\prep395\` 去掉继承，只留 Administrators、SYSTEM 完全控制和 `prep395svc` 读取执行；`logs\`、`tmp\` 给 `prep395svc` 修改权限。
4. 在 `C:\prep395\services\` 写三个 WinSW 服务定义并注册：`prep395-ocr`（llama-server，127.0.0.1:9101）、`prep395-llm9b`（llama-server，127.0.0.1:9102）、`prep395`（`python -m prep395`，监听 `<LanIp>:9000`，后端 `llama`，依赖前两个）。开机自启，崩溃后 10 / 30 / 60 秒重启；WinSW 自身不写日志（`<log mode="none"/>`）；llama-server 不开 `--verbose`、`--log-file`，加 `--log-disable`、`--no-webui`。
5. 调 `firewall.ps1`：入站只放行 TCP 9000，来源 `192.168.8.0/24` 和 `10.126.126.0/24`；9101、9102 显式阻止。
6. `powercfg /h off` 关闭休眠。
7. 启动三个服务并访问 `/health`。

llama-server 的参数名随版本变化；装完后用 `C:\prep395\llama\llama-server.exe --help` 核对 `--log-disable`、`--no-webui`、`-np` 是否存在，不存在就在 `install.ps1` 里去掉后重跑。

**不由脚本处理**（按候 owner 清单的决定执行，未决定前不动）：BitLocker。

**向日葵**（用户 2026-09-30 决定：保留，关掉开机自启）：395 是律所的电脑，向日葵保留。由用户或律所的人在 395 上把向日葵设为**不开机自启**，需要远程维护时临时打开、用完关闭。部署脚本不操作向日葵。**风险告知**：395 装有向日葵，它运行期间，这台机器存在经厂商公网服务器中转被远程控制的可能；395 的识别服务处理完即返回、不在硬盘上留存扫描内容，但运行中的请求仍可能被看到。律所知悉此风险并由律所承担。

## 3. 验收（开发机 + 395）

```powershell
# 开发机
python scripts\check_395_reach.py 192.168.8.124      # 9000 通，9101 / 9102 不通，/health 为 ok
python acceptance\sec\dewatermark_395.py              # 一次真实识别（用测试 Key），印章、批注不被去除
python acceptance\sec\port_scan.py --target 所内
# 395（管理员）
powershell -NoProfile -ExecutionPolicy Bypass -File <仓库>\scripts\probe_395.ps1   # 休眠不可用、9000 被 prep395 占用
Restart-Computer                                     # 重启后 Get-Service prep395* 三个都在运行
```

残留检查按 `acceptance\manual\395残留检查.md`。

G-5 / G-6 实测（选模型、定并发数 N 之后，或换模型时）：在开发机上运行

```powershell
python prep395\deploy\bench_g5g6.py --base http://192.168.8.124:9000 --pages 20
```

它用讯问笔录的 3 页扫描件加现造的 20 页虚构扫描页（一半带水印），量每页耗时、并发 1 / 2 / 3 的吞吐、字符相似度、姓名 / 日期 / 金额 / 证件号的命中率，以及 9B 抽取的值能否在所标页原样找到；结果写 `docs\plan\evidence\T11\g5-g6.md`（只有数字，不含识别出的正文）。已在开发机上对测试后端跑通过。

## 4. 卸载

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\prep395\src\prep395\deploy\uninstall.ps1   # 加 -RemoveAccount 同时删账号
```
