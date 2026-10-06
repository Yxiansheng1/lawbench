# lawbench — 给每个 Claude Code 会话的规矩

律师本地 AI 工作台（涉密项目）。开工前按顺序读：

1. `docs\plan\lawbench-关键事实索引-20260928.md` —— 路径、机器、账号、已定决定、会话表、纪律。
2. `docs\plan\lawbench-工单集-第一版开发-20260928.md` 中你被派的那张工单（本文件兼进度台账）。
3. 工单"输入"里列出的 Spec 章节和契约文件。
4. `PROJECT-PROFILE.md` —— 会话之间怎么传话（协调目录 `D:\lawbench-coord\`）、复核分级、无人值守能做什么；`.claude\skills\` 下 13 个工程 skill 都读它。

总览（给人看）：`docs\plan\lawbench-编排计划-第一版开发-20260928.html`。

## 你是谁

看你所在的目录：`D:\lawbench` = 主编排（Fable）；`D:\lawbench-A` / `-B` / `-C` / `-D` = 线 A / B / C / D（Opus 5.5；线 D 做 macOS 版 T28，**不改 Windows 行为**）。只做派给你这条线的工单。主编排不写产品代码。

## 必须遵守

- **契约优先**：接口和共用数据格式以 `contracts\` 为准，不许私自增减字段。改契约走事实索引第 8 节第 1 条的流程。
- **只在自己的分支提交**，提交信息 `T<n>: ...`；合并到 `main` 只由主编排做。开工前 `git rebase main`。
- **机密**：`.env.local` 不提交；任何文件、提交、日志、工单回填里不写 Key 和密码。仓库不放真实案卷，测试只用 `tests\fixtures\` 的虚构材料。
- **产品不外连**：产品代码只允许访问设置里的 6000D（所内 `192.168.8.77:8000`、所外 `10.126.126.1:8000`）、395（所内 `192.168.8.124:9000`、所外 `10.126.126.3:9000`）和 `127.0.0.1`；所内所外由工作台服务自动切换（Spec 第 15 节）。日志只记元数据，不记材料名、检索词、模型输入输出。
- **证据**：测试输出和截图放 `docs\plan\evidence\T<n>\`；做完把交付说明写进 `docs\plan\evidence\T<n>\交付说明.md`（提交 SHA、证据路径、偏离之处、遗留问题），随分支提交，然后在 `D:\lawbench-coord\` 落交回件通知主编排（写法见 `PROJECT-PROFILE.md` 第 3 节）。**不要改工单集文件本身**——它只由主编排在 `main` 上改，各线改会在合并时冲突。
- **文档**：改 `docs\src\*.md` 后运行 `python scripts\build_docs.py`；不直接改 HTML。
- **engines\**：律所提供的发票、委托材料工具原样使用，不改代码；确需改动的，先交主编排决定，并记入该目录的 `CHANGELOG.md`。发票引擎只能按 Spec 13.3 的白名单动作调用，不得开放邮箱、IMAP、正文链接下载。
- **Skill**：改 `skills\` 后运行 `python skills\_scripts\build_skills.py --root skills` 和 `python contracts\check_examples.py --skills skills`，都通过才提交。
- **模糊处不自行拍板**：摘录原文写进该卡的 `交付说明.md`，交主编排决定。
- **Windows / PowerShell**：命令按 PowerShell 写，路径用反斜杠。
- **派子代理时必须显式指定 model**，不继承主会话模型。
- **禁 `git stash`**：所有工作目录共用一个 stash 栈，会弹错目录。
- **协调目录不放机密**：`D:\lawbench-coord\` 里不写 Key、密码、网络密钥、真实案卷内容。

## 常用检查

```powershell
python contracts\check_examples.py --skills skills   # 契约与 Skill 自检
python scripts\check_6000d.py                          # 6000D 网关与测试 Key
python scripts\check_395_reach.py 192.168.8.124        # 395 端口与 /health
```
