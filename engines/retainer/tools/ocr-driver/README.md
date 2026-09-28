# 本地证件识别驱动（retainer-offline 配套）

对外接口统一是 HTML —— 本目录只提供「能力」，不作为独立入口。

## 一、核心设计判断

**PDF 与 Word 里的文字，多数不该走 OCR。**

| 输入 | 文字在哪 | 正确处理 | 是否需要 OCR |
| --- | --- | --- | --- |
| PNG / JPG / JPEG / BMP / TIFF / WebP / GIF | 像素里 | 直接识别 | **是** |
| PDF（有文本层，如电子证照） | 文本层 | 直接提取 | **否**，零误差 |
| PDF（扫描件，无文本层） | 像素里 | 逐页渲染成图再识别 | **是** |
| DOCX | XML 里 | 直接提取文字 | **否**；仅内嵌图片需识别 |
| DOC（老版二进制） | 二进制流 | 需先转换 | 本机**无可用解析器** |

因此驱动内部分两层：`docloader.py` 把任意输入拆成「文本」与「待识别图像」，
`driver.py` 只对「待识别图像」调用 OCR。返回结果中 `text` 与 `lines` 语义不同：

- `text`：来自文档文本层，**可信，无需人工复核**；
- `lines`：OCR 结果，**需人工确认**。

## 二、引擎实测结论（2026-09-13 本机）

引擎：RapidOCR 3.9.2 + 内置 PP-OCRv6 small 模型，ONNX Runtime 1.24.4，CPU 推理。

| 指标 | RapidOCR（本方案） | PaddleOCR 本地（对照） |
| --- | --- | --- |
| 模型体积 | **31.66 MB**（随包分发） | 405.7 MB |
| 引擎初始化 | **0.32 – 0.90 s** | 1.7 s |
| 营业执照单张 | **1.97 – 2.10 s** | 16.98 s |
| 身份证单张 | **1.52 – 1.70 s** | 12.64 s |
| 关键误识 | 无 | `类　　型` 误识为 `美型` |
| 是否需联网 | **否**（模型内置） | 否（模型已在本地） |

模型构成：`PP-OCRv6_det_small.onnx` 9.47 MB、`PP-OCRv6_rec_small.onnx` 20.25 MB、
`ch_ppocr_mobile_v2.0_cls_mobile.onnx` 0.56 MB。

## 三、多格式实测结果

全部为脚本生成的虚构内容。

| 文件 | 解析格式 | 文本层 | 图像 | 走 OCR | 关键信息命中 | 耗时 |
| --- | --- | --- | --- | --- | --- | --- |
| `license.png` | `.png` | 0 字 | 1 | 是 | 3/3 | 1.74 s |
| `license-q90.jpg` | `.jpg` | 0 字 | 1 | 是 | 3/3 | 1.10 s |
| `license-q70.jpeg` | `.jpeg` | 0 字 | 1 | 是 | 3/3 | 1.76 s |
| `license-text.pdf` | `.pdf` | **107 字** | 0 | **否** | 3/3 | 0.07 s |
| `license-scan.pdf` | `.pdf` | 0 字 | 1 | 是 | 3/3 | 1.81 s |
| `license.docx` | `.docx` | **97 字** | 1 | 是（仅图片） | 3/3 | 1.26 s |
| `license-noext` | 按文件头判为 `.png` | 0 字 | 1 | 是 | 3/3 | 1.67 s |
| `license-old.doc` | `.doc` | — | — | — | — | 友好报错 |

两个值得注意的实测点：

1. **PDF 文本层直接提取比 OCR 快约 26 倍**（0.07 s vs 1.81 s）且零误差 —— 电子证照应走这条路；
2. **DOCX 的文字完全不需要 OCR**，97 字瞬时提取；只有内嵌的 1 张图片才走识别。

## 四、优点与局限

**优点**：轻（31.66 MB，本机 PaddleOCR 的 1/13）、快（单张 1.1–1.9 s，比 PaddleOCR 快约 8 倍）、
真离线（模型随 wheel 内置，启动日志 `File exists and is valid`）、行聚合好、引擎可替换。

**局限（须正视）**：

1. **`doc` 无法直接读取**。本机无 LibreOffice、无 Word、无 pywin32/olefile。
   需在 WPS/Word 中另存为 `.docx`，或先转 PDF；驱动返回中文提示而非静默失败。
2. **本轮 100% 是合成图结果**。真实身份证有底纹、防伪图案、反光、透视畸变，
   **真实样本尚未验证**，预期准确率会明显下降。
3. **需要 Python 运行时**，与原「双击 HTML 即用、零进程」体验有落差。
4. **必须放开 CSP**（`connect-src` 放行 `http://127.0.0.1:17801`），是该工具唯一安全模型破例。
5. **加密 PDF 无法读取**（需口令）；DOCX 中的 EMF/WMF 矢量图暂不支持识别。
6. 竖排、繁体、生僻字、印章压字未验证。

