#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
decode_results.py — 批量解码 MCP DownloadAttachment 结果文件

背景：QQ 邮箱连接器 DownloadAttachment 返回超大 base64 时，结果不进入上下文，
而是自动落盘到 tool-results 目录（.txt），格式为 JSON：
    {"data":{"content":"<base64>","filename":"xxx.zip"}}

本脚本扫描该目录，提取 base64 解码为真实文件，并校验 ZIP/PDF 魔数。

用法：
    python decode_results.py <tool-results目录> <输出目录>

② 阶段硬门禁（不通过**均不落盘**）：
    1) 解码结果非空（0 字节不写）
    2) 魔数校验 ∈ {ZIP, PDF}
    3) 原文件名安全化（只取末段，防路径穿越）
    4) 写后回读校验（存在且大小一致，I2）

退出码：0=全部成功  1=致命错误（参数/目录）  2=存在失败项（需人工处理，均未落盘）

校验输出示例：
    OK  xxx_通行费电子发票.zip  597379B  [ZIP]
    OK  xxx.pdf  148881B  [PDF]
    !!  xxx: 魔数校验失败：非ZIP/PDF:b'xxxx'   ← 不落盘
"""
import sys
import os
import json
import base64

# ── 环境自举：校验当前包指纹并使用外部缓存；无有效环境时中止 ──
import sys as _sys_boot
from pathlib import Path as _Path_boot
_sys_boot.dont_write_bytecode = True
_sys_boot.path.insert(0, str(_Path_boot(__file__).resolve().parent))
import _deps
_deps.guard(__file__)


def extract(path):
    """从结果文件中提取 (base64, 原文件名)。兼容多层 data 嵌套。"""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    obj = json.loads(text)
    d = obj
    for _ in range(6):
        if isinstance(d, dict) and "data" in d:
            d = d["data"]
        else:
            break
    return d.get("content", ""), d.get("filename", "")


def detect_magic(raw):
    """识别文件类型：ZIP/PDF/其他"""
    if raw[:2] == b"PK":
        return "ZIP"
    if raw[:5] == b"%PDF-":
        return "PDF"
    return "非ZIP/PDF:" + repr(raw[:8])


ALLOWED_MAGIC = ("ZIP", "PDF")


def main():
    if len(sys.argv) == 2 and sys.argv[1] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    if len(sys.argv) != 3:
        print("用法: python decode_results.py <tool-results目录> <输出目录>")
        sys.exit(1)
    src_dir, dst_dir = sys.argv[1], sys.argv[2]
    os.makedirs(dst_dir, exist_ok=True)

    ok = 0
    failures = []      # (文件名, 原因) —— 内容层失败，均不落盘
    skipped = []       # 非内容问题（结果文件本身为空）

    for fn in sorted(os.listdir(src_dir)):
        if not fn.endswith(".txt"):
            continue
        path = os.path.join(src_dir, fn)
        if os.path.getsize(path) == 0:
            skipped.append((fn, "结果文件本身为空"))
            continue
        try:
            b64, orig = extract(path)
        except Exception as e:
            failures.append((fn, f"JSON 解析失败 {e}"))
            continue
        b64 = "".join(b64.split())
        if not b64:
            failures.append((fn, "结果文件内没有 base64 内容（content 为空）"))
            continue
        try:
            raw = base64.b64decode(b64)
        except Exception as e:
            failures.append((fn, f"base64 解码失败 {e}"))
            continue

        # ── ② 硬门禁 1：解码结果非空（0 字节不得落盘）──
        if not raw:
            failures.append((fn, "解码结果为空（0 字节）"))
            continue

        # ── ② 硬门禁 2：魔数校验（非 ZIP/PDF 不得落盘）──
        kind = detect_magic(raw)
        if kind not in ALLOWED_MAGIC:
            failures.append((fn, f"魔数校验失败：{kind}"))
            continue

        # ── ② 硬门禁 3：原文件名安全化（防路径穿越，只取末段）──
        safe_orig = os.path.basename(str(orig).replace("\\", "/").strip())
        if not safe_orig:
            failures.append((fn, "原始文件名为空或非法"))
            continue

        # 输出文件名：工具结果名 + 原文件名（保留原名用于后续归档）
        out = os.path.join(dst_dir, fn[:-4] + "_" + safe_orig)
        with open(out, "wb") as f:
            f.write(raw)

        # ── I2 回读：写后校验存在且大小一致 ──
        if not os.path.exists(out) or os.path.getsize(out) != len(raw):
            failures.append((fn, "写后回读校验失败（内容不完整）"))
            continue

        ok += 1
        print(f"OK  {os.path.basename(out)}  {len(raw)}B  [{kind}]")

    # ── 报告与退出码（I3：失败必须传递到退出码）──
    print(f"\n共解码 {ok} 个文件 → {dst_dir}")
    if skipped:
        print(f"跳过（非内容问题）：{len(skipped)}")
        for fn, why in skipped:
            print(f"  -- {fn}: {why}")
    if failures:
        print(f"\n[ERROR] 失败 {len(failures)} 个（**均未落盘**，需人工处理）：")
        for fn, why in failures:
            print(f"  !! {fn}: {why}")
        print("      → 非 ZIP/PDF 或空内容说明附件不完整，请重新下载该附件")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
