r"""T3 第三轮红绿：S1 补漏（执行令 致B-ORCH-执行令-T3第三轮及T5返修-20260930-0136 第 2 节）。复用 redgreen.py。

用法（在 service\ 目录）：.venv\Scripts\python ..\docs\plan\evidence\T3\redgreen_round3.py
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_spec = importlib.util.spec_from_file_location("redgreen_t3", pathlib.Path(__file__).with_name("redgreen.py"))
rg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rg)

R = "tests/test_t3_rework3.py"
rg.TITLE = "T3 第三轮红绿验证"
rg.MUTATIONS = [
    ("S1·设置 PUT 与启动时用 httpx 同一解析器再校验", "net.py", [
        ("(not server_url_ok(servers[key]) or _host_port(servers[key]) is None)", "_host_port(servers[key]) is None"),
    ], f"{R} -k 'put_f10 or check_servers or saved_f10'"),
    ("S1·拒绝控制字符、非 ASCII 和 @?#%\\", "net.py", [
        ("    if any(not (0x20 < ord(c) < 0x7F) for c in url) or _URL_FORBIDDEN & set(url):\n        return False\n", ""),
    ], f"{R} -k bad_urls_rejected"),
    ("S1·两个解析器的主机、端口要一致", "net.py", [
        ("    if host != a.hostname.lower():\n        return False\n", ""),
    ], f"{R} -k parsers_must_agree_alone"),
    ("S1·主机名只收 ASCII 标签或 IP 字面量，拒绝非标准 IPv4 写法", "net.py", [
        ("    if last.isdigit() or last.startswith(\"0x\"):", "    if False:"),
    ], f"{R} -k bad_urls_rejected"),
    ("S1·probe 接住解析异常，不出 500", "net.py", [
        ("        except Exception as e:  # noqa: BLE001 如 httpx.InvalidURL（不是 TransportError）：按不通处理，不出 500\n"
         "            logs.event(\"net\", \"probe_\" + kind, status=\"fail\", error=type(e).__name__)\n"
         "            return False\n", ""),
    ], f"{R} -k probe_catches"),
]

_run = rg.run


def _run_no_full(sel: str):
    """结尾那次"复原后全量"不在这里跑：三张卡提交后深、短路径各跑一次全量，见 T5\pytest-*.txt。"""
    if sel == "tests":
        return 0, "（本脚本不跑全量，见 T5\\pytest-返修第一轮*.txt）"
    return _run(sel)


rg.run = _run_no_full

if __name__ == "__main__":
    sys.exit(rg.main())