## 五、接口契约（引擎无关）

```
GET /health
→ {"ok":true,"ready":true,"engine":"rapidocr","version":"3.9.2",
   "maxBytes":52428800,"offline":true,
   "formats":[".bmp",".doc",".docx",".gif",".jpeg",".jpg",…,".pdf",".png",…],
   "imageFormats":[…],"problems":[]}

POST /ocr      Content-Type: application/octet-stream
               X-File-Name: <URL 编码的文件名>（用于判断格式）
               body: 文件字节
→ 200 {"ok":true,"engine":"rapidocr","filename":"license.docx","format":".docx",
        "text":"…文本层直接提取的文字…","textSource":"document","usedOcr":true,
        "lines":[{"text":"…","score":0.996,"box":[[48,139],…],"source":"image1.png"}],
        "pages":[{"index":1,"kind":"text","textChars":97},
                 {"index":2,"kind":"scan","dpi":200}],
        "notes":["已直接提取 Word 文本 97 字…","另有 1 张内嵌图片需要识别"],
        "durationMs":1260}
→ 415 不支持的格式（含中文说明）
→ 413 文件过大（上限 50 MB）
→ 503 本机无可用引擎
```

约束：仅监听 `127.0.0.1`；不落盘；不出网。
CORS 放行 `Content-Type`、`X-File-Name`，并回 `Access-Control-Allow-Private-Network: true`
（`file://` 页面源为 `null`，且跨本机回环需通过 Chrome 私有网络预检）。

## 六、通道验证结果（已实测）

| 用例 | 页面 CSP | 结果 |
| --- | --- | --- |
| `test/channel.html` | `connect-src http://127.0.0.1:17801` | **PASS**　`engine=rapidocr,ready=true` |
| `test/channel.html#auto` | 同上 | **UPLOAD_PASS**　`format=.png,usedOcr=true,lines=4,durationMs=1089` |
| `test/channel-blocked.html` | `connect-src 'none'` | **FAIL**　`TypeError: Failed to fetch` |

环境：Chrome 152 无头模式、`file://` 协议、驱动真实运行。
结论：**「HTML 作对外接口 + 本机回环驱动」路径可用**，CSP 放行是必要条件，自定义请求头的预检也已通过。

## 七、集成到 retainer-offline 的改动清单

1. `启动.html` 的 CSP：`connect-src 'none'` → `connect-src http://127.0.0.1:17801`；
2. 新增 `app/idscan.js`：探测 `/health`（失败则整块功能隐藏）、上传、
   把 `text` 与 `lines` 交给字段解析；`text` 可直接采信，`lines` 须人工确认；
3. `data/config.json` 新增 `certificateTypes`（证种 → 字段标签映射），保持配置驱动；
4. 表单侧复用现有 `checkCase` 校验流程，识别结果仅作**预填**；
5. 文档同步：`使用说明.md` 增加驱动启动步骤；`docs/架构审查.md` 的门禁「离线连接约束」
   改写为「`connect-src` 仅本机回环白名单，外网请求数为 0」；
6. 版本与包兼容策略需一并决定（升版会触发工作包版本漂移校验）。

**渐进增强**：探测不到驱动时识别入口隐藏，工具按原方式照常工作。

## 八、交付物

| 交付物 | 说明 |
| --- | --- |
| `driver.py` | 本机回环 HTTP 驱动，自带 vendor 注入，引擎可切换 |
| `docloader.py` | 统一文档装载层（格式分流、文件头嗅探、PDF 渲染、docx 文本与图片提取） |
| `fieldfix.py` | 字段解析与容错修正器（视觉行重建、校验位纠错、同行/跨行配对） |
| `vendor/` | 隔离安装的 rapidocr 及依赖（含内置模型），33 MB |
| `start-driver.bat` | 一键启动 |
| `test/channel*.html` + `channel.js` | 通道正反例验证页，支持图片/PDF/DOCX |
| `tests/` | 多轮测试机制与多格式验证，见 `tests/README.md` |

## 九、验证方式

| 层级 | 方法 | 通过标准 |
| --- | --- | --- |
| 驱动可用 | 启动后 `GET /health` | `ready=true`，`problems` 为空 |
| 通道可用 | 无头浏览器打开 `channel.html#auto` | `MACHINE_STATE=UPLOAD_PASS` |
| 通道反例 | 打开 `channel-blocked.html` | `MACHINE_STATE=FAIL` |
| 多格式 | `python tests/run_formats.py` | 各格式关键信息命中 3/3；`.doc` 返回友好提示 |
| 识别质量 | `python tests/run_round.py` | 字段准确率、代码校验通过率不低于上一轮 |
| 修正有效性 | `python tests/run_round.py --diff N M` | 逐例对比，退化用例须归零 |
| 真实场景 | **尚缺**：需真实证件照片补测 | 待补 |
