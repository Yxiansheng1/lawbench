#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
发票PDF解析与重命名工具

功能:
1. 使用 pdfplumber 无头解析PDF发票内容
2. 提取发票关键字段（发票代码、发票号码、价税合计、货物或应税劳务名称等）
3. 根据律所14类发票分类规则自动匹配项目名称
4. 将PDF重命名为: "项目名称 价税合计（小写） 发票代码后四位.pdf"
5. 文件被占用时自动创建副本并重命名副本

用法:
    python invoice_renamer.py <pdf_path_or_directory> [--dry-run]
"""

import argparse
import io
import os
import re
import shutil
import sys
from pathlib import Path

# ── 环境自举：校验当前包指纹并使用外部缓存；无有效环境时中止 ──
import sys as _sys_boot
from pathlib import Path as _Path_boot
_sys_boot.dont_write_bytecode = True
_sys_boot.path.insert(0, str(_Path_boot(__file__).resolve().parent))
import _deps
_deps.guard(__file__)

try:
    import pdfplumber
except ImportError:
    print("[ERROR] pdfplumber 加载失败，请确保依赖包完整")
    sys.exit(1)

# 依赖缺失属环境问题，必须传递为退出码（I3），不得静默跳过导出
class DependencyMissing(RuntimeError):
    """必需依赖缺失。由 __main__ 统一转为退出码 1。"""

    def __init__(self, name: str):
        self.name = name
        super().__init__(f"缺少必需依赖：{name}")


try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
except ImportError:
    Workbook = None

# 注：xlwt（.xls 旧导出）于 3.5.0 随 `export_to_excel` 一并移除 —— 该函数从无调用点，
# 保留它会让一个依赖只为死代码存在。现统一走 openpyxl（.xlsx）。

# ── ③ 阶段门禁阈值 ──
# 字段提取失败率上限：超过则在**重命名前**中止，避免基于不完整数据排出错误的类别序号
EXTRACT_FAIL_RATE_MAX = 0.10

# 餐饮服务分类的业务口径（2026-09-18 用户确认）：
#   < 1000 元 → 福利费；>= 1000 元 → 业务费
# 注：原为三档（>=2000 会议费 / >=500 业务费 / 其余 福利费），已按此口径替换。
# 边界取"含 1000 归业务费"（现网数据无恰好 1000 元，边界不影响结果）。
CATERING_BUSINESS_FEE_THRESHOLD = 1000.0

# 修复 Windows 控制台 UTF-8 输出
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


# ============================================================
# 发票分类关键词与匹配规则
# ============================================================

CATEGORY_RULES = [
    {
        "name": "培圳费",
        "keywords": ["培圳", "培训", "律协", "法律专业课程"],
        "amount_rule": None,
    },
    {
        "name": "会议费",
        "keywords": ["会议"],
        "amount_rule": "catering_gte_2000",
    },
    {
        "name": "差旅费",
        "keywords": [
            "住宿", "机票", "铁路", "铁路电子客票", "电子客票", "高铁票", "火车票", "车票", "船票", "签证", "工本费",
            "代订机票", "代订房费", "代订车费",
            "租车", "用车", "汽车租赁", "通行费", "停车费", "经营租赁", "客运服务费", "运输服务", "代驾服务费",
            "生活服务*代驾",
            "汽油", "轨道交通", "地铁", "公交", "保险服务",
        ],
        "amount_rule": None,
    },
    {
        "name": "办案费",
        "keywords": [
            "停车费", "路桥费", "车辆管理", "车辆维修", "车辆保险",
            "代驾", "零配件", "车船税", "小车汽油", "充值卡",
        ],
        "amount_rule": None,
    },
    {
        "name": "交通费",
        "keywords": ["的士费", "公交车费", "地铁费", "滴滴车费"],
        "amount_rule": None,
    },
    {
        "name": "办公费",
        "keywords": [
            "办公用品", "复印纸", "茶叶", "电脑配件", "显示器", "硬盘",
            "鼠标", "内存", "耗材", "墨盒", "碳粉", "数据线", "手机",
            "录音笔", "快递费", "翻译费", "查询费", "档案费", "技术服务费",
            "电器电子产品及配件", "其他机械设备", "移动通信设备", "通讯器材及配件", "日用杂品", "日用品",
        ],
        "amount_rule": None,
    },
    {
        "name": "通讯费",
        "keywords": ["通信服务费"],
        "amount_rule": None,
    },
    {
        "name": "服装费",
        "keywords": ["服装", "工作服", "衬衫", "西裤", "西装", "上衣", "皮鞋"],
        "amount_rule": None,
    },
    {
        "name": "资料费",
        "keywords": ["图书", "报刊", "期刊"],
        "amount_rule": None,
    },
    {
        "name": "宣传费",
        "keywords": ["烟酒", "广告", "策划", "宣传费", "运动服", "礼品"],
        "amount_rule": None,
    },
    {
        "name": "咨询费",
        "keywords": ["咨询"],
        "amount_rule": None,
    },
    {
        "name": "学习考察费",
        "keywords": ["学习考察", "学习参观"],
        "amount_rule": None,
    },
    {
        "name": "业务费",
        "keywords": [],
        "amount_rule": "catering_500_to_2000",
    },
    {
        "name": "福利费",
        "keywords": ["食品", "水果", "药品", "医疗", "体检", "乳制品", "焙烤", "软饮料"],
        "amount_rule": "catering_lt_500",
    },
]


# ============================================================
# PDF 文本提取
# ============================================================

def extract_text_from_pdf(pdf_path: str) -> str:
    """使用 pdfplumber 无头模式提取 PDF 全部文本内容。"""
    text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception as e:
        print(f"  [WARN] PDF 解析异常: {e}")
    return text


# ============================================================
# 发票字段提取（正则匹配）
# ============================================================

def extract_invoice_fields(text: str) -> dict:
    """
    从提取的文本中解析发票关键字段。

    返回:
        {
            "invoice_code":   str,  # 发票代码
            "invoice_number": str,  # 发票号码
            "amount":         str,  # 价税合计（小写）
            "amount_cn":      str,  # 价税合计（大写）
            "pre_tax_amount": str,  # 金额（不含税）
            "tax":            str,  # 税额
            "items":          list, # 货物或应税劳务名称列表
            "raw_text":       str,  # 原始文本
        }
    """
    fields = {
        "invoice_code": "",
        "invoice_number": "",
        "amount": "",
        "amount_cn": "",
        "pre_tax_amount": "",
        "tax": "",
        "items": [],
        "raw_text": text,
    }

    # 发票代码: 通常10-12位数字
    m = re.search(r"发票代码[：:]\s*(\d{10,12})", text)
    if not m:
        m = re.search(r"发票代码\s*(\d{10,12})", text)
    if m:
        fields["invoice_code"] = m.group(1)

    # 发票号码: 支持8位和20位（全电发票）
    m = re.search(r"发票号码[：:]\s*(\d{8,20})", text)
    if not m:
        m = re.search(r"发票号码\s*(\d{8,20})", text)
    # 回退: 查找20位数字串（全电发票常见格式，号码可能不在"发票号码："后）
    if not m:
        m = re.search(r"(?<!\d)(\d{20})(?!\d)", text)
    if m:
        fields["invoice_number"] = m.group(1)

    from invoice_integrity import total_amount
    fields["amount"], fields["amount_error"] = total_amount(text)

    # 价税合计（大写）
    m = re.search(r"价税合计.*?[（(]大写[)）]\s*([零壹贰叁肆伍陆柒捌玖拾佰仟万亿圆角分整]+\s*多余\d+分?)", text)
    if not m:
        m = re.search(r"[（(]大写[)）]\s*([零壹贰叁肆伍陆柒捌玖拾佰仟万亿圆角分整]+)", text)
    if m:
        fields["amount_cn"] = m.group(1)

    # 不含税金额
    m = re.search(r"合\s*计.*?([\d,]+\.?\d*)\s*[\d.]+%\s*([\d,]+\.?\d*)", text)
    if m:
        fields["pre_tax_amount"] = m.group(1).replace(",", "")
        fields["tax"] = m.group(2).replace(",", "")

    # 货物或应税劳务名称: 尝试多种提取策略
    items = _extract_items(text)
    fields["items"] = items

    return fields


def _extract_items(text: str) -> list:
    """
    从发票文本中提取货物/应税劳务/服务名称。
    使用多种策略提高提取成功率。
    """
    items = []

    # 策略1: 查找 "货物或应税劳务、服务名称" 之后的行
    m = re.search(
        r"货物或应税劳务[、,]服务名称\s*\n(.*?)(?:规格|单位|数量|单价|金额|税率|备注|$)",
        text,
        re.DOTALL,
    )
    if m:
        lines = m.group(1).strip().split("\n")
        for line in lines:
            line = line.strip()
            if line and not re.match(r"^[\d.,\s%]+$", line):
                # 过滤纯数字行
                if len(line) < 50:
                    items.append(line)
        if items:
            return items

    # 策略2: 查找 "*货物或应税劳务" 标记之后的文本（电子发票常见格式）
    m = re.search(r"\*货物或应税劳务[、,]服务名称\*\s*(.*?)(?:规格型号|单位|数量|$)", text, re.DOTALL)
    if m:
        content = m.group(1).strip()
        # 清理掉后续的字段标签
        content = re.split(r"规格型号|数量|单价|金额|税率|备注", content)[0].strip()
        if content:
            items.append(content)
        if items:
            return items

    # 策略3: 查找项目明细关键词（如 "项目名称"、"商品名称"、"服务项目"）
    # 电子发票中 "项目名称" 后跟表格行，如 "*经营租赁*租车费 无 次 1 123.45 ..."
    for label in ["项目名称", "商品名称", "服务项目", "货物名称"]:
        m = re.search(rf"{label}\s+(.*?)(?:\n|$)", text)
        if m:
            raw = m.group(1).strip()
            # 跳过表头行（包含"规格型号"、"金额"、"税额"等列标题）
            if re.search(r"规格型号|税率.*征收率|税\s*额", raw):
                break
            # 清理掉表格中的数字字段，只保留名称部分
            # 格式如: "*经营租赁*租车费 无 次 1 123.45 123.45 13% 16.05"
            cleaned = re.split(r"\s+无\s+|\s+\d+\s+\d", raw)[0].strip()
            if cleaned:
                items.append(cleaned)
            break

    # 策略3.5: 查找 "*类别*名称" 格式（电子发票常见，可能在非标准位置）
    if not items:
        m = re.search(r"\*[^*]+\*[^*\s]+", text)
        if m:
            items.append(m.group(0).strip())

    # 策略4: 在 "名  称" 列之后提取
    m = re.search(r"名\s*称\s*\n(.*?)(?:规格|单位|数量|单价|金额|税率|税额|价税合计)", text, re.DOTALL)
    if m:
        lines = m.group(1).strip().split("\n")
        for line in lines:
            line = line.strip()
            if line and not re.match(r"^[\d.,\s%]+$", line):
                if len(line) < 50:
                    items.append(line)
        if items:
            return items

    # 策略5: 查找 "详见销货清单" 或 "*详见*" 提示
    m = re.search(r"详见销货清单", text)
    if m:
        items.append("详见销货清单")
        return items

    return items


# ============================================================
# 发票分类匹配
# ============================================================

def classify_invoice(fields: dict) -> str:
    """
    根据发票字段和分类规则，返回匹配的项目名称。
    如果无法匹配，返回 "未分类"。
    """
    text_for_match = " ".join(fields.get("items", []))
    raw_text = fields.get("raw_text", "")
    combined_text = f"{text_for_match} {raw_text}"
    amount = 0.0
    try:
        amount = float(fields.get("amount", "0"))
    except (ValueError, TypeError):
        pass

    # 判断是否为餐饮类（含"餐饮"/"餐费"字样；"餐费"兼容仅 items 含"*生产生活服务*餐费"的发票）
    is_catering = bool(re.search(r"餐饮|餐费", combined_text))

    # 特殊规则：同时包含无形资产/会员权益和餐饮服务，归入福利费
    if is_catering and (("无形资产" in combined_text) or ("会员权益" in combined_text)):
        return "福利费"

    for rule in CATEGORY_RULES:
        amount_rule = rule.get("amount_rule")

        # 跳过纯金额规则（餐饮相关），先处理关键词匹配
        if not rule["keywords"] and amount_rule:
            continue

        # 关键词匹配
        matched = False
        for kw in rule["keywords"]:
            if kw in combined_text:
                matched = True
                break

        if matched:
            # 餐饮金额规则的特殊处理
            if rule["name"] == "会议费" and is_catering:
                return "会议费"
            return rule["name"]

    # 餐饮服务金额分流（业务口径，2026-09-18 确认）：
    #   < 1000 元 → 福利费；>= 1000 元 → 业务费
    if is_catering:
        return "福利费" if amount < CATERING_BUSINESS_FEE_THRESHOLD else "业务费"

    return "未分类"


# ============================================================
# 文件重命名（含占用自动副本）
# ============================================================

def safe_rename(src_path: str, new_name: str) -> str:
    """
    安全重命名文件。如果原文件被占用或涉及权限问题，自动创建副本并重命名。

    返回:
        新文件的完整路径
    """
    src = Path(src_path)
    parent = src.parent
    dest = parent / new_name

    # 如果目标文件名与源文件名相同，无需操作
    if src.name == new_name:
        print(f"  [SKIP] 文件名已是目标名称: {src.name}")
        return str(src)

    # 避免覆盖已有文件
    if dest.exists():
        stem = dest.stem
        suffix = dest.suffix
        counter = 1
        while dest.exists() and counter <= 1000:
            dest = parent / f"{stem}_{counter}{suffix}"
            counter += 1
        if counter > 1000:
            print(f"  [ERROR] 无法生成唯一文件名，跳过重命名")
            return str(src)

    # 尝试直接重命名
    try:
        src.rename(dest)
        print(f"  [OK] 重命名成功: {src.name} -> {dest.name}")
        return str(dest)
    except PermissionError:
        print(f"  [WARN] 文件被占用或权限不足，创建副本: {src.name}")
    except OSError as e:
        print(f"  [WARN] 重命名失败 ({e})，创建副本: {src.name}")

    # 创建副本并重命名副本
    try:
        shutil.copy2(src, dest)
        print(f"  [OK] 副本创建并重命名成功: {dest.name}")
        return str(dest)
    except Exception as e:
        print(f"  [ERROR] 副本创建失败: {e}")
        return str(src)


# ============================================================
# 生成新文件名
# ============================================================

def generate_new_filename(category: str, amount: str, invoice_code: str, invoice_number: str = "") -> str:
    """
    生成新文件名: "项目名称 价税合计（小写） 发票代码后四位.pdf"

    参数:
        category:      项目名称（分类名称）
        amount:        价税合计数字字符串
        invoice_code:  发票代码
        invoice_number: 发票号码（当发票代码为空时回退使用）

    返回:
        新文件名字符串（含 .pdf 后缀）
    """
    # 处理价税合计
    if not amount:
        amount_display = "未知金额"
    else:
        try:
            amount_float = float(amount)
            amount_display = f"{amount_float:.2f}"
        except (ValueError, TypeError):
            amount_display = amount

    # 处理发票代码后四位（回退到发票号码）
    code = invoice_code or invoice_number or ""
    if not code or len(code) < 4:
        code_tail = "未知代码"
    else:
        code_tail = code[-4:]

    new_name = f"{category} {amount_display} {code_tail}.pdf"
    return new_name.strip()  # 防止空 category 时产生前导空格




def parse_filename_metadata(filename: str) -> dict:
    """解析文件名中的序号前缀、分类、金额与尾部数字。

    支持的格式（`references/01-template-structure.md` 已登记三种）：
      1. `类别号-类内序号-项目名称 金额 代码后四位.pdf`（9月 renamer，**空格**分隔）
      2. `项目名称 金额 代码.pdf`（同上，无序号前缀）
      3. `类别号-类内序号-YYYY-MM-DD_类别_金额_后五位.pdf`（统计表模板，**下划线**分隔）

    返回值增加 `scheme` 字段（`renamer` / `ymd`）—— 两种格式的**尾部数字语义不同**
    （renamer=发票代码后四位，ymd=发票号码后五位），下游比对必须据此区分，
    否则会把整批 8 月文件误报为"不一致"（2026-09-18 修复）。
    """
    stem = Path(filename).stem
    sort_prefix = ""
    content_stem = stem

    m = re.match(r"^(\d+-\d+)-(.*)$", stem)
    if m:
        sort_prefix = m.group(1)
        content_stem = m.group(2).strip()

    # ── 统计表模板（下划线分隔）：类别号-序号-日期_类别_金额_后五位 ──
    m8 = re.match(r"^(\d{4}-\d{2}-\d{2})_([^_]+)_([\d.]+)_(\d{4,5})(?:_\d+)?$", content_stem)
    if m8:
        return {
            "sort_prefix": sort_prefix,
            "category": m8.group(2),
            "amount_str": m8.group(3),
            "code_tail": m8.group(4),
            "date": m8.group(1),
            "scheme": "ymd",
            "valid": True,
        }

    parts = content_stem.rsplit(" ", 2)
    if len(parts) == 3:
        category, amount_str, code_tail = parts
        # 剥离重复文件去重后缀（如 "5952_1" → "5952"）：safe_rename 对同名文件追加 "_N"
        code_tail = re.sub(r"_\d+$", "", code_tail)
    elif len(parts) == 2:
        category, amount_str = parts
        code_tail = ""
    else:
        return {
            "sort_prefix": sort_prefix,
            "category": "",
            "amount_str": "",
            "code_tail": "",
            "date": "",
            "scheme": "",
            "valid": False,
        }

    return {
        "sort_prefix": sort_prefix,
        "category": category,
        "amount_str": amount_str,
        "code_tail": code_tail,
        "date": "",
        "scheme": "renamer",
        "valid": True,
    }


def verify_rename(result: dict, actual_file: str) -> list:
    """
    重命名完成后，重新打开PDF提取字段，与当前文件名中的信息进行逐项比对。

    参数:
        result:      process_single_pdf 的返回结果（含 fields、category、new_name）
        actual_file: 实际磁盘上的PDF文件路径（重命名后的路径）

    返回:
        错误列表，每个元素为描述不一致的字符串；空列表表示全部通过。
    """
    errors = []

    if not os.path.isfile(actual_file):
        errors.append(f"文件不存在: {actual_file}")
        return errors

    # 从文件名解析预期信息（兼容带序号前缀的文件名）
    filename = os.path.basename(actual_file)
    parsed = parse_filename_metadata(filename)
    if not parsed["valid"]:
        errors.append(f"文件名格式不符合规则: {filename}")
        return errors

    expected_category = parsed["category"]
    expected_amount_str = parsed["amount_str"]
    expected_code_tail = parsed["code_tail"]


    # 重新解析PDF内容
    text = extract_text_from_pdf(actual_file)
    if not text.strip():
        errors.append("重新提取PDF文本为空，无法验证")
        return errors

    fields = extract_invoice_fields(text)
    verify_category = classify_invoice(fields)

    # 比对1: 项目名称（分类）
    if verify_category != expected_category:
        errors.append(
            f"分类不一致: 文件名=[{expected_category}], PDF重新解析=[{verify_category}] "
            f"(货物/服务: {', '.join(fields['items']) or '无'})"
        )

    # 比对2: 金额
    try:
        actual_amount = float(fields.get("amount", "0"))
        expected_amount = float(expected_amount_str)
        if abs(actual_amount - expected_amount) > 0.01:
            errors.append(
                f"金额不一致: 文件名=[{expected_amount_str}], PDF重新解析=[{actual_amount:.2f}]"
            )
    except (ValueError, TypeError):
        if fields.get("amount"):
            errors.append(
                f"金额不一致: 文件名=[{expected_amount_str}], PDF重新解析=[{fields['amount']}]"
            )

    # 比对3: 文件名尾部数字 —— 两种命名格式语义不同，命中任一候选尾部即通过
    #   renamer 格式：尾部 = 发票代码后四位
    #   ymd(8月) 格式：尾部 = 发票号码后五位
    code = fields.get("invoice_code") or ""
    num = fields.get("invoice_number") or ""
    cands = set()
    if len(code) >= 4:
        cands.add(code[-4:])
    if len(num) >= 5:
        cands.add(num[-5:])
    if len(num) >= 4:
        cands.add(num[-4:])
    if expected_code_tail and expected_code_tail != "未知代码" and cands:
        if expected_code_tail not in cands:
            errors.append(
                f"文件名尾部数字与票面不符: 文件名=[{expected_code_tail}], "
                f"候选尾部={sorted(cands)} (发票代码={code or '无'}, 发票号码={num or '无'})"
            )

    return errors


def run_rename_review(results: list, actual_files: list = None) -> list:
    """
    对所有成功重命名的PDF执行复查1: 重新打开PDF解析内容，与文件名逐项比对。

    参数:
        results: process_single_pdf 返回结果列表
        actual_files: 可选，排序重命名后的最终文件路径列表

    返回:
        错误摘要列表，每个元素为格式化的错误描述。
    """
    errors_summary = []
    reviewed = 0

    print(f"\n{'='*60}")
    print("复查1: 重命名验证（文件名 vs PDF实际内容）")
    print(f"{'='*60}")

    file_to_result = {}
    for r in results:
        if not r["success"] or not r.get("fields"):
            continue
        original_path = r.get("new_path") or r.get("path")
        if original_path:
            file_to_result[os.path.basename(original_path)] = r
            file_to_result[Path(original_path).stem] = r

    review_targets = []
    if actual_files:
        for file_path in actual_files:
            if os.path.isfile(file_path):
                review_targets.append(file_path)
    else:
        for r in results:
            if not r["success"] or not r.get("fields"):
                continue
            actual_file = r.get("new_path") or r.get("path")
            if actual_file and os.path.isfile(actual_file):
                review_targets.append(actual_file)

    for actual_file in review_targets:
        filename = os.path.basename(actual_file)
        stem = Path(actual_file).stem
        matched_result = file_to_result.get(filename) or file_to_result.get(stem)
        if not matched_result:
            parsed = parse_filename_metadata(filename)
            if parsed["valid"]:
                matched_result = {
                    "success": True,
                    "fields": {
                        "invoice_code": "",
                        "invoice_number": "",
                        "amount": parsed["amount_str"],
                        "items": [],
                    },
                    "category": parsed["category"],
                    "new_name": filename,
                    "new_path": actual_file,
                    "path": actual_file,
                }
            else:
                continue

        reviewed += 1
        errs = verify_rename(matched_result, actual_file)

        if errs:
            for e in errs:
                errors_summary.append(f"[{filename}] {e}")
        else:
            print(f"  [PASS] {filename}")

    if errors_summary:
        print(f"\n  !! 发现 {len(errors_summary)} 项不一致:")
        for e in errors_summary:
            print(f"    [ERROR] {e}")
    else:
        print(f"\n  全部 {reviewed} 个文件验证通过，无不一致项。")

    print(f"  复查数量: {reviewed} 个文件")
    return errors_summary



# ============================================================
# 处理单个 PDF 文件
# ============================================================

def process_single_pdf(pdf_path: str, dry_run: bool = False) -> dict:
    """
    处理单个PDF文件: 解析 -> 分类 -> 重命名

    返回:
        处理结果字典
    """
    result = {
        "path": pdf_path,
        "success": False,
        "fields": None,
        "category": "未分类",
        "new_name": "",
        "new_path": "",
        "error": "",
    }

    if not os.path.isfile(pdf_path):
        result["error"] = "文件不存在"
        return result

    if not pdf_path.lower().endswith(".pdf"):
        result["error"] = "非PDF文件"
        return result

    print(f"\n{'='*60}")
    print(f"处理文件: {os.path.basename(pdf_path)}")
    print(f"{'='*60}")

    # Step 1: 提取文本
    text = extract_text_from_pdf(pdf_path)
    if not text.strip():
        result["error"] = "PDF文本提取为空"
        print("  [ERROR] 无法提取PDF文本内容")
        return result

    # Step 2: 解析字段
    fields = extract_invoice_fields(text)
    result["fields"] = fields
    from extract_fields import parse_text_fields
    from buyer_verification import buyer_errors
    from invoice_integrity import admission_errors
    verified = parse_text_fields(text, Path(pdf_path).name)
    verified['发票类别'] = classify_invoice(fields)
    reasons = buyer_errors(verified) + admission_errors(verified)
    if reasons:
        result['error'] = '；'.join(reasons)
        print('[BLOCKED]', result['error'])
        return result

    print(f"  发票代码: {fields['invoice_code'] or '未找到'}")
    print(f"  发票号码: {fields['invoice_number'] or '未找到'}")
    print(f"  价税合计: {fields['amount'] or '未找到'}")
    print(f"  货物/服务: {', '.join(fields['items']) if fields['items'] else '未找到'}")

    # Step 3: 分类匹配
    category = classify_invoice(fields)
    result["category"] = category
    print(f"  匹配分类: {category}")

    # Step 4: 生成新文件名
    new_name = generate_new_filename(category, fields["amount"], fields["invoice_code"], fields["invoice_number"])
    result["new_name"] = new_name
    print(f"  新文件名: {new_name}")

    # Step 5: 重命名（dry-run 模式仅预览）
    if dry_run:
        print("  [DRY-RUN] 预览模式，不执行重命名")
        result["success"] = True
    else:
        new_path = safe_rename(pdf_path, new_name)
        result["new_path"] = new_path
        result["success"] = True

    return result


# ============================================================
# 批量处理
# ============================================================

def process_directory(dir_path: str, dry_run: bool = False) -> list:
    """处理目录下所有PDF文件。"""
    results = []
    pdf_dir = Path(dir_path)

    if not pdf_dir.is_dir():
        print(f"[ERROR] 目录不存在: {dir_path}")
        return results

    pdf_files = sorted([f for f in pdf_dir.iterdir()
                        if f.is_file() and f.suffix.lower() == ".pdf"])

    if not pdf_files:
        print(f"[INFO] 目录中未找到PDF文件: {dir_path}")
        return results

    print(f"[INFO] 找到 {len(pdf_files)} 个PDF文件")

    for pdf_file in pdf_files:
        result = process_single_pdf(str(pdf_file), dry_run)
        results.append(result)

    # 打印汇总
    print(f"\n{'='*60}")
    print("处理汇总")
    print(f"{'='*60}")
    success_count = sum(1 for r in results if r["success"])
    fail_count = len(results) - success_count
    print(f"  总计: {len(results)} 个文件")
    print(f"  成功: {success_count} 个")
    print(f"  失败: {fail_count} 个")

    return results


# ============================================================
# 导出 Excel 统计表
# ============================================================


# ============================================================
# V2: 类别序号排序重命名
# ============================================================

def sort_and_rename(results: list, dry_run: bool = False) -> list:
    """
    V2 排序模式: 按类别分组、金额升序排列，添加"类别号-类内序号"前缀。

    返回:
        排序映射列表 [{old_name, new_name, category, amount, code, prefix}, ...]
    """
    success_results = [r for r in results if r["success"] and r.get("fields")]
    if not success_results:
        print("[WARN] 无成功处理的文件，跳过排序重命名")
        return []

    # 提取信息
    items = []
    for r in success_results:
        fields = r["fields"]
        category = r["category"]
        try:
            amount = float(fields.get("amount", "0"))
        except (ValueError, TypeError):
            amount = 0.0
        code = fields.get("invoice_code") or fields.get("invoice_number") or ""
        code_tail = code[-4:] if len(code) >= 4 else "未知"
        old_name = os.path.basename(r.get("new_path") or r.get("path") or "")
        parsed_name = parse_filename_metadata(old_name)
        base_name = old_name
        if parsed_name["valid"] and parsed_name["sort_prefix"]:
            base_name = f"{parsed_name['category']} {parsed_name['amount_str']} {parsed_name['code_tail']}.pdf"
        items.append({
            "old_name": old_name,
            "base_name": base_name,
            "path": r.get("new_path") or r.get("path") or "",
            "category": category,
            "amount": amount,
            "code": code_tail,
        })

    # 按类别分组
    category_order = []
    grouped = {}
    for item in items:
        cat = item["category"]
        if cat not in grouped:
            category_order.append(cat)
            grouped[cat] = []
        grouped[cat].append(item)

    # 类内按金额升序，金额相同按代码排序
    for cat in category_order:
        grouped[cat].sort(key=lambda x: (x["amount"], x["code"]))

    # 分配"类别号-类内序号"
    rename_map = []
    for cat_idx, cat in enumerate(category_order):
        cat_num = cat_idx + 1
        for item_idx, item in enumerate(grouped[cat]):
            prefix = f"{cat_num}-{item_idx + 1}"
            new_name = f"{prefix}-{item['base_name']}"
            rename_map.append({
                "old_name": item["old_name"],
                "new_name": new_name,
                "category": cat,
                "amount": item["amount"],
                "code": item["code"],
                "prefix": prefix,
                "path": item["path"],
            })

    # 执行重命名（逆序避免集合内冲突）
    def _unique_dest(dest: Path) -> Path:
        """目标已存在时自动加 _N 后缀（对齐 next_seq 惯例）：不覆盖、不中止。"""
        if not dest.exists():
            return dest
        stem, suf = dest.stem, dest.suffix
        n = 2
        while True:
            cand = dest.with_name(f"{stem}_{n}{suf}")
            if not cand.exists():
                return cand
            n += 1

    if not dry_run:
        for rm in reversed(rename_map):
            src = Path(rm["path"])
            dest = src.parent / rm["new_name"]
            if src.exists() and src.name != rm["new_name"]:
                dest = _unique_dest(dest)
                if dest.name != rm["new_name"]:
                    print(f"  [WARN] 目标名已存在，改用：{dest.name}")
                try:
                    src.rename(dest)
                    # I2 回读校验：改名后必须确认磁盘真实状态
                    if not dest.exists() or src.exists():
                        raise RuntimeError("重命名后磁盘状态不符")
                    print(f"  [OK] {rm['old_name']} -> {dest.name}")
                    rm["final_path"] = str(dest)
                    rm["new_name"] = dest.name
                except PermissionError:
                    try:
                        shutil.copy2(src, dest)
                        print(f"  [WARN] 源文件被占用，已改为副本方式：{dest.name}")
                        print(f"         ⚠ 原文件 {src.name} 仍在原处，须人工确认后删除")
                        rm["final_path"] = str(dest)
                        rm["new_name"] = dest.name
                        rm["duplicate_leftover"] = str(src)
                    except Exception as e:
                        print(f"  [ERROR] {rm['old_name']}: {e}")
                        rm["final_path"] = str(src)
                except Exception as e:
                    print(f"  [ERROR] {rm['old_name']}: {e}")
                    rm["final_path"] = str(src)
            else:
                rm["final_path"] = rm["path"]
    else:
        for rm in rename_map:
            print(f"  [DRY-RUN] {rm['old_name']} -> {rm['new_name']}")
            rm["final_path"] = rm["path"]

    # ── I2：汇总前回读磁盘，不只信内存 rename_map ──
    if not dry_run and rename_map:
        missing = [rm for rm in rename_map if not Path(rm.get("final_path") or "").exists()]
        if missing:
            print(f"\n  [ERROR] {len(missing)} 个结果文件在磁盘上不存在，本汇总不可信：")
            for rm in missing[:10]:
                print(f"    {rm['old_name']} -> {rm.get('final_path')}")
        leftovers = [rm for rm in rename_map if rm.get("duplicate_leftover")]
        if leftovers:
            print(f"\n  [WARN] {len(leftovers)} 个文件留有副本残留（原文件未删，需人工确认）：")
            for rm in leftovers[:10]:
                print(f"    {Path(rm['duplicate_leftover']).name}")

    # 打印分类汇总
    print(f"\n{'='*60}")
    print("V2 排序结果汇总")
    print(f"{'='*60}")
    for cat_idx, cat in enumerate(category_order):
        cat_items = [rm for rm in rename_map if rm["category"] == cat]
        print(f"  第{cat_idx+1}类 {cat}: {len(cat_items)}个文件 ({cat_items[0]['prefix']} ~ {cat_items[-1]['prefix']})")
    print(f"  总计: {len(rename_map)} 个文件")

    return rename_map


# ============================================================
# V2: 导出带公式的 Excel 统计表 (openpyxl)
# ============================================================

def export_sorted_excel(rename_map: list, output_path: str = "") -> str:
    """
    V2 模式: 将排序结果导出为带公式的 Excel 统计表 (.xlsx)。

    表格格式:
    - 列A: 序号
    - 列B: 类别序号
    - 列C: 项目名称
    - 列D: 金额（元）
    - 列E: 发票代码后四位
    - 合计行使用 =SUM() 公式
    - 分类汇总区使用 =SUM() 公式

    参数:
        rename_map:  sort_and_rename 返回的排序映射列表
        output_path: 输出文件路径

    返回:
        生成的 Excel 文件路径
    """
    if Workbook is None:
        print("[ERROR] openpyxl 未安装，V2 Excel 导出无法执行（环境未就绪）。")
        print("        请先构建技能内环境包：python scripts/build_env_zip.py")
        raise DependencyMissing("openpyxl")

    if not rename_map:
        print("[WARN] 无排序数据，跳过 Excel 导出")
        return ""

    if not output_path:
        first_dir = os.path.dirname(rename_map[0].get("final_path") or rename_map[0].get("path") or ".")
        output_path = os.path.join(first_dir, "发票统计表.xlsx")

    wb = Workbook()
    ws = wb.active
    ws.title = "发票统计"

    # 样式定义
    header_font = Font(bold=True, size=11)
    header_fill = PatternFill("solid", fgColor="D9E1F2")
    header_align = Alignment(horizontal="center", vertical="center")
    thin_border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    sum_font = Font(bold=True, size=11)
    sum_fill = PatternFill("solid", fgColor="FFF2CC")
    summary_header_fill = PatternFill("solid", fgColor="C6E0B4")
    summary_row_fill = PatternFill("solid", fgColor="E2F0D9")
    verify_fill = PatternFill("solid", fgColor="BDD7EE")
    pass_fill = PatternFill("solid", fgColor="C6E0B4")
    fail_fill = PatternFill("solid", fgColor="F4B084")
    warning_fill = PatternFill("solid", fgColor="FFD966")
    info_fill = PatternFill("solid", fgColor="FFF2CC")
    sum_align = Alignment(horizontal="right", vertical="center")
    label_align = Alignment(horizontal="center", vertical="center")
    cell_align = Alignment(horizontal="center", vertical="center")
    wrap_align = Alignment(horizontal="left", vertical="center", wrap_text=True)
    amount_fmt = '#,##0.00'


    # 写表头
    headers = ["序号", "类别序号", "项目名称", "金额（元）", "发票代码后四位"]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = thin_border

    # 写数据行
    for i, rm in enumerate(rename_map):
        row = i + 2  # Excel 行号 (1-based, 表头在 row 1)
        ws.cell(row=row, column=1, value=i + 1).alignment = cell_align
        ws.cell(row=row, column=1).border = thin_border
        ws.cell(row=row, column=2, value=rm["prefix"]).alignment = cell_align
        ws.cell(row=row, column=2).border = thin_border
        ws.cell(row=row, column=3, value=rm["category"]).alignment = cell_align
        ws.cell(row=row, column=3).border = thin_border
        amt_cell = ws.cell(row=row, column=4, value=rm["amount"])
        amt_cell.number_format = amount_fmt
        amt_cell.alignment = sum_align
        amt_cell.border = thin_border
        ws.cell(row=row, column=5, value=rm["code"]).alignment = cell_align
        ws.cell(row=row, column=5).border = thin_border

    data_end_row = len(rename_map) + 1  # 最后一行数据的行号

    # 空行
    empty_row = data_end_row + 1

    # 合计行 (使用公式)
    total_row = empty_row + 1
    cell = ws.cell(row=total_row, column=3, value="合计")
    cell.font = sum_font
    cell.alignment = label_align
    cell.fill = sum_fill
    cell.border = thin_border
    formula_cell = ws.cell(row=total_row, column=4)
    formula_cell.value = f"=SUM(D2:D{data_end_row})"
    formula_cell.number_format = amount_fmt
    formula_cell.font = sum_font
    formula_cell.alignment = sum_align
    formula_cell.fill = sum_fill
    formula_cell.border = thin_border
    ws.cell(row=total_row, column=1).border = thin_border
    ws.cell(row=total_row, column=2).border = thin_border
    ws.cell(row=total_row, column=5).border = thin_border

    # 空行
    empty_row2 = total_row + 1

    # 分类汇总标题行
    sub_header_row = empty_row2 + 1
    cell = ws.cell(row=sub_header_row, column=2, value="分类汇总")
    cell.font = sum_font
    cell.alignment = label_align
    cell.fill = summary_header_fill
    cell.border = thin_border
    for col in [1, 3, 4, 5]:
        header_cell = ws.cell(row=sub_header_row, column=col)
        header_cell.fill = summary_header_fill
        header_cell.border = thin_border

    # 分类小计行 (使用公式)
    # 按类别分组计算行范围
    category_rows = {}
    for i, rm in enumerate(rename_map):
        row = i + 2
        cat = rm["category"]
        if cat not in category_rows:
            category_rows[cat] = {"start": row, "end": row}
        category_rows[cat]["end"] = row

    cat_keys = list(category_rows.keys())
    summary_start_row = sub_header_row + 1
    for idx, cat in enumerate(cat_keys):
        row = summary_start_row + idx
        range_info = category_rows[cat]
        row_fill = summary_row_fill if idx % 2 == 0 else info_fill
        seq_cell = ws.cell(row=row, column=1, value=idx + 1)
        seq_cell.alignment = cell_align
        seq_cell.border = thin_border
        seq_cell.fill = row_fill
        prefix_cell = ws.cell(row=row, column=2, value=f"{idx + 1}-{idx + 1}")
        prefix_cell.alignment = cell_align
        prefix_cell.border = thin_border
        prefix_cell.fill = row_fill
        cell = ws.cell(row=row, column=3, value=cat)
        cell.alignment = cell_align
        cell.border = thin_border
        cell.fill = row_fill
        formula_cell = ws.cell(row=row, column=4)
        formula_cell.value = f"=SUM(D{range_info['start']}:D{range_info['end']})"
        formula_cell.number_format = amount_fmt
        formula_cell.font = sum_font
        formula_cell.alignment = sum_align
        formula_cell.border = thin_border
        formula_cell.fill = row_fill
        count_cell = ws.cell(row=row, column=5, value=range_info['end'] - range_info['start'] + 1)
        count_cell.alignment = cell_align
        count_cell.border = thin_border
        count_cell.fill = row_fill

    # 分类复验合计
    verify_total_row = summary_start_row + len(cat_keys)
    cell = ws.cell(row=verify_total_row, column=3, value="分类小计复验合计")
    cell.font = sum_font
    cell.alignment = label_align
    cell.fill = verify_fill
    cell.border = thin_border
    verify_formula = ws.cell(row=verify_total_row, column=4)
    verify_formula.value = f"=SUM(D{summary_start_row}:D{verify_total_row - 1})"
    verify_formula.number_format = amount_fmt
    verify_formula.font = sum_font
    verify_formula.alignment = sum_align
    verify_formula.fill = verify_fill
    verify_formula.border = thin_border
    verify_count = ws.cell(row=verify_total_row, column=5)
    verify_count.value = f"=SUM(E{summary_start_row}:E{verify_total_row - 1})"
    verify_count.font = sum_font
    verify_count.alignment = cell_align
    verify_count.fill = verify_fill
    verify_count.border = thin_border
    ws.cell(row=verify_total_row, column=1).fill = verify_fill
    ws.cell(row=verify_total_row, column=1).border = thin_border
    ws.cell(row=verify_total_row, column=2).fill = verify_fill
    ws.cell(row=verify_total_row, column=2).border = thin_border

    # 最终校验结果
    final_check_row = verify_total_row + 1
    cell = ws.cell(row=final_check_row, column=3, value="校验结果")
    cell.font = sum_font
    cell.alignment = label_align
    cell.fill = info_fill
    cell.border = thin_border
    check_formula = ws.cell(row=final_check_row, column=4)
    check_formula.value = f'=IF(ABS(D{total_row}-D{verify_total_row})<0.01,"通过","不通过")'
    check_formula.font = sum_font
    check_formula.alignment = cell_align
    check_formula.fill = pass_fill
    check_formula.border = thin_border
    check_desc = ws.cell(row=final_check_row, column=5)
    check_desc.value = f'=IF(ABS(D{total_row}-D{verify_total_row})<0.01,"分类小计之和=总金额","请复核分类小计")'
    check_desc.alignment = cell_align
    check_desc.fill = pass_fill
    check_desc.border = thin_border
    ws.cell(row=final_check_row, column=1).fill = info_fill
    ws.cell(row=final_check_row, column=1).border = thin_border
    ws.cell(row=final_check_row, column=2).fill = info_fill
    ws.cell(row=final_check_row, column=2).border = thin_border

    # 未知/异常识别提示区
    issue_title_row = final_check_row + 2
    issue_unknown = [
        rm for rm in rename_map
        if "未知金额" in rm["new_name"] or "未知代码" in rm["new_name"] or rm["amount"] <= 0
    ]
    issue_categories = sorted({rm["category"] for rm in issue_unknown})
    issue_files = "；".join(rm["new_name"] for rm in issue_unknown) if issue_unknown else "无"
    issue_summary = "、".join(issue_categories) if issue_categories else "无"

    for col in range(1, 6):
        ws.cell(row=issue_title_row, column=col).fill = warning_fill
        ws.cell(row=issue_title_row, column=col).border = thin_border
    title_cell = ws.cell(row=issue_title_row, column=2, value="未知/异常识别提示区")
    title_cell.font = sum_font
    title_cell.alignment = label_align

    issue_labels = [
        ("异常文件数", len(issue_unknown)),
        ("异常分类", issue_summary),
        ("异常文件名", issue_files),
        ("处理建议", "优先复核文件名含“未知金额/未知代码”或金额为0的票据")
    ]

    for idx, (label, value) in enumerate(issue_labels, start=1):
        row = issue_title_row + idx
        label_cell = ws.cell(row=row, column=2, value=label)
        label_cell.font = sum_font
        label_cell.alignment = label_align
        label_cell.fill = warning_fill
        label_cell.border = thin_border
        value_cell = ws.cell(row=row, column=3, value=value)
        value_cell.alignment = wrap_align
        value_cell.fill = info_fill if not issue_unknown else warning_fill
        value_cell.border = thin_border
        ws.merge_cells(start_row=row, start_column=3, end_row=row, end_column=5)
        for col in [1]:
            ws.cell(row=row, column=col).fill = warning_fill
            ws.cell(row=row, column=col).border = thin_border

    if issue_unknown:
        check_formula.fill = fail_fill
        check_desc.fill = fail_fill
        check_desc.value = "存在未知/异常项目，请复核提示区"
    else:
        check_formula.fill = pass_fill
        check_desc.fill = pass_fill
        check_desc.value = "分类小计之和=总金额，且未发现未知/异常项目"


    # 列宽
    ws.column_dimensions["A"].width = 6
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 18
    ws.column_dimensions["D"].width = 14
    ws.column_dimensions["E"].width = 34



    # 保存
    try:
        wb.save(output_path)
        total = sum(rm["amount"] for rm in rename_map)
        print(f"\n[OK] V2 Excel 统计表已导出: {output_path}")
        print(f"     共 {len(rename_map)} 条记录，{len(category_rows)} 个分类，金额合计: {total:,.2f} 元")
        return output_path
    except Exception as e:
        print(f"\n[ERROR] V2 Excel 导出失败: {e}")
        return ""


# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="发票PDF解析与重命名工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python invoice_renamer.py invoice.pdf
  python invoice_renamer.py ./invoices/ --dry-run
  python invoice_renamer.py C:/Users/xxx/Desktop/发票/ --sort
        """,
    )
    parser.add_argument("path", help="PDF文件路径或包含PDF的目录路径")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="预览模式: 仅显示匹配结果，不实际重命名",
    )
    parser.add_argument(
        "--sort",
        action="store_true",
        help="V2 排序模式: 按类别分组、金额升序排列，添加类别序号前缀，并导出带公式的 Excel (.xlsx)",
    )
    args = parser.parse_args()

    target = args.path
    dry_run = args.dry_run
    sort_mode = args.sort

    if not os.path.exists(target):
        print(f"[ERROR] 路径不存在: {target}")
        sys.exit(1)

    if os.path.isfile(target):
        results = [process_single_pdf(target, dry_run)]
    elif os.path.isdir(target):
        results = process_directory(target, dry_run)
    else:
        print(f"[ERROR] 无效路径: {target}")
        sys.exit(1)

    # ── ③ 门禁：字段提取成功率阈值（硬，fail-fast）──
    # 在**排序重命名与导出之前**判定：失败率过高说明输入或提取环节有问题，
    # 此时若继续，会基于不完整数据排出错误的「类别号-类内序号」。
    # 注意：收集阶段（process_directory）已按内容完成首次规范化改名，本门禁
    # 拦的是"排序重命名 + Excel 导出"这一步（才是会把序号整体排错的那一步）。
    if results:
        fail_n = sum(1 for r in results if not r["success"])
        if fail_n:
            rate = fail_n / len(results)
            print(f"\n[INFO] 字段提取：成功 {len(results) - fail_n} / 失败 {fail_n} "
                  f"（失败率 {rate:.1%}，阈值 {EXTRACT_FAIL_RATE_MAX:.0%}）")
            if rate > EXTRACT_FAIL_RATE_MAX:
                print(f"[ERROR] 失败率超过阈值，已中止重命名（不做任何改名/导出）。失败明细：")
                for r in results:
                    if not r["success"]:
                        name = os.path.basename(r.get("path") or r.get("new_path") or "")
                        why = r.get("error") or r.get("reason") or "未提取到字段"
                        print(f"          {name} → {why}")
                sys.exit(1)

    # V2 排序模式: 类别序号排序重命名 + 导出带公式 Excel
    final_review_files = None
    if sort_mode and results:
        print(f"\n{'='*60}")
        print("V2 类别序号排序模式")
        print(f"{'='*60}")
        rename_map = sort_and_rename(results, dry_run)
        if rename_map:
            export_sorted_excel(rename_map)
            # I3：磁盘一致性失败必须影响退出码（部分文件未完成 → 2，需人工关注）
            bad = [rm for rm in rename_map
                   if not Path(rm.get("final_path") or "").exists()]
            if bad and not dry_run:
                print(f"\n[ERROR] {len(bad)} 个重命名结果在磁盘上不存在，须人工处理")
                sys.exit(2)
            final_review_files = [rm.get("final_path") or rm.get("path") for rm in rename_map]

    # 复查1: 重命名验证（对所有成功文件重新解析PDF并比对文件名）
    review_errors = []
    if results:
        review_errors = run_rename_review(results, actual_files=final_review_files) or []

    # ── I3：复查发现的不一致必须影响退出码（原实现只打印、不影响退出码）──
    if review_errors:
        print(f"\n[ERROR] 复查1 发现 {len(review_errors)} 项「文件名 vs PDF 内容」不一致，"
              f"须人工处理（exit 2）")
        sys.exit(2)

    # 失败率在阈值内（≤10%）→ 属"需人工关注"，按契约取 2；超过阈值已在上面 exit 1
    if any(not r["success"] for r in results):
        sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except DependencyMissing as e:
        print(f"\n[FATAL] 运行环境未就绪：缺少 {e.name}")
        sys.exit(1)
