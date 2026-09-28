#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_consistency.py — 技能一致性校验器（"文档编译器"）通用样板

由 skill-creator 的 init_skill.py 自动生成。用途：每次修改技能后运行，
自动检测跨文件一致性缺陷，从根子上拦截"改了一处漏了引用处"类回归
（例如：改了版本号忘了 _meta.json / CHANGELOG / 目录表；改了文件忘了引用路径）。

用法：
    python verify_consistency.py                 # 自动定位技能根目录（脚本位于 <skill>/scripts/ 下）
    python verify_consistency.py /path/to/skill  # 校验指定技能目录
    python verify_consistency.py --quiet         # 只输出 FAIL，不输出 OK

退出码：0 = 全部通过；1 = 存在 FAIL（可用于 CI 门禁 / 打包门禁）

内置校验类：
    V1 版本联动：frontmatter version == _meta.json version == CHANGELOG 最新条目
    V2 引用路径完整性：SKILL.md 中所有相对引用路径存在（references/、templates/、scripts/、assets/）
    V3 CHANGELOG：CHANGELOG.md 存在且最新条目版本 == frontmatter version

如何新增本技能特有的校验类：
    在下方 CUSTOM_CHECKS 区添加函数，返回 (name, issues) 即可，main() 会自动执行。
    issues 为列表，每项 (message, location)；location 用于定位（文件:行号或说明）。
    例如：检查某张表的数据行数 == 某处声明的数量（V3 P0/P2 计数类）。

