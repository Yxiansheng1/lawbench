import pathlib, subprocess, sys
F = pathlib.Path("lawbench/case/source.py"); U = pathlib.Path("lawbench/api/ui.py")
orig = {F: F.read_text(encoding="utf-8"), U: U.read_text(encoding="utf-8")}
muts = [
 ("无路由", U, '        Route("/api/source", E("source", source, query=True), methods=["GET"]),\n', ""),
 ("文本取错单元", F, '"text": mat.text_at(loc)', '"text": mat.text_at({**loc, "from": loc["from"] + 1, "to": loc.get("to", loc["from"]) + 1}) if loc["unit"] != "cell" else mat.text_at(loc)'),
 ("非PDF也出图", F, 'if meta["type"] == "pdf" and loc["unit"] == "page":\n        png = _page_png(root, meta, loc["from"])', 'if loc["unit"] == "page":\n        png = _page_png(root, meta, loc["from"], meta["type"])'),
 ("范围取末页图", F, 'png = _page_png(root, meta, loc["from"])', 'png = _page_png(root, meta, loc.get("to", loc["from"]))'),
 ("不认材料名", F, 'item = next((i for i in cites[0].items if i.name == name), None)', 'item = next(iter(cites[0].items), None)'),
 ("不判位置", F, '    if problem:\n        raise', '    if False:\n        raise'),
 ("任一旧版即提示", F, 'return bool(versions) and meta["sha256"] not in versions', 'return any(v != meta["sha256"] for v in versions)'),
 ("从不提示", F, 'return bool(versions) and meta["sha256"] not in versions', 'return False'),
 ("日志不记编号", F, 'logs.event("source", "view", case_id=case_id, material_id=material_id, unit=loc["unit"])', 'logs.event("source", "view", case_id=case_id)'),
]
# 非PDF也出图 需要 _page_png 接受类型
extra = {"非PDF也出图": ('def _page_png(root: str, meta: dict, page_no: int) -> str | None:', 'def _page_png(root: str, meta: dict, page_no: int, kind: str = "pdf") -> str | None:',
                         'render.render_png(path, "pdf", page_no)', 'render.render_png(path, kind, page_no)')}
try:
    for name, f, a, b in muts:
        s = orig[f]; assert a in s, name; s = s.replace(a, b)
        if name in extra:
            x = extra[name]; assert x[0] in s and x[2] in s; s = s.replace(x[0], x[1]).replace(x[2], x[3])
        f.write_text(s, encoding="utf-8")
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "tests/test_source.py"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        last = r.stdout.strip().splitlines()[-1]
        print(("红 " if r.returncode else "绿! ") + name + " | " + last)
        f.write_text(orig[f], encoding="utf-8")
finally:
    for f, s in orig.items(): f.write_text(s, encoding="utf-8")
