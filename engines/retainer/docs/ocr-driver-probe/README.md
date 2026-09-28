# 本地 OCR 驱动可行性验证记录

验证日期：2026-09-13　验证机：Windows 10 专业版（UI 区域 zh-CN）
验证目的：确认「浏览器只做渠道、OCR 由本地轻量驱动承担」这一方案在本机是否成立。

本目录全部测试图为脚本生成的虚构内容，不含任何真实证件信息。

## 一、环境实测事实

| 项目 | 实测结果 |
| --- | --- |
| 系统 Python 3.12.10 | `paddleocr` 3.4.0、`paddle`、`onnxruntime`、`fitz`、`pdfplumber`、`pypdf`、`PIL`、`numpy`、`cv2`、`shapely` 均已安装 |
| PaddleX 模型 | `~/.paddlex/official_models` 共 405.7 MB，含 `PP-OCRv5_server_det`(168.5MB)、`PP-OCRv5_server_rec`(162.6MB)、`PP-LCNet_x1_0_doc_ori`、`PP-LCNet_x1_0_textline_ori`、`UVDoc` |
| Windows 内置 OCR | `AvailableRecognizerLanguages` = `en-US, zh-Hans-CN`，语言包可用 |
| 其它引擎 | `tesseract` 未安装；`rapidocr_onnxruntime` 未安装；`pyzbar` 未安装 |
| 结论 | **本机无需安装任何软件即具备完全离线的中文 OCR 能力** |

## 二、端到端实测结果

以脚本生成的两张虚构证件图（营业执照、居民身份证版式）测试。

引擎：PaddleOCR 3.4.0 + PP-OCRv5 server 模型，CPU 推理，全程离线。

离线证据（stderr 原文）：`Connectivity check to the model hoster has been skipped because PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK is enabled.` 与 `Model files already exist. Using cached files.`

识别结果（关键字段）：

- 统一社会信用代码 `91440300MA5EXAMPLA` —— **逐字符正确**
- 公民身份号码 `11010519491231002X` —— **逐字符正确**
- 法定代表人 `张三`、姓名 `李四`、出生日期 `1985年3月12日`、住所行 —— 均正确

耗时：营业执照 16.98 秒、身份证 12.64 秒（引擎初始化 1.7 秒）。

## 三、必须记录的两个坑

### 1. oneDNN 崩溃（阻断级）

PaddleOCR 3.4.0 默认启用 oneDNN，在 PIR 新执行器下推理直接抛错：

```
NotImplementedError: (Unimplemented) ConvertPirAttribute2RuntimeAttribute not support
[pir::ArrayAttribute<pir::DoubleAttribute>]
(at ..\paddle\fluid\framework\new_executor\instruction\onednn\onednn_instruction.cc:118)
```

- 无效做法：设置环境变量 `FLAGS_use_mkldnn=0`、`FLAGS_enable_pir_api=0` —— 均不生效（PaddleX 显式传参覆盖）。
- 有效做法：构造时传 `enable_mkldnn=False`。

```python
PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False,
          use_textline_orientation=False, enable_mkldnn=False)
```

### 2. 行切分不等于字段（决定接口设计）

识别输出是「文本行」，不是「字段」。实测中同一行的标签与值会被切成独立行，例如 `名称` / `深圳市示例科技有限公司`、`所` / `广东省深圳市福田区示例路1号`；全角空格排版还会造成错位误识，`类　　型` 被识为 `美型`。

因此驱动**不应直接输出字段**，而应输出「带坐标的文本行」，由前端按邻近关系配对，并用校验位算法纠错。这是接口契约的直接依据。

## 四、校验位算法验证

以官方样例校验，两个算法均通过：

- 统一社会信用代码（GB 32100-2015）：官例 `91350100M000100Y43` 计算末位 = `3`，与官例一致。注意权重方向为**左起 `3^i mod 31`**，写成右起会算错。
- 公民身份号码（GB 11643-1999 / ISO 7064 MOD 11-2）：官例 `11010519491231002X` 计算末位 = `X`。

## 五、未验证事项

1. RapidOCR（ONNX）未实测 —— `rapidocr_onnxruntime` 未安装。它模型约 15MB、无需 paddle 框架、加载更快，是「轻量化」的候选，需另行验证。
2. Windows.Media.Ocr 未跑通 —— 本机安全策略拦截 PowerShell 的 `Add-Type` 与 `Invoke-Expression`，无法完成 WinRT 异步调用；改用 Go/Rust 可执行文件调用 WinRT 可绕开。
3. 真实证件照片未测 —— 本次测试图均为干净白底印刷体。真实身份证照片存在底纹、反光、透视畸变，识别难度显著更高，须以真实样本复测。
4. 浏览器侧通道未打通 —— `file://` 页面访问 `127.0.0.1` 涉及 CSP、CORS 与 Private Network Access 预检，需实测确认。

## 六、本目录文件

| 文件 | 说明 |
| --- | --- |
| `_tmp_ocr_make.py` | 生成虚构测试图，并验证两个校验位算法 |
| `_tmp_ocr_paddle.py` | PaddleOCR 离线识别实测脚本（含 oneDNN 规避与多组参数回退） |
| `_ocr_paddle_result.txt` | 识别结果原文 |
| `_tmp_ocr_license.png` / `_tmp_ocr_idcard.png` | 虚构测试图 |
| `_tmp_winrt_ocr.ps1` | Windows 内置 OCR 尝试脚本（受本机策略限制未跑通） |
| `_ocr_probe2.txt` ~ `_ocr_probe6b.txt` | 环境与模型目录探测原始输出 |