本文件由 skill-creator 自动生成，可自由裁剪。
"""

import json
import os
import re
import sys

# ============ 配置区 ============

SKILL_FILENAME = "SKILL.md"
META_FILENAME = "_meta.json"
CHANGELOG_FILENAME = "CHANGELOG.md"


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _get_frontmatter_version(skill):
    m = re.search(r'^version:\s*"?([\d.]+)"?', skill, re.MULTILINE)
    return m.group(1) if m else None


# ============ V1 版本联动 ============

def check_version(root):
    """frontmatter version == _meta.json version（若存在）"""
    issues = []
    skill_path = os.path.join(root, SKILL_FILENAME)
    skill = _read(skill_path)
    fm_version = _get_frontmatter_version(skill)

    if not fm_version:
        issues.append(("frontmatter 缺少 version 字段", f"{SKILL_FILENAME}:frontmatter"))
        return ("V1 版本联动", issues)

    meta_path = os.path.join(root, META_FILENAME)
    if os.path.exists(meta_path):
        try:
            meta = json.loads(_read(meta_path))
            meta_v = str(meta.get("version", ""))
            if meta_v != fm_version:
                issues.append((f"_meta.json version {meta_v} != frontmatter {fm_version}", META_FILENAME))
        except json.JSONDecodeError as e:
            issues.append((f"_meta.json 不是合法 JSON: {e}", META_FILENAME))
    else:
        issues.append(("_meta.json 缺失（可删除本校验类或补建 _meta.json）", META_FILENAME))

    return ("V1 版本联动", issues)


# ============ V2 引用路径完整性 ============

def check_references(root):
    """SKILL.md 中 references/ templates/ scripts/ assets/ 相对引用均可达"""
    issues = []
    skill = _read(os.path.join(root, SKILL_FILENAME))
    seen = set()
    for m in re.finditer(r'\[[^\]]*\]\(((?:references|templates|scripts|assets)/[^)]+)\)', skill):
        rel = m.group(1)
        if rel in seen:
            continue
        seen.add(rel)
        target = rel.split("#")[0]  # 去掉锚点
        if not os.path.exists(os.path.join(root, target)):
            issues.append((f"引用路径不存在: {rel}", f"{SKILL_FILENAME}"))
    return ("V2 引用路径", issues)


# ============ V3 CHANGELOG 版本 ============

def check_changelog(root):
    """CHANGELOG.md 存在且最新条目版本 == frontmatter version"""
    issues = []
    skill = _read(os.path.join(root, SKILL_FILENAME))
    fm_version = _get_frontmatter_version(skill)
    cl_path = os.path.join(root, CHANGELOG_FILENAME)

    if not os.path.exists(cl_path):
        issues.append(("CHANGELOG.md 缺失（可删除本校验类或补建 CHANGELOG.md）", CHANGELOG_FILENAME))
        return ("V3 CHANGELOG", issues)

    cl = _read(cl_path)
    m = re.search(r'^## \[([\d.]+)\]', cl, re.MULTILINE)
    if not m:
        issues.append(("CHANGELOG 无版本条目", CHANGELOG_FILENAME))
    elif fm_version and m.group(1) != fm_version:
        issues.append((f"CHANGELOG 最新条目 [{m.group(1)}] != frontmatter {fm_version}", CHANGELOG_FILENAME))

    return ("V3 CHANGELOG", issues)


# ============ 自定义校验区（CUSTOM_CHECKS） ============
# 在此添加本技能特有的校验函数。示例：

# def check_my_rule(root):
#     """示例：某表数据行数 == 某处声明的数量"""
#     issues = []
#     skill = _read(os.path.join(root, SKILL_FILENAME))
#     m = re.search(r'### 我的映射表\n(.*?)(?=\n### |\Z)', skill, re.DOTALL)
#     if not m:
#         issues.append(("找不到映射表", f"{SKILL_FILENAME}"))
#         return ("V4 我的规则", issues)
#     rows = sum(1 for line in m.group(1).splitlines()
#                if re.match(r'^\s*\|.*\|', line) and '|------' not in line and '---' not in line)
#     m2 = re.search(r'共(\d+)项', skill)
#     if m2 and int(m2.group(1)) != rows:
#         issues.append((f"声明 {m2.group(1)} 项，实际 {rows} 行", f"{SKILL_FILENAME}"))
#     return ("V4 我的规则", issues)

def check_description(root):
    """V4 description 一致性 + 精简度。

    两处 description 供不同消费者读取（路由／元数据），必须逐字一致，
    否则会出现"哪一份才是权威"的歧义（2026-09-17 实测曾出现 324 vs 408 字符的漂移）。
    另设长度护栏：description 会注入上下文用于触发判定，过长既挤占预算、
    又易与正文重复；实现细节与历史应写进正文，而非路由描述。
    """
    issues = []
    skill = _read(os.path.join(root, SKILL_FILENAME))
    m = re.search(r'^description:\s*(.+)$', skill, re.MULTILINE)
    fm_desc = m.group(1).strip() if m else ""
    if not fm_desc:
        issues.append(("frontmatter 缺少 description", SKILL_FILENAME))
        return ("V4 description 一致性", issues)

    meta_path = os.path.join(root, META_FILENAME)
    if not os.path.exists(meta_path):
        issues.append((f"{META_FILENAME} 不存在", META_FILENAME))
        return ("V4 description 一致性", issues)
    try:
        meta = json.loads(_read(meta_path))
    except Exception as e:
        issues.append((f"{META_FILENAME} 解析失败：{e}", META_FILENAME))
        return ("V4 description 一致性", issues)

    meta_desc = (meta.get("description") or "").strip()
    if meta_desc != fm_desc:
        issues.append((f"description 不一致：frontmatter {len(fm_desc)} 字符 vs "
                       f"{META_FILENAME} {len(meta_desc)} 字符",
                       f"{SKILL_FILENAME} / {META_FILENAME}"))
    if len(fm_desc) > 220:
        issues.append((f"description 过长（{len(fm_desc)} 字符，护栏 220）："
                       f"实现细节与历史请移入正文", SKILL_FILENAME))
    return ("V4 description 一致性", issues)


CUSTOM_CHECKS = [check_description]


# ============ 运行入口 ============

def _find_skill_root(start):
    """从脚本所在目录向上查找包含 SKILL.md 的技能根目录。"""
    cur = os.path.abspath(start)
    while True:
        if os.path.exists(os.path.join(cur, SKILL_FILENAME)):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def main():
    quiet = "--quiet" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        root = os.path.abspath(args[0])
    else:
        # 无参数时自动定位技能根目录（脚本通常位于 <skill>/scripts/ 下）
        root = _find_skill_root(os.path.dirname(os.path.abspath(__file__)))
        if root is None:
            print(f"错误: 找不到 {SKILL_FILENAME}（从脚本目录向上查找失败），请显式指定技能目录")
            sys.exit(2)

    if not os.path.exists(os.path.join(root, SKILL_FILENAME)):
        print(f"错误: {root} 下找不到 {SKILL_FILENAME}，请指定技能目录")
        sys.exit(2)

    checks = [
        check_version,
        check_references,
        check_changelog,
    ] + CUSTOM_CHECKS

    skill_name = os.path.basename(root)
    all_ok = True
    print(f"=== invoice-ledger-db 一致性校验 ===")
    print(f"目标目录: {root}\n")

    for fn in checks:
        name, issues = fn(root)
        if not issues:
            if not quiet:
                print(f"  [OK] {name}")
        else:
            all_ok = False
            print(f"  [FAIL] {name} ({len(issues)} 项)")
            for msg, loc in issues:
                print(f"      - {msg}")
                print(f"        ↳ {loc}")

    print()
    if all_ok:
        print("✓ 全部校验通过")
        sys.exit(0)
    else:
        print("✗ 存在不一致，请修复后重跑")
        sys.exit(1)


if __name__ == "__main__":
    main()
