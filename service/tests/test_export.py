"""导出与确认保存（Spec 12.1、14.3、20.8；工单 T15 第 1、2、6 步）。

- 草稿 → 成果/<标题>-v<N>.<md|docx>，版本递增不覆盖，成果/索引.json 过契约；
- 两种格式都去掉指向工作区的链接，出处 〔〕 原样保留；
- pandoc 每次都带 --sandbox：草稿里指向 127.0.0.1 本机监听的远程图片，导出 Word 后监听收到 0 个请求
  （对照：不带 --sandbox 时同一草稿会去取图，证明监听有效）；
- 只读草稿、材料文本，原件区逐字节不变。
"""
from __future__ import annotations

import hashlib
import http.server
import io
import json
import pathlib
import subprocess
import threading
import zipfile

import pytest
from lxml import etree

from lawbench.export import pandoc as P

from t8_helpers import CASE_FILES, FIXTURES, Env, fail, ok, validator

PANDOC = P.find_pandoc()
needs_pandoc = pytest.mark.skipif(PANDOC is None, reason="本机没有 pandoc")
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
INDEX_SCHEMA = validator("files/outputs_index.schema.json")

DRAFT = """# 借款纠纷分析

一、借款事实：张某甲向李某乙出借 10 万元〔借条 第1段〕，详见[借条原文](工作区/材料/文本/M0001.md)。

二、还款情况：见[还款记录](../../材料/文本/M0003.md)与<工作区/任务/x/草稿/a.md>。

三、参考：[最高法公报](https://example.com/case)。
"""


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    e = Env(tmp_path_factory.mktemp("t15exp"), CASE_FILES)
    yield e
    e.close()


@pytest.fixture
def tid(env, request):
    return env.begin(f"sess-{request.node.name}")["task_id"]


def draft(env, tid, title: str, content: str) -> str:
    return env.tool_ok(tid, "case_save_draft", {"title": title, "content": content})["path"]


def confirm(env, tid, rel: str, formats=("md", "docx"), template="文书"):
    return env.client.post("/api/outputs/confirm", json={"case_id": env.case_id, "task_id": tid, "draft": rel,
                                                         "formats": list(formats), "template": template})


def index(env) -> dict:
    data = json.loads((env.root / "成果" / "索引.json").read_text(encoding="utf-8"))
    assert not list(INDEX_SCHEMA.iter_errors(data))
    return data


