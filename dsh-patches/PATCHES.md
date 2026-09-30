# DSH 补丁台账

DSH 以子模块 `dsh\` 固定在提交 `477b4f420553e8a52c2fbccc464d7561b239c443`，不跟随上游。子模块内不放我方文件；对 DSH 源码的每一处改动都以补丁文件存在本目录并在此登记。子模块指针始终保持固定提交，补丁在工作区应用。

**应用**（在仓库根目录，按顺序）：

```powershell
git -C dsh apply ..\dsh-patches\P-10-profile-lawbench-dsh.patch
git -C dsh apply ..\dsh-patches\P-12-desktop-no-office.patch
git -C dsh apply ..\dsh-patches\P-13-desktop-no-open-config.patch
git -C dsh apply ..\dsh-patches\P-3-first-run-page.patch
```

应用后重新 `pnpm install`（P-10 改了依赖）和 `pnpm run build`（见事实索引第 5 节的开发命令）；我方组合包另需 `cd dsh-ext; node scripts/build.mjs`（产出 `dsh-ext\lib\`，不入库）。换 DSH 提交时逐条重做并重新核对。

| 编号 | 文件（相对 `dsh\`） | 改法 | 原因 | 验证方法 |
|---|---|---|---|---|
| P-10 | `packages/boot/app-boot/src/profile.ts`；`apps/cli/package.json`；`pnpm-lock.yaml`（补丁 `P-10-profile-lawbench-dsh.patch`） | `PROFILE_TEMPLATES.web.bundles` 末尾加 `lawbench-dsh`；`@deepseek-ai/dsh`（`apps/cli`）依赖加 `"lawbench-dsh": "link:../../../dsh-ext"`，锁文件随之更新 | Spec 14.1、3.2 P-10：我方组合包进入桌面端 profile（桌面端用 `PROFILE_TEMPLATES.web` 初始化，无单独 desktop 模板） | 删掉旧 profile（或换一个空的 `DSH_HOME`）后启动，新 profile 的 `package.json` 中 `dsh.profile.bundles` 末尾是 `lawbench-dsh`；启动日志无 "skipping profile bundle"；摘录见 `docs\plan\evidence\T4\p10-profile-excerpt.txt`，运行时插件清单见 `docs\plan\evidence\T7\plugin-inventory-desktop.json` |
| P-3 | `apps/desktop/src/welcome-api.ts`、`preload-welcome.ts`、`welcome-window.ts`、`welcome-backend.ts`、`main.ts`、`client/WelcomePage.tsx`；`apps/desktop/tests/`（补丁 `P-3-first-run-page.patch`） | 欢迎窗口换成我方"首次配置"页：6000D、395 的所内和所外地址（初值取服务 `GET /api/settings`，即 Spec 15 默认值）、个人 Key、"测试连接"（经 Host 的 `lawbench/trialConnection`：先保存再调 `/api/connection/test`，没通过就恢复测试前的地址和 Key，T7 返修 P3-5）、"保存并进入"（`lawbench/putSettings` 写 settings.json，`credentials/set` 写 Key）；判断条件改为"没有配置过律所服务器"（T7 执行令 Q3：settings.json 不存在或凭据管理器没有 Key）；删掉 DeepSeek 账号监听、登录、授权链接等全部代码。测试：`welcome-window.spec.ts` 改写保留（窗口隔离、禁止跳转、拒绝非本窗口的 IPC、关闭时移除处理器，通道换成三个操作，T7 返修 P2-2）；删除只测原 DeepSeek 流程的 4 个测试文件（`welcome-flow.e2e.ts`、`welcome-host.spec.ts`、`welcome-renderer.client.spec.tsx`、`welcome-startup.spec.ts`）；新增 `lawbench-first-run.spec.ts`（判断条件、输入校验、`connectDesktopWelcome` 的"未认证就拒绝""诊断信息不外泄"）；`main-startup.spec.ts` 的欢迎后端 mock 改为按 `configured` 判断，并删掉 4 个 Platform 授权用例 | Spec 3.2 P-3。原欢迎窗口依赖 DeepSeek 账号与官方 Key。**P-03a（T4 的临时补丁）随之删除**：它只为让原欢迎页在账号服务关掉后还能读状态，P-3 已不读账号服务，P-03a 的"每 1 秒重连账号 WebSocket"副作用也一并消失 | `docs\plan\evidence\T7\first-run.png`；`tsc -b apps/desktop` 通过；`welcome-window.spec.ts`、`lawbench-first-run.spec.ts`、`main-startup.spec.ts` 共 123 项通过；红测见 `docs\plan\evidence\T7\rework-P2-2-red-green.txt`、`rework2-red-green.txt` |
| P-12 | `apps/desktop-host/src/index.ts`（补丁 `P-12-desktop-no-office.patch`） | 不再挂载桌面端的 Office 组合（`desktop-office`：Office Skill 和 `load_workspace_dependencies` 工具） | 桌面端 Host 在补丁行之外直接挂载这两项，配置补丁关不掉；不关的话律师工作台会话里多出 `load_workspace_dependencies` 工具（实测抓包），Office Skill 也会进 Skill 目录（违反 Spec 3.1 工具白名单、Spec 10.1 Skill 只从两处加载）。主编排已同意（T4 返修令第 4 节） | 抓包工具名集合（`docs\plan\evidence\T7\request-tools.json`：11 个 `case_*` + `skill` + `ask_user_question`） |
| P-13 | `packages/client/ui-settings-general/src/client/index.ts`（补丁 `P-13-desktop-no-open-config.patch`） | 有桌面端标记（`globalThis.dshDesktop`）时不创建设置文档控制器，设置页不注册"打开配置文件"动作（`open-document`）；Web 界面不变 | 该按钮用系统编辑器打开桌面 profile 自己的 `cordis.patch.yml`，这一层叠在我方组合包补丁之后、改了即时重载，能改模型地址、重新打开被关掉的行（T4 第二轮复核 P2-A，已实测属实） | 打补丁前后设置页截图 `docs\plan\evidence\T4\settings-before-P13.png`、`settings-after-P13.png`；实测记录 `p2a-open-config-tests.txt` |
| P-6 | —（**不需要改源码**，T13 执行令 Q1） | 不改 `packages/api/remotes/src/client/index.ts`。界面插件（`legal-ui`）启动时自己 `ctx.remote.$mount` 一份手写的 `lawbench` 描述（`dsh-ext\ui\remote.ts`），再 `ctx.inject(['remote.lawbench', 'slots'], …)` 取子上下文调用，写法仍是 `ctx.remote.lawbench.<方法>()`。Host 端靠网关对无生成代码的远程服务的运行时回退（`packages/api/gateway/src/index.ts:743-830`，按 `typertRemote` 绑定和原型上的方法标记注册） | Spec 1.2 原写"要在官方 `api-remotes` 里加一行导入"，但那里导入的是 Typert 代码生成器的 `/remote` 产物，我方远程类是纯 JS、没有这份产物。网关的 `$mount` 对任何插件开放（`packages/api/gateway/src/client/index.ts:202-210`），只校验参数编解码为 `mode: 'strict'` 和命名空间不冲突；DSH 自己的实验插件 voice-input 也是这样挂载（`packages/experimental/client-ui-voice-input/src/client/mount.ts:60-65`）。直接在组件里读 `ctx.remote.lawbench` 会被 cordis 拒绝（"cannot get property … without inject"，实测），所以要先 `$mount` 再 `inject` | 桌面端设置页"律师工作台"调通 `setupState`（`docs\plan\evidence\T13\00-通路验证-设置页调用setupState.jpg`）；Host 方法表与界面描述一致由 `dsh-ext\tests\remote-methods.spec.ts` 守着（方法名、形参名，做过变异验证） |

## 换 DSH 提交时的核对清单（我方依赖、但不在补丁里的 DSH 内部写法）

| 依赖 | 在哪里用 | 怎么核对 |
|---|---|---|
| 对话区节点属性 `data-chat-flow-kind`，助手回答节点取值 `assistant-step`（`packages/client/ui-chat/src/client/chat/ChatNodeSeat.tsx:155`、`register-node-renderers.ts:42`）；回答里的文字是普通文字节点（`packages/client/ui-primitives/src/markdown/render.tsx:273-277`） | 点草稿正文里的出处打开原文（`dsh-ext\ui\citation-click.ts`，T13 后续项 A：插件内命中测试，不改源码） | `dsh-ext\tests\citation.spec.ts` “依赖的 DSH 对话区标记结构还在”一组会先变红；另在桌面端点一次出处实测 |

## 结论记录

| 事项 | 结论 | 依据 |
|---|---|---|
| 窗口条目（Spec 8.2〔待验证〕） | **只配一个 128K 条目**（Spec 8.2 备选）。pi-ai 把模型条目的 `id` 原样作为请求中的 `model` 发给网关，路由配置里没有单独的"上游模型名"字段（`packages/llm/llm-pi-ai/src/config.ts` 模型条目字段只有 id、name、contextWindow、maxTokens、input、reasoningEfforts、compat；pi-ai `openai-completions.js` 用 `model.id` 作请求 model）。同一路由下三个条目若都叫 `qwen38-27b`，id 重复无法区分，所以不能做三个窗口条目。律师选的窗口只控制 L1 长度和最大生成量，DSH 的历史压缩统一按 128K | 实测请求 `model` 为 `qwen38-27b`（`docs\plan\evidence\T4\request-tools.json`） |
| 思考档参数（Spec 8.1〔待验证〕） | `qwen-chat-template` 格式只发 `enable_thinking`、不发 `reasoning_effort`，所以改用 `thinkingFormat: chat-template` 加 `chatTemplateKwargs`：`enable_thinking` 取 `thinking.enabled`，`reasoning_effort` 取 `thinking.effort`（关闭档省略） | 四档实测见 `docs\plan\evidence\T4\request-tools.json` |
| "高"档的取值 | 6000D 不接受 `reasoning_effort: "high"`（400：只支持 xhigh（默认）、medium、low），界面"高"改发 `xhigh`。主编排已实测确认并改了 Spec 8.1、8.2 | 2026-09-29 实测 |
| 重试（Spec 8.3） | `llm-retry` 行没有配置项（写任何字段都报错），重试策略在 `llm-pi-ai` 路由的 `retryPolicy`：`mode: normal, maxRetries: 1`；默认可重试错误码只含空响应、限流、服务端、超时、传输错误，不含鉴权失败，401 / 403 不重试 | `packages/llm/llm/src/retry-policy.ts` |
| 凭据行 | 行 id 实为 `credentials`（插件 `@deepseek-ai/dsh-credentials-local`）。补丁不能改一行的插件名（`vendor/include/src/index.ts:115-118` 名字不符就跳过），所以 T7 把 `credentials` 行设 `disabled: true`，另插 `legal-credentials`（`lawbench-dsh/credentials`）提供同名服务（执行令 Q1） | `docs\plan\evidence\T7\plugin-inventory-desktop.json`：`include:credentials` 关、`include:legal-credentials` 启用 |
| 凭据管理器与 Python keyring（Spec 8.1〔待验证〕） | **对得上，不用改格式**：Node 侧经 PowerShell 调 `CredWriteW` 写"普通凭据"，目标名 `lawbench/LAWFIRM_KEY`、用户名 `lawbench`、内容 UTF-16LE；Python `keyring.get_password("lawbench/LAWFIRM_KEY", "lawbench")` 读到的值与首次配置页填入的一致 | `docs\plan\evidence\T7\credentials-check.txt`；`dsh-ext\dev\check-keyring.mjs` |
| 授权记录（凭据服务的 readRecord / modifyRecord 等） | DSH 自己的连接插件启动时要把浏览器会话密钥写成一条记录（`packages/client/connection/lib/index.js:330`），拒绝写入桌面端就起不来。T7 让记录只放进程内存（不落盘、不进凭据管理器），偏离执行令 Q2"写入拒绝"，已落注记件候主编排定 | `致ORCH-A-注记-T7凭据记录只放内存-*.md` |
| G-2：打开工作区时从 `cwd` 读取的内容 | 归 T17 | 主编排 T4 裁决 |
| Skill 目录先后（Spec 10.1） | preset 的 `customSkillDirs` 为 `[%ProgramData%\lawbench\skills, 内置目录]`：DSH 同一级内先到先得，管理员目录在前才能覆盖内置同名 Skill | 实测同名 Skill 加载到管理员目录那份（`docs\plan\evidence\T4\rework-runtime-tests.txt`） |

## 待办

| 归属 | 事项 |
|---|---|
| T20 | 打包后内置 Skill 目录由 Host 固定为 `<安装目录>\skills`，不再读环境变量 `LAWBENCH_SKILLS_DIR`（开发期才用它；不固定的话打包后内置 Skill 不加载，且环境变量能把 Skill 根目录指到任意位置） |
| T20 | `legal-host` 的启动命令、工作目录、服务端口范围目前由开发期环境变量 `LAWBENCH_SERVICE_CMD`、`LAWBENCH_SERVICE_CWD`、`LAWBENCH_SERVICE_PORTS`、`LAWBENCH_SERVICE_ENV` 给出；打包后固定为内置 Python 与安装目录 |
| T13 | ~~P-6：界面插件需要 `ctx.remote.lawbench` 时再做~~ 已结：不改源码，见上表 P-6 行 |
| T17（N38） | **模型回答里的外链图片会自动加载**：不用律师点，渲染时就向外网发请求，材料里的诱导内容可借它把东西带出去。位置：`packages/client/ui-primitives/src/markdown/render.tsx` 的图片渲染（`render.tsx:641-644` 的 `LoadedMarkdownImage`，`referrerPolicy="no-referrer"`，`http`/`https` 源直接加载）；链接的协议白名单 `sanitizeUrl`（`render.tsx:53-68`）放行 `http:`、`https:`、`mailto:`。同一个 `MarkdownText` 也用于推理摘要（`ui-chat/src/client/chat/ReasoningRow.tsx:70`）等处。线 A 按主编排 06:34 注记不拦不改，留给 T17 与源码补丁一起定（回答里的链接可点开属 N15，同归 T17） |
