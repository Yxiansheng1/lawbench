# -*- coding: utf-8 -*-
"""
一次性修复：个人委托合同的条文补正

背景：`个人委托/1 民事委托代理合同.docx` 缺少两项条文，且有一处语病
（对照见 docs/template-refactor/合同版本差异对照.md）。公司委托合同不受影响。

本脚本做四件事：
  1. 修正「四、2.」段中的主客颠倒语病（乙方未付→甲方未付；支付给甲方→支付给乙方）
  2. 在「八、特别约定」之后插入仲裁条款，编号为「九、」
  3. 原「九、本合同有效期限…」顺延为「十、」
  4. 原「十、本合同一式叁份…」顺延为「十一、」并补入电子签名与电子合同约定
  5. 原「十一、乙方承办律师…」顺延为「十二、」

用法（项目根目录）： python tools/fix-personal-contract.py
"""
import copy
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TARGET = os.path.join(ROOT, "original-skill", "templates", "个人委托", "1 民事委托代理合同.docx")

# 1) 语病修正（主客颠倒）
TYPO_OLD = "乙方已收取的律师费用不再退还给甲方，乙方剩余未付的律师费应当在对方当事人履行完毕的3日内支付给甲方。"
TYPO_NEW = "乙方已收取的律师费用不再退还给甲方，甲方剩余未付的律师费应当在对方当事人履行完毕的3日内支付给乙方。"

# 2) 新增仲裁条款（取自公司委托合同第九条，保持措辞一致）
ARBITRATION = "九、凡因本合同引起的或与本合同有关的任何争议，均应提交深圳国际仲裁院仲裁。"

# 3) 编号顺延 + 补电子签名约定
RENUMBER = [
    # (旧文本片段, 新文本片段)
    ("十一、乙方承办律师已经向甲方详细解释文本内容", "十二、乙方承办律师已经向甲方详细解释文本内容"),
    (
        "十、本合同一式叁份，甲方执壹份，乙方执贰份，自甲乙双方签字或盖章之日起生效。",
        "十一、本合同一式叁份，甲方执壹份，乙方执贰份，自甲乙双方签字或盖章之日起生效"
        "（签字或盖章包括电子签名、电子章）。甲方同意以签署电子合同形式办理该委托事项，"
        "各方通过软件发送的电子合同与纸质合同均同等有效，对各方发生法律约束力。",
    ),
    ("九、本合同有效期限，自签订之日起至本案执行程序中第一次终本之日止。",
     "十、本合同有效期限，自签订之日起至本案执行程序中第一次终本之日止。"),
]


def set_text_keep_format(p, text):
    """替换段落文本，保留段落属性与首个 run 的字体属性"""
    if not p.runs:
        p.add_run(text)
        return
    p.runs[0].text = text
    for r in p.runs[1:]:
        r._element.getparent().remove(r._element)


def clone_paragraph_with_text(ref_para, text):
    """克隆参照段落（继承其段落与字体格式），文本设为给定内容"""
    new_el = copy.deepcopy(ref_para._element)
    # 仅保留首个 run
    runs = new_el.findall("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}r")
    for r in runs[1:]:
        new_el.remove(r)
    if runs:
        r = runs[0]
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        for t in r.findall(ns + "t"):
            r.remove(t)
        t = r.makeelement(ns + "t", {})
        t.text = text
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        r.append(t)
    return new_el


def main():
    from docx import Document

    doc = Document(TARGET)
    paras = list(doc.paragraphs)
    log = []

    def snapshot():
        return [(i, p.text.strip()[:70]) for i, p in enumerate(doc.paragraphs) if p.text.strip()]

    log.append("=== 改动前 ===")
    log += ["[%02d] %s" % (i, t) for i, t in snapshot()]

    # 1) 语病
    for p in paras:
        if TYPO_OLD in p.text:
            set_text_keep_format(p, p.text.replace(TYPO_OLD, TYPO_NEW))
            log.append("· 已修正语病（主客颠倒）")
            break
    else:
        log.append("· 未找到待修正的语病句（可能已处理）")

    # 2) 编号顺延 + 补电子签名（先做，避免与插入混淆）
    for old, new in RENUMBER:
        for p in paras:
            t = p.text
            if t.strip().startswith(old[:6]) or old[:20] in t:
                if old[:14] in t:
                    set_text_keep_format(p, t.replace(old, new))
                    log.append("· 编号/条文已更新：" + new[:26] + "…")
                    break
        else:
            log.append("· 未匹配：" + old[:26] + "…")

    # 3) 插入仲裁条款（在「八、特别约定」之后）
    anchor = None
    for p in paras:
        if p.text.strip().startswith("八、特别约定"):
            anchor = p
            break
    if anchor is None:
        log.append("· 未找到「八、特别约定」，仲裁条款未插入")
    else:
        new_el = clone_paragraph_with_text(anchor, ARBITRATION)
        anchor._element.addnext(new_el)
        log.append("· 已在「八、特别约定」后插入仲裁条款")

    doc.save(TARGET)

    doc2 = Document(TARGET)
    log.append("")
    log.append("=== 改动后（第九条起）===")
    for i, p in enumerate(doc2.paragraphs):
        t = p.text.strip()
        if t and any(t.startswith(k) for k in ["八、", "九、", "十、", "十一、", "十二、"]):
            log.append("[%02d] %s" % (i, t[:110]))
    log.append("")
    log.append("段落总数：%d" % len(doc2.paragraphs))

    out = os.path.join(ROOT, "docs", "template-refactor", "_fix-contract-log.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(log))
    print("\n".join(log))


if __name__ == "__main__":
    main()