def originals(env) -> dict:
    return {str(p.relative_to(env.root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in env.root.rglob("*") if p.is_file() and p.relative_to(env.root).parts[0] not in ("工作区", "成果")}


def docx_text(data: bytes) -> tuple[str, str, str]:
    """(各段文字连起来, document.xml 原文, 关系文件原文)：pandoc 会把一句话拆成几个 run，文字要按段拼。"""
    z = zipfile.ZipFile(io.BytesIO(data))
    xml = z.read("word/document.xml")
    root = etree.fromstring(xml)
    paras = ["".join(t.text or "" for t in p.iter(f"{{{W}}}t")) for p in root.iter(f"{{{W}}}p")]
    return "\n".join(paras), xml.decode("utf-8"), z.read("word/_rels/document.xml.rels").decode("utf-8")


def with_font(src: pathlib.Path, old: str, new: str) -> bytes:
    zin = zipfile.ZipFile(src)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for n in zin.namelist():
            data = zin.read(n)
            if n == "word/styles.xml":
                data = data.decode("utf-8").replace(f'w:eastAsia="{old}"', f'w:eastAsia="{new}"').encode("utf-8")
            zout.writestr(n, data)
    return buf.getvalue()


# ---------------------------------------------------------------- 确认流程

@needs_pandoc
def test_confirm_md_and_docx_versions_and_index(env, tid):
    before = originals(env)
    rel = draft(env, tid, "借款纠纷分析", DRAFT)
    v1 = ok(confirm(env, tid, rel), "api/outputs_confirm.schema.json")
    assert v1["outputs"] == [{"format": "md", "path": "成果/借款纠纷分析-v1.md", "version": 1},
                             {"format": "docx", "path": "成果/借款纠纷分析-v1.docx", "version": 1}]
    md = (env.root / "成果" / "借款纠纷分析-v1.md").read_text(encoding="utf-8")
    assert "〔借条 第1段〕" in md and "工作区" not in md and "../../材料" not in md
    assert "详见借条原文。" in md and "见还款记录与。" in md
    assert "[最高法公报](https://example.com/case)" in md                     # 外部网址不是工作区链接，保留
    text, xml, rels = docx_text((env.root / "成果" / "借款纠纷分析-v1.docx").read_bytes())
    assert "〔借条 第1段〕" in text and "详见借条原文。" in text
    assert "工作区" not in xml + rels and "M0001" not in rels and "../../" not in rels

    v2 = ok(confirm(env, tid, rel, formats=["md"]), "api/outputs_confirm.schema.json")   # 再确认一次：v2，v1 不动
    assert v2["outputs"] == [{"format": "md", "path": "成果/借款纠纷分析-v2.md", "version": 2}]
    assert (env.root / "成果" / "借款纠纷分析-v1.docx").is_file()
    entries = [o for o in index(env)["outputs"] if o["title"] == "借款纠纷分析"]
    assert [(o["version"], [f["format"] for f in o["files"]]) for o in entries] == [(1, ["md", "docx"]), (2, ["md"])]
    task = env.read_json(tid, "task.json", "files/task.schema.json")
    assert all(o["task_id"] == tid and o["inputs"] == task["inputs"] for o in entries)
    assert entries[0]["citation_passed"] is True
    # GET /api/outputs 返回同一份索引
    assert ok(env.client.get("/api/outputs", params={"case_id": env.case_id}),
              "api/outputs_list.schema.json") == index(env)
    assert originals(env) == before                                          # 原件区逐字节不变


@needs_pandoc
def test_version_counts_existing_files_case_insensitive(env, tid):
    (env.root / "成果").mkdir(exist_ok=True)
    (env.root / "成果" / "CASE-memo-v7.docx").write_bytes(b"x")              # 律师自己放进去的同名文件也算
    rel = draft(env, tid, "case-memo", "正文〔推断〕")
    v = ok(confirm(env, tid, rel, formats=["md"]), "api/outputs_confirm.schema.json")
    assert v["outputs"][0]["path"] == "成果/case-memo-v8.md"
    assert (env.root / "成果" / "CASE-memo-v7.docx").read_bytes() == b"x"


def test_citation_failed_recorded(env, tid):
    rel = draft(env, tid, "出处有误", "张某甲借款 10 万元〔不存在的材料 第1段〕。")
    ok(confirm(env, tid, rel, formats=["md"]), "api/outputs_confirm.schema.json")
    e = next(o for o in index(env)["outputs"] if o["title"] == "出处有误")
    assert e["citation_passed"] is False


@needs_pandoc
def test_templates(env, tid):
    rel = draft(env, tid, "模板对照", "正文")
    a = ok(confirm(env, tid, rel, formats=["docx"], template="文书"), "api/outputs_confirm.schema.json")
    b = ok(confirm(env, tid, rel, formats=["docx"], template="合同"), "api/outputs_confirm.schema.json")
    c = ok(confirm(env, tid, rel, formats=["docx"], template=None), "api/outputs_confirm.schema.json")

    def font(rel_out):
        z = zipfile.ZipFile(env.root / rel_out)
        return "仿宋" if 'w:eastAsia="仿宋"' in z.read("word/styles.xml").decode() else \
            "宋体" if 'w:eastAsia="宋体"' in z.read("word/styles.xml").decode() else None
    assert font(a["outputs"][0]["path"]) == "仿宋" and font(b["outputs"][0]["path"]) == "宋体"
    assert font(c["outputs"][0]["path"]) == "仿宋"                            # 不选模板按文书


@needs_pandoc
def test_custom_template_from_settings(env, tid, tmp_path):
    s = ok(env.client.get("/api/settings"), "api/settings.schema.json")
    custom = tmp_path / "律所合同模板.docx"
    custom.write_bytes(with_font(P.TEMPLATE_DIR / "合同.docx", "宋体", "黑体"))
    try:
        s2 = json.loads(json.dumps(s))
        s2["templates"]["合同"] = str(custom)
        ok(env.client.put("/api/settings", json=s2), "api/settings.schema.json")
        rel = draft(env, tid, "律所模板", "正文")
        v = ok(confirm(env, tid, rel, formats=["docx"], template="合同"), "api/outputs_confirm.schema.json")
        assert 'w:eastAsia="黑体"' in zipfile.ZipFile(env.root / v["outputs"][0]["path"]).read("word/styles.xml").decode()
        custom.unlink()                                                     # 设置里的模板不在了：报缺模板，不悄悄换
        n = len(list((env.root / "成果").iterdir()))
        fail(confirm(env, tid, rel, formats=["docx"], template="合同"), "TEMPLATE_MISSING")
        assert len(list((env.root / "成果").iterdir())) == n
    finally:
        ok(env.client.put("/api/settings", json=s), "api/settings.schema.json")


def test_pandoc_missing(env, tid, monkeypatch):
    monkeypatch.setenv("LAWBENCH_PANDOC", str(pathlib.Path(env.appdata) / "没有这个" / "pandoc.exe"))
    rel = draft(env, tid, "缺 pandoc", "正文")
    fail(confirm(env, tid, rel, formats=["docx"]), "INTERNAL")
    ok(confirm(env, tid, rel, formats=["md"]), "api/outputs_confirm.schema.json")    # 只要 md 不需要 pandoc


@pytest.mark.parametrize("rel", [
    "工作区/任务/{tid}/草稿/../task.json", "工作区/任务/{tid}/task.json", "证据/借条.docx",
    "工作区/任务/{tid}/草稿/没有-v1.md", "工作区/任务/T-20260101000000-0000/草稿/a-v1.md",
    "工作区/任务/{tid}/草稿/无版本号.md", "成果/借款纠纷分析-v1.md",
])
def test_bad_draft_paths(env, tid, rel):
    r = confirm(env, tid, rel.format(tid=tid), formats=["md"])
    assert r.json()["ok"] is False and r.json()["error"]["code"] in ("INVALID_ARGUMENT", "OUT_OF_CASE")


def test_other_case_task(env, tid):
    rel = draft(env, tid, "别的案件", "正文")
    r = env.client.post("/api/outputs/confirm", json={"case_id": "00000000-0000-4000-8000-000000000000",
                                                      "task_id": tid, "draft": rel, "formats": ["md"],
                                                      "template": None})
    assert r.json()["ok"] is False


def test_docx_draft_confirmed_as_is(env, tid):
    """修订版等 Word 草稿：原样进 成果/，只能选 docx。"""
    path = env.tool_ok(tid, "case_save_edit_list", {"name": "采购合同", "edits": [
        {"id": 1, "para": 27, "action": "replace", "find": "九十日", "text": "三十日", "comment": "期限"}]})["path"]
    red = ok(env.client.post("/api/redline", json={"case_id": env.case_id, "task_id": tid, "edit_list": path}),
             "api/redline.schema.json")
    fail(confirm(env, tid, red["path"], formats=["md", "docx"]), "INVALID_ARGUMENT")
    v = ok(confirm(env, tid, red["path"], formats=["docx"], template=None), "api/outputs_confirm.schema.json")
    assert v["outputs"][0]["path"] == "成果/采购合同-修订版-v1.docx"
    assert (env.root / v["outputs"][0]["path"]).read_bytes() == (env.root / red["path"]).read_bytes()


# ---------------------------------------------------------------- --sandbox：远程图片不取

class _Counter(http.server.BaseHTTPRequestHandler):
    hits: list = []

    def do_GET(self):  # noqa: N802
        type(self).hits.append(self.path)
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.end_headers()
        self.wfile.write(bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                                       "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"))

    def log_message(self, *a):
        pass


@pytest.fixture
def listener():
    _Counter.hits = []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Counter)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", _Counter.hits
    srv.shutdown()
    srv.server_close()


