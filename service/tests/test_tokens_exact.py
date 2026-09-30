"""有 tokenizer.json（6000D 上 qwen38-27b 的分词器，不进仓库）时：真计数启用，近似计数在仓库样本上不少算。
没有这个文件的机器（复核员的克隆）自动跳过。"""
from __future__ import annotations

import pytest

from lawbench.config import REPO_ROOT
from lawbench.llm import tokens

pytestmark = pytest.mark.skipif(not tokens.TOKENIZER_PATH.is_file(), reason="本机没有 tokenizer.json")


def _approx(text: str) -> int:
    real = tokens._tokenizer
    tokens._tokenizer = lambda: None
    try:
        return tokens.count(text)
    finally:
        tokens._tokenizer = real


def test_exact_enabled():
    assert tokens.is_exact()
    assert tokens.count("借款人王某丙") > 0


def test_approx_not_less_than_exact_on_fixtures():
    tok = tokens._tokenizer()
    checked = 0
    for p in sorted((REPO_ROOT / "tests" / "fixtures").rglob("*")):
        if p.suffix.lower() not in (".txt", ".md", ".csv") or not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        if len(text) < 50:
            continue
        exact = len(tok.encode(text).ids)
        assert _approx(text) >= exact, (p.name, _approx(text), exact)
        checked += 1
    assert checked >= 20


def test_approx_undercounts_extension_cjk_known_limit():
    """已知限制（上一轮复核员预判、主编排裁定不要求）：扩展区生僻字近似每字只算 1，真实更多。"""
    text = "𠀀𠀁𠀂𪚥"
    assert _approx(text) < len(tokens._tokenizer().encode(text).ids)
