import re, zipfile
p = r"D:\workbuddy测试\retainer-offline\original-skill\templates\刑事\1、刑事辩护委托合同.docx"
xml = zipfile.ZipFile(p).read("word/document.xml").decode("utf-8","ignore")
paras = re.findall(r"<w:p[ >].*?</w:p>", xml, re.S)
texts = []
for pa in paras:
    t = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", pa, re.S))
    if t.strip(): texts.append(t)
print("非空段落数:", len(texts))
print("--- 含 六、/收费/律师费/甲乙双方协商确定 的段落 ---")
hit = 0
for i,t in enumerate(texts):
    if any(k in t for k in ["六、","甲乙双方协商确定","律师费","收费","代理费"]):
        print("[%d] %s" % (i, t[:180])); hit += 1
print("命中段落:", hit)
print("--- 前 12 段预览 ---")
for i,t in enumerate(texts[:12]): print("  %d: %s" % (i, t[:80]))