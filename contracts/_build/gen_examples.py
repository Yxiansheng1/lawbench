import json, pathlib

EX = pathlib.Path(__file__).resolve().parents[1] / "examples"
EX.mkdir(parents=True, exist_ok=True)
for p in EX.glob("*.json"):
    p.unlink()
M = []
CASE = "3f2b9c1e-7a4d-4e8b-9c2a-1b5d6e7f8a90"
SHA = "a" * 64
T = "T-20260928093000-7c1f"
P = "P-20260928100000-02ab"
J = "J-20260928094500-3e9d"
NOW = "2026-09-28T09:30:00+08:00"
PARAMS = {"thinking": "低", "window": "64K", "max_tokens": 16384}
CHECK = {"passed": False,
         "problems": [{"class": "B", "severity": "must_fix", "excerpt": "借款金额 60,000 元〔借条 第3页〕",
                       "citation": "〔借条 第3页〕", "message": "该金额在〔借条 第2页〕，不在第3页"}],
         "stats": {"citations": 12, "must_fix": 1, "hints": 0}}
COV = {"total": 3, "fully_read": ["借条"], "partially_read": [{"name": "银行流水", "read_units": 40, "total_units": 120}],
       "not_read": [], "unreadable": [{"name": "证据/照片2", "reason": "识别未完成"}]}


def ex(file, schema, data, pointer="", expect="valid"):
    (EX / file).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    M.append({"file": file, "schema": schema, "pointer": pointer, "expect": expect})


# 出处
for n, (txt, ok) in enumerate([
        ("〔借条 第2页〕", 1), ("〔证据/借条 第3-4页〕", 1), ("〔银行流水 Sheet1!B12〕", 1),
        ("〔起诉书 第5段、讯问笔录1 第12行〕", 1), ("〔未找到依据〕", 1), ("〔推断〕", 1),
        ("【借条 第2页】", 0), ("〔借条 第2页、第3页〕", 0), ("〔借条〕", 0)]):
    ex(f"citation_{n}.json", "common.schema.json", txt, "#/$defs/citation_text", "valid" if ok else "invalid")

# /core
ex("core_task_begin.req.json", "core/task_begin.schema.json",
   {"session_id": "s_01HZX", "cwd": "D:\\案件\\张某诈骗案"}, "#/$defs/request")
ex("core_task_begin.res.json", "core/task_begin.schema.json",
   {"ok": True, "value": {"task_id": T, "case_id": CASE, "skill": "criminal-reading-notes", "params": PARAMS,
                          "budget": {"model_calls": 8, "tool_calls": 24, "minutes": 45}}}, "#/$defs/response")
ex("core_task_begin.fail.json", "core/task_begin.schema.json",
   {"ok": False, "error": {"code": "CASE_NOT_FOUND", "message": "当前会话不属于任何已打开的案件"}}, "#/$defs/response")
ex("core_context.res.json", "core/context.schema.json",
   {"ok": True, "value": {"l0": {"text": "## 案件卡片 …", "chars": 3200},
                          "l1": {"text": "## 输入1 刑事阅卷笔录-v2 …", "tokens": 18000, "truncated": True,
                                 "toc": [{"index": 2, "title": "证据审查意见-v1", "tokens": 9000}]}}}, "#/$defs/response")
ex("core_task_end.req.json", "core/task_end.schema.json",
   {"task_id": T, "reason": "budget", "model_calls": 8, "tool_calls": 19, "elapsed_s": 600}, "#/$defs/request")

# 工具
ex("tool_list.result.json", "tools/case_list_materials.schema.json",
   {"materials": [{"material_id": "M0001", "name": "借条", "type": "pdf", "status": "parsed", "unit": "page",
                   "unit_count": 3, "is_ocr": "partial", "stale_ocr": False, "error": None}], "total": 1},
   "#/$defs/result")
