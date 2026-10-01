"""T4 插件树核对（返修版；T13 复制过来，白名单加 legal-ui；T17 第一步复制过来，21 行由白名单移入"必须关"，第一步补再加 ui-deliverables；T17 第二步 N41 再移 9 行；T13 目录里的原件未动）。

输入：
  plugin-inventory-desktop.json  运行中的桌面端 Host 的 pluginInventory/list 返回（dump_inventory.ps1 导出）；
                                 enabled 是 Loader 在桌面端语境下的实际状态，!!js 条件已求值。
  plugin-tree.txt                dsh --profile web --dump-config 导出，用于比较改配置行的取值。
检查：
  1. 必须关的行：启用即报错。
  2. 反向检查：启用的行必须在白名单里，清单外的启用行一律报出。
  3. 改配置的行：比较取值。
  4. preset-lawbench：只挂允许的插件。
  5. 启用的行必须都已激活（fiberPhase=active）：关掉某行后依赖它的行起不来会在这里报出。
  6. 我方 legal-ui、legal-host、legal-credentials 与 preset-lawbench 必须启用且已激活（组合包没加载时 DSH 会静默以原版启动）。
  7. 静态树（plugin-tree.txt）里"必须关"的行都写着 disabled: true。
  8. 我方会话存储 legal-session-store 的配置（T17 第三轮返修 A-P3-4）：allowOutsideCase 为 false（N46 ②），
     投影缓存按案件存（projectionCache 指向原版包、写入节奏同 base 原行）。
plugin-inventory 行（清单导出本身靠它）：产品配置关闭；取证启动在 profile 自己的补丁层临时写 disabled: false，
用 --inventory-overlay 声明，脚本对这一行改判为"取证期临时启用"，其余照常。产品配置下它关着由第 7 项静态树和
另行请求 /api/pluginInventory/list 失败两处核对。
用法：python check_plugin_tree.py plugin-inventory-desktop.json plugin-tree.txt [--inventory-overlay]
"""
import json, re, sys, yaml

# ── 1. 必须关的行（Spec 3.1 清单 21 行 + T4 复核补关 6 行）─────────────────
MUST_OFF = {
    "preset-standard", "preset-ptc", "preset-minimal", "preset-cordis",
    "web", "web-search-deepseek", "web-fetch-http", "mcp-resources",
    "plugin-manager", "ui-plugin-manager", "plugin-package-inventory-deepseek",
    "deepseek-account", "llm-deepseek", "llm-deepseek-account",
    "session-telemetry-otel", "message-feedback", "ui-message-feedback",
    "session-title-llm", "ui-sidebar-documentpreview", "office-to-pdf", "ui-brand-official",
    # 返修补关
    "ui-sidebar-browser", "ui-settings-models", "ui-settings-account", "account-controller",
    "ptc-runtime", "session-log-deepseek",
    # T7：原凭据行（Key 明文存 $DSH_HOME\.credentials.yaml）关闭，由我方 legal-credentials 提供同名服务（执行令 Q1）
    "credentials",
    # 官方 web-app 已关、须保持关闭的 AI 工具行
    "tool-bash", "tool-pwsh", "tool-jobs", "tool-fs", "tool-fs-search", "agent-instructions",
    "skill-filesystem", "tool-skill", "tool-subagent", "tool-subagent-fork", "tool-subagent-control",
    "tool-subagent-list-agents", "workflow-ptc", "tool-workflow", "tool-ralph", "tool-todo",
    "tool-web", "tool-goal", "command-goal", "plan-mode", "tool-plugin-manager",
}
# T17 第一步（执行令 2026-09-30 08:54）与第一步补（09:39）：律师用不上的入口，Host 行和界面行成对关；
# ui-deliverables 的 Host 半边硬依赖 workspace-files，随之显式关，不留"启用但起不来"。
# 名单只写这一份，并入"必须关"（复核 A-P3-3：不抄两遍）；第 2d 项静态树核对也用它。
T17_STEP1 = {
    "terminal-controller", "ui-sidebar-terminal",
    "file-reference-local", "session-reference", "ui-reference",
    "workspace-files", "ui-sidebar-files", "ui-deliverables",
    "open-in-app", "ui-open-in-app",
    "cordis-host-runner", "cordis-inspect-providers", "cordis-client-runner", "ui-cordis",
    "session-log-download",
    "ui-settings-plugins", "ui-settings-plugin-inventory", "plugin-inventory",
    "ui-settings-shell", "ui-settings-agent-loop", "ui-settings-subagent", "ui-settings-web-search",
}
# 条数守卫：执行令点名 21 行 + ui-deliverables；有人删掉一行而没改这里，脚本直接报错
assert len(T17_STEP1) == 22, f"T17 第一步名单应为 22 行，现为 {len(T17_STEP1)} 行"
MUST_OFF |= T17_STEP1
# T17 第二步 N41（用户同意主编排推荐，执行令 10:39 第 1 节）：要取舍的入口，同样成对关，由白名单移入"必须关"
T17_N41 = {
    "permission", "ui-permission",
    "ui-model-selection",
    "ui-agent-preset",
    "command-feedback",
    "ui-trajectory", "workspace-changes",
    "ui-goal", "ui-plan",
}
assert len(T17_N41) == 9, f"N41 名单应为 9 行，现为 {len(T17_N41)} 行"
MUST_OFF |= T17_N41
# T17 第三步（执行令 2026-09-30 15:16）：会话记录改由我方 legal-session-store 按案件存；原存储行关掉；
# 会话投影缓存会把律师原话存进 $DSH_HOME\storages，一并关掉（第三轮返修起由 legal-session-store 按案件存，见第 8 项）
T17_STEP3 = {"session-persistence-jsonl", "session-projection-cache"}
MUST_OFF |= T17_STEP3
# 取证期允许临时启用的行（见文件头）
OVERLAY_ROW = "plugin-inventory"
# 启用但起不来、已上报主编排待裁决的行（单列显示，不隐藏；裁决后按结论改）
# （ui-deliverables 曾列于此，主编排 09:39 裁决显式关掉，已移入"必须关"；现为空）
PENDING_DECISION = {}
OURS_REQUIRED = ["legal-ui", "legal-host", "legal-credentials", "legal-session-store", "preset-lawbench"]

