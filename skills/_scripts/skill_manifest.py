"""Skill 校验规则（Spec 第 10 节）。

胶囊配置不在这里：按 Spec 10.3 放在 <Skill 根目录>/capsules.default.json，
build_skills.py 和 install.py 都从那里读，只维护一份。
这个文件只放"什么样的 Skill 算合格"的规则。
"""

# ---- Spec 10.2 头部信息 ----
REQUIRED_FIELDS = ["name", "title", "description", "mode", "kind", "params", "owner", "inputs"]
MODES = {"pipeline", "agent"}
KINDS = {"excerpt", "analysis", "draft"}          # 决定出处核对 G 类规则（Spec 9.4）
INPUTS = {"materials", "wiki", "prior"}           # 材料 / wiki / 前序成果
PARAM_THINKING = {"关闭", "低", "中", "高"}
PARAM_WINDOW = {"32K", "64K", "128K"}
MAX_TOKENS_LIMIT = 262144                          # 服务器上限（Spec 8.2）
DESC_MAX = 400                                     # description 建议上限（字）

# ---- Spec 10.2 正文：六个二级标题，按此顺序 ----
REQUIRED_SECTIONS = ["适用场景", "输入", "必问问题", "处理步骤", "输出模板", "自检清单"]
# 必问问题每条：- key：问题（可从材料中获取：是/否）；没有必问问题时整节只写"无"
QUESTION_PATTERN = r"^- ([a-z][a-z0-9_]*)：(.+)（可从材料中获取：(是|否)）$"

# ---- 工具 ----
# 正文里允许出现的 case_* 工具（Spec 20.4、contracts/tools/）
ALLOWED_TOOLS = {
    "case_list_materials", "case_read_material", "case_search", "case_read_input",
    "case_read_wiki", "case_save_draft", "case_suggest_wiki", "case_save_edit_list",
    "case_calc_sentence", "case_archive_match", "case_save_archive_plan",          # 契约 1.1
}
# 以 case_ 开头但不是工具的字段名（工具返回值、参数名），校验时跳过
NON_TOOL_NAMES = {"case_type"}
# 律师工作台 preset 不挂的通用工具，正文里写了模型也调不到（Spec 3.1）
# 只列不会和普通字段名混淆的名字
FORBIDDEN_TOOLS = {"bash", "pwsh", "powershell", "read_file", "write_file", "edit_file", "web_fetch", "web_search"}
# 保存成果的工具：至少提到一个（只做指引的 Skill 除外）
SAVE_TOOLS = {"case_save_draft", "case_save_archive_plan"}
# legal-workflow 只做指引；case-wiki-build 是流水线，由程序保存（Spec D6、9.1）
NO_SAVE_REQUIRED = {"legal-workflow", "case-wiki-build"}

# ---- 共用规则同步 ----
SHARED_RULES_FILE = "_shared/共用规则.md"
BLOCK_START = "<!-- 共用规则:开始 -->"
BLOCK_END = "<!-- 共用规则:结束 -->"
BLOCK_ANCHOR = "自检清单"          # 没有标记时，插在"## 自检清单"之前

# ---- 胶囊配置与测试集 ----
CAPSULES_FILE = "capsules.default.json"   # 首页两级胶囊的默认配置（契约 skill/capsules.schema.json）
TOOL_IDS = {"invoice", "retainer"}        # kind=tool 的胶囊能打开的内置工具
TESTS_MIN_SAMPLES = 4              # Spec 10.2：至少 4 个样本 + 要点.md

# ---- 安装 ----
COPY_IGNORE = [".DS_Store", "__pycache__", "*.pyc", ".git", ".gitkeep", "Thumbs.db"]
