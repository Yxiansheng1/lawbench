"""生成 contracts/ 下的全部 JSON Schema（契约 1.0）。
改契约只改这个脚本，再运行一次；不要手改生成的 .schema.json。
"""
import json, pathlib, shutil

OUT = pathlib.Path(__file__).resolve().parents[1]
BASE = "lawbench://contracts/"
DRAFT = "https://json-schema.org/draft/2020-12/schema"
C = BASE + "common.schema.json#/$defs/"


def ref(name):
    return {"$ref": C + name}


def obj(props, required=None, extra=False, desc=None):
    o = {"type": "object", "properties": props, "additionalProperties": extra}
    o["required"] = list(props.keys()) if required is None else required
    if desc:
        o["description"] = desc
    return o


def arr(items, **kw):
    return {"type": "array", "items": items, **kw}


def s(desc=None, **kw):
    o = {"type": "string", **kw}
    if desc:
        o["description"] = desc
    return o


def i(desc=None, **kw):
    o = {"type": "integer", **kw}
    if desc:
        o["description"] = desc
    return o


def b(desc=None):
    o = {"type": "boolean"}
    if desc:
        o["description"] = desc
    return o


def enum(*vals, desc=None):
    o = {"enum": list(vals)}
    if desc:
        o["description"] = desc
    return o


def nullable(x):
    return {"anyOf": [x, {"type": "null"}]}


FILES = {}


def put(path, title, desc, defs=None, root=None):
    sch = {"$schema": DRAFT, "$id": BASE + path, "title": title, "description": desc}
    if defs:
        sch["$defs"] = defs
    if root:
        sch.update(root)
    FILES[path] = sch