# 必须关的行在运行时清单里不存在时一律计入失败（可能是 id 写错或换了 DSH 提交），
# 除非列在这里并写明原因。固定提交 477b4f4 下"必须关"的各行全部存在，所以目前为空。
ALLOWED_ABSENT = {}

# ── 2. 允许启用的行：类别 + 它是做什么的、为什么可以开 ─────────────────────
CORE = "核心运行时"
UI = "界面框架"
SET = "设置"
OURS = "我方"
LATER = "后续工单处理"
ALLOWED = {
    # 核心运行时：进程内服务，不对模型暴露工具、不外连
    "include": (CORE, "Cordis 组合包加载器本身"),
    "timer": (CORE, "定时器服务，供其他插件调度"),
    "hmr": (CORE, "开发期插件热更新；只重载本地文件"),
    "llm": (CORE, "LLM 适配器注册表，路由由 llm-pi-ai 提供"),
    "deepseek-llm-api-extensions": (CORE, "DeepSeek 官方 API 附加字段注册表，只被已关的 llm-deepseek 使用，处于空转"),
    "session": (CORE, "会话服务"),
    "typert": (CORE, "Typert 远程接口注册表（界面与 Host 通信）"),
    "typert-loader": (CORE, "Typert 远程接口加载"),
    "typert-gateway": (CORE, "界面到 Host 的 /api 网关，只监听 127.0.0.1"),
    "session-title": (CORE, "会话标题服务；LLM 生成标题的行已关，T7 由我方插件设标题"),
    "user-questions": (CORE, "ask_user_question 工具背后的提问服务"),
    "agent": (CORE, "Agent 运行服务"),
    "agent-default-model": (CORE, "新会话默认模型，已改成律所路由"),
    "jobs": (CORE, "后台任务注册表；产生任务的工具行都已关"),
    "llm-retry": (CORE, "LLM 重试服务，策略在 llm-pi-ai 路由的 retryPolicy"),
    "config-editor": (CORE, "把设置写进 profile 自己的补丁（叠在我方补丁之后、即时重载）；界面入口：插件页已随 ui-plugin-manager 关闭，设置页\"打开配置文件\"由 P-13 在桌面端去掉；设置接口的远程写入（update / mutate）归 T17，由 P-7 地址白名单兜底"),
    "settings": (CORE, "设置服务"),
    "authorization": (CORE, "本机界面鉴权"),
    "llm-pi-ai": (CORE, "律所模型路由（唯一路由，指向 127.0.0.1:18765）"),
    "session-query-sqlite": (CORE, "会话检索，内存库且不开启"),
    "session-projection": (CORE, "会话投影（界面显示用）"),
    "storage": (CORE, "存储服务"),
    "storage-json": (CORE, "JSON 存储后端"),
    "storage-domain": (CORE, "存储分域"),
    "subprocess": (CORE, "子进程服务；T7 的 Host 插件用它拉起工作台服务"),
    "sandbox": (CORE, "沙箱服务；命令工具已关，只作基础设施"),
    "sandbox-policy": (CORE, "沙箱策略"),
    "pwsh-sandbox": (CORE, "PowerShell 沙箱后端；tool-pwsh 已关，没有模型入口"),
    "approval": (CORE, "用户审批服务"),
    "shell-env": (CORE, "Shell 环境变量；命令工具已关"),
    "fs-observation-policy": (CORE, "文件观察策略"),
    "skill": (CORE, "Skill 注册表；只由 preset 内 skill-filesystem 注册两处目录"),
    "commands": (CORE, "斜杠命令注册表"),
    "goal": (CORE, "目标状态服务；模型侧 tool-goal、command-goal 已关"),
    "goal-round-driver": (CORE, "目标续跑驱动；无目标时空转"),
    "token-meter": (CORE, "用量统计，preset 的 compaction 依赖它"),
    "subagent": (CORE, "子智能体注册表；所有子智能体工具行已关"),
    "subagent-spawn-in-process": (CORE, "子智能体后端；无工具入口"),
    "subagent-fork-in-process": (CORE, "子智能体后端；无工具入口"),
    "subagent-model-selection-settings": (CORE, "子智能体模型选择设置；无工具入口"),
    "timeout-policy": (CORE, "工具调用超时策略"),
    "spill-local": (CORE, "溢出文件存储；阈值已调到 100 万 token，不会产生文件"),
    "spill-policy": (CORE, "溢出阈值 1000000"),
    "session-checkpoint-policy": (CORE, "会话检查点"),
    "image-offload": (CORE, "图片卸载；Agent 路由 input 只有 text"),
    "repeat-tool-reminder": (CORE, "重复工具调用提醒（提示词段）"),
    "tools": (CORE, "工具注册表，mode 锁成 native"),
    "system-prompt": (CORE, "系统提示组装；preset 的 persona complete: true 覆盖默认"),
    "agent-loop": (CORE, "Agent 循环"),
    "fs-sandbox": (CORE, "文件沙箱；文件工具已关"),
    "session-stats": (CORE, "会话统计（界面）"),
    "session-turn-outline": (CORE, "会话轮次大纲（界面）"),
    "directory-picker": (CORE, "目录选择器（打开案件用）"),
    "session-controller": (CORE, "会话命令远程接口"),
    "job-controller": (CORE, "后台任务远程接口"),
    "settings-controller": (CORE, "设置远程接口（读 describe、写 update / mutate）；远程写入可改 profile 补丁，归 T17，由 P-7 地址白名单兜底"),
    "workspace-controller": (CORE, "工作区远程接口，documentsDirectory 已改"),
    "web-startup": (CORE, "Web 启动参数"),
    "webserver": (CORE, "本机 Web 服务，绑定 127.0.0.1"),
    "web-runtime": (CORE, "界面静态资源与启动地址"),
    "agent-preset-registry": (CORE, "preset 注册表，default: lawbench"),
    # 界面框架：只渲染，不对模型暴露工具、不外连
    "client-hmr": (UI, "界面热更新（开发期）"),
    "modules": (UI, "界面插件模块表"),
    "connection": (UI, "界面到 Host 的连接"),
    "file-upload": (UI, "界面上传通道（附件改导入归 P-5 / T17）"),
    "api-remotes": (UI, "远程接口装配"),
    "ui-theme": (UI, "主题"),
    "locale": (UI, "语言，固定中文"),
    "shortcuts": (UI, "快捷键服务"),
    "ui-shortcuts": (UI, "快捷键界面"),
    "ui-layout": (UI, "布局"),
    "ui-renderer": (UI, "渲染器"),
    "ui-session": (UI, "会话界面"),
    "resources": (UI, "资源协议"),
    "ui-sidebar": (UI, "左侧栏"),
    "ui-sidebar-right": (UI, "右侧栏容器"),
    "ui-conversation": (UI, "对话区（附件入口改造归 P-5 / T17）"),
    "ui-approval": (UI, "审批界面"),
    "ui-chat": (UI, "聊天界面"),
    "ui-tool": (UI, "工具调用卡片"),
    "ui-workflow-run": (UI, "工作流运行卡片；工作流工具已关"),
    "ui-input-trigger": (UI, "输入框 / 和 @ 触发"),
    "ui-commands": (UI, "斜杠命令菜单"),
    "ui-skill": (UI, "Skill 引用"),
    "ui-subagent": (UI, "子智能体卡片；工具已关"),
    "ui-jobs": (UI, "后台任务列表"),
    "ui-user-questions": (UI, "ask_user_question 的界面"),
    # 设置
    "ui-settings": (SET, "设置页外壳；enabled: false 即开发者模式关"),
    "ui-settings-general": (SET, "通用设置页（语言、外观、字号等）；\"打开配置文件\"按钮已由 P-13 在桌面端去掉，开发者模式开关由 P-18 去掉，权限一行随 ui-permission 关掉"),
    # 我方
    "preset-lawbench": (OURS, "律师工作台 preset"),
    "legal-host": (OURS, "我方 Host 插件：启动并看护工作台服务（只监听 127.0.0.1），提供 lawbenchCore 服务和 lawbench 远程接口（首次配置页用）；不对模型暴露工具"),
    # T13：界面插件，行名即包名 lawbench-dsh（DSH 的 modules 行据此加载 ./client）
    "legal-ui": (OURS, "我方界面插件：首页、胶囊管理、右侧栏材料 / 成果 / 原文查看、输入区上方选择、设置页一节；一切数据经 lawbench 远程接口（Host 转 127.0.0.1 的工作台服务），不读写案件文件"),
    "legal-credentials": (OURS, "我方凭据插件：只认 LAWFIRM_KEY、读写 Windows 凭据管理器；授权记录只在内存；不读环境变量"),
    # T17 第三步
    "legal-session-store": (OURS, "我方会话存储：顶替 session-persistence-jsonl 与 session-projection-cache，案件里的会话记录存 <案件>\\工作区\\会话、投影缓存存 <案件>\\工作区\\会话缓存；不在案件里的会话不许新建、已有的只读；内部用原版 JSONL 包与原版缓存类"),
    # 后续工单处理（不是 AI 工具、不外连；归 T17 / T13 / T7 加固，本轮不关）
    "workspace": (LATER, "工作区服务与\"默认工作区\"入口（T13）"),
    "ui-workspace": (LATER, "\"默认工作区\"入口界面（T13）"),
    "attachment-local": (LATER, "附件存 $DSH_HOME，改为导入（P-5，T17）"),
    "ui-attachment": (LATER, "附件界面（P-5，T17）"),
}

