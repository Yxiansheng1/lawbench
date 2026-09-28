# -*- coding: utf-8 -*-
"""
发票主台账管理工具
用法:
  init              python invoice_db.py init --src <目录> --batch <名称> [--reimbursed] [--full-nums-json <文件>] [--out <候选文件名>]
  import            python invoice_db.py import --src <文件/目录> --batch <名称> [--img]
  mark-reimbursed   python invoice_db.py mark-reimbursed --batch <名称> [--month|--prefix] [--apply]
  report            python invoice_db.py report [--status X] [--batch X]
  check-schema      python invoice_db.py check-schema [--archive <目录>] [--batch X]   （只读六级体检）
  review            python invoice_db.py review [--batch X] [--sample-rate 0.05]      （抽验清单＋留痕）

退出码：0=成功 1=致命错误 2=有重复/冲突/待人工等需关注事项
"""

import argparse
import json
import os
import re
import shutil
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# ── 环境自举：校验当前包指纹并使用外部缓存；无有效环境时中止 ──
import sys as _sys_boot
from pathlib import Path as _Path_boot
_sys_boot.dont_write_bytecode = True
_sys_boot.path.insert(0, str(_Path_boot(__file__).resolve().parent))
import _deps
_deps.guard(__file__)

# 子模块
import extract_fields
from invoice_integrity import admission_errors, ledger_gate, valid_identity

