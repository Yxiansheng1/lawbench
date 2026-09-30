r"""T3 S1 · N43 ① 的红绿（执行令补充 致B-ORCH-执行令补充-N43N44已定-20260930-1327）。复用 redgreen.py。

用法（在 service\ 目录）：.venv\Scripts\python ..\docs\plan\evidence\T3\redgreen_n43.py
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_spec = importlib.util.spec_from_file_location("redgreen_t3", pathlib.Path(__file__).with_name("redgreen.py"))
rg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rg)

R = "tests/test_t3_rework3.py"
rg.TITLE = "T3 N43 红绿验证"
rg.MUTATIONS = [
    ("N43·读 b.host 放在 try 里（idna 的 UnicodeError 是 ValueError 的子类，挪进 try 才接得住）", "net.py", [
        ("        b_host = b.host  # xn-- 写法不合规时 idna 在这里才报错（UnicodeError），也算解析不了（N43）\n"
         "    except (ValueError, UnicodeError, httpx.InvalidURL):\n        return False\n",
         "    except (ValueError, UnicodeError, httpx.InvalidURL):\n        return False\n    b_host = b.host\n"),
    ], f"{R} -k 'n43_xn_rejected or n43_put_xn'"),
    ("N43·构造 Net 出任何异常都退回默认地址", "app.py", [
        ("    except Exception as e:  # noqa: BLE001 设置里的地址不合格", "    except ApiError as e:  # noqa: BLE001 设置里的地址不合格"),
    ], f"{R} -k n43_app_survives"),
]

_run = rg.run


def _run_no_full(sel: str):
    if sel == "tests":
        return 0, "（本脚本不跑全量，见 T5\\pytest-返修第二轮*.txt）"
    return _run(sel)


rg.run = _run_no_full

if __name__ == "__main__":
    sys.exit(rg.main())
