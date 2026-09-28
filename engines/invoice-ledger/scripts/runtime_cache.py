"""Offline runtime cache. Standard library only; import never writes."""
import contextlib
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath

SKILL_ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = SKILL_ROOT / "vendor"
ENV_ZIP = VENDOR_DIR / "env-win_amd64.zip"
ENV_LOCK = VENDOR_DIR / "env.lock"
EXEMPT = frozenset({"build_env_zip.py", "env_check.py", "package_skill.py"})
DEPS = ["openpyxl", "et_xmlfile", "pdfplumber", "pdfminer", "PIL", "pypdfium2", "cryptography", "charset_normalizer",
        "winsdk.windows.media.ocr", "winsdk.windows.graphics.imaging",
        "winsdk.windows.storage", "winsdk.windows.globalization"]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1048576), b""):
            h.update(block)
    return h.hexdigest()


def read_lock():
    lock = json.loads(ENV_LOCK.read_text(encoding="utf-8"))
    z = lock["zip"]
    if (lock.get("schema") != 2 or lock.get("platform_tag") != "win-amd64"
            or z.get("name") != ENV_ZIP.name
            or not re.fullmatch(r"[0-9a-f]{64}", z.get("sha256", ""))
            or not isinstance(z.get("size"), int) or z["size"] <= 0
            or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", lock.get("python_version", ""))
            or not re.fullmatch(r"[0-9a-f]{64}", lock.get("manifest_sha256", ""))):
        raise RuntimeError("env.lock 格式无效或不是 schema 2；请获取完整新版环境包")
    return lock


def verify_archive(lock):
    if ENV_ZIP.stat().st_size != lock["zip"]["size"] or sha256(ENV_ZIP) != lock["zip"]["sha256"]:
        raise RuntimeError("环境包大小或 SHA256 与 env.lock 不符")


def cache_root():
    override = os.environ.get("INVOICE_RUNTIME_CACHE")
    root = Path(override) if override else Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "invoice-ledger-db/runtimes"
    if not root.is_absolute():
        raise RuntimeError("INVOICE_RUNTIME_CACHE 必须是绝对路径")
    root = root.resolve()
    if root == SKILL_ROOT or SKILL_ROOT in root.parents:
        raise RuntimeError("运行缓存必须位于技能目录之外")
    # Long package license paths exceed MAX_PATH after adding the content hash.
    value = str(root)
    if os.name == "nt" and not value.startswith("\\\\?\\"):
        value = "\\\\?\\UNC\\" + value[2:] if value.startswith("\\\\") else "\\\\?\\" + value
    return Path(value)


def bucket(lock):
    return cache_root() / lock["platform_tag"] / lock["zip"]["sha256"]


def selected(lock):
    try:
        name = json.loads((bucket(lock) / "active.json").read_text(encoding="utf-8"))["generation"]
        if not re.fullmatch(r"gen-[0-9a-f]{32}", name):
            return None
        p = bucket(lock) / name
        return p if p.is_dir() and not p.is_symlink() else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def safe_relative(name):
    p = PurePosixPath(name)
    if not name or "\\" in name or ":" in name or p.is_absolute() or ".." in p.parts:
        raise RuntimeError(f"非法环境包路径：{name}")
    return p


def verify_files(root, lock, deep=False, ready=True):
    if ready:
        mark = json.loads((root / "ready.json").read_text(encoding="utf-8"))
        if mark != {"schema": 1, "archive_sha256": lock["zip"]["sha256"], "manifest_sha256": lock["manifest_sha256"]}:
            raise RuntimeError("缓存完成标记与环境包不一致")
    mf = root / "MANIFEST.tsv"
    if sha256(mf) != lock["manifest_sha256"]:
        raise RuntimeError("缓存文件清单不一致")
    seen = set()
    for line in mf.read_text(encoding="utf-8").splitlines():
        name, size, digest = line.split("\t")
        p = root / safe_relative(name)
        if name in seen or p.is_symlink() or root.resolve() not in p.resolve().parents:
            raise RuntimeError(f"缓存路径异常：{name}")
        seen.add(name)
        if not p.is_file() or p.stat().st_size != int(size) or (deep and sha256(p) != digest):
            raise RuntimeError(f"缓存文件损坏或缺失：{name}")
    if len(seen) != lock["file_count"] or "python.exe" not in seen:
        raise RuntimeError("缓存清单文件数不一致或缺少解释器")
    if deep:
        extras = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()} - seen - {"MANIFEST.tsv", "ready.json"}
        if extras:
            raise RuntimeError(f"缓存存在额外文件：{sorted(extras)[:5]}")


