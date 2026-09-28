# -*- coding: utf-8 -*-
"""build_env_zip.py — 构建技能内自带运行环境包（开发机执行，允许联网）

产出：
  vendor/env-win_amd64.zip   自含解释器 + 依赖的环境包（单文件，随技能走）
  vendor/env.lock            zip 的 sha256/大小、解释器来源与校验值、依赖版本清单

步骤：
  1/5 取 embeddable 解释器（优先用本地 vendor/python-embed-amd64.zip，否则联网下载）
  2/5 解压并改写 _pth，仅保留运行环境路径；技能脚本目录由启动器注入
  3/5 用宿主 pip 把依赖装到 Lib/site-packages（cp tag 必须与 embeddable 一致）
  4/5 生成 MANIFEST.tsv（相对路径 / 大小 / sha256）
  5/5 压缩为 env-win_amd64.zip 并写入 env.lock

用法：
  python scripts/build_env_zip.py [--py-version 3.12.10] [--keep-tmp]

注意：
 - 本脚本豁免自举（见 _deps.EXEMPT），必须用宿主 Python 运行
 - 运行期永不联网；联网仅发生在构建期
 - 宿主的 Python 次版本必须与 --py-version 一致，否则二进制 wheel 不匹配
"""
import argparse
import os
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = SKILL_ROOT / "vendor"
ENV_ZIP = VENDOR_DIR / "env-win_amd64.zip"
ENV_LOCK = VENDOR_DIR / "env.lock"
EMB_LOCAL = VENDOR_DIR / "python-embed-amd64.zip"
EMB_URL_TPL = "https://www.python.org/ftp/python/{v}/python-{v}-embed-amd64.zip"

# 依赖清单（版本取自 2026-09-16 实测的本机用户级 site-packages）
# 注：xlwt 已于 3.5.0 移除（唯一使用者 export_to_excel 无调用点，已删）；导出一律走 openpyxl
PACKAGES = [
    "openpyxl==3.1.5",
    "et-xmlfile==2.0.0",
    "pdfplumber==0.11.9",
    "pdfminer.six==20251230",
    "pillow==12.1.1",
    "pypdfium2==5.6.0",
    "cryptography==46.0.5",
    "charset-normalizer==3.4.5",
    "winsdk==1.0.0b10",
]

