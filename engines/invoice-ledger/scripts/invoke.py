"""统一入口：python scripts/invoke.py <脚本名> [args...]。"""
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _deps

def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if args else 1
    target = Path(args[0])
    if not target.is_absolute():
        target = HERE / target
    if not target.is_file():
        print(f"[ERROR] 未找到脚本：{target}")
        return 1
    return _deps.run_in_env([str(target.resolve())] + args[1:])

if __name__ == "__main__":
    sys.exit(main())
