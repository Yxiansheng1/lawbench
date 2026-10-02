r"""T16 真机补测（执行令 20261002-1506 第 2 条）：真 6000D 上流水线在途时取消，量取消到 cancelled 的时间（对照脚本）。

用法（在 service\ 目录，机器在律所局域网）：
    .venv\Scripts\python ..\docs\plan\evidence\T16\run_cancel_real.py [--runs 3]

- 每轮新建一个大卷宗案件（照 run_大卷宗.py），经产品接口起 wiki_build（不开 9B），等网关 /health 的 inflight
  比起跑前多出本流水线的请求（摘要两路并行）后再等 2 秒，调 /api/pipeline/{id}/cancel，
  每 0.1 秒查一次状态，记从取消到状态不再是 running 的时间和最终状态（要求 cancelled、≤10 秒）。
- 网关侧：6000D 没有 /status，/admin 要管理员；能看的只有 /health 的全局 inflight / queued。取消前后每秒记一次，
  看本流水线的在途请求是否在网关侧消失（连接断开的旁证；499 日志本身看不到）。
- 先探过：网关不按 Key 限并发（max_concurrency 24 为全局），同一 Key 再多占两路也不会让请求进入排队；
  要造出排队只能把全局 24 路占满，会影响律所其他人，没做。所以本测的是"已发出、在途"的请求被取消。
- Key 从 .env.local 读，只在内存；输出不含 Key、材料内容。
"""
from __future__ import annotations

import argparse
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

GATEWAY = "http://192.168.8.77:8000"


def health() -> tuple[int, int]:
    with urllib.request.urlopen(GATEWAY + "/health", timeout=5) as r:
        d = json.loads(r.read())
    return d["inflight"], d["queued"]


def one(n: int, key: str) -> dict:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lbt16-cx-"))
    appdata, root = tmp / "appdata", tmp / "大卷宗案件"
    root.mkdir()
    app = create_app(Config(token=big.TOKEN, appdata=appdata), key_getter=lambda: key)
    c = TestClient(app, raise_server_exceptions=False)
    c.headers["Authorization"] = f"Bearer {big.TOKEN}"
    try:
        case_id = c.post("/api/case/open", json={"path": str(root)}).json()["value"]["case_id"]
        big.build_index(root, case_id)
        base_in, base_q = health()
        params = {"thinking": "关闭", "window": "64K", "max_tokens": 8192}
        tid = c.post("/api/pipeline/run", json={"case_id": case_id, "step": "wiki_build", "use_prep": False,
                                                "params": params}).json()["value"]["task_id"]
        t_start = time.monotonic()
        seen = None
        while time.monotonic() - t_start < 60:
            inflight, _ = health()
            if inflight >= base_in + 1:
                seen = round(time.monotonic() - t_start, 1)
                break
            time.sleep(0.3)
        time.sleep(2)
        before = health()
        t0 = time.monotonic()
        c.post(f"/api/pipeline/{tid}/cancel", json={})
        took, status = None, None
        while time.monotonic() - t0 < 30:
            status = c.get(f"/api/pipeline/{tid}").json()["value"]["status"]
            if status != "running":
                took = round(time.monotonic() - t0, 2)
                break
            time.sleep(0.1)
        after = []
        for _ in range(10):
            after.append(health())
            time.sleep(1)
        res = json.loads((root / "工作区" / "任务" / tid / "result.json").read_text(encoding="utf-8"))
        return {"轮": n, "起跑前网关 inflight/queued": [base_in, base_q], "看到本流水线在途（起跑后秒）": seen,
                "取消前 inflight/queued": list(before), "取消到状态结束秒": took, "状态": status,
                "result.json 状态": res["status"], "已发出调用（usage）": res["usage"]["model_calls"],
                "取消后每秒 inflight/queued": [list(x) for x in after]}
    finally:
        c.close()
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    args = ap.parse_args()
    key = big.test_key()
    gate._registry_onedrive_folders = lambda: []
    rows = []
    for n in range(1, args.runs + 1):
        r = one(n, key)
        rows.append(r)
        print(json.dumps(r, ensure_ascii=False), flush=True)
        time.sleep(3)
    (HERE / "cancel-real.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