def health(root, lock):
    code = ("import sys,importlib,importlib.metadata; " + f"assert sys.version.split()[0] == {lock['python_version']!r}; "
            + f"[importlib.import_module(m) for m in {DEPS!r}]; "
            + f"expected={lock['packages']!r}; "
            + "assert all(importlib.metadata.version(k)==v for k,v in expected.items()); print('ALL_OK')")
    r = subprocess.run([str(root / "python.exe"), "-B", "-c", code], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=45)
    if r.returncode or r.stdout.strip() != "ALL_OK":
        raise RuntimeError(f"解释器或依赖自检失败：{r.stderr[-600:]}")


@contextlib.contextmanager
def build_lock(folder):
    import msvcrt
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / "build.lock", "a+b") as f:
        if f.seek(0, 2) == 0:
            f.write(b"0")
            f.flush()
        deadline = time.monotonic() + 45
        while True:
            try:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("等待环境构建锁超时；请在另一任务完成后重试")
                time.sleep(0.1)
        try:
            yield
        finally:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)


def usable(lock):
    p = selected(lock)
    if p:
        try:
            verify_files(p, lock)
            return p
        except (OSError, ValueError, KeyError, TypeError, RuntimeError):
            pass
    return None


def ensure_runtime(force=False):
    if os.name != "nt" or platform.machine().lower() not in ("amd64", "x86_64"):
        raise RuntimeError("当前环境包仅支持 Windows AMD64")
    lock = read_lock()
    verify_archive(lock)
    p = usable(lock)
    if p and not force:
        return p
    folder = bucket(lock)
    with build_lock(folder):
        p = usable(lock)
        if p and not force:
            return p
        temp = Path(tempfile.mkdtemp(prefix=".build-", dir=folder))
        try:
            print("[ENV] 校验并展开到外部缓存 ...", flush=True)
            with zipfile.ZipFile(ENV_ZIP) as z:
                seen = set()
                for info in z.infolist():
                    name = info.filename
                    safe_relative(name)
                    if name.casefold() in seen or (info.external_attr >> 16) & 0o170000 == 0o120000:
                        raise RuntimeError("环境包存在重复路径或符号链接")
                    seen.add(name.casefold())
                    z.extract(info, temp)
            verify_files(temp, lock, deep=True, ready=False)
            health(temp, lock)
            (temp / "ready.json").write_text(json.dumps({"schema": 1,
                "archive_sha256": lock["zip"]["sha256"], "manifest_sha256": lock["manifest_sha256"]}), encoding="utf-8")
            target = folder / ("gen-" + uuid.uuid4().hex)
            os.replace(temp, target)
            pointer = folder / (".active-" + uuid.uuid4().hex)
            pointer.write_text(json.dumps({"generation": target.name}), encoding="utf-8")
            os.replace(pointer, folder / "active.json")
            return target
        finally:
            if temp.exists() and temp.parent.resolve() == folder.resolve() and temp.name.startswith(".build-"):
                shutil.rmtree(temp)


def command(root, argv):
    bootstrap = ("import sys,runpy; from pathlib import Path; target=sys.argv[1]; sys.argv=sys.argv[1:]; "
                 + f"sys.path.insert(0,{str(SKILL_ROOT / 'scripts')!r}); "
                 + "sys.path.insert(0,str(Path(target).resolve().parent)); runpy.run_path(target,run_name='__main__')")
    return [str(root / "python.exe"), "-B", "-c", bootstrap] + list(argv)


def run_in_env(argv=None):
    try:
        hops = int(os.environ.get("INVOICE_RUNTIME_HOPS", "0"))
        if hops >= 3:
            raise RuntimeError("环境重复转发超过限制，请运行 env_check.py --deep")
        root = ensure_runtime()
        env = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", INVOICE_RUNTIME_HOPS=str(hops + 1))
        return subprocess.run(command(root, sys.argv if argv is None else argv), env=env).returncode
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError, zipfile.BadZipFile) as e:
        print(f"[ENV][FATAL] {e}", file=sys.stderr)
        return 1


def guard(entry_file):
    if Path(entry_file).name in EXEMPT or Path(sys.argv[0]).resolve() != Path(entry_file).resolve():
        return
    try:
        root = ensure_runtime()
        if Path(sys.executable).resolve() == (root / "python.exe").resolve():
            # lawbench 律所内部版：经周海沺律师同意（2026-09-28）移除设备授权校验
            return
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError, zipfile.BadZipFile) as e:
        print(f"[ENV][FATAL] {e}", file=sys.stderr)
        sys.exit(1)
    sys.exit(run_in_env())


def main():
    import argparse
    ap = argparse.ArgumentParser(description="准备外部运行缓存；--repair 强制建立新副本，保留旧副本")
    ap.add_argument("--repair", action="store_true")
    args = ap.parse_args()
    try:
        print(ensure_runtime(force=args.repair))
        return 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError, zipfile.BadZipFile) as e:
        print(f"[ENV][FATAL] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
