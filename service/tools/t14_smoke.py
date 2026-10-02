r"""T14 准备：服务端全链路联调脚本（只是联调工具，不是产品功能；不改 lawbench\ 产品代码）。

用法（在 service\ 目录，开发机在律所局域网，395 和 6000D 可连）：
    .venv\Scripts\python tools\t14_smoke.py                 # 默认：本脚本自己起服务，测试 Key 取自仓库 .env.local
    .venv\Scripts\python tools\t14_smoke.py --keyring       # T14 当天：用产品入口 python -m lawbench 起服务，Key 走凭据管理器
    .venv\Scripts\python tools\t14_smoke.py --out <文件>    # 结果写到别处（默认 docs\plan\evidence\T14\service-smoke.txt）

做什么（按顺序调公开接口，任何一步失败就停下并给出"归属线"建议）：
  1 起服务（127.0.0.1 随机端口、随机令牌、临时应用数据目录），等 /api/settings 可用
  2 首次配置就位核对：GET /api/settings（两组服务器地址）、POST /api/connection/test（llm、prep：可达、Key 有效）
  3 建案件：临时目录里的空文件夹 → POST /api/case/open
  4 导入：tests\fixtures\criminal-01 先复制一份到临时目录，再 POST /api/materials/import 导入全部材料；GET /api/materials
  5 识别：对需识别的页 POST /api/ocr/jobs（真 395，讯问笔录去水印）；第一个任务进行中时强杀服务进程，查 case.db 的 ocr_pages，
    再起服务，轮询到全部完成，核对：关停前已完成的页没有重做（attempts、result_path 不变）、每页一行、识别页文件数等于页数
  6 全文检索一次：GET /api/search，命中要落在识别出来的那份材料的原件页上
  7 新建任务单：POST /api/task（criminal-reading-notes，不要求模型执行）
  8 最小工具链：/core/task/begin → /core/tool（case_list_materials、case_read_material、case_search、case_save_draft 存一份
    固定草稿，看 citation_check）→ /core/task/end
  9 确认保存 + 导出 Word：POST /api/outputs/confirm（md、docx），对 docx 做结构校验（能打开、带出处的段落数）
 10 收尾自检：日志 0 泄漏（材料名、Key、识别文本、检索词）；fixtures 原件与案件原件区 sha256 前后一致

不走 6000D 的 Agent 回答，也不跑需要模型的 wiki 流水线（T16 真机已测）。
每步只记：接口、耗时、返回码、关键元数据（计数、状态、页码）；不记材料名、检索词、模型或识别文本、Key。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile

import httpx

SERVICE = pathlib.Path(__file__).resolve().parents[1]
REPO = SERVICE.parent
FIXTURE = REPO / "tests" / "fixtures" / "criminal-01"
OUT = REPO / "docs" / "plan" / "evidence" / "T14" / "service-smoke.txt"
SEARCH_TERM = "还了网贷"                 # 讯问笔录第 2 页（扫描页，只有识别后才搜得到）；不写进结果
LEAK_TEXT = ["还了网贷", "虚构区不存在路", "LBFX-CRIM01-7Q3Z"]   # 识别文本、材料原文、特征串：日志里不应出现
OWNER = {"服务": "B（T3 服务骨架）", "配置": "A（T7 首次配置）/ B（T3 设置接口）", "案件": "B（T3、T5）",
         "识别": "C（T12 识别队列；395 侧 T6/T11）", "检索": "B（T9）", "任务": "B（T8）", "工具": "B（T8；出处核对 T10）",
         "导出": "C（T15）", "保密": "B（T3 日志）"}
DRAFT_TITLE = "联调样稿"
DRAFT = """# 张某甲诈骗案阅卷摘录（联调样稿）

