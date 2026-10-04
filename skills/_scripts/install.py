"""把胶囊配置用到的 Skill 和 capsules.default.json，按 Spec 10.1–10.3 的目录结构复制到 DSH 加载目录。

用法：
    python install.py --out "<安装目录>\\skills"
    python install.py --skills-dir "D:\\新建文件夹\\skill临时文件夹" --out "D:\\lawbench\\skills"
    python install.py --out ... --strict           # 发版：测试集、owner 不全就不安装
    python install.py --out ... --dry-run          # 只打印要做什么

结果（Spec 10.1 的 <安装目录>/skills/ 或管理员下发目录）：
    <out>/
    ├─ <skill-id>/                胶囊配置用到的每个 Skill（默认不带 tests/）
    ├─ capsules.default.json      默认胶囊（律师点"恢复默认"时用它覆盖本机配置）
    ├─ manifest.json              胶囊 -> Skill、每个 Skill 的头部信息和 SKILL.md 的 sha256
    └─ .generated-by-install      标记文件：有它才允许下次整目录重建

dsh-skill-filesystem 的 customSkillDirs 指向 <out>（Spec 3.1、10.1）。
安装前先以 --check 模式跑 build_skills.py，没同步或有错误就不安装。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_skills  # noqa: E402
import skill_manifest as M  # noqa: E402

MARKER = ".generated-by-install"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_reset(out: Path, src: Path, dry: bool) -> None:
    """清空输出目录。只清空由本脚本生成的目录，防止误删。"""
    if out == src or src in out.parents or out in src.parents:
        raise SystemExit(f"输出目录 {out} 不能与 Skill 源目录 {src} 重叠")
    if not out.exists():
        return
    if not (out / MARKER).is_file():
        if any(out.iterdir()):
            raise SystemExit(f"{out} 已存在且不是 install.py 生成的（没有 {MARKER}），拒绝覆盖")
        return
    if dry:
        print(f"[dry-run] 删除旧目录 {out}")
    else:
        shutil.rmtree(out)


def main() -> int:
    build_skills.setup_console()
    ap = argparse.ArgumentParser(description="按胶囊配置安装 Skill")
    ap.add_argument("--skills-dir", type=Path, default=Path(__file__).resolve().parent.parent,
                    help="Skill 源目录（默认：本脚本上一级目录）")
    ap.add_argument("--out", type=Path, required=True, help="输出目录（DSH 加载 Skill 的位置）")
    ap.add_argument("--strict", action="store_true", help="按发版标准校验")
    ap.add_argument("--include-tests", action="store_true", help="连 tests/ 一起复制（默认不带样本材料）")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不复制")
    args = ap.parse_args()

    src = args.skills_dir.resolve()
    out = args.out.resolve()

    rep = build_skills.run(src, check_only=True, strict=args.strict)
    if rep.errors or rep.changed:
        print(f'校验未通过，先运行：python build_skills.py --root "{src}"')
        for e in rep.errors:
            print(f"  ✘ {e}")
        if rep.changed:
            print(f"  ✘ 共用规则未同步：{', '.join(rep.changed)}")
        return 1

    safe_reset(out, src, args.dry_run)
    ignore_list = list(M.COPY_IGNORE) + ([] if args.include_tests else ["tests"])
    ignore = shutil.ignore_patterns(*ignore_list)
    skills = build_skills.managed_skills(rep.capsules, rep.shared)

    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        # 只记源目录名，不记构建机上的绝对路径（T20 候选包复核 P3-2：装好的程序里出现构建机路径）
        "source": src.name,
        "capsules": [{"group": c.group, "id": c.id, "name": c.name, "kind": c.kind, "skills": c.skills,
                      "tool": c.tool} for c in rep.capsules],
        "shared": rep.shared,
        "skills": {},
    }
    for name in skills:
        meta = rep.metas[name]
        manifest["skills"][name] = {
            "title": meta.get("title"), "mode": meta.get("mode"), "kind": meta.get("kind"),
            "params": meta.get("params"),
            "owner": meta.get("owner"), "inputs": meta.get("inputs"),
            "sha256": sha256(src / name / "SKILL.md"),
        }
        if args.dry_run:
            print(f"[dry-run] {src / name} -> {out / name}")
        else:
            shutil.copytree(src / name, out / name, ignore=ignore)

    if args.dry_run:
        print(f"[dry-run] {src / M.CAPSULES_FILE} -> {out / M.CAPSULES_FILE}")
    else:
        shutil.copy2(src / M.CAPSULES_FILE, out / M.CAPSULES_FILE)
        (out / MARKER).write_text("由 install.py 生成，重新运行会整目录重建，不要手工修改。\n", encoding="utf-8")
        (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                           encoding="utf-8")

    print(f"\n{'[dry-run] ' if args.dry_run else ''}已安装 {len(skills)} 个 Skill、{len(rep.capsules)} 个胶囊到 {out}\n")
    for c in rep.capsules:
        print(f"  {c.group:<6} {c.name:<12} {' → '.join(c.skills) if c.skills else '内置工具 ' + str(c.tool)}")
    print(f"\ncordis.patch.yml 中 skill-filesystem 的 customSkillDirs 加上：{json.dumps(str(out), ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