@needs_pandoc
def test_sandbox_no_remote_fetch(env, tid, listener):
    url, hits = listener
    content = f"# 图\n\n![远程图]({url}/a.png)\n\n<img src=\"{url}/b.png\">\n\n正文〔推断〕\n"
    # 对照：不带 --sandbox 的 pandoc 会去取图（证明监听确实能收到）
    subprocess.run([PANDOC, "-f", "markdown", "-t", "docx", "-o", "-"], input=content.encode("utf-8"),
                   capture_output=True, timeout=60)
    assert len(hits) >= 1
    hits.clear()
    rel = draft(env, tid, "远程图片", content)
    ok(confirm(env, tid, rel, formats=["md", "docx"]), "api/outputs_confirm.schema.json")
    assert hits == []


def test_strip_workspace_links_unit():
    s = P.strip_workspace_links
    assert s("[甲](工作区/材料/a.md)") == "甲"
    assert s("[甲](%E5%B7%A5%E4%BD%9C%E5%8C%BA/a.md)") == "甲"
    assert s("![图](工作区/临时/a.png)") == "图"
    assert s("[甲](C:/案件/工作区/a.md) [乙](file:///D:/x.md)") == "甲 乙"
    assert s("[甲][r]\n\n[r]: 工作区/a.md\n") == "甲\n\n\n"
    assert s("[网](https://example.com) <https://example.com> <br> [锚](#一)") == \
        "[网](https://example.com) <https://example.com> <br> [锚](#一)"
    assert s("〔借条 第1段〕【待补充：金额】") == "〔借条 第1段〕【待补充：金额】"


