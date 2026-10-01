"""契约注册表与校验（Spec 20.11），以及落盘 JSON 的统一写法（先校验、再写临时文件、再 os.replace）。

写法照 contracts/check_examples.py 的 validator()。
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import tempfile
import time
from functools import lru_cache

from jsonschema import Draft202012Validator, FormatChecker, ValidationError, validators
from referencing import Registry, Resource

# 带 pattern 的字符串字段（编号、期间、批次名、标题、相对路径……）一律是单行：含换行或其他控制字符
# （Unicode Cc）就不合契约。Python 正则的 $ 会放过结尾的换行，"2026-09\n" 能匹配 ^…$（T3 小项，
# 执行令 20261001-1246）。format: date 字段由日期校验整串解析，本来就不收换行。
# 草稿正文这类多行自由文本字段没有 pattern，不受影响。
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _single_line(builtin):
    def check(validator, value, instance, schema):
        if validator.is_type(instance, "string") and _CONTROL.search(instance):
            yield ValidationError("含换行或控制字符")
            return
        yield from builtin(validator, value, instance, schema)
    return check


_Validator = validators.extend(Draft202012Validator, {
    "pattern": _single_line(Draft202012Validator.VALIDATORS["pattern"]),
})

from .config import REPO_ROOT

BASE = "lawbench://contracts/"
_dir: pathlib.Path = REPO_ROOT / "contracts"


class ContractError(Exception):
    """数据不符合契约。只带契约名和字段路径，不带数据内容（Spec 20.8）。"""

    def __init__(self, schema: str, field_path: str):
        super().__init__(f"{schema} {field_path}")
        self.schema = schema
        self.field_path = field_path


def set_contracts_dir(path: pathlib.Path) -> None:
    global _dir
    _dir = pathlib.Path(path)
    registry.cache_clear()
    validator.cache_clear()
    version.cache_clear()


@lru_cache(maxsize=1)
def registry() -> Registry:
    reg = Registry()
    for p in sorted(_dir.rglob("*.schema.json")):
        sch = json.loads(p.read_text(encoding="utf-8"))
        reg = reg.with_resource(sch["$id"], Resource.from_contents(sch))
    return reg


@lru_cache(maxsize=None)
def validator(schema_path: str, pointer: str = "") -> Draft202012Validator:
    """schema_path 如 'api/case_open.schema.json'，pointer 如 '#/$defs/request'。"""
    return _Validator({"$ref": BASE + schema_path + pointer}, registry=registry(), format_checker=FormatChecker())


@lru_cache(maxsize=1)
def version() -> str:
    return (_dir / "VERSION").read_text(encoding="utf-8").strip()


def errors(schema_path: str, pointer: str, data) -> list:
    return list(validator(schema_path, pointer).iter_errors(data))


def validate(schema_path: str, pointer: str, data) -> None:
    errs = errors(schema_path, pointer, data)
    if errs:
        first = min(errs, key=lambda e: len(e.absolute_path))
        raise ContractError(schema_path + pointer, "/" + "/".join(str(p) for p in first.absolute_path))


def write_json(path: pathlib.Path, data, schema_path: str, pointer: str = "") -> None:
    """校验后原子写入。调用方负责先让案件内路径过闸门（case/gate.py）。"""
    validate(schema_path, pointer, data)
    atomic_write_bytes(pathlib.Path(path), json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))


def atomic_write_bytes(path: pathlib.Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".~lb-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        _replace_with_retry(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


REPLACE_RETRIES = 10
REPLACE_WAIT = 0.03


def _replace_with_retry(tmp: str, path: pathlib.Path) -> None:
    """Windows 上目标文件正被别的句柄打开（读取、杀毒扫描）时 os.replace 抛 PermissionError：有上限地重试。"""
    for attempt in range(REPLACE_RETRIES):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == REPLACE_RETRIES - 1:
                raise
            time.sleep(REPLACE_WAIT)


def read_json(path: pathlib.Path):
    """Windows 上文件正被原子替换（os.replace）的那一刻打开会抛 PermissionError：有上限地重试，与写侧对称（T8 F3）。"""
    for attempt in range(REPLACE_RETRIES):
        try:
            return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        except PermissionError:
            if attempt == REPLACE_RETRIES - 1:
                raise
            time.sleep(REPLACE_WAIT)
