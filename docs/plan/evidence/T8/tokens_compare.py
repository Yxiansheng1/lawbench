r"""近似 token 计数与 qwen38-27b 真实分词器的对比（需要本机有 service\lawbench\llm\tokenizer.json 且装了 tokenizers）。

用法（在 service\ 目录）：.venv\Scripts\python ..\docs\plan\evidence\T8\tokens_compare.py > ..\docs\plan\evidence\T8\tokens-对比.txt
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4] / "service"))
from lawbench.config import REPO_ROOT  # noqa: E402
from lawbench.llm import tokens  # noqa: E402

tok = tokens._tokenizer()
assert tok is not None, "本机没有 tokenizer.json 或没装 tokenizers"


def approx(text: str) -> int:
    real = tokens._tokenizer
    tokens._tokenizer = lambda: None
    try:
        return tokens.count(text)
    finally:
        tokens._tokenizer = real


rows = []
for p in sorted((REPO_ROOT / "tests" / "fixtures").rglob("*")):
    if p.suffix.lower() in (".txt", ".md", ".csv") and p.is_file():
        t = p.read_text(encoding="utf-8", errors="ignore")
        if len(t) >= 50:
            rows.append((str(p.relative_to(REPO_ROOT / "tests" / "fixtures")), t))
rows += [("（造）出处文本", "〔借条 第2段〕借款人王某丙于2025-03-10向出借人借款人民币80000元，约定月利率1.5%。"),
         ("（造）英文混排", "The borrower shall repay USD 12,345.67 before 2025-12-31 per Clause 3.2(b)."),
         ("（造）表格行", "| 12 | 2025-03-10 | 转账 | 80,000.00 | 王某丙 |"),
         ("（造）扩展区生僻字", "𠀀𠀁𠀂𪚥𪚥 龘靐齉 堃犇淼")]
ratios = []
print(f"{'样本':50}\t字数\t真实\t近似\t近似/真实")
for name, t in rows:
    e, a = len(tok.encode(t).ids), approx(t)
    ratios.append((a / e, name))
    print(f"{name:50}\t{len(t)}\t{e}\t{a}\t{a / e:.2f}")
fx = [r for r, n in ratios if not n.startswith("（造）")]
print(f"\n仓库样本 {len(fx)} 份：近似/真实 最小 {min(fx):.2f}，最大 {max(fx):.2f}，中位数 {sorted(fx)[len(fx) // 2]:.2f}")
print("少算的样本：" + ("、".join(n for r, n in ratios if r < 1) or "无"))