ex("tool_read.args.json", "tools/case_read_material.schema.json", {"name": "借条", "start": 2}, "#/$defs/args")
ex("tool_read.args_path.json", "tools/case_read_material.schema.json",
   {"name": "借条", "path": "D:/x"}, "#/$defs/args", "invalid")
ex("tool_read.result.json", "tools/case_read_material.schema.json",
   {"name": "借条", "material_id": "M0001", "unit": "page", "start": 2, "end": 3, "text": "【第2页】\n…",
    "has_more": False, "next_start": None}, "#/$defs/result")
ex("tool_search.result.json", "tools/case_search.schema.json",
   {"hits": [{"name": "银行流水", "material_id": "M0002", "citation": "〔银行流水 Sheet1!B12〕",
              "snippet": "…转账 80,000.00 …", "is_ocr": False, "match": "expanded"}], "total": 1, "truncated": False},
   "#/$defs/result")
ex("tool_save_draft.result.json", "tools/case_save_draft.schema.json",
   {"path": f"工作区/任务/{T}/草稿/刑事阅卷笔录-v2.md", "version": 2, "citation_check": CHECK, "coverage": COV,
    "not_fully_read": ["银行流水"]}, "#/$defs/result")
ex("tool_edit_list.args.json", "tools/case_save_edit_list.schema.json",
   {"name": "采购合同", "edits": [{"id": 1, "para": 37, "action": "replace", "find": "九十日内付款",
                                   "text": "三十日内付款", "comment": "付款期限过长，建议缩短"}]}, "#/$defs/args")

# /api
ex("api_case_open.fail.json", "api/case_open.schema.json",
   {"ok": False, "error": {"code": "CASE_IN_SYNC_FOLDER", "message": "该文件夹在 OneDrive 同步目录中，请移到本机普通文件夹后再打开"}},
   "#/$defs/response")
ex("api_ocr_submit.req.json", "api/ocr_submit.schema.json",
   {"case_id": CASE, "material_id": "M0001", "pages": [2, 3], "dewatermark": False}, "#/$defs/request")
ex("api_ocr_list.res.json", "api/ocr_list.schema.json",
   {"ok": True, "value": {"jobs": [{"job_id": J, "material_id": "M0001", "name": "借条", "status": "paused",
                                    "pause_reason": "prep_down", "total": 2, "done": 1, "failed": 0, "created_at": NOW}]}},
   "#/$defs/response")
ex("api_source.res.json", "api/source.schema.json",
   {"ok": True, "value": {"name": "借条", "loc": {"unit": "page", "from": 2}, "text": "…", "page_png_base64": "iVBOR…",
                          "source_changed": False}}, "#/$defs/response")
ex("api_wiki_suggestions.res.json", "api/wiki_suggestions.schema.json",
   {"ok": True, "value": {"suggestions": [{"id": "S0001", "field": "当事人", "value": "李某（出借人）",
    "source": "〔借条 第1页〕", "reason": None, "task_id": T, "created_at": NOW, "status": "pending"}]}}, "#/$defs/response")

# 395
ex("prep_ocr.res.json", "prep395/ocr_page.schema.json",
   {"markdown": "借条\n今借到李某人民币陆万元整（¥60,000.00）…", "unclear": 1, "elapsed_ms": 5400,
    "backend": "llama.cpp/vulkan", "image_png_base64": None}, "#/$defs/response")
ex("prep_ocr.err.json", "prep395/ocr_page.schema.json",
   {"error": {"code": "QUEUE_FULL", "message": "排队已满"}}, "#/$defs/error")
ex("prep_extract.req.json", "prep395/extract.schema.json",
   {"task": "fields", "text": "【第6页】…", "fields": ["当事人", "日期", "金额", "案号"]}, "#/$defs/request")
ex("prep_extract.res.json", "prep395/extract.schema.json",
   {"task": "fields", "result": [{"field": "金额", "value": "60,000.00", "loc": "第6页"}], "elapsed_ms": 3200},
   "#/$defs/response")
