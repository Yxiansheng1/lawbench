#!/usr/bin/env python3
"""
诉讼委托材料生成器 v3.2.0 — 原始 DOCX 模板 + 精确占位符替换
Litigation Retainer Document Generator
广东连越（深圳）律师事务所

████████████████████████████████████████████████████████████████
⚠️  存档说明（重要）：本目录是 v3.2.0 的原样存档，仅用于功能追溯与对照，
    请勿用于实际生成。现行版本是 HTML 版 retainer-offline v3.4.1。

    二者已不一致之处：
      1) 模板目录：本版按「主体-收费」分组（个人-固定 / 个人-半风险 /
         公司-固定 / 公司-半风险 / 刑事，共 22 份）；现行版已改为按主体
         分组（个人委托 / 公司委托 / 刑事，共 13 份）。
      2) 收费条款：本版 FEE_CLAUSES 为单段文本，只支持「固定」「半风险」；
         现行版支持「固定 / 半风险 / 全风险」，条款为段落数组，并在生成时
         由 swapFee 按收费模式替换民事合同的第六条。
      3) 目模板文件的第六条已按现行版规范规整为单锚点段，故本版输出与
         历史 v3.2.0 结果亦不完全相同。

    如需与现行版一致的生成结果，请使用 HTML 版：
        retainer-offline/启动.html
████████████████████████████████████████████████████████████████

流程:
  1. 首次运行 → 从原始 .docx 创建模板 (注入 {{PLACEHOLDER}}, 仅替换变量run)
  2. 每次生成 → ZIP/XML 级别 {{…}} → 值替换 (保留模板格式)
"""

import os, sys, re, shutil, zipfile, json, tempfile, argparse
from datetime import datetime
from docx import Document

# ---------------------------------------------------------------------------
# 存档运行警示（2026-09-16 补入）
# 本文件是 v3.2.0 原样存档，其 FEE_CLAUSES 为旧的单段文本结构，仅支持「固定」
# 与「半风险」；现行 HTML 版 3.4.1 支持「固定 / 半风险 / 全风险」，条款为段落
# 数组并在生成时由 swapFee 替换民事合同第六条。二者对同一案件会产出不同的
# 合同第六条。运行本文件时提示如下，避免静默产出与现行版不一致的结果。
# 设置环境变量 RETRAINER_ARCHIVE_SILENT=1 可抑制本提示（供回归测试使用）。
# ---------------------------------------------------------------------------
if os.environ.get("RETRAINER_ARCHIVE_SILENT") != "1":
    sys.stderr.write(
        "【存档警示】original-skill/generate.py 为 v3.2.0 原样存档，收费条款逻辑与现行版 3.4.1\n"
        "           不一致，直接运行会产出不同的合同第六条。现行版本请使用 启动.html。\n"
    )
from lxml import etree


