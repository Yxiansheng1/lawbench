# T13 拖文件夹建案件 AMEND 关闭 + 两小项 · 独立复核记录（第二轮，PASS）

- 复核时刻：2026-10-10 15:34–15:45 (+08:00)；复核员：一名 Opus 只读复核员（换人；克隆 `D:\lawbench-rv\rv-A56`，实验目录 `rv-A56-exp`）
- target：line-A `ac92e19`（累计 `355cc7c`→`341f379`→`ac92e19`）；基座 main `5e0d218`
- 裁决（主编排）：**PASS**，cherry-pick 三提交进 main（`1eabaeb`、`113ca25`、`21db3d5`）。P3-1（explorer 接线无用例）记第八版小项；NOTE-2 转线 B 随端口四修改 `MESSAGES` 文案。

## 复核员报告（原文摘要）

**结论：PASS。** 上轮 P2-1/P3-1/P3-2 均关闭且有用例守（改回旧样即红）。

### Findings
- **P3-1 explorer 加引号的接线无用例守**（本次修正引入，不阻断）：`explorerArg` 本身有用例，但 `desk-node.ts openPath` 里"`explorerArg` 包路径 + `windowsVerbatimArguments: true`"两处接线无用例，变异 M7（去 `, true`）、M8（去 `explorerArg`）`desk-actions.spec` 13/13 仍绿。修：spawn 可注入或抽纯函数，补断言 `['"D:\\案件\\甲,乙"']` 且 verbatim。
- **NOTE-1 stderr 解码**（此前既有）：收集器编码不在仓库内；`portFailure` 只匹配 ASCII 前缀，解码方式不影响解析；中文句客户端不采用。
- **NOTE-2 服务侧文案有不存在的入口**（无关新发现，line-B）：`portdiag.py MESSAGES` RESERVED "请在设置里换一个端口"、DENIED "请换一个端口"，界面无此入口；客户端自写文案律师看不到，但日志/stderr 留着。

### 逐条核对
上轮关闭：M1（`has_case` 改回只看 `工作区\`）红；M2（去 `plainAbsolute`）红，用例路径 `\\?\<盘>`/`\\localhost\<盘>$` 真实存在；M3（取消抛错）红。引号回归：verbatim 子进程回显实测 `&^%PATH%`、空格+逗号+等号、末尾反斜杠（去掉）、`;()!`、盘根（不加引号）均完整到达；白名单与根内校验未放宽。supervisor：固定转发端口直接 failed（M4 红）；工作台端口仍换端口重试 6 次（M6 红）；老服务无类别行照旧；`giveUp` 换代（M5 两例 30 秒后红）；只在进程退出后调用，不误判慢启动；portdiag 字面一致性用例借 rv-B23 源码跑 1 passed。文案 `check_ui_words` 产品零命中（1 处为空 dsh 子模块）；三类句尾不重复"请联系技术支持"（有断言）。计数 729/1/7（唯一失败读 `dsh\apps` 环境缺件，计入即 730/0/7 与自报一致）；`tsc` 0；证据/截图 05、06 无用户名。

### 跑过的命令
`git diff 5e0d218|355cc7c ac92e19`；克隆与实验副本各三只读联接；`vitest.rv.mjs`/`vitest.m.mjs` cacheDir 指实验目录；全量 vitest；`mutate.ps1` M1–M8；`argtest.mjs`+`print.cjs` verbatim 实测；portdiag 一致性用例；`tsc --noEmit`；`check_ui_words.py`；`git grep` 用户名。6 联接已 `rmdir`，A 目录无 15:34 后写入，克隆干净。
