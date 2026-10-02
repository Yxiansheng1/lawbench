r"""T16 真机补测（执行令 20261002-1506 第 1 条）：对真 395 逐份跑 9B 的分类与字段抽取，记每份结果（对照脚本，不是产品代码）。

用法（在 service\ 目录，机器在律所局域网）：
    .venv\Scripts\python ..\docs\plan\evidence\T16\run_9b.py

- 案件与材料文本照 run_大卷宗.py 的做法建（大卷宗 21 份材料文本 + 2 份失败材料）。
- 每份非表格材料单独交给产品的 pipeline.prep.Prep 跑一次（classify + 每段 fields + 按原文核对），记分类、字段数、
  核对不过数、通过率、调用次数、耗时；表格类材料产品本身不送 9B，照记"跳过（表格类）"。
- 395 地址用设置默认值（所内 http://192.168.8.124:9000），只经产品的 Net。Key 从 .env.local 读，只在内存。
- 输出 9b-逐份.json（只有材料编号、材料名、分类、计数、耗时；不含字段值和原文）。
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import shutil
import sys
import tempfile
import time
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("run_big", HERE / "run_大卷宗.py")
big = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(big)

from starlette.testclient import TestClient  # noqa: E402

from lawbench.app import create_app  # noqa: E402
from lawbench.case import gate  # noqa: E402
from lawbench.config import Config  # noqa: E402
from lawbench.pipeline.prep import FAIL_RATIO, Prep  # noqa: E402
from lawbench.pipeline.steps import wiki  # noqa: E402


def main() -> int:
    key = big.test_key()
    gate._registry_onedrive_folders = lambda: []
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lbt16-9b-"))
    appdata, root = tmp / "appdata", tmp / "大卷宗案件"
    root.mkdir()
    app = create_app(Config(token=big.TOKEN, appdata=appdata), key_getter=lambda: key)
    c = TestClient(app, raise_server_exceptions=False)
    c.headers["Authorization"] = f"Bearer {big.TOKEN}"
    case_id = c.post("/api/case/open", json={"path": str(root)}).json()["value"]["case_id"]
    index = big.build_index(root, case_id)
    net = app.state.lb.net
    base, route = net.select("prep")
    with urllib.request.urlopen(base + "/health", timeout=10) as r:
        health = json.loads(r.read())
    mats, skipped = wiki.load_materials(str(root), index)
    rows, total_f, total_bad, t_all = [], 0, 0, time.monotonic()
    for m in mats:
        row = {"材料编号": m.mid, "材料名": m.name, "单位": m.meta["unit"], "单元数": len(m.units)}
        if m.table:
            row["结果"] = "跳过（表格类，产品不送 9B）"
            rows.append(row)
            print(m.mid, m.name, row["结果"], flush=True)
            continue
        p = Prep(net, lambda: key)
        t0 = time.monotonic()
        refs, cats = p.run([m])
        n, bad = p.stats["字段"], p.stats["核对不过"]
        total_f, total_bad = total_f + n, total_bad + bad
        row.update({"分类": cats.get(m.mid), "调用": p.stats["调用"], "字段": n, "核对不过": bad,
                    "通过率": round((n - bad) / n, 3) if n else None, "耗时秒": round(time.monotonic() - t0, 1),
                    "单份若独立判断": ("超 20%，整体跳过" if n and bad / n > FAIL_RATIO else "通过"),
                    "提示": p.note})
        rows.append(row)
        print(m.mid, m.name, row, flush=True)
    out = {"395": {"地址": "所内" if route == "primary" else "所外", "health": health},
           "跳过的材料": [{"材料名": meta["name"], "原因": why} for meta, why in skipped],
           "逐份": rows,
           "合计": {"字段": total_f, "核对不过": total_bad,
                  "核对不过比例": round(total_bad / total_f, 3) if total_f else None,
                  "整次是否跳过（>20%）": bool(total_f and total_bad / total_f > FAIL_RATIO),
                  "总耗时秒": round(time.monotonic() - t_all, 1)}}
    (HERE / "9b-逐份.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out["合计"], ensure_ascii=False))
    c.close()
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
