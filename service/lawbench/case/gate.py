"""路径闸门（Spec 4.2）。所有读写案件文件的代码都必须经过这里，没有其他写文件的途径。

六条规则：
1. 案件根目录只从注册表取，realpath 保存为 ROOT；根目录本身是链接或 junction 拒绝登记（CASE_ROOT_IS_LINK）；
   位于云同步目录拒绝（CASE_IN_SYNC_FOLDER，SEC-14）。
2. AI 传入的参数：不能是绝对路径或带盘符，不能含 ..，不能以 .、工作区、成果 开头。
3. 不跟随链接：拼接后的路径及其每一级父目录 lstat，只要有一级是符号链接或 reparse point 就拒绝。
4. 最终校验：realpath 必须以 ROOT + 分隔符开头；Windows 下比较前统一大小写。
5. 写权限：只允许写 工作区/ 和 成果/；原件区只允许界面触发的"补建空文件夹"和"导入复制（不覆盖）"。
6. 拒绝时返回"超出当前案件范围"（OUT_OF_CASE），本机日志只记操作名和原因，不记参数内容。
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import stat
import uuid

from .. import logs
from ..contracts import atomic_write_bytes
from ..errors import ApiError

WORK = "工作区"
OUTPUT = "成果"
WRITABLE_TOP = (WORK, OUTPUT)

# 云同步目录：路径中任一级目录名包含这些字样即视为同步目录（Spec 4.2 第 1 条；列表可补充）
SYNC_NAME_MARKERS: list[str] = [
    "OneDrive", "坚果云", "Nutstore", "BaiduNetdisk", "百度网盘", "Dropbox", "Google Drive",
    "iCloudDrive", "WPS云盘",
]
SYNC_ENV_VARS = ("OneDrive", "OneDriveCommercial", "OneDriveConsumer")

DEVICE_NAMES = frozenset(
    ["con", "prn", "aux", "nul", "conin$", "conout$"]
    + [f"{d}{n}" for d in ("com", "lpt") for n in [*"0123456789", "¹", "²", "³"]])

MAX_COMPONENT = 255
MAX_REL = 1024

_FILE_ATTRIBUTE_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_DRIVE = re.compile(r"^[A-Za-z]:")
_BAD_CHARS = re.compile(r'[\x00-\x1f<>:"|?*]')


class GateError(ApiError):
    def __init__(self, code: str = "OUT_OF_CASE", reason: str = ""):
        super().__init__(code, reason)


def _deny(op: str, reason: str, code: str = "OUT_OF_CASE"):
    logs.event("gate", op, status="denied", error=f"{code}:{reason}")
    return GateError(code, reason)


# ---------- 基础判断 ----------

def is_link(path: str | os.PathLike) -> bool:
    """lstat 判断符号链接或 reparse point（junction 在内）。不存在返回 False。"""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def _norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(p))


def is_within(root: str, target: str) -> bool:
    """target 是否在 root 之内（不含 root 本身）。Windows 下大小写不敏感。"""
    r = _norm(root)
    t = _norm(target)
    return t.startswith(r.rstrip(os.sep) + os.sep)


def _registry_onedrive_folders() -> list[str]:
    """HKCU\\Software\\Microsoft\\OneDrive\\Accounts\\*\\UserFolder。"""
    try:
        import winreg
    except ImportError:
        return []
    out: list[str] = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\OneDrive\Accounts") as acc:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(acc, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(acc, sub) as k:
                        val, _ = winreg.QueryValueEx(k, "UserFolder")
                        if val:
                            out.append(str(val))
                except OSError:
                    continue
    except OSError:
        return []
    return out


def sync_folder_roots() -> list[str]:
    roots = [os.environ[v] for v in SYNC_ENV_VARS if os.environ.get(v)]
    roots += _registry_onedrive_folders()
    return roots


def in_sync_folder(path: str) -> bool:
    for base in sync_folder_roots():
        if _norm(path) == _norm(base) or is_within(base, path):
            return True
    parts = pathlib.PureWindowsPath(path).parts if os.name == "nt" else pathlib.PurePath(path).parts
    markers = [m.casefold() for m in SYNC_NAME_MARKERS]
    for part in parts:
        low = part.casefold()
        if any(m in low for m in markers):
            return True
    return False


# ---------- 规则 1：案件根目录 ----------

def strip_long_prefix(path: str) -> str:
    """去掉 \\\\?\\ 前缀：\\\\?\\C:\\x → C:\\x，\\\\?\\UNC\\s\\x → \\\\s\\x。"""
    if path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path[8:]
    if path.startswith("\\\\?\\"):
        return path[4:]
    return path


def check_root(path: str, op: str = "case_open", appdata: str | os.PathLike | None = None) -> str:
    """校验律师选的案件文件夹，返回 realpath（即 ROOT）。

    拒绝：链接或 junction（CASE_ROOT_IS_LINK）；云同步目录（CASE_IN_SYNC_FOLDER）；
    盘符根目录、包含本软件应用数据目录的文件夹（INVALID_ARGUMENT，Spec 4.2 第 1 条）。
    """
    if not isinstance(path, str) or not path or "\x00" in path:
        raise _deny(op, "root_not_abs", "INVALID_ARGUMENT")
    path = strip_long_prefix(path)
    if not os.path.isabs(path):
        raise _deny(op, "root_not_abs", "INVALID_ARGUMENT")
    p = os.path.normpath(path)
    if is_link(p):
        raise _deny(op, "root_is_link", "CASE_ROOT_IS_LINK")
    if not os.path.isdir(p):
        raise _deny(op, "root_not_dir", "INVALID_ARGUMENT")
    real = os.path.normpath(strip_long_prefix(os.path.realpath(p)))
    if os.path.splitdrive(real)[1] in ("", os.sep):
        raise _deny(op, "root_is_drive", "INVALID_ARGUMENT")
    if appdata is not None:
        ad = os.path.realpath(appdata)
        if _norm(ad) == _norm(real) or is_within(real, ad):
            raise _deny(op, "root_has_appdata", "INVALID_ARGUMENT")
    if in_sync_folder(p) or in_sync_folder(real):
        raise _deny(op, "sync_folder", "CASE_IN_SYNC_FOLDER")
    return real


def check_office_dir(path: str, op: str = "settings_put") -> None:
    """设置中的日常办公文件夹：按云同步目录规则校验（formats.md 1.2）。"""
    if not isinstance(path, str) or not path or "\x00" in path or not os.path.isabs(path):
        raise _deny(op, "office_not_abs", "INVALID_ARGUMENT")
    p = os.path.normpath(path)
    if in_sync_folder(p) or (os.path.exists(p) and in_sync_folder(os.path.realpath(p))):
        raise _deny(op, "sync_folder", "CASE_IN_SYNC_FOLDER")


# ---------- 规则 2：相对路径的形状 ----------

def _split_rel(rel: str, op: str) -> list[str]:
    if not isinstance(rel, str) or not rel.strip():
        raise _deny(op, "empty")
    if len(rel) > MAX_REL:
        raise _deny(op, "too_long")
    if rel.startswith(("/", "\\")) or _DRIVE.match(rel) or os.path.isabs(rel):
        raise _deny(op, "absolute")
    if _BAD_CHARS.search(rel):  # 含 ":"：盘符、备用数据流；控制字符；Windows 保留字符
        raise _deny(op, "bad_char")
    parts = [p for p in re.split(r"[\\/]+", rel) if p not in ("", ".")]
    if not parts:
        raise _deny(op, "empty")
    for p in parts:
        # Windows 会去掉名字末尾的点和空格："..." "工作区." 与 ".." "工作区" 指向同一处
        if p.rstrip(" .") in ("", "..") or p == "..":
            raise _deny(op, "dotdot")
        if len(p) > MAX_COMPONENT:
            raise _deny(op, "too_long")
        if is_device_name(p):
            raise _deny(op, "device_name")
    return parts


def is_device_name(name: str) -> bool:
    """Windows 设备名：去尾部点和空格、取第一个 . 之前的部分，不分大小写比对（NUL.txt、con 同样算）。"""
    base = name.rstrip(" .").split(".")[0].rstrip(" ").casefold()
    return base in DEVICE_NAMES


def _top(parts: list[str]) -> str:
    return parts[0].rstrip(" .").casefold()


def check_ai_rel(rel: str, op: str = "ai") -> list[str]:
    """AI 传入的材料相对路径（规则 2）。"""
    parts = _split_rel(rel, op)
    first = parts[0]
    if first.startswith(".") or _top(parts) in (WORK.casefold(), OUTPUT.casefold()):
        raise _deny(op, "reserved_top")
    return parts


# ---------- 规则 3、4：不跟随链接 + 最终校验 ----------

def _resolve(root: str, parts: list[str], op: str) -> pathlib.Path:
    if is_link(root):
        raise _deny(op, "root_is_link")
    cur = root
    for p in parts:
        cur = os.path.join(cur, p)
        try:
            st = os.lstat(cur)
        except FileNotFoundError:
            break  # 其余各级尚不存在，不可能是链接
        except OSError:
            raise _deny(op, "lstat_error")
        if stat.S_ISLNK(st.st_mode) or getattr(st, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT:
            raise _deny(op, "link")
    target = os.path.join(root, *parts)
    try:
        real = os.path.realpath(target)
    except OSError:
        raise _deny(op, "realpath_error")
    if not is_within(root, real):
        raise _deny(op, "escape")
    return pathlib.Path(target)


def _relpath(path: str | os.PathLike, root: str, op: str) -> str:
    try:
        return os.path.relpath(path, root)
    except ValueError:  # 不同盘符、设备路径等：一律按越界拒绝
        raise _deny(op, "relpath_error")


def _real_top(root: str, path: pathlib.Path, op: str = "internal") -> str:
    rel = _relpath(os.path.realpath(path), root, op)
    return pathlib.Path(rel).parts[0].casefold()


def resolve_read(root: str, rel: str, op: str = "ai_read") -> pathlib.Path:
    """AI 读原件区的材料：规则 2 + 3 + 4。"""
    parts = check_ai_rel(rel, op)
    path = _resolve(root, parts, op)
    top = _real_top(root, path, op)  # 8.3 短名等别名，解析后仍落在保留目录也拒绝
    if top.startswith(".") or top in (WORK.casefold(), OUTPUT.casefold()):
        raise _deny(op, "reserved_top")
    return path


def resolve_internal(root: str, rel: str, op: str = "internal") -> pathlib.Path:
    """服务内部读 工作区/、成果/ 下的文件（规则 3 + 4；形状同规则 2，但允许保留目录开头）。"""
    parts = _split_rel(rel, op)
    return _resolve(root, parts, op)


def resolve_write(root: str, rel: str, op: str = "write") -> pathlib.Path:
    """写入：只允许 工作区/ 和 成果/（规则 5）。"""
    parts = _split_rel(rel, op)
    if parts[0] not in WRITABLE_TOP:
        raise _deny(op, "write_outside_work")
    path = _resolve(root, parts, op)
    if _real_top(root, path, op) not in (WORK.casefold(), OUTPUT.casefold()):
        raise _deny(op, "write_outside_work")
    return path


# ---------- 写操作：唯一的写入途径 ----------

def write_bytes(root: str, rel: str, data: bytes, op: str = "write") -> pathlib.Path:
    path = resolve_write(root, rel, op)
    _mkdirs(root, path.parent, op)
    atomic_write_bytes(path, data)
    return path


def mkdir_work(root: str, rel: str, op: str = "write") -> pathlib.Path:
    path = resolve_write(root, rel, op)
    _mkdirs(root, path, op)
    return path


def mkdir_original(root: str, rel: str, op: str = "case_template") -> bool:
    """原件区补建空文件夹（仅 /api/case/open 的 template）。返回是否新建。

    已存在的一级（含链接、junction）一律跳过、不报错、不往里写：某一级已是链接时，它下面的各级也不建。
    """
    parts = check_ai_rel(rel, op)
    cur = root
    for p in parts:
        cur = os.path.join(cur, p)
        if is_link(cur):
            return False
    path = _resolve(root, parts, op)
    if os.path.lexists(path):
        return False
    _mkdirs(root, path, op)
    return True


def copy_original(root: str, rel: str, src: str | os.PathLike, op: str = "import") -> pathlib.Path:
    """原件区新建文件（仅 /api/materials/import）：复制，从不覆盖。目标已存在抛 FileExistsError。"""
    parts = check_ai_rel(rel, op)
    path = _resolve(root, parts, op)
    if os.path.lexists(path):
        raise FileExistsError(rel)
    _mkdirs(root, path.parent, op)
    tmp = path.parent / f".~lb-{uuid.uuid4().hex}.tmp"  # 以 . 开头，扫描原件区时不会当成材料
    try:
        shutil.copy2(src, tmp)
        os.rename(tmp, path)  # Windows 上目标已存在时 rename 失败，不会覆盖
    finally:
        if os.path.lexists(tmp):
            os.unlink(tmp)
    if is_link(path) or not is_within(root, os.path.realpath(path)):
        raise _deny(op, "copy_escape")
    return path


def delete_work_file(root: str, rel: str, op: str = "import") -> None:
    """删除 工作区/ 下的临时文件（导入粘贴的截图、委托材料窗口的下载后用）。原件区不提供删除。"""
    parts = _split_rel(rel, op)
    if parts[0] != WORK:
        raise _deny(op, "delete_outside_work")
    path = _resolve(root, parts, op)
    if _real_top(root, path, op) != WORK.casefold():
        raise _deny(op, "delete_outside_work")
    if os.path.isfile(path):
        os.unlink(path)


def _mkdirs(root: str, path: pathlib.Path, op: str) -> None:
    """逐级新建目录；每新建一级都复查不是链接、仍在 ROOT 内（防止并发替换成 junction）。"""
    rel_parts = pathlib.Path(_relpath(path, root, op)).parts
    cur = root
    for p in rel_parts:
        cur = os.path.join(cur, p)
        if not os.path.lexists(cur):
            os.mkdir(cur)
        if is_link(cur) or not os.path.isdir(cur) or not is_within(root, os.path.realpath(cur)):
            raise _deny(op, "mkdir_escape")
