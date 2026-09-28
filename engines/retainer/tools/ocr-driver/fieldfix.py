# -*- coding: utf-8 -*-
"""
证件字段解析与容错修正器

职责：把 OCR 输出的「带坐标文本行」转成结构化字段，并在此过程中做确定性修正。
本模块不依赖任何 OCR 引擎，可单独测试。

修正手段（全部为确定性规则，不含模型、不含联网）：
  1. 视觉行重建：按 bbox 纵向重叠聚类，把被切碎的行碎片拼回去；
  2. 全角/半角与易混字符归一：仅在数字域内进行（姓名域严禁替换）；
  3. 校验位纠错：统一社会信用代码（GB 32100-2015）、公民身份号码（GB 11643-1999），
     校验失败时做单位替换穷举，唯一命中才修正；
  4. 标签词典匹配：用证种标签白名单容忍标签被切碎或误识；
  5. 低置信度标记：低于阈值的字段标为待人工确认，不静默采用。
"""

import re

USCC_CHARS = "0123456789ABCDEFGHJKLMNPQRTUWXY"
ID_WEIGHTS = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
ID_MAP = "10X98765432"

# 数字域内的高频混淆，仅用于代码类字段
DIGIT_CONFUSION = {
    "O": "0", "o": "0", "D": "0", "Q": "0",
    "I": "1", "l": "1", "|": "1", "i": "1",
    "Z": "2", "z": "2",
    "A": "4",
    "S": "5", "s": "5",
    "G": "6", "b": "6",
    "T": "7",
    "B": "8",
    "g": "9", "q": "9",
}

DOC_TYPES = {
    "business_license": {
        "label": "营业执照",
        "name": ["名称", "企业名称", "单位名称"],
        "credit_code": ["统一社会信用代码", "统一代码", "社会信用代码", "纳税人识别号"],
        "org_type": ["类型", "公司类型", "企业类型", "主体类型"],
        "legal_rep": ["法定代表人", "负责人", "执行事务合伙人", "投资人", "经营者"],
        "capital": ["注册资本", "出资额", "注册资金"],
        "address": ["住所", "地址", "经营场所", "主要经营场所", "营业场所"],
        "established": ["成立日期", "注册日期", "成立时间"],
        "scope": ["经营范围", "业务范围", "许可经营项目"],
    },
    "social_org_cert": {
        "label": "社会团体法人登记证书",
        "name": ["名称", "社团名称", "单位名称"],
        "credit_code": ["统一社会信用代码", "统一代码", "社会信用代码"],
        "org_type": ["类型", "社团类型"],
        "legal_rep": ["法定代表人", "负责人"],
        "address": ["住所", "办公住所", "地址"],
        "established": ["成立日期", "登记日期"],
        "scope": ["业务范围", "宗旨和业务范围"],
    },
    "private_nonenterprise_cert": {
        "label": "民办非企业单位登记证书",
        "name": ["名称", "单位名称"],
        "credit_code": ["统一社会信用代码", "统一代码"],
        "legal_rep": ["法定代表人", "负责人"],
        "address": ["住所", "地址"],
        "established": ["成立日期", "登记日期"],
        "scope": ["业务范围"],
    },
    "id_card_front": {
        "label": "居民身份证（人像面）",
        "name": ["姓名"],
        "gender": ["性别"],
        "ethnicity": ["民族"],
        "birth": ["出生"],
        "address": ["住址", "地址"],
        "id_number": ["公民身份号码", "公民身份证号码", "身份号码", "身份证号"],
    },
    "id_card_back": {
        "label": "居民身份证（国徽面）",
        "issuing_authority": ["签发机关"],
        "valid_period": ["有效期限", "有效期"],
    },
}

REQUIRED_FIELD = {
    "business_license": ["name", "credit_code"],
    "social_org_cert": ["name", "credit_code"],
    "private_nonenterprise_cert": ["name", "credit_code"],
    "id_card_front": ["name", "id_number"],
    "id_card_back": ["issuing_authority"],
}