- 2025年3月10日，张某甲以缴纳保证金为名，诱使被害人吴某转账人民币80,000元〔起诉意见书 第2页〕。
- 张某甲称8万元保证金用于还网贷〔讯问笔录 第2页〕。
- 以上共计骗取人民币126,500元〔起诉意见书 第1页〕。
"""   # 第三条出处故意标错页（实际在第 2 页），看出处核对是否报 B 类


class Stop(Exception):
    def __init__(self, area: str, msg: str):
        super().__init__(msg)
        self.area, self.msg = area, msg


def env_local_key() -> str:
    for line in (REPO / ".env.local").read_text(encoding="utf-8").splitlines():
        if line.startswith("LAWFIRM_TEST_KEY_A="):
            return line.split("=", 1)[1].strip()
    raise SystemExit(".env.local 里没有 LAWFIRM_TEST_KEY_A")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def sha_tree(root: pathlib.Path) -> dict:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


# ---------------------------------------------------------------- 服务进程

def serve_main(argv: list[str]) -> int:
    """子命令 serve：用产品的 create_app 起真服务（uvicorn、只监听 127.0.0.1），Key 由本函数从 .env.local 读、只在内存。"""
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--token", required=True)
    ap.add_argument("--appdata", required=True)
    a = ap.parse_args(argv)
    sys.path.insert(0, str(SERVICE))
    import uvicorn
    from lawbench import __main__ as entry
    from lawbench.app import create_app
    from lawbench.config import Config
    key = env_local_key()
    entry._silence_uvicorn()
    app = create_app(Config(token=a.token, port=a.port, appdata=pathlib.Path(a.appdata)), key_getter=lambda: key)
    uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=a.port, access_log=False, log_level="warning",
                                  log_config=None, lifespan="on")).run()
    return 0


class Service:
    def __init__(self, appdata: pathlib.Path, keyring: bool, logdir: pathlib.Path):
        self.appdata, self.keyring, self.logdir = appdata, keyring, logdir
        self.port, self.token = free_port(), secrets.token_hex(20)
        self.proc: subprocess.Popen | None = None
        self.starts = 0

    def start(self) -> float:
        self.starts += 1
        if self.keyring:
            cmd = [sys.executable, "-m", "lawbench", "--port", str(self.port), "--token", self.token,
                   "--appdata", str(self.appdata), "--forward-port", str(free_port())]
        else:
            cmd = [sys.executable, str(pathlib.Path(__file__).resolve()), "serve", "--port", str(self.port),
                   "--token", self.token, "--appdata", str(self.appdata)]
        out = open(self.logdir / f"service-{self.starts}.out", "wb")
        self.proc = subprocess.Popen(cmd, cwd=str(SERVICE), stdout=out, stderr=subprocess.STDOUT,
                                     env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        t0 = time.monotonic()
        while time.monotonic() - t0 < 60:
            if self.proc.poll() is not None:
                raise Stop("服务", f"服务进程退出，退出码 {self.proc.returncode}")
            try:
                if httpx.get(self.url("/api/settings"), headers=self.headers(), timeout=2).status_code == 200:
                    return time.monotonic() - t0
            except httpx.HTTPError:
                pass
            time.sleep(0.3)
        raise Stop("服务", "60 秒内服务没有就绪")

    def kill(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.kill()                     # 强杀：模拟崩溃、断电，比正常退出更苛刻
            self.proc.wait(10)

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}


# ---------------------------------------------------------------- 主流程

class Smoke:
    def __init__(self, svc: Service, tmp: pathlib.Path):
        self.svc, self.tmp = svc, tmp
        self.rows: list[str] = []
        self.client = httpx.Client(timeout=120, trust_env=False)

    def log(self, step: str, api: str, secs: float, code, meta: str) -> None:
        line = f"[{step}] {api}  {secs:.2f}s  {code}  {meta}"
        self.rows.append(line)
        print(line, flush=True)

    def call(self, area: str, step: str, method: str, path: str, *, params=None, body=None, meta=None,
             want_ok: bool = True):
        t0 = time.monotonic()
        try:
            r = self.client.request(method, self.svc.url(path), params=params, json=body, headers=self.svc.headers())
        except httpx.HTTPError as e:
            self.log(step, f"{method} {path}", time.monotonic() - t0, type(e).__name__, "")
            raise Stop(area, f"{method} {path} 连不上服务：{type(e).__name__}")
        secs = time.monotonic() - t0
        try:
            data = r.json()
        except ValueError:
            data = {}
        if want_ok and not (r.status_code == 200 and data.get("ok")):
            code = (data.get("error") or {}).get("code") if isinstance(data, dict) else None
            self.log(step, f"{method} {path}", secs, f"{r.status_code} {code}", "")
            raise Stop(area, f"{method} {path} 返回 {r.status_code} {code}")
        value = data.get("value", {}) if isinstance(data, dict) else {}
        self.log(step, f"{method} {path}", secs, r.status_code, meta(value) if meta else "")
        return value

    # ---- 2 配置
    def settings(self) -> None:
        v = self.call("配置", "2", "GET", "/api/settings",
                      meta=lambda v: "servers=" + ",".join(f"{k}:{'有' if s else '空'}" for k, s in sorted(v["servers"].items())))
        s = v["servers"]
        if not (s.get("llm_base_url") and s.get("prep_base_url")):
            raise Stop("配置", "设置里 6000D 或 395 地址为空")
        for server in ("llm", "prep"):
            t = self.call("配置", "2", "POST", "/api/connection/test", body={"server": server},
                          meta=lambda v: f"{server} reachable={v['reachable']} key_valid={v['key_valid']} "
                                         f"route={v['route']} latency_ms={v['latency_ms']}")
            if not t["reachable"] or t["key_valid"] is False:
                raise Stop("配置", f"{server} 不可达或 Key 无效")

    # ---- 3、4 案件与导入
    def case_and_import(self) -> None:
        self.root = self.tmp / "案件" / "张某甲诈骗案（联调）"
        self.root.mkdir(parents=True)
        v = self.call("案件", "3", "POST", "/api/case/open", body={"path": str(self.root), "template": None},
                      meta=lambda v: f"created={v['created']} folders={len(v['folders_created'])}")
        self.case_id = v["case_id"]
        self.src = self.tmp / "导入源"
        shutil.copytree(FIXTURE, self.src)
        self.src_sha = sha_tree(self.src)
        paths = [str(p) for p in sorted(self.src.iterdir()) if p.is_file()]
        v = self.call("案件", "4", "POST", "/api/materials/import",
                      body={"case_id": self.case_id, "paths": paths, "target": None, "unzip": False},
                      meta=lambda v: f"copied={len(v['copied'])} skipped={len(v['skipped'])} scan={json.dumps(v.get('scan'))}")
        if len(v["copied"]) != len(paths):
            raise Stop("案件", f"导入了 {len(v['copied'])} / {len(paths)} 份")
        self.copied = {c["from"]: c["to"] for c in v["copied"]}
        self.materials()

    def materials(self) -> list[dict]:
        v = self.call("案件", "4", "GET", "/api/materials", params={"case_id": self.case_id},
                      meta=lambda v: "materials=" + "；".join(
                          f"{m['material_id']} {m['type']} {m['status']} {m['unit']}×{m['unit_count']} "
                          f"need_ocr={m.get('pages_need_ocr')} mixed={m.get('pages_mixed')}" for m in v["materials"]))
        self.mats = v["materials"]
        return self.mats

    # ---- 5 识别 + 中途强杀
    def db_pages(self) -> dict:
        con = sqlite3.connect(f"file:{self.root / '工作区' / 'case.db'}?mode=ro", uri=True)
        try:
            rows = con.execute("SELECT job_id, page_no, status, attempts, result_path FROM ocr_pages").fetchall()
        finally:
            con.close()
        return {(j, p): (s, a, r) for j, p, s, a, r in rows}

    def jobs(self, step: str) -> list[dict]:
        """轮询识别任务；状态没变的轮次不记（只留状态变化的那几行）。"""
        n = len(self.rows)
        v = self.call("识别", step, "GET", "/api/ocr/jobs", params={"case_id": self.case_id},
                      meta=lambda v: "jobs=" + "；".join(f"{j['material_id']} {j['status']} {j['done']}/{j['total']} "
                                                         f"failed={j['failed']} pause={j['pause_reason']}"
                                                         for j in v["jobs"]))
        state = self.rows[-1].split("jobs=", 1)[-1]
        if getattr(self, "_last_jobs", None) == state and len(self.rows) == n + 1:
            self.rows.pop()
        self._last_jobs = state
        return v["jobs"]

    def ocr(self) -> None:
        targets = [m for m in self.mats if m.get("pages_need_ocr")]
        if not targets:
            raise Stop("案件", "没有需要识别的页（criminal-01 的讯问笔录应是扫描件）")
        self.ocr_mids = []
        for m in sorted(targets, key=lambda m: -len(m["pages_need_ocr"])):
            pages = m["pages_need_ocr"] + [p for p in (m.get("pages_mixed") or []) if p not in m["pages_need_ocr"]]
            self.call("识别", "5", "POST", "/api/ocr/jobs",
                      body={"case_id": self.case_id, "material_id": m["material_id"], "pages": sorted(pages),
                            "dewatermark": m["type"] == "pdf"},
                      meta=lambda v, m=m: f"{m['material_id']} job pages={v['pages']} est_min={v['estimated_minutes']}")
            self.ocr_mids.append(m["material_id"])
            self.ocr_pages_total = getattr(self, 'ocr_pages_total', 0) + len(pages)
        # 识别进行中就强杀：每 0.2 秒看一次 case.db 的 ocr_pages，有页已完成、又有页还没完成时立刻杀
        t0, killed_at = time.monotonic(), None
        while time.monotonic() - t0 < 600:
            try:
                pages = self.db_pages()
            except sqlite3.Error:
                pages = {}
            st = [v[0] for v in pages.values()]
            if st and "done" in st and any(x in ("pending", "sending") for x in st):
                killed_at = {"done": st.count("done"), "sending": st.count("sending"), "pending": st.count("pending")}
                break
            if st and all(x not in ("pending", "sending") for x in st) and len(st) >= self.ocr_pages_total:
                break
            time.sleep(0.2)
        if killed_at is None:
            self.caveat = "识别中途强杀没有赶上（续做未检验，请重跑）"
            self.rows.append("[5] 注：识别太快，没赶上\"有页已完成、有页未完成\"的时刻；这次强杀发生在全部识别完之后，"
                             "续做没有被检验，请重跑")
        self.svc.kill()
        before = self.db_pages()
        self.log("5", "强杀服务进程", 0, "-", f"关停时 {killed_at or '（见注）'}；ocr_pages 行数={len(before)} "
                 f"状态={sorted({v[0] for v in before.values()})}")
        secs = self.svc.start()
        self.log("5", "重新起服务", secs, "-", "")
        t0 = time.monotonic()
        while time.monotonic() - t0 < 900:
            js = self.jobs("5")
            if js and all(j["status"] not in ("queued", "running", "paused") for j in js):
                break
            time.sleep(3)
        else:
            raise Stop("识别", "重启后 15 分钟内识别没有全部结束")
        after = self.db_pages()
        redone = [k for k, (s, a, r) in before.items() if s == "done" and after.get(k) != (s, a, r)]
        not_done = [k for k, v in after.items() if v[0] != "done"]
        files = list((self.root / "工作区" / "材料" / "识别页").rglob("*.md"))
        self.log("5", "核对 ocr_pages", 0, "-",
                 f"关停前已完成 {sum(1 for v in before.values() if v[0] == 'done')} 页、重启后被改动 {len(redone)} 页；"
                 f"全部 {len(after)} 页、未完成 {len(not_done)}；最大 attempts={max(v[1] for v in after.values())}；"
                 f"识别页文件 {len(files)}")
        if redone:
            raise Stop("识别", f"关停前已完成的页在重启后被改动：{redone}")
        if not_done or len(files) != len(after):
            raise Stop("识别", "重启后有页没完成，或识别页文件数与页数不符")
        if any(j["status"] != "done" for j in js):
            raise Stop("识别", "有识别任务没有以 done 结束")
        self.materials()

    # ---- 6 检索
    def search(self) -> None:
        import re

        def where(h):           # 出处里只取位置（"第2页"），不记材料名
            m = re.search(r"(第\d+[页段行])〕$", h["citation"])
            return m.group(1) if m else "?"

        v = self.call("检索", "6", "GET", "/api/search", params={"case_id": self.case_id, "q": SEARCH_TERM},
                      meta=lambda v: f"hits={len(v.get('hits', []))} total={v.get('total')} "
                                     + "；".join(f"{h['material_id']} {where(h)} is_ocr={h['is_ocr']} {h['match']}"
                                                for h in v.get("hits", [])[:5]))
        hits = v.get("hits", [])
        mine = [h for h in hits if h["material_id"] in self.ocr_mids]
        if not mine:
            raise Stop("检索", "检索识别出来的文字没有命中那份识别材料")
        if not any(where(h) == "第2页" and h["is_ocr"] for h in mine):
            raise Stop("检索", "命中没有落在原件第 2 页（识别页）")

    # ---- 7、8 任务单与工具链
    def task_and_tools(self) -> None:
        self.session = f"sess-t14-{uuid.uuid4().hex[:8]}"
        params = {"thinking": "关闭", "window": "64K", "max_tokens": 4096}
        v = self.call("任务", "7", "POST", "/api/task",
                      body={"case_id": self.case_id, "session_id": self.session, "entry": None,
                            "skill": "criminal-reading-notes", "inputs": [], "params": params},
                      meta=lambda v: f"task_id={v['task_id']}")
        self.selection_id = v["task_id"]
        # 契约 1.2（N37）：begin 按该会话的选择（待执行的任务单）复制出一个新的执行中任务，编号不同、skill 照搬
        b = self.call("任务", "8", "POST", "/core/task/begin", body={"session_id": self.session, "cwd": str(self.root)},
                      meta=lambda v: f"task_id={v['task_id']} skill={v['skill']} budget={json.dumps(v['budget'])}")
        if b["skill"] != "criminal-reading-notes" or b["task_id"] == self.selection_id:
            raise Stop("任务", "core/task/begin 没有按任务单复制出新的执行中任务（skill 不对或编号相同）")
        self.task_id = b["task_id"]

        def tool(name, args, meta):
            return self.call("工具", "8", "POST", "/core/tool", body={"task_id": self.task_id, "tool": name, "args": args},
                             meta=lambda v: f"{name} " + meta(v))
        tool("case_list_materials", {}, lambda v: f"materials={len(v.get('materials', []))}")
        ocr_name = next(m["name"] for m in self.mats if m["material_id"] == self.ocr_mids[0])
        tool("case_read_material", {"name": ocr_name, "start": 2},
             lambda v: f"has_more={v.get('has_more')} chars={len(v.get('text', ''))}")
        tool("case_search", {"query": SEARCH_TERM}, lambda v: f"hits={len(v.get('hits', []))}")
        d = tool("case_save_draft", {"title": DRAFT_TITLE, "content": DRAFT},
                 lambda v: "citation_check=" + json.dumps({"passed": v["citation_check"]["passed"],
                                                           **v["citation_check"]["stats"],
                                                           "classes": sorted(p["class"] for p in v["citation_check"]["problems"])},
                                                          ensure_ascii=False))
        self.draft_rel = d["path"]
        classes = [p["class"] for p in d["citation_check"]["problems"] if p["severity"] == "must_fix"]
        if "B" not in classes:
            raise Stop("工具", "故意标错页的出处没有报 B 类")
        self.call("任务", "8", "POST", "/core/task/end",
                  body={"task_id": self.task_id, "reason": "completed", "model_calls": 0, "tool_calls": 4, "elapsed_s": 1},
                  meta=lambda v: f"status={v['status']}")

    # ---- 9 确认保存与导出 Word
    def export(self) -> None:
        v = self.call("导出", "9", "POST", "/api/outputs/confirm",
                      body={"case_id": self.case_id, "task_id": self.task_id, "draft": self.draft_rel,
                            "formats": ["md", "docx"], "template": "文书"},
                      meta=lambda v: "outputs=" + "；".join(f"{o['format']} v{o['version']}" for o in v["outputs"]))
        docx = next((o for o in v["outputs"] if o["format"] == "docx"), None)
        if docx is None:
            raise Stop("导出", "没有生成 docx")
        path = self.root / docx["path"]
        t0 = time.monotonic()
        try:
            import docx as python_docx
            doc = python_docx.Document(str(path))
            paras = [p.text for p in doc.paragraphs]
        except Exception as e:  # noqa: BLE001
            raise Stop("导出", f"python-docx 打不开导出的 docx：{type(e).__name__}")
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
        cited = sum(1 for p in paras if "〔" in p and "〕" in p)
        want = sum(1 for line in DRAFT.splitlines() if "〔" in line)
        self.log("9", "docx 结构校验", time.monotonic() - t0, "-",
                 f"段落={len(paras)} 带出处的段落={cited}/{want} document.xml={'word/document.xml' in names}")
        if cited != want:
            raise Stop("导出", f"docx 里带出处的段落 {cited} 个，草稿里是 {want} 个")

    # ---- 10 自检
    def self_check(self, key: str | None) -> None:
        logs = list((self.svc.appdata / "logs").rglob("*")) + list(self.svc.logdir.glob("service-*.out"))
        text = "".join(p.read_bytes().decode("utf-8", "replace") for p in logs if p.is_file())
        names = [m["name"] for m in self.mats]
        needles = names + LEAK_TEXT + [SEARCH_TERM] + ([key, key[:12], key[-12:]] if key else [])
        hits = sum(text.count(n) for n in needles if n)
        self.log("10", "日志泄漏自检", 0, "-", f"日志文件 {len(logs)} 个、{len(text)} 字；材料名/识别文本/检索词/Key 命中 {hits}")
        if hits:
            raise Stop("保密", f"日志里出现了材料名、识别文本、检索词或 Key（{hits} 处）")
        src_now = sha_tree(self.src)
        fixture_ok = sha_tree(FIXTURE) == self.fixture_sha
        case_orig = {to: hashlib.sha256((self.root / to).read_bytes()).hexdigest() for to in self.copied.values()}
        same = all(case_orig[self.copied[str(self.src / rel)]] == h for rel, h in self.src_sha.items()
                   if str(self.src / rel) in self.copied)
        self.log("10", "原件 sha256", 0, "-", f"fixtures 不变={fixture_ok}；导入源不变={src_now == self.src_sha}；"
                                              f"案件原件区与导入源一致={same}")
        if not (fixture_ok and src_now == self.src_sha and same):
            raise Stop("案件", "原件 sha256 前后不一致")


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        return serve_main(sys.argv[2:])
    ap = argparse.ArgumentParser()
    ap.add_argument("--keyring", action="store_true", help="用产品入口起服务，Key 走凭据管理器")
    ap.add_argument("--out", type=pathlib.Path, default=OUT)
    ap.add_argument("--keep", action="store_true", help="保留临时目录（排查用）")
    a = ap.parse_args()
    key = None if a.keyring else env_local_key()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lbt14-"))
    logdir = tmp / "服务输出"
    logdir.mkdir()
    svc = Service(tmp / "appdata", a.keyring, logdir)
    s = Smoke(svc, tmp)
    s.fixture_sha = sha_tree(FIXTURE)
    started = time.strftime("%Y-%m-%d %H:%M:%S")
    result, t_all = "通过", time.monotonic()
    try:
        secs = svc.start()
        s.log("1", "起服务", secs, "-", f"方式={'python -m lawbench（凭据管理器）' if a.keyring else '本脚本 serve（.env.local 测试 Key）'}")
        s.settings()
        s.case_and_import()
        s.ocr()
        s.search()
        s.task_and_tools()
        s.export()
        s.self_check(key)
    except Stop as e:
        result = f"失败：{e.msg}；建议归属 {OWNER.get(e.area, e.area)}"
    else:
        if getattr(s, "caveat", None):
            result = f"通过，但{s.caveat}"
    finally:
        svc.kill()
        s.client.close()
    head = [f"T14 服务端预联调（tools\\t14_smoke.py）  开始 {started}  总耗时 {time.monotonic() - t_all:.0f} 秒",
            f"结果：{result}", "格式：[步骤] 接口  耗时  返回码  关键元数据（不含材料名、检索词、文本、Key）", ""]
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text("\n".join(head + s.rows) + "\n", encoding="utf-8")
    print(head[1])
    if not a.keep:
        shutil.rmtree(tmp, ignore_errors=True)
    else:
        print("临时目录保留在", tmp)
    return 0 if result == "通过" else 1


if __name__ == "__main__":
    sys.exit(main())
