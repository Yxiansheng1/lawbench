from docx import Document
for label, p in [
    ("个人委托", r"D:\workbuddy测试\retainer-offline\original-skill\templates\个人委托\1 民事委托代理合同.docx"),
    ("公司委托", r"D:\workbuddy测试\retainer-offline\original-skill\templates\公司委托\1 民事委托代理合同.docx"),
]:
    d = Document(p)
    print("=" * 20, label, "共", len(d.paragraphs), "段", "=" * 20)
    for i, para in enumerate(d.paragraphs):
        t = para.text.strip()
        if not t: continue
        # 条款标题行完整显示，其余截断
        import re
        if re.match(r"^[一二三四五六七八九十]+、", t):
            print("[%02d] %s" % (i, t[:150]))
        else:
            print("[%02d]   %s" % (i, t[:90]))
    print()