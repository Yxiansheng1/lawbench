# T17 第一步复核记录 · Reviewer B（影响半径、边缘情况与回归安全）

- 复核员：主编排派出的子代理，Opus 5.5 · high，只读；与 Reviewer A 同一条消息并发派出，互相看不到
- target：head `2827c695111527cd4dc5027457507f6eec794b79`（line-A），base `661f57b`；提交 `d105303`、`2827c69`
- 复核位置：主编排临时目录里的克隆和实验目录；没有联网，没有启动桌面端；DSH 源码一律以固定提交 `477b4f4` 为准
- 时间：2026-09-30 10:25 起，约 16 分钟（用户已回来，值守窗已关）
- 以下是复核员最终报告的原文，只把本机路径里的用户名替换成 `<用户>`，其余未作删改；综合裁决见 `review-综合裁决.md`

---
# Reviewer B 复核：T17 第一步（只改配置关入口，加拖入守卫）

target 已亲自核对：`line-A` 的 HEAD 是 `2827c695111527cd4dc5027457507f6eec794b79`，克隆 `git status --short` 为空，base 为 `661f57b`。

**一句话结论**：22 行关得干净，Host 行和界面行都成对关了，没有顺手关掉明令不关的行，也没有"启用但起不来"的行。拖入守卫本身写得稳，但留了两个口子没堵：
- 一是从"+"菜单"添加文件"选的文件，会同样卡住、没有提示；
- 二是从 Excel 这类地方复制、剪贴板里同时带文字和图片时，这次粘贴会被整次拦掉，文字也粘不进去。

两条都是 P2，所以结论是 AMEND。

## 一、Findings（按严重度）

**F1 · P2 · 引入的回归（守卫没覆盖的第三个入口）**
- **问题**：从"+"菜单"添加文件"（输入框的回形针选文件）选普通文件，仍会生成发不出去的引用标签。按回车、点发送都没反应，也没有提示。选图片的话，图片照样进 DSH 附件目录。
- **违反的不变量**：主编排 09:39 裁决写的"没有提示地卡住不行"；D13 要求"不进附件"。
- **影响**：拖入和粘贴已经有提示了，选文件这条路还是原来的死路。这个死路是 `d105303` 关 `ui-reference` 带出来的：关之前，这类标签能交给 `file-reference-local` 发出去。
- **证据**：
  - 选文件和拖入走的是同一个 `addFiles`（`ui-conversation/src/client/apply.ts`，固定提交 `477b4f4` 第 273 行附近登记 `name: 'file'`）；
  - 第 472 行：不是图片、又拿得到本机路径的文件做成 `source: 'reference'` 标签；是图片则上传成附件；
  - 发送时 `ui-input-trigger/src/client/controller.ts:346-351` 找不到 `reference` 的序列化器，于是拒绝发送；
  - 调研第 4 节自己也写了"添加文件（file）：仍在"；截图 09 里输入框左下"+"按钮也还在。
- **最小修复**：二选一，交主编排定。
  - 守卫在 document 捕获阶段加一个 `change` 监听：目标是 `input[type=file]`、不在 `data-lawbench-drop` 里、页面上有对话输入框时，拦下来、清空 `value`、弹同一条提示，约 8 行；
  - 或者在交付说明里明写"过渡期'+'添加文件同样会卡住"，并入 N36/P-5（D13 本来就要去掉"+"附件按钮）。

**F2 · P2 · 引入的回归**
- **问题**：剪贴板里同时有文字和文件时，守卫把整次粘贴拦掉，文字也粘不进去，只弹"请把文件拖到材料面板"。典型场景是从 Excel 复制一片单元格：Excel 会同时放一份位图，浏览器会把它当成一个文件。
- **违反的不变量**：执行令写的"纯文字照常"。DSH 原本的行为是文字照样粘进去、文件另外处理（`keymap.ts:159-185`：先 `intakeFiles`，再 `pasteText(text)`）。
- **影响**：律师从 Excel 粘金额表、从带图的文档粘内容时，文字丢了，提示还答非所问。
- **证据**：实验 E4。粘贴一个 `image.png` 加文字"合同金额 100 万元"，结果 `defaultPrevented=true`，弹 1 次提示，文字没有交给 DSH。Excel 剪贴板里真的带图片这一点，本机没启动桌面端，没有实测，属于依据常识的判断；代码层面的行为是确定的。
- **最小修复**：`getData('text/plain')` 不为空时，拦下原事件后只把文字交回去：用只含文字的 `DataTransfer` 重新派发一次 paste，或者 `execCommand('insertText')`，约 6 行。再补一条"文字加文件"的用例。

