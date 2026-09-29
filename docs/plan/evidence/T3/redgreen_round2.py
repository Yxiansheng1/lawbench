r"""T3 第二轮返修（S1–S7）与同时并入的 T5 修改的红绿验证：复用 redgreen.py，只跑新增的几类。

用法（在 service\ 目录）：.venv\Scripts\python ..\docs\plan\evidence\T3\redgreen_round2.py
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_spec = importlib.util.spec_from_file_location("redgreen_t3", pathlib.Path(__file__).with_name("redgreen.py"))
rg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rg)

R2 = "tests/test_t3_rework2.py"
T5G = "tests/test_t5_gate.py"
LONG = "tests/test_t5_long_paths.py"

rg.MUTATIONS = [
    ("S1·_host_port 捕获 urlsplit 的 ValueError", "net.py", [
        ("    try:\n        u = urlsplit(url)\n", "    u = urlsplit(url)\n    try:\n"),
    ], f"{R2} -k s1_"),
    ("S1·check_servers 拒绝解析不了的地址（不依赖转发端口）", "net.py", [
        ('            if servers.get(key) and _host_port(servers[key]) is None:\n'
         '                raise ApiError("INVALID_ARGUMENT", "server_url_invalid")\n', "            pass\n"),
    ], f"{R2} -k s1_"),
    ("S1·转发遇到未预料的异常返回 502、日志记类名", "net.py", [
        ("            except Exception as e:  # noqa: BLE001 未预料的异常（如 httpx.InvalidURL，它不是 HTTPError 的子类）\n"
         "                finish(\"fail\", type(e).__name__)\n"
         "                await fail_502(\"INTERNAL\")\n", ""),
    ], f"{R2} -k s1_"),
    ("S2·resolve_internal 的拒绝路径", "case/gate.py", [
        ("    parts = _split_rel(rel, op)\n    return _resolve(root, parts, op)\n",
         "    return pathlib.Path(root, rel)\n"),
    ], f"{R2} -k s2_"),
    ("S3·copy_original 复制后复查（copy_escape）", "case/gate.py", [
        ('    if is_link(path) or not is_within(root, os.path.realpath(path)):\n'
         '        raise _deny(op, "copy_escape")\n', ""),
    ], T5G),
    ("S3·delete_work_file 第一层（第一级必须是 工作区）", "case/gate.py", [
        ('    if parts[0] != WORK:\n        raise _deny(op, "delete_outside_work")\n', ""),
    ], T5G),
    ("S3·delete_work_file 第二层（解析后仍在 工作区）", "case/gate.py", [
        ('    if _real_top(root, path, op) != WORK.casefold():\n        raise _deny(op, "delete_outside_work")\n', ""),
    ], T5G),
    ("S4·标准目录位置上是文件时跳过", "case/gate.py", [
        ("        if is_link(cur) or (os.path.lexists(cur) and not os.path.isdir(cur)):", "        if is_link(cur):"),
    ], f"{R2} -k s4_"),
    ("S5·盘符根目录规则", "case/gate.py", [
        ('    if os.path.splitdrive(real)[1] in ("", os.sep):\n', "    if False:\n"),
    ], f"{R2} -k s5_"),
    ("S7·工作台端口被占时进程非零退出", "__main__.py", [
        ("            failed.append(name)\n", "            pass\n"),
    ], f"{R2} -k s7_main"),
    ("S7·转发流式逐段透传", "net.py", [
        ('                    async for chunk in resp.aiter_raw():\n'
         '                        await send({"type": "http.response.body", "body": chunk, "more_body": True})\n',
         '                    buf = b"".join([c async for c in resp.aiter_raw()])\n'
         '                    await send({"type": "http.response.body", "body": buf, "more_body": True})\n'),
    ], f"{R2} -k s7_stream"),
    ("T5·导入遇到设备名或点开头的文件名只跳过这一个", "case/materials.py", [
        ("            except ApiError:\n                # 文件名是设备名", "            except KeyError:\n                # 文件名是设备名"),
    ], f"{T5G} -k device"),
    ("T5·深路径：材料文本超长只让该份失败", "case/materials.py", [
        ('    if os.name != "nt":\n        return False\n    full = os.path.join(root, *rel.split("/"))',
         '    return False\n    full = os.path.join(root, *rel.split("/"))'),
    ], LONG),
    ("T5·深路径：复制原件的临时名不比目标名长", "case/gate.py", [
        ('    tmp = path.parent / f".~lb{uuid.uuid4().hex[:8]}"', '    tmp = path.parent / f".~lb-{uuid.uuid4().hex}.tmp"'),
    ], LONG),
]

if __name__ == "__main__":
    sys.exit(rg.main())
