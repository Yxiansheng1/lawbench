"""路径闸门（Spec 4.2）：每类越界都必须被拒绝，正常路径必须放行。"""
from __future__ import annotations

import os
import pathlib

import pytest

from lawbench import logs
from lawbench.case import gate
from lawbench.errors import ApiError

from conftest import IS_WIN, make_junction, try_symlink

win_only = pytest.mark.skipif(not IS_WIN, reason="junction / 盘符只在 Windows 上有")


@pytest.fixture
def case(tmp_path):
    """一个登记过的案件根目录 + 一个案件外的秘密文件。"""
    root = tmp_path / "案件甲"
    (root / "证据").mkdir(parents=True)
    (root / "证据" / "借条.txt").write_text("LBTEST-IOU", encoding="utf-8")
    (root / "工作区" / "材料").mkdir(parents=True)
    (root / "成果").mkdir()
    (root / ".dsh" / "skills").mkdir(parents=True)
    outside = tmp_path / "案件外"
    outside.mkdir()
    (outside / "secret.txt").write_text("LBTEST-SECRET", encoding="utf-8")
    sibling = tmp_path / "案件甲-evil"
    sibling.mkdir()
    (sibling / "x.txt").write_text("x", encoding="utf-8")
    logs.setup(tmp_path / "appdata")
    return gate.check_root(str(root)), outside, tmp_path


def denied(fn, *a, code="OUT_OF_CASE"):
    with pytest.raises(ApiError) as ei:
        fn(*a)
    assert ei.value.code == code, ei.value.code
    return ei.value


# ---------- 规则 2：AI 参数的形状 ----------

BAD_AI_PATHS = [
    "../案件外/secret.txt",                 # 上跳
    "证据/../../案件外/secret.txt",         # 中间上跳
    "..\\案件外\\secret.txt",               # 反斜杠上跳
    "证据/.../x",                           # Windows 去尾点后等于 ..
    "证据/.. /x",                           # 去尾空格后等于 ..
    "C:\\Windows\\win.ini",                 # 绝对路径带盘符
    "C:Windows\\win.ini",                   # 盘符相对路径
    "/etc/passwd",                          # 根路径
    "\\Windows\\win.ini",                   # 反斜杠根路径
    "\\\\server\\share\\x.txt",             # UNC
    "//server/share/x.txt",                 # UNC 正斜杠
    "证据/借条.txt:secret",                  # 备用数据流
    "证据/借条\x00.txt",                     # NUL
    "工作区/材料/index.json",                # 保留目录 工作区
    "成果/意见书.md",                        # 保留目录 成果
    "工作区./材料/index.json",               # 保留目录 + 尾点
    "成果 /意见书.md",                       # 保留目录 + 尾空格
    "./工作区/case.db",                      # ./ 前缀
    ".dsh/skills/evil/SKILL.md",            # 以 . 开头
    ".DSH/skills/evil/SKILL.md",            # 大小写变体
    "a" * 300 + ".txt",                     # 超长名
    "/".join(["b" * 200] * 6),              # 超长路径
    "",                                     # 空
    "   ",                                  # 空白
]


@pytest.mark.parametrize("rel", BAD_AI_PATHS, ids=range(len(BAD_AI_PATHS)))
def test_ai_path_rejected(case, rel):
    root, _, _ = case
    denied(gate.resolve_read, root, rel)


def test_ai_path_ok(case):
    root, _, _ = case
    p = gate.resolve_read(root, "证据/借条.txt")
    assert p.read_text(encoding="utf-8") == "LBTEST-IOU"
    assert gate.resolve_read(root, "证据\\借条.txt") == p  # 反斜杠等价
    assert gate.resolve_read(root, "成果汇总.pdf").name == "成果汇总.pdf"  # 只有整级目录名是"成果"才算保留目录


# ---------- 规则 3：不跟随链接 ----------

@win_only
def test_junction_to_outside(case):
    root, outside, _ = case
    make_junction(pathlib.Path(root) / "证据" / "jn", outside)
    denied(gate.resolve_read, root, "证据/jn/secret.txt")
    denied(gate.resolve_read, root, "证据/jn")


@win_only
def test_junction_to_inside_also_rejected(case):
    """链接指向案件内也拒绝：不跟随链接是无条件的。"""
    root, _, _ = case
    make_junction(pathlib.Path(root) / "别名", pathlib.Path(root) / "证据")
    denied(gate.resolve_read, root, "别名/借条.txt")


@win_only
def test_junction_into_work_dir(case):
    """原件区里放一个指向 工作区 的 junction，绕过"不能以 工作区 开头"。"""
    root, _, _ = case
    make_junction(pathlib.Path(root) / "w", pathlib.Path(root) / "工作区")
    denied(gate.resolve_read, root, "w/材料")


def test_symlink_file_to_outside(case):
    root, outside, _ = case
    if not try_symlink(pathlib.Path(root) / "证据" / "link.txt", outside / "secret.txt"):
        pytest.skip("本机账号没有创建符号链接的权限（开发者模式未开）")
    denied(gate.resolve_read, root, "证据/link.txt")


def test_symlink_dir_to_outside(case):
    root, outside, _ = case
    if not try_symlink(pathlib.Path(root) / "sl", outside, is_dir=True):
        pytest.skip("本机账号没有创建符号链接的权限（开发者模式未开）")
    denied(gate.resolve_read, root, "sl/secret.txt")


@win_only
def test_root_replaced_by_junction_after_registration(case, tmp_path):
    root, outside, _ = case
    moved = tmp_path / "moved"
    os.rename(root, moved)
    make_junction(pathlib.Path(root), outside)
    denied(gate.resolve_read, root, "secret.txt")
    denied(gate.write_bytes, root, "工作区/x.txt", b"x")


