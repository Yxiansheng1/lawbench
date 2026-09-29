"""395 访问日志（Spec 6.6）：JSON Lines，按天滚动、保留 30 天，只记元数据。

字段固定为 ts、key（Key 的 SHA-256 前 8 位）、api、pages、bytes、elapsed_ms、status、err（异常类名）；
不记图片、文本、识别结果、检索词或 Key 原文。
"""
from __future__ import annotations

import json
import logging
import logging.handlers
from datetime import datetime, timezone
from pathlib import Path

FIELDS = ("ts", "key", "api", "pages", "bytes", "elapsed_ms", "status", "err")


class AccessLog:
    def __init__(self, log_dir: Path) -> None:
        log_dir.mkdir(parents=True, exist_ok=True)
        self.path = log_dir / "access.log"
        self._log = logging.getLogger(f"prep395.access.{id(self)}")
        self._log.propagate = False
        self._log.setLevel(logging.INFO)
        h = logging.handlers.TimedRotatingFileHandler(self.path, when="midnight", backupCount=30,
                                                      encoding="utf-8")
        h.setFormatter(logging.Formatter("%(message)s"))
        self._handler = h
        self._log.addHandler(h)

    def write(self, *, key: str | None, api: str, pages: int, nbytes: int, elapsed_ms: int,
              status: int, err: str | None) -> None:
        rec = {
            "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "key": key,
            "api": api,
            "pages": pages,
            "bytes": nbytes,
            "elapsed_ms": elapsed_ms,
            "status": status,
            "err": err,
        }
        self._log.info(json.dumps(rec, ensure_ascii=False))

    def event(self, api: str, count: int) -> None:
        """服务自身的事件（如启动清理），同样只记数量。"""
        self.write(key=None, api=api, pages=count, nbytes=0, elapsed_ms=0, status=0, err=None)

    def close(self) -> None:
        self._log.removeHandler(self._handler)
        self._handler.close()