# _pth 追加项（相对路径，相对环境根目录）
PTH_EXTRA = ["Lib\\site-packages"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def host_tag() -> str:
    return f"cp{sys.version_info.major}{sys.version_info.minor}"


def fetch_embeddable(ver: str, dst: Path) -> str:
    """本地优先，其次联网下载。返回来源 URL 或 'local'。"""
    if EMB_LOCAL.is_file():
        print(f"[1/5] 使用本地解释器包：{EMB_LOCAL}")
        shutil.copy2(str(EMB_LOCAL), str(dst))
        return "local"

    url = EMB_URL_TPL.format(v=ver)
    print(f"[1/5] 下载 embeddable：{url}")
    urllib.request.urlretrieve(url, str(dst))
    return url


def patch_pth(root: Path) -> None:
    pths = sorted(root.glob("python3*._pth"))
    if not pths:
        raise RuntimeError("未找到 python3xx._pth，embeddable 包结构异常")
    p = pths[0]
    lines = p.read_text(encoding="utf-8").splitlines()
    keep = [ln for ln in lines if ln.strip() and not ln.strip().startswith("#") and ln.strip() != "..\\..\\scripts"]
    for extra in PTH_EXTRA:
        if extra not in keep:
            keep.append(extra)
    # 硬门禁：不允许任何绝对路径（换机器即失效）
    for ln in keep:
        if len(ln) > 2 and ln[1] == ":":
            raise RuntimeError(f"_pth 含绝对路径，禁止：{ln}")
    p.write_text("\n".join(keep) + "\n", encoding="utf-8")
    print(f"[2/5] _pth 改写完成：{p.name} → {keep}")


def install_deps(env_root: Path) -> None:
    site = env_root / "Lib" / "site-packages"
    site.mkdir(parents=True, exist_ok=True)
    print(f"[3/5] 安装依赖 → {site.name}（仅二进制 wheel，不编译）...")
    cmd = [sys.executable, "-m", "pip", "install", "--no-cache-dir",
           "--only-binary=:all:", "--no-compile", "--target", str(site)] + PACKAGES
    subprocess.run(cmd, check=True)


def write_manifest(env_root: Path) -> int:
    mf = env_root / "MANIFEST.tsv"
    rows = []
    for p in sorted(env_root.rglob("*")):
        if p.is_file() and p.name != "MANIFEST.tsv":
            rows.append(f"{p.relative_to(env_root).as_posix()}\t{p.stat().st_size}\t{sha256(p)}")
    mf.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"[4/5] MANIFEST.tsv：{len(rows)} 个文件")
    return len(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description="构建技能内自带运行环境包")
    ap.add_argument("--py-version", default="3.12.10", help="embeddable 版本，须与宿主次版本一致")
    ap.add_argument("--keep-tmp", action="store_true", help="保留临时目录以便排查")
    ap.add_argument("--repack", action="store_true", help="离线验证并重打包现有环境，保留依赖版本")
    args = ap.parse_args()

    emb_minor = ".".join(args.py_version.split(".")[:2])
    host_minor = f"{sys.version_info.major}.{sys.version_info.minor}"
    if not args.repack and emb_minor != host_minor:
        print(f"[FATAL] 宿主 Python 为 {host_minor}，与 --py-version {emb_minor} 不一致，"
              f"二进制 wheel 不匹配。请改用与 {host_minor} 对应的 embeddable 版本。")
        return 1

    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="invoice_env_"))
    try:
        env_root = tmp / "env"
        previous = None
        if args.repack:
            previous = json.loads(ENV_LOCK.read_text(encoding="utf-8"))
            if sha256(ENV_ZIP) != previous["zip"]["sha256"] or ENV_ZIP.stat().st_size != previous["zip"]["size"]:
                raise RuntimeError("现有环境包与锁文件不一致")
            with zipfile.ZipFile(ENV_ZIP) as zf:
                from runtime_cache import safe_relative
                for name in zf.namelist():
                    safe_relative(name)
                zf.extractall(env_root)
            source = previous["embeddable"]["source"]
            emb_sha = previous["embeddable"]["sha256"]
        else:
            emb = tmp / "python-embed.zip"
            source = fetch_embeddable(args.py_version, emb)
            emb_sha = sha256(emb)
            with zipfile.ZipFile(emb) as zf:
                zf.extractall(env_root)
            install_deps(env_root)
        patch_pth(env_root)
        # Bytecode is regenerated when needed; never distribute interpreter-specific caches.
        for cache in list(env_root.rglob("__pycache__")):
            shutil.rmtree(cache)
        for cache in env_root.rglob("*.pyc"):
            cache.unlink()
        n_files = write_manifest(env_root)

        print("[5/5] 压缩并写入 env.lock ...")
        zip_candidate = tmp / ENV_ZIP.name
        with zipfile.ZipFile(zip_candidate, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(env_root.rglob("*")):
                if p.is_file():
                    zf.write(p, p.relative_to(env_root).as_posix())

        lock = {
            "schema": 2,
            "built_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "platform_tag": "win-amd64",
            "python_version": previous["python_version"] if previous else args.py_version,
            "host_tag": previous["host_tag"] if previous else host_tag(),
            "zip": {
                "name": ENV_ZIP.name,
                "size": zip_candidate.stat().st_size,
                "sha256": sha256(zip_candidate),
            },
            "embeddable": {"source": source, "sha256": emb_sha},
            "packages": previous["packages"] if previous else {p.split("==")[0]: p.split("==")[1] for p in PACKAGES},
            "file_count": n_files,
            "manifest_sha256": sha256(env_root / "MANIFEST.tsv"),
        }
        lock_candidate = tmp / ENV_LOCK.name
        lock_candidate.write_text(json.dumps(lock, ensure_ascii=False, indent=2), encoding="utf-8")
        # Build in a staging copy; a concurrent reader fails closed during the pair update.
        shutil.copy2(zip_candidate, VENDOR_DIR / (ENV_ZIP.name + ".new"))
        shutil.copy2(lock_candidate, VENDOR_DIR / (ENV_LOCK.name + ".new"))
        os.replace(VENDOR_DIR / (ENV_ZIP.name + ".new"), ENV_ZIP)
        os.replace(VENDOR_DIR / (ENV_LOCK.name + ".new"), ENV_LOCK)

        print(f"[OK] {ENV_ZIP}  ({lock['zip']['size'] / 1048576:.1f} MB / {n_files} 文件)")
        print(f"[OK] {ENV_LOCK}")
        print("[OK] 下一步：运行 invoke.py；新指纹将自动建立外部缓存")
        return 0
    except Exception as e:
        print(f"[FATAL] 构建失败：{type(e).__name__}: {e}")
        return 1
    finally:
        if not args.keep_tmp:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
