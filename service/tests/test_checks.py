"""T10 出处核对：七类问题的构造用例、cite-cases（G-8）、接入 case_save_draft。"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import tempfile

import pytest
from starlette.testclient import TestClient

from lawbench import logs
from lawbench.app import create_app
from lawbench.case import gate
from lawbench.checks import MaterialSet, check_text, skill_kind
from lawbench.config import REPO_ROOT, Config

from t8_helpers import CASE_FILES, Env, ok, validator

FIXTURES = REPO_ROOT / "tests" / "fixtures"
TOKEN = "k" * 40
WORD = {"page": "页", "para": "段", "line": "行"}


def assert_contract(check: dict, cites: list) -> None:
    errs = list(validator("common.schema.json", "#/$defs/citation_check").iter_errors(check))
    assert not errs, [e.message for e in errs]
    for c in cites:
        errs = list(validator("common.schema.json", "#/$defs/citation").iter_errors(c))
        assert not errs, [e.message for e in errs]


def run(text: str, kind: str = "excerpt", declared=None) -> tuple[dict, list]:
    check, cites = check_text(text, MATS, kind, declared)
    assert_contract(check, cites)
    return check, cites


def classes(check: dict) -> list[str]:
    return [p["class"] for p in check["problems"]]


# ---------- 构造材料（formats.md 第 2 节的材料文本写法） ----------

MATS = MaterialSet.from_texts([
    {"name": "笔录", "material_id": "M0001", "sha256": "a" * 64, "unit": "page",
     "text": "【第1页】\n2025年3月12日，陈美华转账60,000.00元给周立新。\n\n"
             "【第2页】\n被害人称周某某借款8■,000.00元。证人陈美■在场。\n\n"
             "【第3页】\n他说“项目稳赚不赔，年底连本带利还你”，我就信了。\n"},
    {"name": "借条", "material_id": "M0002", "sha256": "b" * 64, "unit": "para",
     "text": "【第1段】\n借款人：王某，1981年6月出生\n\n【第2段】\n今借到人民币80,000元整。\n"},
    {"name": "流水", "material_id": "M0003", "sha256": "c" * 64, "unit": "cell",
     "text": "【表:流水】\n| 行 | A | B | C |\n|---|---|---|---|\n"
             "| 1 | 日期 | 金额 | 对方 |\n| 2 | 2025-03-12 | 60000 | 陈美华 |\n| 3 | 2025-03-20 | 5■,000 | 甲\\|乙丙丁戊己 |\n"},
    {"name": "记录", "material_id": "M0004", "sha256": "d" * 64, "unit": "line",
     "text": "【第1行】\n还款记录\n2025-06-10,20000,手机银行\n3月底结清\n"},
    {"name": "坏件", "material_id": "M0005", "sha256": "e" * 64, "unit": "page", "text": None},
    {"name": "收条", "material_id": "M0006", "sha256": "f" * 64, "unit": "para",
     "text": "【第1段】\n二〇二五年三月十二日，今收到人民币捌万元整，年利率百分之十二。\n\n"
             "【第2段】\n今收到人民币捌万元整（¥80,000）。\n\n"
             "【第3段】\n2025年收到人民币捌万元整。\n"},
])


# ---------- 正确的写法：不报 ----------

@pytest.mark.parametrize("text", [
    "2025年3月12日，陈美华转账6万元〔笔录 第1页〕。",
    "借款80,000元〔借条 第2段〕；同日转账60,000元〔笔录 第1页〕。",
    "转账60000元〔流水 流水!B2〕，对方陈美华〔流水 流水!C2〕。",
    "2025-03-12 至 2025-03-20 的流水〔流水 流水!A2:A3〕。",
    "2025年6月10日还款20,000元〔记录 第2行〕。",
    "被害人称周某某借款8■,000.00元〔笔录 第2页〕。",                 # 照抄识别结果
    "他说“项目稳赚不赔，年底连本带利还你”〔笔录 第3页〕。",
    "金额共60,000元〔笔录 第1-2页〕。",
    "| 2025-03-12 | 转账 60,000 元 | 〔笔录 第1页〕 |",
    "> 2025年3月12日，陈美华转账60,000.00元给周立新。〔笔录 第1页〕",
    "据虚公刑诉字〔2026〕417号起诉意见书，借款80,000元〔借条 第2段〕。",  # 文号年份不是出处
    "附件名写作“〔附件〕”，借款80,000元〔借条 第2段〕。",               # 引号内的〔〕不是出处
    "单元格里是“甲|乙丙丁戊己”〔流水 流水!C3〕。",                    # 单元格里的竖线还原后比
    "| 〔笔录 第1页〕 | 2025年3月12日 转账60,000元 |",                  # 表格行整行算一段（出处在前也算）
    "王某1981年出生〔借条 第1段〕。",                                   # 只写年份也能核到原文的年月
    "他说“项目稳赚不赔，年底连本带利还你”，我就信了〔笔录 第3页〕。",
    "证人称“他说‘项目稳赚不赔，年底连本带利还你’，我就信了”〔笔录 第3页〕。",   # 引文套引文：内层换单引号（P2-1）
    "证人称“他说'项目稳赚不赔，年底连本带利还你'，我就信了”〔笔录 第3页〕。",
    "借款人写“借款人：王某，１９８１年６月出生”〔借条 第1段〕。",          # 全角半角（P3-5）
    "据（2025）京0105民初123号判决书，借款80,000元〔借条 第2段〕。",      # 法院案号不当金额（P3-2）
    "2025年3月12日收到80,000元，年利率12%〔收条 第1段〕。",             # 原文只用中文数字：不比对（裁决 4）
    "收到80,000元〔收条 第2段〕。",
    "2025年3月底结清〔记录 第3行〕。",                                       # 只写月份（月底、月初、月份）
])
def test_correct_citations_pass(text):
    check, _ = run(text)
    assert check["passed"] and check["problems"] == [], check["problems"]


# ---------- A：疑似补全 ----------

@pytest.mark.parametrize("text,needle", [
    ("被害人称周某某借款80,000元〔笔录 第2页〕。", "8■,000.00"),
    ("证人陈美华在场〔笔录 第2页〕。", "陈美■"),
    ("3月20日收入50,000元〔流水 流水!B3〕。", "5■,000"),
])
def test_a_filled_in(text, needle):
    check, _ = run(text)
    a = [p for p in check["problems"] if p["class"] == "A"]
    assert a and needle in a[0]["message"] and a[0]["severity"] == "must_fix" and not check["passed"]


# ---------- B：值在所引材料别处 ----------

@pytest.mark.parametrize("text,where", [
    ("2025年3月12日转账60,000元〔笔录 第2页〕。", "笔录 第1页"),
    ("他说“项目稳赚不赔，年底连本带利还你”〔笔录 第1页〕。", "笔录 第3页"),
    ("3月12日转账60000元〔流水 流水!B3〕。", "流水 流水!B2"),
    ("2025年6月10日还款20,000元〔记录 第1行〕。", "记录 第2行"),
])
def test_b_wrong_location(text, where):
    check, _ = run(text)
    b = [p for p in check["problems"] if p["class"] == "B"]
    assert b and any(where in p["message"] for p in b) and all(p["severity"] == "must_fix" for p in b)


# ---------- C：所引材料中找不到 ----------

@pytest.mark.parametrize("text", [
    "借款90,000元〔借条 第2段〕。",
    "他说“这句话材料里根本就没有”〔笔录 第1页〕。",
    "2024年1月1日签订〔借条 第2段〕。",
    "> 这一句在材料里并不存在的原话〔笔录 第1页〕",                       # 引用块整段按引语核
    "他说‘这句话材料里根本就没有’〔笔录 第1页〕。",                       # 单独的单引号（P3-3）
    "他说＂这句话材料里根本就没有＂〔笔录 第1页〕。",                       # 全角双引号（P3-3）
    "收到90,000元〔收条 第2段〕。",                                       # 同处也有阿拉伯数字：照常核
    "王某1979年出生〔借条 第1段〕。",
])
def test_c_not_found(text):
    check, _ = run(text)
    assert "C" in classes(check) and not check["passed"]


# ---------- D：声明引用的材料里没有（只在给了 declared 时查） ----------

def test_d_undeclared_material():
    check, _ = run("借款80,000元〔借条 第2段〕；转账60,000元〔笔录 第1页〕。", declared=["借条"])
    d = [p for p in check["problems"] if p["class"] == "D"]
    assert len(d) == 1 and "笔录" in d[0]["message"]
    check, _ = run("借款80,000元〔借条 第2段〕。", declared=[])
    assert classes(check) == ["D"]
    check, _ = run("借款80,000元〔借条 第2段〕。")                         # 不给 declared：不查 D
    assert check["passed"]


# ---------- E：出处格式错误 ----------

@pytest.mark.parametrize("text,msg", [
    ("借款80,000元【借条 第2段】。", "【】"),
    ("借款80,000元〔借条第2段〕。", "格式不对"),
    ("借款80,000元〔借条 2段〕。", "格式不对"),
    ("借款80,000元〔借条 第2段、第3段〕。", "格式不对"),                 # 每处都要写材料名
    ("借款80,000元〔不存在 第2段〕。", "没有叫“不存在”的材料"),
    ("借款80,000元〔借条 第9段〕。", "超出材料范围"),
    ("借款80,000元〔借条 第0段〕。", "从 1 起"),
    ("借款80,000元〔借条 第2页〕。", "第N段"),
    ("转账60000元〔流水 别表!B2〕。", "没有名为“别表”的工作表"),
    ("金额〔笔录 第3-1页〕。", "范围写反了"),
    ("转账60000元〔流水 第2行〕。", "工作表!单元格"),
    ("转账60000元〔流水 流水!B99〕。", "超出工作表范围"),                   # P3-1
    ("转账60000元〔流水 流水!Z2〕。", "超出工作表范围"),
    ("转账60000元〔流水 流水!B3:B2〕。", "区域写反了"),
    ("转账60000元〔流水 流水!C2:B3〕。", "区域写反了"),
    ("每人5000元〔京政发〔2024〕1号 第1段〕。", "契约 1.4 前无法引用"),     # P2-2：材料名带〔年份〕
])
def test_e_bad_format(text, msg):
    check, _ = run(text)
    e = [p for p in check["problems"] if p["class"] == "E"]
    assert e and msg in e[0]["message"] and not check["passed"], check["problems"]


# ---------- F：含金额日期但没有出处（提示） ----------

@pytest.mark.parametrize("text", ["2025年3月12日陈美华转账。", "借款共计80,000元。", "| 2025-03-12 | 转账 |"])
def test_f_no_citation_is_hint(text):
    check, _ = run(text)
    assert classes(check) == ["F"] and check["problems"][0]["severity"] == "hint" and check["passed"]


def test_f_not_for_inferred_or_small_numbers():
    check, _ = run("借款应为80,000元〔推断〕。第3条约定共2人。")
    assert check["problems"] == []


# ---------- G：评价性用语，按成果类型 ----------

def test_g_excerpt_must_fix_analysis_hint():
    text = "周立新显然知情〔笔录 第1页〕。"
    check, _ = run(text, "excerpt")
    assert classes(check) == ["G"] and check["problems"][0]["severity"] == "must_fix" and not check["passed"]
    for kind in ("analysis", "draft"):
        check, _ = run(text, kind)
        assert classes(check) == ["G"] and check["problems"][0]["severity"] == "hint" and check["passed"]
        assert "分析意见" in check["problems"][0]["message"]


def test_g_quotes_and_flagged_lines():
    check, _ = run("他说“项目稳赚不赔，年底连本带利还你”〔笔录 第3页〕，证人称“这显然是骗局”〔笔录 第3页〕。")
    assert "G" not in classes(check)                                       # 引号内的原文不算
    check, _ = run("该笔款项用途待律师核实。")
    assert check["problems"] == []
    check, _ = run("构成犯罪与否待律师核实。")                                # 待核实也不豁免定罪判断
    assert classes(check) == ["G"]
    check, _ = run("证人称‘这显然是骗局’，又称＂显然如此＂。")                  # 单引号、全角双引号内也不算（P3-3）
    assert "G" not in classes(check)


def test_material_name_with_year_bracket():
    """材料名带〔年份〕（"京政发〔2024〕1号"）：整条报 E，不消失、不被当文号跳过（P2-2）。"""
    for text in ("每人3000元〔京政发〔2024〕1号 第1段〕。", "每人5000元〔京政发〔2024〕1号 第1段〕，另见〔借条 第2段〕。"):
        check, cites = run(text)
        e = [p for p in check["problems"] if p["class"] == "E"]
        assert e and e[0]["citation"] == "〔京政发〔2024〕1号 第1段〕" and not check["passed"]
        assert all(c["name"] != "京政发〔2024〕1号" for c in cites)
    check, _ = run("据京政发〔2024〕1号文，借款80,000元〔借条 第2段〕。")       # 正文提到文号：不报
    assert check["passed"] and check["problems"] == []


def test_cell_errors_not_recorded_as_citations():
    _, cites = run("转账60000元〔流水 流水!B99〕〔流水 流水!B3:B2〕〔流水 流水!B2〕。")
    assert [c["loc"]["ref"] for c in cites] == ["B2"]


def test_unknown_kind_falls_back_to_analysis():
    check, _ = run("显然如此。", "nonsense")
    assert check["problems"][0]["severity"] == "hint"


# ---------- 推断、未就绪材料、结构化出处 ----------

def test_inferred_skips_value_checks():
    check, _ = run("借款90,000元〔推断〕。他说“完全没有这句话的原文”〔未找到依据〕。"
                   "借款90,000元〔借条 第2段〕〔推断〕。")                    # 与真出处同组也不核
    assert check["passed"] and check["problems"] == []


def test_material_without_text_not_checked():
    check, cites = run("借款90,000元〔坏件 第1页〕。")
    assert check["passed"] and [c["material_id"] for c in cites] == ["M0005"]


def test_structured_citations_deduplicated():
    check, cites = run("借款80,000元〔借条 第2段〕。又见〔借条 第2段〕、〔笔录 第1-2页〕〔流水 流水!B2:C2〕。")
    assert cites == [
        {"material_id": "M0002", "material_version": "b" * 64, "name": "借条", "loc": {"unit": "para", "from": 2}},
        {"material_id": "M0001", "material_version": "a" * 64, "name": "笔录",
         "loc": {"unit": "page", "from": 1, "to": 2}},
        {"material_id": "M0003", "material_version": "c" * 64, "name": "流水",
         "loc": {"unit": "cell", "sheet": "流水", "ref": "B2:C2"}},
    ]
    assert check["stats"]["citations"] == 4


def test_code_blocks_and_headings_skipped():
    check, _ = run("# 2025年3月12日\n```\n借款90,000元〔借条 第2段〕\n```\n<!-- 80,000 -->\n")
    assert check["problems"] == []


def test_no_second_citation_regex_in_code():
    """出处正则只从契约读：产品代码里没有另一份正则字面量（复核 NOTE：原来的自比测试测不出东西）。"""
    pat = json.loads((REPO_ROOT / "contracts" / "common.schema.json").read_text(encoding="utf-8"))
    src = "".join(p.read_text(encoding="utf-8") for p in (REPO_ROOT / "service" / "lawbench").rglob("*.py"))
    assert "(未找到依据|推断" not in src and pat["$defs"]["citation_text"]["pattern"][:20] not in src


def test_year_only_not_exempted_by_chinese_amount():
    """所标位置有阿拉伯数字年份、金额是中文：年份写错照常报，金额不比对（第二轮复核 P3-c，cn6/cn7）。"""
    check, _ = run("2024年收到〔收条 第3段〕。")
    assert classes(check) == ["C"] and not check["passed"]                  # cn6
    check, _ = run("2025年收到80,000元〔收条 第3段〕。")
    assert check["passed"] and check["problems"] == []                      # cn7


def test_skill_md_not_utf8(tmp_path):
    """SKILL.md 不是 UTF-8 时不抛（save_draft 先写草稿后核对，抛了会留下没登记的草稿）。"""
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "SKILL.md").write_bytes("---\nname: x\nkind: excerpt\ndescription: 中文说明\n---\n".encode("gbk"))
    assert skill_kind([tmp_path], "x") == "excerpt"


def test_merge_keeps_latest_version():
    from lawbench.tools.drafts import merge_citations
    loc = {"unit": "para", "from": 2}
    old = [{"material_id": "M0002", "material_version": "b" * 64, "name": "借条", "loc": loc}]
    new = [{"material_id": "M0002", "material_version": "9" * 64, "name": "借条", "loc": dict(loc)}]
    assert merge_citations(old, new) == new


def test_skill_kind_admin_dir_overrides(tmp_path):
    """Spec 10.1：同名时管理员下发（后一个目录）覆盖安装目录；头部带 BOM、kind 带引号也认（P3-4）。"""
    install, admin = tmp_path / "install", tmp_path / "admin"
    for d, kind in ((install, "excerpt"), (admin, "analysis")):
        (d / "x").mkdir(parents=True)
        (d / "x" / "SKILL.md").write_text(f"---\nname: x\nkind: {kind}\n---\n", encoding="utf-8")
    assert skill_kind([install, admin], "x") == "analysis"
    assert skill_kind([install], "x") == "excerpt"
    (admin / "x" / "SKILL.md").write_text('\ufeff---\nname: x\nkind: "excerpt"\n---\n', encoding="utf-8")
    assert skill_kind([install, admin], "x") == "excerpt"
    (admin / "x" / "SKILL.md").write_text("---\nname: x\nkind: 'draft'\n---\n", encoding="utf-8")
    assert skill_kind([install, admin], "x") == "draft"


def test_large_sheet_wrong_locations_fast():
    """2 万行×5 列的流水、30 处位置写错（各差一行）：每处都报 B，空闲机器 10 秒内（P2-3）。"""
    import time
    rows = "\n".join(f"| {r} | 2025-01-01 | {100000 + r} | 户名{r} | 摘要{r} | 备注 |" for r in range(1, 20001))
    big = MaterialSet.from_texts([{"name": "大流水", "material_id": "M0099", "sha256": "9" * 64, "unit": "cell",
                                   "text": "【表:流水】\n| 行 | A | B | C | D | E |\n|---|---|---|---|---|---|\n" + rows}])
    draft = "\n".join(f"金额{100000 + r}元〔大流水 流水!B{r + 1}〕" for r in range(100, 20000, 664))
    t0 = time.perf_counter()
    check, _ = check_text(draft, big, "excerpt")
    took = time.perf_counter() - t0
    b = [p for p in check["problems"] if p["class"] == "B"]
    assert len(draft.splitlines()) == 30 and len(b) == 30 and len(check["problems"]) == 30
    assert took < 10, took


def test_skill_kind():
    dirs = [REPO_ROOT / "skills"]
    assert skill_kind(dirs, "case-wiki-build") == "excerpt"
    assert skill_kind(dirs, "contract-review") == "analysis"
    assert skill_kind(dirs, "contract-draft") == "draft"
    assert skill_kind(dirs, "no-such-skill") == "analysis"
    assert skill_kind(dirs, None) == "analysis"
    assert skill_kind(dirs, "../skills/contract-draft") == "analysis"      # 不拼路径
    assert skill_kind([], "contract-draft") == "analysis"


# ---------- cite-cases（G-8）：正确出处全部通过，改错位置报 B ----------

CITE = json.loads((FIXTURES / "cite-cases.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def cases(tmp_path_factory):
    base = tmp_path_factory.mktemp("t10")
    saved = gate._registry_onedrive_folders
    gate._registry_onedrive_folders = lambda: []
    appdata = pathlib.Path(tempfile.mkdtemp(prefix="lbad-"))
    client = TestClient(create_app(Config(token=TOKEN, appdata=appdata), key_getter=lambda: None),
                        raise_server_exceptions=False)
    client.headers["Authorization"] = f"Bearer {TOKEN}"
    out = {}
    for c in sorted({x["case"] for x in CITE}):
        root = base / c
        shutil.copytree(FIXTURES / c, root)
        cid = ok(client.post("/api/case/open", json={"path": str(root)}), "api/case_open.schema.json")["case_id"]
        ok(client.post("/api/materials/scan", json={"case_id": cid}), "api/materials_scan.schema.json")
        out[c] = MaterialSet.from_case(client.app.state.lb.cases.root_of(cid), client.app.state.lb.materials.index(cid))
    yield out
    client.close()
    gate._registry_onedrive_folders = saved
    logs.close()
    shutil.rmtree(appdata, ignore_errors=True)


def wrong_location(ms: MaterialSet, item: dict) -> tuple[str, bool]:
    """(改错位置后的出处, 材料里有没有别的位置)。只有一页的材料改成第 2 页（超出范围，报 E）。"""
    m = ms.get(item["material"])
    loc = item["loc"]
    if loc["unit"] == "cell":
        col, row = re.match(r"([A-Z]+)(\d+)", loc["ref"]).groups()
        other = next(u.row for u in m.units if u.sheet == loc["sheet"] and u.row != int(row))
        return f"〔{item['material']} {loc['sheet']}!{col}{other}〕", True
    last = max(u.no for u in m.units)
    if last == 1:
        return f"〔{item['material']} 第2{WORD[loc['unit']]}〕", False
    n = loc["from"] + 1 if loc["from"] < last else loc["from"] - 1
    return f"〔{item['material']} 第{n}{WORD[loc['unit']]}〕", True


@pytest.mark.parametrize("item", CITE, ids=[x["citation"] for x in CITE])
def test_cite_cases(cases, item):
    ms = cases[item["case"]]
    check, cites = check_text(f"“{item['text']}”{item['citation']}", ms, "excerpt")
    assert_contract(check, cites)
    assert check["passed"] and check["problems"] == [], check["problems"]
    assert [c["loc"] for c in cites] == [item["loc"]]
    wrong, has_other = wrong_location(ms, item)
    check, _ = check_text(f"“{item['text']}”{wrong}", ms, "excerpt")
    assert not check["passed"]
    assert set(classes(check)) == ({"B"} if has_other else {"E"}), check["problems"]


# ---------- 接入 case_save_draft ----------

@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path / "case", {k: v for k, v in CASE_FILES.items() if k.endswith(".txt")})
    yield e
    e.close()


def create(e, session, skill):
    req = {"case_id": e.case_id, "session_id": session, "entry": skill, "skill": skill, "inputs": [],
           "params": {"thinking": "中", "window": "64K", "max_tokens": 4096}}
    return ok(e.client.post("/api/task", json=req), "api/task_create.schema.json")["task_id"]


def line3_cite(e) -> tuple[str, str, dict]:
    """案件里唯一一份材料（情况说明.txt）第 3 行的原文、材料名、索引项。"""
    m = e.client.app.state.lb.materials.index(e.case_id)["materials"][0]
    line = (FIXTURES / "civil-01" / "情况说明.txt").read_text(encoding="utf-8").splitlines()[2]
    return m["name"], line, m


def test_save_draft_returns_check_and_records_citations(env):
    name, line, m = line3_cite(env)
    create(env, "sess-d1", "case-wiki-build")                                 # kind: excerpt
    tid = env.begin("sess-d1")["task_id"]
    content = f"“{line}”〔{name} 第3行〕\n\n“{line}”〔{name} 第1行〕\n\n显然如此〔{name} 第3行〕\n"
    v = env.tool_ok(tid, "case_save_draft", {"title": "核对", "content": content})
    chk = v["citation_check"]
    assert not chk["passed"] and {"B", "G"} <= set(classes(chk))
    assert all(p["severity"] == "must_fix" for p in chk["problems"] if p["class"] == "G")   # excerpt
    res = env.read_json(tid, "result.json", "files/result.schema.json")
    assert res["citation_check"] == chk
    assert res["citations"] == [
        {"material_id": m["material_id"], "material_version": m["sha256"], "name": name,
         "loc": {"unit": "line", "from": 3}},
        {"material_id": m["material_id"], "material_version": m["sha256"], "name": name,
         "loc": {"unit": "line", "from": 1}}]
    # 第二份草稿：出处并进来、去重
    v = env.tool_ok(tid, "case_save_draft", {"title": "核对2", "content": f"“{line}”〔{name} 第3行〕\n"})
    assert v["citation_check"]["passed"]
    res = env.read_json(tid, "result.json", "files/result.schema.json")
    assert len(res["citations"]) == 2


def test_save_draft_analysis_kind_g_is_hint(env):
    name, _, _ = line3_cite(env)
    create(env, "sess-d2", "contract-review")                                 # kind: analysis
    tid = env.begin("sess-d2")["task_id"]
    v = env.tool_ok(tid, "case_save_draft", {"title": "意见", "content": f"显然如此〔{name} 第1行〕\n"})
    assert v["citation_check"]["passed"] and classes(v["citation_check"]) == ["G"]
    assert v["citation_check"]["problems"][0]["severity"] == "hint"


def test_save_draft_does_not_log_content(env):
    name, _, _ = line3_cite(env)
    tid = env.begin("sess-d3")["task_id"]
    env.tool_ok(tid, "case_save_draft", {"title": "日志", "content": f"独一无二的草稿句子显然〔{name} 第99行〕\n"})
    logs.close()
    text = "".join(p.read_text(encoding="utf-8") for p in (env.appdata / "logs").glob("*"))
    logs.setup(env.appdata)
    assert "独一无二的草稿句子" not in text and f"{name} 第99行" not in text


# ---------- A：识别不清的人名紧挨别的汉字（T10 小项，执行令 20261001-2301 第 2 条） ----------

ADJ = MaterialSet.from_texts([
    {"name": "流水单", "material_id": "M0011", "sha256": "1" * 64, "unit": "page",
     "text": "【第1页】\n2025-03-20 转账 80,000.00 对方户名 陈美■ 摘要 投资\n\n"
             "【第2页】\n收款人 陈■华 已签收\n\n"
             "【第3页】\n| 2025-03-20 | 转账 | 陈美■ |\n\n"
             "【第4页】\n对方户名付■ 摘要 转账\n"}])


@pytest.mark.parametrize("text,needle", [
    ("3月20日向陈美华转账〔流水单 第1页〕。", "陈美■"),           # ■ 在名字末尾，前面紧挨"对方户名"
    ("陈美华已签收〔流水单 第2页〕。", "陈■华"),                   # ■ 在名字中间，前面紧挨"收款人"
    ("3月20日向陈美华转账〔流水单 第3页〕。", "陈美■"),           # 表格单元格里：本来就认得出，仍然认得出
])
def test_a_name_next_to_other_chars(text, needle):
    check, cites = check_text(text, ADJ, "excerpt")
    assert_contract(check, cites)
    a = [p for p in check["problems"] if p["class"] == "A"]
    assert a and needle in a[0]["message"] and not check["passed"], check["problems"]


@pytest.mark.parametrize("text", [
    "3月20日向陈美■转账〔流水单 第1页〕。",                         # 照抄识别结果
    "陈■华已签收〔流水单 第2页〕。",
    "3月20日向陈美■转账〔流水单 第3页〕。",
    "对方户名陈美■〔流水单 第1页〕。",
    "支付了款项〔流水单 第4页〕。",                                # 不取 2 字子串："付■"不去配"付了"
])
def test_a_name_next_to_other_chars_copied(text):
    check, _ = check_text(text, ADJ, "excerpt")
    assert "A" not in classes(check), check["problems"]


def test_name_windows():
    from lawbench.checks.citations import _name_windows
    assert _name_windows("陈美■") == ["陈美■"]                      # 不长于 4 字：只看整串（原来的做法）
    w = _name_windows("对方户名陈美■")
    assert w[0] == "对方户名陈美■" and "名陈美■" in w and "陈美■" in w
    assert not any(len(x) < 3 for x in w) and all("■" in x for x in w)