# directory-picker 运行时自动挂载的子项没有固定 id（每次启动随机 8 位十六进制），按模块名放行
ALLOWED_MODULES = {
    "@deepseek-ai/dsh-host-directory-picker-native": (UI, "桌面端原生目录选择器（directory-picker 自动挂载的子项，Host 半边）"),
    "@deepseek-ai/dsh-client-ui-directory-picker-native": (UI, "桌面端原生目录选择器（界面半边）"),
}

# ── 3. 改配置的行：期望取值（!!js 按原文比较）─────────────────────────────
EXPECT = {
    "agent-preset-registry": {"default": "lawbench"},
    "agent-default-model": {"provider": "lawfirm", "model": "qwen38-27b"},
    "spill-policy": {"maxInlineTokens": 1000000},
    "spill-local": {"cleanupPeriodDays": 1},
    "locale": {"preference": "zh"},
    "ui-settings": {"enabled": False},
    "tools": {"mode": "native", "maxParallelSubCalls": 10},
    # T17 第二步返修（1516 令小项③）：权限关掉后写死，不读 DSH_PERMISSION_MODE
    "sandbox-policy": {"mode": "workspace-write", "workspaceRoot": "!!js process.cwd()"},
    "approval": {"policy": "ask"},
}
# 第 8 项：legal-session-store 的配置
SESSION_STORE_EXPECT = {
    "allowOutsideCase": False,
    "projectionCache.writeEveryEvents": 200,
    "projectionCache.writeIntervalMs": 5000,
}
LLM_EXPECT = {"baseURL": "http://127.0.0.1:18765/v1", "api": "openai-completions", "apiKeyEnv": "LAWFIRM_KEY",
              "retryPolicy": {"mode": "normal", "maxRetries": 1}}
