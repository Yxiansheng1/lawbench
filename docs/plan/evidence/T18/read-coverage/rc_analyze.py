"""read-coverage 复现分析：每个案件最新一个 Agent 任务的工具调用序列、reads.json、coverage、citation_check。
只取元数据：工具名、case_read_material 的 name/start/offset/max_chars、返回是否出错及错误码、读取记录的单元范围；
不取材料正文和模型输出（材料是 tests\\fixtures 的虚构材料，名字可留）。"""
import io
import json
import pathlib
import sys

import zstandard

sys.stdout.reconfigure(encoding="utf-8")
CASES = pathlib.Path(r"D:\lawbench-T18\cases")


def session_events(root: pathlib.Path, sid: str) -> list[dict]:
    for p in (root / "工作区" / "会话").rglob("session*.jsonl*"):
        raw = p.read_bytes()
        if p.name.endswith(".zstd"):
            with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw), read_across_frames=True) as r:
                raw = r.read()
        lines = [json.loads(x) for x in raw.decode("utf-8").splitlines() if x.strip()]
        if lines and lines[0].get("id") == sid:
            return lines
    return []


def tool_seq(events: list[dict]) -> list[dict]:
    out, pending = [], {}
    for e in events:
        d = e.get("data") or {}
        if e.get("type") == "tool/call":
            args = d.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            keep = {k: args.get(k) for k in ("name", "start", "offset", "max_chars") if k in args} if d.get("name") == "case_read_material" else {}
            rec = {"tool": d.get("name"), **keep}
            pending[d.get("callId")] = rec
            out.append(rec)
        elif e.get("type") == "tool/result":
            m = d.get("message") or {}
            if m.get("isError") and out:   # 只留报错文字的开头（工作台的提示语），不留正文
                txt = "".join(c.get("text", "") for c in m.get("content", []) if isinstance(c, dict))
                out[-1]["error"] = txt.replace("Error: ", "")[:30]
    return out


def main(names: list[str]) -> None:
    report = {}
    for n in names:
        root = CASES / n
        tdir = root / "工作区" / "任务"
        tasks = sorted((p for p in tdir.iterdir() if (p / "result.json").is_file()), key=lambda p: p.name)
        t = tasks[-1]
        task = json.loads((t / "task.json").read_text(encoding="utf-8"))
        res = json.loads((t / "result.json").read_text(encoding="utf-8"))
        reads = json.loads((t / "reads.json").read_text(encoding="utf-8"))["reads"] if (t / "reads.json").is_file() else []
        idx = {m["material_id"]: m for m in json.loads((root / "工作区" / "材料" / "index.json").read_text(encoding="utf-8"))["materials"]}
        seq = tool_seq(session_events(root, task["session_id"]))
        cc = res.get("citation_check") or {}
        report[n] = {
            "task_id": task["task_id"], "status": res["status"], "usage": res["usage"],
            "drafts": [d["path"].split("/")[-1] for d in res["drafts"]],
            "tool_sequence": seq,
            "reads": [{"material": idx[r["material_id"]]["name"], "unit": r["unit"], "from": r["from"], "to": r["to"]} for r in reads],
            "materials": [{"id": k, "name": m["name"], "type": m["type"], "status": m["status"], "unit": m["unit"],
                           "unit_count": m["unit_count"], "is_ocr": m["is_ocr"], "pages_need_ocr": m["pages_need_ocr"]} for k, m in idx.items()],
            "coverage": res.get("coverage"),
            "citation_check_stats": cc.get("stats"), "citation_classes": sorted({p["class"] + ("!" if p["severity"] == "must_fix" else "") for p in cc.get("problems", [])}),
        }
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
