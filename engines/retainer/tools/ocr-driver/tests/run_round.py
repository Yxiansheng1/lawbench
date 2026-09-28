# -*- coding: utf-8 -*-
"""
多轮 OCR 测试运行器

一轮测试 = 对同一套语料跑一遍「识别 → 字段解析 → 修正 → 比对」，产出一份可比较的报告。

分层指标
  L1 行级：识别到的文本行数、平均置信度
  L2 字段级：字段抽取准确率（键值均精确匹配才算对）
  L3 校验级：代码类字段（统一社会信用代码、身份证号）通过校验位的比例
  L4 覆盖率：关键字段齐全率

用法
  python run_round.py                 # 跑一轮，自动编号
  python run_round.py --label 修正邻近配对
  python run_round.py --diff 3 4      # 对比第 3、4 轮
"""
import argparse
import json
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER_DIR = os.path.dirname(HERE)
ROOT = os.path.dirname(DRIVER_DIR)
RESULTS = os.path.join(HERE, "results")

sys.path.insert(0, os.path.join(DRIVER_DIR, "vendor"))
sys.path.insert(0, DRIVER_DIR)

os.environ.setdefault("HF_HUB_OFFLINE", "1")

import fieldfix  # noqa: E402

CODE_FIELDS = {"credit_code", "id_number"}


def load_corpus():
    with open(os.path.join(HERE, "corpus.json"), encoding="utf-8") as f:
        return json.load(f)


def next_round_index():
    os.makedirs(RESULTS, exist_ok=True)
    nums = []
    for n in os.listdir(RESULTS):
        if n.startswith("round-") and n.endswith(".json"):
            try:
                nums.append(int(n[len("round-"):-len(".json")]))
            except ValueError:
                pass
    return (max(nums) + 1) if nums else 1


def run_engine(engine_name):
    from rapidocr import RapidOCR
    t0 = time.time()
    engine = RapidOCR()
    return engine, time.time() - t0


def to_lines(raw):
    boxes = getattr(raw, "boxes", None)
    txts = getattr(raw, "txts", None)
    scores = getattr(raw, "scores", None)
    if txts is None and isinstance(raw, (list, tuple)) and len(raw) == 2:
        seq = raw[0] or []
        boxes = [x[0] for x in seq]
        txts = [x[1] for x in seq]
        scores = [x[2] for x in seq]
    out = []
    for i, t in enumerate(txts or []):
        box = boxes[i] if boxes is not None and i < len(boxes) else None
        sc = scores[i] if scores is not None and i < len(scores) else None
        if box is not None:
            box = [[int(p[0]), int(p[1])] for p in box]
        out.append({"text": str(t), "score": None if sc is None else round(float(sc), 4), "box": box})
    return out


def score_case(doc_type, lines):
    fields, meta = fieldfix.extract(doc_type, lines)
    return fields, meta


def compare(expect, fields):
    hit, miss, wrong = [], [], []
    for k, v in expect.items():
        got = fields.get(k)
        if got is None or got == "":
            miss.append(k)
        elif got == v:
            hit.append(k)
        else:
            wrong.append({"field": k, "expect": v, "got": got})
    extra = [k for k in fields if k not in expect]
    return hit, miss, wrong, extra


def run_round(label, engine_name, only=None):
    corpus = load_corpus()
    cases = corpus["cases"]
    if only:
        cases = [c for c in cases if only in c["id"]]

    engine, init_s = run_engine(engine_name)
    detail, totals = [], {"fields": 0, "hit": 0, "wrong": 0, "miss": 0, "lines": 0, "score_sum": 0.0,
                          "score_n": 0, "code_ok": 0, "code_n": 0, "required_ok": 0, "errors": 0}
    wall_start = time.time()

    for c in cases:
        path = os.path.join(HERE, c["file"])
        rec = {"id": c["id"], "docType": c["docType"], "scene": c["scene"]}
        try:
            t1 = time.time()
            lines = to_lines(engine(path))
            rec["seconds"] = round(time.time() - t1, 2)
            rec["lineCount"] = len(lines)
            rec["lines"] = lines
            fields, meta = score_case(c["docType"], lines)
            rec["fields"] = fields
            rec["status"] = meta.get("status", {})
            rec["warnings"] = meta.get("warnings", [])
            rec["unmatched"] = meta.get("unmatched_rows", [])
            hit, miss, wrong, extra = compare(c["expect"], fields)
            rec["hit"] = hit
            rec["miss"] = miss
            rec["wrong"] = wrong
            rec["extra"] = extra
            rec["ok"] = not miss and not wrong

            totals["fields"] += len(c["expect"])
            totals["hit"] += len(hit)
            totals["wrong"] += len(wrong)
            totals["miss"] += len(miss)
            totals["lines"] += len(lines)
            for ln in lines:
                if ln["score"] is not None:
                    totals["score_sum"] += ln["score"]
                    totals["score_n"] += 1
            for k in CODE_FIELDS & set(c["expect"]):
                totals["code_n"] += 1
                if meta.get("status", {}).get(k) in ("ok", "fixed"):
                    totals["code_ok"] += 1
            if not miss:
                totals["required_ok"] += 1
        except Exception as e:
            rec["error"] = str(e)[:300]
            rec["trace"] = traceback.format_exc()[-600:]
            totals["errors"] += 1
        detail.append(rec)

    idx = next_round_index()
    report = {
        "round": idx,
        "label": label,
        "engine": engine_name,
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "engineInitSeconds": round(init_s, 2),
        "wallSeconds": round(time.time() - wall_start, 1),
        "caseCount": len(cases),
        "metrics": {
            "fieldAccuracy": round(totals["hit"] / totals["fields"], 4) if totals["fields"] else None,
            "fieldHit": totals["hit"],
            "fieldWrong": totals["wrong"],
            "fieldMiss": totals["miss"],
            "fieldTotal": totals["fields"],
            "avgScore": round(totals["score_sum"] / totals["score_n"], 4) if totals["score_n"] else None,
            "totalLines": totals["lines"],
            "codePassRate": round(totals["code_ok"] / totals["code_n"], 4) if totals["code_n"] else None,
            "requiredCompleteRate": round(totals["required_ok"] / len(cases), 4) if cases else None,
            "errors": totals["errors"],
        },
        "detail": detail,
    }
    path = os.path.join(RESULTS, "round-%d.json" % idx)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    return report, path