**F3 · P3 · 范围内（测试覆盖）**
- **问题**：粘贴时"P-5 接上就让路"这一支没有测试守着。
- **证据**：变异 M4（去掉 `onPaste` 里的 `|| deps.intakeActive()`）之后，作者的 `drop-guard.spec.ts` 8 例仍然全绿，只有我补的 E9 变红。作者的 10 个变异里也没有这一项。
- **最小修复**：在第 4 个用例里补一次 `intake=true` 时的粘贴断言。

**F4 · NOTE · 独立后续**
- **问题**：关了 `plugin-inventory` 以后，产品配置本身再也导不出运行时清单了。"`legal-ui` 等真的加载了"这一条（执行令要求 5），在产品配置下只能靠界面模块列表加界面现象来间接证明；要看清单就得临时加叠加层，而加了叠加层，被测的配置就变了。
- **建议**：这个做法主编排已认可，不重开。以后几张卡（安装程序、失败即关）要设计一种不依赖 `plugin-inventory` 的自检，比如由我方 `legal-host` 自报已加载的行，或者由 0.1 的"失败即关"兜住。

**F5 · NOTE（给 N41 的输入，不重开）**
- `workspace-changes` 现在一个使用者都没有了：唯一注入 `workspaceChanges` 的是 `ui-deliverables`，已经关了。
- 它却还在每一轮跑 `git`、把改动过的文件复制到 `%TEMP%`（调研第 5 节）。
- 现在关掉它不会损失任何功能，建议主编排在 N41 里告诉用户这一点。

**F6 · NOTE · 已声明的偏离，影响可以接受**
- 守卫拦截的范围是"页面上有对话输入框时，整个 document"，比执行令写的"只拦输入区"宽。
- 我核对了会被误拦的情形，都可以接受：
  - 设置弹层盖在对话上时拖文件进去（E8）；
  - 在页面里拖一张图片，Chromium 会带上 Files 类型（E6）。
- DSH 自己的拖动只带 `text/plain`，不受影响（E7）：会话、工作区排序在 `Rows.tsx:254`，拖文字同理。

**F7 · NOTE · 证据表述有小出入**
- 作者说只在改后失败的 6 项都是超时。实际 `package-target-errors … on darwin` 是断言失败：同一文件里 win32 那条先超时，环境变量没恢复，连带出了错。
- 性质仍是打包类、与本步无关，单独重跑也通过了，结论不变。

**F8 · NOTE · 臆测，未实测**
- 以前打开过"终端 / 文件"标签的老 profile：右侧栏布局存在 Local Storage，重启后可能恢复出一个已经没人认领的标签。
- 律师装的是全新环境，不受影响；只可能影响开发机和试点机。

**另外提醒一件事**：复核期间，`D:\lawbench-A\dsh` 工作区正在被改。`ui-conversation/src/client/apply.ts` 在 10:36 被修改，内容是 P-5 的 `conversationFileIntake`；线 A 的 `pnpm build`、`tsc -b` 也在跑。作者截图里的版本号是 `477b4f4-dirty`。我引用 DSH 源码时一律以固定提交 `477b4f4` 为准（`git show`），关键的 5 个文件都核对过与固定提交一致。

## 二、依赖核对表（22 行，静态推算）

**推算方法**：
- 自己写合并脚本，依次叠 base、web-app、`dsh-ext` 三层配置：改前启用 125 行，改后 103 行，差 22 行，正好就是这 22 行，其余行一行没动。
- 结果与作者的 `plugin-tree.txt` 逐行对比，完全一致。
- 注入关系用 `rg` 在 `packages/**/src` 里搜。

