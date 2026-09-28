"""契约自检：用 contracts/ 下的 schema 校验 examples/ 下的样例。

用法：python contracts/check_examples.py [--skills <Skill 根目录>]
  --skills  另外校验 capsules.default.json、真实 Skill 的 SKILL.md 头部和归档目录
退出码：全部符合预期为 0，否则为 1。开发工单的契约测试可直接调用本脚本里的 validator()。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = pathlib.Path(__file__).resolve().parent
BASE = "lawbench://contracts/"


def registry() -> Registry:
    reg = Registry()
    for p in ROOT.rglob("*.schema.json"):
        sch = json.loads(p.read_text(encoding="utf-8"))
        reg = reg.with_resource(sch["$id"], Resource.from_contents(sch))
    return reg


REG = registry()


def validator(schema_path: str, pointer: str = "") -> Draft202012Validator:
    """schema_path 如 'tools/case_save_draft.schema.json'，pointer 如 '#/$defs/result'。"""
    return Draft202012Validator({"$ref": BASE + schema_path + pointer}, registry=REG,
                                format_checker=FormatChecker())


def check_manifest() -> int:
    bad = 0
    manifest = json.loads((ROOT / "examples" / "manifest.json").read_text(encoding="utf-8"))
    for case in manifest:
        data = json.loads((ROOT / "examples" / case["file"]).read_text(encoding="utf-8"))
        errs = list(validator(case["schema"], case.get("pointer", "")).iter_errors(data))
        ok = (not errs) == (case["expect"] == "valid")
        if not ok:
            bad += 1
            print(f"[不符合预期] {case['file']} -> {case['schema']}{case.get('pointer','')} 预期 {case['expect']}")
            for e in errs[:5]:
                print("   ", list(e.absolute_path), e.message[:200])
    print(f"样例 {len(manifest)} 个，不符合预期 {bad} 个")
    return bad


def check_skills(root: pathlib.Path) -> int:
    """校验 capsules.default.json、胶囊用到的每个 SKILL.md 头部，以及归档目录 catalogs/*.json。"""
    import yaml
    bad = 0
    fm = validator("skill/frontmatter.schema.json")
    cap = validator("skill/capsules.schema.json")
    cat = validator("skill/archive_catalog.schema.json")
    caps = json.loads((root / "capsules.default.json").read_text(encoding="utf-8"))
    errs = list(cap.iter_errors(caps))
    bad += bool(errs)
    print(("[错] " if errs else "[对] ") + "capsules.default.json", *(e.message[:120] for e in errs[:3]))
    names = set(caps.get("shared", []))
    for g in caps.get("groups", []):
        for it in g.get("items", []):
            names.update(it.get("skills", []))
    for n in sorted(names):
        f = root / n / "SKILL.md"
        if not f.is_file():
            bad += 1
            print("[错] " + n, "找不到 SKILL.md")
            continue
        head = yaml.safe_load(f.read_text(encoding="utf-8").split("---")[1])
        errs = list(fm.iter_errors(head))
        bad += bool(errs)
        print(("[错] " if errs else "[对] ") + n, *(e.message[:120] for e in errs[:3]))
    for f in sorted((root / "case-archiving" / "catalogs").glob("*.json")):
        errs = list(cat.iter_errors(json.loads(f.read_text(encoding="utf-8"))))
        bad += bool(errs)
        print(("[错] " if errs else "[对] ") + "case-archiving/catalogs/" + f.name, *(e.message[:120] for e in errs[:3]))
    return bad


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--skills", type=pathlib.Path)
    a = ap.parse_args()
    n = check_manifest()
    if a.skills:
        n += check_skills(a.skills)
    sys.exit(1 if n else 0)