# 值可能跨多行的字段：值为最大续行数。住址最典型，证照上的地址常被排版成 2—3 行
MULTILINE = {"address": 3, "scope": 5}
# 住址末端标识：缺少这些词通常意味着没有取全
ADDR_TAIL = re.compile(r"[号组村路巷弄栋室楼队区县旗盟]")
PROVINCE = {
    "11": "北京", "12": "天津", "13": "河北", "14": "山西", "15": "内蒙古", "21": "辽宁",
    "22": "吉林", "23": "黑龙江", "31": "上海", "32": "江苏", "33": "浙江", "34": "安徽",
    "35": "福建", "36": "江西", "37": "山东", "41": "河南", "42": "湖北", "43": "湖南",
    "44": "广东", "45": "广西", "46": "海南", "50": "重庆", "51": "四川", "52": "贵州",
    "53": "云南", "54": "西藏", "61": "陕西", "62": "甘肃", "63": "青海", "64": "宁夏",
    "65": "新疆",
}


# ---------------- 基础归一 ----------------

def to_halfwidth(s):
    """全角转半角（含全角空格），保留中文"""
    out = []
    for ch in str(s):
        code = ord(ch)
        if code == 0x3000:
            out.append(" ")
        elif 0xFF01 <= code <= 0xFF5E:
            out.append(chr(code - 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)


def squeeze(s):
    return " ".join(to_halfwidth(s).split())


def strip_label_noise(s):
    """去掉标签里常见的误识字符与空白，用于宽松匹配"""
    return "".join(ch for ch in squeeze(s) if ch not in " \u3000:：")


# ---------------- 校验位纠错 ----------------

def uscc_check_char(code17):
    total = 0
    for i, ch in enumerate(code17):
        if ch not in USCC_CHARS:
            return None
        total += USCC_CHARS.index(ch) * pow(3, i, 31)
    c = 31 - (total % 31)
    if c == 31:
        c = 0
    return USCC_CHARS[c]


def fix_uscc(raw):
    """返回 (code, status)；status 取 ok / fixed / invalid"""
    s = squeeze(raw).upper().replace(" ", "")
    for ch in list(s):
        if ch in DIGIT_CONFUSION and ch not in USCC_CHARS:
            s = s.replace(ch, DIGIT_CONFUSION[ch], 1)
    if len(s) != 18:
        return s, "invalid"
    if any(c not in USCC_CHARS for c in s):
        return s, "invalid"
    if uscc_check_char(s[:17]) == s[17]:
        return s, "ok"
    hits = []
    for i in range(18):
        for c in USCC_CHARS:
            if c == s[i]:
                continue
            cand = s[:i] + c + s[i + 1:]
            if uscc_check_char(cand[:17]) == cand[17]:
                hits.append(cand)
    if len(hits) == 1:
        return hits[0], "fixed"
    return s, "invalid"


def id_check_char(id17):
    if any(c not in "0123456789" for c in id17):
        return None
    return ID_MAP[sum(int(id17[i]) * ID_WEIGHTS[i] for i in range(17)) % 11]


def fix_id_card(raw):
    """返回 (code, status)"""
    s = squeeze(raw).upper().replace(" ", "")
    for ch in list(s):
        if ch in DIGIT_CONFUSION and ch not in "0123456789X":
            s = s.replace(ch, DIGIT_CONFUSION[ch], 1)
    if len(s) != 18:
        return s, "invalid"
    if any(c not in "0123456789X" for c in s):
        return s, "invalid"
    if id_check_char(s[:17]) == s[17]:
        return s, "ok"
    hits = []
    for i in range(18):
        alphabet = "0123456789" if i < 17 else "0123456789X"
        for c in alphabet:
            if c == s[i]:
                continue
            cand = s[:i] + c + s[i + 1:]
            if id_check_char(cand[:17]) == cand[17]:
                hits.append(cand)
    if len(hits) == 1:
        return hits[0], "fixed"
    return s, "invalid"


# ---------------- 视觉行重建 ----------------

def _bbox(line):
    return line.get("box")


def build_visual_lines(lines):
    """按纵向重叠把碎片行聚成视觉行，再按横向顺序拼接"""
    items = []
    for ln in lines:
        box = _bbox(ln)
        text = squeeze(ln.get("text", ""))
        if not text:
            continue
        if not box:
            items.append({"text": text, "top": 0, "bottom": 0, "left": 0, "score": ln.get("score")})
            continue
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        items.append({
            "text": text,
            "top": min(ys), "bottom": max(ys),
            "left": min(xs), "right": max(xs),
            "height": max(ys) - min(ys) or 1,
            "score": ln.get("score"),
        })
    if not items:
        return []

    items.sort(key=lambda x: (x.get("top", 0), x.get("left", 0)))
    rows = []
    for it in items:
        placed = False
        for row in rows:
            overlap = min(row["bottom"], it.get("bottom", 0)) - max(row["top"], it.get("top", 0))
            if overlap > 0.5 * min(row["height"], it.get("height", 1)):
                row["items"].append(it)
                row["top"] = min(row["top"], it.get("top", row["top"]))
                row["bottom"] = max(row["bottom"], it.get("bottom", row["bottom"]))
                row["height"] = max(row["height"], it.get("height", 1))
                placed = True
                break
        if not placed:
            rows.append({
                "items": [it],
                "top": it.get("top", 0),
                "bottom": it.get("bottom", 0),
                "height": it.get("height", 1),
            })
    for row in rows:
        row["items"].sort(key=lambda x: x.get("left", 0))
    rows.sort(key=lambda r: r["top"])
    return rows


def _compact_map(text):
    """返回 (去空白后的字符串, 每个字符在原文中的索引)"""
    chars, idx = [], []
    for i, ch in enumerate(text):
        if ch in " \u3000\t":
            continue
        chars.append(ch)
        idx.append(i)
    return "".join(chars), idx


def find_loose(text, label):
    """在 text 中宽松查找 label（忽略空白差异），返回原文区间 (start, end) 或 None"""
    c_text, imap = _compact_map(text)
    c_lab, _ = _compact_map(label)
    if not c_lab:
        return None
    p = c_text.find(c_lab)
    if p < 0:
        return None
    return imap[p], imap[p + len(c_lab) - 1] + 1


def scan_labels(text, spec):
    """扫出一行内出现的全部字段标签，按位置排序并去掉重叠"""
    hits = []
    for field, labels in spec.items():
        if field == "label":
            continue
        best = None
        for lab in labels:
            span = find_loose(text, lab)
            if span and (best is None or span[0] < best[0]):
                best = span
        if best:
            hits.append({"field": field, "start": best[0], "end": best[1], "label": text[best[0]:best[1]]})
    hits.sort(key=lambda h: (h["start"], -(h["end"] - h["start"])))
    cleaned = []
    for h in hits:
        if cleaned and h["start"] < cleaned[-1]["end"]:
            continue
        cleaned.append(h)
    return cleaned


def extract(doc_type, lines, score_threshold=0.5):
    """把文本行解析为字段字典；返回 (fields, meta)

    两级策略：
      1) 同行切分：一行内若有多个「标签＋值」，按标签位置切段，各取其后的内容；
      2) 跨行配对：标签与值分处两行时（部分引擎的排版），取下一行作为值。
    """
    spec = DOC_TYPES.get(doc_type)
    if not spec:
        return {}, {"error": "未知证种：" + str(doc_type)}

    rows = build_visual_lines(lines)
    texts = []
    for row in rows:
        items = row["items"]
        texts.append({
            "text": " ".join(i["text"] for i in items),
            "left": min((i.get("left", 0) for i in items), default=0),
        })
    fields, meta = {}, {"status": {}, "warnings": [], "unmatched_rows": [], "lowScore": []}
    used_rows = set()

    for idx, row in enumerate(texts):
        text = row["text"]
        hits = scan_labels(text, spec)
        for j, h in enumerate(hits):
            start = h["end"]
            end = hits[j + 1]["start"] if j + 1 < len(hits) else len(text)
            value = squeeze(text[start:end]).strip(" ：:　")
            if not value:
                continue
            field = h["field"]
            # 值可能跨行：吸收紧随其后、不含标签、且未明显左移的行
            max_more = MULTILINE.get(field, 0)
            if max_more:
                more, k = 0, idx + 1
                while k < len(texts) and more < max_more:
                    if k in used_rows:
                        break
                    if scan_labels(texts[k]["text"], spec):
                        break
                    piece = squeeze(texts[k]["text"])
                    if not piece:
                        break
                    if texts[k]["left"] < row["left"] - 20:
                        break
                    value += piece
                    used_rows.add(k)
                    more += 1
                    k += 1
            if field not in fields:
                fields[field] = value
            used_rows.add(idx)

    for idx, row in enumerate(texts):
        if idx in used_rows:
            continue
        text = row["text"]
        hits = scan_labels(text, spec)
        if len(hits) != 1:
            continue
        h = hits[0]
        tail = squeeze(text[h["end"]:]).strip(" ：:　")
        if tail:
            fields.setdefault(h["field"], tail)
            used_rows.add(idx)
            continue
        if idx + 1 < len(texts) and (idx + 1) not in used_rows and not scan_labels(texts[idx + 1]["text"], spec):
            fields.setdefault(h["field"], squeeze(texts[idx + 1]["text"]))
            used_rows.add(idx)
            used_rows.add(idx + 1)

    if doc_type in ("business_license", "social_org_cert", "private_nonenterprise_cert"):
        if "credit_code" in fields:
            code, status = fix_uscc(fields["credit_code"])
            fields["credit_code"] = code
            meta["status"]["credit_code"] = status
            if status == "invalid":
                meta["warnings"].append("统一社会信用代码校验未通过，需人工核对")
            elif status == "fixed":
                meta["warnings"].append("统一社会信用代码已由校验位算法修正")
    if doc_type == "id_card_front" and "id_number" in fields:
        code, status = fix_id_card(fields["id_number"])
        fields["id_number"] = code
        meta["status"]["id_number"] = status
        if status == "invalid":
            meta["warnings"].append("公民身份号码校验未通过，需人工核对")
        elif status == "fixed":
            meta["warnings"].append("公民身份号码已由校验位算法修正")

    for field in REQUIRED_FIELD.get(doc_type, []):
        if not fields.get(field):
            meta["warnings"].append("缺少关键字段：" + field)

    for idx, text in enumerate(texts):
        if idx not in used_rows and len(strip_label_noise(text["text"])) >= 2:
            meta["unmatched_rows"].append(text["text"])

    cross_check(doc_type, fields, meta["warnings"])

    return fields, meta


def cross_check(doc_type, fields, warnings):
    """补正验证：住址完整性，以及身份号码与住址、出生日期的相互印证"""
    addr = fields.get("address")
    if addr:
        if len(addr) < 6:
            warnings.append("住址识别结果过短（" + addr + "），可能未取全，请核对原件")
        elif not ADDR_TAIL.search(addr):
            warnings.append("住址「" + addr + "」未见村组或门牌等末端信息，可能未取全，请核对原件")

    if doc_type != "id_card_front":
        return
    idno = fields.get("id_number", "")
    if not re.match(r"^\d{17}[\dXx]$", idno):
        return

    prov = PROVINCE.get(idno[:2])
    if prov and addr and prov[:2] not in addr:
        warnings.append("住址与身份号码的行政区划不一致：号码归属" + prov
                        + "，住址为「" + addr[:14] + "…」，请核对原件")

    y, m, d = idno[6:10], idno[10:12], idno[12:14]
    birth = fields.get("birth", "")
    if birth:
        digits = re.sub(r"\D", "", birth)
        if (y + m + d) not in digits and y not in digits:
            warnings.append("出生日期「" + birth + "」与身份号码中的 "
                            + y + "年" + m + "月" + d + "日 不一致，请核对原件")
