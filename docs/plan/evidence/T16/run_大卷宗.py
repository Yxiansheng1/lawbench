r"""T16 第 6 步：用大卷宗 21 份材料跑真 6000D 生成案件 wiki（对照脚本，不是产品代码）。

用法（在 service\ 目录，机器要能连所内或所外 6000D）：
    .venv\Scripts\python ..\docs\plan\evidence\T16\run_大卷宗.py [--think 关闭|低|中|高]

做法：
- 大卷宗只有材料文本（tests\fixtures\wiki-test\大卷宗\raw\卷宗\*.md，formats.md 第 2 节的写法），没有原件。
  脚本在临时目录建一个案件、经工作台服务打开，把每份材料文本放到 工作区\材料\文本\<rel_path>.md，
  照契约写 工作区\材料\index.json（文字版、扫描件按 _处理状态.md 标 is_ocr；两份失败材料标 failed），
  然后调产品的 /api/pipeline/run，等它跑完。
- Key 从 D:\lawbench-B\.env.local 的 LAWFIRM_TEST_KEY_A 读，只在内存里，不打印、不落盘。
- 跑完把 工作区\wiki\ 整个复制到本目录 大卷宗wiki\，任务目录的 运行记录.json 抄成 大卷宗运行记录.json，
  result.json 的核对结果汇总写进 大卷宗核对.txt。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[3]
RAW = REPO / "tests" / "fixtures" / "wiki-test" / "大卷宗" / "raw" / "卷宗"
sys.path.insert(0, str(REPO / "service"))

from starlette.testclient import TestClient  # noqa: E402

from lawbench import contracts  # noqa: E402
from lawbench.app import create_app  # noqa: E402
from lawbench.case import gate  # noqa: E402
from lawbench.config import Config  # noqa: E402

TOKEN = "d" * 40
MARK = re.compile(r"^【第(\d+)(页|段)】$", re.M)


def test_key() -> str:
    for line in (REPO / ".env.local").read_text(encoding="utf-8").splitlines():
        if line.startswith("LAWFIRM_TEST_KEY_A="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("缺 LAWFIRM_TEST_KEY_A")


def status_rows() -> list[list[str]]:
    rows = []
    for line in (RAW / "_处理状态.md").read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 5 and cells[0] not in ("原件",) and not set(cells[0]) <= set("-"):
            rows.append(cells)
    return rows


def build_index(root: pathlib.Path, case_id: str) -> dict:
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    mats = []
    for n, (orig, kind, _pages, state, note) in enumerate(status_rows(), 1):
        stem = pathlib.Path(orig).stem
        src = RAW / f"{stem}.md"
        ext = pathlib.Path(orig).suffix.lstrip(".")
        rel = f"卷宗/{orig}"
        entry = {"material_id": f"M{n:04d}", "rel_path": rel, "name": re.sub(r"^\d+", "", stem), "type": ext,
                 "size": 0, "mtime": now, "sha256": "0" * 64, "status": "failed", "unit": "page", "unit_count": 0,
                 "is_ocr": "none", "text_path": f"工作区/材料/文本/{rel}.md", "pages_need_ocr": [], "pages_mixed": [],
                 "note": None, "error": note, "imported_at": now, "updated_at": now}
        if state != "失败" and src.is_file():
            text = src.read_text(encoding="utf-8")
            marks = MARK.findall(text)
            entry.update(status="parsed", unit="para" if marks and marks[0][1] == "段" else "page",
                         unit_count=len(marks), is_ocr="full" if "扫描件" in kind else "none", error=None,
                         size=len(text.encode("utf-8")), sha256=hashlib.sha256(text.encode("utf-8")).hexdigest())
            p = root / "工作区" / "材料" / "文本" / f"{rel}.md"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        mats.append(entry)
    index = {"v": 1, "case_id": case_id, "next_seq": len(mats) + 1, "materials": mats}
    contracts.validate("files/material_index.schema.json", "", index)
    (root / "工作区" / "材料" / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2),
                                                     encoding="utf-8")
    return index


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--think", default="关闭", choices=["关闭", "低", "中", "高"])
    ap.add_argument("--max-tokens", type=int, default=8192)
    args = ap.parse_args()
    key = test_key()
    gate._registry_onedrive_folders = lambda: []
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lbt16-"))
    appdata, root = tmp / "appdata", tmp / "大卷宗案件"
    root.mkdir()
    app = create_app(Config(token=TOKEN, appdata=appdata), key_getter=lambda: key)
    c = TestClient(app, raise_server_exceptions=False)
    c.headers["Authorization"] = f"Bearer {TOKEN}"
    r = c.post("/api/case/open", json={"path": str(root)}).json()
    case_id = r["value"]["case_id"]
    build_index(root, case_id)
    params = {"thinking": args.think, "window": "64K", "max_tokens": args.max_tokens}
    r = c.post("/api/pipeline/run", json={"case_id": case_id, "step": "wiki_build", "use_prep": False,
                                          "params": params}).json()
    if not r.get("ok"):
        print("启动失败：", r)
        return 1
    tid = r["value"]["task_id"]
    t0 = time.time()
    last = None
    while True:
        v = c.get(f"/api/pipeline/{tid}").json()["value"]
        line = f"{v['status']} 第 {v['step_index']} 步 / 共 {v['step_total']} 步  当前：{v['current']}"
        if line != last:
            print(f"[{time.time() - t0:6.0f}s] {line}", flush=True)
            last = line
        if v["status"] != "running":
            break
        time.sleep(3)
    task_dir = root / "工作区" / "任务" / tid
    out = HERE / "大卷宗wiki"
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(root / "工作区" / "wiki", out)
    rec = json.loads((task_dir / "运行记录.json").read_text(encoding="utf-8"))
    res = json.loads((task_dir / "result.json").read_text(encoding="utf-8"))
    rec["参数"] = {"thinking": args.think, "max_tokens": args.max_tokens, "并行": 2, "每段字数": 8000}
    (HERE / "大卷宗运行记录.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    chk = res["citation_check"] or {}
    counts = {k: sum(1 for p in chk.get("problems", []) if p["class"] == k) for k in "ABCDEFG"}
    lines = [f"# 大卷宗 wiki 全文核对（产品 checks 库，excerpt）", f"任务 {tid}  状态 {res['status']}",
             "；".join(f"{k} {counts[k]}" for k in "ABCDEFG"), f"must_fix {chk.get('stats', {}).get('must_fix')}", ""]
    for p in chk.get("problems", []):
        lines.append(f"- {p['class']} [{p['severity']}] {p['message']}")
        lines.append(f"    原句：{p['excerpt'][:100]}")
    (HERE / "大卷宗核对.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n完成：{res['status']}，调用 {rec['模型调用次数']} 次，{rec['总耗时秒']} 秒；核对 " +
          "；".join(f"{k} {counts[k]}" for k in "ABCDEFG"))
    c.close()
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
