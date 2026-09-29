"""格式互转（Spec 13.2，PRD F-TOOL-02）。原文件不动：先复制到临时目录，转换程序只碰副本。

| 转换 | 实现 |
| doc / wps → docx，xls → xlsx，Word → PDF | LibreOffice headless（配置目录放临时目录，用完删除） |
| PDF → Word | 仅限文字版 PDF：pypdfium2 取文字 → 按段落组织 → pandoc 输出 docx，只保留文字和段落 |
| Markdown ↔ Word | pandoc |
| 图片 → PDF | Pillow |

结果放在原文件旁的"转换结果"文件夹；同名已存在时改名为"原名(2)"，不覆盖。
不联网：pandoc 一律加 --sandbox（不取远程图片等资源）；LibreOffice 在本次的配置目录里设
BlockUntrustedRefererLinks=true（不下载文档里以外部链接引用的图片）。
"""
from __future__ import annotations

import html
import os
import re
import time
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

try:
    from . import finder
except ImportError:          # 直接运行或打包后的入口
    import finder  # type: ignore

OUT_DIR_NAME = "转换结果"
TIMEOUT_S = 120
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PDF_TO_WORD_NOTE = "PDF 转 Word 只保留文字和段落，不保留版式；扫描件（没有文字层）不能转换。"
IMAGES_NOTE = "Markdown 与 Word 互转不保留图片。"
TEMP_PREFIX = "lawbench-convert-"
STALE_S = 600
INTERNAL = "处理失败（程序内部错误），其余文件不受影响。"
LO_REGISTRY = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
    '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
    '<prop oor:name="BlockUntrustedRefererLinks" oor:op="fuse"><value>true</value></prop></item>\n'
    # 文档里的链接一律不更新（Writer、Calc）
    '<item oor:path="/org.openoffice.Office.Writer/Content/Update"><prop oor:name="Link" oor:op="fuse">'
    '<value>2</value></prop></item>\n'
    '<item oor:path="/org.openoffice.Office.Calc/Content/Update"><prop oor:name="Link" oor:op="fuse">'
    '<value>2</value></prop></item>\n'
    # 兜底：万一还有组件要联网，走一个连不上的本机代理（端口 9），本机地址也不例外
    '<item oor:path="/org.openoffice.Inet/Settings"><prop oor:name="ooInetProxyType" oor:op="fuse">'
    '<value>1</value></prop></item>\n'
    '<item oor:path="/org.openoffice.Inet/Settings"><prop oor:name="ooInetHTTPProxyName" oor:op="fuse">'
    '<value>127.0.0.1</value></prop></item>\n'
    '<item oor:path="/org.openoffice.Inet/Settings"><prop oor:name="ooInetHTTPProxyPort" oor:op="fuse">'
    '<value>9</value></prop></item>\n'
    '<item oor:path="/org.openoffice.Inet/Settings"><prop oor:name="ooInetHTTPSProxyName" oor:op="fuse">'
    '<value>127.0.0.1</value></prop></item>\n'
    '<item oor:path="/org.openoffice.Inet/Settings"><prop oor:name="ooInetHTTPSProxyPort" oor:op="fuse">'
    '<value>9</value></prop></item>\n'
    '<item oor:path="/org.openoffice.Inet/Settings"><prop oor:name="ooInetNoProxy" oor:op="fuse">'
    '<value></value></prop></item>\n'
    '</oor:items>\n'
)


class ConvertError(Exception):
    """给用户看的中文原因。"""


@dataclass(frozen=True)
class Kind:
    key: str
    label: str
    inputs: tuple[str, ...]
    output: str