| 行 | 提供什么 | 谁注入 / 使用 | 使用方是否仍启用 | 结论 |
|---|---|---|---|---|
| terminal-controller | Host：`terminalController`（命名空间 terminal）；界面半边：`webTerminals` | ui-sidebar-terminal（必需） | 关 | 成对关，干净 |
| ui-sidebar-terminal | 终端标签类型、Ctrl+\` 快捷键 | 无 | — | 干净 |
| file-reference-local | `fileReferences`；系统提示的 file-reference 一节 | session-controller 内部子插件 `SessionFileReferences`（必需，`file-references.ts:18`）；ui-reference 用它的远程命名空间 | 子插件停在 pending；ui-reference 关 | 子插件 pending 作者已如实写明，这不是清单行；它背后的远程命名空间现在没有调用方 |
| session-reference | `sessionReferenceResolver`，以及 `agent/pre-step` 塞入别的会话内容 | ui-reference（远程） | 关 | 塞入别的会话内容只在这个包里做，关掉就没有了；全库没有第二处解析会话引用 |
| ui-reference | `@` 触发源、`reference` 序列化器 | ui-conversation 的 `addFiles` 生成 `reference` 标签（不是注入，是运行时要用） | 启用 | 这就是 F1、F2 的来源；拖入、粘贴已由守卫接住，选文件没接住 |
| workspace-files | Host `workspaceFiles`；界面半边往 `resources` 登记 `file` 提供者 | ui-deliverables（必需）、ui-sidebar-files、ui-sidebar-documentpreview、office-to-pdf（`ctx.get`） | 全关 | 干净。我方 `dsh-ext\ui`、`dsh-ext\host` 里一次也没有用过 `workspaceFiles`，界面读写案件文件全部经 `remote.lawbench` |
| ui-sidebar-files | 文件树标签 | 无 | — | 干净 |
| ui-deliverables | 界面半边提供 `chatFileMentions` | ui-chat 用可选的 `ctx.get('chatFileMentions')?.` | 启用，但属可选 | 干净，不会起不来 |
| open-in-app | Host 路由（注入 webServer、connection、subprocess） | ui-open-in-app | 关 | 干净 |
| ui-open-in-app | "在…中打开"、Ctrl+Alt+O | 无 | — | 干净。`session.openWorkspacePath` 在界面上的调用方只有 ui-open-in-app 和 ui-deliverables，两个都关了；现在只能从渲染进程直接调远程接口（DevTools 开着，或者任何界面插件），仍候 N40 |
| cordis-host-runner | `dynamicCordisRunner`、`cordisInspect` | cordis-inspect-providers、tool-cordis（在 preset-cordis 里，已关）、cordis-client-runner | 全关 | 干净 |
| cordis-inspect-providers | 工具提供者 | 无 | — | 干净 |
| cordis-client-runner | 界面半边 `dynamicCordisRunner`、`cordisInspect`、`timer` | ui-cordis | 关 | 干净。它界面半边提供的 `timer` 没有别的启用行依赖（界面模块清单里没有它，也没有报缺） |
| ui-cordis | 面板 | 无 | — | 干净 |
| session-log-download | `/export`、`GET /api/session.export`；界面半边 `sessionLogDownload` | 无 | — | 干净，`api-probe` 返回 404 |
| plugin-inventory | `pluginInventory` | ui-settings-plugin-inventory、ui-plugin-manager、我方反向检查脚本 | 前两者关 | 产品里没人依赖；反向检查只能靠叠加层（F4） |
| ui-settings-plugin-inventory / ui-settings-plugins | 设置页 | 无 | — | 干净 |
| ui-settings-shell / -agent-loop / -subagent / -web-search | 设置页（经 configForms） | 无 | — | 干净。它们编辑的 Host 行（shell-env、subagent-model-selection-settings 等）仍启用、按默认值跑，无害 |

**"启用但起不来"**：静态推算为 0 行，与作者取证的"2b：0 个"一致。唯一处于 pending 的是 session-controller 的内部子插件，没有调用方。

**`workspace-changes`**：只注入 `subprocess`，能正常激活，但已经没有使用者（F5）。

## 三、Host 行和界面行是否成对

逐对核对，全部成对：
- 终端：2 行；
- `@` 与跨会话引用：3 行；
- 工作区文件：2 行，加上 `ui-deliverables`（同一个包里 Host 和界面两半）；
- 在别的程序里打开：2 行；
- 动态 Cordis：4 行；
- 导出：1 行（同一个包里两半）；
- 内置插件：`plugin-inventory` 加 6 个界面页。

没有只关一面的。仍挂着、指向无服务命名空间的只有 `fileReferences`、`sessionReferenceResolver`：远程客户端无条件挂载这些命名空间（调研 0.4），但已经没有任何调用方。

**明令不关的行，全部仍启用**：permission、ui-permission、ui-model-selection、ui-agent-preset、ui-trajectory、workspace-changes、command-feedback、ui-goal、ui-plan、directory-picker、subprocess、sandbox；pwsh-sandbox 仍是按平台动态启用（Windows 上开）。

**1a、1b 节和其他配置项**：diff 只在 1c 节新增，`skillDirs`、`spill-local` 等没有动。

## 四、守卫的影响地图与实验

**拦截条件**：带 Files，且页面上有 `[data-composer-input]`，且目标不在 `[data-lawbench-drop]` 里，且 P-5 没接上，四条同时满足才拦。粘贴只看输入框里的粘贴、剪贴板里有文件才拦。

**首页不碰这一点属实**：`AppFrame.tsx:42` 只渲染当前选中的那个 main 面板，打开首页时对话面板被卸载，输入框不在页面上。这依赖 DSH 的布局实现，由作者那条"标记还在"的测试在 DSH 升级时守着输入框标记。

**卸载**：用 `ctx.effect` 返回的卸载函数移除监听，插件重载时会清掉。监听挂在 document 上，是否拦截每次事件发生时现场判断，所以切换会话不需要重新装。

**提示文案**：固定文字，不带文件名和路径（E2）。

**P-5 让路**：现在走不到这一支（DSH 没有提供 `conversationFileIntake`），只有判断函数层面的测试，`index.tsx` 里的接线没有测试。粘贴让路没有测试（F3）。

**实验**：在副本里用 jsdom，装上**真的** DSH `drop-events.ts` 加守卫，自补 10 例，全部通过：

| 编号 | 场景 | 结果 |
|---|---|---|
| E1 | 拖入对话区 | DSH 的拖入计数一直是 0，高亮从没打开；`dragleave` 守卫不接，但计数最低到 0，不会卡住 |
| E2 | 看提示内容 | 不带文件名 |
| E3 | 从材料面板拖到对话区 | 到了对话区就被接住，DSH 计数不再增加 |
| E4 | 文字加文件的粘贴 | 整次被拦（F2） |
| E5 | 纯文字粘贴；在我方输入框里粘贴文件 | 都不碰 |
| E6 | 在页面里拖图片 | 被接住并提示 |
| E7 | 侧栏拖动排序；事件没有 dataTransfer | 不碰，也不抛错 |
| E8 | 设置弹层盖在对话上时拖入 | 被接住 |
| E9 | P-5 接上后粘贴 | 让路 |
| E10 | 输入框被移走（相当于首页） | 不碰，交还 DSH |

**变异**（每次改一处，跑作者的 spec 和我的 spec，跑完还原并逐字节核对）：

| 变异 | 作者 spec | 我的 spec |
|---|---|---|
| M1 去掉"我方拖入区除外" | 变红 | 仍绿 |
| M2 去掉"纯文字粘贴放行" | 变红 | 变红 |
| M3 去掉"没有输入框不碰" | 变红 | 变红 |
| M4 粘贴不看 P-5 | **仍绿** | 变红 |
| M5 拖动经过时不 stopPropagation | 变红 | 变红 |

你点名的三个变异（M1、M2、M3），作者的测试都会变红。

## 五、DSH 自带测试的核对

- **改前对照**：11 项失败；**改后**：16 项失败。两边都失败的 10 项相同：Windows 签名、上传凭据、签名缓存目录、Unicode 签名，外加 `profile-mcp`。
- **只在改后失败的 6 项**：installed-update-builder、macos-signature、package-target-errors（win32、darwin 各一）、packaged-runtime-verification、windows-update-publisher。
  - 除 darwin 那项外都是"超过 5 秒超时"；darwin 那项是 win32 超时连带出的断言失败（F7）；
  - `desktop-rerun.txt` 单独重跑这 5 个文件加 profile-mcp，33 项只有 profile-mcp 1 项失败；
  - 这些打包测试不读我方 `cordis.patch.yml`，和本步无关，说法成立。
- **只在改前失败的 1 项**：packaging-run 的"阶段进程超时"，同属这一类。
- **`profile-mcp`**：测试期望 `mcp-resources` 行没有 `disabled`，实际多了 `disabled`，而我方从 T4 起就关了它。两边都失败，说法成立。
- **我方全量测试**：独立跑，17 个文件，204 项通过、5 项跳过，与作者一致。DSH 桌面测试我没有重跑，见第九节。

## 六、可观测性与失败语义（给看法，不拍板）

- **Ctrl+\`、Ctrl+Alt+O**：处理这两个快捷键的界面包没加载，按了安静地没反应。这两个键从来没对律师宣传过，没反应可以接受。
- **`@`**：输入后不弹菜单，字面照样作为文字留在输入框里。但输入框占位文字仍写着"@ 文件或对话"，会误导，候 N40。
- **`/export`**：菜单里没有匹配项。按回车后是会被当成普通文字发给模型，还是被拦下，我没有核实；桌面端没启动。
- **真正不可接受的是"卡住且没有提示"**：拖入和粘贴已经修好，选文件还没有（F1）。

## 七、证据

- `api-probe-product.txt`（404）、`client-modules-product.txt`（43 个模块，本批 0 个，`lawbench-dsh` 在）、`plugin-tree-check.txt`（通过；2b 为 0；2d 第 22 行已关）都支持交付说明的说法。
- 界面模块清单里没有 `dsh-api-workspace-files` 和 `dsh-session-log-export` 的界面半边，与关掉的行一致。
- **截图 09、11 与代码对得上**：09 是拖到输入框，弹"没有加进对话"模态框，文案与 `DROP_TITLE`、`DROP_TEXT` 一致；11 是拖到材料面板，照常出现"导入材料"确认框。截图 05 显示发不出去的引用标签，与源码推断一致。
- **机密与用户名**：对 T17 证据目录的全部文本做了正则扫描，没有 Key、令牌、密码、本机用户名。截图里的路径是 `D:\lawbench-A\.tmp-demo\…`，不含用户名。

## 八、八项清单

1. **契约一致**：通过。没改 `contracts\`，没改远程接口。
2. **边界输入**：未通过（F2）。没有 dataTransfer、纯文字、侧栏拖动排序这几种都没问题。
3. **错误路径**：部分通过。选文件时依然安静地卡住（F1）。
4. **日志不含正文**：通过。守卫不写日志，提示是固定文案。
5. **路径闸门未被绕过**：通过。我方界面不用 `workspaceFiles`；`openWorkspacePath` 和 `/api/file` 仍候 N40，不属本步。
6. **无外连**：通过。只改了配置和 DOM 监听。
7. **测试覆盖新代码**：基本通过，有 P3 缺口：粘贴让路没测（F3），`index.tsx` 接线没测。
8. **无机密入库**：通过。

## 九、我实际跑过的命令

- `git rev-parse HEAD`、`git status --short`、`git log`、`git diff 661f57b HEAD`（克隆里只读）。
- 对 `D:\lawbench-A\dsh` 只做只读操作：`git show 477b4f4:…`、`git diff`、`git status`。
- python 合并脚本，推算改前、改后的启用行，并与 `plugin-tree.txt` 逐行对比。
- 在实验目录里：`robocopy /XJ` 复制仓库和 `dsh-ext\node_modules`，重建 junction（`dsh\node_modules`、`dsh\packages` 只读指向 `D:\lawbench-A\dsh`，另有 `.pnpm` 里的嵌套 junction 5 个）。
  - `node scripts\test.mjs` 全量跑：第一次缺嵌套 junction 失败，补上后 204 过、5 跳过；
  - 跑我的 `rvb-drop-guard.spec.ts` 加作者的 spec：18 项通过；
  - `mutate.py`：5 个变异 × 2 个 spec。
- 没启动桌面端，没联网，没碰凭据管理器，没用 `dsh --dump-config`（改用静态合并加作者的静态树对比）。

## 十、残留审计

- 实验目录 `rv-A17-B-lab`：先拆掉 10 个 junction，再用 `shutil.rmtree` 删除，已不存在。
- 源头 `D:\lawbench-A\dsh\packages` 和 `D:\lawbench-A\dsh-ext\node_modules` 完好。
- 复核克隆干净，HEAD 没变。
- 我起的 node 进程都已结束。现有进程都不是我的：`28216`、`35660` 是 Codex 的；`41876`、`26764` 是线 A 正在跑的 `pnpm build` 和 `tsc -b`。`soffice.bin` 没有动。
- `D:\lawbench-A\dsh\node_modules\.vite-temp` 的修改时间 10:39:41，晚于我最后一次运行（10:35），我的缓存都写在实验目录里，所以判断是线 A 写的。

## 十一、证据缺口（没启动桌面端，验证不了的）

- Excel、WPS 复制时剪贴板里是否真的带图片文件（F2 的触发频率）。
- "+"添加文件在当前产品配置下是否可见、选文件后是否真的卡住（F1 目前只有源码推断，加上调研第 4 节的说法）。
- 在 `/export` 后按回车的实际行为。
- 老 profile 恢复出已无人认领的标签（F8）。
- 真实 Chromium 里 React 合成事件的 `stopPropagation` 与守卫的先后顺序：jsdom 里没有 React，E3 只证明到了对话区会被接住。
- DSH 桌面测试没有独立重跑，只核对了作者的三份输出。

AMEND