# ---------------------------------------------------------------- C0 / C1 通用
common = {
    "case_id": s("案件编号：UUID v4，首次打开案件时生成，写入 case.db 的 meta 表",
                 pattern="^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"),
    "material_id": s("材料编号：M + 4 位序号，按首次导入顺序分配，同一案件内不复用；改名或移动视为删除后新增",
                     pattern="^M[0-9]{4}$"),
    "sha256": s("小写十六进制 sha256", pattern="^[0-9a-f]{64}$"),
    "task_id": s("任务编号：T-（Agent）或 P-（流水线）+ 本地时间 YYYYMMDDHHMMSS + - + 4 位小写十六进制",
                 pattern="^[TP]-[0-9]{14}-[0-9a-f]{4}$"),
    "job_id": s("识别任务编号", pattern="^J-[0-9]{14}-[0-9a-f]{4}$"),
    "session_id": s("DSH 会话 ID，原样透传，不解析", minLength=1),
    "time": s("ISO 8601，带时区，如 2026-09-28T09:30:00+08:00", format="date-time"),
    "rel_path": s("相对案件根目录的路径，分隔符一律用 /，不以 / 开头，不含 .. 段",
                  pattern="^(?!/)(?!.*(^|/)\\.\\.(/|$)).+$"),
    "material_type": enum("pdf", "docx", "doc", "wps", "xlsx", "xls", "csv", "md", "txt", "image"),
    "unit": enum("page", "para", "cell", "line", desc="位置单位：PDF / 图片按页，Word 按段，Excel 按单元格，csv / md / txt 按行"),
    "material_status": enum("parsed", "needs_ocr", "ocr_running", "partial", "failed", "source_deleted",
                            desc="parsed=已解析可读；needs_ocr=有页待识别；ocr_running=识别中；partial=部分页识别失败或未识别；failed=无法处理；source_deleted=原件已删除（保留文本）"),
    "ocr_state": enum("none", "partial", "full", desc="文本中识别所得的比例"),
    "error_code": enum(
        "INVALID_ARGUMENT", "OUT_OF_CASE", "CASE_NOT_FOUND", "CASE_ROOT_IS_LINK", "CASE_IN_SYNC_FOLDER",
        "MATERIAL_NOT_FOUND", "MATERIAL_NOT_READY", "TASK_NOT_FOUND", "INPUT_CHANGED", "BUDGET_EXCEEDED",
        "SERVER_UNREACHABLE", "KEY_INVALID", "SERVER_BUSY", "CONTEXT_TOO_LONG", "OUTPUT_TRUNCATED",
        "TIMEOUT", "HOST_NOT_ALLOWED", "PREP_UNAVAILABLE", "CANCELLED", "SERVICE_UNAVAILABLE", "INTERNAL",
        desc="错误码；含义与对应的中文提示见 Spec 20.1"),
    "error": obj({"code": ref("error_code"),
                  "message": s("给律师看的中文提示；不含材料名、检索词、正文")}),
    "fail": obj({"ok": {"const": False}, "error": ref("error")}, desc="统一失败体"),
    "loc": {
        "description": "结构化位置。page/para/line 用 from/to（含两端，to 可省略表示单个）；cell 用 sheet + ref（如 B12 或 B12:D12）",
        "oneOf": [
            obj({"unit": enum("page", "para", "line"), "from": i(minimum=1), "to": i(minimum=1)},
                required=["unit", "from"]),
            obj({"unit": {"const": "cell"}, "sheet": s(minLength=1),
                 "ref": s(pattern="^[A-Z]{1,3}[0-9]+(:[A-Z]{1,3}[0-9]+)?$")}),
        ]},
    "citation_text": s(
        "出处文本写法：〔材料名 位置〕。位置为 第N页 / 第N-M页 / 第N段 / 第N-M段 / 第N行 / 第N-M行 / 工作表名!B12 / 工作表名!B12:D12；"
        "同一括号内多处用顿号分隔，每处都写材料名；另有 〔未找到依据〕、〔推断〕 两种固定写法",
        pattern="^〔(未找到依据|推断|[^〔〕、 ]+ (第[0-9]+(-[0-9]+)?[页段行]|[^〔〕、!]+![A-Z]{1,3}[0-9]+(:[A-Z]{1,3}[0-9]+)?)(、[^〔〕、 ]+ (第[0-9]+(-[0-9]+)?[页段行]|[^〔〕、!]+![A-Z]{1,3}[0-9]+(:[A-Z]{1,3}[0-9]+)?))*)〕$"),
    "citation": obj({"material_id": ref("material_id"), "material_version": ref("sha256"),
                     "name": s("材料名，与 case_list_materials 返回的 name 相同"), "loc": ref("loc")},
                    desc="解析后的出处，由程序从出处文本解析得出并写入结果清单"),
    "thinking": enum("关闭", "低", "中", "高"),
    "window": enum("32K", "64K", "128K"),
    "params": obj({"thinking": ref("thinking"), "window": ref("window"),
                   "max_tokens": i(minimum=256, maximum=262144),
                   "temperature": {"type": "number", "minimum": 0, "maximum": 2}},
                  required=["thinking", "window", "max_tokens"]),
    "budget": obj({"model_calls": i(minimum=1), "tool_calls": i(minimum=1), "minutes": i(minimum=1)}),
    "problem": obj({
        "class": enum("A", "B", "C", "D", "E", "F", "G", desc="Spec 9.4 的七类问题"),
        "severity": enum("must_fix", "hint"),
        "excerpt": s("出问题的原句，最多 120 字"),
        "citation": nullable(s()),
        "message": s("中文说明，告诉模型或律师怎么改")},
        required=["class", "severity", "excerpt", "message"]),
    "citation_check": obj({
        "passed": b("没有 must_fix 类问题即为 true"),
        "problems": arr(ref("problem")),
        "stats": obj({"citations": i(minimum=0), "must_fix": i(minimum=0), "hints": i(minimum=0)})},
        desc="出处核对结果（界面上叫'数值与出处位置核对'）"),
    "coverage": obj({
        "total": i("本任务范围内的材料数", minimum=0),
        "fully_read": arr(s("材料名")),
        "partially_read": arr(obj({"name": s(), "read_units": i(minimum=0), "total_units": i(minimum=0)})),
        "not_read": arr(s("材料名")),
        "unreadable": arr(obj({"name": s(), "reason": s()}))},
        desc="覆盖清单：按 reads.json 的实际读取记录计算，不采信模型自报"),
    "input_ref": obj({"index": i(minimum=1), "title": s(), "path": ref("rel_path"),
                      "version": nullable(i(minimum=1)), "sha256": ref("sha256")},
                     desc="任务选用的一份前序成果或草稿；执行时核对 sha256，不一致报 INPUT_CHANGED"),
    "fact": obj({"id": s(pattern="^F[0-9]{4}$"), "text": s(), "citations": arr(ref("citation_text")),
                 "status": enum("lawyer_confirmed", "excerpt", "unconfirmed",
                                desc="✔律师确认 > 原文摘录 > ⚠模型生成未确认")}),
    "material_row": obj({
        "material_id": ref("material_id"), "name": s("案件内唯一，规则见 Spec 20.2"),
        "type": ref("material_type"), "status": ref("material_status"),
        "unit": ref("unit"), "unit_count": i(minimum=0), "is_ocr": ref("ocr_state"),
        "stale_ocr": b("原件变了而识别结果还是旧版本"),
        "error": nullable(s("失败原因，中文"))},
        desc="材料在 AI 工具中暴露的字段（不含路径）"),
}
put("common.schema.json", "通用定义", "所有契约共用的类型；其他文件用 $ref 引用这里的 $defs", defs=common)

