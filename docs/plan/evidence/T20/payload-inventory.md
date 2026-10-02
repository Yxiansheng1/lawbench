# T20 步骤 3 载荷清单（执行令 0127 第 1 条；2026-10-02 本机盘点，离线，没有下载任何东西）

版本、哈希以 `packaging\versions.lock` 的 `[client]`、`[client.pip]` 为准，由 `packaging\gen_lock.py --stage` 从暂存目录实际文件生成；许可证见 `packaging\THIRD-PARTY-LICENSES.md`。
"本机现有"指这台开发机上已有、可离线拷入的；正式构建用哪份由主编排定。

| 载荷 | 版本 | 本机现有位置 | 大小 | sha256（关键文件） | 许可证 | 状态 |
|---|---|---|---|---|---|---|
| Python 解释器 | 3.12.14（python-build-standalone 20260901） | DSH 下载缓存 `dsh\apps\desktop\.desktop-build\downloads\<sha256>` | 解压后连依赖约 502 MB | 压缩包 `7c45c962…14b`（与 DSH lock.json 一致） | PSF-2.0 | 就位（build.ps1 `python` 步核哈希后解压） |
| Python 依赖（50 个包） | 见 `[client.pip]` | 线 C `.venv`、线 B `service\.venv` 已装的，经 `packaging\python\repack_wheels.py` 回装成 `packaging\wheelhouse\`（不入库） | 轮子约 120 MB | 回装的轮子**不是 PyPI 原文件**，哈希对不上 | 见许可证表 | 本机跑通；**正式构建候补：需联网**在构建机 `pip download` 原始轮子 |
| LibreOffice | 26.8.0.3 | `C:\Program Files\LibreOffice`（系统安装） | 667 MB | `soffice.exe` `a2823391…cb988` | MPL-2.0 | 可拷入；正式发布包（MSI 解包的精简版）**候补：需联网** |
| pandoc | 3.11 | `%LOCALAPPDATA%\Pandoc\pandoc.exe`（用户安装） | 223 MB | `8063cc4b…a098` | GPL-2.0-or-later | 可拷入；GPL 分发方式候 owner N58 |
| tokenizer.json | Qwen3 | `D:\lawbench-B\service\lawbench\llm\tokenizer.json`（线 B 工作区，git 忽略；N16 由用户放的） | 约 19 MB | `87a7830d…2de4` | Apache-2.0 | 可拷入 |
| Skill 与 `capsules.default.json` | 仓库现有 | `skills\`，`install.py --out` 产出 27 个文件 | 0.1 MB | — | 我方 | 就位（`skills` 步） |
| 发票引擎 | invoice-ledger-db 3.9.4.1 | `engines\invoice-ledger\`（含运行环境压缩包 `vendor\env-win_amd64.zip`） | 44 MB | 环境包 `c872e5bf…7189` | 作者授权 | 就位（`engines` 步原样拷贝） |
| 委托材料网页与证件识别驱动 | retainer-offline 3.4.1 | `engines\retainer\`（驱动自带 `tools\ocr-driver\vendor\`：rapidocr、omegaconf、antlr4，33 MB） | 50 MB | — | 作者授权；RapidOCR Apache-2.0 | 就位 |
| 驱动的 Python 依赖 | onnxruntime 1.24.4、opencv-python-headless 5.0.0.93 等 | 在 `[client.pip]` 内 | 含在上面 | — | MIT、Apache-2.0 | 就位 |
| Word 模板（设置里的默认文书、合同模板） | — | **仓库里没有** | — | — | — | **候补**：要律所提供，或确认第一版不带默认模板 |
| 管理员 Skill 目录只读脚本 | — | `packaging\installer\set-skills-acl.ps1` | — | — | 我方 | 就位（`skills` 步一并放进 `installer\`） |

## 体积
暂存目录合计约 1.5 GB、2.8 万个文件（`package-dryrun.txt`）。大头：
- LibreOffice 667 MB，是系统安装的完整版；精简后可以小很多。
- pandoc 223 MB。
- Python 依赖：onnxruntime、opencv、sympy（onnxruntime 拉进来的）、numpy、PyMuPDF。

是否精简、怎么精简，候步骤 3 定。

## 依赖里值得一看的
- `tokenizers` 依赖 `huggingface_hub`（连带 `fsspec`、`filelock`、`tqdm`）。我方只用 `Tokenizer.from_file` 读本地文件，不调它的下载接口；但它在包里，有联网能力。
- 产品不外连由 Spec 14.3 的地址白名单兜底（服务统一的 httpx 客户端）。`huggingface_hub` 自己发请求时不经那个客户端，靠"代码里不调用"保证，记在这里。
