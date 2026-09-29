import sys, yaml
class L(yaml.SafeLoader): pass
L.add_constructor("tag:yaml.org,2002:js", lambda l, n: ("!!js", l.construct_scalar(n)))
rows = yaml.load(open(sys.argv[1], encoding="utf-8-sig"), Loader=L)
by = {r.get("id"): r for r in rows if isinstance(r, dict)}
need = """preset-standard preset-ptc preset-minimal preset-cordis web web-search-deepseek web-fetch-http mcp-resources
plugin-manager ui-plugin-manager plugin-package-inventory-deepseek deepseek-account llm-deepseek llm-deepseek-account
session-telemetry-otel message-feedback ui-message-feedback session-title-llm ui-sidebar-documentpreview office-to-pdf ui-brand-official""".split()
bad = 0
print("Spec 3.1 关掉的行（web profile 导出；!!js 表达式按未求值打印）")
for i in need:
    r = by.get(i)
    st = "不存在" if r is None else ("disabled" if r.get("disabled") is True else "启用!")
    bad += st == "启用!"
    print(f"  {i:36s} {st}")
print("改配置的行")
for i in ["agent-preset-registry", "agent-default-model", "spill-policy", "spill-local", "locale", "ui-settings", "workspace-controller", "llm-pi-ai"]:
    r = by.get(i); print(f"  {i:24s} {'config 已覆盖' if r and r.get('config') is not None else '缺失!'}")
p = by.get("preset-lawbench")
print("preset-lawbench:", "存在" if p else "缺失!", [x.get("id") for x in p["config"]["plugins"]] if p else "")
print("结论:", "通过" if bad == 0 and p else f"不通过（{bad} 行仍启用）")
