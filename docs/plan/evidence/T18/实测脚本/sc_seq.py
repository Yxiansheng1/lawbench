import sys, json, pathlib
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")
import rc_analyze as a
root = pathlib.Path(r"D:\lawbench-T18\cases") / sys.argv[1]
t = sorted(p for p in (root / "工作区" / "任务").iterdir() if (p / "result.json").is_file())[-1 if len(sys.argv) < 3 else int(sys.argv[2])]
task = json.loads((t / "task.json").read_text(encoding="utf-8")); res = json.loads((t / "result.json").read_text(encoding="utf-8"))
ev = a.session_events(root, task["session_id"])
print(t.name, res["status"], res["usage"], "budget", task["budget"], "drafts", len(res["drafts"]))
step = 0
for e in ev:
    d = e.get("data") or {}
    if e["type"] == "step/start": step += 1
    if e["type"] == "tool/call":
        args = d.get("arguments") or {}
        if isinstance(args, str):
            try: args = json.loads(args)
            except ValueError: args = {}
        keep = {k: args[k] for k in ("name", "start", "max_chars", "more_names", "query", "penalty") if k in args}
        print(f"  步{step:>2} {d.get('name')} {json.dumps(keep, ensure_ascii=False)}")
reads = json.loads((t / "reads.json").read_text(encoding="utf-8"))["reads"] if (t / "reads.json").is_file() else []
print("  reads:", [(r["material_id"], r["from"], r["to"]) for r in reads])
