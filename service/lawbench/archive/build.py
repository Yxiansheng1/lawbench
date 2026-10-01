"""生成归档文件（/api/archive/build；Spec 12.4"生成"第 1–8 步；原版规则 lawyer-archiving 第六、七、八步）。

1. 用界面提交的 confirmed 方案（result 为 null → PLAN_NOT_CONFIRMED），按目录再核一次编号和材料名。
2. 每项材料按编号、项内按方案顺序取原件：PDF 直接用；Word 类按 12.3 转；图片用 Pillow 转；表格等用 LibreOffice。
   中间文件都在 工作区/临时/归档-<随机>/，结束时（成功或失败）整个删掉。
3. 结案报告（generated 项）：模板在就填，不在用临时版式；转 PDF 后放在卷宗里它的编号处。
4. 卷宗：pypdf 按编号合并，缺项跳过、不插空白页，记每项起止页；reportlab 页码层：每页底部先画白色矩形遮住原有
   页码，再居中写"第x页 共x页"（STSong-Light 10 号），逐页叠加。
5. 立卷申请书（只生成 docx）；6. 发票.pdf（"收费发票凭证"一项的材料单独合并一份，不加页码）；
7. 必交项缺失 → 材料缺失情况说明；律师费未结清 → 律师费未结清情况说明；
8. 输出到 成果/归档/<委托人>与<对方当事人>案件归档/（同名已有时 -v2、-v3…，旧的不动），另写 归档目录.md；
   登记到 成果/索引.json（与确认保存共用 export.outputs.index_update；索引只收 md/docx，PDF 不登记）。
原件只读；所有写入经闸门；日志只记元数据。
"""
from __future__ import annotations

import io
import pathlib
import re
import secrets

from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from .. import logs
from ..case import gate
from ..case.task import now_iso
from ..errors import ApiError
from ..export import outputs as eo
from ..ingest.libreoffice import remove_tree
from ..office.convert import OfficeConverter
from . import documents as D
from . import match as am

ARCHIVE_DIR = "成果/归档"
TEMP_DIR = "工作区/临时"
FONT = "STSong-Light"          # Adobe 的 CJK CID 字体名：reportlab 只写字体名、不嵌入字体文件（见交付说明）
MASK_H = 55                    # 白色遮罩高度（磅），与原版第六步一致
NUMBER_Y = 25                  # 页码基线离页面底边（磅）
_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
IMAGE_TYPES = {"image"}
PDF_TYPES = {"pdf"}
SIGN = "立卷申请书须打印 → 经办律师手签 → 扫描为 PDF 后上传金助理，不得代签、不得电子签"
_font_ready = False


def _register_font() -> None:
    global _font_ready
    if not _font_ready:
        pdfmetrics.registerFont(UnicodeCIDFont(FONT))
        _font_ready = True


def folder_name(client: str, opponent: str | None) -> str:
    """<委托人>与<对方当事人>案件归档；名字里 Windows 不许的字符换成 _，各取前 40 字。"""
    def clean(s: str) -> str:
        return _BAD.sub("_", s).strip().rstrip(".")[:40] or "_"
    return f"{clean(client)}与{clean(opponent)}案件归档" if opponent else f"{clean(client)}案件归档"


def number_pages(writer: PdfWriter) -> None:
    """每页底部白色遮罩 + 居中"第x页 共x页"。页面先把旋转转进内容，页码层按页面实际大小和原点画。"""
    _register_font()
    total = len(writer.pages)
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    boxes = []
    for i, page in enumerate(writer.pages):
        page.transfer_rotation_to_content()
        box = page.mediabox
        x0, y0, w, h = float(box.left), float(box.bottom), float(box.width), float(box.height)
        boxes.append(page)
        c.setPageSize((x0 + w, y0 + h))
        c.setFillColorRGB(1, 1, 1)
        c.rect(x0, y0, w, MASK_H, stroke=0, fill=1)
        c.setFillColorRGB(0, 0, 0)
        c.setFont(FONT, 10)
        c.drawCentredString(x0 + w / 2, y0 + NUMBER_Y, f"第{i + 1}页 共{total}页")
        c.showPage()
    c.save()
    layer = PdfReader(io.BytesIO(buf.getvalue()))
    for page, over in zip(boxes, layer.pages):
        page.merge_page(over)


def _readable(path: pathlib.Path) -> PdfReader | None:
    try:
        r = PdfReader(str(path))
        if r.is_encrypted and not r.decrypt(""):
            return None
        len(r.pages)
        return r
    except Exception:  # noqa: BLE001 坏的 PDF
        return None


