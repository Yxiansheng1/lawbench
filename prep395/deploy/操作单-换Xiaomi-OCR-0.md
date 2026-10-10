# 操作单 · 395 的识别模型换成 Xiaomi-OCR-0（可随时回退到 PaddleOCR-VL）

用户 2026-10-10 定：识别模型先换成 Xiaomi-OCR-0，部署在 395，不动 6000D。模型的核实记录在 `docs\plan\evidence\T11\模型候选.md` 第七节。
本单在 **395 上以管理员身份的 PowerShell** 里做，SSH 进去或坐在机器前都行，约 15 分钟。期间识别服务会中断一两分钟；6000D 上的推理不受影响。
**本单不涉及任何密钥**：管理口令沿用现有服务里已存的摘要，不用重新输入。

## 0. 记下现状（回退用）

```powershell
$svc = "C:\prep395\services"
$bak = "$svc\backup-$(Get-Date -Format yyyyMMdd-HHmm)"
New-Item -ItemType Directory $bak | Out-Null
Copy-Item "$svc\prep395*.xml" $bak
([xml](Get-Content "$bak\prep395-ocr.xml")).service.arguments
# 预期：一行 llama-server 参数，里面有 -m "...\models\<现在的 OCR 模型>.gguf" --mmproj "...\<现在的 mmproj>.gguf" ... -c <数字>
# 把这一行抄下来：回退时要用里面的两个文件名
& C:\prep395\llama\llama-server.exe --version
# 预期：version: 11269 (...)。Qwen3.5 系列 2026 年 2–3 月起就被支持，这个版本按理够用
```

## 1. 下载两个文件并核对 sha256

来源是社区 GGUF 仓库 `prithivMLmods/Xiaomi-OCR-0-GGUF`，Apache-2.0，走 hf-mirror。395 能上外网就直接下：

```powershell
cd C:\prep395\models
curl.exe -L -o Xiaomi-OCR-0.BF16.gguf        https://hf-mirror.com/prithivMLmods/Xiaomi-OCR-0-GGUF/resolve/main/Xiaomi-OCR-0.BF16.gguf
curl.exe -L -o Xiaomi-OCR-0.mmproj-bf16.gguf https://hf-mirror.com/prithivMLmods/Xiaomi-OCR-0-GGUF/resolve/main/Xiaomi-OCR-0.mmproj-bf16.gguf
```

395 上不了外网的话：在开发机上用同样两条命令下载，再用 U 盘或 `scp` 拷到 `C:\prep395\models\`。

```powershell
Get-FileHash Xiaomi-OCR-0.BF16.gguf, Xiaomi-OCR-0.mmproj-bf16.gguf -Algorithm SHA256 | Format-Table Hash, @{n='Size';e={(Get-Item $_.Path).Length}}, Path
```

**预期（必须逐字符一致，不一致就删掉重下，不要继续）：**

| 文件 | 大小（字节） | SHA256 |
|---|---|---|
| `Xiaomi-OCR-0.BF16.gguf` | 1516744960 | `D796FA2CD211BA39A40F37691FC0046AA49F59C7968EC844EB9E81F2AE476A52` |
| `Xiaomi-OCR-0.mmproj-bf16.gguf` | 207346624 | `634D6BC95781EBF4A3F06570A59859FA5082D488DB540FD474BC6B4061AEC90E` |

## 2. 把新的 prep395 源码拷到 395

新代码会按模型名选提示词：模型名里带 xiaomi 时，用模型卡规定的那句提示词；否则用原来的提示词。
把开发机仓库（main）里的 `prep395\` 整个目录覆盖到 395 的 `C:\prep395\src\prep395\`，方法和 9-30 部署时一样，不要开临时网页服务。

```powershell
Select-String -Path C:\prep395\src\prep395\prep395\backends.py -Pattern "XIAOMI_OCR_PROMPT" | Select-Object -First 1
# 预期：有一行输出（说明拷过来的是新代码）
```

## 3. 换模型：带新模型名重跑 install.ps1

其余参数从现有服务定义里读，不用手抄，也不用重新输入口令。

```powershell
# 自检：第 2 步的新源码必须已经拷到位。旧的 install.ps1 也能跑成，但只换模型、不换提示词（2026-10-10 第一遍就这样漏了）
if (-not (Select-String -Path C:\prep395\src\prep395\deploy\install.ps1 -Pattern 'PREP395_OCR_MODEL = ' -Quiet)) {
  throw "install.ps1 是旧的：先做第 2 步（把新的 prep395 源码拷到 C:\prep395\src\prep395），再回来做第 3 步"
}
$svc = "C:\prep395\services"
$e = @{}; ([xml](Get-Content "$svc\prep395.xml")).service.env | ForEach-Object { $e[$_.name] = $_.value }
$llm = [regex]::Match(([xml](Get-Content "$svc\prep395-llm9b.xml")).service.arguments, 'models\\([^"]+\.gguf)').Groups[1].Value
$lan = ($e["PREP395_HOST"] -split ",")[0]
"所内地址 $lan；9B 模型 $llm；并发 $($e['PREP395_OCR_CONCURRENCY'])"      # 预期：192.168.8.124、现在的 9B 文件名、2

powershell -NoProfile -ExecutionPolicy Bypass -File C:\prep395\src\prep395\deploy\install.ps1 `
  -LanIp $lan -LlmModel $llm -OcrParallel $e["PREP395_OCR_CONCURRENCY"] `
  -AdminUser $e["PREP395_ADMIN_USER"] -AdminPassSha256 $e["PREP395_ADMIN_PASS_SHA256"] `
  -OcrModel Xiaomi-OCR-0.BF16.gguf -OcrMmproj Xiaomi-OCR-0.mmproj-bf16.gguf -OcrCtx 16384
```

