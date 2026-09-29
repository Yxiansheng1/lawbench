r"""T3 红绿验证：逐类"改坏防护 → 跑对应测试应当变红 → 复原 → 变绿"。不用 git stash。

用法（在 service\ 目录）：.venv\Scripts\python ..\docs\plan\evidence\T3\redgreen.py
每个改动都是源码里的精确字符串替换（必须恰好命中一次），跑完一定在 finally 里写回原文，
最后核对源码与开始时逐字节一致，再跑一次全量测试。
"""
from __future__ import annotations

import pathlib
import shlex
import subprocess
import sys

SERVICE = pathlib.Path(__file__).resolve().parents[4] / "service"
PKG = SERVICE / "lawbench"

# (类别, 文件, [(原文, 改坏后)], 测试选择)
MUTATIONS = [
    # 返修后 _relpath 把 relpath 的 ValueError 转成拒绝，也能拦住 Windows 尾点变体（"证据/.../x"），所以三层一起去掉
    ("闸门·上跳 ..（形状检查 + 最终 realpath 校验 + relpath 异常转拒绝一起去掉）", "case/gate.py", [
        ('if p.rstrip(" .") in ("", "..") or p == "..":', "if False:"),
        ("    if not is_within(root, real):\n        raise _deny(op, \"escape\")", "    pass"),
        ('    except ValueError:  # 不同盘符、设备路径等：一律按越界拒绝\n        raise _deny(op, "relpath_error")',
         "    except ValueError:\n        return os.path.basename(path)"),
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
        ("if _real_top(root, path, op) not in (WORK.casefold(), OUTPUT.casefold()):", "if False:"),
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
        ('op = _FORWARD_ROUTES.get((scope["method"], scope["path"]))',
         'op = _FORWARD_ROUTES.get((scope["method"], scope["path"]), "chat")'),
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
    # ---------- 返修（执行令 T3返修-20260929-1950） ----------
    ("R1·settings.json 损坏不阻止启动", "app.py", [
        ("except Exception as e:  # noqa: BLE001 settings.json 损坏",
         "except ZeroDivisionError as e:  # noqa: BLE001 settings.json 损坏"),
    ], "tests/test_t3_rework.py -k r1_"),
    ("R1·capsules.json 损坏不阻止启动、reset 可恢复", "app.py", [
        ("except Exception as e:  # noqa: BLE001 capsules.json 损坏",
         "except ZeroDivisionError as e:  # noqa: BLE001 capsules.json 损坏"),
    ], "tests/test_t3_rework.py -k r1_"),
    ("R2·Windows 设备名", "case/gate.py", [
        ("        if is_device_name(p):\n", "        if False:\n"),
    ], "tests/test_t3_rework.py -k r2_"),
    ("R2·relpath 的 ValueError 转成拒绝", "case/gate.py", [
        ("    except ValueError:  # 不同盘符", "    except ZeroDivisionError:  # 不同盘符"),
    ], "tests/test_t3_rework.py -k r2_"),
    ("R3·原子写遇文件被占用时重试", "contracts.py", [
        ("REPLACE_RETRIES = 10", "REPLACE_RETRIES = 1"),
    ], "tests/test_t3_rework.py -k r3_"),
    ("R4·转发端口绑定失败时进程非零退出", "__main__.py", [
        ("            failed.append(name)\n", "            pass\n"),
    ], "tests/test_t3_rework.py -k r4_"),
    ("R5·case.db 版本不对拒绝打开", "case/registry.py", [
        ('                        raise ApiError("INVALID_ARGUMENT", "case_db_version")',
         "                        return row[0]"),
    ], "tests/test_t3_rework.py -k r5_"),
    ("R5·错误日志带原因代号", "app.py", [
        ('error = f"{exc.code}:{exc.reason}" if exc.reason else exc.code', "error = exc.code"),
    ], "tests/test_t3_rework.py -k r5_"),
    ("R6·工作台 500 用中间件返回、不断开连接", "app.py", [
        ("except Exception as exc:  # noqa: BLE001 内部异常", "except ZeroDivisionError as exc:  # noqa: BLE001 内部异常"),
    ], "tests/test_t3_rework.py tests/test_api_case.py -k 'r6_ or internal'"),
    ("R6·转发在回响应头之前的其他 httpx 异常记 fail 并返回 502", "net.py", [
        ('            except httpx.HTTPError as e:\n                finish("fail", type(e).__name__)\n'
         '                await _send_simple(send, 502, _error_body("SERVER_UNREACHABLE"))\n', ""),
    ], "tests/test_t3_rework.py -k r6_"),
    ("R6·转发流式中途上游断开记 fail", "net.py", [
        ('finish("fail", type(e).__name__)  # 上游流式中途断开', 'finish("ok", None)  # 上游流式中途断开'),
    ], "tests/test_t3_rework.py -k r6_"),
    ("R8·回响应头之前客户端断开即取消上游", "net.py", [
        ("                        cancel_scope.cancel()\n                    return\n",
         "                    return\n"),
    ], "tests/test_t3_rework.py -k r8_"),
    ("R9·转发端口检查 Host、拒绝 Origin", "net.py", [
        ('if op is None or host not in (f"{LOOPBACK}:{port}", f"localhost:{port}") or "origin" in headers:',
         "if op is None:"),
    ], "tests/test_t3_rework.py -k r9_"),
    ("R10·6000D 地址不能是转发端口自己", "net.py", [
        ("        if not self.forward_port:\n            return\n", "        return\n"),
    ], "tests/test_t3_rework.py -k r10_"),
    ("R11·拒绝盘符根目录", "case/gate.py", [
        ('    if os.path.splitdrive(real)[1] in ("", os.sep):\n', "    if False:\n"),
    ], "tests/test_t3_rework.py -k r11_"),
    ("R11·拒绝包含应用数据目录的根目录", "case/gate.py", [
        ("        if _norm(ad) == _norm(real) or is_within(real, ad):", "        if False:"),
    ], "tests/test_t3_rework.py -k r11_"),
    ("R12·标准目录某一级已是 junction 时跳过", "case/gate.py", [
        ("        if is_link(cur):\n            return False\n", ""),
    ], "tests/test_t3_rework.py -k r12_"),
]


def run(sel: str) -> tuple[int, str]:
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:warnings", "-p", "no:cacheprovider",
                        *shlex.split(sel)], cwd=SERVICE, capture_output=True, text=True, encoding="utf-8",
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
