"""T18 test harness only: record the service port/token for the CDP driver, then run the product entry unchanged."""
import json, os, runpy, sys
with open(r"D:\lawbench-T18\svc.json", "w", encoding="utf-8") as f:
    json.dump({"port": os.environ.get("LB_PORT"), "token": os.environ.get("LB_TOKEN")}, f)
sys.argv = ["lawbench"]
runpy.run_module("lawbench", run_name="__main__", alter_sys=True)