# ── 控制台 ──
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── 台账位置（可移植配置，优先级：CLI --ledger > 环境变量 INVOICE_LEDGER_DIR > 技能目录上一级） ──
def _resolve_ledger_dir(cli_path=None) -> Path:
    if cli_path:
        return Path(cli_path)
    env = os.environ.get("INVOICE_LEDGER_DIR", "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent

LEDGER_DIR = _resolve_ledger_dir()
LEDGER_FILE = LEDGER_DIR / "发票主台账.xlsx"

HEADERS = [
    "类别序号", "发票类别", "开票日期",
    "价税合计（元）", "发票号码后五位", "文件名",
    "来源批次", "发票号码全号", "状态",
]
VALID_STATUS = frozenset({
    "未报", "已报", "重复-剔除", "红冲", "⚠OCR待人工",
    "冲突-待裁",   # 同一标识指向矛盾记录，待人工裁定（不计入合计）
    "已取代",      # 该行已被裁定性更正取代，保留留痕（不计入合计）
})

# ── 冲突记录表（与主表同文件，**建在主表之后**；append-only）──
# 设计见 references/05-env-and-deps.md 与本文件 §判定表；不变量见 references/06-invariants.md I1
CONFLICT_SHEET = "冲突记录"
# 字段块（类别序号…全号）与主表同序，便于"采纳新值"时直接据此追加一条完整主表行
CONFLICT_HEADERS = [
    "冲突ID", "发现时间", "来源批次", "来源路径", "文件名",
    "类别序号", "发票类别", "开票日期", "价税合计（元）", "发票号码后五位", "发票号码全号",
    "冲突类型", "对方行", "冲突原因", "状态",
    "对方行号",    # 冲突所涉主表行的 Excel 行号（裁定定位依据）
    "原状态",      # 该行被标记为"冲突-待裁"之前的状态（"维持台账"时还原用）
    "裁定结果", "裁定时间",
]
CONFLICT_STATUS = frozenset({"待裁", "已归档"})
# 裁定可选项（resolve-conflict --decision）
CONFLICT_DECISIONS = ("采纳新值", "维持台账", "剔除")
# 不计入金额合计的状态（口径：冲突/已取代/剔除单列，避免合计虚高）
EXCLUDED_FROM_TOTAL = frozenset({"冲突-待裁", "已取代", "重复-剔除", "⚠OCR待人工"})
DATE_NOW = datetime.now().strftime("%Y%m%d_%H%M%S")


# ════════════════════════════════════════════════════════════
#  运行产物目录（_ 前缀，天然被扫描逻辑跳过，见 06-invariants.md）
# ════════════════════════════════════════════════════════════
BACKUP_DIRNAME = "_备份"     # 台账备份，保留最近 3 个
LOG_DIRNAME = "_日志"        # 运行日志（含去重报告），保留最近 10 个
CANDIDATE_DIRNAME = "_候选台账"  # init --out 生成的候选台账


def _sub_dir(name: str) -> Path:
    d = LEDGER_DIR / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _backup_ledger(keep: int = 3) -> Path:
    """写前备份到 _备份/，保留最近 keep 个。备份失败即抛错（硬门禁）。"""
    bak = _sub_dir(BACKUP_DIRNAME) / f"{LEDGER_FILE.stem}_bak_{DATE_NOW}.xlsx"
    shutil.copy2(str(LEDGER_FILE), str(bak))
    if not bak.exists() or bak.stat().st_size == 0:
        raise RuntimeError(f"备份失败：{bak}")
    baks = sorted(_sub_dir(BACKUP_DIRNAME).glob(f"{LEDGER_FILE.stem}_bak_*.xlsx"),
                  key=lambda p: p.stat().st_mtime)
    for old in baks[:-keep]:
        try:
            old.unlink()
        except OSError:
            pass
    return bak


# ════════════════════════════════════════════════════════════
#  台账读写（原子保存 + 备份断言）
# ════════════════════════════════════════════════════════════

def _load_ledger(path=None):
    """返回 (rows_list, col_map_dict)。

    注意：按工作表**名**取主表，不用 wb.active（冲突记录表在主表之后，
    一旦顺序变化 active 会指向错表且不报错 —— 见 06-invariants.md I4）。
    """
    p = Path(path) if path else LEDGER_FILE
    rows = []
    col_map = {h: i for i, h in enumerate(HEADERS)}
    if not p.exists():
        return rows, col_map

    import openpyxl
    wb = openpyxl.load_workbook(str(p), data_only=True)
    ws = wb["发票主台账"] if "发票主台账" in wb.sheetnames else wb.worksheets[0]
    hdr = [str(c.value or "").strip() for c in ws[1]]
    if hdr:
        col_map = {h: idx for idx, h in enumerate(hdr)}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row and any(v is not None for v in row):
            rows.append(list(row))
    wb.close()
    return rows, col_map


def _load_conflicts(path=None):
    """读冲突记录表。文件不存在或没有该工作表 → 返回 []（不报错）。"""
    p = Path(path) if path else LEDGER_FILE
    if not p.exists():
        return []
    import openpyxl
    wb = openpyxl.load_workbook(str(p), data_only=True)
    try:
        if CONFLICT_SHEET not in wb.sheetnames:
            return []
        ws = wb[CONFLICT_SHEET]
        out = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            if row and any(v is not None for v in row):
                out.append(list(row))
        return out
    finally:
        wb.close()


def _write_conflict_sheet(wb, rows):
    """在 wb 写入冲突记录表。**建在主表之后**（wb.active 永远指向首个表）。

    I1：调用方负责传入"既有行 ＋ 新增行"，行数只增不减。
    与主表共用同一个 Workbook，故主表与冲突表**同一次 save，天然原子**。
    """
    from openpyxl.styles import Font, Alignment
    ws = wb[CONFLICT_SHEET] if CONFLICT_SHEET in wb.sheetnames \
        else wb.create_sheet(CONFLICT_SHEET)      # 追加在末尾
    for col, h in enumerate(CONFLICT_HEADERS, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = Font(bold=True, size=11)
        cell.alignment = Alignment(horizontal="center")
    for i, row in enumerate(rows, 2):
        for col, val in enumerate(row, 1):
            ws.cell(row=i, column=col, value=val)
    widths = [16, 18, 16, 44, 44, 24, 16, 14, 12, 14, 46, 40, 10, 10, 10, 26, 18]
    for col, w in enumerate(widths, 1):
        ws.column_dimensions[chr(64 + col)].width = w
    return len(rows)


def _ledger_headers_for(path: Path) -> list:
    """读目标台账实际表头：HEADERS + 既有额外列（按原位置保留）。

    用于"保留未知列"——人工加的列不得在写盘时被静默丢弃（I1）。
    """
    if not path.exists():
        return list(HEADERS)
    import openpyxl
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    try:
        ws = wb["发票主台账"] if "发票主台账" in wb.sheetnames else wb.worksheets[0]
        hdr = [str(c.value or "").strip() for c in next(ws.iter_rows(min_row=1, max_row=1))]
    finally:
        wb.close()
    return list(HEADERS) + [h for h in hdr[len(HEADERS):] if h]


def _save_ledger(rows, col_map=None, mode="append", reason="", target=None,
                 conflicts=None, conflicts_full=None):
    """写台账（原子保存 + 备份 + 不变量断言）。

    mode="append"  唯一常规路径，受 I1 增量性约束
    mode="replace" 破坏性写入，**必须**给 reason，否则拒绝
    target         写盘目标，默认主台账；指定非主台账时按候选产物处理
                   （跳过备份与 I1，不触碰主台账）
    conflicts      本次新增的冲突记录行（list）；与主表同一次 save 写出
    conflicts_full 冲突记录**整表**（裁定回写用，改状态/填裁定结果）；与 conflicts 二选一

    I1 增量性：主表写入行数 ≥ 读取行数、读入全号集合 ⊆ 写出全号集合；
              冲突表行数只增不减（追加与整表替换两条路径均受此约束）
    I2 回读性：写盘后重新打开比对主表行数与冲突表行数
    """
    if mode == "replace" and not reason:
        raise RuntimeError("破坏性写入必须提供 reason（见 references/06-invariants.md I1）")

    import openpyxl
    from openpyxl.styles import Font, Alignment

    target = Path(target) if target else LEDGER_FILE
    is_main = target.resolve() == LEDGER_FILE.resolve()

    if is_main and LEDGER_FILE.exists():
        before_rows, before_map = _load_ledger()
        if mode == "append":
            if len(rows) < len(before_rows):
                raise RuntimeError(
                    f"I1 违反：写入行数 {len(rows)} < 读取行数 {len(before_rows)}"
                    f"（台账只做增量、不做删减）")
            ci_before = before_map.get("发票号码全号", 7)
            before_nums = {str(r[ci_before]).strip() for r in before_rows
                           if len(r) > ci_before and str(r[ci_before] or "").strip()}
            ci_now = (col_map or before_map).get("发票号码全号", 7)
            now_nums = {str(r[ci_now]).strip() for r in rows
                        if len(r) > ci_now and str(r[ci_now] or "").strip()}
            lost = before_nums - now_nums
            if lost:
                raise RuntimeError(
                    f"I1 违反：{len(lost)} 条既有全号在写入后消失（例：{sorted(lost)[:3]}）")
        else:
            print(f"[WARN] 破坏性写入台账：{reason}；{len(before_rows)} 行 → {len(rows)} 行")
        _backup_ledger()

    full_headers = _ledger_headers_for(target)
    tmp = target.with_name(f"_tmp_{DATE_NOW}_{target.name}")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "发票主台账"

    for col, h in enumerate(full_headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = Font(bold=True, size=11)
        cell.alignment = Alignment(horizontal="center")

    for i, row in enumerate(rows, 2):
        for col, val in enumerate(row, 1):
            ws.cell(row=i, column=col, value=val)

    widths = [12, 12, 14, 14, 16, 50, 16, 24, 14]
    for col, w in enumerate(widths, 1):
        ws.column_dimensions[chr(64 + col)].width = w

    # ── 冲突记录表：自动补建（迁移既有台账即由此完成）＋ 追加写入 ──
    # conflicts_full 非空时按"整表替换"处理（裁定回写路径：改状态/填裁定结果），
    # 否则按"既有 + 本次新增"追加（导入路径）。两条路径都受 I1 行数不减约束。
    prior_conflicts = _load_conflicts(target)
    if conflicts_full is not None:
        merged_conflicts = list(conflicts_full)
    else:
        merged_conflicts = prior_conflicts + list(conflicts or [])
    if len(merged_conflicts) < len(prior_conflicts):
        raise RuntimeError(
            f"I1 违反：冲突记录行数 {len(merged_conflicts)} < 既有 {len(prior_conflicts)}")
    _write_conflict_sheet(wb, merged_conflicts)

    try:
        wb.save(str(tmp))
    except PermissionError:
        print("[FATAL] 台账被占用（Excel/坚果云同步中），请关闭后重试")
        return -1

    # 硬门禁：断言临时文件非空
    if tmp.stat().st_size == 0:
        raise RuntimeError("临时文件为空，保存失败")

    # 原子替换
    os.replace(str(tmp), str(target))

    # ── I2：回读校验（主表 + 冲突表）──
    final_rows, _ = _load_ledger(target)
    if len(final_rows) != len(rows):
        raise RuntimeError(f"保存后行数不一致：{len(final_rows)} vs 期望 {len(rows)}")
    final_conf = _load_conflicts(target)
    if len(final_conf) != len(merged_conflicts):
        raise RuntimeError(
            f"保存后冲突行数不一致：{len(final_conf)} vs 期望 {len(merged_conflicts)}")
    return len(rows)


def _build_index(rows, col_map):
    """建立判重索引（**dict 形式**，便于冲突判定时取出"对方行"信息）。

    full_index  : {全号: {"last5","amt","date","batch","status","row_no"}}
    triple_index: {(后五位, 金额, 日期): {"full_num","batch","row_no"}}

    dict 支持 `in`，故原有 `full_num in full_set` 写法仍然成立。
    与 set 版的差别：能回答"台账里那一行的金额/日期/批次是什么"——这是
    把"重复"与"冲突"拆开的前提（否则无法判断关键字段是否一致）。
    """
    full_index = {}
    triple_index = {}
    col_fn = col_map.get("发票号码全号", 7)
    col_l5 = col_map.get("发票号码后五位", 4)
    col_amt = col_map.get("价税合计（元）", 3)
    col_dt = col_map.get("开票日期", 2)
    col_batch = col_map.get("来源批次", 6)
    col_st = col_map.get("状态", 8)

    def _cell(r, i):
        return str(r[i] or "").strip() if len(r) > i else ""

    for n, r in enumerate(rows, start=2):   # Excel 行号自 2 起
        fn = _cell(r, col_fn)
        last5 = _cell(r, col_l5)
        amt = _cell(r, col_amt)
        date = _cell(r, col_dt)
        st = _cell(r, col_st)
        retired = st in EXCLUDED_FROM_TOTAL      # 已取代/重复-剔除/冲突-待裁 = 已退休，不作比对对象
        if fn:
            cur = full_index.get(fn)
            # 同一全号可能有多行（"采纳新值"裁定会追加更正行）：
            # **优先保留未退休的行**，否则裁完再导入会反复判冲突（死循环）
            if cur is None or (cur.get("status") in EXCLUDED_FROM_TOTAL and not retired):
                full_index[fn] = {
                    "last5": last5, "amt": amt, "date": date,
                    "batch": _cell(r, col_batch), "status": st,
                    "row_no": n,
                }
        if last5:
            key = (last5, amt, date)
            cur = triple_index.get(key)
            if cur is None or (cur.get("status") in EXCLUDED_FROM_TOTAL and not retired):
                triple_index[key] = {
                    "full_num": fn, "batch": _cell(r, col_batch),
                    "status": st, "row_no": n,
                }
    return full_index, triple_index


def classify_incoming(full_num, last5, amt, date, full_index, triple_index):
    """判定新发票相对既有台账的关系。**纯函数**：不读盘、不写盘、无副作用。

    返回 (kind, ctype_label, reason, other)
      kind        ∈ {"new", "dup", "conflict"}
      ctype_label 冲突记录表「冲突类型」值："" | "重复" | "重复(低置信)" | "冲突"
      reason      冲突记录表「冲突原因」值
      other       「对方行」描述；无对方行为 ""

    判定表（references/02-dedup-logic.md 同步维护）：
      A 全号命中 + 金额与日期均一致        → dup
      B 全号命中 + 金额或日期不一致        → conflict
      C 无全号 + 三维命中                  → dup（低置信）
      D 有全号但未命中 + 三维命中且全号不同 → conflict
      E 均未命中                           → new

    设计意图：B/D 在原实现中被当作普通"重复"或直接"新增"，都会掩盖数据矛盾；
    拆开后一律进入冲突记录表待人工裁定（信息不抹除）。
    """
    full_num = (full_num or "").strip()
    last5 = (last5 or "").strip()
    amt = (amt or "").strip()
    date = (date or "").strip()

    # ── A / B：全号命中 ──
    prior = full_index.get(full_num) if full_num else None
    if prior:
        same_amt = (prior.get("amt") or "") == amt
        same_date = (prior.get("date") or "") == date
        other = (f"全号={full_num} 批次={prior.get('batch', '')} "
                 f"金额={prior.get('amt', '')} 日期={prior.get('date', '')}")
        if same_amt and same_date:
            st = prior.get("status") or ""
            reason = "重复-已报销" if st == "已报" else "重复-已存在"
            return "dup", "重复", reason, other
        diffs = []
        if not same_amt:
            diffs.append(f"金额 {prior.get('amt', '') or '(空)'} → {amt or '(空)'}")
        if not same_date:
            diffs.append(f"日期 {prior.get('date', '') or '(空)'} → {date or '(空)'}")
        return ("conflict", "冲突",
                "全号相同但关键字段不一致：" + "；".join(diffs), other)

    # ── C / D：三维兜底 ──
    hit = triple_index.get((last5, amt, date)) if last5 else None
    if hit:
        hit_full = (hit.get("full_num") or "").strip()
        other = (f"全号={hit_full or '(空)'} 批次={hit.get('batch', '')} "
                 f"后五位={last5} 金额={amt} 日期={date}")
        if not full_num:
            return "dup", "重复(低置信)", "三维命中-低置信（建议人工复核）", other
        if hit_full and hit_full != full_num:
            return ("conflict", "冲突",
                    f"后五位+金额+日期一致但全号不同（台账 {hit_full} vs 本次 {full_num}）",
                    other)
        return "dup", "重复(低置信)", "三维命中-低置信（建议人工复核）", other

    return "new", "", "", ""


def _mk_conflict_row(now, batch, src_path, fn, seq, category, full_num, last5, amt, date,
                     ctype_label, other, reason, prior_status="", prior_row=None):
    """构造一行冲突记录（冲突ID 留空，写盘前统一编号）。

    状态：凡 ctype_label 以"重复"开头 → 已归档（无需裁定）；否则 → 待裁。
    状态值受 `CONFLICT_STATUS` 白名单约束（唯一构造出口，故在此校验）。
    seq/category：为"采纳新值"裁定准备完整主表行所需的类别字段。
    prior_status / prior_row：冲突所涉主表行的"原状态"与 Excel 行号，供裁定定位与还原。
    """
    status = "已归档" if ctype_label.startswith("重复") else "待裁"
    if status not in CONFLICT_STATUS:
        raise RuntimeError(f"冲突记录状态非法：{status}（白名单 {sorted(CONFLICT_STATUS)}）")
    return [
        "",                                    # 冲突ID
        now, batch, src_path, fn,
        seq, category, date, amt, last5, full_num,
        ctype_label, other, reason,
        status,
        prior_row if prior_row is not None else "",   # 对方行号
        prior_status,                                 # 原状态
        "", "",                                       # 裁定结果 / 裁定时间
    ]


def _prior_row_status(full_num, last5, amt, date, full_index, triple_index):
    """返回冲突所涉主表行的 (原状态, Excel 行号)；找不到则 ("", None)。

    优先按全号定位（判定表 B），否则按三维键定位（判定表 D）。
    """
    prior = full_index.get((full_num or "").strip()) if full_num else None
    if prior:
        return (prior.get("status") or ""), prior.get("row_no")
    key = ((last5 or "").strip(), (amt or "").strip(), (date or "").strip())
    hit = triple_index.get(key) if last5 else None
    if hit:
        return (hit.get("status") or ""), hit.get("row_no")
    return "", None


# ════════════════════════════════════════════════════════════
#  文件收集
# ════════════════════════════════════════════════════════════

def collect_files(src: Path):
    """递归收集 PDF/图片；跳过汇总单、内部目录；Windows 大小写去重"""
    files = []
    seen = set()
    for f in src.rglob("*"):
        if f.is_dir():
            continue
        ext = f.suffix.lower()
        if ext not in (".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"):
            continue
        # 跳过汇总单
        if "汇总单" in f.name:
            continue
        # 跳过内部目录（父路径含 _ 或 已分类）
        parts = f.relative_to(src).parts
        if any(p.startswith("_") or p in ("raw_decoded",) for p in parts[:-1]):
            continue
        key = str(f.resolve()).lower()  # Windows 大小写不敏感去重
        if key not in seen:
            seen.add(key)
            files.append(f)
    return sorted(files, key=lambda p: str(p).casefold())


# ════════════════════════════════════════════════════════════
#  命令: init
# ════════════════════════════════════════════════════════════

def cmd_init(args):
    src = Path(args.src)
    if not src.is_dir():
        print(f"[ERROR] 源目录不存在：{src}")
        return 1

    # I4：拒绝把含台账的目录当作模板源（技能根目录即为典型误操作）
    if (src / LEDGER_FILE.name).exists():
        print(f"[ERROR] --src 目录内含台账本体（{LEDGER_FILE.name}），拒绝以台账为模板重建。")
        print("        请指向纯统计表目录。")
        return 1

    # Native renamer statistics are an attachment summary; initialize from their original PDFs
    # through the SAME admission/dedup path, never by summing the summary workbook.
    if (src / "发票统计表.xlsx").exists() and collect_files(src) and not args.out:
        if LEDGER_FILE.exists():
            print("[ERROR] 台账已存在，请使用 import")
            return 1
        args.img = False; args.ocr = False
        rc = cmd_import(args)
        if rc == 0 and args.reimbursed:
            args.prefix = False; args.month = False; args.apply = True
            return cmd_mark(args)
        return rc

    # 定位模板（表头前6列匹配）
    import openpyxl
    candidates = []
    for f in src.glob("*.xlsx"):
        try:
            wb = openpyxl.load_workbook(str(f), data_only=True)
            hdr = [str(c.value or "").strip() for c in wb.active[1]]
            wb.close()
            # I4 识别唯一性：模板必须"前 6 列匹配 **且不含台账管理列**"。
            # 台账的前 6 列与模板逐字相同，只比前 6 列会让台账被当成模板（自我指涉，
            # 后果是丢掉第 7~9 列：来源批次/全号/状态，且对账门禁看不见）。
            hdr_clean = [h for h in hdr if h]
            if (hdr_clean[:6] == HEADERS[:6]
                    and not (set(hdr_clean) & {"来源批次", "发票号码全号", "状态"})):
                candidates.append(f)
        except Exception:
            continue
    if not candidates:
        print("[ERROR] 未找到表头匹配的统计表（期望前6列 = 类别序号/发票类别/开票日期/价税合计/后五位/文件名）")
        return 1
    tpl = candidates[0]

    # 优先文件名含"总"的统计表（总统计表 163 行）
    for c in candidates:
        if "报销统计表" in c.name or c.stem.startswith("8月"):
            tpl = c
            break

    print(f"[INFO] 模板：{tpl.name}")

    # 读取数据行（过滤非数据行）
    wb = openpyxl.load_workbook(str(tpl), data_only=True)
    ws = wb.active
    tpl_rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row:
            continue
        fn = str(row[5] or "").strip()
        if not fn:
            continue  # 跳过小计/总额/空行
        tpl_rows.append(row)
    wb.close()
    print(f"[INFO] 模板数据行：{len(tpl_rows)}")

    # 全号映射（文件名 → 全号）+ 批次推断（目录名）
    full_num_map = {}
    if args.full_nums_json:
        jp = Path(args.full_nums_json)
        if jp.exists():
            with open(jp, "r", encoding="utf-8") as f:
                data = json.load(f)
            # json 格式：{全号: 路径} → 反查文件名 → 全号
            for full_num, path_str in data.items():
                full_num_map[Path(path_str).name] = full_num
            print(f"[INFO] 全号映射：{len(full_num_map)} 条")

    # 目录 → 批次名（从 src 子目录反查文件名归属批次）
    file_to_batch = {}
    for d in src.iterdir():
        if d.is_dir():
            for f in d.iterdir():
                file_to_batch[f.name] = d.name

    # 组装行
    new_rows = []
    for row in tpl_rows:
        fn = str(row[5] or "").strip()
        # 批次：优先子目录，其次文件名中段推断，最后 --batch
        batch = file_to_batch.get(fn) or args.batch or "8月"
        # 状态：--reimbursed → 全部已报；否则含"已报"目录名 → 已报
        if args.reimbursed:
            status = "已报"
        elif "已报" in batch:
            status = "已报"
        else:
            status = "未报"
        new_rows.append([
            str(row[0] or "").strip(),   # 类别序号
            str(row[1] or "").strip(),   # 发票类别
            extract_fields.normalize_date(row[2]),  # 开票日期
            extract_fields.normalize_amount(row[3]),  # 价税合计
            str(row[4] or "").strip(),   # 后五位
            fn,                          # 文件名
            batch,                       # 来源批次
            full_num_map.get(fn, ""),    # 全号
            status,                      # 状态
        ])

    failures = ledger_gate(new_rows, {h:i for i,h in enumerate(HEADERS)}, EXCLUDED_FROM_TOTAL)
    if failures:
        print("[BLOCKED] 模板数据不完整或重复：", failures[:10])
        return 2
    print("[BLOCKED] 旧统计模板没有购买方原票证据；请提供原票并使用 import")
    return 2
    # 对账：模板金额合计
    tpl_sum = sum(float(extract_fields.normalize_amount(r[3]) or 0) for r in tpl_rows)
    ledger_sum = sum(float(r[3] or 0) for r in new_rows)
    print(f"  模板合计：{tpl_sum:,.2f}  台账合计：{ledger_sum:,.2f}")
    if abs(tpl_sum - ledger_sum) > 0.01:
        print(f"[FATAL] 对账失败：模板 {tpl_sum:,.2f} ≠ 台账 {ledger_sum:,.2f}")
        return 1

    # ── 只做增量：init 永不覆盖现有台账（I1）──
    if LEDGER_FILE.exists():
        if not args.out:
            print(f"[ERROR] 主台账已存在（{LEDGER_FILE.name}），init 不再允许覆盖。")
            print("        日常录入请改用：invoice_db.py import --src <目录> --batch <批次>")
            print("        确需从模板重建候选台账：加 --out <候选文件名>（写入 _候选台账/，主台账不受影响）")
            return 1
        out_name = Path(args.out).name
        if out_name == LEDGER_FILE.name:
            print(f"[ERROR] --out 不得指向主台账本体（{LEDGER_FILE.name}），否则等同覆盖。")
            return 1
        target = _sub_dir(CANDIDATE_DIRNAME) / out_name
        n = _save_ledger(new_rows, mode="replace",
                         reason=f"init 生成候选台账 {out_name}", target=target)
        if n < 0:
            return 1
        print(f"\n[OK] 候选台账已生成：{target}")
        print(f"     主台账未改动（{LEDGER_FILE}）；比对后由你决定是否采用。")
        return 0

    n = _save_ledger(new_rows, mode="replace", reason="首次建立主台账")
    if n < 0:
        return 1

    # 全号覆盖率
    missing_full = sum(1 for r in new_rows if not r[7])
    print(f"  全号缺失：{missing_full} 条")
    if missing_full:
        print(f"  [WARN] 全号缺失 {missing_full} 条，建议人工补录")

    # 状态分布
    sc = defaultdict(int)
    for r in new_rows:
        sc[r[8]] += 1
    for s, c in sorted(sc.items()):
        print(f"  状态「{s}」：{c}")
    print(f"\n[OK] 主台账初始化完成：{len(new_rows)} 条 → {LEDGER_FILE.name}")
    return 0


# ════════════════════════════════════════════════════════════
#  命令: import
# ════════════════════════════════════════════════════════════

def cmd_import(args):
    src = Path(args.src)
    if not src.exists():
        print(f"[ERROR] 路径不存在：{src}")
        return 1

    # --batch 必填（目录可自动取目录名，文件必须显式）
    batch = args.batch
    if not batch and src.is_dir():
        batch = src.name
        print(f"[INFO] 自动取批次名：{batch}")
    if not batch:
        print("[FATAL] 文件导入必须指定 --batch（防孤儿数据）")
        return 1

    files = collect_files(src) if src.is_dir() else [src]
    if not files:
        print("[ERROR] 目录内没有可导入的 PDF/图片")
        return 2
    print(f"[INFO] 待导入文件：{len(files)} 个（批次：{batch}）")

    rows, col_map = _load_ledger()
    full_index, triple_index = _build_index(rows, col_map)
    col_full = col_map.get("发票号码全号", 7)
    col_status = col_map.get("状态", 8)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_rows = []
    duplicates = []     # 重复（无矛盾）→ 冲突表留痕，不入主表
    conflicts = []      # 冲突（关键字段矛盾）→ 冲突表待裁，不入主表
    pending = []        # 空键/OCR无全号 → 待人工，不入库
    errors = []
    conflict_rows = []  # 冲突记录（含"重复"留痕），与主表同一次 save 写出
    marked = []         # 被标记为「冲突-待裁」的主表行 (Excel行号, 原状态)

    for f in files:
        ext = f.suffix.lower()
        # 提取
        if ext == ".pdf":
            try:
                result = extract_fields.extract_from_pdf(str(f))
            except extract_fields.DependencyMissing as e:
                # 环境问题必须中止，不得混入"字段提取失败/待人工"（I3）
                print(f"\n[FATAL] 运行环境未就绪：缺少 {e.name}")
                print("        请先构建技能内环境包：python scripts/build_env_zip.py")
                return 1
        else:
            if not (args.img or args.ocr):
                errors.append((f.name, "图片需 --img 参数"))
                continue
            try:
                result = extract_fields.extract_from_image(str(f))
            except extract_fields.DependencyMissing as e:
                print(f"\n[FATAL] 运行环境未就绪：缺少内置依赖 {e.name}")
                print("        请运行 python scripts/runtime_cache.py --repair")
                return 1
            if result.get("_ocr_language_missing"):
                pending.append((f.name, result["_ocr_language_missing"]))
                continue
            if result.get("_ocr_error"):
                pending.append((f.name, f"OCR 执行失败：{result['_ocr_error']}"))
                continue
            if result.get("_ocr_empty"):
                pending.append((f.name, "OCR 未识别出文字"))
                continue

        # 内容层失败（文件损坏/加密），与依赖缺失分开归入 errors
        if result.get("_extract_error"):
            errors.append((f.name, f"PDF 解析失败：{result['_extract_error']}"))
            continue

        fn = result.get("文件名") or f.name
        full_num = (result.get("发票号码全号") or "").strip()
        last5 = (result.get("发票号码后五位") or "").strip()
        amt = extract_fields.normalize_amount(result.get("价税合计（元）"))
        date = extract_fields.normalize_date(result.get("开票日期"))
        category = (result.get("发票类别") or "").strip()
        seq = (result.get("类别序号") or "").strip()

        from evidence_store import preserve
        preserve(LEDGER_DIR, f, result, batch)
        from buyer_verification import buyer_errors
        reasons = admission_errors(result, CATEGORY_WHITELIST) + buyer_errors(result)
        if reasons:
            pending.append((fn, "；".join(reasons)))
            continue

        # 空后五位（且无全号）→ 不入库
        if not last5 and not full_num:
            pending.append((fn, "后五位与全号均为空"))
            continue
        # OCR 无全号 → 不入库（G6/L6）
        if result.get("_ocr") and not full_num:
            pending.append((fn, "OCR 未提取到全号"))
            continue

        # ── 判重与冲突拆分（纯函数；判定表见 classify_incoming 与 references/02-dedup-logic.md）──
        kind, ctype_label, creason, other = classify_incoming(
            full_num, last5, amt, date, full_index, triple_index)
        # 所涉主表行的 (原状态, Excel行号)：dup 与 conflict 都有；new 为 ("", None)
        st_prior, row_no = _prior_row_status(
            full_num, last5, amt, date, full_index, triple_index)

        if kind == "dup":
            duplicates.append((fn, creason, full_num or last5, amt))
            conflict_rows.append(_mk_conflict_row(
                now, batch, str(f), fn, seq, category, full_num, last5, amt, date,
                ctype_label, other, creason, prior_status=st_prior, prior_row=row_no))
            continue

        if kind == "conflict":
            conflicts.append((fn, creason, full_num or last5, amt))
            # 冲突同时作用于**主表既有行**：标记为"冲突-待裁"使其金额暂不计入合计
            # （口径见 EXCLUDED_FROM_TOTAL），供 resolve-conflict 还原/定位
            combined = rows + new_rows
            if row_no and row_no - 2 < len(combined):
                prior_row = combined[row_no - 2]
                cur = _cell(prior_row, col_status)
                if cur != "冲突-待裁":
                    prior_row[col_status] = "冲突-待裁"
                    marked.append((row_no, st_prior))
            conflict_rows.append(_mk_conflict_row(
                now, batch, str(f), fn, seq, category, full_num, last5, amt, date,
                ctype_label, other, creason, prior_status=st_prior, prior_row=row_no))
            full_index, triple_index = _build_index(rows + new_rows, col_map)
            continue
            continue

        # 状态
        status = "红冲" if (amt and float(amt) < 0) else "未报"
        if result.get("_ocr"):
            from buyer_verification import proofs
            if not proofs(LEDGER_DIR, full_num, amt, date):
                status = "⚠OCR待人工"

        new_rows.append([
            seq, category, date, amt, last5, fn, batch, full_num, status,
        ])
        full_index, triple_index = _build_index(rows + new_rows, col_map)

    # ── 冲突表去重（**跨运行**）：同 (全号|文件名, 冲突类型) 只登记首次 ──
    # 否则重复导入同一目录会让冲突表虚增；已知项只在本次运行报告里列出。
    conflict_records = []
    if conflict_rows:
        existing_cf = _load_conflicts()
        i_full = CONFLICT_HEADERS.index("发票号码全号")
        i_name = CONFLICT_HEADERS.index("文件名")
        i_type = CONFLICT_HEADERS.index("冲突类型")

        def _ck(r):
            return ((r[i_full] or r[i_name]), r[i_type])

        seen = {_ck(r) for r in existing_cf}
        for r in conflict_rows:
            k = _ck(r)
            if k in seen:
                continue
            seen.add(k)
            conflict_records.append(r)
        base = len(existing_cf)
        stamp = datetime.now().strftime("%Y%m%d")
        for i, r in enumerate(conflict_records, 1):
            r[0] = f"CF-{stamp}-{base + i:04d}"

    # 追加保存（新增发票和／或新冲突记录，均须落盘）
    if new_rows or conflict_records or marked:
        rows.extend(new_rows)
        rc = _save_ledger(rows, conflicts=conflict_records)
        if rc < 0:
            return 1

    # 报告
    print(f"\n{'='*50}")
    print(f"导入报告 [{batch}]")
    print(f"{'='*50}")
    print(f"  新增：{len(new_rows)} 张")
    print(f"  重复：{len(duplicates)} 张（不入主表，冲突表留痕）")
    if duplicates:
        for fn, reason, key, amt in duplicates[:15]:
            print(f"    {fn} → {reason} | {key} | {amt}")
        if len(duplicates) > 15:
            print(f"    ... 共 {len(duplicates)} 张")
    print(f"  冲突：{len(conflicts)} 张（关键字段矛盾 → 待裁，不入主表）")
    if conflicts:
        for fn, reason, key, amt in conflicts[:15]:
            print(f"    {fn} → {reason} | {key} | {amt}")
        if len(conflicts) > 15:
            print(f"    ... 共 {len(conflicts)} 张")
        print(f"    ⚠ 请用 check-schema 查看冲突记录后裁定")
    print(f"  冲突表新增记录：{len(conflict_records)} 条（已登记过的不再重复登记）")
    if marked:
        print(f"  主表标记：{len(marked)} 行置为「冲突-待裁」（金额暂不计入合计）")
        for rn, st in marked[:10]:
            print(f"    Excel 第{rn}行（原状态 {st or '空'}）")
    print(f"  待人工：{len(pending)} 张（不入库）")
    if pending:
        for fn, reason in pending[:15]:
            print(f"    {fn} → {reason}")
        if len(pending) > 15:
            print(f"    ... 共 {len(pending)} 张")
    if errors:
        print(f"  跳过：{len(errors)} 张")
        for fn, reason in errors[:10]:
            print(f"    {fn} → {reason}")

    # 报告文件（utf-8-sig）
    report_path = _sub_dir(LOG_DIRNAME) / f"去重报告_{DATE_NOW}.txt"
    # 日志为运行产物（_ 前缀目录，不参与打包），保留最近 10 个
    for old in sorted(_sub_dir(LOG_DIRNAME).glob("去重报告_*.txt"),
                      key=lambda p: p.stat().st_mtime)[:-10]:
        try:
            old.unlink()
        except OSError:
            pass
    with open(report_path, "w", encoding="utf-8-sig") as f:
        f.write(f"导入报告 [{batch}]  {DATE_NOW}\n")
        f.write(f"来源：{args.src}\n")
        f.write(f"新增：{len(new_rows)}  重复：{len(duplicates)}  冲突：{len(conflicts)}"
                f"  待人工：{len(pending)}  跳过：{len(errors)}\n")
        f.write(f"冲突表新增记录：{len(conflict_records)} 条\n")
        if marked:
            f.write(f"主表标记为「冲突-待裁」：{len(marked)} 行（金额暂不计入合计）\n")
            for rn, st in marked:
                f.write(f"  Excel 第{rn}行 | 原状态 {st or '空'}\n")
        if duplicates:
            f.write("\n重复明细（不入主表，冲突表已留痕）：\n")
            for fn, reason, key, amt in duplicates:
                f.write(f"  {fn} | {reason} | {key} | {amt}\n")
        if conflicts:
            f.write("\n冲突明细（待裁，不入主表）：\n")
            for fn, reason, key, amt in conflicts:
                f.write(f"  {fn} | {reason} | {key} | {amt}\n")
        if pending:
            f.write("\n待人工补录：\n")
            for fn, reason in pending:
                f.write(f"  {fn} | {reason}\n")
    print(f"\n  报告文件：{report_path}")

    from decimal import Decimal
    admitted = [r for r in new_rows if r[8] not in EXCLUDED_FROM_TOTAL]
    summary = {"batch": batch, "files": len(files), "new_records": len(new_rows),
               "new_active": len(admitted), "new_active_amount": str(sum((Decimal(r[3]) for r in admitted), Decimal(0))),
               "duplicates": duplicates, "conflicts": conflicts, "pending": pending, "errors": errors}
    summary_path = _sub_dir("_审计") / (datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # 退出码：有重复/冲突/待人工/跳过 → 2（需人工关注）
    if duplicates or conflicts or pending or errors:
        return 2
    return 0


# ════════════════════════════════════════════════════════════
#  命令: mark-reimbursed
# ════════════════════════════════════════════════════════════

def cmd_mark(args):
    rows, col_map = _load_ledger()
    if not rows:
        print("[INFO] 主台账为空")
        return 0

    col_batch = col_map.get("来源批次", 6)
    col_status = col_map.get("状态", 8)

    batch = args.batch

    # 匹配
    matched = []
    for r in rows:
        b = str(r[col_batch] or "")
        if args.prefix:
            hit = b.startswith(batch)
        elif args.month:
            hit = batch in b  # 子串（月份级）
        else:
            hit = b == batch
        if hit:
            matched.append(r)

    if not matched:
        print(f"[INFO] 未找到批次匹配「{batch}」的记录")
        return 0

    failures = ledger_gate(rows, col_map, EXCLUDED_FROM_TOTAL)
    failures += _check_business(rows, col_map)
    if any(_cell(r, col_status) == "冲突-待裁" for r in matched):
        failures.append((0, "该批次含未裁定冲突"))
    if failures:
        print("[BLOCKED] 报销前校验失败：", failures[:10])
        return 2

    from buyer_verification import check_row
    if any(not check_row(LEDGER_DIR, r) for r in matched if r[col_status] == "未报"):
        print("[BLOCKED] 存在未核验购买方或缺少原票证据的记录")
        return 2
    from reimbursement import assigned_numbers
    reserved = assigned_numbers(LEDGER_DIR)
    if any(str(r[7]) in reserved for r in matched if r[col_status] == "未报"):
        print("[BLOCKED] 发票已分配打印批次，请用 workflow.py reimburse 确认该批次")
        return 2

    # 预览
    to_mark = [r for r in matched if r[col_status] == "未报"]
    skipped = [r for r in matched if r[col_status] != "未报"]
    print(f"\n匹配批次「{batch}」：{len(matched)} 条")
    print(f"  将标记为已报：{len(to_mark)} 条")
    for r in to_mark[:10]:
        print(f"    {r[col_batch]} | {r[5]} | {r[col_status]}")
    if len(to_mark) > 10:
        print(f"    ... 共 {len(to_mark)} 条")
    if skipped:
        # 状态机白名单：红冲/重复/OCR 不标记
        sc = defaultdict(int)
        for r in skipped:
            sc[r[col_status]] += 1
        detail = "，".join(f"{s}×{c}" for s, c in sorted(sc.items()))
        print(f"  跳过（非未报状态）：{len(skipped)} 条（{detail}）")

    if not args.apply:
        print("\n[DRY-RUN] 未执行修改。加 --apply 生效。")
        return 0

    # 执行
    for r in to_mark:
        r[col_status] = "已报"
    rc = _save_ledger(rows)
    if rc < 0:
        return 1
    print(f"\n[OK] 已标记 {len(to_mark)} 条 → 已报")
    return 0


# ════════════════════════════════════════════════════════════
#  命令: report
# ════════════════════════════════════════════════════════════

def cmd_report(args):
    rows, col_map = _load_ledger()
    if not rows:
        print("[INFO] 主台账为空")
        return 0

    col_status = col_map.get("状态", 8)
    col_batch = col_map.get("来源批次", 6)
    col_amt = col_map.get("价税合计（元）", 3)

    filtered = rows
    if args.status:
        filtered = [r for r in filtered if (r[col_status] or "") == args.status]
    if args.batch:
        filtered = [r for r in filtered if args.batch in (r[col_batch] or "")]

    # 不计入合计的状态（口径：冲突/已取代单列，避免合计虚高）
    # 口径统一取模块级 EXCLUDED_FROM_TOTAL（含 冲突-待裁 / 已取代 / 重复-剔除）
    counted = [r for r in filtered if (r[col_status] or "") not in EXCLUDED_FROM_TOTAL]
    excluded = [r for r in filtered if (r[col_status] or "") in EXCLUDED_FROM_TOTAL]
    total = sum(float(r[col_amt] or 0) for r in counted)

    print(f"\n{'='*50}")
    print("发票主台账统计")
    print(f"{'='*50}")
    print(f"  总记录：{len(rows)}")
    if args.status or args.batch:
        print(f"  筛选后：{len(filtered)}")
    print(f"  金额合计（筛选，不含冲突/已取代）：{total:,.2f} 元")

    if excluded:
        ex_total = sum(float(r[col_amt] or 0) for r in excluded)
        print(f"\n  ⚠ 未计入合计（需人工关注）：{len(excluded)} 条 / {ex_total:,.2f} 元")
        ec = defaultdict(int)
        for r in excluded:
            ec[r[col_status] or "未知"] += 1
        for s, c in sorted(ec.items()):
            print(f"    {s}: {c}")

    # 状态分布
    sc = defaultdict(int)
    for r in rows:
        sc[r[col_status] or "未知"] += 1
    print(f"\n  状态分布：")
    for s, c in sorted(sc.items()):
        print(f"    {s}: {c}")

    # 批次分布
    bc = defaultdict(int)
    for r in rows:
        bc[r[col_batch] or "未知"] += 1
    print(f"\n  批次分布：")
    for b, c in sorted(bc.items()):
        print(f"    {b}: {c}")

    # 冲突记录概要（只报计数，不展开明细 —— 明细用 check-schema 查看）
    crows = _load_conflicts()
    i_cst = CONFLICT_HEADERS.index("状态")
    pend_c = sum(1 for r in crows if str(r[i_cst] or "").strip() == "待裁")
    print(f"\n  冲突记录：待裁 {pend_c} 条 / 已归档 {len(crows) - pend_c} 条")
    if pend_c:
        print("    ⚠ 存在待裁冲突，请用 check-schema 查看后裁定")
    return 0


# ════════════════════════════════════════════════════════════
#  命令: check-schema（**只读体检**：台账六级检测）
#     1 可达性 / 2 结构(表头漂移) / 3 可解析性 / 4 冗余互推 /
#     5 业务规则 / 6 双向对账（需 --archive）
# ════════════════════════════════════════════════════════════

# 类别白名单（事实源：invoice_renamer.CATEGORY_RULES 的 name 集合；两者必须一致）
CATEGORY_WHITELIST = frozenset({
    "差旅费", "福利费", "业务费", "办公费", "通讯费", "会议费", "培圳费",
    "办案费", "交通费", "服装费", "资料费", "宣传费", "咨询费", "学习考察费",
})


def _cell(r, i) -> str:
    return str(r[i] or "").strip() if len(r) > i else ""


def _check_parseability(rows, col_map):
    """第 3 级：必填列空值与金额/日期可解析性。"""
    c_seq, c_cat, c_date = (col_map.get("类别序号", 0), col_map.get("发票类别", 1),
                            col_map.get("开票日期", 2))
    c_amt, c_fn = col_map.get("价税合计（元）", 3), col_map.get("文件名", 5)
    out = []
    for n, r in enumerate(rows, start=2):
        problems = []
        if not _cell(r, c_seq):
            problems.append("类别序号为空")
        if not _cell(r, c_cat):
            problems.append("发票类别为空")
        if not _cell(r, c_fn):
            problems.append("文件名为空")
        amt = _cell(r, c_amt)
        if not amt:
            problems.append("价税合计为空")
        else:
            try:
                float(amt)
            except ValueError:
                problems.append(f"金额不可解析({amt!r})")
        d = _cell(r, c_date)
        if d and not re.match(r"^\d{4}-\d{2}-\d{2}$", d):
            problems.append(f"日期格式异常({d!r})")
        if problems:
            out.append((n, "；".join(problems)))
    return out


def _check_redundancy(rows, col_map):
    """第 4 级：内部冗余互推（F 列文件名反推 A/B/C/D 并与台账比对）。

    只比较**跨文件名格式语义一致**的列：
      金额（D）、类别（B）—— 三种格式都提供；
      类别序号（A）—— 仅格式 1/2 提供，空则跳过；
      开票日期（C）—— 仅格式 1 提供，空则跳过。
    **刻意不比后五位**：格式 2 的 4 位数字是「发票代码后四位」，与后五位语义不同
    （见 references/01-template-structure.md），比了会误报。
    """
    c_seq, c_cat, c_date = (col_map.get("类别序号", 0), col_map.get("发票类别", 1),
                            col_map.get("开票日期", 2))
    c_amt, c_fn = col_map.get("价税合计（元）", 3), col_map.get("文件名", 5)
    out = []
    for n, r in enumerate(rows, start=2):
        fn = _cell(r, c_fn)
        if not fn:
            continue
        try:
            pf = extract_fields.parse_filename(fn)
        except Exception:
            continue
        diffs = []
        if pf.get("价税合计（元）") and pf["价税合计（元）"] != _cell(r, c_amt):
            diffs.append(f"金额 台账={_cell(r, c_amt)} 文件名={pf['价税合计（元）']}")
        if pf.get("发票类别") and pf["发票类别"] != _cell(r, c_cat):
            diffs.append(f"类别 台账={_cell(r, c_cat)} 文件名={pf['发票类别']}")
        if pf.get("类别序号") and pf["类别序号"] != _cell(r, c_seq):
            diffs.append(f"类别序号 台账={_cell(r, c_seq)} 文件名={pf['类别序号']}")
        if pf.get("开票日期") and pf["开票日期"] != _cell(r, c_date):
            diffs.append(f"日期 台账={_cell(r, c_date)} 文件名={pf['开票日期']}")
        if diffs:
            out.append((n, fn, "；".join(diffs)))
    return out


def _check_business(rows, col_map):
    """第 5 级：业务规则（全号位数、类别白名单、金额符号）。"""
    c_cat, c_date = col_map.get("发票类别", 1), col_map.get("开票日期", 2)
    c_amt, c_full, c_st = (col_map.get("价税合计（元）", 3),
                           col_map.get("发票号码全号", 7), col_map.get("状态", 8))
    out = []
    for n, r in enumerate(rows, start=2):
        problems = []
        full = _cell(r, c_full)
        if not full:
            problems.append("全号为空（无法判重）")
        elif not valid_identity(full):
            problems.append(f"全号非有效18/20位组合（{full}）")
        cat = _cell(r, c_cat)
        if cat and cat not in CATEGORY_WHITELIST:
            problems.append(f"类别不在白名单（{cat}）")
        amt_raw = _cell(r, c_amt)
        try:
            amt = float(amt_raw)
        except ValueError:
            amt = None                      # 已由第 3 级报出，此处不重复
        if amt is not None:
            st = _cell(r, c_st)
            if st == "红冲":
                if amt >= 0:
                    problems.append("红冲行金额应为负")
            else:
                if amt == 0:
                    problems.append("金额为 0")
                elif amt < 0:
                    problems.append(f"非红冲行金额为负（{amt}）")
        if problems:
            out.append((n, "；".join(problems)))
    return out


def _check_reconcile(rows, col_map, root: Path, batch_filter: str = "", deep: bool = False):
    """第 6 级：台账文件名 ↔ 归档目录文件名 **双向对账**（按文件名，不解析 PDF → 快）。

    deep=True 时额外做**内容校验**：对同名文件解析 PDF、提取 20 位全号，与台账 H 列比对
    （代价是逐个解析 PDF，故为可选项）。
    """
    c_fn, c_batch = col_map.get("文件名", 5), col_map.get("来源批次", 6)
    led = {}
    for n, r in enumerate(rows, start=2):
        if batch_filter and batch_filter not in _cell(r, c_batch):
            continue
        fn = _cell(r, c_fn)
        if fn:
            led.setdefault(fn, n)
    t0 = time.time()
    on_disk = {}
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() == ".pdf":
            on_disk.setdefault(p.name, p)
    elapsed = time.time() - t0

    content_bad = []
    n_cmp = 0
    if deep:
        c_full = col_map.get("发票号码全号", 7)
        c_st = col_map.get("状态", 8)
        # 权威全号取自**全表**（不受 --batch 过滤影响：批次只用于收窄对账范围，
        # 不应改变"哪条记录是权威"）。同名多行时**优先未退休行**——与 _build_index 同原则；
        # 否则"采纳新值"追加的更正行会被已退休的旧行遮蔽，误报全号不符。
        want_full = {}
        for n, r in enumerate(rows, start=2):
            name = _cell(r, c_fn)
            if not name:
                continue
            st = _cell(r, c_st)
            cur = want_full.get(name)
            if cur is None or (cur[1] in EXCLUDED_FROM_TOTAL and st not in EXCLUDED_FROM_TOTAL):
                want_full[name] = (_cell(r, c_full), st)
        for name, p in on_disk.items():
            got_want = want_full.get(name)
            want = (got_want[0] if got_want else "").strip()
            if not want:
                continue          # 目录里有、台账里没有的名字已由双向对账报出
            n_cmp += 1
            try:
                got = (extract_fields.extract_from_pdf(str(p)).get("发票号码全号") or "").strip()
            except Exception as e:
                content_bad.append((name, want, f"解析失败 {type(e).__name__}"))
                continue
            if got != want:
                content_bad.append((name, want, got or "(空)"))
    return (sorted(set(led) - set(on_disk)), sorted(set(on_disk) - set(led)),
            elapsed, content_bad, n_cmp)


def cmd_check_schema(args):
    """只读体检：台账六级检测，结果同时落 `_日志/台账体检_<时间戳>.txt`。

    硬约束（I2）：本命令**不得**改变台账字节数。
    退出码：0=全部通过；1=致命（不可达/被改动）；2=存在需人工关注项。
    """
    import openpyxl
    lines = []

    def emit(s=""):
        print(s)
        lines.append(s)

    # ── 第 1 级：可达性 ──
    if not LEDGER_FILE.exists():
        print(f"[ERROR] 主台账不存在：{LEDGER_FILE}")
        return 1
    size_before = LEDGER_FILE.stat().st_size
    try:
        wb = openpyxl.load_workbook(str(LEDGER_FILE), read_only=True, data_only=True)
    except PermissionError:
        print("[FATAL] 台账被占用（Excel／坚果云同步中），请关闭后重试")
        return 1
    except Exception as e:
        print(f"[FATAL] 台账无法打开：{type(e).__name__}: {e}")
        return 1

    try:
        names = list(wb.sheetnames)
        ws = wb["发票主台账"] if "发票主台账" in names else wb.worksheets[0]
        hdr = [str(c.value or "").strip() for c in next(ws.iter_rows(min_row=1, max_row=1))]
        rows = [list(r) for r in ws.iter_rows(min_row=2, values_only=True)
                if r and any(v is not None for v in r)]
    finally:
        wb.close()

    col_map = {h: i for i, h in enumerate(hdr)} if hdr else \
              {h: i for i, h in enumerate(HEADERS)}

    emit("=" * 56)
    emit("台账体检（只读，六级检测）")
    emit("=" * 56)
    emit(f"  文件：{LEDGER_FILE.name}（{size_before:,} bytes）")
    emit(f"  工作表：{', '.join(names)}")
    emit(f"  主表：{len(rows)} 行 / {len(hdr)} 列（标准 {len(HEADERS)} 列）")

    needs_attention = False

    # ── 第 2 级：结构（表头漂移 → 提示确认，不静默拒绝）──
    emit("")
    emit("[第2级] 结构（表头）")
    std = list(HEADERS)
    if hdr[:len(std)] == std:
        extra = [h for h in hdr[len(std):] if h]
        emit(f"  OK 前 {len(std)} 列与标准一致"
             + (f"；额外列（写盘会被保留）：{', '.join(extra)}" if extra else "；无额外列"))
    else:
        accept = bool(getattr(args, "accept_header_drift", False))
        if not accept:
            needs_attention = True
        emit("  " + ("OK " if accept else "!! ") + "表头与标准不一致"
             + ("——**已按 --accept-header-drift 确认接受**" if accept else "——**请确认**")
             + "（未做任何修改）：")
        for i in range(max(len(std), len(hdr))):
            a = std[i] if i < len(std) else "(无)"
            b = hdr[i] if i < len(hdr) else "(无)"
            if a != b:
                emit(f"     第{i + 1}列：标准={a} / 实际={b}")
        if not accept:
            emit("      → 确认该差异无误后，可加 --accept-header-drift 复跑以消除本项关注")

    # ── 第 3 级：可解析性 ──
    emit("")
    emit("[第3级] 可解析性（必填列空值 / 金额 / 日期）")
    bad3 = _check_parseability(rows, col_map)
    if not bad3:
        emit("  OK 全部行可解析")
    else:
        needs_attention = True
        emit(f"  !! {len(bad3)} 行存在问题（列出行号，前 10 条）：")
        for n, why in bad3[:10]:
            emit(f"     Excel 第{n}行：{why}")
        if len(bad3) > 10:
            emit(f"     … 共 {len(bad3)} 行")

    # ── 第 4 级：内部冗余互推 → 标单行 + 报待人工 ──
    emit("")
    emit("[第4级] 内部冗余互推（文件名反推 vs 台账）")
    bad4 = _check_redundancy(rows, col_map)
    if not bad4:
        emit("  OK 文件名与台账列一致（可比字段：金额/类别/类别序号/日期）")
    else:
        needs_attention = True
        emit(f"  !! {len(bad4)} 行不一致（标单行，报待人工；前 10 条）：")
        for n, fn, why in bad4[:10]:
            emit(f"     Excel 第{n}行 {fn}：{why}")
        if len(bad4) > 10:
            emit(f"     … 共 {len(bad4)} 行")
    emit("  说明：不比后五位——格式2 的 4 位数字是「发票代码后四位」，语义不同")

    # ── 第 5 级：业务规则 ──
    emit("")
    emit("[第5级] 业务规则（全号 20 位 / 类别白名单 / 金额符号）")
    bad5 = _check_business(rows, col_map) + ledger_gate(rows, col_map, EXCLUDED_FROM_TOTAL)
    if not bad5:
        emit("  OK 全部行符合业务规则")
    else:
        needs_attention = True
        emit(f"  !! {len(bad5)} 行违规（前 10 条）：")
        for n, why in bad5[:10]:
            emit(f"     Excel 第{n}行：{why}")
        if len(bad5) > 10:
            emit(f"     … 共 {len(bad5)} 行")

    from buyer_verification import check_row
    unverified = [n for n, row in enumerate(rows, 2)
                  if _cell(row, col_map.get("状态", 8)) not in EXCLUDED_FROM_TOTAL and not check_row(LEDGER_DIR, row)]
    if unverified:
        needs_attention = True
        emit(f"  !! {len(unverified)} 行缺少购买方原票核验；历史记录不自动认定通过（前10行：{unverified[:10]}）")
    else:
        emit("  OK 有效记录均有购买方核验证据")

    # 状态分布与白名单
    emit("")
    emit("  状态分布与白名单校验：")
    sc = defaultdict(int)
    for r in rows:
        sc[_cell(r, col_map.get("状态", 8)) or "(空)"] += 1
    for k in sorted(sc):
        okk = "OK" if (k == "(空)" or k in VALID_STATUS) else "!! 不在白名单"
        if okk != "OK":
            needs_attention = True
        emit(f"    {k}：{sc[k]}  {okk}")

    # 冲突记录表
    crows = _load_conflicts()
    i_cst = CONFLICT_HEADERS.index("状态")
    pend = sum(1 for r in crows if str(r[i_cst] or "").strip() == "待裁")
    arch = len(crows) - pend
    if pend:
        needs_attention = True
    emit(f"  冲突记录表：{'存在' if CONFLICT_SHEET in names else '缺失（下次写盘自动补建）'}"
         f"  待裁 {pend} 条 / 已归档 {arch} 条")
    illegal = sorted({str(r[i_cst] or "").strip() for r in crows}
                     - set(CONFLICT_STATUS))
    if illegal:
        needs_attention = True
        emit(f"  !! 冲突记录表存在非法状态：{illegal}（白名单 {sorted(CONFLICT_STATUS)}）")

    # ── 第 6 级：双向对账（需 --archive）──
    emit("")
    emit("[第6级] 双向对账（台账文件名 ↔ 归档目录）")
    arch_root = Path(args.archive) if getattr(args, "archive", None) else None
    if not arch_root:
        emit("  跳过：未指定归档根目录（如需对账请加 --archive <目录>）")
    elif not arch_root.is_dir():
        needs_attention = True
        emit(f"  !! 归档根目录不存在：{arch_root}")
    else:
        deep = bool(getattr(args, "deep", False))
        only_led, only_disk, sec, content_bad, n_cmp = _check_reconcile(
            rows, col_map, arch_root, getattr(args, "batch", "") or "", deep=deep)
        tag = "（批次过滤：" + args.batch + "）" if getattr(args, "batch", "") else ""
        emit(f"  归档根：{arch_root}{tag}  扫描耗时 {sec:.1f}s"
             + ("　＋内容校验(--deep)" if deep else "")
             + ("  [WARN] 超过 30s，建议改用 --batch 缩小范围" if sec > 30 else ""))
        if not only_led and not only_disk:
            emit("  OK 台账与目录文件名完全对应")
        else:
            needs_attention = True
            if only_led:
                emit(f"  !! 只在台账、目录中找不到：{len(only_led)} 个（前 5）")
                for f in only_led[:5]:
                    emit(f"     {f}")
            if only_disk:
                emit(f"  !! 只在目录、台账未记录：{len(only_disk)} 个（前 5）")
                for f in only_disk[:5]:
                    emit(f"     {f}")
        if deep:
            if content_bad:
                needs_attention = True
                emit(f"  !! 内容校验：{len(content_bad)}/{n_cmp} 个文件的全号与台账不符（前 5）")
                for name, want, got in content_bad[:5]:
                    emit(f"     {name}：台账={want} / PDF={got}")
                emit("     → 用 resolve-conflict 走裁定流程，不要直接改台账")
            elif n_cmp:
                emit(f"  OK 内容校验：{n_cmp} 个同名 PDF 的 20 位全号均与台账一致")
            else:
                emit("  -- 内容校验：无同名文件可比对")

    # ── I2 + 报告落盘 ──
    size_after = LEDGER_FILE.stat().st_size
    same = size_before == size_after
    if not same:
        needs_attention = True
    emit("")
    emit(f"[I2] 体检前后字节：{size_before:,} → {size_after:,}  "
         f"{'未改动 OK' if same else '!! 被改动 FAIL'}")
    emit(f"[结论] {'存在需人工关注项（exit 2）' if needs_attention else '全部通过（exit 0）'}")

    try:
        d = _sub_dir(LOG_DIRNAME)
        rp = d / f"台账体检_{DATE_NOW}.txt"
        rp.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
        for old in sorted(d.glob("台账体检_*.txt"), key=lambda p: p.stat().st_mtime)[:-10]:
            try:
                old.unlink()
            except OSError:
                pass
        print(f"\n  报告文件：{rp}")
    except Exception as e:
        print(f"  [WARN] 报告落盘失败（不影响体检结论）：{e}")

    if not same:
        return 1
    return 2 if needs_attention else 0


# ════════════════════════════════════════════════════════════
#  命令: review（④/4.x 抽验清单 + 留痕；只读）
# ════════════════════════════════════════════════════════════

def cmd_review(args):
    """生成复核抽验清单并留痕（只读台账，仅向 `_日志/` 追加记录）。

    必查项（**全查，无抽样**）：
      a 状态 ⚠OCR待人工   b 状态 冲突-待裁／已取代   c 冲突表 待裁条目
      d 红冲行            e 金额离群（> 3×中位数）    f 冲突表 类型含「低置信」
    抽样：其余行按 --sample-rate（默认 0.05）随机抽取，seed 固定可复现

    分工（4.3）：凡"改台账状态"的裁定性动作 → **律师本人**；
                 "只看不写"的阅读性确认 → 可交助理。
    """
    # ── 回填模式：只把复核结论追加到留痕文件，不生成清单、不触台账 ──
    if getattr(args, "record", None):
        lg = _sub_dir(LOG_DIRNAME) / "复核记录.md"
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        inc = getattr(args, "inconsistent", None)
        head = ""
        if not lg.exists():
            head = ("# 复核记录（append-only）\n\n"
                    "| 时间 | 台账 | 范围 | 总行数 | 必查项 | 抽样数 | 执行安排 |\n"
                    "|---|---|---|---:|---:|---:|---|\n")
        with open(lg, "a", encoding="utf-8") as f:
            if head:
                f.write(head)
            f.write(f"\n### 复核结论回填　{ts}\n"
                    f"- 台账：{LEDGER_FILE.name}｜范围：{args.batch or '全部批次'}\n"
                    f"- 不一致条数：{'未提供' if inc is None else inc}\n"
                    f"- 结论：{args.record}\n")
        print("=" * 56)
        print("复核结论回填（append-only，未触碰台账）")
        print("=" * 56)
        print(f"  不一致条数：{'未提供' if inc is None else inc}")
        print(f"  结论      ：{args.record}")
        print(f"  留痕文件  ：{lg}")
        return 0
    if not LEDGER_FILE.exists():
        print(f"[ERROR] 主台账不存在：{LEDGER_FILE}")
        return 1
    rows, col_map = _load_ledger()
    if not rows:
        print("[INFO] 主台账为空，无需复核")
        return 0

    c_fn = col_map.get("文件名", 5)
    c_batch = col_map.get("来源批次", 6)
    c_amt = col_map.get("价税合计（元）", 3)
    c_st = col_map.get("状态", 8)
    c_cat = col_map.get("发票类别", 1)

    batch_filter = args.batch or ""
    indexed = [(n, r) for n, r in enumerate(rows, start=2)
               if not batch_filter or batch_filter in _cell(r, c_batch)]

    # 金额离群阈值：**按类别分组**取 Q3 + 3×IQR（Tukey 远端）
    # 标定依据（对既有台账实测）：全局 median×3 命中率过高，不可用；
    # 分组 median×3 偏多；分组 Q3+3IQR 命中率最低，可执行。
    # 各类别金额分布异质，必须分组。
    import statistics
    bycat = defaultdict(list)
    for _, r in indexed:
        try:
            bycat[_cell(r, c_cat)].append(abs(float(_cell(r, c_amt))))
        except ValueError:
            pass
    cuts = {}
    for cat, vs in bycat.items():
        vs.sort()
        if len(vs) >= 4:
            q1, q3 = statistics.quantiles(vs, n=4)[0], statistics.quantiles(vs, n=4)[2]
            cuts[cat] = q3 + 3 * (q3 - q1)
        else:
            cuts[cat] = statistics.median(vs) * 3 if vs else float("inf")

    must = []          # (类别, 说明, 建议执行人)
    for n, r in indexed:
        st = _cell(r, c_st)
        fn = _cell(r, c_fn)
        if st == "⚠OCR待人工":
            must.append(("OCR 路径", f"第{n}行 {fn}", "助理（阅读性确认）"))
        if st in ("冲突-待裁", "已取代"):
            must.append(("裁定态行", f"第{n}行 {fn}", "**律师本人**（改状态）"))
        if st == "红冲":
            must.append(("红冲", f"第{n}行 {fn}", "助理（阅读性确认）"))
        try:
            amt = abs(float(_cell(r, c_amt)))
            cut = cuts.get(_cell(r, c_cat))
            if cut is not None and amt > cut:
                must.append(("金额离群", f"第{n}行 {fn} 金额={amt}（该类别阈值 {cut:.2f}）",
                             "**律师本人**（改状态）"))
        except ValueError:
            pass

    crows = _load_conflicts()
    i_cst = CONFLICT_HEADERS.index("状态")
    i_ctyp = CONFLICT_HEADERS.index("冲突类型")
    i_cfn = CONFLICT_HEADERS.index("文件名")
    for r in crows:
        if str(r[i_ctyp] or "").find("低置信") >= 0:
            must.append(("低置信判重", f"冲突表 {r[i_cfn]}", "**律师本人**（改状态）"))
        if str(r[i_cst] or "").strip() == "待裁":
            must.append(("冲突待裁", f"冲突表 {r[i_cfn]}", "**律师本人**（改状态）"))

    # 抽样：排除已在必查项中的行
    must_rows = set()
    for tag, desc, _ in must:
        m = re.search(r"第(\d+)行", desc)
        if m:
            must_rows.add(int(m.group(1)))
    rest = [(n, r) for n, r in indexed if n not in must_rows]
    rate = max(0.0, min(1.0, args.sample_rate))
    k = int(round(len(rest) * rate))
    import random
    rnd = random.Random(20260917)          # 固定 seed → 结果可复现
    sample = rnd.sample(rest, k) if k else []

    lines = []
    lines.append(f"# 复核抽验清单  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"台账：{LEDGER_FILE.name}｜范围：{batch_filter or '全部批次'}｜"
                 f"总行数 {len(indexed)}")
    lines.append(f"抽样率：{rate:.0%}（其余 {len(rest)} 行中抽 {k} 行，seed=20260917）")
    lines.append("")
    lines.append(f"## 一、必查项（全查，共 {len(must)} 项）")
    if not must:
        lines.append("- （无）")
    for tag, desc, who in must:
        lines.append(f"- [{tag}] {desc}　→ 执行人：{who}")
    lines.append("")
    lines.append(f"## 二、抽样项（共 {len(sample)} 行）")
    if not sample:
        lines.append("- （无）")
    for n, r in sample:
        lines.append(f"- 第{n}行 {_cell(r, c_fn)}｜状态 {_cell(r, c_st)}｜"
                     f"金额 {_cell(r, c_amt)}　→ 执行人：助理（阅读性确认）")
    lines.append("")
    lines.append("## 三、口径说明")
    lines.append("- 必查项＝OCR 路径／裁定态行／冲突待裁／红冲／金额离群／低置信判重（全部**全查，无抽样**）")
    lines.append("- 金额离群＝**按类别分组**取 Q3 + 3×IQR（Tukey 远端）；"
                 "标定依据：对既有台账实测，分组 Q3+3IQR 命中率最低，"
                 "而全局 median×3 命中率过高（不可用）")
    lines.append("  各类别阈值：" + "；".join(f"{k}={v:.2f}" for k, v in sorted(cuts.items())))
    lines.append("- **离群 ≠ 错误**：类别粒度较粗（差旅费同时含通行费与机票/住宿），"
                 "故被标出的行应理解为『值得看一眼』，需回看原始凭证再判断，不要据此直接改数据")
    lines.append(f"- 抽样率 {rate:.0%}（seed=20260917，可复现）；必查项盖住的行不重复抽样")
    lines.append("- 分工：凡『改台账状态』的裁定性动作由**律师本人**；"
                 "『只看不写』的阅读性确认可交助理")

    text = "\n".join(lines) + "\n"
    d = _sub_dir(LOG_DIRNAME)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    tag = batch_filter or "全部批次"
    cp = d / f"复核清单_{tag}_{ts}.md"
    cp.write_text(text, encoding="utf-8")

    # 留痕：append-only
    lg = d / "复核记录.md"
    head = "" if lg.exists() else ("# 复核记录（append-only）\n\n"
                                   "| 时间 | 台账 | 范围 | 总行数 | 必查项 | 抽样数 | 执行安排 |\n"
                                   "|---|---|---|---:|---:|---:|---|\n")
    with open(lg, "a", encoding="utf-8") as f:
        if head:
            f.write(head)
        f.write(f"| {datetime.now().strftime('%Y-%m-%d %H:%M')} | {LEDGER_FILE.name} | {tag} | "
                f"{len(indexed)} | {len(must)} | {len(sample)} | "
                f"裁定项→律师本人（{sum(1 for _, _, w in must if '律师' in w)} 项）／"
                f"阅读项→助理（{sum(1 for _, _, w in must if '助理' in w) + len(sample)} 项）|\n")

    print("=" * 56)
    print("复核抽验清单（只读台账）")
    print("=" * 56)
    print(f"  范围：{tag}｜总行数 {len(indexed)}｜抽样率 {rate:.0%}")
    print(f"  【必查项】{len(must)} 项（全查）")
    for tag_, desc, who in must[:15]:
        print(f"    [{tag_}] {desc} → {who}")
    if len(must) > 15:
        print(f"    … 共 {len(must)} 项")
    print(f"  【抽样项】{len(sample)} 行")
    print(f"\n  清单文件：{cp}")
    print(f"  留痕记录：{lg}（已追加 1 行）")
    return 2 if must else 0


# ════════════════════════════════════════════════════════════
#  命令: resolve-conflict（裁定冲突；默认 dry-run）
# ════════════════════════════════════════════════════════════

def cmd_resolve_conflict(args):
    """裁定冲突 —— **唯一**能把「冲突-待裁／已取代／重复-剔除」落地为正式状态的入口。

    默认 dry-run，加 `--apply` 才写盘。`--decision` 三选一：

    | 裁定 | 对主表既有行的处理 |
    |---|---|
    | `采纳新值` | 原行置 `已取代`（不计入合计）＋ **追加一行**按发票新值（状态 `未报`）|
    | `维持台账` | 原行状态**还原**为冲突前的「原状态」（未记录时须 `--restore-status` 指定）|
    | `剔除`     | 原行置 `重复-剔除`（不计入合计）|

    三者都会把冲突记录行置 `已归档`，并填写 `裁定结果` / `裁定时间`。

    「采纳新值」采用**追加新行**而非就地改值：就地改会改变既有全号，触发 I1
    「全号集合只增不减」断言 —— `已取代` ＋ 追加正是为此设计的路径。
    """
    rows, col_map = _load_ledger()
    crows = _load_conflicts()
    if not crows:
        print("[INFO] 冲突记录表为空，无需裁定")
        return 0

    I = {k: CONFLICT_HEADERS.index(k) for k in CONFLICT_HEADERS}
    g = lambda r, k: str(r[I[k]] or "").strip()      # noqa: E731
    pend = [(n, r) for n, r in enumerate(crows, start=2) if g(r, "状态") == "待裁"]
    if not pend:
        print("[INFO] 无「待裁」冲突，无需裁定")
        return 0

    if args.id:
        target = [(n, r) for n, r in pend if g(r, "冲突ID") == args.id]
        if not target:
            print(f"[ERROR] 未找到「待裁」冲突：{args.id}")
            for n, r in pend[:10]:
                print(f"        {g(r, '冲突ID')}｜{g(r, '文件名')}")
            return 1
    elif args.index is not None:
        target = [(n, r) for n, r in pend if n == args.index]
        if not target:
            print(f"[ERROR] Excel 第 {args.index} 行不是「待裁」冲突")
            return 1
    elif len(pend) == 1:
        target = pend
    else:
        print(f"[ERROR] 有 {len(pend)} 条「待裁」冲突，须用 --id 或 --index 指定其一：")
        for n, r in pend[:15]:
            print(f"        [--index {n}] {g(r, '冲突ID')}｜{g(r, '文件名')}")
        if len(pend) > 15:
            print(f"        …… 共 {len(pend)} 条")
        return 1

    _, cf = target[0]
    decision = args.decision

    # ── 定位主表行：优先用记录的「对方行号」，否则按全号/三维回退 ──
    led_row = None
    pr = g(cf, "对方行号")
    if pr.isdigit() and 2 <= int(pr) <= len(rows) + 1:
        led_row = int(pr)
    if led_row is None:
        c_full, c_l5 = col_map.get("发票号码全号", 7), col_map.get("发票号码后五位", 4)
        c_amt, c_date = col_map.get("价税合计（元）", 3), col_map.get("开票日期", 2)
        want_full = g(cf, "发票号码全号")
        for n, r in enumerate(rows, start=2):
            if want_full and _cell(r, c_full) == want_full:
                led_row = n
                break
            if (not want_full and _cell(r, c_l5) == g(cf, "发票号码后五位")
                    and _cell(r, c_amt) == g(cf, "价税合计（元）")
                    and _cell(r, c_date) == g(cf, "开票日期")):
                led_row = n
                break
    if led_row is None:
        print(f"[ERROR] 无法在台账中定位该冲突所涉行（冲突ID {g(cf, '冲突ID')}）")
        print("        → 该行可能已被人工改动；请核对后手工处理")
        return 1

    c_st = col_map.get("状态", 8)
    prev = g(cf, "原状态")
    if decision == "维持台账":
        restore = (args.restore_status or prev).strip()
        if not restore:
            print("[ERROR] 该冲突未记录「原状态」，无法自动还原。")
            print("        请用 --restore-status <状态> 显式指定应还原为的状态")
            return 1
        plan = f"第{led_row}行：冲突-待裁 → 还原为「{restore}」"
    elif decision == "剔除":
        plan = f"第{led_row}行：冲突-待裁 → 重复-剔除（不计入合计）"
    else:
        plan = (f"第{led_row}行：冲突-待裁 → 已取代（不计入合计）；"
                f"另追加 1 行（{g(cf, '发票类别') or '类别空'} / {g(cf, '价税合计（元）')} / "
                f"{g(cf, '开票日期')} / 全号 {g(cf, '发票号码全号')}，状态 未报）")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result_text = decision + (f"｜{args.note}" if args.note else "")
    print("=" * 58)
    print("冲突裁定" + ("（执行）" if args.apply else "（dry-run，加 --apply 执行）"))
    print("=" * 58)
    print(f"  冲突ID  ：{g(cf, '冲突ID')}")
    print(f"  文件    ：{g(cf, '文件名')}")
    print(f"  冲突类型：{g(cf, '冲突类型')}")
    print(f"  冲突原因：{g(cf, '冲突原因')}")
    print(f"  裁定    ：{decision}")
    print(f"  计划    ：{plan}")

    if not args.apply:
        print("\n  [DRY-RUN] 未写盘。确认无误后加 --apply 执行。")
        return 0

    if decision in ("采纳新值", "维持台账"):
        from buyer_verification import proofs
        if decision == "采纳新值":
            verified=proofs(LEDGER_DIR,g(cf,"发票号码全号"),g(cf,"价税合计（元）"),g(cf,"开票日期"))
        else:
            old=rows[led_row-2];verified=proofs(LEDGER_DIR,str(old[7]),str(old[3]),str(old[2]))
        if not verified:
            print("[BLOCKED] 裁定恢复有效记录前必须有抬头通过的原票证据")
            return 2
    # ── 执行 ──
    if decision == "维持台账":
        rows[led_row - 2][c_st] = restore
    elif decision == "剔除":
        rows[led_row - 2][c_st] = "重复-剔除"
    else:
        rows[led_row - 2][c_st] = "已取代"
        # 追加行**继承原状态**（冲突记录里的「原状态」）——否则已报销的票在台账里会变成"未报"，
        # 造成重复报销风险。原状态缺失或本身为退休态时回落到 `未报`。
        st_new = g(cf, "原状态") or "未报"
        if st_new in EXCLUDED_FROM_TOTAL or st_new == "冲突-待裁":
            st_new = "未报"
        rows.append([
            g(cf, "类别序号"), g(cf, "发票类别"), g(cf, "开票日期"),
            g(cf, "价税合计（元）"), g(cf, "发票号码后五位"), g(cf, "文件名"),
            (g(cf, "来源批次") + "（裁定追加）") if g(cf, "来源批次") else "裁定追加",
            g(cf, "发票号码全号"), st_new,
        ])
    cf[I["状态"]] = "已归档"
    cf[I["裁定结果"]] = result_text
    cf[I["裁定时间"]] = now

    rc = _save_ledger(rows, conflicts_full=crows)
    if rc < 0:
        return 1
    rows2, _ = _load_ledger()
    print(f"\n  OK 已裁定：主表 {len(rows2)} 行｜冲突记录已置「已归档」")
    print(f"     裁定结果：{result_text}")
    print("     → 建议接着跑 check-schema 复核状态分布与合计口径")
    return 0


# ════════════════════════════════════════════════════════════
#  主入口
# ════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="发票主台账管理工具")
    # 全局参数：台账目录（可移植性，优先级：CLI > 环境变量 > 脚本位置）
    parser.add_argument("--ledger", help="发票主台账.xlsx 所在目录（默认：$INVOICE_LEDGER_DIR 或脚本父目录）")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="从模板统计表建立台账（仅首次建库；已存在则只读另存）")
    p.add_argument("--src", required=True, help="统计表所在目录")
    p.add_argument("--batch", default="8月", help="批次名（默认 8月）")
    p.add_argument("--reimbursed", action="store_true", help="全部状态=已报")
    p.add_argument("--full-nums-json", help="_dup_check_rmb.json 路径（补全号）")
    p.add_argument("--out", help="候选台账文件名（主台账已存在时必填；生成到 _候选台账/，不触碰主台账）")
    p.add_argument("--ledger", help="台账目录（也可置于子命令前）")

    p = sub.add_parser("import", help="导入新发票文件/目录")
    p.add_argument("--src", required=True, help="文件或目录")
    p.add_argument("--batch", help="批次名（目录导入可自动取目录名）")
    p.add_argument("--img", action="store_true", help="启用图片OCR")
    p.add_argument("--ocr", action="store_true", help="同 --img")
    p.add_argument("--ledger", help="台账目录（也可置于子命令前）")

    p = sub.add_parser("mark-reimbursed", help="标记批次已报销")
    p.add_argument("--batch", required=True)
    p.add_argument("--month", action="store_true", help="月级子串匹配")
    p.add_argument("--prefix", action="store_true", help="前缀匹配")
    p.add_argument("--apply", action="store_true", help="执行（默认 dry-run）")
    p.add_argument("--ledger", help="台账目录（也可置于子命令前）")

    p = sub.add_parser("report", help="统计报表")
    p.add_argument("--status", help="按状态过滤")
    p.add_argument("--batch", help="按批次过滤")
    p.add_argument("--ledger", help="台账目录（也可置于子命令前）")

    p = sub.add_parser("check-schema", help="只读体检：台账六级检测（结构/可解析/冗余互推/业务规则/双向对账）")
    p.add_argument("--archive", help="归档根目录（给出则执行第 6 级双向对账）")
    p.add_argument("--batch", help="对账时按来源批次子串过滤（缩小扫描范围）")
    p.add_argument("--deep", action="store_true",
                   help="第 6 级追加内容校验：解析同名 PDF 的 20 位全号并与台账比对（较慢）")
    p.add_argument("--accept-header-drift", action="store_true",
                   help="确认接受表头与标准不一致（仅用于第 2 级，消除该项关注）")
    p.add_argument("--ledger", help="台账目录（也可置于子命令前）")

    p = sub.add_parser("review", help="生成复核抽验清单并留痕（必查项全查 ＋ 其余抽样）")
    p.add_argument("--batch", help="按来源批次子串过滤")
    p.add_argument("--sample-rate", type=float, default=0.05, help="抽样率（默认 0.05）")
    p.add_argument("--record", metavar="结论",
                   help="回填模式：把复核结论追加到 _日志/复核记录.md（不生成清单）")
    p.add_argument("--inconsistent", type=int, default=None, help="回填模式：发现的不一致条数")
    p.add_argument("--ledger", help="台账目录（也可置于子命令前）")

    p = sub.add_parser("resolve-conflict", help="裁定冲突（默认 dry-run；唯一能落地 冲突-待裁/已取代/重复-剔除 的入口）")
    p.add_argument("--id", help="冲突ID（如 CF-20260917-0001）")
    p.add_argument("--index", type=int, help="冲突记录表行号（与 --id 二选一）")
    p.add_argument("--decision", required=True, choices=list(CONFLICT_DECISIONS),
                   help="裁定：采纳新值 / 维持台账 / 剔除")
    p.add_argument("--restore-status", help="维持台账时显式指定还原状态（原状态未记录时必填）")
    p.add_argument("--note", help="裁定说明（写入 裁定结果）")
    p.add_argument("--apply", action="store_true", help="执行（默认 dry-run）")
    p.add_argument("--ledger", help="台账目录（也可置于子命令前）")

    args = parser.parse_args()
    # 按 CLI --ledger 覆盖台账目录（模块级全局更新，兼容子命令前后两种写法）
    global LEDGER_DIR, LEDGER_FILE
    if getattr(args, "ledger", None):
        LEDGER_DIR = _resolve_ledger_dir(args.ledger)
        LEDGER_FILE = LEDGER_DIR / "发票主台账.xlsx"
    from ledger_lock import transaction_lock
    with transaction_lock(LEDGER_DIR, args.command in {"init", "import", "mark-reimbursed", "resolve-conflict"}):
        return dispatch(args)

def dispatch(args):
    try:
        if args.command == "init":
            return cmd_init(args)
        if args.command == "import":
            return cmd_import(args)
        if args.command == "mark-reimbursed":
            return cmd_mark(args)
        if args.command == "report":
            return cmd_report(args)
        if args.command == "check-schema":
            return cmd_check_schema(args)
        if args.command == "review":
            return cmd_review(args)
        if args.command == "resolve-conflict":
            return cmd_resolve_conflict(args)
        parser.print_help()
        return 0
    except Exception as e:
        print(f"[FATAL] {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
