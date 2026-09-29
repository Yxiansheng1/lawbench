"""<应用数据>/settings.json 的读写（契约 files/settings.schema.json）。Key 不在这里（Spec 8.1）。"""
from __future__ import annotations

import copy
import pathlib
import threading

from . import contracts
from .case import gate
from .errors import ApiError

SCHEMA = "files/settings.schema.json"

# 默认值：Spec 第 15 节"地址选择"的四个默认地址；参数默认值同契约样例 file_settings.json
DEFAULTS: dict = {
    "v": 1,
    "servers": {
        "llm_base_url": "http://192.168.8.77:8000/v1",
        "prep_base_url": "http://192.168.8.124:9000",
        "llm_alt_base_url": "http://10.126.126.1:8000/v1",
        "prep_alt_base_url": "http://10.126.126.3:9000",
    },
    "defaults": {"thinking": "中", "window": "64K", "max_tokens": 16384, "temperature": 0.3},
    "skill_presets": {},
    "templates": {"文书": None, "合同": None},
    "ocr_fallback_llm": False,
    "profile": {"lawyer_name": None},
    "office": {"dir": None, "invoice_buyer": None},
    "converter": "auto",
}


class SettingsStore:
    def __init__(self, appdata: pathlib.Path):
        self.path = pathlib.Path(appdata) / "settings.json"
        self._lock = threading.Lock()
        self._listeners: list = []

    def on_change(self, fn) -> None:
        self._listeners.append(fn)

    def get(self) -> dict:
        with self._lock:
            if not self.path.exists():
                return copy.deepcopy(DEFAULTS)
            data = contracts.read_json(self.path)
        if data.get("v") != 1:
            raise ApiError("INTERNAL", "settings_unknown_v")
        contracts.validate(SCHEMA, "", data)
        return data

    def put(self, data: dict) -> dict:
        if self.path.exists():
            if contracts.read_json(self.path).get("v") != 1:
                raise ApiError("INVALID_ARGUMENT", "settings_unknown_v")  # 不认识的 v：只读、不写
        office_dir = data["office"]["dir"]
        if office_dir is not None:
            gate.check_office_dir(office_dir)
        with self._lock:
            contracts.write_json(self.path, data, SCHEMA)
        for fn in self._listeners:
            fn(data)
        return data
