r"""T5 第三轮红绿：注记 2218 的三件事，以及第二轮没变红的 S3 第一层。复用 T3 的 redgreen.py，只跑新增的几类。

用法（在 service\ 目录）：.venv\Scripts\python ..\docs\plan\evidence\T5\redgreen_round3.py
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_T3 = pathlib.Path(__file__).resolve().parents[1] / "T3" / "redgreen.py"
_spec = importlib.util.spec_from_file_location("redgreen_t3", _T3)
rg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rg)

LOP = "tests/test_t5_lo_placement.py"
SAFE = "tests/test_t5_convert_safety.py"

rg.MUTATIONS = [
    ("S3·delete_work_file 第一层（单独测：第二层失效时第一层仍拒绝）", "case/gate.py", [
        ('    if parts[0] != WORK:\n        raise _deny(op, "delete_outside_work")\n', ""),
    ], "tests/test_t5_gate.py -k first_layer"),
    ("LO·配置目录在 <应用数据>\\临时\\lo\\<8 位随机>", "ingest/libreoffice.py", [
        ("            root = self.conv.lo_base / uuid.uuid4().hex[:8]\n",
         '            root = pathlib.Path(tempfile.gettempdir()) / ("lbx" + uuid.uuid4().hex[:8])\n'),
    ], f"{LOP} -k under_appdata"),
    ("LO·配置目录用完删除", "ingest/libreoffice.py", [
        ("            if s.profile_root is not None:\n                remove_tree(s.profile_root)\n", ""),
    ], f"{LOP} -k under_appdata"),
    ("LO·服务启动时清理残留", "app.py", [
        ("    libreoffice.cleanup_base(lo_base)", "    pass"),
    ], f"{LOP} -k startup_cleanup"),
    ("LO·删不掉要记日志", "ingest/libreoffice.py", [
        ('    logs.event("libreoffice", "cleanup", status="fail", error="DIR_NOT_REMOVED")\n', ""),
    ], f"{LOP} -k failure_is_logged"),
    ("LO·配置目录路径超过 100 字符不调用", "ingest/libreoffice.py", [
        ('            if len(str((root / "p").resolve())) > MAX_PROFILE_PATH:\n', "            if False:\n"),
    ], f"{LOP} -k too_long"),
    ("LO·0xC0000409 报转换程序异常退出", "ingest/libreoffice.py", [
        ("        if code in CRASH_EXIT_CODES:\n", "        if False:\n"),
    ], f"{LOP} -k crash"),
    ("xlsx·有外链关系不交给 LibreOffice 重算", "case/materials.py", [
        ("        if links.xlsx_has_external_rels(path):\n            return None\n", ""),
    ], f"{LOP} -k external_not_recalculated"),
    (".doc·只在域指令范围内匹配", "ingest/links.py", [
        ("    for m in _INSTR.finditer(text):\n        instr = m.group(1)\n", "    for instr in [text]:\n"),
    ], f"{SAFE} -k plain_text"),
    (".doc·地址要在词首（本机路径里的 \\\\ 不算 UNC）", "ingest/links.py", [
        ('_URL = re.compile(r"(?:^|[\\s\\"\'])(?:https?://|ftp://|file://|\\\\\\\\)", re.IGNORECASE)',
         '_URL = re.compile(r"(?:https?://|ftp://|file://|\\\\\\\\)", re.IGNORECASE)'),
    ], f"{SAFE} -k field_forms"),
    (".doc·链接类域名（开关在前也拦）", "ingest/links.py", [
        ('_FIELD_NAMES = r"(?:INCLUDEPICTURE|INCLUDETEXT|LINK|IMPORT|DDEAUTO|DDE)"',
         '_FIELD_NAMES = r"(?:INCLUDEPICTURE)"'),
    ], f"{SAFE} -k field_forms"),
    (".doc·Data 流单字节地址", "ingest/links.py", [
        ("    return _data_stream_has_url(pathlib.Path(path))\n", "    return False\n"),
    ], f"{SAFE} -k data_stream_alone"),
    (".doc·Data 流里的元数据命名空间不算", "ingest/links.py", [
        ("        if not any(host == h or host.startswith(h) for h in _NAMESPACE_HOSTS):\n", "        if True:\n"),
    ], f"{SAFE} -k data_bytes"),
]

if __name__ == "__main__":
    sys.exit(rg.main())
