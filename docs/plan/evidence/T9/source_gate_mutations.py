"""复核 AMEND：把 source.py 的两处闸门换成直接拼路径，对应用例应变红；跑完复原。在 service 目录下运行。"""
import pathlib, subprocess, sys
F = pathlib.Path("lawbench/case/source.py")
orig = F.read_text(encoding="utf-8")
muts = [
 ("_page_png 原件不过闸门", 'path = gate.resolve_read(root, meta["rel_path"], op="source_view")',
  'import pathlib as _p; path = _p.Path(root) / meta["rel_path"]', "junction_no_image"),
 ("_changed 每份 result.json 不过闸门",
  'path = gate.resolve_internal(root, f"{TASK_DIR}/{d.name}/result.json", op="source_view")',
  'path = d / "result.json"', "task_folder_junction"),
 ("_changed 任务根不过闸门", 'base = gate.resolve_internal(root, TASK_DIR, op="source_view")',
  'import pathlib as _p; base = _p.Path(root) / TASK_DIR', "tasks_root_junction"),
]
try:
    for name, a, b, k in muts:
        assert a in orig, name
        F.write_text(orig.replace(a, b), encoding="utf-8")
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/test_source.py", "-k", k],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        print(("红 " if r.returncode else "绿! ") + name + " | " + r.stdout.strip().splitlines()[-1])
        F.write_text(orig, encoding="utf-8")
finally:
    F.write_text(orig, encoding="utf-8")