# ---------- 规则 4：最终校验，大小写 ----------

def test_is_within_prefix_and_case():
    base = "C:\\T\\案件甲" if IS_WIN else "/t/案件甲"
    sep = "\\" if IS_WIN else "/"
    assert not gate.is_within(base, base + "-evil" + sep + "x.txt")   # 前缀相同的兄弟目录
    assert not gate.is_within(base, base)                              # 根本身不算
    assert gate.is_within(base, base + sep + "证据" + sep + "x")
    if IS_WIN:
        assert gate.is_within("C:\\T\\Case", "c:\\t\\CASE\\x.txt")     # Windows 大小写不敏感
        assert not gate.is_within("C:\\T\\Case", "c:\\t\\CASE-evil\\x.txt")


# ---------- 规则 5：写权限 ----------

@pytest.mark.parametrize("rel", ["证据/新文件.txt", "新文件.txt", "工作区/../证据/x.txt", "工作区x/a.txt",
                                 "工作区./a.txt", ".dsh/a.txt", "../案件外/x.txt", "C:\\x.txt"])
def test_write_outside_work_rejected(case, rel):
    root, _, _ = case
    denied(gate.write_bytes, root, rel, b"x")


def test_write_inside_work_ok(case):
    root, _, _ = case
    p = gate.write_bytes(root, "工作区/临时/a/b.txt", b"ok")
    assert p.read_bytes() == b"ok"
    p2 = gate.write_bytes(root, "成果/索引.json", b"{}")
    assert p2.read_bytes() == b"{}"
    assert not list(pathlib.Path(root, "工作区", "临时", "a").glob(".~lb-*"))  # 临时文件已原子替换


@win_only
def test_write_through_junction_rejected(case):
    root, outside, _ = case
    make_junction(pathlib.Path(root) / "工作区" / "jn", outside)
    denied(gate.write_bytes, root, "工作区/jn/evil.txt", b"x")
    assert not (outside / "evil.txt").exists()


def test_mkdir_original_only_missing(case):
    root, _, _ = case
    assert gate.mkdir_original(root, "03一审/我方证据") is True
    assert gate.mkdir_original(root, "证据") is False  # 已存在：不动
    denied(gate.mkdir_original, root, "工作区/x")
    denied(gate.mkdir_original, root, "../x")


# ---------- 规则 1：根目录 ----------

@win_only
def test_root_is_junction(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    make_junction(tmp_path / "jroot", real)
    denied(gate.check_root, str(tmp_path / "jroot"), code="CASE_ROOT_IS_LINK")


def test_root_symlink(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    if not try_symlink(tmp_path / "sroot", real, is_dir=True):
        pytest.skip("本机账号没有创建符号链接的权限（开发者模式未开）")
    denied(gate.check_root, str(tmp_path / "sroot"), code="CASE_ROOT_IS_LINK")


@pytest.mark.parametrize("bad", ["相对/路径", "", "C:", "\x00"])
def test_root_bad_shape(bad):
    denied(gate.check_root, bad, code="INVALID_ARGUMENT")


def test_root_missing(tmp_path):
    denied(gate.check_root, str(tmp_path / "不存在"), code="INVALID_ARGUMENT")


# ---------- 云同步目录（SEC-14） ----------

def test_sync_env_onedrive(tmp_path, monkeypatch):
    od = tmp_path / "MyDrive"
    (od / "案件").mkdir(parents=True)
    monkeypatch.setenv("OneDrive", str(od))
    denied(gate.check_root, str(od / "案件"), code="CASE_IN_SYNC_FOLDER")
    denied(gate.check_root, str(od), code="CASE_IN_SYNC_FOLDER")


@pytest.mark.parametrize("var", ["OneDriveCommercial", "OneDriveConsumer"])
def test_sync_env_other_vars(tmp_path, monkeypatch, var):
    od = tmp_path / "Biz"
    (od / "a").mkdir(parents=True)
    monkeypatch.setenv(var, str(od))
    denied(gate.check_root, str(od / "a"), code="CASE_IN_SYNC_FOLDER")


def test_sync_registry_userfolder(tmp_path, monkeypatch):
    uf = tmp_path / "Corp"
    (uf / "a").mkdir(parents=True)
    monkeypatch.setattr(gate, "_registry_onedrive_folders", lambda: [str(uf)])
    denied(gate.check_root, str(uf / "a"), code="CASE_IN_SYNC_FOLDER")


@pytest.mark.parametrize("name", ["坚果云", "Nutstore", "BaiduNetdisk", "百度网盘", "dropbox", "Google Drive",
                                  "iCloudDrive", "WPS云盘", "my onedrive files"])
def test_sync_by_name(tmp_path, name):
    p = tmp_path / name / "案件"
    p.mkdir(parents=True)
    denied(gate.check_root, str(p), code="CASE_IN_SYNC_FOLDER")


def test_sync_sibling_not_matched(tmp_path, monkeypatch):
    od = tmp_path / "Drive"
    od.mkdir()
    ok = tmp_path / "Drive2"
    ok.mkdir()
    monkeypatch.setenv("OneDrive", str(od))
    assert gate.check_root(str(ok))


# ---------- 规则 6：拒绝时日志不记参数 ----------

def test_denied_log_has_no_argument(case):
    root, _, tmp_path = case
    for rel in ["../案件外/secret.txt", "证据/借条.txt:LBSECRETNAME", "工作区/LBSECRETNAME"]:
        with pytest.raises(ApiError):
            gate.resolve_read(root, rel)
    logs.close()
    text = "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "appdata" / "logs").glob("*"))
    assert "denied" in text
    for bad in ["案件外", "secret", "LBSECRETNAME", "借条", str(tmp_path)]:
        assert bad not in text