# ---------------------------------------------------------------- C2 插件 → 工作台服务 /core/*
def endpoint(path, title, desc, req, res):
    put(path, title, desc, defs={
        "request": req,
        "response": {"oneOf": [obj({"ok": {"const": True}, "value": res}), ref("fail")]},
        "value": res})

endpoint("core/task_begin.schema.json", "POST /core/task/begin",
         "Agent 插件在每轮第一步调用：由会话头 cwd 找到案件，取该会话待执行的任务单；没有则按'自由对话'默认值新建",
         obj({"session_id": ref("session_id"), "cwd": s("会话头的 cwd，原样传入；服务只用它查注册表")}),
         obj({"task_id": ref("task_id"), "case_id": ref("case_id"), "skill": nullable(s()),
              "params": ref("params"), "budget": ref("budget")}))
endpoint("core/context.schema.json", "POST /core/context",
         "取首轮注入的 L0（案件卡片）和 L1（任务输入）文本",
         obj({"task_id": ref("task_id")}),
         obj({"l0": obj({"text": s(), "chars": i(minimum=0)}),
              "l1": obj({"text": s(), "tokens": i(minimum=0), "truncated": b(),
                         "toc": arr(obj({"index": i(minimum=1), "title": s(), "tokens": i(minimum=0)}),
                                    description="未放入 L1 的输入目录，AI 用 case_read_input 读")})}))
endpoint("core/tool.schema.json", "POST /core/tool",
         "执行一个 case_* 工具；args 和 value 的结构见 tools/<工具名>.schema.json",
         obj({"task_id": ref("task_id"), "tool": s(pattern="^case_[a-z_]+$"), "args": {"type": "object"}}),
         {"type": "object"})
endpoint("core/progress.schema.json", "POST /core/progress",
         "session/event 收到 assistant/message 时调用：覆盖写 草稿/进行中.md，更新用量",
         obj({"task_id": ref("task_id"), "text": s(), "model_calls": i(minimum=0), "tool_calls": i(minimum=0)}),
         obj({}))
endpoint("core/task_end.schema.json", "POST /core/task/end",
         "turn/end 时调用：写 result.json 最终状态；没存过正式草稿时把 进行中.md 改名为 未完成-<时间>.md",
         obj({"task_id": ref("task_id"),
              "reason": enum("completed", "aborted", "blocked", "error", "max-tokens", "interrupted", "budget",
                             desc="DSH turn/end 的 reason.kind，外加插件自己的 budget"),
              "model_calls": i(minimum=0), "tool_calls": i(minimum=0), "elapsed_s": i(minimum=0)}),
         obj({"status": enum("completed", "cancelled", "budget_stopped", "output_limit", "failed", "interrupted",
                             desc="写入 result.json 的状态")}))

# ---------------------------------------------------------------- C3 case_* 工具
def tool(name, desc, args, result):
    put(f"tools/{name}.schema.json", name, desc, defs={"args": args, "result": result})

MAXC = i("单次最多返回的字数，默认且最大 8000", minimum=500, maximum=8000)
tool("case_list_materials", "列出当前案件的材料。name 在案件内唯一，引用时照抄",
     obj({}), obj({"materials": arr(ref("material_row")), "total": i(minimum=0)}))
