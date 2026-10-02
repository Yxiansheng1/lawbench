r"""从一个已装好的 site-packages 回装出离线 wheelhouse（T20 步骤 3 第 2 条，开发期凑轮子用）。

用法：python packaging\python\repack_wheels.py --site <site-packages> [--site …] --pins <requirements.txt> --out <wheelhouse>
每个要的包按它自己的 dist-info：RECORD 列出的文件（只取 site-packages 之内的）+ dist-info 本身，WHEEL 里的标签，
重新打成 <名>-<版本>-<标签>.whl。回装的轮子内容与当初装进去的一致，但**不是 PyPI 上的原文件**（哈希对不上）：
正式构建应在能联网的构建机上 pip download 原始轮子（versions.lock 按原文件记哈希）。缺的包列出来。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import pathlib
import re
import sys
import zipfile
from importlib.metadata import PathDistribution


def norm(n: str) -> str:
    return re.sub(r"[-_.]+", "-", n).lower()


def record_line(arc: str, data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    return f"{arc},sha256={digest},{len(data)}"


def repack(site: pathlib.Path, meta: pathlib.Path, out: pathlib.Path) -> pathlib.Path:
    d = PathDistribution(meta)
    wheel_txt = (meta / "WHEEL").read_text(encoding="utf-8")
    tags = [l.split(":", 1)[1].strip().split("-") for l in wheel_txt.splitlines() if l.startswith("Tag:")]
    # 文件名要带全部标签（如 py2.py3-none-any），只取第一行 pip 会认为装不上
    part = lambda i: ".".join(dict.fromkeys(t[i] for t in tags))  # noqa: E731
    tag = f"{part(0)}-{part(1)}-{part(2)}" if tags else "py3-none-any"
    name = re.sub(r"[-.]+", "_", d.metadata["Name"])
    whl = out / f"{name}-{d.version}-{tag}.whl"
    files: list[str] = []
    for row in (meta / "RECORD").read_text(encoding="utf-8").splitlines():
        arc = row.rsplit(",", 2)[0].strip('"')
        if not arc or arc.startswith("..") or arc.endswith(".pyc") or "/__pycache__/" in f"/{arc}":
            continue  # 脚本目录（../../Scripts）、字节码不进轮子
        if arc.endswith("/RECORD") and arc.startswith(meta.name):
            continue
        if (site / arc).is_file():
            files.append(arc)
    rec_name = f"{meta.name}/RECORD"
    lines = []
    with zipfile.ZipFile(whl, "w", zipfile.ZIP_DEFLATED) as z:
        for arc in sorted(set(files)):
            data = (site / arc).read_bytes()
            z.writestr(arc, data)
            lines.append(record_line(arc, data))
        lines.append(f"{rec_name},,")
        z.writestr(rec_name, "\n".join(lines) + "\n")
    return whl


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True, type=pathlib.Path, action="append", help="可给多次；同名包以先给的为准")
    ap.add_argument("--pins", required=True, type=pathlib.Path)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    metas: dict[str, tuple[pathlib.Path, pathlib.Path]] = {}
    for site in a.site:
        for m in site.glob("*.dist-info"):
            metas.setdefault(norm(PathDistribution(m).metadata["Name"]), (site, m))
    missing, made = [], 0
    for line in a.pins.read_text(encoding="utf-8").splitlines():
        if "==" not in line:
            continue
        n, v = line.strip().split("==", 1)
        hit = metas.get(norm(n))
        if hit is None or PathDistribution(hit[1]).version != v:
            missing.append(line.strip())
            continue
        repack(hit[0], hit[1], a.out)
        made += 1
    print(f"回装 {made} 个；缺 {len(missing)} 个：{', '.join(missing) or '无'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
