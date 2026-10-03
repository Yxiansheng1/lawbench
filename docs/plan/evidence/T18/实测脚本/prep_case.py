"""T18 harness: build a case folder from a skill's tests\\样本01 and register it with the running service.

Usage: python prep_case.py <skill>
- copies every file/folder of 样本01 except _任务说明.md and _L0*.md into D:\\lawbench-T18\\cases\\<skill>\\
  (_上游成果-*.md are copied as 上游成果-*.md so the model can read them as materials);
- POST /api/case/open, POST /api/materials/scan; prints case_id, root and the task text (part before ---).
Only fictional test material from the repo. Prints no material text other than the task instruction itself.
"""
import json
import pathlib
import shutil
import sys
import urllib.request

SKILLS = pathlib.Path(r"D:\lawbench-B\skills")
CASES = pathlib.Path(r"D:\lawbench-T18\cases")


def api(method: str, path: str, body: dict | None = None) -> dict:
    svc = json.loads(pathlib.Path(r"D:\lawbench-T18\svc.json").read_text(encoding="utf-8"))
    req = urllib.request.Request(f"http://127.0.0.1:{svc['port']}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {svc['token']}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        out = json.loads(r.read())
    if not out.get("ok"):
        raise SystemExit(f"{path}: {out}")
    return out["value"]


def main(skill: str, name: str | None = None) -> None:
    sample = next((SKILLS / skill / "tests").glob("样本01*"))
    root = CASES / (name or skill)
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    for p in sample.iterdir():
        if p.name in ("_任务说明.md",) or p.name.startswith("_L0"):
            continue
        dst = root / (p.name[1:] if p.name.startswith("_上游成果") else p.name)
        (shutil.copytree if p.is_dir() else shutil.copy2)(p, dst)
    case = api("POST", "/api/case/open", {"path": str(root)})
    scan = api("POST", "/api/materials/scan", {"case_id": case["case_id"]})
    task = (sample / "_任务说明.md").read_text(encoding="utf-8").split("\n---", 1)[0]
    task = task.replace("# 任务说明", "").strip()
    print(json.dumps({"skill": skill, "sample": sample.name, "case_id": case["case_id"], "root": str(root),
                      "scan": {k: v for k, v in scan.items() if isinstance(v, (int, str))}, "task": task},
                     ensure_ascii=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