def norm(v):
    """!!js 表达式在导出时可能被折行，比较前把连续空白压成一个空格。"""
    return re.sub(r"\s+", " ", str(v)).strip()


# 期望的 !!js 原文（与 dsh-ext\cordis.patch.yml 一致；导出后的反斜杠是两个）
EXPECTED_SKILL_DIRS = norm(r"!!js [process.getBuiltinModule('node:path').join(process.env.ProgramData ?? 'C:\\ProgramData', 'lawbench', 'skills'), process.env.LAWBENCH_SKILLS_DIR].filter(Boolean)")
EXPECTED_PERSONA_PREFIX = norm(r"!!js process.getBuiltinModule('node:fs').readFileSync(process.getBuiltinModule('node:module').createRequire(baseUrl).resolve('lawbench-dsh/persona.md'), 'utf8').replace(/^【草稿[^\n]*\n+/, '').trim()")
PERSONA_FILE = __import__("pathlib").Path(__file__).resolve().parents[4] / "dsh-ext" / "persona.md"

PRESET_ALLOWED = {"persona", "skill-filesystem", "tool-skill", "tool-ask-user", "legal-agent",
                  "compaction-basic", "tool-result-pruner"}


def main(inv_path, tree_path, overlay=False):
    inv = json.load(open(inv_path, encoding="utf-8"))["result"]["value"]
    entries = {e["entryId"].removeprefix("include:"): e for e in inv["entries"]}
    bad = []
    out = ["# 桌面端运行时插件核对（pluginInventory/list，enabled 为桌面端语境下的实际状态）", ""]

    out.append(f"## 1. 必须关的行（{len(MUST_OFF)} 行）")
    for i in sorted(MUST_OFF):
        e = entries.get(i)
        if e is None:
            st = f"不存在（允许：{ALLOWED_ABSENT[i]}）" if i in ALLOWED_ABSENT else "不存在!"
        else:
            st = "关" if not e["enabled"] else "启用!"
            if st == "启用!" and overlay and i == OVERLAY_ROW:
                st = "取证期临时启用（--inventory-overlay）"
        if st == "启用!":
            bad.append(f"必须关的行仍启用：{i}")
        if st == "不存在!":
            bad.append(f"必须关的行在清单里不存在（id 写错或 DSH 提交变了）：{i}")
        out.append(f"  {i:36s} {st}")

    enabled = sorted(i for i, e in entries.items() if e["enabled"] and not (overlay and i == OVERLAY_ROW))
    out += ["", f"## 2. 反向检查：启用的行 {len(enabled)} 个，逐条对白名单"]
    by_cat = {}
    for i in enabled:
        mod = entries[i]["moduleName"]
        if i not in ALLOWED and mod in ALLOWED_MODULES and re.fullmatch(r"[0-9a-f]{8}", i):
            by_cat.setdefault(ALLOWED_MODULES[mod][0], []).append((f"{i}（随机 id）", ALLOWED_MODULES[mod][1]))
        elif i not in ALLOWED:
            bad.append(f"清单外的启用行：{i}（{entries[i]['moduleName']}）")
            by_cat.setdefault("未列入白名单!", []).append((i, entries[i]["moduleName"]))
        else:
            by_cat.setdefault(ALLOWED[i][0], []).append((i, ALLOWED[i][1]))
    for cat in [CORE, UI, SET, OURS, LATER, "未列入白名单!"]:
        rows = by_cat.get(cat, [])
        if rows:
            out.append(f"### {cat}（{len(rows)}）")
            out += [f"  {i:36s} {why}" for i, why in rows]
    stale = sorted(set(ALLOWED) - set(enabled))
    if stale:
        out.append(f"（白名单中本次未启用的行：{', '.join(stale)}）")

    inactive = sorted(i for i, e in entries.items() if e["enabled"] and e.get("fiberPhase") != "active")
    out += ["", f"## 2b. 启用但没有激活的行（依赖缺失等）：{len(inactive)} 个"]
    for i in inactive:
        if i in PENDING_DECISION:
            out.append(f"  {i:36s} fiberPhase={entries[i].get('fiberPhase')}（待裁决：{PENDING_DECISION[i]}）")
            continue
        bad.append(f"启用但没有激活：{i}（fiberPhase={entries[i].get('fiberPhase')}）")
        out.append(f"  {i:36s} fiberPhase={entries[i].get('fiberPhase')}!")

    out += ["", "## 2c. 我方插件与 preset 已加载并激活（组合包没加载时 DSH 静默以原版启动）"]
    for i in OURS_REQUIRED:
        e = entries.get(i)
        ok = bool(e and e["enabled"] and e.get("fiberPhase") == "active")
        if not ok:
            bad.append(f"我方行没有加载或没有激活：{i}")
        out.append(f"  {i:36s} {'已激活' if ok else '缺失或未激活!'}")

    class L(yaml.SafeLoader): pass
    L.add_constructor("tag:yaml.org,2002:js", lambda l, n: "!!js " + l.construct_scalar(n))
    rows = {r.get("id"): r for r in yaml.load(open(tree_path, encoding="utf-8-sig"), Loader=L) if isinstance(r, dict)}
    out += ["", f"## 2d. 静态树里 T17 第一步这 {len(T17_STEP1)} 行、第二步 N41 这 {len(T17_N41)} 行、第三步 {len(T17_STEP3)} 行都写着 disabled: true（产品配置，不含取证叠加层）"]
    for i in sorted(T17_STEP1 | T17_N41 | T17_STEP3):
        r = rows.get(i)
        ok = bool(r) and r.get("disabled") is True
        if not ok:
            bad.append(f"静态树里没有关：{i}")
        out.append(f"  {i:36s} {'disabled: true' if ok else ('不存在!' if not r else '没有关!')}")
    out += ["", "## 3. 改配置的行（比较取值，来源 plugin-tree.txt）"]
    for i, exp in EXPECT.items():
        got = (rows.get(i) or {}).get("config")
        ok = got == exp
        if not ok:
            bad.append(f"{i} 取值不符：期望 {exp}，实际 {got}")
        out.append(f"  {i:24s} {'一致' if ok else '不一致!'}  {json.dumps(got, ensure_ascii=False)}")
    lf = (((rows.get("llm-pi-ai") or {}).get("config") or {}).get("providers") or {}).get("lawfirm") or {}
    for k, v in LLM_EXPECT.items():
        ok = lf.get(k) == v
        if not ok:
            bad.append(f"llm-pi-ai.{k} 不符：{lf.get(k)}")
        out.append(f"  llm-pi-ai.{k:18s} {'一致' if ok else '不一致!'}  {json.dumps(lf.get(k), ensure_ascii=False)}")
    models = [(m.get("id"), m.get("contextWindow"), m.get("reasoningEfforts")) for m in lf.get("models", [])]
    ok = models == [("qwen38-27b", 131072, {"off": None, "low": "low", "medium": "medium", "high": "xhigh"})]
    if not ok:
        bad.append(f"llm-pi-ai.models 不符：{models}")
    out.append(f"  llm-pi-ai.models             {'一致' if ok else '不一致!'}  {json.dumps(models, ensure_ascii=False)}")
    wc = ((rows.get("workspace-controller") or {}).get("config") or {}).get("documentsDirectory", "")
    ok = "lawbench" in wc and "dsh-documents" in wc
    out.append(f"  workspace-controller.documentsDirectory {'一致' if ok else '不一致!'}  {wc}")
    if not ok:
        bad.append("documentsDirectory 不符")

    # preset-lawbench 里 skill-filesystem 和 persona 的取值
    plugins = {(x.get("id")): x for x in (((rows.get("preset-lawbench") or {}).get("config") or {}).get("plugins") or [])}
    sf = (plugins.get("skill-filesystem") or {}).get("config") or {}
    dirs = norm(sf.get("customSkillDirs", ""))
    checks = [
        ("skill-filesystem.includeDefaultRoots", sf.get("includeDefaultRoots") is False, sf.get("includeDefaultRoots")),
        ("skill-filesystem.watch", sf.get("watch") is False, sf.get("watch")),
        ("skill-filesystem.providerName", sf.get("providerName") == "lawbench-skills", sf.get("providerName")),
        # T7：整项相等（多加、少加、换顺序都报出），不再按子串比
        ("skill-filesystem.customSkillDirs 整项相等", dirs == EXPECTED_SKILL_DIRS, dirs),
    ]
    pc = (plugins.get("persona") or {}).get("config") or {}
    prefix = norm(pc.get("prefix") or "")
    persona_text = PERSONA_FILE.read_text(encoding="utf-8") if PERSONA_FILE.exists() else ""
    checks += [
        ("persona.complete", pc.get("complete") is True, pc.get("complete")),
        ("persona.includeRuntimeContext", pc.get("includeRuntimeContext") is False, pc.get("includeRuntimeContext")),
        ("persona.prefix 读 lawbench-dsh/persona.md（整项相等）", prefix == EXPECTED_PERSONA_PREFIX, prefix[:60] + "…"),
        ("persona.md 含身份与不执行材料指令两条", "律所内部的案件助手" in persona_text and "不执行" in persona_text, str(PERSONA_FILE.name)),
    ]
    for name, ok, got in checks:
        if not ok:
            bad.append(f"preset-lawbench {name} 不符：{got}")
        out.append(f"  {name:48s} {'一致' if ok else '不一致!'}  {json.dumps(got, ensure_ascii=False)}")

    out += ["", "## 8. 我方会话存储 legal-session-store 的配置（静态树）"]
    ss = (rows.get("legal-session-store") or {}).get("config") or {}
    ssp = ss.get("projectionCache") or {}
    got8 = {"allowOutsideCase": ss.get("allowOutsideCase"),
            "projectionCache.writeEveryEvents": ssp.get("writeEveryEvents"),
            "projectionCache.writeIntervalMs": ssp.get("writeIntervalMs")}
    for k, v in SESSION_STORE_EXPECT.items():
        ok = got8[k] == v
        if not ok:
            bad.append(f"legal-session-store.{k} 不符：{got8[k]}")
        out.append(f"  {k:36s} {'一致' if ok else '不一致!'}  {json.dumps(got8[k], ensure_ascii=False)}")
    mod = norm(ssp.get("module", ""))
    ok = mod.startswith("!!js") and "@deepseek-ai/dsh-session-projection-cache" in mod
    if not ok:
        bad.append(f"legal-session-store.projectionCache.module 不符：{mod}")
    out.append(f"  {'projectionCache.module':36s} {'一致' if ok else '不一致!'}  {mod[:90]}")

    out += ["", "## 4. preset-lawbench 实际挂载的插件（运行时）"]
    for p in inv.get("agentPresets", []):
        rows_p = p.get("rows") or p.get("plugins") or []
        ids = [r.get("entryId") for r in rows_p]
        extra = [i for i in ids if i not in PRESET_ALLOWED]
        if p["id"] == "lawbench" and extra:
            bad.append(f"preset-lawbench 含不允许的插件：{extra}")
        out.append(f"  {p['id']}（默认={p.get('isDefault')}）：{ids}")
    if not any(p["id"] == "lawbench" and p.get("isDefault") for p in inv.get("agentPresets", [])):
        bad.append("preset-lawbench 不存在或不是默认")

    out += ["", "## 结论", "通过" if not bad else "不通过："] + [f"  - {b}" for b in bad]
    print("\n".join(out))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2], overlay="--inventory-overlay" in sys.argv[3:]))