tool("case_read_material", "读一份材料的解析文本（带位置标记）。每次读取记入 reads.json",
     obj({"name": s(), "start": i("起始位置号（页 / 段 / 行；Excel 为工作表内的行号），默认 1", minimum=1), "max_chars": MAXC},
         required=["name"]),
     obj({"name": s(), "material_id": ref("material_id"), "unit": ref("unit"),
          "start": i(minimum=1), "end": i(minimum=1), "text": s(),
          "has_more": b(), "next_start": nullable(i(minimum=1))}))
tool("case_search", "全文检索（Spec 第 11 节）",
     obj({"query": s(minLength=1, maxLength=100), "max_hits": i("默认 20", minimum=1, maximum=50)}, required=["query"]),
     obj({"hits": arr(obj({"name": s(), "material_id": ref("material_id"),
                           "citation": ref("citation_text"), "snippet": s("命中处前后各 40 字"),
                           "is_ocr": b(), "match": enum("exact", "expanded")})),
          "total": i(minimum=0), "truncated": b()}))
tool("case_read_input", "分段读取任务单选用的第 index 个输入（L1 放不下时用）",
     obj({"index": i(minimum=1), "start": i("起始行号，默认 1", minimum=1), "max_chars": MAXC}, required=["index"]),
     obj({"index": i(minimum=1), "title": s(), "start": i(minimum=1), "end": i(minimum=1), "text": s(),
          "has_more": b(), "next_start": nullable(i(minimum=1))}))
tool("case_read_wiki", "读 wiki 的一节",
     obj({"section": enum("卡片", "概览", "当事人", "时间线", "材料清单", "争议焦点", "材料摘要"),
          "name": s("section 为 材料摘要 时必填：材料名")}, required=["section"]),
     obj({"section": s(), "text": s(), "updated_at": nullable(ref("time")),
          "stale": b("wiki 生成后有材料新增或变化")}))
tool("case_save_draft", "保存草稿到 工作区/任务/<任务ID>/草稿/，同标题再存生成新版本（旧版本保留）；返回核对结果",
     obj({"title": s(minLength=1, maxLength=60, pattern="^[^\\\\/:*?\"<>|]+$"), "content": s(minLength=1)}),
     obj({"path": ref("rel_path"), "version": i(minimum=1), "citation_check": ref("citation_check"),
          "coverage": ref("coverage"), "not_fully_read": arr(s("材料名"),
          description="coverage.partially_read 与 coverage.not_read 的材料名合并；不含 unreadable")}))
tool("case_suggest_wiki", "提出一条 wiki 修改建议，写入 wiki/待确认.json，律师确认后才生效",
     obj({"field": enum("本方立场", "当事人", "争议焦点", "关键事实", "时间线"), "value": s(minLength=1),
          "source": ref("citation_text"), "reason": s()}, required=["field", "value", "source"]),
     obj({"suggestion_id": s(pattern="^S[0-9]{4}$")}))
edit_item = obj({"id": i(minimum=1), "para": i("与材料文本的段号一致", minimum=1),
                 "action": enum("replace", "insert_after", "delete"),
                 "find": s("该段中恰好出现一次的原文", minLength=1),
                 "text": s("replace / insert_after 时必填"), "comment": s("批注：修改理由", minLength=1)},
                required=["id", "para", "action", "find", "comment"])
tool("case_save_edit_list", "保存合同修改清单（Spec 12.2），律师点'生成修订版'时使用",
     obj({"name": s("合同材料名"), "edits": arr(edit_item, minItems=1)}),
     obj({"path": ref("rel_path"), "accepted": i(minimum=0),
          "out_of_scope": arr(obj({"id": i(minimum=1), "reason": s()}))}))
FILES["tools/case_save_edit_list.schema.json"]["$defs"]["edit_item"] = edit_item

# ---------------------------------------------------------------- C4 界面 → /api/*
job_row = obj({"job_id": ref("job_id"), "material_id": ref("material_id"), "name": s(),
               "status": enum("queued", "running", "paused", "done", "cancelled", "partial_failed"),
               "pause_reason": nullable(enum("offline", "prep_down", "key_invalid", "app_exit")),
               "total": i(minimum=0), "done": i(minimum=0), "failed": i(minimum=0),
               "created_at": ref("time")})
