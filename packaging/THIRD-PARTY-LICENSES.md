# 第三方组件与许可证（T20 步骤 5）

由 `packaging\gen_lock.py` 生成，版本以 `packaging\versions.lock` 为准。标"候补"的是还没选定或还没装进依赖目录的，打包前补齐。

## 桌面端（DSH）

- DSH 本身 MIT（`dsh\LICENSE`）；它的直接依赖、内置 Python 包和 vendored 源码见 `dsh\THIRD_PARTY_NOTICES.md`（DSH 自带，生成工具 `scripts\gen-third-party-notices.ts`）；npm 全部传递依赖以 `dsh\pnpm-lock.yaml` 为准（`pnpm licenses list`）。
- Electron（MIT）、Node.js（MIT）、Python（PSF-2.0）随 DSH 桌面端内置运行时。

## 其他内置组件

| 组件 | 许可证 | 说明 |
|---|---|---|
| LibreOffice | MPL-2.0 | 版本候补（T20 步骤 3） |
| pandoc | GPL-2.0-or-later | 版本候补；**作为独立程序随包分发，按 GPL 要附许可证全文并提供对应源码的获取方式**，候主编排确认分发方式 |
| 发票整理引擎（invoice-ledger-db 3.9.4.1） | 作者授权 | 律所周海沺律师提供，原样使用；署名保留 |
| 委托材料网页与证件识别驱动（retainer-offline 3.4.1） | 作者授权 | 同上；驱动内附 RapidOCR 及模型，许可证见驱动目录 |
| Qwen3 分词文件 tokenizer.json | Apache-2.0 | |

## 客户端 Python 依赖

| 包 | 版本 | 许可证（取自包自己的元数据） |
|---|---|---|
| anyio | 4.15.1 | MIT |
| attrs | 26.1.0 | MIT |
| certifi | 2026.7.22 | MPL-2.0 |
| charset-normalizer | 3.5.1 | MIT |
| click | 8.5.0 | BSD-3-Clause |
| et_xmlfile | 2.0.0 | MIT |
| flatbuffers | 25.12.19 | Apache 2.0 |
| h11 | 0.16.0 | MIT |
| httpcore | 1.0.9 | BSD-3-Clause |
| httpx | 0.28.1 | BSD-3-Clause |
| idna | 3.20 | BSD-3-Clause |
| jsonschema | 4.26.0 | MIT |
| jsonschema-specifications | 2025.9.1 | MIT |
| lxml | 6.1.3 | BSD-3-Clause |
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
| pymupdf | 1.28.2 | 候补 |
| pypdf | 6.19.0 | BSD-3-Clause |
| pypdfium2 | 5.13.0 | BSD-3-Clause, Apache-2.0, dependency licenses |
| pywin32 | 312 | PSF |
| PyYAML | 6.0.3 | MIT |
| referencing | 0.37.0 | MIT |
| reportlab | 5.0.1 | BSD License |
| rpds-py | 2026.6.3 | MIT |
| shapely | 2.1.2 | BSD 3-Clause |
| starlette | 1.7.0 | BSD-3-Clause |
| sympy | 1.14.0 | BSD |
| typing_extensions | 4.16.0 | PSF-2.0 |
| uvicorn | 0.54.0 | BSD-3-Clause |

候补：keyring, omegaconf, tokenizers（依赖目录里没有，打包时装上再生成）。