def summarize(report):
    m = report["metrics"]
    lines = []
    lines.append("第 %d 轮　%s" % (report["round"], report["label"]))
    lines.append("引擎 %s　初始化 %.2fs　总耗时 %.1fs　用例 %d" % (
        report["engine"], report["engineInitSeconds"], report["wallSeconds"], report["caseCount"]))
    lines.append("字段准确率 %s（%d/%d）　误识 %d　漏取 %d" % (
        m["fieldAccuracy"], m["fieldHit"], m["fieldTotal"], m["fieldWrong"], m["fieldMiss"]))
    lines.append("代码校验通过率 %s　关键字段齐全率 %s　平均置信度 %s　识别行数 %d" % (
        m["codePassRate"], m["requiredCompleteRate"], m["avgScore"], m["totalLines"]))
    if m["errors"]:
        lines.append("异常用例 %d" % m["errors"])
    bad = [d for d in report["detail"] if not d.get("ok")]
    lines.append("未全对用例 %d/%d：" % (len(bad), len(report["detail"])))
    for d in bad[:20]:
        if d.get("error"):
            lines.append("  %s  [异常] %s" % (d["id"], d["error"][:80]))
        else:
            parts = []
            if d["miss"]:
                parts.append("漏 " + ",".join(d["miss"]))
            for w in d["wrong"]:
                parts.append("%s 期望[%s] 实得[%s]" % (w["field"], w["expect"], w["got"]))
            lines.append("  %s（%s）%s" % (d["id"], d["scene"], "；".join(parts)))
    return "\n".join(lines)


def diff(a, b):
    ra = json.load(open(os.path.join(RESULTS, "round-%d.json" % a), encoding="utf-8"))
    rb = json.load(open(os.path.join(RESULTS, "round-%d.json" % b), encoding="utf-8"))
    da = {d["id"]: d for d in ra["detail"]}
    db = {d["id"]: d for d in rb["detail"]}
    lines = ["第 %d 轮 → 第 %d 轮" % (a, b),
             "字段准确率 %s → %s" % (ra["metrics"]["fieldAccuracy"], rb["metrics"]["fieldAccuracy"]),
             "代码校验通过率 %s → %s" % (ra["metrics"]["codePassRate"], rb["metrics"]["codePassRate"])]
    for cid in sorted(set(da) | set(db)):
        x, y = da.get(cid), db.get(cid)
        if x is None or y is None:
            lines.append("  %s：仅存在于一侧" % cid)
            continue
        if x.get("ok") != y.get("ok"):
            lines.append("  %s：%s → %s" % (cid, "通过" if x.get("ok") else "未通过", "通过" if y.get("ok") else "未通过"))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="基线")
    ap.add_argument("--engine", default="rapidocr")
    ap.add_argument("--only", default=None)
    ap.add_argument("--diff", nargs=2, type=int, default=None)
    args = ap.parse_args()

    if args.diff:
        text = diff(args.diff[0], args.diff[1])
    else:
        report, path = run_round(args.label, args.engine, args.only)
        text = summarize(report) + "\n\n报告：" + path
    with open(os.path.join(HERE, "_last_run.txt"), "w", encoding="utf-8") as f:
        f.write(text)


if __name__ == "__main__":
    main()