api = [
    ("case_open", "POST /api/case/open", "打开或新建案件；登记到 cases.json。云同步目录报 CASE_IN_SYNC_FOLDER，链接或 junction 报 CASE_ROOT_IS_LINK",
     obj({"path": s("律师选的文件夹绝对路径")}),
     obj({"case_id": ref("case_id"), "name": s("文件夹名"), "created": b("本次新建了 工作区/")})),
    ("case_recent", "GET /api/case/recent", "最近案件（按最近打开时间倒序）", obj({}),
     obj({"cases": arr(obj({"case_id": ref("case_id"), "name": s(), "root": s(), "last_opened": ref("time"),
                            "exists": b("文件夹是否还在")}))})),
    ("materials_scan", "POST /api/materials/scan", "扫描原件区并在本机解析新增或变化的材料（同步返回汇总）",
     obj({"case_id": ref("case_id")}),
     obj({"added": i(minimum=0), "changed": i(minimum=0), "removed": i(minimum=0), "failed": i(minimum=0),
          "review_needed": b("有材料变化，wiki 和已有成果需要复核")})),
    ("materials_list", "GET /api/materials?case_id=", "材料列表（界面用，比 AI 工具多路径和页面信息）",
     obj({"case_id": ref("case_id")}),
     obj({"materials": arr(obj({
         "material_id": ref("material_id"), "name": s(), "rel_path": ref("rel_path"), "type": ref("material_type"),
         "status": ref("material_status"), "unit": ref("unit"), "unit_count": i(minimum=0),
         "is_ocr": ref("ocr_state"), "stale_ocr": b(), "error": nullable(s()),
         "pages_need_ocr": arr(i(minimum=1)), "pages_mixed": arr(i(minimum=1))}))})),
    ("ocr_submit", "POST /api/ocr/jobs", "提交识别（调用前界面已弹确认框，写明页数和发往 395）",
     obj({"case_id": ref("case_id"), "material_id": ref("material_id"), "pages": arr(i(minimum=1), minItems=1),
          "dewatermark": b()}),
     obj({"job_id": ref("job_id"), "pages": i(minimum=1), "estimated_minutes": nullable(i(minimum=0))})),
    ("ocr_list", "GET /api/ocr/jobs?case_id=", "识别任务进度", obj({"case_id": ref("case_id")}),
     obj({"jobs": arr(job_row)})),
    ("ocr_cancel", "POST /api/ocr/jobs/{job_id}/cancel", "取消识别；已完成的页保留",
     obj({"job_id": ref("job_id")}), obj({"job_id": ref("job_id"), "status": s()})),
    ("task_create", "POST /api/task", "为某个会话写待执行的任务单；Agent 插件在该会话下一次请求时取用",
     obj({"case_id": ref("case_id"), "session_id": ref("session_id"), "entry": nullable(s()),
          "skill": nullable(s()), "inputs": arr(ref("rel_path"), description="选用的草稿或成果路径，服务端计算版本和 sha256"),
          "params": ref("params")}),
     obj({"task_id": ref("task_id")})),
    ("pipeline_run", "POST /api/pipeline/run", "运行流水线（本次只有案件 wiki 的生成和更新）",
     obj({"case_id": ref("case_id"), "step": enum("wiki_build", "wiki_update"),
          "use_prep": b("字段抽取和分类用 395 的 9B（路由表：律师勾选即授权）"), "params": ref("params")}),
     obj({"task_id": ref("task_id")})),
    ("pipeline_status", "GET /api/pipeline/{task_id}", "流水线进度",
     obj({"task_id": ref("task_id")}),
     obj({"status": enum("running", "completed", "cancelled", "budget_stopped", "failed", "interrupted"),
          "step_index": i(minimum=0), "step_total": i(minimum=0), "current": nullable(s("当前处理的材料名")),
          "queue_wait_ms": nullable(i(minimum=0))})),
    ("pipeline_cancel", "POST /api/pipeline/{task_id}/cancel", "取消流水线；已完成的步骤存为草稿",
     obj({"task_id": ref("task_id")}), obj({})),
    ("tasks_list", "GET /api/tasks?case_id=", "本案任务列表（成果区用），数据来自各任务的 result.json",
     obj({"case_id": ref("case_id")}),
     obj({"tasks": arr(obj({"task_id": ref("task_id"), "skill": nullable(s()), "status": s(),
                            "drafts": arr(obj({"title": s(), "path": ref("rel_path"), "version": i(minimum=1)})),
                            "citation_passed": nullable(b()), "finished_at": nullable(ref("time"))}))})),
    ("redline", "POST /api/redline", "按修改清单在本机生成修订版 Word，存为该任务的草稿",
     obj({"case_id": ref("case_id"), "task_id": ref("task_id"), "edit_list": ref("rel_path")}),
     obj({"path": ref("rel_path"), "applied": i(minimum=0),
          "manual": arr(obj({"id": i(minimum=1), "reason": s()}), description="需人工修改的条目")})),
    ("wiki_suggestions", "GET /api/wiki/suggestions?case_id= ；POST /api/wiki/suggestions/{id}",
     "列出 / 处理 AI 提出的 wiki 修改建议",
     obj({"case_id": ref("case_id"), "id": s(pattern="^S[0-9]{4}$"), "accept": b()}, required=["case_id"]),
     obj({"suggestions": arr({"$ref": BASE + "files/wiki_pending.schema.json#/$defs/suggestion"})})),
    ("outputs_confirm", "POST /api/outputs/confirm", "律师确认草稿，导出到 成果/ 并写 成果/索引.json",
     obj({"case_id": ref("case_id"), "task_id": ref("task_id"), "draft": ref("rel_path"),
          "formats": arr(enum("md", "docx"), minItems=1, uniqueItems=True),
          "template": nullable(enum("文书", "合同"))}),
     obj({"outputs": arr(obj({"format": enum("md", "docx"), "path": ref("rel_path"), "version": i(minimum=1)}))})),
    ("source", "GET /api/source?case_id=&material_id=&loc=", "原文查看：返回定位单元的文本；PDF 另返回该页图片",
     obj({"case_id": ref("case_id"), "material_id": ref("material_id"), "citation": ref("citation_text")}),
     obj({"name": s(), "loc": ref("loc"), "text": s(), "page_png_base64": nullable(s()),
          "source_changed": b("原件哈希已与出处记录不同")})),
    ("search", "GET /api/search?case_id=&q=", "律师检索；返回结构同 case_search",
     obj({"case_id": ref("case_id"), "q": s(minLength=1, maxLength=100)}),
     {"$ref": BASE + "tools/case_search.schema.json#/$defs/result"}),
    ("settings", "GET / PUT /api/settings", "读写 settings.json；PUT 传完整对象",
     {"$ref": BASE + "files/settings.schema.json"}, {"$ref": BASE + "files/settings.schema.json"}),
    ("connection_test", "POST /api/connection/test", "测试服务器连接（只发探测请求，不含内容）",
     obj({"server": enum("llm", "prep")}),
     obj({"reachable": b(), "key_valid": nullable(b()), "latency_ms": nullable(i(minimum=0)), "message": s()})),
]
for name, title, desc, req, res in api:
    endpoint(f"api/{name}.schema.json", title, desc, req, res)

