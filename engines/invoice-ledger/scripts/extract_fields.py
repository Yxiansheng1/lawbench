# -*- coding: utf-8 -*-
"""
发票字段提取器（模块）
提供: PDF 文本提取 / 图片 OCR / 文件名解析 / Excel 行解析
统一返回 dict: {类别序号, 发票类别, 开票日期, 价税合计（元）, 发票号码后五位, 文件名, 发票号码全号}
"""

import re
import sys
from pathlib import Path

# ── Windows 控制台 UTF-8 ──
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ════════════════════════════════════════════════════════════
#  正则（全半角覆盖）
# ════════════════════════════════════════════════════════════

RE_INVOICE_NUM_LABEL = re.compile(r"发票号码[：:]\s*(\d{8,20})(?!\d)")
RE_INVOICE_NUM_FALLBACK = re.compile(r"(?<!\d)(\d{20})(?!\d)")
# 老式票的发票代码（10~12 位）；与发票号码拼接才是 20 位全号
RE_INVOICE_CODE = re.compile(r"发票代码[：:]\s*(\d{10,12})")

RE_DATE_CN = re.compile(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
RE_DATE_ISO = re.compile(r"(20\d{2})-(\d{1,2})-(\d{1,2})")

RE_AMOUNT = re.compile(r"[\xa5￥¥]\s*([\d,]+\.\d{2})")

# 文件名格式（兼容 _N 重复后缀、大写扩展名）
# 格式1: 1-1-2026-01-15_业务费_1234.56_12345.pdf
RE_FN_FMT1 = re.compile(
    r"^(\d+-\d+)-(\d{4}-\d{2}-\d{2})_(.+?)_([\d.]+)_(\d{4,5})(?:_\d+)?\.pdf$", re.I
)
# 格式2（renamer 输出）: 1-1-差旅费 12.34 0001.pdf
RE_FN_FMT2 = re.compile(
    r"^(\d+-\d+)-(.+?)\s+([\d.]+)\s+(\d{4,5})(?:_\d+)?\.pdf$", re.I
)
# 格式3（旧）: 差旅费234.56-0001.pdf
RE_FN_FMT3 = re.compile(r"^(.+?)([\d.]+)-(\d{4,5})\.pdf$", re.I)


def _empty_result(filename: str) -> dict:
    return {
        "类别序号": "",
        "发票类别": "",
        "开票日期": "",
        "价税合计（元）": "",
        "发票号码后五位": "",
        "文件名": Path(filename).name,
        "发票号码全号": "",
    }


def _normalize_date(year: str, month: str, day: str) -> str:
    try:
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    except Exception:
        return ""


def _normalize_amount_str(s: str) -> str:
    """金额文本 → '12.34' 字符串，空值返回 ''"""
    if not s:
        return ""
    s = str(s).replace(",", "").replace("¥", "").replace("￥", "").strip()
    try:
        return f"{float(s):.2f}"
    except Exception:
        return ""


# ════════════════════════════════════════════════════════════
#  文本字段提取（PDF 文本与 OCR 文本共用）
# ════════════════════════════════════════════════════════════

def parse_text_fields(text: str, filename: str) -> dict:
    """从发票文本中提取字段（号码/日期/金额/类别）"""
    r = _empty_result(filename)
    if not text:
        return r

    # 发票号码 → 20 位全号。两种排版都要覆盖：
    #   ① 数电票（单段）：发票号码：26000000000000000001            → 直接取 20 位
    #   ② 老式票（两段）：发票代码：144032609110 ＋ 发票号码：11611829 → **须拼接**为 20 位
    # 只取标签值会漏掉 ②，得到 8 位"全号"，进而与台账 20 位全号对不上
    # （实测：某一历史批次中有 1 张属 ②，会被误判为冲突）
    m = RE_INVOICE_NUM_LABEL.search(text)
    if not m:
        m = RE_INVOICE_NUM_FALLBACK.search(text)
    if m:
        num = m.group(1)
        if len(num) < 20:
            mc = RE_INVOICE_CODE.search(text)
            if mc and len(num) == 8 and len(mc.group(1)) in (10, 12):
                num = mc.group(1) + num
            else:
                r['_identity_error'] = '非20位号码缺少有效的发票代码与8位号码配对'
        r["发票号码全号"] = num
        r["发票号码后五位"] = num[-5:]

    from buyer_verification import annotate
    annotate(text, r)

    # 开票日期（中文日期优先）
    m = RE_DATE_CN.search(text)
    if not m:
        m = RE_DATE_ISO.search(text)
    if m:
        r["开票日期"] = _normalize_date(m.group(1), m.group(2), m.group(3))

    from invoice_integrity import total_amount
    r["价税合计（元）"], problem = total_amount(text)
    if problem: r["_amount_error"] = problem

    return r


# ════════════════════════════════════════════════════════════
#  文件名解析
# ════════════════════════════════════════════════════════════

def parse_filename(filename: str) -> dict:
    """从文件名提取字段（8月/9月/旧格式兼容）"""
    name = Path(filename).name
    r = _empty_result(name)

    # 格式1: 含日期（统计表模板同款）
    m = RE_FN_FMT1.match(name)
    if m:
        r["类别序号"] = m.group(1)
        r["开票日期"] = m.group(2)
        r["发票类别"] = m.group(3)
        r["价税合计（元）"] = _normalize_amount_str(m.group(4))
        r["发票号码后五位"] = m.group(5)
        return r

    # 格式2: renamer 格式（9月）
    m = RE_FN_FMT2.match(name)
    if m:
        r["类别序号"] = m.group(1)
        r["发票类别"] = m.group(2).strip()
        r["价税合计（元）"] = _normalize_amount_str(m.group(3))
        r["发票号码后五位"] = m.group(4)
        return r

    # 格式3: 旧格式（2/4/5月）
    m = RE_FN_FMT3.match(name)
    if m:
        r["发票类别"] = m.group(1).strip()
        r["价税合计（元）"] = _normalize_amount_str(m.group(2))
        r["发票号码后五位"] = m.group(3)
        return r

    return r


# ════════════════════════════════════════════════════════════
#  依赖缺失（环境问题，必须与内容问题分流 —— 见 references/06-invariants.md I3）
# ════════════════════════════════════════════════════════════

class DependencyMissing(RuntimeError):
    """必需依赖缺失。属环境问题，**不得**降级为"字段提取失败"。"""

    def __init__(self, name: str, cause=None):
        self.name = name
        self.cause = cause
        super().__init__(f"缺少必需依赖：{name}")


# ════════════════════════════════════════════════════════════
#  PDF 提取
# ════════════════════════════════════════════════════════════

def extract_from_pdf(path: str) -> dict:
    """pdfplumber 提取 PDF 字段。

    分流（I3）：
      - pdfplumber 缺失 → raise DependencyMissing（环境问题，调用方须中止）
      - PDF 打开/解析失败 → 返回带 _extract_error 的空结果（内容问题）
    """
    p = Path(path)
    r = _empty_result(p.name)
    try:
        import pdfplumber
    except ImportError as e:
        raise DependencyMissing("pdfplumber", e) from e

    try:
        with pdfplumber.open(str(p)) as pdf:
            text = ""
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    text += t + "\n"
    except Exception as e:
        r["_extract_error"] = f"{type(e).__name__}"
        return r

    scanned = not text.strip()
    if scanned:
        import tempfile
        import pypdfium2 as pdfium
        with tempfile.TemporaryDirectory(prefix="invoice-ocr-") as td:
            document=pdfium.PdfDocument(str(p))
            try:
                for i in range(len(document)):
                    page=document[i]; bitmap=page.render(scale=2)
                    try:
                        target=Path(td)/(str(i)+".png"); bitmap.to_pil().save(target)
                        part=extract_from_image(str(target))
                        if part.get("_ocr_error") or part.get("_ocr_language_missing") or part.get("_ocr_empty"):
                            return {**r, "_extract_error":"扫描PDF OCR未完成", "_ocr":True}
                        text+=part.get("_recognized_text", "")+"\n"
                    finally: bitmap.close();page.close()
            finally:document.close()
    r = parse_text_fields(text, p.name)
    if scanned:
        r["_ocr"]=True
        r["_recognized_text"]=text
    from invoice_renamer import extract_invoice_fields, classify_invoice
    r["发票类别"] = classify_invoice(extract_invoice_fields(text))

    # 兜底：文本提取不到时用文件名补齐
    fn = parse_filename(p.name)
    for key in ("类别序号",):
        if not r.get(key) and fn.get(key):
            r[key] = fn[key]
    return r


# ════════════════════════════════════════════════════════════
#  图片 OCR（内置 winsdk 绑定，调用 Windows OCR）
# ════════════════════════════════════════════════════════════

def normalize_ocr_text(text: str) -> str:
    """只整理 OCR 空格和金额小数点，不把 O/I 等字母猜成数字。"""
    lines = []
    for line in text.splitlines():
        line = re.sub(r'([¥￥]\s*[+-]?\d+)\s*，\s*(\d{2})(?!\d)', r'\1.\2', line)
        line = re.sub(r"(?<=[\u4e00-\u9fff])[ \t]+(?=[\u4e00-\u9fff])", "", line)
        line = re.sub(r"(?<!\d)(2\s*0\s*\d\s*\d)\s*年\s*(\d(?:\s*\d)?)\s*月\s*(\d(?:\s*\d)?)\s*日",
                      lambda m: re.sub(r"\s+", "", m.group()), line)
        line = re.sub(r"([¥￥])[ \t]*([\d,][\d, \t]*)[.·．][ \t]*(\d[ \t]*\d)(?!\d)",
                      lambda m: m[1] + re.sub(r"[ \t]", "", m[2]) + "." + re.sub(r"[ \t]", "", m[3]), line)
        line = re.sub(r"(发票号码\s*[：:]\s*)((?:\d[ \t]*){8,20})(?!\d)",
                      lambda m: m[1] + re.sub(r"[ \t]", "", m[2]), line)
        lines.append(line)
    return "\n".join(lines)


def ocr_capabilities() -> dict:
    """检查内置绑定和目标 Windows 的中文 OCR 语言功能，不识别或改写文件。"""
    try:
        from winsdk.windows.media.ocr import OcrEngine
        from winsdk.windows.globalization import Language
    except ImportError as e:
        raise DependencyMissing("winsdk", e) from e
    languages = [lang.language_tag for lang in OcrEngine.available_recognizer_languages]
    return {"languages": languages,
            "chinese_available": OcrEngine.is_language_supported(Language("zh-Hans-CN"))}


def extract_from_image(path: str) -> dict:
    """内置 winsdk OCR。缺依赖为致命环境错误；缺语言、运行失败和空白分别标记。"""
    p = Path(path)
    r = _empty_result(p.name)
    try:
        import asyncio
        from winsdk.windows.media.ocr import OcrEngine
        from winsdk.windows.graphics.imaging import BitmapDecoder, BitmapPixelFormat, BitmapAlphaMode
        from winsdk.windows.storage import StorageFile, FileAccessMode
        from winsdk.windows.globalization import Language
    except ImportError as e:
        raise DependencyMissing("winsdk", e) from e

    async def _ocr_one(path_str):
        engine = OcrEngine.try_create_from_language(Language("zh-Hans-CN"))
        if engine is None:
            return None
        file = await StorageFile.get_file_from_path_async(path_str)
        stream = await file.open_async(FileAccessMode.READ)
        bitmap = None
        try:
            decoder = await BitmapDecoder.create_async(stream)
            if max(decoder.pixel_width, decoder.pixel_height) > OcrEngine.max_image_dimension:
                raise ValueError(f"图片超过 Windows OCR 尺寸上限 {OcrEngine.max_image_dimension} 像素")
            bitmap = await decoder.get_software_bitmap_async(BitmapPixelFormat.BGRA8, BitmapAlphaMode.PREMULTIPLIED)
            result = await engine.recognize_async(bitmap)
            # Keep line boundaries so one invoice field cannot absorb the next one.
            return "\n".join(line.text for line in result.lines)
        finally:
            if bitmap is not None:
                bitmap.close()
            stream.close()

    try:
        text = asyncio.run(_ocr_one(str(p.resolve())))
    except Exception as e:
        r["_ocr_error"] = f"{type(e).__name__}: {e}"
        return r
    if text is None:
        r["_ocr_language_missing"] = "目标 Windows 未启用简体中文 OCR 语言功能（zh-CN）；请在 Windows 语言设置中安装对应 OCR 功能"
        return r
    if not text.strip():
        r["_ocr_empty"] = True
        return r
    r = parse_text_fields(normalize_ocr_text(text), p.name)
    from invoice_renamer import extract_invoice_fields, classify_invoice
    r["发票类别"] = classify_invoice(extract_invoice_fields(normalize_ocr_text(text)))
    r["_recognized_text"] = normalize_ocr_text(text)
    r["_ocr"] = True
    return r


# ════════════════════════════════════════════════════════════
#  辅助判断
# ════════════════════════════════════════════════════════════


def is_skip_dir(dirname: str) -> bool:
    """内部目录跳过"""
    return dirname.startswith("_") or "已分类" in dirname or dirname in ("raw_decoded",)


def normalize_date(v) -> str:
    """Excel/字符串日期 → YYYY-MM-DD"""
    if v is None:
        return ""
    if isinstance(v, str):
        v = v.strip()
        m = RE_DATE_CN.search(v)
        if m:
            return _normalize_date(m.group(1), m.group(2), m.group(3))
        m = RE_DATE_ISO.search(v)
        if m:
            return _normalize_date(m.group(1), m.group(2), m.group(3))
        return v if re.match(r"^\d{4}-\d{2}-\d{2}$", v) else ""
    return str(v)


def normalize_amount(v) -> str:
    """任意金额类型 → '12.34'"""
    return _normalize_amount_str(str(v) if v is not None else "")


if __name__ == "__main__":
    # 自测
    import sys
    for f in sys.argv[1:]:
        p = Path(f)
        if p.suffix.lower() == ".pdf":
            print(p.name, "→", extract_from_pdf(str(p)))
        else:
            print(p.name, "→", parse_filename(p.name))
