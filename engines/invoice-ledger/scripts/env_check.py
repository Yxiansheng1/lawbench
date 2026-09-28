"""只读环境诊断；--deep 校验全部文件哈希。不会展开或修复缓存。"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _deps

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--deep", action="store_true")
    ap.add_argument("--ocr", action="store_true", help="额外检查目标 Windows 简体中文 OCR 语言功能")
    args = ap.parse_args()
    try:
        lock = _deps.read_lock()
        _deps.verify_archive(lock)
        root = _deps.selected(lock)
        if not args.quiet:
            print(f"期望指纹：{lock['zip']['sha256']}")
            print(f"缓存：{root or '尚未建立'}")
        if root is None:
            print("[结论] 环境包有效，缓存尚未建立；首次运行将自动创建。")
            return 1 if args.ocr else 0
        _deps.verify_files(root, lock, deep=args.deep)
        _deps.health(root, lock)
        ledger = Path(os.environ.get("INVOICE_LEDGER_DIR", _deps.SKILL_ROOT)) / "发票主台账.xlsx"
        if ledger.is_file():
            code = "import openpyxl,sys; w=openpyxl.load_workbook(sys.argv[1],read_only=True); print(w.sheetnames); w.close()"
            r = subprocess.run([str(root / "python.exe"), "-B", "-c", code, str(ledger)],
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            if r.returncode:
                raise RuntimeError(f"台账读取失败：{r.stderr[-300:]}")
        if args.ocr:
            code = ("import sys,json; " + f"sys.path.insert(0,{str(_deps.SKILL_ROOT / 'scripts')!r}); "
                    + "import extract_fields; print(json.dumps(extract_fields.ocr_capabilities()))")
            result = subprocess.run([str(root / "python.exe"), "-B", "-c", code], capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=30)
            if result.returncode:
                raise RuntimeError(f"OCR 能力检查失败：{result.stderr[-300:]}")
            status = json.loads(result.stdout)
            print("[OCR] Windows 已安装语言：" + ", ".join(status["languages"]))
            if not status["chinese_available"]:
                raise RuntimeError("winsdk 已内置，但目标 Windows 缺少简体中文 OCR 语言功能（zh-CN）")
        print("[结论] 环境健康（只读诊断通过）")
        return 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as e:
        print(f"[问题] {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