# ---------------------------------------------------------------- C5 本机 → 395
perr = obj({"error": obj({"code": enum("BAD_IMAGE", "KEY_INVALID", "TOO_LARGE", "QUEUE_FULL", "TIMEOUT",
                                        "KEY_CHECK_UNAVAILABLE", "BAD_REQUEST", "INTERNAL"),
                          "message": s()})}, desc="395 的错误体；HTTP 状态见 Spec 20.5")
put("prep395/health.schema.json", "GET /health（395）", "不需要 Key，不含任何内容",
    root=obj({"status": enum("ok", "degraded"), "ocr": enum("ok", "down"), "llm9b": enum("ok", "down"),
              "queue": i(minimum=0), "version": s(), "contract_version": s()}))
put("prep395/ocr_page.schema.json", "POST /v1/ocr/page", "请求体是单页图片的原始字节（Content-Type: image/png 或 image/jpeg，≤10MB，长边≤2480 像素）；选项放在查询参数",
    defs={"query": obj({"dewatermark": b(), "deskew": b(), "return_image": b("仅验收去水印时用")},
                       required=[]),
          "response": obj({"markdown": s("识别文本；看不清的字为 ■，整行看不清为 [看不清]"),
                           "unclear": i(minimum=0), "elapsed_ms": i(minimum=0), "backend": s(),
                           "image_png_base64": nullable(s())}),
          "error": perr})
