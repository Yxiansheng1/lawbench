from docx import Document
d = Document(r"D:\workbuddy测试\retainer-offline\original-skill\templates\个人委托\1 民事委托代理合同.docx")
for i, p in enumerate(d.paragraphs):
    if "剩余未付的律师费" in p.text:
        print("[%d] %s" % (i, p.text))