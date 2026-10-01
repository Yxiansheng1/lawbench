"""出处解析与材料位置定位（Spec 9.3、20.2；契约 common.schema.json 的 citation_text、citation、loc）。

识别出处
- 正文里每个〔…〕先判断是不是出处：引号内的〔〕是引语原文的一部分，内容只有 4 位数字的〔〕是公文文号里的年份
  （"虚公刑诉字〔2026〕417号"），这两种不算出处；其余都按契约 citation_text 的正则判，不合格报 E 类。
  正则从契约文件读，不在代码里另写一份宽的（执行令 T10 硬要求）。
- 形如【材料名 第N页】的写法是用错了括号，报 E 类（formats.md 第 3 节）。

定位
- MaterialSet 按材料名找材料，只在用到时读材料文本（工作区/材料/文本，经 texts.read_text 过闸门），不碰原件区。
- 位置文本：页、段、行取对应单元；单元格取该格的显示值（材料文本里的 \\| 还原成 |、<br> 还原成换行）；
  区域（B12:D12）取区域内各格。
"""
from __future__ import annotations

import functools
import json
import re
from dataclasses import dataclass, field

from .. import contracts
from ..case import texts
from ..errors import ApiError

FIXED = ("未找到依据", "推断")
UNIT_OF = {"页": "page", "段": "para", "行": "line"}
WORD_OF = {v: k for k, v in UNIT_OF.items()}

_BRACKET = re.compile(r"〔([^〔〕\n]*)〕")
_YEAR = re.compile(r"^[0-9]{4}$")
QUOTE = re.compile(r"“[^”\n]*”|\"[^\"\n]*\"|「[^」\n]*」")
_LENTICULAR = re.compile(r"【[^【】\n]+? (?:第[0-9]+(?:-[0-9]+)?[页段行]|[^【】!\n]+![A-Z]{1,3}[0-9]+(?::[A-Z]{1,3}[0-9]+)?)】")
_ITEM = re.compile(r"^(?P<name>[^〔〕、 ]+) (?:第(?P<a>[0-9]+)(?:-(?P<b>[0-9]+))?(?P<u>[页段行])"
                   r"|(?P<sheet>[^〔〕、!]+)!(?P<ref>[A-Z]{1,3}[0-9]+(?::[A-Z]{1,3}[0-9]+)?))$")
_REF = re.compile(r"^([A-Z]{1,3})([0-9]+)$")
_CELL_SEP = re.compile(r"(?<!\\)\|")


@functools.lru_cache(maxsize=4)
def _citation_re(contracts_dir: str) -> re.Pattern:
    schema = json.loads((contracts._dir / "common.schema.json").read_text(encoding="utf-8"))
    return re.compile(schema["$defs"]["citation_text"]["pattern"])


def citation_re() -> re.Pattern:
    return _citation_re(str(contracts._dir))


@dataclass
class Item:
    """出处里的一处：材料名 + 结构化位置（契约 $defs/loc）。"""
    name: str
    loc: dict

    def text(self) -> str:
        return f"{self.name} {loc_text(self.loc)}"


@dataclass
class Cite:
    start: int
    end: int
    raw: str                      # 含〔〕的原样文字
    ok: bool                      # 符合 citation_text 正则
    fixed: str | None = None      # 〔未找到依据〕〔推断〕
    items: list[Item] = field(default_factory=list)


def loc_text(loc: dict) -> str:
    if loc["unit"] == "cell":
        return f"{loc['sheet']}!{loc['ref']}"
    rng = f"{loc['from']}-{loc['to']}" if "to" in loc else f"{loc['from']}"
    return f"第{rng}{WORD_OF[loc['unit']]}"


def quote_spans(line: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in QUOTE.finditer(line)]


def _inside(pos: int, spans: list[tuple[int, int]]) -> bool:
    return any(a < pos < b for a, b in spans)


def find_cites(line: str) -> list[Cite]:
    """一行里的出处（按出现顺序）。"""
    quotes = quote_spans(line)
    pat = citation_re()
    out: list[Cite] = []
    for m in _BRACKET.finditer(line):
        body = m.group(1)
        if _inside(m.start(), quotes) or _YEAR.match(body):
            continue
        raw = m.group(0)
        if not pat.match(raw):
            out.append(Cite(m.start(), m.end(), raw, ok=False))
            continue
        if body in FIXED:
            out.append(Cite(m.start(), m.end(), raw, ok=True, fixed=body))
            continue
        items = []
        for part in body.split("、"):
            g = _ITEM.match(part)
            if g["sheet"] is not None:
                loc = {"unit": "cell", "sheet": g["sheet"], "ref": g["ref"]}
            else:
                loc = {"unit": UNIT_OF[g["u"]], "from": int(g["a"])}
                if g["b"] is not None:
                    loc["to"] = int(g["b"])
            items.append(Item(g["name"], loc))
        out.append(Cite(m.start(), m.end(), raw, ok=True, items=items))
    return out


