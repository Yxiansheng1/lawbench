"""SEC-05（上线必过第 2 项）：案件 A 读不到案件 B 和其他文件——通过工具调用和工作台接口构造越权参数。

前提：工作台服务在运行（环境变量 LB_URL、LB_TOKEN），并且已按 acceptance\\manual\\案件隔离.md 准备好：
  - 案件 A = tests\\fixtures\\attack-01 的副本（含 外部目录链接 联接、外部文件链接.txt 符号链接）；
  - 案件 B = tests\\fixtures\\civil-01 的副本，文件夹名保持 civil-01（或用 LB_CASE_B 指定它的 case_id）；
  - 在案件 A 的会话里发起过一次对话，拿到它的 task_id，放进环境变量 LB_TASK_A。
第一部分以案件 A 的 task_id 调 POST /core/tool，用各种越权参数调用读、搜、存草稿、存修改清单、归档方案等工具；
第二部分（T23/T15/T12/T16 之后）以案件 A 的身份调工作台接口：归档生成、草稿确认导出、修订版、流水线状态
（识别提交不在此列：material_id 每个案件各自从 M0001 编起，没有"别的案件的编号"可借；它只认请求里的 case_id），参数里放 ../、绝对路径、联接、案件 B 的材料名和 material_id，以及"案件 B 的 case_id + 案件 A 的
task_id"这类混搭。返回里出现案件 B 的特征字符串或 win.ini 的内容，或案件 B 的文件夹、案件文件夹的上一级在
调用前后多了 / 改了文件，即不通过。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import FAIL, FEATURES, PASS, UNMET, Report, env_local, http, service  # noqa: E402

B_FEAT = FEATURES["civil-01"]
WININI = ("[fonts]", "[extensions]", "[mci extensions]", "for 16-bit app support")

NAMES = [
    "../civil-01/情况说明", "..\\civil-01\\情况说明", "../../civil-01/情况说明.txt",
    "C:\\Windows\\win.ini", "C:/Windows/win.ini", "\\\\?\\C:\\Windows\\win.ini", "/etc/passwd",
    "外部目录链接/情况说明", "外部目录链接/情况说明.txt", "外部文件链接", "外部文件链接.txt",
    "外部目录链接\\..\\..\\civil-01\\借条", "情况说明", "借条", "银行流水",      # B 的材料名
    "%2e%2e/civil-01/情况说明", "....//civil-01//情况说明", "AGENTS.md", ".dsh/skills/evil/SKILL",
    "CON", "a" * 300,
]
# 写入类工具与接口的目标：都应落在案件 A 自己的 工作区 / 成果 里，或被拒绝
WRITE_NAMES = ["../../civil-01/写进B", "..\\..\\civil-01\\写进B", "C:\\Windows\\Temp\\写到外面",
               "外部目录链接/写进B", "../写到上一级", "CON"]
STATE_FILES = {"case.db", "case.db-wal", "case.db-shm"}
BAD_REL = ["../civil-01/情况说明.txt", "外部目录链接/情况说明.txt", "C:/Windows/win.ini",
           "工作区/../../civil-01/情况说明.txt", "外部目录链接/工作区/任务/x/归档方案.json"]


def archive_plan(materials: list[str]) -> dict:
    return {"catalog": "民事行政卷", "client": "某甲", "opponent": "某乙", "cause": "民间借贷纠纷", "lawyer": None,
            "entrust_date": "2026-01-05", "close_date": "2026-06-30", "jzl_no": None, "result": "调解",
            "summary": "越权测试", "opinion": "越权测试", "fee_settled": True,
            "items": [{"code": 7, "name": "证据材料", "materials": materials}]}


def calls():
    for n in NAMES:
        yield "case_read_material", {"name": n}
        yield "case_read_material", {"name": n, "start": 1, "max_chars": 2000}
    for q in (B_FEAT, "李某乙", "fonts"):
        yield "case_search", {"query": q}
    for i in (-1, 0, 999999):
        yield "case_read_input", {"index": i}
    for n in ("../../civil-01/借条", "C:\\Windows\\win.ini", "借条"):
        yield "case_read_wiki", {"section": "材料摘要", "name": n}
    yield "case_list_materials", {}
    for c in ("民事行政卷", "刑事卷"):
        yield "case_archive_match", {"catalog": c}
    for n in ("../civil-01/借条", "外部目录链接/借条", "借条", "C:\\Windows\\win.ini", "外部文件链接"):
        yield "case_save_archive_plan", archive_plan([n])
    for n in WRITE_NAMES:
        yield "case_save_draft", {"title": n, "content": "越权写入测试"}
        yield "case_save_edit_list", {"name": n, "edits": []}


def snapshot(case_b: Path, parent: Path) -> dict[str, str]:
    """案件 B 的全部文件、案件文件夹上一级的直接文件：路径 → sha256（上一级只看有没有新文件，记空串）。"""
    out = {str(p): "" for p in parent.iterdir() if p.is_file()}
    if case_b.is_dir():
        for p in case_b.rglob("*"):
            if p.is_file() and not p.is_symlink():
                try:
                    out[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
                except OSError:
                    pass
    return out


class Api:
    def __init__(self, url: str, token: str) -> None:
        self.url, self.h = url, {"Authorization": f"Bearer {token}"}

    def __call__(self, method: str, path: str, body=None, query: dict | None = None):
        q = "?" + urllib.parse.urlencode(query) if query else ""
        st, _, raw = http(method, self.url + path + q, body, self.h, timeout=300)
        text = raw.decode("utf-8", "replace")
        try:
            j = json.loads(text)
        except ValueError:
            j = {}
        return st, j, text


def cases(api: Api, task_a: str) -> tuple[dict | None, dict | None]:
    """由 LB_TASK_A 找案件 A（任务文件夹在它下面）；案件 B 用 LB_CASE_B，或文件夹名为 civil-01 的那个。"""
    _, j, _ = api("GET", "/api/case/recent")
    rows = [c for c in j.get("value", {}).get("cases", []) if c.get("exists")]
    a = next((c for c in rows if (Path(c["root"]) / "工作区" / "任务" / task_a).is_dir()), None)
    want_b = env_local().get("LB_CASE_B")
    b = next((c for c in rows if (c["case_id"] == want_b if want_b else Path(c["root"]).name == "civil-01")), None)
    return a, b


def api_calls(a: dict, b: dict, task_a: str):
    A, B = a["case_id"], b["case_id"]
    plan_rel = f"工作区/任务/{task_a}/归档方案.json"
    for rel in BAD_REL + [plan_rel]:
        yield "POST", "/api/archive/build", {"case_id": A, "task_id": task_a, "plan": rel,
                                             "confirmed": archive_plan(["借条"])}, None
    for n in ("../civil-01/借条", "外部目录链接/借条", "借条", "C:\\Windows\\win.ini"):
        yield "POST", "/api/archive/build", {"case_id": A, "task_id": task_a, "plan": plan_rel,
                                             "confirmed": archive_plan([n])}, None
    yield "POST", "/api/archive/build", {"case_id": B, "task_id": task_a, "plan": plan_rel,
                                         "confirmed": archive_plan(["借条"])}, None          # B 的案件 + A 的任务
    for rel in BAD_REL:
        yield "POST", "/api/outputs/confirm", {"case_id": A, "task_id": task_a, "draft": rel, "formats": ["md", "docx"],
                                               "template": None}, None
        yield "POST", "/api/redline", {"case_id": A, "task_id": task_a, "edit_list": rel}, None
    yield "POST", "/api/outputs/confirm", {"case_id": B, "task_id": task_a, "draft": f"工作区/任务/{task_a}/草稿.md",
                                           "formats": ["md"], "template": None}, None
    yield "GET", "/api/search", None, {"case_id": A, "q": B_FEAT}
    yield "GET", "/api/search", None, {"case_id": A, "q": "李某乙"}
    yield "GET", "/api/materials", None, {"case_id": A}
    yield "GET", "/api/outputs", None, {"case_id": A}
    yield "GET", f"/api/pipeline/{task_a}", None, None


def leaked(text: str) -> bool:
    return B_FEAT in text or any(m in text for m in WININI)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    r = Report("case_isolation", "SEC-05；上线必过第 2 项", a.out)
    svc = service()
    task = env_local().get("LB_TASK_A")
    if not svc:
        r.finish(UNMET, "工作台服务没有运行，或没有设置 LB_URL / LB_TOKEN（T3 之后按 manual\\案件隔离.md 准备）")
    if not task:
        r.finish(UNMET, "没有案件 A 会话的 task_id（环境变量 LB_TASK_A）")
    url, token = svc
    api = Api(url, token)
    ca, cb = cases(api, task)
    if not ca or not cb:
        r.finish(UNMET, "工作台最近案件里找不到案件 A（LB_TASK_A 所在）或案件 B（文件夹 civil-01，或设 LB_CASE_B）")
    parent = Path(ca["root"]).parent
    before = snapshot(Path(cb["root"]), parent)

    leaks, n = [], 0
    r.log("## 一、工具调用（POST /core/tool，案件 A 的 task_id）")
    for tool, args in calls():
        st, _, body = http("POST", url + "/core/tool", {"task_id": task, "tool": tool, "args": args},
                           {"Authorization": f"Bearer {token}"}, timeout=60)
        n += 1
        text = body.decode("utf-8", "replace")
        ok = False
        try:
            ok = bool(json.loads(text).get("ok"))
        except ValueError:
            pass
        bad = leaked(text)
        r.log(f"  {tool} {json.dumps(args, ensure_ascii=False)[:80]} → HTTP {st} ok={ok}{'  ← 泄露' if bad else ''}")
        if bad:
            leaks.append(f"{tool} {args}")

    r.log("## 二、工作台接口（案件 A 的身份，越权参数与混搭）")
    # 先用案件 A 自己的材料存一份合法的归档方案，下面"确认方案里放 B 的材料名"才走得到材料匹配那一步
    _, j, _ = api("GET", "/api/materials", query={"case_id": ca["case_id"]})
    own = [m["name"] for m in j.get("value", {}).get("materials", []) if m.get("type") in ("txt", "docx", "pdf")]
    st, _, body = http("POST", url + "/core/tool", {"task_id": task, "tool": "case_save_archive_plan",
                                                    "args": archive_plan(own[:1] or ["案情材料"])},
                       {"Authorization": f"Bearer {token}"}, timeout=60)
    r.log(f"  （准备）用案件 A 的材料 {own[:1]} 存归档方案 → HTTP {st} ok={json.loads(body or b'{}').get('ok')}")
    for method, path, body, query in api_calls(ca, cb, task):
        st, j, text = api(method, path, body, query)
        n += 1
        bad = leaked(text)
        code = j.get("error", {}).get("code") if not j.get("ok") else ""
        shown = json.dumps(body if body is not None else query, ensure_ascii=False)
        r.log(f"  {method} {path} {shown[:90]} → HTTP {st} ok={bool(j.get('ok'))} {code or ''}"
              f"{'  ← 泄露' if bad else ''}")
        if bad:
            leaks.append(f"{method} {path} {shown[:120]}")

    after = snapshot(Path(cb["root"]), parent)
    diff = sorted(k for k in after if before.get(k) != after[k]) + sorted(k for k in before if k not in after)
    # 案件 B 的 case.db 及其 -wal/-shm 由服务自己维护（识别队列等会读写），内容变化不算越权写；新出现的文件仍算
    state = [k for k in diff if Path(k).name in STATE_FILES and k in before]
    touched = [k for k in diff if k not in state]
    r.log(f"共 {n} 次越权调用；案件 B 与案件文件夹上一级调用前后变化的文件 {len(touched)} 个")
    for k in touched:
        r.log(f"  变化：{k}")
    if state:
        r.log(f"  （只记）服务自己的状态文件有变化：{'、'.join(Path(k).name for k in state)}")
    if leaks or touched:
        r.finish(FAIL, f"{len(leaks)} 次调用读到了案件 B 或系统文件的内容；案件外 {len(touched)} 个文件被写或改")
    r.finish(PASS, "所有越权调用都没有读到案件 B 或案件外文件的内容，也没有在案件 A 之外写文件")


if __name__ == "__main__":
    main()