put("prep395/extract.schema.json", "POST /v1/extract", "9B 抽取；单次 text ≤16000 字，由客户端按页切分",
    defs={"request": {"oneOf": [
              obj({"task": {"const": "fields"}, "text": s(maxLength=16000),
                   "fields": arr(s(), minItems=1)}),
              obj({"task": {"const": "classify"}, "text": s(maxLength=16000),
                   "categories": arr(s(), minItems=2)})]},
          "response": {"oneOf": [
              obj({"task": {"const": "fields"}, "result": arr(obj({"field": s(), "value": s(),
                   "loc": s("材料文本中的位置标记，如 第6页；表格类材料不送 9B，所以没有单元格位置", pattern="^第[0-9]+[页段行]$")})), "elapsed_ms": i(minimum=0)}),
              obj({"task": {"const": "classify"}, "result": obj({"category": s()}), "elapsed_ms": i(minimum=0)})]},
          "error": perr})

# ---------------------------------------------------------------- C7 / C8 落盘文件
def ffile(name, title, desc, body):
    body = dict(body)
    body["properties"] = {"v": {"const": 1}, **body["properties"]}
    body["required"] = ["v"] + body["required"]
    put(f"files/{name}.schema.json", title, desc, root=body)

ffile("material_index", "工作区/材料/index.json", "原件索引；导入时更新",
      obj({"case_id": ref("case_id"), "next_seq": i(minimum=1),
           "materials": arr(obj({
               "material_id": ref("material_id"), "rel_path": ref("rel_path"), "name": s(),
               "type": ref("material_type"), "size": i(minimum=0), "mtime": ref("time"), "sha256": ref("sha256"),
               "status": ref("material_status"), "unit": ref("unit"), "unit_count": i(minimum=0),
               "is_ocr": ref("ocr_state"), "text_path": ref("rel_path"),
               "pages_need_ocr": arr(i(minimum=1)), "pages_mixed": arr(i(minimum=1)),
               "note": nullable(enum("含修订，已按修订后文本", "由 doc 转换", "由 wps 转换", "由 xls 转换",
                                     "摘要为筛选结果，非全量")),
               "error": nullable(s()), "imported_at": ref("time"), "updated_at": ref("time")}))}))
ffile("task", "工作区/任务/<任务ID>/task.json", "任务单（执行前写）",
      obj({"task_id": ref("task_id"), "case_id": ref("case_id"), "kind": enum("agent", "pipeline"),
           "session_id": nullable(ref("session_id")), "entry": nullable(s()), "skill": nullable(s()),
           "step": nullable(enum("wiki_build", "wiki_update")),
           "inputs": arr(ref("input_ref")), "params": ref("params"), "budget": ref("budget"),
           "state": enum("pending", "running", "finished", "abnormal",
                         desc="abnormal=打开案件时发现仍为 running（上次硬退出）"),
           "created_at": ref("time")}))
ffile("reads", "工作区/任务/<任务ID>/reads.json", "读取记录：每次 case_read_material 追加一条",
      obj({"task_id": ref("task_id"),
           "reads": arr(obj({"material_id": ref("material_id"), "material_version": ref("sha256"),
                             "unit": ref("unit"), "from": i(minimum=1), "to": i(minimum=1), "at": ref("time")}))}))
ffile("result", "工作区/任务/<任务ID>/result.json", "结果清单（执行中更新进度，结束时写最终状态）",
      obj({"task_id": ref("task_id"),
           "status": enum("running", "completed", "cancelled", "budget_stopped", "output_limit", "failed",
                          "interrupted", "abnormal"),
           "usage": obj({"model_calls": i(minimum=0), "tool_calls": i(minimum=0), "elapsed_s": i(minimum=0)}),
           "drafts": arr(obj({"title": s(), "path": ref("rel_path"), "version": i(minimum=1)})),
           "citation_check": nullable(ref("citation_check")), "coverage": nullable(ref("coverage")),
           "citations": arr(ref("citation")), "finished_at": nullable(ref("time"))}))
