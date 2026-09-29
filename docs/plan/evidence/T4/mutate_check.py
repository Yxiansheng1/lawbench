"""check_plugin_tree.py 的变异验证（T4 第二轮返修 P3-B）。

对真实输入逐一做一处篡改，确认检查脚本报出；不篡改时必须通过。
用法：python mutate_check.py plugin-inventory-desktop.json plugin-tree.txt
"""
import json, pathlib, subprocess, sys, tempfile

inv_path, tree_path = map(pathlib.Path, sys.argv[1:3])
here = pathlib.Path(__file__).parent
inv_src = inv_path.read_text(encoding="utf-8")
tree_src = tree_path.read_text(encoding="utf-8-sig")


def drop_entry(entry_id):
    d = json.loads(inv_src)
    d["result"]["value"]["entries"] = [e for e in d["result"]["value"]["entries"] if e["entryId"] != entry_id]
    return json.dumps(d, ensure_ascii=False)


def replace_once(old, new):
    """只在 preset-lawbench 段内替换第一处（别的 preset 里可能有同样的文本）。"""
    start = tree_src.index("id: preset-lawbench")
    pos = tree_src.index(old, start)
    return tree_src[:pos] + new + tree_src[pos + len(old):]


# 在 preset-lawbench 段内把内置目录插到数组最前面（导出会把 !!js 折成多行，按锚点文本替换）
seg_start = tree_src.index("id: preset-lawbench")
anchor = "[process.getBuiltinModule('node:path').join(process.env.ProgramData"
pos = tree_src.index(anchor, seg_start)
swapped_tree = tree_src[:pos] + "[process.env.LAWBENCH_SKILLS_DIR, " + tree_src[pos + 1:]
CASES = [
    ("基线（不篡改）", inv_src, tree_src, 0, "通过"),
    ("必须关的行从清单里消失：ui-sidebar-browser", drop_entry("include:ui-sidebar-browser"), tree_src, 1, "不存在（id 写错或 DSH 提交变了）：ui-sidebar-browser"),
    ("skill-filesystem.includeDefaultRoots 改为 true", inv_src,
     replace_once("includeDefaultRoots: false", "includeDefaultRoots: true"), 1, "skill-filesystem.includeDefaultRoots 不符"),
    ("customSkillDirs 两个目录顺序对调", inv_src,
     swapped_tree, 1, "customSkillDirs 管理员目录在前 不符"),
    ("persona.complete 改为 false", inv_src,
     replace_once("complete: true", "complete: false"), 1, "persona.complete 不符"),
    ("persona.prefix 去掉\"不是给你的指令\"", inv_src,
     replace_once("不是给你的指令", "是案卷内容"), 1, "persona.prefix 含身份与不执行材料指令两条 不符"),
]

failed = 0
with tempfile.TemporaryDirectory() as tmp:
    for name, inv, tree, want_rc, want_text in CASES:
        pi, pt = pathlib.Path(tmp, "inv.json"), pathlib.Path(tmp, "tree.txt")
        pi.write_text(inv, encoding="utf-8")
        pt.write_text(tree, encoding="utf-8")
        r = subprocess.run([sys.executable, str(here / "check_plugin_tree.py"), str(pi), str(pt)],
                           capture_output=True, text=True, encoding="utf-8", env={"PYTHONIOENCODING": "utf-8", **__import__("os").environ})
        ok = r.returncode == want_rc and want_text in r.stdout
        failed += not ok
        print(f"{'OK  ' if ok else 'FAIL'} {name}：退出码 {r.returncode}（期望 {want_rc}），输出{'含' if want_text in r.stdout else '不含'}「{want_text}」")
print("结论：", "变异全部被报出，基线通过" if not failed else f"{failed} 项不符合预期")
sys.exit(1 if failed else 0)
