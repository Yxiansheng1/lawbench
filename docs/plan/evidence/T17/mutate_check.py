"""check_plugin_tree.py 的变异验证（T17 第二步 N41 增补 6 例；T17 第一步复制并增补：这一批某行被改回启用、静态树里没关、我方行缺失、启用行没激活、不带取证声明时 plugin-inventory 启用；T13 复制并增补"清单外启用行"一例；T4 第二轮返修 P3-B；T7 增补：Skill 目录整项相等、persona 改为读文件、原 credentials 行；T17 第三轮返修增补会话存储配置 3 例）。

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


def enable_entry(entry_id):
    d = json.loads(inv_src)
    for e in d["result"]["value"]["entries"]:
        if e["entryId"] == entry_id:
            e["enabled"] = True
    return json.dumps(d, ensure_ascii=False)


def add_entry(entry_id, module):
    d = json.loads(inv_src)
    d["result"]["value"]["entries"].append({"entryId": entry_id, "moduleName": module, "enabled": True, "fiberPhase": "active"})
    return json.dumps(d, ensure_ascii=False)


def set_phase(entry_id, phase):
    d = json.loads(inv_src)
    for e in d["result"]["value"]["entries"]:
        if e["entryId"] == entry_id:
            e["fiberPhase"] = phase
    return json.dumps(d, ensure_ascii=False)


def tree_enable(row_id):
    """静态树里把某行的 disabled: true 去掉（模拟配置里这一行被删或改回）。"""
    nl = "\r\n" if "\r\n" in tree_src else "\n"
    head = f"- id: {row_id}{nl}"
    pos = tree_src.index(head)
    end = tree_src.index(f"{nl}- ", pos + len(head))
    seg = tree_src[pos:end].replace(f"{nl}  disabled: true", "", 1)
    assert seg != tree_src[pos:end]
    return tree_src[:pos] + seg + tree_src[end:]


def replace_once(old, new):
    """只在 preset-lawbench 段内替换第一处（别的 preset 里可能有同样的文本）。"""
    start = tree_src.index("id: preset-lawbench")
    pos = tree_src.index(old, start)
    return tree_src[:pos] + new + tree_src[pos + len(old):]


# 在 preset-lawbench 段内把内置目录插到数组最前面（导出会把 !!js 折成多行，按锚点文本替换）
seg_start = tree_src.index("id: preset-lawbench")
# T20 起 customSkillDirs 换成打包感知的写法（数组在函数体里，元素用 p.join），锚点随之改
anchor = "[p.join(process.env.ProgramData"
pos = tree_src.index(anchor, seg_start)
swapped_tree = tree_src[:pos] + "[process.env.LAWBENCH_SKILLS_DIR, " + tree_src[pos + 1:]
CASES = [
    ("基线（不篡改）", inv_src, tree_src, 0, "通过"),
    ("必须关的行从清单里消失：ui-sidebar-browser", drop_entry("include:ui-sidebar-browser"), tree_src, 1, "不存在（id 写错或 DSH 提交变了）：ui-sidebar-browser"),
    ("skill-filesystem.includeDefaultRoots 改为 true", inv_src,
     replace_once("includeDefaultRoots: false", "includeDefaultRoots: true"), 1, "skill-filesystem.includeDefaultRoots 不符"),
    ("customSkillDirs 两个目录顺序对调", inv_src,
     swapped_tree, 1, "skill-filesystem.customSkillDirs 整项相等 不符"),
    ("persona.complete 改为 false", inv_src,
     replace_once("complete: true", "complete: false"), 1, "persona.complete 不符"),
    ("persona.prefix 改成读别的文件", inv_src,
     replace_once("lawbench-dsh/persona.md", "lawbench-dsh/other.md"), 1, "persona.prefix 读 lawbench-dsh/persona.md（整项相等） 不符"),
    ("customSkillDirs 多加第三个目录", inv_src,
     replace_once("process.env.LAWBENCH_SKILLS_DIR]", "process.env.LAWBENCH_SKILLS_DIR, 'C:\\\\x']"), 1, "skill-filesystem.customSkillDirs 整项相等 不符"),
    ("原 credentials 行被重新启用", enable_entry("include:credentials"), tree_src, 1, "必须关的行仍启用：credentials"),
    # T13 增补：反向检查本身——多出一个清单外的启用行（冒充我方包名的界面行）必须报出
    ("多出清单外的启用行 legal-ui-extra", add_entry("legal-ui-extra", "lawbench-dsh"), tree_src, 1, "清单外的启用行：legal-ui-extra"),
    # T17 第一步增补
    ("这一批里 session-reference 被改回启用", enable_entry("include:session-reference"), tree_src, 1, "必须关的行仍启用：session-reference"),
    ("这一批里 terminal-controller 被改回启用", enable_entry("include:terminal-controller"), tree_src, 1, "必须关的行仍启用：terminal-controller"),
    ("静态树里 ui-reference 没有关", inv_src, tree_enable("ui-reference"), 1, "静态树里没有关：ui-reference"),
    ("我方 legal-ui 行缺失（组合包没加载）", drop_entry("include:legal-ui"), tree_src, 1, "我方行没有加载或没有激活：legal-ui"),
    ("启用的 ui-chat 没有激活", set_phase("include:ui-chat", "pending"), tree_src, 1, "启用但没有激活：ui-chat"),
    ("不带取证声明时 plugin-inventory 启用", inv_src, tree_src, 1, "必须关的行仍启用：plugin-inventory", []),
    # 第一步补：ui-deliverables 被改回启用（或启用但起不来）都要报出
    ("ui-deliverables 被改回启用", enable_entry("include:ui-deliverables"), tree_src, 1, "必须关的行仍启用：ui-deliverables"),
    # 第二步 N41：成对关的 9 行，Host 半边、界面半边各抽一行改回启用；静态树里没关；从清单里消失
    ("N41：permission 被改回启用", enable_entry("include:permission"), tree_src, 1, "必须关的行仍启用：permission"),
    ("N41：ui-permission 被改回启用", enable_entry("include:ui-permission"), tree_src, 1, "必须关的行仍启用：ui-permission"),
    ("N41：workspace-changes 被改回启用", enable_entry("include:workspace-changes"), tree_src, 1, "必须关的行仍启用：workspace-changes"),
    ("N41：静态树里 ui-model-selection 没有关", inv_src, tree_enable("ui-model-selection"), 1, "静态树里没有关：ui-model-selection"),
    ("N41：静态树里 command-feedback 没有关", inv_src, tree_enable("command-feedback"), 1, "静态树里没有关：command-feedback"),
    ("N41：ui-agent-preset 从清单里消失", drop_entry("include:ui-agent-preset"), tree_src, 1, "必须关的行在清单里不存在（id 写错或 DSH 提交变了）：ui-agent-preset"),
    # 第三步：我方会话存储没加载；会话投影缓存被改回启用
    ("第三步：legal-session-store 缺失", drop_entry("include:legal-session-store"), tree_src, 1, "我方行没有加载或没有激活：legal-session-store"),
    ("第三步：session-projection-cache 被改回启用", enable_entry("include:session-projection-cache"), tree_src, 1, "必须关的行仍启用：session-projection-cache"),
    # 第二步返修：审批写死被改回（读环境变量或改成 never）
    ("返修：approval.policy 改成 never", inv_src, tree_src.replace("policy: ask", "policy: never", 1), 1, "approval 取值不符"),
    # 第三轮返修（A-P3-4）：会话存储配置
    ("三轮：allowOutsideCase 改回 true", inv_src, tree_src.replace("allowOutsideCase: false", "allowOutsideCase: true", 1), 1, "legal-session-store.allowOutsideCase 不符"),
    ("三轮：投影缓存写入节奏改动", inv_src, tree_src.replace("      writeEveryEvents: 200", "      writeEveryEvents: 20", 1), 1, "legal-session-store.projectionCache.writeEveryEvents 不符"),
    ("三轮：投影缓存配置整段去掉", inv_src, tree_src.replace("    projectionCache:", "    projectionCacheX:", 1), 1, "legal-session-store.projectionCache.module 不符"),
]

failed = 0
with tempfile.TemporaryDirectory() as tmp:
    for name, inv, tree, want_rc, want_text, *extra in CASES:
        args = extra[0] if extra else ["--inventory-overlay"]
        pi, pt = pathlib.Path(tmp, "inv.json"), pathlib.Path(tmp, "tree.txt")
        pi.write_text(inv, encoding="utf-8")
        pt.write_text(tree, encoding="utf-8")
        r = subprocess.run([sys.executable, str(here / "check_plugin_tree.py"), str(pi), str(pt), *args],
                           capture_output=True, text=True, encoding="utf-8", env={"PYTHONIOENCODING": "utf-8", **__import__("os").environ})
        ok = r.returncode == want_rc and want_text in r.stdout
        failed += not ok
        print(f"{'OK  ' if ok else 'FAIL'} {name}：退出码 {r.returncode}（期望 {want_rc}），输出{'含' if want_text in r.stdout else '不含'}「{want_text}」")
print("结论：", "变异全部被报出，基线通过" if not failed else f"{failed} 项不符合预期")
sys.exit(1 if failed else 0)