def find_lenticular(line: str) -> list[str]:
    """用【】写的出处（应为〔〕）。"""
    quotes = quote_spans(line)
    return [m.group(0) for m in _LENTICULAR.finditer(line) if not _inside(m.start(), quotes)]


# ---------- 材料 ----------

def col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def col_letters(i: int) -> str:
    out = ""
    while i:
        i, r = divmod(i - 1, 26)
        out = chr(65 + r) + out
    return out


def cell_values(line: str) -> list[str]:
    """Excel 一行"| 行号 | A | B |" → [A 的值, B 的值, …]（显示值，\\| 与 <br> 还原）。"""
    cells = _CELL_SEP.split(line)[2:-1]
    return [c.strip().replace("\\|", "|").replace("<br>", "\n") for c in cells]


@dataclass
class Place:
    label: str      # 出处里的位置写法：第3页、表一!B12
    text: str


class Material:
    def __init__(self, name: str, material_id: str, sha256: str, unit: str, units: list | None):
        self.name = name
        self.material_id = material_id
        self.sha256 = sha256
        self.unit = unit
        self.units = units          # None：没有材料文本（失败、未就绪），不核对内容

    @functools.cached_property
    def places(self) -> list[Place]:
        """最小定位单元：页、段、行各一条；Excel 每个非空单元格一条。"""
        if self.units is None:
            return []
        if self.unit != "cell":
            return [Place(f"第{u.no}{WORD_OF[self.unit]}", u.text) for u in self.units]
        out = []
        for u in self.units:
            for ci, v in enumerate(cell_values(u.text), 1):
                if v:
                    out.append(Place(f"{u.sheet}!{col_letters(ci)}{u.row}", v))
        return out

    def check_loc(self, loc: dict) -> str | None:
        """位置合不合这份材料：返回问题说明，合则 None。"""
        if loc["unit"] != self.unit:
            want = "工作表!单元格" if self.unit == "cell" else f"第N{WORD_OF[self.unit]}"
            return f"这份材料按{want}定位"
        if self.units is None:
            return None
        if self.unit == "cell":
            if any(int(_REF.match(x).group(2)) < 1 for x in loc["ref"].split(":")):
                return "行号从 1 起"
            if not any(u.sheet == loc["sheet"] for u in self.units):
                return f"没有名为“{loc['sheet']}”的工作表"
            return None
        a, b = loc["from"], loc.get("to", loc["from"])
        if a < 1:
            return f"{WORD_OF[self.unit]}号从 1 起"
        if b < a:
            return "范围写反了"
        last = max((u.no for u in self.units), default=0)
        if b > last:
            return f"超出材料范围（共 {last} {WORD_OF[self.unit]}）"
        return None

    def text_at(self, loc: dict) -> str:
        """位置文本。位置不合时返回空串。"""
        if self.units is None or loc["unit"] != self.unit:
            return ""
        if self.unit != "cell":
            a, b = loc["from"], loc.get("to", loc["from"])
            return "\n".join(u.text for u in self.units if a <= u.no <= b)
        refs = loc["ref"].split(":")
        (c1, r1), (c2, r2) = [(col_index(m.group(1)), int(m.group(2)))
                              for m in (_REF.match(x) for x in (refs[0], refs[-1]))]
        out = []
        for u in self.units:
            if u.sheet == loc["sheet"] and min(r1, r2) <= u.row <= max(r1, r2):
                vals = cell_values(u.text)
                out += [vals[c - 1] for c in range(min(c1, c2), max(c1, c2) + 1) if c - 1 < len(vals)]
        return "\n".join(out)


class MaterialSet:
    """按材料名找材料；材料文本用到时才读。"""

    def __init__(self, loader, metas: list[dict]):
        self._loader = loader
        self._metas = {m["name"]: m for m in metas}
        self._cache: dict[str, Material] = {}

    def names(self) -> set[str]:
        return set(self._metas)

    def get(self, name: str) -> Material | None:
        if name not in self._metas:
            return None
        if name not in self._cache:
            m = self._metas[name]
            self._cache[name] = Material(name, m["material_id"], m["sha256"], m["unit"], self._loader(m))
        return self._cache[name]

    @classmethod
    def from_case(cls, root: str, index: dict) -> "MaterialSet":
        def load(m: dict):
            if m["status"] == "failed":
                return None
            try:
                return texts.split_units(texts.read_text(root, m), m["unit"])
            except ApiError:
                return None
        return cls(load, index["materials"])

    @classmethod
    def from_texts(cls, materials: list[dict]) -> "MaterialSet":
        """不经案件目录：每项 {name, material_id, sha256, unit, text}（大卷宗对照脚本、单元测试用）。"""
        return cls(lambda m: texts.split_units(m["text"], m["unit"]) if m.get("text") is not None else None,
                   materials)
