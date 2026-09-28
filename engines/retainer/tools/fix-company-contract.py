# -*- coding: utf-8 -*-
"""
公司委托合同条文补正

背景：公司委托合同第十一条原为「本合同一式 叁 份，甲方执 壹 份，乙方执 两 份。双方签字或盖章后生效。」
按用户指示，份数与生效表述统一为与个人委托合同一致，并补入电子签名与电子合同约定。

改后：
  十一、本合同一式叁份，甲方执壹份，乙方执贰份，自甲乙双方签字或盖章之日起生效
  （签字或盖章包括电子签名、电子章）。甲方同意以签署电子合同形式办理该委托事项，
  各方通过软件发送的电子合同与纸质合同均同等有效，对各方发生法律约束力。

用法（项目根目录）： python tools/fix-company-contract.py
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TARGET = os.path.join(ROOT, "original-skill", "templates", "公司委托", "1 民事委托代理合同.docx")

PREFIX = "十一、本合同一式"
NEW_TEXT = (
    "十一、本合同一式叁份，甲方执壹份，乙方执贰份，自甲乙双方签字或盖章之日起生效"
    "（签字或盖章包括电子签名、电子章）。甲方同意以签署电子合同形式办理该委托事项，"
    "各方通过软件发送的电子合同与纸质合同均同等有效，对各方发生法律约束力。"
)


def set_text_keep_format(p, text):
    """替换段落文本，保留段落属性与首个 run 的字体属性"""
    if not p.runs:
        p.add_run(text)
        return
    p.runs[0].text = text
    for r in p.runs[1:]:
        r._element.getparent().remove(r._element)


def main():
    from docx import Document

    doc = Document(TARGET)
    log = []
    target = None
    for p in doc.paragraphs:
        if p.text.strip().startswith(PREFIX):
            target = p
            break

    if target is None:
        log.append("未找到以「%s」开头的段落，未做任何修改。" % PREFIX)
    else:
        log.append("原第十一条：")
        log.append("  " + target.text.strip())
        log.append("")
        log.append("已改为：")
        log.append("  " + NEW_TEXT)
        set_text_keep_format(target, NEW_TEXT)
        doc.save(TARGET)

    doc2 = Document(TARGET)
    log.append("")
    log.append("=== 改动后（第九条起）===")
    for i, p in enumerate(doc2.paragraphs):
        t = p.text.strip()
        if t.startswith(("八、", "九、", "十、", "十一、", "十二、", "（以下无正文）")):
            log.append("[%02d] %s" % (i, t))
    log.append("")
    log.append("段落总数：%d" % len(doc2.paragraphs))

    out = os.path.join(ROOT, "docs", "template-refactor", "_fix-company-log.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(log))
    print("\n".join(log))


if __name__ == "__main__":
    main()
