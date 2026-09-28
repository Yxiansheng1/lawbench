# -*- coding: utf-8 -*-
"""探测脚本：验证校验位算法 + 生成虚构测试图（不含任何真实证件信息）"""
import os
from PIL import Image, ImageDraw, ImageFont

OUT = r"D:\workbuddy测试"
log = []


def uscc_check(code):
    """统一社会信用代码校验位 GB 32100-2015"""
    s = code.strip().upper()
    chars = "0123456789ABCDEFGHJKLMNPQRTUWXY"
    if len(s) != 18 or any(c not in chars for c in s[:17]):
        return None
    total = 0
    for i in range(17):
        total += chars.index(s[i]) * pow(3, i, 31)
    c = 31 - (total % 31)
    if c == 31:
        c = 0
    return chars[c]


def id_check(idn):
    """身份证校验位 GB 11643-1999 / ISO 7064 MOD 11-2"""
    s = idn.strip().upper()
    if len(s) != 18 or any(c not in "0123456789" for c in s[:17]):
        return None
    w = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    m = "10X98765432"
    return m[sum(int(s[i]) * w[i] for i in range(17)) % 11]


log.append("=== checksum algorithms ===")
log.append("USCC official sample 91350100M000100Y43 -> computed tail = " + str(uscc_check("91350100M000100Y43")) + " (expect 3)")
log.append("ID   official sample 11010519491231002X -> computed tail = " + str(id_check("11010519491231002X")) + " (expect X)")

# 构造一个校验位合法的虚构统一社会信用代码
body = "91440300MA5EXAMPL"
full = body + str(uscc_check(body + "0")) if False else None
# 逐位试出合法校验位
for cand in "0123456789ABCDEFGHJKLMNPQRTUWXY":
    test = body + cand
    if uscc_check(test) == cand:
        full = test
        break
log.append("constructed fictional USCC = " + str(full))
if full:
    log.append("verify constructed USCC -> " + str(uscc_check(full)))

font_path = None
for p in [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\simsun.ttc"]:
    if os.path.exists(p):
        font_path = p
        break
log.append("font = " + str(font_path))


def make(path, title, lines, width=1000):
    font_t = ImageFont.truetype(font_path, 34)
    font_b = ImageFont.truetype(font_path, 26)
    h = 60 + 50 * len(lines) + 40
    img = Image.new("RGB", (width, h), "white")
    d = ImageDraw.Draw(img)
    d.text((40, 24), title, fill="black", font=font_t)
    y = 86
    for t in lines:
        d.text((50, y), t, fill="black", font=font_b)
        y += 50
    img.save(path)
    log.append("saved " + path + " size=" + str(os.path.getsize(path)))
    return path


lic = make(os.path.join(OUT, "_tmp_ocr_license.png"), "营业执照", [
    "名　　称　深圳市示例科技有限公司",
    "统一社会信用代码　" + (full or ""),
    "类　　型　有限责任公司",
    "法定代表人　张三",
    "住　　所　广东省深圳市福田区示例路1号",
    "成立日期　2020年09月01日",
])

idc = make(os.path.join(OUT, "_tmp_ocr_idcard.png"), "居民身份证", [
    "姓名　李四　性别　男　民族　汉",
    "出生　1985年3月12日",
    "住址　广东省深圳市南山区示例路2号",
    "公民身份号码　11010519491231002X",
])

with open(r"D:\workbuddy测试\_ocr_probe6.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(log))
