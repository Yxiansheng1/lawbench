# -*- coding: utf-8 -*-
"""
边界与异常输入测试

覆盖空文件、超大文件、错误格式、损坏文件、伪装扩展名等情况，
确认装载层给出明确的中文原因而不是崩溃或静默失败。
"""
import io
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER_DIR = os.path.dirname(HERE)
sys.path.insert(0, DRIVER_DIR)

import docloader  # noqa: E402

LOG = os.path.join(HERE, "_edge_result.txt")


def tiny_png():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (60, 30), "white").save(buf, "PNG")
    return buf.getvalue()


def fake_xlsx():
    """含 xl/ 的最小 zip，冒充 Excel"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", "<workbook/>")
        z.writestr("[Content_Types].xml", "<Types/>")
    return buf.getvalue()


def broken_docx():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("hello.txt", "not a word file")
    return buf.getvalue()


def fake_pdf():
    return b"%PDF-1.4\n" + b"\x00" * 400


def fake_doc():
    return b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 512


CASES = [
    ("空文件", b"", "empty.png", "error", "空"),
    ("随机二进制且无扩展名", b"\x00\x01\x02\x03\x04\x05", "noext", "error", "无法判断"),
    ("纯文本文件", "这是一段文字".encode("utf-8"), "note.txt", "error", "不是证件材料"),
    ("Excel 冒充 docx", fake_xlsx(), "book.docx", "error", "不是证件材料"),
    ("伪装成 Word 的非 Word zip", broken_docx(), "broken.docx", "error", ""),
    ("损坏的 PDF", fake_pdf(), "broken.pdf", "error", ""),
    ("老版 doc", fake_doc(), "old.doc", "error", "另存为"),
    ("超过 50 MB", b"x" * (51 * 1024 * 1024), "big.png", "error", "50 MB"),
    ("1x1 极小图片", tiny_png(), "tiny.png", "ok", ""),
    ("扩展名与内容不符（图配 pdf 名）", tiny_png(), "wrong.pdf", "ok", ""),
]


def main():
    lines, passed, failed = [], 0, 0
    lines.append("边界与异常输入测试")
    lines.append("=" * 60)

    for name, data, filename, expect, kw in CASES:
        sniffed = docloader.sniff(data)
        try:
            r = docloader.load_smart(data, filename)
            got, detail = "ok", "format=%s text=%d images=%d" % (r.format, len(r.text), len(r.images))
        except docloader.UnsupportedFormat as e:
            got, detail = "error", "UnsupportedFormat: " + str(e)
        except Exception as e:
            # 非预期异常类型也算 error，但要标出来，便于判断是否缺少兜底
            got, detail = "error", "[" + type(e).__name__ + "] " + str(e)[:160]

        hit_kw = (kw in detail) if kw else True
        ok = (got == expect) and hit_kw
        if ok:
            passed += 1
        else:
            failed += 1

        lines.append("")
        lines.append("%s  %s" % ("通过" if ok else "未通过", name))
        lines.append("  文件=%s  sniff=%s  期望=%s  实际=%s" % (filename, sniffed, expect, got))
        lines.append("  说明=" + detail)

    lines.append("")
    lines.append("=" * 60)
    lines.append("合计 %d 项：通过 %d，未通过 %d" % (len(CASES), passed, failed))

    with open(LOG, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
