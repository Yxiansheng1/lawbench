r"""T3 红绿验证：逐类"改坏防护 → 跑对应测试应当变红 → 复原 → 变绿"。不用 git stash。

用法（在 service\ 目录）：.venv\Scripts\python ..\docs\plan\evidence\T3\redgreen.py
每个改动都是源码里的精确字符串替换（必须恰好命中一次），跑完一定在 finally 里写回原文，
最后核对源码与开始时逐字节一致，再跑一次全量测试。
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

SERVICE = pathlib.Path(__file__).resolve().parents[4] / "service"
PKG = SERVICE / "lawbench"

# (类别, 文件, [(原文, 改坏后)], 测试选择)
MUTATIONS = [
    ("闸门·上跳 ..（形状检查 + 最终 realpath 校验一起去掉）", "case/gate.py", [
        ('if p.rstrip(" .") in ("", "..") or p == "..":', "if False:"),
        ("    if not is_within(root, real):\n        raise _deny(op, \"escape\")", "    pass"),
    ], "tests/test_gate.py"),
    ("闸门·绝对路径 / 盘符 / UNC（形状检查 + 最终校验一起去掉）", "case/gate.py", [
        ('if rel.startswith(("/", "\\\\")) or _DRIVE.match(rel) or os.path.isabs(rel):', "if False:"),
        ("    if not is_within(root, real):\n        raise _deny(op, \"escape\")", "    pass"),
    ], "tests/test_gate.py"),
    ("闸门·备用数据流 / NUL / 保留字符", "case/gate.py", [
        ("if _BAD_CHARS.search(rel):", "if False:"),
    ], "tests/test_gate.py"),
    ("闸门·以 . / 工作区 / 成果 开头（含尾点尾空格、大小写）", "case/gate.py", [
        ('if first.startswith(".") or _top(parts) in (WORK.casefold(), OUTPUT.casefold()):', "if False:"),
        ('if top.startswith(".") or top in (WORK.casefold(), OUTPUT.casefold()):', "if False:"),
    ], "tests/test_gate.py"),
    ("闸门·超长名 / 超长路径", "case/gate.py", [
        ("if len(rel) > MAX_REL:", "if False:"),
        ("if len(p) > MAX_COMPONENT:", "if False:"),
    ], "tests/test_gate.py"),
    ("闸门·不跟随链接（符号链接、junction）", "case/gate.py", [
        ('if stat.S_ISLNK(st.st_mode) or getattr(st, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT:',
         "if False:"),
        ("    if is_link(root):\n        raise _deny(op, \"root_is_link\")", "    pass"),
    ], "tests/test_gate.py"),
    ("闸门·最终校验的大小写与分隔符（前缀相同的兄弟目录）", "case/gate.py", [
        ("return os.path.normcase(os.path.normpath(p))", "return os.path.normpath(p)"),
        ("return t.startswith(r.rstrip(os.sep) + os.sep)", "return t.startswith(r)"),
    ], "tests/test_gate.py::test_is_within_prefix_and_case"),
    ("闸门·写权限只限 工作区/ 成果/", "case/gate.py", [
        ("if parts[0] not in WRITABLE_TOP:", "if False:"),
        ("if _real_top(root, path) not in (WORK.casefold(), OUTPUT.casefold()):", "if False:"),
    ], "tests/test_gate.py"),
    ("闸门·案件根目录是链接或 junction", "case/gate.py", [
        ('if is_link(p):\n        raise _deny(op, "root_is_link", "CASE_ROOT_IS_LINK")', "pass"),
    ], "tests/test_gate.py tests/test_api_case.py"),
    ("闸门·云同步目录（环境变量、注册表、目录名）", "case/gate.py", [
        ("def in_sync_folder(path: str) -> bool:\n", "def in_sync_folder(path: str) -> bool:\n    return False\n"),
    ], "tests/test_gate.py tests/test_api_case.py"),
    ("标准目录·只补缺不改已有文件夹", "case/gate.py", [
        ("    if os.path.lexists(path):\n        return False\n", ""),
    ], "tests/test_api_case.py tests/test_gate.py"),
    ("白名单·主机和端口", "net.py", [
        ("return hp[0] == LOOPBACK or hp in self._targets", "return True"),
    ], "tests/test_net.py"),
    ("白名单·不跟随重定向（3xx 视为错误）", "net.py", [
        ("    if response.is_redirect or 300 <= response.status_code < 400:", "    if False:"),
    ], "tests/test_net.py"),
    ("白名单·不读系统代理", "net.py", [
        ("follow_redirects=False, trust_env=False, transport=transport,\n            timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=CONNECT_TIMEOUT),\n            event_hooks={\"request\": [lambda r",
         "follow_redirects=False, trust_env=True, transport=transport,\n            timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=CONNECT_TIMEOUT),\n            event_hooks={\"request\": [lambda r"),
    ], "tests/test_net.py"),
    ("地址选择·所内不通改用所外", "net.py", [
        ("        if self._servers.get(alt_key):\n", "        if False:\n"),
    ], "tests/test_net.py tests/test_api_case.py"),
    ("地址选择·60 秒缓存", "net.py", [
        ("if cached and not force and cached[2] > now:", "if False:"),
    ], "tests/test_net.py"),
    ("本机转发·其余路径 404", "net.py", [
        ('Route("/v1/models", handle, methods=["GET"])', 'Route("/{p:path}", handle, methods=["GET", "POST"])'),
        ("op = _FORWARD_ROUTES.get((request.method, request.url.path))",
         'op = _FORWARD_ROUTES.get((request.method, request.url.path), "other")'),
    ], "tests/test_net.py"),
    ("令牌·缺令牌返回 401", "app.py", [
        ('if request.url.path != "/health":', "if False:"),
    ], "tests/test_api_case.py tests/test_main.py"),
    ("胶囊·PUT 校验（Skill、工具、不能删、shared/hint）", "capsules.py", [
        ("        reason = self._check(data, default)\n", "        reason = None\n"),
    ], "tests/test_api_case.py"),
    ("日志·异常只记类名", "app.py", [
        ('logs.event("api", _op(request), status="fail", error=type(exc).__name__)  # 只记异常类名',
         'logs.event("api", _op(request), status="fail", error=repr(exc))'),
    ], "tests/test_api_case.py"),
]


def run(sel: str) -> tuple[int, str]:
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:warnings", "-p", "no:cacheprovider",
                        *sel.split()], cwd=SERVICE, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    tail = [ln for ln in p.stdout.splitlines() if ln.strip()]
    failed = [ln.split(" - ")[0].replace("FAILED ", "") for ln in tail if ln.startswith("FAILED ")]
    summary = tail[-1] if tail else "(无输出)"
    return p.returncode, summary + ("\n      变红的用例：" + "\n        ".join([""] + failed[:12])
                                     + (f"\n        …共 {len(failed)} 个" if len(failed) > 12 else "")
                                     if failed else "")


def main() -> int:
    originals = {p: p.read_bytes() for p in PKG.rglob("*.py")}
    bad = 0
    print(f"T3 红绿验证：{len(MUTATIONS)} 类防护\n")
    try:
        for i, (label, rel, reps, sel) in enumerate(MUTATIONS, 1):
            f = PKG / rel
            src = f.read_text(encoding="utf-8")
            mutated = src
            for old, new in reps:
                n = mutated.count(old)
                if n != 1:
                    raise SystemExit(f"[{i}] {label}：原文命中 {n} 次（应为 1），脚本需要更新")
                mutated = mutated.replace(old, new)
            try:
                f.write_text(mutated, encoding="utf-8")
                rc_red, sum_red = run(sel)
            finally:
                f.write_bytes(originals[f])
            rc_green, sum_green = run(sel)
            ok = rc_red != 0 and rc_green == 0
            bad += not ok
            print(f"[{i:02d}] {label}\n  改坏 {rel} → {'红' if rc_red else '绿（未变红！）'}：{sum_red}\n"
                  f"  复原 → {'绿' if rc_green == 0 else '红（复原后未变绿！）'}：{sum_green}\n")
    finally:
        for p, data in originals.items():
            if p.read_bytes() != data:
                p.write_bytes(data)
                print(f"[复原] {p}")
    same = all(p.read_bytes() == d for p, d in originals.items())
    print(f"源码与开始时逐字节一致：{'是' if same else '否'}")
    rc, summ = run("tests")
    print(f"复原后全量：{summ}")
    print(f"\n结论：{len(MUTATIONS) - bad}/{len(MUTATIONS)} 类防护 改坏即红、复原即绿")
    return 1 if bad or rc or not same else 0


if __name__ == "__main__":
    sys.exit(main())