# ---------------------------------------------------------------- 第一轮复核返修（2259 令）

def test_strip_three_more_forms():
    """P3-4：尖括号目标带空格、原始 HTML 的 href / src、图片外再套链接。"""
    s = P.strip_workspace_links
    assert s("[x](<工作区/材料/文本/M 1.md>)") == "x"
    assert s('<a href="工作区/材料/a.md">原文</a>与<a href=\'https://example.com\'>网</a>') == \
        "原文与<a href='https://example.com'>网</a>"
    assert s('前<img src="工作区/临时/a.png">后') == "前后"
    assert s("[![图](工作区/a.png)](工作区/b.md)") == "图"
    assert s("[![图](https://example.com/a.png)](工作区/b.md)") == "![图](https://example.com/a.png)"


@needs_pandoc
def test_raw_openxml_not_passed_through(env, tid):
    """NOTE-1：草稿里的 ```{=openxml} 块（INCLUDEPICTURE 外链）不原样写进 docx。"""
    raw = ('<w:p><w:r><w:fldChar w:fldCharType="begin" w:dirty="true"/></w:r><w:r><w:instrText>'
           ' INCLUDEPICTURE "http://127.0.0.1:9/x.png" \\\\d </w:instrText></w:r>'
           '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
    rel = draft(env, tid, "原始块", f"正文〔推断〕\n\n```{{=openxml}}\n{raw}\n```\n\n`<w:p/>`{{=openxml}}\n")
    v = ok(confirm(env, tid, rel, formats=["docx"]), "api/outputs_confirm.schema.json")
    _text, xml, _rels = docx_text((env.root / v["outputs"][0]["path"]).read_bytes())
    # 原始块只会作为普通文字（代码样式）出现，不会成为真正的域
    assert "<w:instrText" not in xml and "<w:fldChar" not in xml and "<w:fldSimple" not in xml


@needs_pandoc
def test_concurrent_confirms_distinct_versions(env, tid):
    """P3-5：同一案件并发确认 4 次，版本 v1–v4 不撞（案件锁）。"""
    import concurrent.futures
    rel = draft(env, tid, "并发", "正文〔推断〕")
    with concurrent.futures.ThreadPoolExecutor(4) as ex:
        rs = list(ex.map(lambda _i: confirm(env, tid, rel, formats=["md", "docx"]), range(4)))
    versions = sorted(ok(r, "api/outputs_confirm.schema.json")["outputs"][0]["version"] for r in rs)
    assert versions == [1, 2, 3, 4]
    entries = [o for o in index(env)["outputs"] if o["title"] == "并发"]
    assert sorted(o["version"] for o in entries) == [1, 2, 3, 4]


def test_index_write_failure_rolls_back(env, tid, monkeypatch):
    """P3-5：写 成果/索引.json 失败：刚导出的成果文件也删掉，索引不变。"""
    from lawbench.export import outputs as O
    rel = draft(env, tid, "写索引失败", "正文〔推断〕")
    real = O.gate.write_bytes

    def boom(root, r, data, op="write"):
        if r == O.OUTPUTS_REL:
            raise OSError(28, "disk full")
        return real(root, r, data, op=op)
    monkeypatch.setattr(O.gate, "write_bytes", boom)
    before = (env.root / "成果" / "索引.json").read_bytes() if (env.root / "成果" / "索引.json").exists() else None
    r = confirm(env, tid, rel, formats=["md"])
    assert r.json()["ok"] is False
    assert not list((env.root / "成果").glob("写索引失败-v*"))
    after = (env.root / "成果" / "索引.json").read_bytes() if (env.root / "成果" / "索引.json").exists() else None
    assert after == before


def test_logs_have_no_titles_or_content(env, tid):
    """P3-5：确认保存与修订版之后，服务日志里没有标题、正文、材料名、修改内容。"""
    from lawbench import logs
    logs.setup(pathlib.Path(env.appdata))                  # 别的模块建的服务会把日志改指到它的目录：指回本服务
    rel = draft(env, tid, "日志核对标题甲", "日志核对正文乙〔推断〕")
    ok(confirm(env, tid, rel, formats=["md"]), "api/outputs_confirm.schema.json")
    path = env.tool_ok(tid, "case_save_edit_list", {"name": "采购合同", "edits": [
        {"id": 1, "para": 27, "action": "replace", "find": "九十日", "text": "日志核对新文字丙", "comment": "日志核对批注丁"}]})["path"]
    ok(env.client.post("/api/redline", json={"case_id": env.case_id, "task_id": tid, "edit_list": path}),
       "api/redline.schema.json")
    log = "".join(p.read_text(encoding="utf-8") for p in (pathlib.Path(env.appdata) / "logs").glob("service.log*"))
    assert '"op": "confirm"' in log and '"op": "redline"' in log
    for word in ("日志核对标题甲", "日志核对正文乙", "日志核对新文字丙", "日志核对批注丁", "采购合同", "修订版", "九十日"):
        assert word not in log, word


# ---------------------------------------------------------------- 第二轮复核记录项（0110 注记）

def test_strip_html_unclosed_anchors_fast_and_iframe_closed():
    """记录项 5：大量不闭合的 <a href> 不再按平方增长；记录项 6：<iframe>/<object> 连结束标签和里面的内容一起去掉。"""
    import time as _t
    s = P.strip_workspace_links
    big = '<a href="https://example.com/x">' * 4000 + "正文"
    t0 = _t.monotonic()
    assert s(big) == big
    assert _t.monotonic() - t0 < 2
    assert s('<a href="工作区/a.md">不闭合' * 3) == "不闭合" * 3
    assert s('前<iframe src="工作区/a.html">备用</iframe>后<object data="工作区/b.pdf"><p>x</p></object>尾') == "前后尾"
    assert s('<a href="https://e.com">外<a href="工作区/a">内</a></a>') == '<a href="https://e.com">外内</a>'
    assert s('<iframe src="https://e.com/v"></iframe>') == '<iframe src="https://e.com/v"></iframe>'
