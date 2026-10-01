r"""T10 验收：用产品的出处核对库跑 D:\pycharm\test\wiki\大卷宗\wiki\ 的文章，与 检查报告_流水线.txt 对照。

用法（在 service\ 目录）：.venv\Scripts\python ..\docs\plan\evidence\T10\对照_大卷宗.py > ..\docs\plan\evidence\T10\大卷宗对照-原始.txt

只读大卷宗目录，不改它（执行令 1127 硬要求）。转换规则（裁决 5：产品代码不认链接写法，转换在本脚本里做）：
1. 出处 〔[材料名 第N页](../../raw/卷宗/xx.md)〕 → 〔材料名 第N页〕；材料名取链接文字去掉位置部分，
   链接目标（raw 文件）→ 材料集合里的一份材料。同一 raw 文件被写成不同名字时，每个名字都指向它。
   括号里出现链接以外的写法（如"第1页"缺材料名）原样保留，交给库按出处正则判。
2. raw\卷宗\*.md：去掉 "# 标题" 和 "> Source/Collected/Published" 头部，按 【第N页】/【第N段】 切单元；
   没有位置标记的整篇算第 1 页。单元类型取文件里第一个位置标记（页或段）。
3. 文章头部的 "> Sources/Raw/Updated/Archived/Status" 行去掉；Raw 字段里的链接目标即"声明引用的材料"，
   传给库的 declared 参数（D 类）。其余正文里的 Markdown 链接只留文字。
4. 成果类型按 excerpt（wiki 是摘录类）。
5. 参数 --expand：再把 wiki 的简写补成产品写法——"材料名 第1页、第2页"后面几处补上材料名，"第1页至第6页"写成
   "第1-6页"。不加时按原样（这类简写按契约正则报 E）。两种都跑：原样数 E，补全后比 A、B、C。
"""
from __future__ import annotations

import collections
import pathlib
import re
import sys

from lawbench.checks import MaterialSet, check_text

ROOT = pathlib.Path(r"D:\pycharm\test\wiki\大卷宗")
LINK = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
CITE_LINK = re.compile(r"〔\[([^\]]*)\]\(([^)]+)\)〕")
POS = re.compile(r"\s*(第[0-9]+(?:-[0-9]+)?[页段行]|[^ !]+![A-Z]{1,3}[0-9]+(?::[A-Z]{1,3}[0-9]+)?)$")
HEADER = re.compile(r"^>\s*(\*\*)?(Sources?|Raw|Updated|Archived|Status|Collected|Published)\b")
MARK = re.compile(r"【第(\d+)(页|段)】")


def raw_text(p: pathlib.Path) -> tuple[str, str]:
    lines = p.read_text(encoding="utf-8").splitlines()
    body = [ln for ln in lines if not ln.startswith("# ") and not re.match(r"^>\s*(Source|Collected|Published)", ln)]
    text = "\n".join(body).strip("\n") + "\n"
    m = MARK.search(text)
    if not m:
        return "【第1页】\n" + text, "page"
    text = text[m.start():]
    unit = "page" if m.group(2) == "页" else "para"
    # 库按行首的位置标记切单元：标记前补换行
    text = re.sub(r"(?<!^)(?<!\n)(【第\d+[页段]】)", r"\n\1", text)
    # 正文里以【开头、又不是位置标记的行（微信截图的"【2025-03-10 21:14】"）：行首加零宽空格，免得被当成标记；
    # 归一化会去掉零宽空格（类别 Cf），不影响比对。产品里同样的问题见交付说明（T5 的材料文本没有转义）
    text = re.sub(r"(?m)^(?=【(?!第\d+[页段行]】))", "​", text)
    return text, unit


EXPAND = "--expand" in sys.argv


def expand(label: str) -> str:
    name, _, rest = label.partition(" ")
    if not rest:
        return label
    rest = re.sub(r"第(\d+)([页段行])至第(\d+)[页段行]", r"第\1-\3\2", rest)
    return "、".join(x if x.startswith(name + " ") else f"{name} {x}" for x in rest.split("、"))


def main() -> int:
    arts = [p for p in sorted((ROOT / "wiki").rglob("*.md")) if p.name not in ("index.md", "log.md")]
    names: dict[str, pathlib.Path] = {}
    for art in arts:
        for label, href in CITE_LINK.findall(art.read_text(encoding="utf-8")):
            names.setdefault(label.split(" ", 1)[0], (art.parent / href.split("#")[0]).resolve())
    metas = []
    for i, (name, path) in enumerate(sorted(names.items()), 1):
        text, unit = raw_text(path) if path.is_file() else (None, "page")
        metas.append({"name": name, "material_id": f"M{i:04d}", "sha256": "0" * 64, "unit": unit, "text": text,
                      "path": path})
    by_path = collections.defaultdict(set)
    for m in metas:
        by_path[m["path"]].add(m["name"])
    ms = MaterialSet.from_texts(metas)
    total = collections.Counter()
    print(f"# 大卷宗 wiki 用产品出处核对库重跑（excerpt；{'补全简写' if EXPAND else '原样'}）")
    print(f"材料 {len(metas)} 个名字（{len(by_path)} 份 raw 文件）；文章 {len(arts)} 篇\n")
    for art in arts:
        lines_out = []
        declared = set()
        for ln in art.read_text(encoding="utf-8").splitlines():
            if HEADER.match(ln.strip()):
                if re.match(r"^>\s*Raw:", ln.strip()):
                    for _, href in LINK.findall(ln):
                        declared |= by_path.get((art.parent / href).resolve(), set())
                continue
            ln = CITE_LINK.sub(lambda m: "〔" + (expand(m.group(1)) if EXPAND else m.group(1)) + "〕", ln)
            lines_out.append(LINK.sub(r"\1", ln))
        check, _ = check_text("\n".join(lines_out), ms, "excerpt", sorted(declared) if declared else None)
        if not check["problems"]:
            continue
        print(f"## {art.relative_to(ROOT).as_posix()}")
        for p in check["problems"]:
            total[p["class"]] += 1
            print(f"- {p['class']} [{p['severity']}] {p['message']}")
            print(f"    原句：{p['excerpt'][:80]}")
        print()
    print("## 汇总")
    print("；".join(f"{k} {total[k]}" for k in "ABCDEFG"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