def _configure_console_encoding():
    """Keep Windows consoles from failing on Unicode status text and filenames."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


_configure_console_encoding()

# ============================================================
# 全局常量
# ============================================================
SKILL_ROOT = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(SKILL_ROOT, "templates")
SRC_BASE = os.path.expanduser(
    os.environ.get("LITIGATION_RETAINER_CIVIL_SRC", "~/Desktop/测试/委托材料/模板-不能修改")
)
CRIMINAL_SRC_BASE = os.path.expanduser(
    os.environ.get("LITIGATION_RETAINER_CRIMINAL_SRC", "~/Desktop/测试/刑事委托材料")
)

LAW_FIRM = "广东连越（深圳）律师事务所"
LAW_FIRM_ADDR = "广东省深圳市福田区深南大道4019号航天大厦A座2106"
LAW_FIRM_BANK = "交通银行股份有限公司深圳华发支行"
LAW_FIRM_ACCOUNT = "4430 6631 9013 0026 23445"
LAW_FIRM_ZIP = "518000"
LEAD_LAWYER = "居君"
LEAD_LAWYER_TEL = "186-6597-7240"
LEAD_LAWYER_TEL_PLAIN = "18665977240"
SECOND_LAWYER = "张文刚"
SECOND_LAWYER_TEL = "159-8940-6216"
SECOND_LAWYER_TEL_PLAIN = "15989406216"
LAWYER_TEAM = "居君律师团队"
ARBITRATION = "深圳国际仲裁院"
CURRENT_YEAR = str(datetime.now().year)

REQUIRED_TEMPLATE_FILES = {
    "个人委托": ["1 民事委托代理合同.docx", "2 授权委托书.docx",
               "⭐️当事人需提供的材料清单.docx", "3 所函.docx"],
    "公司委托": ["1 民事委托代理合同.docx", "2 民事授权委托书.docx",
               "3 法定代表人身份证明.docx", "⭐️贵公司需提供的材料清单.docx", "4 所函.docx"],
    "刑事": ["1、刑事辩护委托合同.docx", "2、刑事授权委托书.docx",
           "⭐️贵方需提供的材料清单.docx", "会见信.docx"],
}

# 刑事案件识别关键词
CRIMINAL_CASE_KEYWORDS = ["刑事", "涉嫌", "犯罪", "辩护", "嫌疑人", "被告人",
                          "拘役", "管制", "逮捕", "羁押", "看守所", "起诉书",
                          "集资诈骗", "诈骗罪", "职务侵占", "帮信", "帮助信息网络犯罪活动", "贩毒", "盗窃", "抢劫", "强奸", "故意伤害",
                          "受贿", "行贿", "贪污", "挪用", "洗钱", "走私",
                          "开设赌场", "非法集资", "寻衅滋事", "聚众斗殴",
                          "危险驾驶", "交通肇事", "容留他人吸毒", "非法经营",
                          "合同诈骗", "信用卡诈骗", "贷款诈骗", "招摇撞骗",
                          "侵犯商业秘密", "虚假广告", "非法行医",
                          "假冒注册商标", "销售假冒注册商标", "假冒专利",
                          "侵犯著作权", "侵犯公民个人信息",
                          "侦查", "审查起诉", "会见", "批捕", "取保候审", "监视居住"]

# 刑事案件代理阶段候选
CRIMINAL_STAGES = ["侦查", "审查起诉", "一审", "二审", "申诉", "再审"]


def detect_case_type(text: str) -> str:
    """根据用户输入检测案件类型。含刑事关键词 → criminal，否则 civil。"""
    if text and "纠纷" in text and not any(k in text for k in ["刑事", "涉嫌", "辩护", "侦查", "审查起诉"]):
        return "civil"
    if not text:
        return "civil"
    for kw in CRIMINAL_CASE_KEYWORDS:
        if kw in text:
            return "criminal"
    return "civil"


# ============================================================
# 自动检测
# ============================================================
def detect_party_type(name: str) -> str:
    for kw in ["公司", "有限公司", "有限责任公司", "股份", "集团", "企业",
               "中心", "事务所", "合伙", "工厂", "银行", "商行", "合作社", "协会", "医院", "学校"]:
        if kw in name.strip(): return "company"
    return "individual"


def detect_fee_type(fee_desc: str) -> str:
    for kw in ["风险", "%", "百分之", "回款", "后期", "分成", "％"]:
        if kw in fee_desc.strip(): return "semi_risk"
    return "fixed"


from runtime_utils import parse_fee, money, fill_template as _fill_template, docx_text
from runtime_utils import unique_directory, replace_text_nodes, NS


def _to_chinese_upper(value):
    return money(value)[0].removesuffix("元整")


def build_case_desc(defendant: str, cause: str) -> str:
    c = cause.rstrip()
    return f"{defendant} {c}" if c.endswith("纠纷") else f"{defendant} {c}纠纷"


def case_label(p, d, c):
    for s in ["有限责任公司", "股份有限公司", "有限公司", "有限合伙"]:
        p = p.replace(s, ""); d = d.replace(s, "")
    return f"{p[:6] if len(p)>6 else p}vs{d[:6] if len(d)>6 else d} {c}"


# ============================================================
# 模板创建引擎 ─ 仅替换变量 run，保留全部格式
# ============================================================
def _templates_complete() -> bool:
    """Return True when the bundled runtime templates are present."""
    for folder, names in REQUIRED_TEMPLATE_FILES.items():
        for name in names:
            if not os.path.isfile(os.path.join(TEMPLATE_DIR, folder, name)):
                return False
    return True


def _mark_templates_ready():
    os.makedirs(TEMPLATE_DIR, exist_ok=True)
    with open(os.path.join(TEMPLATE_DIR, ".ready"), "w", encoding="utf-8") as f:
        f.write("1")


def _missing_source_templates() -> list:
    """List source templates missing from the optional rebuild source paths."""
    civil_sources = [
        (f"{SRC_BASE}/委托材料【个人诉讼案件-半风险】",
         ["1、民事委托代理合同（ 纠纷）.docx", "2、授权委托书（）.docx",
          "⭐️当事人需提供的材料清单（纠纷).docx", "一审所函.docx"]),
        (f"{SRC_BASE}/委托材料【个人诉讼案件-固定】",
         ["1、民事委托代理合同（ 纠纷）.docx", "2、授权委托书（）.docx",
          "⭐️当事人需提供的材料清单（纠纷).docx", "一审所函.docx"]),
        (f"{SRC_BASE}/委托材料【公司诉讼案件-半风险】",
         ["01民事委托代理合同（中科迈航vs营能 建设工程分包合同纠纷）.docx",
          "02民事授权委托书（中科迈航vs营能 建设工程分包合同纠纷）.docx",
          "03法定代表人身份证明（中科迈航vs营能 建设工程分包合同纠纷）.docx",
          "⭐️贵公司需提供的材料清单（中科迈航vs营能 建设工程分包合同纠纷）.docx",
          "一审所函.docx"]),
        (f"{SRC_BASE}/委托材料【公司诉讼案件-固定】",
         ["01民事委托代理合同（中科迈航vs营能 建设工程分包合同纠纷）.docx",
          "02民事授权委托书（中科迈航vs营能 建设工程分包合同纠纷）.docx",
          "03法定代表人身份证明（中科迈航vs营能 建设工程分包合同纠纷）.docx",
          "⭐️贵公司需提供的材料清单（中科迈航vs营能 建设工程分包合同纠纷）.docx",
          "一审所函.docx"]),
    ]
    criminal_sources = [
        (CRIMINAL_SRC_BASE, ["刑事辩护委托合同.docx", "刑事授权委托书.docx",
                             "贵方需提供的材料清单.docx", "会见信.docx"])
    ]

    missing = []
    for src_dir, names in civil_sources + criminal_sources:
        for name in names:
            path = os.path.join(src_dir, name)
            if not os.path.isfile(path):
                missing.append(path)
    return missing


def _rebuild_templates():
    """确保模板存在。优先使用随技能打包的 templates，必要时才从源目录重建。"""
    idx = os.path.join(TEMPLATE_DIR, ".ready")
    if os.path.isfile(idx) and _templates_complete():
        return

    if _templates_complete():
        _mark_templates_ready()
        return

    missing_sources = _missing_source_templates()
    if missing_sources:
        preview = "\n  - ".join(missing_sources[:8])
        if len(missing_sources) > 8:
            preview += f"\n  - ... 另有 {len(missing_sources) - 8} 个缺失文件"
        raise FileNotFoundError(
            "内置模板不完整，且用于重建模板的源文件不存在。\n"
            "请恢复技能目录下的 templates/，或设置 "
            "LITIGATION_RETAINER_CIVIL_SRC / LITIGATION_RETAINER_CRIMINAL_SRC "
            "指向完整源模板目录后重试。\n"
            f"缺失示例：\n  - {preview}"
        )

    # 只有确认源模板完整时才清除并重建，避免误删随技能打包的模板。
    if os.path.isdir(TEMPLATE_DIR):
        shutil.rmtree(TEMPLATE_DIR)
    os.makedirs(TEMPLATE_DIR, exist_ok=True)

    print("创建 DOCX 模板（保留原始格式）...")

    # 个人半风险 → 个人半风险模板（已含半风险收费条款）
    _make_templates("个人", "semi_risk", f"{SRC_BASE}/委托材料【个人诉讼案件-半风险】",
        ["1、民事委托代理合同（ 纠纷）.docx", "2、授权委托书（）.docx",
         "⭐️当事人需提供的材料清单（纠纷).docx", "一审所函.docx"],
        [("contract", "1、民事委托代理合同.docx"), ("auth", "2、授权委托书.docx"),
         ("checklist", "⭐️当事人需提供的材料清单.docx"), ("letter", "一审所函.docx")])

    # 个人固定 → 个人固定模板（已含固定收费条款）
    _make_templates("个人", "fixed", f"{SRC_BASE}/委托材料【个人诉讼案件-固定】",
        ["1、民事委托代理合同（ 纠纷）.docx", "2、授权委托书（）.docx",
         "⭐️当事人需提供的材料清单（纠纷).docx", "一审所函.docx"],
        [("contract", "1、民事委托代理合同.docx"), ("auth", "2、授权委托书.docx"),
         ("checklist", "⭐️当事人需提供的材料清单.docx"), ("letter", "一审所函.docx")])

    comp_files = ["01民事委托代理合同（中科迈航vs营能 建设工程分包合同纠纷）.docx",
                  "02民事授权委托书（中科迈航vs营能 建设工程分包合同纠纷）.docx",
                  "03法定代表人身份证明（中科迈航vs营能 建设工程分包合同纠纷）.docx",
                  "⭐️贵公司需提供的材料清单（中科迈航vs营能 建设工程分包合同纠纷）.docx",
                  "一审所函.docx"]
    comp_dst = [("contract", "01民事委托代理合同.docx"), ("auth", "02民事授权委托书.docx"),
                ("legalrep", "03法定代表人身份证明.docx"),
                ("checklist", "⭐️贵公司需提供的材料清单.docx"), ("letter", "一审所函.docx")]

    # 公司半风险 → 公司半风险模板（已含半风险收费条款）
    _make_templates("公司", "semi_risk", f"{SRC_BASE}/委托材料【公司诉讼案件-半风险】",
                    comp_files, comp_dst)

    # 公司固定 → 公司固定模板（已含固定收费条款）
    _make_templates("公司", "fixed", f"{SRC_BASE}/委托材料【公司诉讼案件-固定】",
                    comp_files, comp_dst)

    # ─────────────────────────────────────────
    # 刑事辩护委托材料模板（统一一套模板）
    # ─────────────────────────────────────────
    crim_src_files = ["刑事辩护委托合同.docx", "刑事授权委托书.docx",
                      "贵方需提供的材料清单.docx", "会见信.docx"]
    crim_dst_pairs = [("contract", "1、刑事辩护委托合同.docx"),
                      ("auth", "2、刑事授权委托书.docx"),
                      ("checklist", "⭐️贵方需提供的材料清单.docx"),
                      ("meeting_letter", "会见信.docx")]

    _make_templates_criminal(f"{CRIMINAL_SRC_BASE}",
                              crim_src_files, crim_dst_pairs)

    _mark_templates_ready()
    print("模板创建完成。")



def ensure_templates():
    """Complete bundled templates are read-only; rebuild in staging before swap."""
    global TEMPLATE_DIR
    if _templates_complete():
        return
    original = TEMPLATE_DIR
    temporary = tempfile.mkdtemp(prefix="retainer-templates-", dir=SKILL_ROOT)
    saved = None
    try:
        TEMPLATE_DIR = temporary
        _rebuild_templates()
        if not _templates_complete():
            raise ValueError("模板重建不完整")
        for folder, names in REQUIRED_TEMPLATE_FILES.items():
            for name in names:
                path = os.path.join(temporary, folder, name)
                _fill_template(path, path + '.tmp', {
                    '2025': '{{YEAR}}', '2026': '{{YEAR}}',
                    '周海沺律师团队': LAWYER_TEAM,
                    '周海沺': LEAD_LAWYER, '135 9016 8866': LEAD_LAWYER_TEL,
                    '13590168866': LEAD_LAWYER_TEL_PLAIN, '1866-5977-240': LEAD_LAWYER_TEL,
                    '大写{{UPFRONT_FEE_SHORT}}': '￥{{UPFRONT_FEE_SHORT}}',
                })
                os.replace(path + '.tmp', path)
        if os.path.exists(original):
            saved = temporary + '-previous'
            os.rename(original, saved)
        try:
            os.rename(temporary, original)
        except Exception:
            if saved:
                os.rename(saved, original)
                saved = None
            raise
    finally:
        TEMPLATE_DIR = original
        if os.path.isdir(temporary):
            shutil.rmtree(temporary)
        if saved and os.path.isdir(saved):
            shutil.rmtree(saved)


def _make_templates(party, fee, src_dir, src_names, dst_pairs, case_type="civil"):
    """从模板源目录复制文件并注入占位符（民商事：按 party × fee 分目录）"""
    out_dir = os.path.join(TEMPLATE_DIR,
        f"{'个人' if party == '个人' else '公司'}-{'半风险' if fee == 'semi_risk' else '固定'}")
    os.makedirs(out_dir, exist_ok=True)

    created = 0
    for (tag, dst_name), src_name in zip(dst_pairs, src_names):
        src = os.path.join(src_dir, src_name)
        if not os.path.isfile(src):
            print(f"  ⚠ 源文件不存在: {src} （跳过）")
            continue
        dst = os.path.join(out_dir, dst_name)
        shutil.copy2(src, dst)
        _inject_placeholders(dst, party, fee, tag, case_type=case_type)
        created += 1

    label = f"{party}-{'半风险' if fee == 'semi_risk' else '固定'}"
    print(f"  ✓ {label}: {created}/{len(dst_pairs)} 模板")


def _make_templates_criminal(src_dir, src_names, dst_pairs):
    """刑事辩护：单一目录，不区分个人/公司/收费方式"""
    out_dir = os.path.join(TEMPLATE_DIR, "刑事")
    os.makedirs(out_dir, exist_ok=True)

    created = 0
    for (tag, dst_name), src_name in zip(dst_pairs, src_names):
        src = os.path.join(src_dir, src_name)
        if not os.path.isfile(src):
            print(f"  ⚠ 源文件不存在: {src} （跳过）")
            continue
        dst = os.path.join(out_dir, dst_name)
        shutil.copy2(src, dst)
        _inject_placeholders(dst, "个人", "fixed", tag, case_type="criminal")
        created += 1

    print(f"  ✓ 刑事: {created}/{len(dst_pairs)} 模板")


# ============================================================
# 占位符注入 — 精确 run 级操作
# ============================================================
def _inject_placeholders(docx_path, party, fee, tag, case_type="civil"):
    """在 .docx 中注入 {{PLACEHOLDER}}，仅修改包含变量文本的 run"""
    doc = Document(docx_path)

    # ── 定义替换规则 ──
    # (搜索文本, 替换为, 选项)
    # 选项: 'exact'=精确匹配, 'blank'=空白下划线run, 'prefix'=前缀定位的空白
    rules = _get_inject_rules(party, fee, tag, case_type=case_type)

    for para in doc.paragraphs:
        _apply_rules_to_para(para, rules)

    # 表格
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    _apply_rules_to_para(para, rules)

    # 页眉页脚
    for section in doc.sections:
        for hdr in [section.header, section.footer,
                     section.first_page_header, section.first_page_footer,
                     section.even_page_header, section.even_page_footer]:
            if hdr:
                for para in hdr.paragraphs:
                    _apply_rules_to_para(para, rules)

    # 后处理：所有含 {{ 的 run 加下划线
    _ensure_placeholder_underline(doc)

    # 合同号行设置为右对齐
    if tag == "contract":
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        for para in doc.paragraphs:
            if "合同号" in para.text and "粤连越深圳民字第" in para.text:
                para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                break

    doc.save(docx_path)


def _ensure_placeholder_underline(doc):
    """Split only plain text runs and retain complete original run properties."""
    import copy
    from docx.text.run import Run
    from docx.oxml.ns import qn
    for para in doc.element.findall('.//w:p', NS):
        for element in list(para.findall('w:r', NS)):
            if any(c.tag not in (qn('w:rPr'), qn('w:t')) for c in element):
                continue
            text = ''.join(element.xpath('./w:t/text()'))
            if '{{' not in text:
                continue
            anchor = element
            for part in re.split(r'(\{\{[A-Z_]+\}\})', text):
                if not part:
                    continue
                clone = copy.deepcopy(element)
                run = Run(clone, None)
                run.text = part
                if re.fullmatch(r'\{\{[A-Z_]+\}\}', part):
                    run.underline = True
                anchor.addnext(clone)
                anchor = clone
            para.remove(element)


def _swap_fee_clause_in_docx(docx_path, target_fee, party, case_type="civil"):
    """替换合同中的收费条款，占位符 run 独立加下划线

    刑事案件没有民事半风险/固定差异化的合同条款模板，
    所有刑事合同统一使用相同的收费结构，因此刑事直接跳过。
    """
    if case_type == "criminal":
        # 刑事委托合同由律师按当事人协商填写，不做模板层 fee 条款切换
        return

    doc = Document(docx_path)

    for para in doc.paragraphs:
        full = para.text
        if "本合同律师费约定如下" not in full:
            continue

        prefix = "六、经双方商定，本合同律师费约定如下："
        for pfx in ["六、经双方商定，本合同律师费约定如下：",
                     "六、经双方商定，本合同律师费约定如下"]:
            if pfx in full:
                prefix = pfx
                break

        if target_fee == "semi_risk":
            new_text = (
                "\n"
                "（1）前期费用：甲方应于本合同签订之日起三（3）个工作日内一次性向乙方支付前期律师费人民币{{UPFRONT_FEE}}（{{UPFRONT_FEE_SHORT}}）；\n"
                "（2）风险费用：除前期费用外，甲方同意按\u201c后期回款金额\u201d的{{RISK_RATE}}向乙方另行支付风险律师费。"
                "\u201c后期回款金额\u201d系指通过和解、调解、裁决、判决、执行或其他任何方式实际收回或抵扣的全部款项。甲方应在收到每笔回款之日起三（3）个工作日内支付。"
            )
        else:
            new_text = (
                "甲方应于本合同签订之日起三（3）个工作日内一次性向乙方支付律师费人民币{{UPFRONT_FEE}}（{{UPFRONT_FEE_SHORT}}）。"
            )

        # 保存原始字体
        orig_font = para.runs[0].font.name if para.runs and para.runs[0].font.name else "仿宋"
        orig_size = para.runs[0].font.size
        from docx.oxml.ns import qn as _qn

        # 清空旧 run
        for r in para.runs:
            r.text = ""

        # 按 {{...}} 分割
        combined = prefix + new_text
        parts = re.split(r'(\{\{[A-Z_]+\}\})', combined)
        for i, part in enumerate(parts):
            if not part:
                continue
            if i == 0 and para.runs:
                run = para.runs[0]
            else:
                run = para.add_run("")
            run.text = part
            run.font.name = orig_font
            run._element.rPr.rFonts.set(_qn('w:eastAsia'), orig_font)
            if orig_size:
                run.font.size = orig_size
            if part.startswith("{{") and part.endswith("}}"):
                run.underline = True
            else:
                run.underline = False

        break

    doc.save(docx_path)


def _apply_rules_to_para(para, rules):
    """对单个段落应用替换规则（增加上下文匹配防止误伤）"""
    full = para.text
    runs = para.runs
    modified = False

    for rule in rules:
        full = para.text
        runs = para.runs
        ctx = rule.get("context", "")
        if ctx and ctx not in full:
            continue

        old = rule.get("old", "")
        new = rule["new"]
        mode = rule.get("mode", "exact")

        if mode == "exact":
            found = False
            for run in runs:
                if old and old in run.text:
                    run.text = run.text.replace(old, new)
                    found = True
                    modified = True
                    break
            if not found and old and old in full:
                _merge_and_replace_in_para(para, old, new)
                modified = True

        elif mode == "blank_prefix":
            prefix = rule.get("prefix", "")
            suffix = rule.get("suffix", "")
            if prefix in full and (not suffix or suffix in full):
                _replace_blank_after_prefix(para, prefix, suffix, new, rule.get("multi", False))
                modified = True

        elif mode == "blank_suffix":
            suffix = rule.get("suffix", "")
            if suffix in full:
                _replace_blank_before_suffix(para, suffix, new)
                modified = True

        elif mode == "underline_after_prefix":
            prefix = rule.get("prefix", "")
            suffix = rule.get("suffix", "")
            if prefix in full and (not suffix or suffix in full):
                replaced = _replace_underline_after_prefix(para, prefix, suffix, new)
                if replaced:
                    modified = True

        elif mode == "regex_replace":
            pattern = rule.get("pattern", "")
            if pattern and re.search(pattern, full):
                _regex_replace_in_para(para, pattern, new)
                modified = True

    # 清理空白 run：仅清除无下划线的空格run（保留下划线填空位）
    if modified:
        for run in para.runs:
            if not run.text.strip() and not run.underline:
                run.text = ""


def _clean_empty_runs(para):
    """清除空 run（仅空格）的内容和格式"""
    for run in para.runs:
        if not run.text.strip():
            run.text = ""
            run.underline = False
            run.bold = False


def _found_in_runs(runs, text):
    """检查文本是否在任意单个 run 中完整出现"""
    for r in runs:
        if text in r.text:
            return True
    return False


def _merge_and_replace_in_para(para, old, new):
    replace_text_nodes(para._element.findall('.//w:t', NS), {old: new})


def _replace_blank_after_prefix(para, prefix, suffix, new, multi=False):
    """替换前缀后、后缀前的空白下划线 run。处理空白+后缀同run的情况"""
    runs = para.runs
    full = para.text

    prefix_pos = full.find(prefix)
    if prefix_pos < 0:
        return
    start_pos = prefix_pos + len(prefix)

    if suffix:
        suffix_pos = full.find(suffix, start_pos)
        if suffix_pos < 0:
            return
        end_pos = suffix_pos
    else:
        end_pos = len(full)

    # 收集空白 run + 处理混合 run
    char_pos = 0
    blank_runs = []
    for ri, run in enumerate(runs):
        run_len = len(run.text)
        run_end = char_pos + run_len
        if run_end > start_pos and char_pos < end_pos:
            txt = run.text
            if txt.strip() == "" and run.underline:
                blank_runs.append(ri)
            elif suffix and run.underline and suffix in txt:
                # 空白和 suffix 在同一 run: 替换整个 run（占位符会包含 suffix 的语义）
                runs[ri].text = new
                return
        char_pos = run_end

    if blank_runs:
        if multi:
            runs[blank_runs[0]].text = new
            for i in blank_runs[1:]:
                runs[i].text = ""
        else:
            runs[blank_runs[0]].text = new
            for i in blank_runs[1:]:
                runs[i].text = ""


def _replace_blank_before_suffix(para, suffix, new):
    """替换后缀前的空白下划线 run"""
    runs = para.runs
    full = para.text
    suffix_pos = full.find(suffix)
    if suffix_pos < 0:
        return

    char_pos = 0
    blank_runs = []
    for ri, run in enumerate(runs):
        run_len = len(run.text)
        if char_pos < suffix_pos:
            txt = run.text
            if txt.strip() == "" and run.underline:
                blank_runs.append(ri)
        char_pos += run_len

    if blank_runs:
        runs[blank_runs[0]].text = new
        for i in blank_runs[1:]:
            runs[i].text = ""


def _replace_underline_after_prefix(para, prefix, suffix, new):
    """替换前缀后第一个有内容的下划线 run（跳过纯空白 run）。

    用于模板在下划线 run 中预填了样本值的情况。
    返回 True 表示成功替换。"""
    runs = para.runs
    full = para.text
    prefix_pos = full.find(prefix)
    if prefix_pos < 0:
        return False
    start_pos = prefix_pos + len(prefix)

    if suffix:
        suffix_pos = full.find(suffix, start_pos)
        if suffix_pos < 0:
            return False
        end_pos = suffix_pos
    else:
        end_pos = len(full)

    # 第一遍：找有内容的下划线 run
    char_pos = 0
    for ri, run in enumerate(runs):
        run_len = len(run.text)
        run_end = char_pos + run_len
        if run_end > start_pos and char_pos < end_pos:
            if run.underline and run.text.strip():
                run.text = new
                return True
        char_pos = run_end

    # 第二遍：没有有内容的下划线 run，则找第一个空白的下划线 run
    char_pos = 0
    for ri, run in enumerate(runs):
        run_len = len(run.text)
        run_end = char_pos + run_len
        if run_end > start_pos and char_pos < end_pos:
            if run.underline:
                run.text = new
                return True
        char_pos = run_end

    return False


def _regex_replace_in_para(para, pattern, new):
    matches = list(re.finditer(pattern, para.text))
    replacements = {m[0]: m.expand(new) for m in matches}
    replace_text_nodes(para._element.findall('.//w:t', NS), replacements)


# ============================================================
# 注入规则定义
# ============================================================
def _get_inject_rules(party, fee, tag, case_type="civil"):
    """返回每个模板的占位符注入规则。每条规则必须有 'context' 字段。"""
    R = []
    is_personal = (party == "个人")
    is_company = (party == "公司")
    is_criminal = (case_type == "criminal")

    # ========================
    # 刑事辩护委托合同
    # ========================
    if is_criminal and tag == "contract":
        # 委托人（甲方）：下划线 run 预填样本值 "张晓燕"，按首个有内容下划线 run 替换
        R.append({"context": "甲方）：", "old": "", "new": "{{CLIENT}}", "mode": "underline_after_prefix",
                   "prefix": "甲方）：", "suffix": "", "multi": False})

        # 当事人（甲方因 ___ 涉嫌）：bound suffix="涉嫌"
        R.append({"context": "因", "old": "", "new": "{{DEFENDANT}}", "mode": "underline_after_prefix",
                   "prefix": "因", "suffix": "涉嫌", "multi": False})

        # 涉嫌罪名
        R.append({"context": "涉嫌", "old": "", "new": "{{CRIME}}", "mode": "underline_after_prefix",
                   "prefix": "涉嫌", "suffix": "", "multi": False})

        # 当事人（犯罪嫌疑人（被告人） ___ 在）：bound suffix="在"
        R.append({"context": "被告人）", "old": "", "new": "{{DEFENDANT}}", "mode": "underline_after_prefix",
                   "prefix": "被告人）", "suffix": "在", "multi": False})

        # 阶段勾选（②③④ 等占位圆圈数字）
        R.append({"context": "在", "old": "", "new": "{{STAGE}}", "mode": "underline_after_prefix",
                   "prefix": "在", "suffix": "阶段", "multi": False})

        # 律师费金额：regex 匹配"律师费人民币40000元"完整段，替换为含{{UPFRONT_FEE}}（已含"元整"）
        R.append({"context": "律师费人民币", "old": "", "new": "律师费人民币{{UPFRONT_FEE}}",
                   "mode": "regex_replace",
                   "pattern": r"律师费人民币\d+元", "multi": False})

        # 年份
        R.append({"context": "字第", "old": CURRENT_YEAR, "new": "{{YEAR}}", "mode": "exact"})

        return R

    # ========================
    # 刑事授权委托书
    # ========================
    if is_criminal and tag == "auth":
        # 委托人：下划线 run 预填样本值 "张晓燕"
        R.append({"context": "委托人", "old": "", "new": "{{CLIENT}}", "mode": "underline_after_prefix",
                   "prefix": "委托人", "suffix": "根据", "multi": False})

        # 涉嫌罪名：bound suffix=" 案件"（run 末尾有" 案件"）
        R.append({"context": "涉嫌", "old": "", "new": "{{CRIME}}", "mode": "underline_after_prefix",
                   "prefix": "涉嫌", "suffix": "案件", "multi": False})

        # 当事人（犯罪嫌疑人（被告人））
        R.append({"context": "被告人）", "old": "", "new": "{{DEFENDANT}}", "mode": "underline_after_prefix",
                   "prefix": "被告人）", "suffix": "的辩护人", "multi": False})

        # 委托期限（直至 ___ ）：使用末段阶段+终结
        R.append({"context": "直至", "old": "", "new": "{{STAGE_DESC}}", "mode": "underline_after_prefix",
                   "prefix": "直至", "suffix": "。", "multi": False})

        # 年份
        R.append({"context": "字第", "old": CURRENT_YEAR, "new": "{{YEAR}}", "mode": "exact"})

        return R

    # ========================
    # 刑事会见信
    # ========================
    if is_criminal and tag == "meeting_letter":
        # 监管场所：看守所/拘留所（替换可能预填的下划线样本）
        for prefix in ["佛山市南海区看守所", "深圳市第一看守所", "广州市第一看守所",
                       "______看守所", "______拘留所"]:
            R.append({"context": "看守所", "old": prefix, "new": "{{DETENTION}}", "mode": "exact"})

        # 涉嫌罪名：模板中下划线 run 通常含样本 "涉嫌XX罪"
        R.append({"context": "涉嫌", "old": "", "new": "{{CRIME}}", "mode": "underline_after_prefix",
                   "prefix": "会见", "suffix": "案", "multi": False})

        # 在押人员姓名：模板中下划线 run 含样本姓名
        R.append({"context": "在押", "old": "", "new": "{{DEFENDANT}}", "mode": "underline_after_prefix",
                   "prefix": "在押犯罪嫌疑人", "suffix": "", "multi": False})
        R.append({"context": "在押", "old": "", "new": "{{DEFENDANT}}", "mode": "underline_after_prefix",
                   "prefix": "在押被告人", "suffix": "", "multi": False})

        # 案号/编号 年份（跨run: "202" + "6"）
        R.append({"context": "粤连越深圳刑字第", "old": CURRENT_YEAR, "new": "{{YEAR}}", "mode": "exact"})

        # 日期由律师手动填写：保留模板原样（"2026年月  日"），不做年份注入

        return R

    # ========================
    # 刑事材料清单
    # ========================
    if is_criminal and tag == "checklist":
        # 案件副标题（嫌疑人涉嫌XX罪一案） — 模板可能预填样本
        R.append({"context": "涉嫌", "old": "（张立涉嫌集资诈骗罪一案）",
                   "new": "（{{CASE_LABEL}}）", "mode": "exact"})
        # 通用模式：尝试匹配任意 "（X涉嫌Y罪一案）"
        R.append({"context": "涉嫌", "pattern": r"（(.+?)涉嫌(.+?)罪一案）",
                   "new": "（{{CASE_LABEL}}）", "mode": "regex_replace"})
        return R

    # ========================
    # 民事委托代理合同
    # ========================
    if tag == "contract":
        # 合同编号中的年份 (跨run: "202" + "6")
        R.append({"context": "合同号：", "old": "2025", "new": "{{YEAR}}", "mode": "exact"})
        R.append({"context": "合同号：", "old": "2026", "new": "{{YEAR}}", "mode": "exact"})

        # 原告名称空白 — 仅个人案件（公司有 exact match）
        if is_personal:
            R.append({"context": "甲方：", "old": "", "new": "{{PLAINTIFF}}", "mode": "blank_prefix",
                       "prefix": "甲方：", "suffix": "", "multi": True})
        # 签名行甲方 — 留空给当事人签字，不注入占位符

        # 对方+案由空白 — 仅个人案件（公司有 exact match）
        if is_personal:
            R.append({"context": "甲方因与", "old": "", "new": "{{DEFENDANT_CAUSE}}", "mode": "blank_prefix",
                       "prefix": "甲方因与", "suffix": "纠纷一案", "multi": True})

        # 代理阶段 (在包含"指派"的段落)
        R.append({"context": "接受甲方的委托", "old": "一审、二审、执行", "new": "{{STAGE}}", "mode": "exact"})
        R.append({"context": "接受甲方的委托", "old": "一审、二审、强制执行", "new": "{{STAGE}}", "mode": "exact"})

        # 律师费 — 只在含"律师费"的段落
        R.append({"context": "律师费", "old": "百分之二（2%）", "new": "{{RISK_RATE}}", "mode": "exact"})
        R.append({"context": "律师费", "old": "百分之二（2.0%）", "new": "{{RISK_RATE}}", "mode": "exact"})
        # 大写金额：空白在"律师费人民币"和"元整"之间
        R.append({"context": "律师费人民币", "old": "", "new": "{{UPFRONT_FEE}}", "mode": "blank_prefix",
                   "prefix": "律师费人民币", "suffix": "元整", "multi": False})
        # 小写金额：空白在"（￥"和"）"之间
        R.append({"context": "律师费人民币", "old": "", "new": "{{UPFRONT_FEE_SHORT}}", "mode": "blank_prefix",
                   "prefix": "（￥", "suffix": "）", "multi": False})

        # 合同编号空白 (字第和号之间的空白，用空格保持行宽不变)
        R.append({"context": "字第", "old": "", "new": "      ", "mode": "blank_prefix",
                   "prefix": "字第", "suffix": "号", "multi": True})

        # 公司特有
        if is_company:
            R.append({"context": "甲方：", "old": "中科迈航信息技术有限公司", "new": "{{PLAINTIFF}}", "mode": "exact"})
            # 签名行甲方：清除公司名，留白盖章
            R.append({"context": "甲  方：", "old": "中科迈航信息技术有限公司", "new": "", "mode": "exact"})
            R.append({"context": "甲方因与", "old": "广东营能建筑工程有限公司  建设工程分包合同",
                       "new": "{{DEFENDANT_CAUSE}}", "mode": "exact"})

    # ========================
    # 授权委托书
    # ========================
    elif tag == "auth":
        R.append({"context": "委 托 人：", "old": "刘存雄", "new": "{{PLAINTIFF}}", "mode": "exact"})
        R.append({"context": "委 托 方：", "old": "中科迈航信息技术有限公司", "new": "{{PLAINTIFF}}", "mode": "exact"})
        R.append({"context": "委 托 人：", "old": "", "new": "{{PLAINTIFF}}", "mode": "blank_prefix",
                   "prefix": "委 托 人：", "suffix": "", "multi": False})

        R.append({"context": "我方诉", "old": "王虹、兰曙光  股权转让", "new": "{{DEFENDANT_CAUSE}}", "mode": "exact"})
        R.append({"context": "我方与", "old": "广东营能建筑工程有限公司", "new": "{{DEFENDANT}}", "mode": "exact"})
        R.append({"context": "我方与", "old": "建设工程分包合同", "new": "{{CAUSE}}", "mode": "exact"})

        R.append({"context": "阶段的代理人", "old": "一审、二审、执行", "new": "{{STAGE}}", "mode": "exact"})
        R.append({"context": "阶段的代理人", "old": "一审、二审、强制执行", "new": "{{STAGE}}", "mode": "exact"})

        # 年份不替换 — 授权委托书日期行保持原样

        if is_company:
            R.append({"context": "委托人（盖章）", "old": "委托人（盖章）：中科迈航信息技术有限公司",
                       "new": "委托人（盖章）：{{PLAINTIFF}}", "mode": "exact"})

    # ========================
    # 法定代表人身份证明
    # ========================
    elif tag == "legalrep":
        R.append({"context": "单位全称", "old": "中科迈航信息技术有限公司", "new": "{{PLAINTIFF}}", "mode": "exact"})
        R.append({"context": "兹有", "old": "朱新为", "new": "{{LEGAL_REP}}", "mode": "exact"})
        R.append({"context": "兹有", "old": "董事长", "new": "{{LEGAL_REP_POSITION}}", "mode": "exact"})
        # 年份不替换 — 日期行保持原样

    # ========================
    # 材料清单
    # ========================
    elif tag == "checklist":
        for lp in ["刘存雄vs兰曙光&王虹股权转让纠纷", "中科迈航vs营能 建设工程分包合同纠纷"]:
            R.append({"context": lp, "old": lp, "new": "{{CASE_LABEL}}", "mode": "exact"})

    # ========================
    # 所函
    # ========================
    elif tag == "letter":
        R.append({"context": "本所接受", "old": "刘存雄", "new": "{{PLAINTIFF}}", "mode": "exact"})
        R.append({"context": "本所接受", "old": "中科迈航信息技术有限公司", "new": "{{PLAINTIFF}}", "mode": "exact"})

        # 法院：整个法院名替换为 {{COURT}}（含"人民法院"）
        R.append({"context": "人民法院", "old": "深圳市龙华区人民法院", "new": "{{COURT}}", "mode": "exact"})
        R.append({"context": "人民法院", "old": "深圳市坪山区人民法院", "new": "{{COURT}}", "mode": "exact"})

        R.append({"context": "贵院受理", "old": "刘存雄 与 王虹、兰曙光  股权转让纠纷",
                   "new": "{{CASE_FULL}}", "mode": "exact"})
        R.append({"context": "贵院受理", "old": "中科迈航信息技术有限公司与广东营能建筑工程有限公司 建设工程施工合同纠纷",
                   "new": "{{CASE_FULL}}", "mode": "exact"})

        R.append({"context": "案件中", "old": "一审阶段", "new": "{{FIRST_STAGE}}", "mode": "exact"})

    return R


# ============================================================
# 文档生成 — ZIP/XML 级别 {{…}} → 值替换
# ============================================================
def generate_documents(params: dict, create_case: bool = False) -> dict:
    """生成委托材料 .docx 文件。

    Args:
        params: 案件参数字典
        create_case: 是否同时创建案件文件夹（默认 False，仅生成委托材料）
    """
    params = dict(params)
    if params.get("case_type") == "criminal":
        params.setdefault("plaintiff", params.get("client", ""))
    for key in ("plaintiff", "defendant", "stage", "crime" if params.get("case_type") == "criminal" else "cause"):
        if not str(params.get(key, "")).strip():
            raise ValueError(f"必填参数为空：{key}")
    ensure_templates()

    party = params["party_type"]
    fee = params["fee_type"]
    case_type = params.get("case_type", "civil")

    if case_type == "criminal":
        tmpl_dir = os.path.join(TEMPLATE_DIR, "刑事")
    else:
        tmpl_dir = os.path.join(TEMPLATE_DIR,
            f"{'个人' if party == 'individual' else '公司'}-{'半风险' if fee == 'semi_risk' else '固定'}")

    if not os.path.isdir(tmpl_dir):
        raise FileNotFoundError(f"模板目录不存在: {tmpl_dir}")

    reps = _build_replacements(params)

    if case_type == "criminal":
        client = params.get("client") or params.get("plaintiff", "当事人")
        defendant = params.get("defendant") or params.get("plaintiff", "当事人")
        crime = params.get("crime", "")
        if crime and not crime.endswith("罪"):
            crime_label = crime + "罪"
        else:
            crime_label = crime or "刑事案件"
        output_dir_name = f"委托材料【刑事辩护 {defendant}涉嫌{crime_label}】"
    else:
        output_dir_name = f"委托材料【{'个人' if party == 'individual' else '公司'}诉讼案件-{'半风险' if fee == 'semi_risk' else '固定'}】"

    output_base = params.get("output_base", os.getcwd())
    output_dir = unique_directory(output_base, output_dir_name)

    files = {}
    for fname in sorted(os.listdir(tmpl_dir)):
        if not fname.endswith(".docx"):
            continue
        src = os.path.join(tmpl_dir, fname)
        dst = os.path.join(output_dir, fname)
        _fill_template(src, dst, reps)
        files[fname] = dst

    # 生成后校验
    errors = _verify_output(files, params)
    if errors:
        raise ValueError("生成校验失败（未归档）：\n" + "\n".join(errors))

    case_dir = None
    if create_case:
        case_dir = create_case_folder(params, output_base, files)

    return {"success": True, "output_dir": output_dir, "files": files, "case_dir": case_dir}


def create_case_folder(params, output_base, files):
    """创建案件目录结构并复制委托材料。

    民商事：在 output_base 下创建 "{原告}vs{被告} {案由}纠纷/" 目录
    刑事：在 output_base 下创建 "{当事人}涉嫌{罪名}/" 目录

    Args:
        params: 案件参数字典
        output_base: 案件文件夹的父目录
        files: {文件名: 源路径} 字典

    Returns:
        case_dir: 案件文件夹路径
    """
    is_criminal = params.get("case_type", "civil") == "criminal"

    if is_criminal:
        defendant = params.get("defendant", "当事人")
        crime = params.get("crime", "刑事案件")
        if not crime.endswith("罪") and crime != "______":
            crime = crime + "罪"
        case_name = f"{defendant}涉嫌{crime}"
        subdirs = [
            "01委托手续",
            "02案件材料/会见笔录",
            "02案件材料/家属沟通",
            "02案件材料/涉案证据",
            "03侦查阶段/我方文件",
            "03侦查阶段/我方证据",
            "03侦查阶段/对方文件",
            "03侦查阶段/对方证据",
            "03侦查阶段/法律研究",
            "04审查起诉阶段/我方文件",
            "04审查起诉阶段/我方证据",
            "04审查起诉阶段/对方文件",
            "04审查起诉阶段/对方证据",
            "04审查起诉阶段/法律研究",
            "05一审/我方文件",
            "05一审/我方证据",
            "05一审/对方文件",
            "05一审/对方证据",
            "05一审/庭审准备",
            "05一审/法院文书",
            "06二审/我方文件",
            "06二审/我方证据",
            "06二审/对方文件",
            "06二审/对方证据",
            "06二审/庭审准备",
            "06二审/法院文书",
            "07申诉与再审",
            "08执行（财产刑/民事赔偿）",
        ]
    else:
        plaintiff = params["plaintiff"]
        defendant = params["defendant"]
        cause = params["cause"].rstrip()
        if cause.endswith("纠纷"):
            cause = cause[:-2]
        case_name = f"{plaintiff}vs{defendant} {cause}纠纷"
        subdirs = [
            "01委托手续",
            "02案件材料",
            "03一审/我方文件",
            "03一审/我方证据",
            "03一审/对方文件",
            "03一审/对方证据",
            "03一审/庭审准备",
            "03一审/法院文书",
            "04二审/我方文件",
            "04二审/我方证据",
            "04二审/对方文件",
            "04二审/对方证据",
            "04二审/庭审准备",
            "04二审/法院文书",
            "05执行/执行申请",
            "05执行/财产线索",
            "05执行/法院文书",
            "06法律研究",
        ]

    case_dir = unique_directory(output_base, case_name)
    for d in subdirs:
        os.makedirs(os.path.join(case_dir, d), exist_ok=True)

    # 复制委托材料到委托手续
    for fname, src_path in files.items():
        dst = os.path.join(case_dir, "01委托手续", fname)
        shutil.copy2(src_path, dst)

    print(f"\n案件目录：{case_dir}")
    return case_dir


def _verify_output(files: dict, params: dict) -> list:
    """检查生成的 docx 是否有残留占位符或缺失关键信息"""
    errors = []
    is_criminal = params.get("case_type", "civil") == "criminal"
    plaintiff = params["plaintiff"]
    defendant = params.get("defendant", "")
    crime = params.get("crime", "")

    if is_criminal:
        client = params.get("client") or plaintiff
        suspect = defendant or plaintiff
        check_keys = [client, suspect, crime]
    else:
        cause_val = params["cause"].rstrip()
        if cause_val.endswith("纠纷"):
            cause_val = cause_val[:-2]
        check_keys = [plaintiff, defendant, cause_val]

    for fname, path in files.items():
        try:
            text = docx_text(path)

            # 残留占位符
            if "{{" in text:
                phs = re.findall(r'\{\{[A-Z_]+\}\}', text)
                errors.append(f"{fname}: 残留占位符 {phs}")

            # 合同要检查委托人/当事人
            if is_criminal:
                if "刑事辩护委托合同" in fname and client not in text:
                    errors.append(f"{fname}: 缺少委托人 {client}")
                if "刑事辩护委托合同" in fname and suspect not in text:
                    errors.append(f"{fname}: 缺少当事人 {suspect}")
            else:
                if "民事委托代理合同" in fname and plaintiff not in text:
                    errors.append(f"{fname}: 缺少甲方名称 {plaintiff}")

            # 含case label的要检查
            if not any(k and k in text for k in check_keys if k):
                if "所函" in fname or "会见信" in fname or "合同" in fname:
                    errors.append(f"{fname}: 缺少关键案件信息")

        except Exception as e:
            errors.append(f"{fname}: 无法打开 ({e})")

    return errors


def _build_replacements(params: dict) -> dict:
    """构建 {{PLACEHOLDER}} → 实际值映射"""
    p = params
    r = {}
    is_criminal = p.get("case_type", "civil") == "criminal"

    if is_criminal:
        # ─── 刑事案件参数 ───
        r["{{CLIENT}}"] = p.get("client") or p.get("plaintiff", "______")
        r["{{DEFENDANT}}"] = p.get("defendant") or p.get("plaintiff", "______")
        crime = p.get("crime", "______")
        if not crime.endswith("罪") and crime != "______":
            crime = crime + "罪"
        r["{{CRIME}}"] = crime
        # 阶段 → 圆圈数字 (用于合同中"在 ②③④ 阶段"勾选)
        stage_circle = {"侦查": "①", "审查起诉": "②", "一审": "③", "二审": "④",
                         "申诉": "申诉", "再审": "⑤"}
        stages = [s.strip() for s in re.split(r"[、，,；;/]+", p["stage"].replace("阶段", "")) if s.strip()]
        r["{{STAGE}}"] = "".join(stage_circle.get(s, s) for s in stages)
        # 委托期限（末段 + 终结）：用于授权委托书"直至 X 终结"
        last_stage = stages[-1] if stages else "______"
        stage_to_desc = {"侦查": "侦查阶段", "审查起诉": "审查起诉阶段",
                          "一审": "一审", "二审": "二审", "申诉": "申诉", "再审": "再审"}
        r["{{STAGE_DESC}}"] = stage_to_desc.get(last_stage, last_stage) + "终结"
        r["{{YEAR}}"] = str(datetime.now().year)
        r["{{DETENTION}}"] = p.get("detention", "______看守所")

        fi = p.get("fee_info", {})
        r["{{UPFRONT_FEE}}"] = fi.get("upfront", "______元整")
        r["{{UPFRONT_FEE_SHORT}}"] = fi.get("upfront_short", "______").replace("¥", "").replace("￥", "")
        r["{{RISK_RATE}}"] = fi.get("risk_rate", "百分之___（___%）")

        # CASE_LABEL: 当事人涉嫌X罪一案
        r["{{CASE_LABEL}}"] = f"{r['{{DEFENDANT}}']}涉嫌{crime}一案"

        # 同时输出民事占位符（部分刑事模板可能复用字段名）
        r["{{PLAINTIFF}}"] = r["{{CLIENT}}"]
        r["{{CAUSE}}"] = crime
        return r

    # ─── 民事案件参数 ───
    r["{{PLAINTIFF}}"] = p["plaintiff"]
    r["{{DEFENDANT}}"] = p["defendant"]
    cause_val = p["cause"].rstrip()
    if cause_val.endswith("纠纷"):
        cause_val = cause_val[:-2]
    r["{{CAUSE}}"] = cause_val
    r["{{STAGE}}"] = p["stage"]
    r["{{YEAR}}"] = str(datetime.now().year)
    court = p.get("court", "")
    if not court or court == "______人民法院":
        r["{{COURT}}"] = "______人民法院"
    else:
        r["{{COURT}}"] = court
    r["{{LEGAL_REP}}"] = p.get("legal_rep", "______")
    r["{{LEGAL_REP_POSITION}}"] = p.get("legal_rep_position", "______")

    fi = p.get("fee_info", {})
    r["{{UPFRONT_FEE}}"] = fi.get("upfront", "______元整")
    r["{{UPFRONT_FEE_SHORT}}"] = fi.get("upfront_short", "¥______").replace("¥", "").replace("￥", "")
    r["{{RISK_RATE}}"] = fi.get("risk_rate", "百分之___（___%）")

    defendant = p["defendant"]
    cause = p["cause"].rstrip()
    # DEFENDANT_CAUSE 用于模板中 "甲方因与___纠纷一案" 的空白位置
    # 模板已自带 "纠纷一案" 后缀，故此处去掉 cause 末尾的 "纠纷" 避免重复
    if cause.endswith("纠纷"):
        case_desc = f"{defendant} {cause[:-2]}"
    else:
        case_desc = f"{defendant} {cause}"
    r["{{DEFENDANT_CAUSE}}"] = case_desc
    r["{{CASE_FULL}}"] = f"{p['plaintiff']}与{case_desc}纠纷"
    r["{{CASE_LABEL}}"] = case_label(p["plaintiff"], defendant, p["cause"])

    first_stage = re.split(r"[、，,；;/]+", p["stage"])[0].strip().removesuffix("阶段") + "阶段"
    r["{{FIRST_STAGE}}"] = first_stage

    return r


# ============================================================
# CLI
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="诉讼委托材料生成器")
    parser.add_argument('--case-folder', '-c', action='store_true')
    parser.add_argument('--case-type', choices=['auto', 'civil', 'criminal'], default='auto')
    parser.add_argument('--party-type', choices=['individual', 'company'])
    parser.add_argument('values', nargs='*', help='委托人 对方/当事人 案由/罪名 律师费 阶段 [法院/监管场所] [法定代表人] [职务]')
    opts = parser.parse_args()
    args = [v.strip() for v in opts.values]
    create_case = opts.case_folder
    if args and not 5 <= len(args) <= 8:
        parser.error('需要 5 至 8 个位置参数')
    if not args and not sys.stdin.isatty():
        parser.error('非交互运行需要提供五个核心参数')

    print("=" * 60)
    print(f"  诉讼委托材料生成器 v3.2.0 — {LAW_FIRM}")
    print(f"  民商事 + 刑事辩护 | 原始 DOCX 模板 | 保留模板格式")
    print("=" * 60)
    print()

    if len(args) >= 5:
        # 命令行：先从第一个参数推断案件类型
        first_arg = args[0] if args else ""
        all_input = " ".join([args[2], args[4]])
        case_type = detect_case_type(all_input) if opts.case_type == "auto" else opts.case_type

        if case_type == "criminal":
            if len(args) > 6:
                parser.error("刑事模式只接受 5 至 6 个位置参数")
            # 刑事: 委托人 当事人 罪名 律师费 阶段 [看守所]
            if len(args) >= 5:
                client = args[0]; defendant = args[1]; crime = args[2].removeprefix("涉嫌").strip()
                fee_desc = args[3]; stage = args[4]
                detention = args[5] if len(args) >= 6 else "______看守所"
            # 当事人为空时，委托人和当事人是同一人（嫌疑人本人委托）
            if not defendant:
                defendant = client
        else:
            plaintiff = args[0]; defendant = args[1]; cause = args[2]
            fee_desc = args[3]; stage = args[4]
            court = args[5] if len(args) >= 6 else "______人民法院"
            legal_rep = args[6] if len(args) >= 7 else "______"
            legal_rep_position = args[7] if len(args) >= 8 else "______"
    else:
        # 交互式：先询问案件类型
        print("案件类型：")
        print("  1) 民事 / 商事 / 仲裁")
        print("  2) 刑事辩护")
        ct_choice = input("选择（1 或 2，回车默认民事）：").strip()
        case_type = "criminal" if ct_choice == "2" else "civil"
        print()

        if case_type == "criminal":
            client = input("委托人名称（签字方，可与当事人相同）：").strip()
            defendant = input("当事人姓名（犯罪嫌疑人/被告人，回车=与委托人相同）：").strip()
            if not defendant:
                defendant = client
            crime = input("涉嫌罪名（如 '集资诈骗'，自动补'罪'）：").strip()
            fee_desc = input("律师费（如 '5万元' 或 '40000元'）：").strip()
            print("代理阶段（可多选，如 '侦查、审查起诉'，回车=全阶段）：")
            stage_input = input("  → ").strip()
            if not stage_input:
                stage = "、".join(CRIMINAL_STAGES[:4])
            else:
                stage = stage_input
            detention = input("监管场所（如 '佛山市南海区看守所'，回车跳过）：").strip() or "______看守所"
        else:
            plaintiff = input("甲方名称：").strip()
            defendant = input("对方名称：").strip()
            cause = input("案由（如 '股权转让'）：").strip()
            fee_desc = input("律师费（如 '5万元' 或 '前期2万+2%风险'）：").strip()
            stage = input("代理阶段（如 '一审、二审、执行'）：").strip()
            court = input("管辖法院（回车跳过）：").strip() or "______人民法院"
            legal_rep = input("法定代表人（公司需填，回车跳过）：").strip() or "______"
            legal_rep_position = input("法定代表人职务（回车跳过）：").strip() or "______"

    if case_type == "criminal":
        # 刑事案件：固定 个人主体 + 固定收费（不区分个人/公司、固定/半风险）
        party_type = "individual"
        fee_type = "fixed"
    else:
        name_for_detect = plaintiff
        party_type = opts.party_type or detect_party_type(name_for_detect)
        fee_type = detect_fee_type(fee_desc)
    fee_info = parse_fee(fee_desc, fee_type)

    print()
    print("-" * 40)
    print(f"  案件类型：{'刑事辩护' if case_type == 'criminal' else '民商事诉讼'}")
    if case_type == "civil":
        print(f"  主体：{'公司' if party_type == 'company' else '个人'}")
        print(f"  收费：{'半风险' if fee_type == 'semi_risk' else '固定'}")
    if fee_type == "semi_risk":
        print(f"  前期：{fee_info['upfront']}    风险：{fee_info['risk_rate']}")
    else:
        print(f"  总额：{fee_info['upfront']}")
    if case_type == "criminal":
        print(f"  委托人：{client}")
        print(f"  当事人：{defendant}")
        print(f"  涉嫌：{crime}")
        print(f"  监管场所：{detention}")
    print("-" * 40)
    print()

    params = {
        "case_type": case_type,
        "fee_desc": fee_desc, "fee_type": fee_type, "fee_info": fee_info,
        "stage": stage, "party_type": party_type,
        "output_base": os.getcwd(),
    }
    if case_type == "criminal":
        params.update({
            "client": client, "plaintiff": client,  # 用 plaintiff 字段兼容旧代码
            "defendant": defendant, "crime": crime,
            "detention": detention,
        })
    else:
        params.update({
            "plaintiff": plaintiff, "defendant": defendant, "cause": cause,
            "court": court, "legal_rep": legal_rep,
            "legal_rep_position": legal_rep_position,
        })

    result = generate_documents(params, create_case=create_case)
    output_dir = result["output_dir"]

    print(f"输出目录：{output_dir}\n")
    for name in sorted(result["files"]):
        print(f"  ✓  {name}")

    n = len(result["files"])
    print(f"\n共 {n} 份 .docx 文件。")
    print("已保留模板格式结构；请在 Word 中复核分页及签署信息。")
    print(f"请用 Word 打开填写日期和合同编号。")
    if create_case and result.get("case_dir"):
        print(f"\n案件文件夹：{result['case_dir']}")
    print()

    return result


if __name__ == "__main__":
    try:
        result = main()
    except (ValueError, OSError, zipfile.BadZipFile, etree.XMLSyntaxError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        sys.exit(1)
    if isinstance(result, dict):
        print("---RESULT_JSON---")
        print(json.dumps(result, ensure_ascii=False, indent=2))
