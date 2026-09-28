#!/usr/bin/env python3
"""
模板预处理：合并相邻同格式 run，消除碎片化
Clean Template Run Merger

将 模板-不能修改/ 下所有 .docx 的相邻同格式 run 合并，
输出到 模板-清洁版/。generate.py 不会自动切换到清洁版；
如需使用清洁版，应先由维护者确认效果，再回填到源模板或随技能打包的 templates/。
"""

import os, sys, shutil, copy
from docx import Document
from lxml import etree
from docx.oxml.ns import qn


def _configure_console_encoding():
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


_configure_console_encoding()

SRC = os.path.expanduser(os.environ.get("LITIGATION_RETAINER_CIVIL_SRC", "~/Desktop/测试/委托材料/模板-不能修改"))
DST = os.path.expanduser(os.environ.get("LITIGATION_RETAINER_CLEAN_DST", "~/Desktop/测试/委托材料/模板-清洁版"))


def runs_equal(a, b):
    """Compare the entire run properties, including color and character style."""
    def props(run):
        p = run._element.rPr
        return etree.tostring(p, method='c14n') if p is not None else b''
    return props(a) == props(b)


def merge_para_runs(para):
    """合并段落内相邻同格式 run，清除空 run"""
    current = None
    for run in para.runs:
        plain = all(c.tag in (qn('w:rPr'), qn('w:t')) for c in run._element)
        if not plain:
            current = None
            continue
        if current is not None and current._element.getnext() is run._element and runs_equal(current, run):
            for child in list(run._element):
                if child.tag == qn('w:t'):
                    current._element.append(child)
            run._element.getparent().remove(run._element)
        else:
            current = run


def clean_docx(src_path, dst_path):
    """合并一个 docx 中所有 run"""
    shutil.copy2(src_path, dst_path)
    doc = Document(dst_path)

    def process(paragraphs):
        for para in paragraphs:
            merge_para_runs(para)

    process(doc.paragraphs)

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                process(cell.paragraphs)

    for section in doc.sections:
        for h in [section.header, section.footer,
                  section.first_page_header, section.first_page_footer,
                  section.even_page_header, section.even_page_footer]:
            if h:
                process(h.paragraphs)
                for table in h.tables:
                    for row in table.rows:
                        for cell in row.cells:
                            process(cell.paragraphs)

    doc.save(dst_path)


def main():
    if not os.path.isdir(SRC):
        raise FileNotFoundError(f"源目录不存在: {SRC}")
    source = os.path.realpath(SRC)
    target = os.path.realpath(DST)
    if os.path.splitdrive(source)[0].lower() == os.path.splitdrive(target)[0].lower() and os.path.commonpath([source, target]) == source:
        raise ValueError("清理输出目录不能位于源目录内部")
    if os.path.isdir(DST):
        print(f"目标目录已存在: {DST}")
        print("如需重建请先手动删除")
        return

    os.makedirs(DST, exist_ok=True)

    total_files = 0
    total_runs_before = 0
    total_runs_after = 0

    for root, dirs, files in os.walk(SRC):
        for fname in files:
            if not fname.endswith('.docx'):
                continue
            src_path = os.path.join(root, fname)
            rel_path = os.path.relpath(src_path, SRC)
            dst_path = os.path.join(DST, rel_path)
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)

            # 统计原始 run 数
            orig_doc = Document(src_path)
            orig_runs = sum(1 for p in orig_doc.paragraphs for r in p.runs if r.text.strip())

            clean_docx(src_path, dst_path)

            # 统计清理后 run 数
            new_doc = Document(dst_path)
            new_runs = sum(1 for p in new_doc.paragraphs for r in p.runs if r.text.strip())

            reduction = orig_runs - new_runs
            pct = f"-{reduction}/{orig_runs}" if reduction > 0 else "no change"
            print(f"  {rel_path}: {orig_runs} → {new_runs} runs ({pct})")

            total_files += 1
            total_runs_before += orig_runs
            total_runs_after += new_runs

    print(f"\n完成: {total_files} 文件, {total_runs_before} → {total_runs_after} runs"
          f" (-{total_runs_before - total_runs_after}, {(total_runs_before - total_runs_after)*100//max(total_runs_before,1)}%)")


if __name__ == "__main__":
    main()