ex("prep_health.json", "prep395/health.schema.json",
   {"status": "ok", "ocr": "ok", "llm9b": "ok", "queue": 3, "version": "1.0.0", "contract_version": "1.0"})

# 落盘文件
ex("file_material_index.json", "files/material_index.schema.json",
   {"v": 1, "case_id": CASE, "next_seq": 2, "materials": [{
       "material_id": "M0001", "rel_path": "证据/借条.pdf", "name": "借条", "type": "pdf", "size": 812345,
       "mtime": NOW, "sha256": SHA, "status": "needs_ocr", "unit": "page", "unit_count": 3, "is_ocr": "none",
       "text_path": "工作区/材料/文本/证据/借条.pdf.md", "pages_need_ocr": [2, 3], "pages_mixed": [],
       "note": None, "error": None, "imported_at": NOW, "updated_at": NOW}]})
ex("file_task.json", "files/task.json".replace("task.json", "task.schema.json"),
   {"v": 1, "task_id": T, "case_id": CASE, "kind": "agent", "session_id": "s_01HZX", "entry": "刑事阅卷",
    "skill": "criminal-reading-notes", "step": None,
    "inputs": [{"index": 1, "title": "刑事阅卷笔录", "path": "成果/刑事阅卷笔录-v1.md", "version": 1, "sha256": SHA}],
    "params": PARAMS, "budget": {"model_calls": 8, "tool_calls": 24, "minutes": 45}, "state": "pending",
    "created_at": NOW})
ex("file_reads.json", "files/reads.schema.json",
   {"v": 1, "task_id": T, "reads": [{"material_id": "M0001", "material_version": SHA, "unit": "page",
                                      "from": 1, "to": 3, "at": NOW}]})
ex("file_result.json", "files/result.schema.json",
   {"v": 1, "task_id": T, "status": "completed", "usage": {"model_calls": 6, "tool_calls": 14, "elapsed_s": 480},
    "drafts": [{"title": "刑事阅卷笔录", "path": f"工作区/任务/{T}/草稿/刑事阅卷笔录-v2.md", "version": 2}],
    "citation_check": CHECK, "coverage": COV,
    "citations": [{"material_id": "M0001", "material_version": SHA, "name": "借条", "loc": {"unit": "page", "from": 2}}],
    "finished_at": NOW})
ex("file_case_card.json", "files/case_card.schema.json",
   {"v": 1, "case_id": CASE, "case_type": "criminal", "stance": None,
    "parties": [{"id": "F0001", "text": "张某，犯罪嫌疑人", "citations": ["〔起诉意见书 第1页〕"], "status": "excerpt"}],
    "issues": [], "key_facts": [], "generated_by": P, "generated_at": NOW,
    "materials_at_generation": [{"material_id": "M0001", "sha256": SHA}]})
ex("file_outputs_index.json", "files/outputs_index.schema.json",
   {"v": 1, "outputs": [{"title": "刑事阅卷笔录", "version": 1,
                         "files": [{"format": "docx", "path": "成果/刑事阅卷笔录-v1.docx"}], "task_id": T,
                         "inputs": [], "citation_passed": True, "confirmed_at": NOW}]})
ex("file_cases.json", "files/cases.schema.json",
   {"v": 1, "cases": [{"case_id": CASE, "root": "D:\\案件\\张某诈骗案", "name": "张某诈骗案", "last_opened": NOW}]})
ex("file_settings.json", "files/settings.schema.json",
   {"v": 1, "servers": {"llm_base_url": "http://192.168.8.77:8000/v1", "prep_base_url": "http://192.168.8.78:9000"},
    "defaults": {"thinking": "中", "window": "64K", "max_tokens": 16384, "temperature": 0.3},
    "skill_presets": {"contract-review": {"thinking": "高", "window": "128K", "max_tokens": 32768}},
    "templates": {"文书": None, "合同": None}, "ocr_fallback_llm": False})

(EX / "manifest.json").write_text(json.dumps(M, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(len(M), "examples")
