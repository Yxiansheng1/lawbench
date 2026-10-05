# 第三方组件与许可证（T20 步骤 5）

由 `packaging\gen_lock.py` 生成，版本以 `packaging\versions.lock` 为准。标"候补"的是还没选定或还没装进依赖目录的，打包前补齐。

## 桌面端（DSH）

- DSH 本身 MIT（`dsh\LICENSE`）；它的直接依赖、内置 Python 包和 vendored 源码见 `dsh\THIRD_PARTY_NOTICES.md`（DSH 自带，生成工具 `scripts\gen-third-party-notices.ts`）；npm 全部传递依赖以 `dsh\pnpm-lock.yaml` 为准（`pnpm licenses list`）。
- Electron（MIT）、Node.js（MIT）、Python（PSF-2.0）随 DSH 桌面端内置运行时。

## 其他内置组件

| 组件 | 许可证 | 说明 |
|---|---|---|
| LibreOffice | MPL-2.0 | 版本、哈希见 `versions.lock` 的 `[client]` |
| pandoc | GPL-2.0-or-later | 版本、哈希见 `versions.lock`；作为独立程序随包分发；GPL 全文随包在 `tools\pandoc\COPYING.rtf`（与 `COPYRIGHT.txt` 均取自 pandoc 官方 Windows 安装包）。**pandoc 源码可向技术支持索取**（N58 法务意见候定） |
| 发票整理引擎（invoice-ledger-db 3.9.4.1） | 作者授权 | 律所周海沺律师提供，原样使用；署名保留 |
| 委托材料网页与证件识别驱动（retainer-offline 3.4.1） | 作者授权 | 同上；驱动内附 RapidOCR 及模型，许可证见驱动目录 |
| Qwen3 分词文件 tokenizer.json | Apache-2.0 | |

## 客户端 Python 依赖

**PyMuPDF 是 AGPL-3.0（或 Artifex 商业许可）**：由证件识别驱动 `engines\retainer\tools\ocr-driver\docloader.py` 引入（把证件 PDF 转成图片），随包分发时要按 AGPL 附许可证全文并提供源码获取方式；能否换成已在用的 pypdfium2 / pypdf 要改律所的驱动代码（原样使用，不改），候 owner N58。
各包的许可证全文随它的 `*.dist-info`（`LICENSE*`、`licenses\`）一起装进 `<安装目录>\python\Lib\site-packages\`。

| 包 | 版本 | 许可证（取自包自己的元数据） |
|---|---|---|
| anyio | 4.15.1 | MIT |
| attrs | 26.1.0 | MIT |
| certifi | 2026.7.22 | MPL-2.0 |
| charset-normalizer | 3.5.1 | MIT |
| click | 8.5.0 | BSD-3-Clause |
| colorama | 0.4.6 | BSD License |
| colorlog | 6.12.0 | MIT License |
| et_xmlfile | 2.0.0 | MIT |
| filelock | 4.0.7 | MIT |
| flatbuffers | 25.12.19 | Apache 2.0 |
| fsspec | 2026.9.0 | BSD-3-Clause |
| h11 | 0.16.0 | MIT |
| hf-xet | 1.6.0 | Apache-2.0 |
| httpcore | 1.0.9 | BSD-3-Clause |
| httpx | 0.28.1 | BSD-3-Clause |
| huggingface_hub | 1.33.0 | Apache-2.0 |
| idna | 3.20 | BSD-3-Clause |
| jaraco.classes | 3.4.0 | MIT License |
| jaraco.context | 6.1.2 | MIT |
| jaraco.functools | 4.6.0 | MIT |
| jsonschema | 4.26.0 | MIT |
| jsonschema-specifications | 2025.9.1 | MIT |
| keyring | 25.7.0 | MIT |
| lxml | 6.1.3 | BSD-3-Clause |
| more-itertools | 11.1.0 | MIT |
| mpmath | 1.3.0 | BSD |
| numpy | 2.5.3 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| olefile | 0.47 | BSD |
| onnxruntime | 1.24.4 | MIT License |
| opencv-python-headless | 5.0.0.93 | Apache 2.0 |
| openpyxl | 3.1.5 | MIT |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| pillow | 12.3.0 | MIT-CMU |
| protobuf | 7.36.2 | 3-Clause BSD License |
| pyclipper | 1.4.0 | MIT |
| pymupdf | 1.28.2 | Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial License |
| pypdf | 6.19.0 | BSD-3-Clause |
| pypdfium2 | 5.13.0 | BSD-3-Clause, Apache-2.0, dependency licenses |
| python-docx | 1.2.0 | MIT |
| pywin32 | 312 | PSF |
| pywin32-ctypes | 0.2.3 | BSD-3-Clause |
| PyYAML | 6.0.3 | MIT |
| referencing | 0.37.0 | MIT |
| reportlab | 5.0.1 | BSD license (see license.txt for details), Copyright (c) 2000-2025, ReportLab Inc. |
| requests | 2.34.2 | Apache-2.0 |
| rpds-py | 2026.6.3 | MIT |
| shapely | 2.1.2 | BSD 3-Clause |
| six | 1.17.0 | MIT |
| starlette | 1.7.0 | BSD-3-Clause |
| sympy | 1.14.0 | BSD |
| tokenizers | 0.23.2 | Apache Software License |
| tqdm | 4.70.1 | MPL-2.0 AND MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| urllib3 | 2.8.0 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |
