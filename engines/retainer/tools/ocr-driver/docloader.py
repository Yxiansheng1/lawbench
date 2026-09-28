# -*- coding: utf-8 -*-
"""
统一文档装载层

核心判断：PDF 与 Word 中的文字多数**不需要 OCR**。
  · PDF 有文本层 → 直接提取，零误差、零耗时
  · PDF 无文本层（扫描件）→ 逐页渲染成图，才交给 OCR
  · docx 文字在 XML 里 → 直接提取；只有内嵌图片才需要 OCR
  · doc（老二进制格式）→ 本机无可用解析器，需先另存为 docx

本模块把任意受支持的输入统一拆成三部分：文本、待识别图像、提示。
驱动层只对「待识别图像」调用 OCR。
"""
import io
import os
import zipfile

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".gif"}
DOC_EXTS = {".pdf", ".docx", ".doc"}
SUPPORTED = IMAGE_EXTS | DOC_EXTS

# 扫描页渲染分辨率：太低伤小字，太高拖慢识别
RENDER_DPI = 200


class UnsupportedFormat(Exception):
    pass


class LoadResult:
    def __init__(self, fmt):
        self.format = fmt
        self.text = ""            # 文本层直接取到的文字（无需 OCR）
        self.images = []          # [(label, png_bytes)] 需要 OCR 的图像
        self.pages = []           # 逐页/逐项明细
        self.notes = []           # 面向用户的提示
        self.image_only = False   # 是否纯图片输入

    def to_dict(self):
        return {
            "format": self.format,
            "textChars": len(self.text),
            "imageCount": len(self.images),
            "notes": self.notes,
            "pages": self.pages,
        }


def _pil_to_png_bytes(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _load_image(data, fmt):
    from PIL import Image
    r = LoadResult(fmt)
    r.image_only = True
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as e:
        raise UnsupportedFormat("图片无法解码：" + str(e)[:120])
    r.images.append(("image", _pil_to_png_bytes(img.convert("RGB"))))
    r.pages.append({"index": 1, "kind": "image", "size": list(img.size), "textChars": 0})
    if img.mode in ("RGBA", "LA", "P") or "transparency" in img.info:
        r.notes.append("图片含透明通道，已合成为白底后识别")
    return r


def _load_pdf(data, fmt):
    import fitz
    r = LoadResult(fmt)
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as e:
        raise UnsupportedFormat("PDF 无法打开，文件可能已损坏或被截断（" + str(e)[:80] + "）")
    try:
        if doc.is_encrypted and not doc.authenticate(""):
            raise UnsupportedFormat("PDF 已加密，需要口令，无法读取")
        n = doc.page_count
        text_parts, scanned_pages = [], []
        for i, page in enumerate(doc):
            t = (page.get_text("text") or "").strip()
            if t:
                text_parts.append(t)
                r.pages.append({"index": i + 1, "kind": "text", "textChars": len(t)})
            else:
                scanned_pages.append(i)
        r.text = "\n".join(text_parts)
        for i in scanned_pages:
            page = doc[i]
            pix = page.get_pixmap(dpi=RENDER_DPI, alpha=False)
            r.images.append(("page-%d" % (i + 1), pix.tobytes("png")))
            r.pages.append({"index": i + 1, "kind": "scan", "dpi": RENDER_DPI, "textChars": 0})
        if scanned_pages and text_parts:
            r.notes.append("该 PDF 为混合型：%d 页有文本层直接提取，%d 页为扫描页需识别"
                           % (len(text_parts), len(scanned_pages)))
        elif scanned_pages:
            r.notes.append("该 PDF 无文本层（扫描件），全部 %d 页需识别" % len(scanned_pages))
        else:
            r.notes.append("该 PDF 有文本层，已直接提取，未使用 OCR（%d 页）" % n)
    except UnsupportedFormat:
        raise
    except Exception as e:
        raise UnsupportedFormat("PDF 读取失败，文件可能已损坏（" + str(e)[:80] + "）")
    finally:
        try:
            doc.close()
        except Exception:
            pass
    return r


def _extract_docx_text(data):
    """优先用 python-docx 取正文与表格文字；失败则退回 XML 解析"""
    try:
        from docx import Document
        doc = Document(io.BytesIO(data))
        parts = [p.text for p in doc.paragraphs if p.text and p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text and c.text.strip()]
                if cells:
                    parts.append(" | ".join(cells))
        return "\n".join(parts)
    except Exception:
        import re
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                xml = z.read("word/document.xml").decode("utf-8", "ignore")
        except Exception as e2:
            raise UnsupportedFormat("这不是有效的 Word 文档，文件可能已损坏或实为其他格式（"
                                    + str(e2)[:80] + "）")
        xml = re.sub(r"</w:p>", "\n", xml)
        return re.sub(r"<[^>]+>", "", xml).strip()


def _extract_docx_images(data):
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        media = sorted(n for n in z.namelist() if n.startswith("word/media/"))
        for name in media:
            raw = z.read(name)
            ext = os.path.splitext(name)[1].lower()
            if ext in IMAGE_EXTS:
                try:
                    from PIL import Image
                    img = Image.open(io.BytesIO(raw))
                    img.load()
                    out.append((name.split("/")[-1], _pil_to_png_bytes(img.convert("RGB"))))
                except Exception:
                    continue
            elif ext in (".emf", ".wmf"):
                out.append(("SKIP:" + name.split("/")[-1], None))
    return out


def _load_docx(data, fmt):
    r = LoadResult(fmt)
    r.text = _extract_docx_text(data)
    r.pages.append({"index": 1, "kind": "text", "textChars": len(r.text)})
    imgs = _extract_docx_images(data)
    skipped = [n[5:] for n in imgs if n[1] is None]
    for name, png in imgs:
        if png:
            r.images.append((name, png))
    if r.text:
        r.notes.append("已直接提取 Word 文本 %d 字，文字部分未使用 OCR" % len(r.text))
    if r.images:
        r.notes.append("另有 %d 张内嵌图片需要识别" % len(r.images))
    if skipped:
        r.notes.append("以下矢量图（EMF/WMF）暂不支持识别：" + "、".join(skipped[:5]))
    if not r.text and not r.images:
        r.notes.append("文档中没有可提取的文字或图片")
    return r


def _load_doc(data, fmt):
    r = LoadResult(fmt)
    r.notes.append(
        "老版 .doc 为二进制格式，本机没有可用的解析器"
        "（未安装 LibreOffice、Word，且缺少 pywin32/olefile）。"
        "请在 WPS 或 Word 中「另存为 .docx」后重试，或直接提供 PDF。"
    )
    raise UnsupportedFormat(r.notes[-1])


def load(data, filename):
    """把任意受支持输入拆成 文本 / 待识别图像 / 提示"""
    if not data:
        raise UnsupportedFormat("文件内容为空")
    if len(data) > 50 * 1024 * 1024:
        raise UnsupportedFormat("文件超过 50 MB")
    ext = os.path.splitext(filename or "")[1].lower()
    if ext in IMAGE_EXTS:
        return _load_image(data, ext)
    if ext == ".pdf":
        return _load_pdf(data, ext)
    if ext == ".docx":
        return _load_docx(data, ext)
    if ext == ".doc":
        return _load_doc(data, ext)
    if ext in (".xlsx", ".xls", ".xlsm", ".csv", ".tsv", ".pptx", ".ppt", ".txt"):
        raise UnsupportedFormat("这是表格、演示或纯文本文件，不是证件材料。本工具支持图片、PDF 与 Word 文档。")
    if not ext:
        raise UnsupportedFormat("无法判断文件类型，请提供带扩展名的文件")
    raise UnsupportedFormat("不支持的格式：" + ext + "，可用：" + "、".join(sorted(SUPPORTED)))


def _sniff_ooxml(data):
    """ZIP 容器进一步区分 Word / Excel / PowerPoint，避免把表格当文档"""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
        if any(n.startswith("word/") for n in names):
            return ".docx"
        if any(n.startswith("xl/") for n in names):
            return ".xlsx"
        if any(n.startswith("ppt/") for n in names):
            return ".pptx"
    except Exception:
        pass
    return ".docx"


def sniff(data):
    """按文件头判断真实类型，避免扩展名不符"""
    if data[:4] == b"%PDF":
        return ".pdf"
    if data[:2] == b"PK":
        return _sniff_ooxml(data)
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return ".doc"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:2] in (b"BM",):
        return ".bmp"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return ".tiff"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def load_smart(data, filename):
    """先用文件头校正扩展名，再装载；扩展名缺失时以文件头为准"""
    real = sniff(data)
    ext = os.path.splitext(filename or "")[1].lower()
    use = real or ext
    if not use:
        raise UnsupportedFormat(
            "无法判断文件类型：扩展名缺失且文件头不是已知格式。"
            "请提供带扩展名的文件（" + "、".join(sorted(SUPPORTED)) + "）")
    result = load(data, "upload" + use)
    if real and ext and real != ext:
        result.notes.append("文件头显示实际为 %s，扩展名为 %s，已按内容处理" % (real, ext))
    elif real and not ext:
        result.notes.append("扩展名缺失，已按文件头识别为 %s" % real)
    return result
