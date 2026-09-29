"""格式互转（Spec 13.2，PRD F-TOOL-02）。原文件不动：先复制到临时目录，转换程序只碰副本。

| 转换 | 实现 |
| doc / wps → docx，xls → xlsx，Word → PDF | LibreOffice headless（配置目录放临时目录，用完删除） |
| PDF → Word | 仅限文字版 PDF：pypdfium2 取文字 → 按段落组织 → pandoc 输出 docx，只保留文字和段落 |
| Markdown ↔ Word | pandoc |
| 图片 → PDF | Pillow |

结果放在原文件旁的"转换结果"文件夹；同名已存在时改名为"原名(2)"，不覆盖。
"""
from __future__ import annotations

import html
import re
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
    profile = (work / "lo_profile").as_uri()
    outdir = work / "out"
    outdir.mkdir()
    _run([str(_soffice()), "--headless", "--norestore", f"-env:UserInstallation={profile}",
          "--convert-to", fmt, "--outdir", str(outdir), str(copy)], cwd=work)
    produced = outdir / f"{copy.stem}.{fmt.split(':')[0]}"
    if not produced.is_file():
        raise ConvertError("转换失败，文件可能已损坏或加密。")
    return produced


def pdf_paragraphs(pdf: Path) -> list[str]:
    """文字版 PDF → 段落列表。行尾是句末标点或明显短于常见行宽时断段；页与页之间断段。"""
    import pypdfium2 as pdfium
    try:
        doc = pdfium.PdfDocument(str(pdf))
    except pdfium.PdfiumError:
        raise ConvertError("PDF 无法打开，可能已损坏或加密。") from None
    pages = [doc[i].get_textpage().get_text_range() for i in range(len(doc))]
    doc.close()
    if not pages or all(len(re.sub(r"\s", "", t)) < 30 for t in pages):
        raise ConvertError("这是扫描件（没有文字层），不在 PDF 转 Word 的范围内。")
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
    return paras


def convert_file(kind: str, src: Path) -> Path:
    k = BY_KEY[kind]
    src = Path(src)
    if src.suffix.lower() not in k.inputs:
        raise ConvertError(f"{src.name} 不是这种转换能处理的格式（{'、'.join(k.inputs)}）。")
    if not src.is_file():
        raise ConvertError(f"{src.name} 不存在或无法读取。")
    target = unique_target(src, k.output)
    work = Path(tempfile.mkdtemp(prefix="lawbench-convert-"))
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
            body = "".join(f"<p>{html.escape(p)}</p>\n" for p in pdf_paragraphs(copy))
            out = work / "out.docx"
            _run([str(_pandoc()), "-f", "html", "-t", "docx", "-o", str(out)], cwd=work,
                 stdin=body.encode("utf-8"))
        elif kind == "md2docx":
            out = work / "out.docx"
            _run([str(_pandoc()), str(copy), "-f", "markdown", "-t", "docx", "-o", str(out)], cwd=work)
        elif kind == "docx2md":
            out = work / "out.md"
            _run([str(_pandoc()), str(copy), "-f", "docx", "-t", "gfm", "--wrap=none", "-o", str(out)], cwd=work)
        elif kind == "img2pdf":
            out = work / "out.pdf"
            _image_to_pdf(copy, out)
        else:
            raise ConvertError("未知的转换类型。")
        shutil.move(str(out), target)
        return target
    finally:
        shutil.rmtree(work, ignore_errors=True)
        try:
            target.parent.rmdir()                     # 失败时不留空的"转换结果"文件夹
        except OSError:
            pass


def _image_to_pdf(src: Path, out: Path) -> None:
    from PIL import Image, UnidentifiedImageError
    try:
        with Image.open(src) as im:
            frames = []
            for i in range(getattr(im, "n_frames", 1)):    # 多页 TIFF 每页一页
                im.seek(i)
                frames.append(im.convert("RGB"))
    except (UnidentifiedImageError, OSError):
        raise ConvertError("图片无法打开，可能已损坏。") from None
    frames[0].save(out, "PDF", save_all=True, append_images=frames[1:], resolution=150)


def convert_many(kind: str, files: list[Path], progress: Callable[[int, int], None] | None = None):
    """批量；单个文件失败不影响其他文件。返回 [(源文件, 结果路径或中文原因)]。"""
    out = []
    for i, f in enumerate(files, 1):
        try:
            r: Path | str = convert_file(kind, Path(f))
        except ConvertError as e:
            r = str(e)
        out.append((Path(f), r))
        if progress:
            progress(i, len(files))
    return out
