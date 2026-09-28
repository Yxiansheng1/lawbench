#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_manifest.py — 将新下载记录追加到 下载日志.tsv，并更新 最终清单 状态

用法：
    python update_manifest.py <工作目录>

说明：
1. 下载日志追加：每行 [attachment_id, 来源, 日期, 文件名, 大小, 本地路径, OK]
   —— 通过 <workdir>/<来源>/<文件名> 扫描本地文件自动生成。
2. 最终清单更新：凡本地已存在文件对应的行，状态 MISSING → OK（按 大小+文件名 匹配）。

安全保护（v1.0.0 实测修复）：
- 早期日志行格式不标准（如 "票根通行费\t0710_x.pdf\t45392\t0710-0714批\t8oNrM.pdf"），
  仅当行满足 7 列标准格式时才解析文件名；否则视为历史批次行，不参与去重判断，
  避免把历史行误判为"不存在"而重复追加。
- 追加前先备份原日志到 <日志名>.bak（确认无误后手动删除）。

数据流：下载 → decode_results.py 解码到 _raw_decoded/ → archive_files.py 归档 → 本脚本记账。
"""
import os
import sys
import glob
import shutil
import datetime

# ── 环境自举：校验当前包指纹并使用外部缓存；无有效环境时中止 ──
import sys as _sys_boot
from pathlib import Path as _Path_boot
_sys_boot.dont_write_bytecode = True
_sys_boot.path.insert(0, str(_Path_boot(__file__).resolve().parent))
import _deps
_deps.guard(__file__)


def find_workdir():
    """定位工作目录：参数优先，否则当前目录。"""
    return sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "."


def find_final_manifest(workdir):
    """自动定位 最终清单_*.tsv（取最新修改时间的一个）"""
    candidates = glob.glob(os.path.join(workdir, "最终清单_*.tsv"))
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def scan_local(workdir):
    """扫描工作目录下的来源子目录，返回 {文件名: (来源, 路径, 大小)}"""
    files = {}
    for sub in os.listdir(workdir):
        subdir = os.path.join(workdir, sub)
        if not os.path.isdir(subdir) or sub.startswith("_"):
            continue
        for fn in os.listdir(subdir):
            p = os.path.join(subdir, fn)
            if os.path.isfile(p):
                files[fn] = (sub, p, os.path.getsize(p))
    return files


def main():
    workdir = find_workdir()
    log_path = os.path.join(workdir, "下载日志.tsv")

    # ---- 1. 扫描本地文件 ----
    local = scan_local(workdir)
    print(f"扫描到 {len(local)} 个本地归档文件")

    # ---- 2. 读现有下载日志 ----
    # 已记账判定：文件名出现在日志**任一列**（兼容标准 7 列与历史非标准格式，
    # 如 "票根通行费\t0710_x.pdf\t45392\t0710-0714批\t8oNrM.pdf" 文件名在第 2 列）。
    existing_files = set()
    lines = []
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line or line.startswith("#"):
                    continue
                lines.append(line)
                for col in line.split("\t"):
                    if col.endswith((".pdf", ".zip", ".ofd", ".xml", ".csv")):
                        existing_files.add(col)

    # ---- 3. 追加新记录 ----
    new_rows = []
    for fn, (src, path, size) in sorted(local.items()):
        if fn in existing_files:
            continue
        date = ""
        p4 = fn[:4]
        if p4.isdigit() and 1 <= int(p4[:2]) <= 12:
            date = p4
        row = [f"local-{src}", src, date, fn, size, f"{src}/{fn}", "OK"]
        lines.append("\t".join(map(str, row)))
        new_rows.append(row)

    if new_rows:
        # 备份后再写入
        bak = log_path + f".bak_{datetime.date.today().strftime('%Y%m%d')}"
        shutil.copy(log_path, bak)
        print(f"已备份原日志 → {bak}（确认无误后删除）")
        with open(log_path, "w", encoding="utf-8-sig", newline="") as f:
            f.write("\n".join(lines) + "\n")
        print(f"下载日志 {log_path}: 新增 {len(new_rows)} 条")
    else:
        print("下载日志: 无新增（所有本地文件均已记账）")

    # ---- 4. 更新/补录最终清单 ----
    final_path = find_final_manifest(workdir)
    if final_path:
        updated = 0
        with open(final_path, "r", encoding="utf-8-sig") as f:
            flines = f.read().splitlines()

        # 4a. 已有条目 MISSING → OK（附件型）
        for i in range(1, len(flines)):
            parts = flines[i].split("\t")
            if len(parts) >= 7 and parts[6] == "MISSING":
                fname = parts[2]
                size = parts[4]
                if fname in local and str(local[fname][2]) == size:
                    parts[6] = "OK"
                    flines[i] = "\t".join(parts)
                    updated += 1

        # 4b. 链接型来源（LINK-*）补录：本地存在但最终清单中没有的条目
        link_dirs = {"京东JD": "LINK-JD", "krystore": "LINK-KR", "票慧通": "LINK-PHT"}
        existing_files = set()
        for line in flines[1:]:
            p = line.split("\t")
            if len(p) >= 3:
                existing_files.add(p[2])
        appended = 0
        for fn, (src, path, size) in sorted(local.items()):
            if fn in existing_files:
                continue
            # 仅处理链接型来源
            for sub, pri in link_dirs.items():
                if src == sub:
                    date = fn[:4] if fn[:4].isdigit() else ""
                    flines.append(f"{date}\t{sub}\t{fn}\tapplication/pdf\t{size}\t{pri}\tOK")
                    appended += 1
                    break

        if updated or appended:
            with open(final_path, "w", encoding="utf-8-sig", newline="") as f:
                f.write("\n".join(flines) + "\n")
            msg = []
            if updated:
                msg.append(f"更新 {updated} 行 MISSING → OK")
            if appended:
                msg.append(f"补录 {appended} 条链接型发票")
            print(f"最终清单 {final_path}: " + ", ".join(msg))
        else:
            print(f"最终清单 {final_path}: 无需更新")
    else:
        print("!! 未找到 最终清单_*.tsv，跳过状态更新")


if __name__ == "__main__":
    main()