ffile("case_card", "工作区/wiki/case.json", "案件卡片（L0 的来源）",
      obj({"case_id": ref("case_id"), "case_type": enum("criminal", "civil", "contract", "other"),
           "stance": nullable(obj({"text": s(), "set_at": ref("time")}, desc="本方立场，只能由律师在界面上填写")),
           "parties": arr(ref("fact")), "issues": arr(ref("fact")), "key_facts": arr(ref("fact")),
           "generated_by": nullable(ref("task_id")), "generated_at": nullable(ref("time")),
           "materials_at_generation": arr(obj({"material_id": ref("material_id"), "sha256": ref("sha256")}),
                                          description="用来判断 wiki 生成后哪些材料新增或变化")}))
sug = obj({"id": s(pattern="^S[0-9]{4}$"), "field": s(), "value": s(), "source": ref("citation_text"),
           "reason": nullable(s()), "task_id": ref("task_id"), "created_at": ref("time"),
           "status": enum("pending", "accepted", "rejected")})
put("files/wiki_pending.schema.json", "工作区/wiki/待确认.json", "AI 提出的 wiki 修改建议",
    defs={"suggestion": sug},
    root=obj({"v": {"const": 1}, "suggestions": arr({"$ref": "#/$defs/suggestion"})}))
ffile("outputs_index", "成果/索引.json", "律师确认后的成果登记",
      obj({"outputs": arr(obj({"title": s(), "version": i(minimum=1),
                               "files": arr(obj({"format": enum("md", "docx"), "path": ref("rel_path")}), minItems=1),
                               "task_id": ref("task_id"), "inputs": arr(ref("input_ref")),
                               "citation_passed": b(), "confirmed_at": ref("time")}))}))
ffile("cases", "<应用数据>/cases.json", "案件注册表：只有编号和路径，没有内容",
      obj({"cases": arr(obj({"case_id": ref("case_id"), "root": s("realpath，Windows 反斜杠原样保存"),
                             "name": s(), "last_opened": ref("time")}))}))
ffile("settings", "<应用数据>/settings.json", "设置；Key 不在这里（在 Windows 凭据管理器）",
      obj({"servers": obj({"llm_base_url": s(pattern="^http://"), "prep_base_url": s(pattern="^http://")}),
           "defaults": ref("params"),
           "skill_presets": {"type": "object", "additionalProperties": ref("params")},
           "templates": obj({"文书": nullable(s()), "合同": nullable(s())}),
           "ocr_fallback_llm": b("395 不可用时由 6000D 接管识别；管理员开启，默认 false")}))

# ---------------------------------------------------------------- C9 Skill 与入口
put("skill/frontmatter.schema.json", "SKILL.md 头部", "DSH 只读 name 和 description；其余字段由工作台服务读取",
    root=obj({"name": s(pattern="^[a-z0-9]+(-[a-z0-9]+)*$"), "title": s(), "description": s(maxLength=400),
              "mode": enum("agent", "pipeline"), "kind": enum("excerpt", "analysis", "draft"),
              "entry": {"anyOf": [s(), arr(s(), minItems=1)], "description": "入口名、入口名列表或'共用'"},
              "order": i(minimum=1), "params": ref("params"), "owner": s(), "inputs":
              arr(enum("materials", "wiki", "prior"), minItems=1, uniqueItems=True)}))
put("skill/entry.schema.json", "entries/<序号>-<id>.yaml", "入口清单；文件名排序即首页顺序",
    root=obj({"id": s(pattern="^[a-z0-9]+(-[a-z0-9]+)*$"), "name": s(), "skills": arr(s(), minItems=1),
              "outputs": arr(s(), minItems=1)}))


def main():
    if OUT.exists():
        for p in OUT.rglob("*.schema.json"):
            p.unlink()
    for path, sch in FILES.items():
        p = OUT / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(sch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "VERSION").write_text("1.0\n", encoding="utf-8")
    print(len(FILES), "schemas")


if __name__ == "__main__":
    main()
