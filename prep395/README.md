# prep395 · 395 预处理服务

单页识别（OCR）和 9B 抽取，部署在 395（Windows 11）上，给工作台服务调用。设计见 Spec 第 6 节、20.6；接口契约 `contracts\prep395\`。

## 本机运行（开发）

```powershell
cd D:\lawbench-C
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -e ".\prep395[test]"

# 用测试后端（不需要模型），6000D 指向所内网关做 Key 校验
$env:PREP395_BACKEND = "fake"
$env:PREP395_LLM_BASE = "http://192.168.8.77:8000"
$env:PREP395_HOME = "$env:TEMP\prep395-dev-home"   # 开发时的服务目录（日志写在其下 logs\）
.\.venv\Scripts\python -m prep395                   # 默认监听 127.0.0.1:9000
```

测试：

```powershell
cd D:\lawbench-C\prep395
..\.venv\Scripts\python -m pytest -q
```

测试不连 6000D、不需要模型：Key 校验用本机假 6000D（200 / 401 / 403 / 500 / 不可达），推理用 `FakeBackend`，`LlamaServerBackend` 对本机假 llama-server 测请求格式与取消。去水印测试读 `tests\fixtures\criminal-01\讯问笔录.pdf`。

## 配置（环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `PREP395_HOST` / `PREP395_PORT` | `127.0.0.1` / `9000` | 监听地址；部署时 HOST 设为 395 的局域网 IP |
| `PREP395_LLM_BASE` | `http://192.168.8.77:8000` | 6000D 网关，用于 Key 校验；只允许 6000D 的所内、所外地址或 127.0.0.1 |
| `PREP395_BACKEND` | `fake` | `fake` 或 `llama` |
| `PREP395_OCR_URL` / `PREP395_LLM9B_URL` | `http://127.0.0.1:9101` / `:9102` | 本机 llama-server；只允许 127.0.0.1 |
| `PREP395_OCR_MODEL` / `PREP395_LLM9B_MODEL` | `ocr` / `llm9b` | 发给 llama-server 的 model 名 |
| `PREP395_OCR_CONCURRENCY` | `2` | 识别同时处理页数 N（按 G-5 实测调整）；9B 固定 1 |
| `PREP395_QUEUE_MAX` | `20` | 排队上限，超出返回 503 `QUEUE_FULL` + `Retry-After` |
| `PREP395_OCR_TIMEOUT` | `120` | 单页识别超时（秒），超时返回 504 |
| `PREP395_HOME` | `C:\prep395` | 服务目录；启动清理范围之一 |
| `PREP395_LOG_DIR` | `<HOME>\logs` | 访问日志 `access.log`，按天滚动、保留 30 天 |
| `PREP395_ADMIN_USER` / `PREP395_ADMIN_PASS_SHA256` | 空 | `/admin` 的 HTTP Basic 账号；口令只配 SHA-256（十六进制），不配明文。未配置时 `/admin` 返回 503 |

生成口令摘要（在部署机上执行，不要把口令写进任何文件）：

```powershell
$p = Read-Host -AsSecureString "管理员口令"
$plain = [Runtime.InteropServices.Marshal]::PtrToStringUni([Runtime.InteropServices.Marshal]::SecureStringToBSTR($p))
-join ([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($plain)) | ForEach-Object { $_.ToString("x2") })
```

## 接口

| 接口 | 鉴权 | 说明 |
|---|---|---|
| `GET /health` | 无 | 状态、两个后端是否在线、排队数、版本 |
| `POST /v1/ocr/page?dewatermark=&deskew=&return_image=` | Bearer 律师 Key | 请求体是 PNG / JPEG 原始字节（≤10MB，长边 ≤2480） |
| `POST /v1/extract` | Bearer 律师 Key | `fields` / `classify` 两种任务，text ≤16000 字 |
| `GET /admin` | HTTP Basic | 只读：排队、处理中、按 Key 前缀（SHA-256 前 8 位）的今日请求数、页数、耗时；`Accept: application/json` 时返回 JSON |

错误体 `{"error": {"code", "message"}}`：400 `BAD_IMAGE` / `BAD_REQUEST`，401 `KEY_INVALID`，413 `TOO_LARGE`，503 `QUEUE_FULL` / `KEY_CHECK_UNAVAILABLE`，504 `TIMEOUT`，500 `INTERNAL`。

## 保密要点（Spec 6.2、6.6）

- 不用 multipart，`request.stream()` 读进内存；先按 `Content-Length` 拒绝超过 10MB 的请求，没有 `Content-Length` 时边读边数。
- 图片在内存中解码、纠偏、去水印、编码为 PNG，以 base64 经本机 HTTP 发给 llama-server；不写临时文件。
- 启动时删除系统临时目录和服务目录下 `prep395-` 前缀的残留（本服务不产生这类文件，是进程被强杀时的兜底），日志只记删除个数。
- 访问日志字段固定为 `ts, key, api, pages, bytes, elapsed_ms, status, err`；`key` 为 SHA-256 前 8 位，`err` 为错误码或异常类名。uvicorn 自带访问日志关闭。
- 客户端断开：排队中的出队；推理中的取消对 llama-server 的请求（连接断开，llama-server 停止生成）。日志里记为 `status: 499`。
- 去水印默认关闭；只把浅灰、低饱和、占全图 ≥1% 的像素换成纸张底色，深色文字、红色、蓝色像素不动。

部署（WinSW 服务、专用账号、防火墙、llama-server 参数）在 T11 做。