KINDS = [
    Kind("doc2docx", "doc / wps → docx", (".doc", ".wps"), ".docx"),
    Kind("xls2xlsx", "xls → xlsx", (".xls",), ".xlsx"),
    Kind("word2pdf", "Word → PDF", (".docx", ".doc", ".wps"), ".pdf"),
    Kind("pdf2docx", "PDF → Word（只保留文字和段落）", (".pdf",), ".docx"),
    Kind("md2docx", "Markdown → Word", (".md", ".markdown"), ".docx"),
    Kind("docx2md", "Word → Markdown", (".docx",), ".md"),
    Kind("img2pdf", "图片 → PDF", (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"), ".pdf"),
]
BY_KEY = {k.key: k for k in KINDS}


def unique_target(src: Path, ext: str) -> Path:
    out_dir = src.parent / OUT_DIR_NAME
    out_dir.mkdir(exist_ok=True)
    p = out_dir / f"{src.stem}{ext}"
    n = 2
    while p.exists():
        p = out_dir / f"{src.stem}({n}){ext}"
        n += 1
    return p


def kill_tree(pid: int) -> None:
    """结束本次启动的进程及其子进程（soffice.exe 会再启动 soffice.bin）；只按进程号，不动别的进程。"""
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)


def _run(cmd: list[str], cwd: Path, stdin: bytes | None = None) -> None:
    """运行转换程序。只用导出接口，不调用打印；卡住（如打印机弹窗）时到 TIMEOUT_S 结束整棵进程树。"""
    try:
        proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
    except OSError:
        raise ConvertError("转换程序无法启动。") from None
    try:
        proc.communicate(input=stdin, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        kill_tree(proc.pid)
        try:
            proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:   # 有子进程逃出进程树、还占着输出管道：不再等
            proc.kill()
        raise ConvertError(f"转换超时（{TIMEOUT_S} 秒），已结束转换程序。文件可能过大或已损坏，"
                           "或转换程序弹出了窗口（例如等待打印机连接）。") from None
    if proc.returncode != 0:
        raise ConvertError("转换失败，文件可能已损坏或加密。")


def _soffice() -> Path:
    p = finder.find_soffice()
    if not p:
        raise ConvertError(finder.MISSING["soffice"])
    return p


def _pandoc() -> Path:
    p = finder.find_pandoc()
    if not p:
        raise ConvertError(finder.MISSING["pandoc"])
    return p


def _libreoffice(copy: Path, fmt: str, work: Path) -> Path:
    user = work / "lo_profile" / "user"
    user.mkdir(parents=True)
    (user / "registrymodifications.xcu").write_text(LO_REGISTRY, encoding="utf-8")   # 不取外部链接的图片
    profile = (work / "lo_profile").as_uri()
    outdir = work / "out"
    outdir.mkdir()
    _run([str(_soffice()), "--headless", "--norestore", f"-env:UserInstallation={profile}",
          "--convert-to", fmt, "--outdir", str(outdir), str(copy)], cwd=work)
    produced = outdir / f"{copy.stem}.{fmt.split(':')[0]}"
    if not produced.is_file():
        raise ConvertError("转换失败，文件可能已损坏或加密。")
    return produced


def pdf_paragraphs(pdf: Path) -> tuple[list[str], list[int]]:
    """文字版 PDF → (段落列表, 没有文字层的页号)。行尾是句末标点或明显短于常见行宽时断段；页与页之间断段。"""
    import pypdfium2 as pdfium
    try:
        doc = pdfium.PdfDocument(str(pdf))
    except pdfium.PdfiumError:
        raise ConvertError("PDF 无法打开，可能已损坏或加密。") from None
    pages = [doc[i].get_textpage().get_text_range() for i in range(len(doc))]
    doc.close()
    if not pages or all(len(re.sub(r"\s", "", t)) < 30 for t in pages):
        raise ConvertError("这是扫描件（没有文字层），不在 PDF 转 Word 的范围内。")
    scans = [i for i, t in enumerate(pages, 1) if len(re.sub(r"\s", "", t)) < 30]
    paras: list[str] = []
    for text in pages:
        lines = [ln.strip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
        widths = sorted(len(ln) for ln in lines if ln)
        typical = widths[int(len(widths) * 0.8)] if widths else 0
        cur = ""
        for ln in lines:
            if not ln:
                if cur:
                    paras.append(cur)
                    cur = ""
                continue
            cur += ln
            if ln[-1] in "。！？；：:!?”」" or len(ln) < 0.7 * typical:
                paras.append(cur)
                cur = ""
        if cur:
            paras.append(cur)
    return paras, scans


def convert_file(kind: str, src: Path) -> Path:
    return convert_file_ex(kind, src)[0]


def convert_file_ex(kind: str, src: Path) -> tuple[Path, list[str]]:
    """返回 (结果路径, 给用户的提示)。"""
    k = BY_KEY[kind]
    notes: list[str] = []
    src = Path(src)
    if src.suffix.lower() not in k.inputs:
        raise ConvertError(f"{src.name} 不是这种转换能处理的格式（{'、'.join(k.inputs)}）。")
    if not src.is_file():
        raise ConvertError(f"{src.name} 不存在或无法读取。")
    target = unique_target(src, k.output)
    work = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
    try:
        copy = work / f"src{src.suffix.lower()}"     # 副本用 ASCII 名，避免转换程序处理中文路径出问题
        shutil.copyfile(src, copy)
        if kind == "doc2docx":
            out = _libreoffice(copy, "docx", work)
        elif kind == "xls2xlsx":
            out = _libreoffice(copy, "xlsx", work)
        elif kind == "word2pdf":
            out = _libreoffice(copy, "pdf", work)
        elif kind == "pdf2docx":
            paras, scans = pdf_paragraphs(copy)
            notes += [f"第 {n} 页是扫描页，没有转出文字" for n in scans]
            body = "".join(f"<p>{html.escape(p)}</p>\n" for p in paras)
            out = work / "out.docx"
            _run([str(_pandoc()), "--sandbox", "-f", "html", "-t", "docx", "-o", str(out)], cwd=work,
                 stdin=body.encode("utf-8"))
        elif kind == "md2docx":
            out = work / "out.docx"
            _run([str(_pandoc()), "--sandbox", str(copy), "-f", "markdown", "-t", "docx", "-o", str(out)], cwd=work)
        elif kind == "docx2md":
            out = work / "out.md"
            _run([str(_pandoc()), "--sandbox", str(copy), "-f", "docx", "-t", "gfm", "--wrap=none", "-o", str(out)],
                 cwd=work)
        elif kind == "img2pdf":
            out = work / "out.pdf"
            _image_to_pdf(copy, out)
        else:
            raise ConvertError("未知的转换类型。")
        shutil.move(str(out), target)
        return target, notes
    finally:
        _remove_workdir(work)
        try:
            target.parent.rmdir()                     # 失败时不留空的"转换结果"文件夹
        except OSError:
            pass


LONG_PREFIX = "\\\\?\\"      # Windows 扩展长度路径前缀 \\?\


def _remove_workdir(work: Path) -> None:
    """删工作目录。LibreOffice 的配置目录层级很深，临时目录路径稍长就超过 Windows 260 字符上限，
    所以用长路径前缀删；LibreOffice 退出后短时间内还可能占着文件，最多重试 10 秒。"""
    target = LONG_PREFIX + str(work.resolve()) if os.name == "nt" else str(work)
    for _ in range(40):
        shutil.rmtree(target, ignore_errors=True)
        if not work.exists():
            return
        time.sleep(0.25)


def _image_to_pdf(src: Path, out: Path) -> None:
    from PIL import Image, UnidentifiedImageError
    try:
        with Image.open(src) as im:
            frames = []
            for i in range(getattr(im, "n_frames", 1)):    # 多页 TIFF 每页一页
                im.seek(i)
                frames.append(im.convert("RGB"))
    except Image.DecompressionBombError:
        raise ConvertError("图片过大，无法转换。") from None
    except (UnidentifiedImageError, OSError):
        raise ConvertError("图片无法打开，可能已损坏。") from None
    frames[0].save(out, "PDF", save_all=True, append_images=frames[1:], resolution=150)


def cleanup_stale(max_age_s: float = STALE_S) -> int:
    """启动时清理：系统临时目录顶层、本工具前缀、超过 10 分钟的目录（上次转换中途被强行关掉留下的）。
    不跟随链接和联接，不碰别的文件。"""
    n = 0
    now = time.time()
    for p in Path(tempfile.gettempdir()).glob(TEMP_PREFIX + "*"):
        try:
            if p.is_symlink() or os.path.isjunction(p) or not p.is_dir():
                continue
            if now - p.stat().st_mtime < max_age_s:
                continue
            shutil.rmtree(p)
            n += 1
        except OSError:
            pass
    return n


def convert_many(kind: str, files: list[Path], progress: Callable[[int, int], None] | None = None):
    """批量；单个文件失败（含意外错误）不影响其他文件。返回 [(源文件, 结果路径或中文原因, 提示列表)]。"""
    out = []
    for i, f in enumerate(files, 1):
        notes: list[str] = []
        try:
            r, notes = convert_file_ex(kind, Path(f))
        except ConvertError as e:
            r = str(e)
        except Exception:  # noqa: BLE001  不把堆栈给用户看
            r = INTERNAL
        out.append((Path(f), r, notes))
        if progress:
            progress(i, len(files))
    return out