class ArchiveBuilder:
    def __init__(self, cases, tasks, materials, settings, skills_dirs, lo_base: pathlib.Path,
                 converter: OfficeConverter | None = None):
        self.cases = cases
        self.tasks = tasks
        self.materials = materials
        self.settings = settings
        self.skills_dirs = [pathlib.Path(d) for d in skills_dirs]
        self.converter = converter or OfficeConverter(lo_base)

    def _skill_file(self, *parts: str) -> pathlib.Path | None:
        for d in self.skills_dirs:
            p = d.joinpath("case-archiving", *parts)
            if p.is_file():
                return p
        return None

    def build(self, d: dict) -> dict:
        cid, root, task = self.tasks.locate(d["task_id"])
        if cid != d["case_id"]:
            raise ApiError("TASK_NOT_FOUND", "other_case")
        if d["plan"] != self.tasks.rel(d["task_id"], "归档方案.json") or \
                not gate.resolve_internal(root, d["plan"], op="archive_build").is_file():
            raise ApiError("INVALID_ARGUMENT", "not_the_plan")
        plan = d["confirmed"]
        if plan["result"] is None:
            raise ApiError("PLAN_NOT_CONFIRMED", "result_null")
        catalog = am.load_catalog(self.skills_dirs, plan["catalog"])
        index = self.materials.index(d["case_id"])
        missing, _warn = am.check_plan(catalog, plan, index)
        by_name = {m["name"]: m for m in index["materials"]}
        s = self.settings.get()
        lawyer = plan["lawyer"] or s["profile"].get("lawyer_name")
        choice = s.get("converter", "auto")
        manual: list[str] = []

        job = f"{TEMP_DIR}/归档-{secrets.token_hex(4)}"
        gate.mkdir_work(root, job, op="archive_build")
        try:
            return self._build(root, d, task, plan, catalog, by_name, missing, lawyer, choice, job, manual)
        finally:
            remove_tree(gate.resolve_internal(root, job, op="archive_build"))

    # ------------------------------------------------------------------

    def _to_pdf(self, root: str, m: dict, job: str, choice: str) -> tuple[pathlib.Path | None, str | None]:
        src = gate.resolve_read(root, m["rel_path"], op="archive_build")
        if m["type"] in PDF_TYPES:
            return src, None
        if m["type"] in IMAGE_TYPES:
            frames = []
            with Image.open(src) as im:
                for k in range(getattr(im, "n_frames", 1)):
                    im.seek(k)
                    frames.append(im.convert("RGB"))
            buf = io.BytesIO()
            frames[0].save(buf, "PDF", save_all=True, append_images=frames[1:], resolution=150)
            return gate.write_bytes(root, f"{job}/图{secrets.token_hex(3)}.pdf", buf.getvalue(), op="archive_build"), None
        out, used = self.converter.to_pdf(root, src, job, choice)
        return out, used

    def _build(self, root, d, task, plan, catalog, by_name, missing, lawyer, choice, job, manual) -> dict:
        changfa = plan["catalog"] == "常法卷"
        gen = [it for it in catalog["items"] if it.get("generated")]
        used_any: list[str] = []
        skipped: list[str] = []
        pdfs: dict[int, list[pathlib.Path]] = {}
        for it in sorted(plan["items"], key=lambda x: x["code"]):
            for name in it["materials"]:
                pdf, used = self._to_pdf(root, by_name[name], job, choice)
                if used:
                    used_any.append(used)
                if pdf is None or _readable(pdf) is None:
                    skipped.append(name)
                    continue
                pdfs.setdefault(it["code"], []).append(pdf)

        # 结案报告
        f = D.report_fields(plan, lawyer)
        tpl = self._skill_file("templates", "结案报告模板.docx")
        if tpl:
            report, notes = D.fill_report_template(tpl, f)
            manual += notes
        else:
            report = D.make_report(f, changfa)
            manual.append("结案报告为临时模板，待律所模板到位后替换")
        rp = gate.write_bytes(root, f"{job}/结案报告.docx", report, op="archive_build")
        report_pdf, report_used = self.converter.to_pdf(root, rp, job, choice)
        manual.append(f"结案报告由 {report_used} 转成 PDF，请在 Word / WPS 中核对是否为一页")
        for g in gen:
            pdfs[g["code"]] = [report_pdf]

        # 卷宗
        writer = PdfWriter()
        ranges: dict[int, tuple[int, int]] = {}
        for code in sorted(pdfs):
            start = len(writer.pages) + 1
            for p in pdfs[code]:
                writer.append(PdfReader(str(p)))
            if len(writer.pages) >= start:
                ranges[code] = (start, len(writer.pages))
        number_pages(writer)
        vol = io.BytesIO()
        writer.write(vol)

        # 发票
        invoice = None
        inv_codes = [it["code"] for it in catalog["items"] if "收费发票" in it["name"] and it["code"] in pdfs]
        if inv_codes:
            w = PdfWriter()
            for code in inv_codes:
                for p in pdfs[code]:
                    w.append(PdfReader(str(p)))
            buf = io.BytesIO()
            w.write(buf)
            invoice = buf.getvalue()
        elif any("收费发票" in it["name"] for it in catalog["items"]):
            manual.append("方案里没有\"收费发票凭证\"的材料，发票.pdf 未生成，请补上发票后重新生成")

        # 立卷申请书
        rows = D.application_rows(plan, catalog, ranges)
        tpl = self._skill_file("templates", f"立卷申请书模板_{plan['catalog']}.docx") or \
            (self._skill_file("templates", "立卷申请书模板.docx") if plan["catalog"] == "民事行政卷" else None)
        if tpl:
            application, notes = D.fill_application_template(tpl, plan, rows)
            manual += notes
        else:
            application = D.make_application(plan, rows, lawyer)
            manual.append("立卷申请书为临时版式，待律所模板到位后替换")
        manual.append(SIGN)

        # 情况说明
        statements: list[tuple[str, str, bytes]] = []
        md = self._skill_file("references", "特殊情况说明模板.md")
        if missing or not plan["fee_settled"]:
            if md is None:
                raise ApiError("TEMPLATE_MISSING", "statement")
            if missing:
                statements.append(("特殊情况说明", "材料缺失情况说明及承诺.docx",
                                   D.make_missing_statement(md, plan, missing)))
                manual.append("必交材料有缺失，已生成《材料缺失情况说明及承诺》：须经办律师手签，交风控专员报备")
            if not plan["fee_settled"]:
                statements.append(("特殊情况说明", "律师费未结清情况说明及承诺.docx", D.make_fee_statement(md, plan)))
                manual.append("律师费未结清，已生成《律师费未结清情况说明及承诺》：须经办律师手签，附佐证材料，交风控专员报备")
        for name in skipped:
            manual.append(f"「{name}」读不了（加密或损坏），没有放进卷宗，请换成可读的版本后重新生成")
        manual.append("上传金助理的三个文件：发票.pdf、立卷申请书（手签扫描版）、卷宗.pdf")

        listing = D.catalog_md(plan, catalog, ranges, missing, skipped).encode("utf-8")
        files = [("卷宗", "卷宗.pdf", vol.getvalue())]
        if invoice is not None:
            files.append(("发票", "发票.pdf", invoice))
        files += [("立卷申请书", "立卷申请书.docx", application), ("结案报告", "结案报告.docx", report),
                  ("归档目录", "归档目录.md", listing)] + statements
        return self._write(root, d, task, plan, files, ranges, report_used, manual)

    def _write(self, root, d, task, plan, files, ranges, report_used, manual) -> dict:
        base = folder_name(plan["client"], plan["opponent"])
        written: list[str] = []
        try:
            with eo.index_update(root, d["case_id"]) as index:
                version, folder = 1, f"{ARCHIVE_DIR}/{base}"
                while gate.resolve_internal(root, folder, op="archive_build").exists():
                    version += 1
                    folder = f"{ARCHIVE_DIR}/{base}-v{version}"
                for _kind, name, data in files:
                    gate.write_bytes(root, f"{folder}/{name}", data, op="archive_build")
                    written.append(f"{folder}/{name}")
                index["outputs"].append({
                    "title": folder.rsplit("/", 1)[1], "version": version,
                    "files": [{"format": n.rsplit(".", 1)[1], "path": f"{folder}/{n}"} for _k, n, _b in files
                              if n.endswith((".docx", ".md"))],
                    "task_id": d["task_id"], "inputs": task["inputs"],
                    "citation_passed": eo.result_passed(self.tasks, root, d["task_id"]), "confirmed_at": now_iso()})
        except Exception:
            eo.remove_outputs(root, written)
            raise
        logs.event("archive", "build", case_id=d["case_id"])
        return {"folder": folder, "files": [{"kind": k, "path": f"{folder}/{n}"} for k, n, _b in files],
                "page_ranges": [{"code": c, "from": a, "to": b} for c, (a, b) in sorted(ranges.items())],
                "converter": report_used, "manual": manual}
