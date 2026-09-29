"""契约注册表与校验（Spec 20.11），以及落盘 JSON 的统一写法（先校验、再写临时文件、再 os.replace）。

写法照 contracts/check_examples.py 的 validator()。
"""
from __future__ import annotations

import json
import os
import pathlib
import tempfile
from functools import lru_cache

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

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
    return Draft202012Validator({"$ref": BASE + schema_path + pointer}, registry=registry(),
                                format_checker=FormatChecker())


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
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def read_json(path: pathlib.Path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
