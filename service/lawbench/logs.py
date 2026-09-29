"""本机日志（Spec 4.5）。

只记：时间、模块、操作名、案件编号、耗时、状态、错误类型。不记材料名、路径、检索词、模型输入输出、
异常的完整信息（只记异常类名）。调试模式也不放开——所以这里只提供结构化的 event()，不提供自由文本接口。
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import pathlib
from datetime import datetime

_LOGGER = logging.getLogger("lawbench.events")
_LOGGER.propagate = False
_LOGGER.setLevel(logging.INFO)

_STATUS = {"ok", "fail", "denied"}


def setup(appdata: pathlib.Path) -> pathlib.Path:
    log_dir = pathlib.Path(appdata) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    for h in list(_LOGGER.handlers):
        _LOGGER.removeHandler(h)
        h.close()
    h = logging.handlers.TimedRotatingFileHandler(
        log_dir / "service.log", when="midnight", backupCount=14, encoding="utf-8", delay=True)
    h.setFormatter(logging.Formatter("%(message)s"))
    _LOGGER.addHandler(h)
    return log_dir


def close() -> None:
    for h in list(_LOGGER.handlers):
        _LOGGER.removeHandler(h)
        h.close()


def event(module: str, op: str, *, status: str = "ok", case_id: str | None = None,
          duration_ms: int | None = None, error: str | None = None) -> None:
    """error 只能是错误码或异常类名。"""
    if status not in _STATUS:
        raise ValueError(f"未知日志状态 {status}")
    rec = {"t": datetime.now().astimezone().isoformat(timespec="seconds"), "module": module, "op": op,
           "status": status}
    if case_id:
        rec["case_id"] = case_id
    if duration_ms is not None:
        rec["ms"] = int(duration_ms)
    if error:
        rec["error"] = error
    _LOGGER.info(json.dumps(rec, ensure_ascii=False))
