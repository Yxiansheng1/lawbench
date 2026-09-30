"""近似 token 计数：偏大（宁可少装、不超窗口）；tokenizer.json 不进仓库（注记 2332）。"""
from __future__ import annotations

import subprocess

import pytest

from lawbench.config import REPO_ROOT
from lawbench.llm import tokens


@pytest.fixture(autouse=True)
def _approx(monkeypatch):
    monkeypatch.setattr(tokens, "_tokenizer", lambda: None)


@pytest.mark.parametrize("text,at_least", [
    ("借款人王某丙", 6),                   # 每个汉字 1
    ("80000", 5),                         # 数字逐位
    ("2025-03-10", 10),                   # 数字和符号各 1
    ("hello world", 5),                   # 5 个字母算 2，空白 1，再 2
    ("〔借条 第2段〕", 7),
])
def test_approx_not_less_than_expected(text, at_least):
    assert tokens.count(text) >= at_least


def test_approx_monotonic_and_budget():
    assert tokens.count("") == 0
    assert tokens.count("甲" * 100) == 100
    assert tokens.l1_budget("32K") == int(32768 * 0.4)
    assert not tokens.is_exact()


def test_tokenizer_json_ignored_by_git():
    out = subprocess.run(["git", "check-ignore", "service/lawbench/llm/tokenizer.json"], cwd=REPO_ROOT,
                         capture_output=True, text=True)
    assert out.returncode == 0, "tokenizer.json 应被 service\\.gitignore 忽略"
