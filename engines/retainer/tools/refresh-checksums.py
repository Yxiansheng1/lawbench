# -*- coding: utf-8 -*-
"""
重算哈希清单（模板内容变更后必须执行）

1. original-skill/template-checksums.json  —— 键相对 original-skill
2. _craft_meta.json 的 craft.checksums     —— 键相对项目根，刷新已存在项并增补新模板

用法（项目根目录）： python tools/refresh-checksums.py
"""
import hashlib
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OSKILL = os.path.join(ROOT, "original-skill")


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_docx(base, prefix=""):
    out = {}
    if not os.path.isdir(base):
        return out
    for dirpath, _dirnames, filenames in os.walk(base):
        for fn in sorted(filenames):
            if fn.startswith("~$") or not fn.lower().endswith(".docx"):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, base).replace("\\", "/")
            out[prefix + rel] = sha256_of(full)
    return out


def main():
    # 1) template-checksums.json
    tpl = collect_docx(os.path.join(OSKILL, "templates"), "templates/")
    dst = os.path.join(OSKILL, "template-checksums.json")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(tpl.items())), f, ensure_ascii=False, indent=2)
    print("template-checksums.json 已重算：%d 项" % len(tpl))

    # 2) _craft_meta.json
    meta_path = os.path.join(ROOT, "_craft_meta.json")
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    fresh = {}
    for k in meta["craft"]["checksums"]:
        p = os.path.join(ROOT, k.replace("/", os.sep))
        if os.path.exists(p):
            fresh[k] = "sha256:" + sha256_of(p)
    for k, v in collect_docx(os.path.join(OSKILL, "templates"), "original-skill/templates/").items():
        fresh[k] = "sha256:" + v
    for k, v in collect_docx(os.path.join(ROOT, "resources", "templates"), "resources/templates/").items():
        fresh[k] = "sha256:" + v
    meta["craft"]["checksums"] = dict(sorted(fresh.items()))
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print("_craft_meta.json 已重算：%d 项" % len(fresh))


if __name__ == "__main__":
    main()