- `-OcrCtx 16384`：这个模型一页 A4（长边 2480 像素）约占 8,400 个图像 token，原来的 8192 不够用。
- **预期**：脚本每一步都打印 `==== … ====`，最后没有红色报错；三个服务被卸掉重装。脚本会停下的情形：文件缺失、权限或服务注册失败。这时照原文把报错发给主编排，然后按第 5 节回退。

## 4. 验证

```powershell
Get-Service prep395-ocr, prep395-llm9b, prep395 | Format-Table Name, Status      # 预期：三个都是 Running（模型加载要十几秒）
Invoke-RestMethod http://127.0.0.1:9101/health                                    # 预期：status ok（llama-server 已加载模型）
Invoke-RestMethod http://192.168.8.124:9000/health                                # 预期：status ok、ocr ok、llm9b ok、contract_version 1.3
([xml](Get-Content C:\prep395\services\prep395.xml)).service.env | Where-Object name -eq PREP395_OCR_MODEL
# 预期：value = Xiaomi-OCR-0.BF16.gguf
```

- 如果 `prep395-ocr` 起不来，或者 9101 的 `/health` 一直不通：多半是 llama-server 不认这个模型。在 395 上手动跑一次看报错：
  `C:\prep395\llama\llama-server.exe -m C:\prep395\models\Xiaomi-OCR-0.BF16.gguf --mmproj C:\prep395\models\Xiaomi-OCR-0.mmproj-bf16.gguf --port 9109`
  报 `unknown model architecture` 或 mmproj 相关的错，就按文末"附：升级 llama.cpp"做；其他报错把原文发给主编排。
- 都正常之后告诉主编排"395 已换好"。线 C 会从开发机对 395 跑一遍对比 `bench_g5g6.py`，用 9-30 那套样张，看水印页是否还复读、每页多少秒。识别结果里的 `backend` 字段会显示 `llama.cpp/vulkan:xiaomi-ocr-0`。

## 5. 回退到 PaddleOCR-VL

模型文件没有删，新代码两种模型都支持。把第 3 步最后两行换成第 0 步抄下的原文件名和原来的上下文长度，重跑一遍：

```powershell
# $lan、$llm、$e 同第 3 步；<原 OCR 模型>、<原 mmproj> 是第 0 步那行参数里的两个文件名
powershell -NoProfile -ExecutionPolicy Bypass -File C:\prep395\src\prep395\deploy\install.ps1 `
  -LanIp $lan -LlmModel $llm -OcrParallel $e["PREP395_OCR_CONCURRENCY"] `
  -AdminUser $e["PREP395_ADMIN_USER"] -AdminPassSha256 $e["PREP395_ADMIN_PASS_SHA256"] `
  -OcrModel <原 OCR 模型>.gguf -OcrMmproj <原 mmproj>.gguf
```

然后重做第 4 节的验证：`PREP395_OCR_MODEL` 变回原文件名，识别结果的 `backend` 字段变回 `llama.cpp/vulkan`。
万一 install.ps1 本身跑不通：把第 0 步备份的三个 xml 拷回 `C:\prep395\services\`，逐个执行 `C:\prep395\services\<服务名>.exe restart`。

## 附：升级 llama.cpp（只在第 4 节手动启动报"不认识这个模型"时做）

1. 从 https://github.com/ggml-org/llama.cpp/releases 下载最新的 `llama-b<版本号>-bin-win-vulkan-x64.zip`。
2. `Get-FileHash <zip> -Algorithm SHA256`，把**版本号、文件名、sha256、字节数**报给主编排，登记进 `packaging\versions.lock`。
3. 停掉三个服务。把 `C:\prep395\llama\` 改名为 `llama-b11269`，留着回退用。把新 zip 解压到 `C:\prep395\llama\`。
4. `C:\prep395\llama\llama-server.exe --help | Select-String "log-disable|no-webui|-np"`，确认这三个参数还在。少了哪个，照 README 第 51 行的说明从 `install.ps1` 里去掉哪个。
5. 重跑第 3 步。
- 回退：停服务，把 `llama-b11269` 改回 `llama`，重跑第 5 节。

## 更新源码（不换模型，例如 2026-10-10 加的 OTSL 表格转 Markdown）

只改了 prep395 的代码、模型和服务参数都不变时，不用重跑 `install.ps1`。在 395 上管理员 PowerShell：

```powershell
# 1) 把开发机仓库（main）的 prep395\ 目录覆盖到 C:\prep395\src\prep395\（scp 或 U 盘，同第 2 节）
# 2) 重新装进服务用的 Python。只覆盖源码目录不会生效：服务跑的是装进 C:\prep395\python 里的那一份（install.ps1 也是这样装的）
C:\prep395\python\python.exe -m pip install --no-warn-script-location --upgrade C:\prep395\src\prep395
# 预期：最后一行 Successfully installed prep395-<版本>
# 3) 重启识别服务（WinSW 的 restart 子命令；两个 llama-server 不用动）
C:\prep395\services\prep395.exe restart
```

验证：

```powershell
Select-String -Path C:\prep395\python\Lib\site-packages\prep395\backends.py -Pattern "otsl_to_markdown" | Select-Object -First 1
# 预期：有一行输出（装进去的是新代码；查的是 site-packages 里那份，不是源码目录）
(Get-Service prep395).Status                                   # 预期 Running
Invoke-RestMethod http://192.168.8.124:9000/health             # 预期 status ok、ocr ok、llm9b ok
```

- 回退：把上一版源码覆盖回 `C:\prep395\src\prep395\`，重做上面三步。
- `prep395.exe restart` 报错时用 `Restart-Service prep395`，效果相同。
