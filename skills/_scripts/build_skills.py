"""同步共用规则，并按 Spec 第 10 节校验 Skill 和胶囊配置。

用法：
    python build_skills.py                  # 默认根目录 = 本脚本所在目录的上一级
    python build_skills.py --root "D:\\新建文件夹\\skill临时文件夹"
    python build_skills.py --check          # 只检查不写入；不同步或有错误时退出码 1
    python build_skills.py --strict         # 发版用：缺测试集、owner 未定也算错误

做两件事：
1. 把 _shared/共用规则.md 写进胶囊配置里用到的每个 Skill 的
   <!-- 共用规则:开始 --> ... <!-- 共用规则:结束 --> 之间；
   没有标记的，插到"## 自检清单"之前。
2. 校验（错误必须改；警告建议看，--strict 时部分警告升级为错误）：
   胶囊配置 capsules.default.json
     - 分组、胶囊的 id 全局不重复；同组胶囊名不重复
     - kind=skill 的 skills 都存在；kind=tool 的 tool 是已知内置工具；shared 里的 Skill 都存在
   SKILL.md 头部（Spec 10.2）
     - name/title/description/mode/kind/params/owner/inputs 齐全
     - name 与目录名一致；mode、kind、inputs、params 取值合法
     - mode=pipeline 必须有 流水线提示词.md
   SKILL.md 正文（Spec 10.2）
     - 六个二级标题齐全且顺序正确
     - 必问问题每条符合"- key：问题（可从材料中获取：是/否）"，或整节写"无"
     - 自检清单至少一条
     - 只用允许的 case_* 工具；不出现 bash 等通用工具；/skill名 引用都存在
     - 写了保存成果的工具（只做指引的 Skill 除外）
   tests/（Spec 10.2）：至少 4 个样本目录和 要点.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import skill_manifest as M  # noqa: E402

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("缺少 PyYAML，请先运行：pip install pyyaml")

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
TOOL_RE = re.compile(r"\bcase_[a-z_]+\b")
SLASH_RE = re.compile(r"`/([a-z0-9-]+)`")
STATUTE_RE = re.compile(r"《[^》]{2,30}》\s*第[一二三四五六七八九十百千零\d]+条")
QUESTION_RE = re.compile(M.QUESTION_PATTERN)
H2_RE = re.compile(r"^## (.+?)\s*$", re.M)


@dataclass
class Capsule:
    group: str
    id: str
    name: str
    kind: str
    skills: list[str]
    tool: str | None


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    capsules: list[Capsule] = field(default_factory=list)
    shared: list[str] = field(default_factory=list)
    metas: dict[str, dict] = field(default_factory=dict)

    def soft(self, msg: str, strict: bool) -> None:
        (self.errors if strict else self.warnings).append(msg)


# ---------- 读写 ----------

def setup_console() -> None:
    # Windows 控制台默认 GBK，打印 ✔ ⚠ 会报错
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def read_text(path: Path) -> tuple[str, str]:
    """读取 UTF-8 文本（兼容 BOM），返回 (内容，统一为 \\n；原换行符)。"""
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    text = raw.decode("utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    return text.replace("\r\n", "\n"), newline


def write_text(path: Path, text: str, newline: str) -> None:
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))


def split_frontmatter(text: str) -> tuple[str | None, str]:
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return None, text
    return text[4:end], text[end + 5:]


def as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


# ---------- 共用规则 ----------

def build_block(rules: str) -> str:
    return f"{M.BLOCK_START}\n{rules.strip()}\n{M.BLOCK_END}"


def sync_block(text: str, block: str) -> str:
    start, end = text.find(M.BLOCK_START), text.find(M.BLOCK_END)
    if start != -1 and end > start:
        return text[:start] + block + text[end + len(M.BLOCK_END):]
    anchor = re.search(rf"^## {re.escape(M.BLOCK_ANCHOR)}\s*$", text, flags=re.M)
    if anchor:
        i = anchor.start()
        return text[:i] + block + "\n\n" + text[i:]
    return text.rstrip("\n") + "\n\n" + block + "\n"


def strip_block(body: str) -> str:
    s, e = body.find(M.BLOCK_START), body.find(M.BLOCK_END)
    if s != -1 and e > s:
        return body[:s] + body[e + len(M.BLOCK_END):]
    return body


# ---------- 胶囊配置 ----------

def load_capsules(root: Path, rep: Report) -> list[Capsule]:
    f = root / M.CAPSULES_FILE
    tag = f"[{M.CAPSULES_FILE}]"
    if not f.is_file():
        rep.errors.append(f"找不到胶囊配置：{f}（Spec 10.3）")
        return []
    try:
        data = json.loads(read_text(f)[0])
    except json.JSONDecodeError as exc:
        rep.errors.append(f"{tag} JSON 格式错误：{exc}")
        return []
    rep.shared = [str(x) for x in as_list(data.get("shared"))]
    caps: list[Capsule] = []
    ids: list[str] = []
    for g in as_list(data.get("groups")):
        gid, gname = str(g.get("id", "")), str(g.get("name", ""))
        if not gid or not gname:
            rep.errors.append(f"{tag} 有分组缺少 id 或 name")
            continue
        ids.append(gid)
        names: list[str] = []
        for it in as_list(g.get("items")):
            cid, cname, kind = str(it.get("id", "")), str(it.get("name", "")), it.get("kind")
            if not NAME_RE.match(cid) or not cname:
                rep.errors.append(f"{tag} 分组「{gname}」里有胶囊的 id 或 name 不合法：{cid!r}")
                continue
            ids.append(cid)
            names.append(cname)
            if kind == "skill":
                skills = [str(x) for x in as_list(it.get("skills"))]
                if not skills:
                    rep.errors.append(f"{tag} 胶囊「{cname}」没有 skills")
                if len(set(skills)) != len(skills):
                    rep.errors.append(f"{tag} 胶囊「{cname}」的 skills 有重复")
                caps.append(Capsule(gname, cid, cname, "skill", skills, None))
            elif kind == "tool":
                tool = str(it.get("tool", ""))
                if tool not in M.TOOL_IDS:
                    rep.errors.append(f"{tag} 胶囊「{cname}」的 tool 只能是 {' / '.join(sorted(M.TOOL_IDS))}")
                caps.append(Capsule(gname, cid, cname, "tool", [], tool))
            else:
                rep.errors.append(f"{tag} 胶囊「{cname}」的 kind 只能是 skill / tool")
        dup = sorted({n for n in names if names.count(n) > 1})
        if dup:
            rep.errors.append(f"{tag} 分组「{gname}」里胶囊名重复：{', '.join(dup)}")
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        rep.errors.append(f"{tag} id 重复：{', '.join(dup)}")
    return caps


def managed_skills(caps: list[Capsule], shared: list[str] | None = None) -> list[str]:
    out: list[str] = []
    for s in [x for c in caps for x in c.skills] + list(shared or []):
        if s not in out:
            out.append(s)
    return out


# ---------- 单个 Skill ----------

def check_meta(name: str, skill_dir: Path, meta: dict, rep: Report, strict: bool) -> None:
    tag = f"[{name}]"
    missing = [k for k in M.REQUIRED_FIELDS if meta.get(k) in (None, "", [], {})]
    if missing:
        rep.errors.append(f"{tag} 头部缺少：{', '.join(missing)}")

    if meta.get("name") is not None and meta.get("name") != name:
        rep.errors.append(f"{tag} 头部 name 为 {meta.get('name')!r}，必须与目录名一致")
    if not NAME_RE.match(name):
        rep.errors.append(f"{tag} 目录名只能用小写字母、数字和连字符")

    desc = str(meta.get("description") or "")
    if len(desc) > M.DESC_MAX:
        rep.warnings.append(f"{tag} description 有 {len(desc)} 字，建议不超过 {M.DESC_MAX} 字")

    mode = meta.get("mode")
    if mode is not None and mode not in M.MODES:
        rep.errors.append(f"{tag} mode 只能是 {' / '.join(sorted(M.MODES))}")
    if mode == "pipeline" and not (skill_dir / "流水线提示词.md").is_file():
        rep.errors.append(f"{tag} mode 为 pipeline，但没有 流水线提示词.md")

    kind = meta.get("kind")
    if kind is not None and kind not in M.KINDS:
        rep.errors.append(f"{tag} kind 只能是 {' / '.join(sorted(M.KINDS))}")

    params = meta.get("params")
    if params is not None:
        if not isinstance(params, dict):
            rep.errors.append(f"{tag} params 必须写成 {{thinking: …, window: …, max_tokens: …}}")
        else:
            if params.get("thinking") not in M.PARAM_THINKING:
                rep.errors.append(f"{tag} params.thinking 只能是 {' / '.join(sorted(M.PARAM_THINKING))}")
            if params.get("window") not in M.PARAM_WINDOW:
                rep.errors.append(f"{tag} params.window 只能是 {' / '.join(sorted(M.PARAM_WINDOW))}")
            mt = params.get("max_tokens")
            if not isinstance(mt, int) or not 1 <= mt <= M.MAX_TOKENS_LIMIT:
                rep.errors.append(f"{tag} params.max_tokens 必须是 1–{M.MAX_TOKENS_LIMIT} 的整数")
            extra = set(params) - {"thinking", "window", "max_tokens"}
            if extra:
                rep.warnings.append(f"{tag} params 里有未定义的字段：{', '.join(sorted(extra))}")

    owner = str(meta.get("owner") or "")
    if owner and (owner == "待定" or owner.startswith("<")):
        rep.soft(f"{tag} owner（责任律师）未指定", strict)

    inputs = as_list(meta.get("inputs"))
    bad = [i for i in inputs if i not in M.INPUTS]
    if bad:
        rep.errors.append(f"{tag} inputs 只能取 {' / '.join(sorted(M.INPUTS))}，出现了 {', '.join(map(str, bad))}")

    for k in ("entry", "order"):
        if k in meta:
            rep.warnings.append(f"{tag} 头部的 {k} 已废止（契约 1.1 起由胶囊配置决定），可以删掉")


def check_body(name: str, body: str, all_skills: set[str], meta: dict, rep: Report) -> None:
    tag = f"[{name}]"
    if body.count(M.BLOCK_START) > 1 or body.count(M.BLOCK_END) > 1:
        rep.errors.append(f"{tag} 共用规则标记出现多次，请手动删掉多余的")
    own = strip_block(body)

    # 六个二级标题
    heads = [h for h in H2_RE.findall(own)]
    positions = []
    for sec in M.REQUIRED_SECTIONS:
        if sec not in heads:
            rep.errors.append(f"{tag} 缺少二级标题「## {sec}」")
        else:
            positions.append(heads.index(sec))
    if len(positions) == len(M.REQUIRED_SECTIONS) and positions != sorted(positions):
        rep.errors.append(f"{tag} 六个二级标题顺序应为：{' → '.join(M.REQUIRED_SECTIONS)}")
    extra = [h for h in heads if h not in M.REQUIRED_SECTIONS]
    if extra:
        rep.warnings.append(f"{tag} 有额外的二级标题：{', '.join(extra)}（建议改成 ### 放进六部分里）")

    sections = section_texts(own)

    # 必问问题
    q = sections.get("必问问题")
    if q is not None:
        lines = [ln.strip() for ln in q.split("\n") if ln.strip()]
        if lines != ["无"]:
            keys = []
            for ln in lines:
                m = QUESTION_RE.match(ln)
                if not m:
                    rep.errors.append(f"{tag} 必问问题格式不对：{ln[:40]}（应为\"- key：问题（可从材料中获取：是/否）\"）")
                else:
                    keys.append(m.group(1))
            dup = sorted({k for k in keys if keys.count(k) > 1})
            if dup:
                rep.errors.append(f"{tag} 必问问题的 key 重复：{', '.join(dup)}")
            if not lines:
                rep.errors.append(f"{tag} 必问问题为空；没有就写\"无\"")

    # 自检清单
    c = sections.get("自检清单")
    if c is not None and not re.search(r"^- \S", c, re.M):
        rep.errors.append(f"{tag} 自检清单至少要有一条（- 开头）")

    # 工具
    for tool in sorted(set(TOOL_RE.findall(own))):
        if tool not in M.ALLOWED_TOOLS and tool not in M.NON_TOOL_NAMES:
            rep.errors.append(f"{tag} 使用了不存在的工具 {tool}")
    for tool in sorted(M.FORBIDDEN_TOOLS):
        if re.search(rf"`{re.escape(tool)}`", own):
            rep.errors.append(f"{tag} 出现通用工具 `{tool}`，律师工作台不提供")
    for ref in sorted(set(SLASH_RE.findall(own))):
        if ref not in all_skills:
            rep.errors.append(f"{tag} 引用了 /{ref}，但胶囊配置里没有这个 Skill")
    if name not in M.NO_SAVE_REQUIRED and not any(t in own for t in M.SAVE_TOOLS):
        rep.errors.append(f"{tag} 正文没有写怎么保存成果（{' / '.join(sorted(M.SAVE_TOOLS))}）")

    # 头部 inputs 与正文是否一致
    inputs = as_list(meta.get("inputs"))
    if "<L1 任务输入>" in own and "prior" not in inputs:
        rep.warnings.append(f"{tag} 正文用到 <L1 任务输入>，但 inputs 里没有 prior")

    for m in STATUTE_RE.finditer(own):
        rep.warnings.append(f"{tag} 出现具体法条「{m.group(0)}」，与共用规则冲突，请确认")


def section_texts(body: str) -> dict[str, str]:
    """按二级标题切分正文，返回 {标题: 内容}。"""
    out: dict[str, str] = {}
    matches = list(H2_RE.finditer(body))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        out[m.group(1)] = body[m.end():end]
    return out


def check_tests(name: str, skill_dir: Path, rep: Report, strict: bool) -> None:
    tests = skill_dir / "tests"
    samples = [p for p in tests.iterdir() if p.is_dir()] if tests.is_dir() else []
    if len(samples) < M.TESTS_MIN_SAMPLES or not (tests / "要点.md").is_file():
        rep.soft(f"[{name}] 测试集不全：tests/ 下需要至少 {M.TESTS_MIN_SAMPLES} 个样本目录和 要点.md"
                 f"（现有 {len(samples)} 个样本）", strict)


# ---------- 主流程 ----------

def run(root: Path, check_only: bool, strict: bool = False) -> Report:
    rep = Report()
    rules_path = root / M.SHARED_RULES_FILE
    if not rules_path.is_file():
        rep.errors.append(f"找不到共用规则文件：{rules_path}")
        return rep
    block = build_block(read_text(rules_path)[0])

    rep.capsules = load_capsules(root, rep)
    names = managed_skills(rep.capsules, rep.shared)
    all_skills = set(names)

    for name in names:
        skill_dir = root / name
        path = skill_dir / "SKILL.md"
        if not path.is_file():
            rep.errors.append(f"[{name}] 胶囊配置里有，但找不到 {path}")
            continue
        try:
            text, newline = read_text(path)
        except UnicodeDecodeError:
            rep.errors.append(f"[{name}] SKILL.md 不是 UTF-8 编码，请另存为 UTF-8")
            continue

        new_text = sync_block(text, block)
        if new_text != text:
            rep.changed.append(name)
            if not check_only:
                write_text(path, new_text, newline)

        head, body = split_frontmatter(new_text)
        if head is None:
            rep.errors.append(f"[{name}] SKILL.md 缺少 --- 包围的头部信息")
            continue
        try:
            meta = yaml.safe_load(head) or {}
        except yaml.YAMLError as exc:
            rep.errors.append(f"[{name}] 头部 YAML 格式错误：{exc}")
            continue
        if not isinstance(meta, dict):
            rep.errors.append(f"[{name}] 头部必须是 key: value 形式")
            continue
        rep.metas[name] = meta
        check_meta(name, skill_dir, meta, rep, strict)
        check_body(name, body, all_skills, meta, rep)
        check_tests(name, skill_dir, rep, strict)

    others = sorted(
        p.name for p in root.iterdir()
        if p.is_dir() and (p / "SKILL.md").is_file() and p.name not in all_skills
    )
    if others:
        rep.warnings.append(f"以下 Skill 不在胶囊配置里，不会被加载（仅参考）：{', '.join(others)}")
    return rep


def print_report(rep: Report, check_only: bool) -> bool:
    if rep.changed:
        verb = "需要同步共用规则" if check_only else "已同步共用规则"
        print(f"\n{verb}（{len(rep.changed)} 个）：{', '.join(rep.changed)}")
    else:
        print("\n共用规则：全部一致")
    if rep.warnings:
        print(f"\n⚠ 警告 {len(rep.warnings)} 条：")
        for w in rep.warnings:
            print(f"  - {w}")
    if rep.errors:
        print(f"\n✘ 错误 {len(rep.errors)} 条：")
        for e in rep.errors:
            print(f"  - {e}")
    failed = bool(rep.errors) or (check_only and bool(rep.changed))
    print("\n结果：" + ("未通过" if failed else "✔ 通过"))
    return not failed


def main() -> int:
    setup_console()
    ap = argparse.ArgumentParser(description="同步共用规则，按 Spec 第 10 节校验 Skill")
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent,
                    help="Skill 根目录（默认：本脚本上一级目录）")
    ap.add_argument("--check", action="store_true", help="只检查，不写文件；不同步也算失败")
    ap.add_argument("--strict", action="store_true", help="发版用：缺测试集、owner 未指定也算错误")
    args = ap.parse_args()

    root = args.root.resolve()
    print(f"Skill 根目录：{root}")
    rep = run(root, args.check, args.strict)
    print(f"胶囊 {len(rep.capsules)} 个，Skill {len(managed_skills(rep.capsules, rep.shared))} 个")
    return 0 if print_report(rep, args.check) else 1


if __name__ == "__main__":
    sys.exit(main())
