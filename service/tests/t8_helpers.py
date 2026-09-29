"""T8 测试共用：一个装好样本材料的案件，以及调用 /core、/api 的小函数（返回都按契约校验）。"""
from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile

from starlette.testclient import TestClient

from lawbench.app import create_app
from lawbench.case import gate
from lawbench.config import REPO_ROOT, Config

sys.path.insert(0, str(REPO_ROOT / "contracts"))
from check_examples import validator  # noqa: E402

FIXTURES = REPO_ROOT / "tests" / "fixtures"
TOKEN = "c" * 40


def ok(r, schema: str) -> dict:
    assert r.status_code == 200, r.text
    body = r.json()
    errs = list(validator(schema, "#/$defs/response").iter_errors(body))
    assert not errs, [e.message for e in errs]
    assert body["ok"] is True, body
    return body["value"]


def fail(r, code: str) -> dict:
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False and body["error"]["code"] == code, body
    return body


class Env:
    def __init__(self, base: pathlib.Path, files: dict[str, pathlib.Path]):
        self.appdata = pathlib.Path(tempfile.mkdtemp(prefix="lbad-"))
        self._saved = gate._registry_onedrive_folders
        gate._registry_onedrive_folders = lambda: []
        self.client = TestClient(create_app(Config(token=TOKEN, appdata=self.appdata), key_getter=lambda: None),
                                 raise_server_exceptions=False)
        self.client.headers["Authorization"] = f"Bearer {TOKEN}"
        self.root = base / "张某甲借款纠纷"
        for rel, src in files.items():
            dst = self.root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, dst)
        self.root.mkdir(exist_ok=True)
        self.case_id = ok(self.client.post("/api/case/open", json={"path": str(self.root)}),
                          "api/case_open.schema.json")["case_id"]
        ok(self.client.post("/api/materials/scan", json={"case_id": self.case_id}), "api/materials_scan.schema.json")

    def close(self) -> None:
        self.client.close()
        gate._registry_onedrive_folders = self._saved
        shutil.rmtree(self.appdata, ignore_errors=True)

    # ---------- /core ----------

    def begin(self, session: str = "sess-1", cwd: str | None = None) -> dict:
        return ok(self.client.post("/core/task/begin", json={"session_id": session, "cwd": cwd or str(self.root)}),
                  "core/task_begin.schema.json")

    def tool(self, task_id: str, tool: str, args: dict):
        return self.client.post("/core/tool", json={"task_id": task_id, "tool": tool, "args": args})

    def tool_ok(self, task_id: str, tool: str, args: dict) -> dict:
        v = ok(self.tool(task_id, tool, args), "core/tool.schema.json")
        errs = list(validator(f"tools/{tool}.schema.json", "#/$defs/result").iter_errors(v))
        assert not errs, [e.message for e in errs]
        return v

    def task_dir(self, task_id: str) -> pathlib.Path:
        return self.root / "工作区" / "任务" / task_id

    def read_json(self, task_id: str, name: str, schema: str) -> dict:
        data = json.loads((self.task_dir(task_id) / name).read_text(encoding="utf-8"))
        errs = list(validator(schema).iter_errors(data))
        assert not errs, [e.message for e in errs]
        return data


CASE_FILES = {
    "证据/借条.docx": FIXTURES / "civil-01" / "借条.docx",
    "证据/银行流水.xlsx": FIXTURES / "civil-01" / "银行流水.xlsx",
    "证据/还款记录.csv": FIXTURES / "civil-01" / "还款记录.csv",
    "证据/情况说明.txt": FIXTURES / "civil-01" / "情况说明.txt",
    "起诉意见书.pdf": FIXTURES / "criminal-01" / "起诉意见书.pdf",
    "讯问笔录.pdf": FIXTURES / "criminal-01" / "讯问笔录.pdf",
    "采购合同.docx": FIXTURES / "contract-01" / "采购合同.docx",
    "采购合同-含未处理修订.docx": FIXTURES / "contract-01" / "采购合同-含未处理修订.docx",
    "加密.pdf": FIXTURES / "broken" / "加密.pdf",
}
