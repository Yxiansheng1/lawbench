# DSH 补丁台账

DSH 以子模块 `dsh\` 固定在提交 `477b4f420553e8a52c2fbccc464d7561b239c443`，不跟随上游。子模块内不放我方文件；对 DSH 源码的每一处改动都以补丁文件存在本目录并在此登记。子模块指针始终保持固定提交，补丁在工作区应用。

**应用**（在仓库根目录）：

```powershell
git -C dsh apply ..\dsh-patches\P-10-profile-lawbench-dsh.patch
git -C dsh apply ..\dsh-patches\P-03a-welcome-no-account.patch
git -C dsh apply ..\dsh-patches\P-12-desktop-no-office.patch
```

应用后重新 `pnpm install`（P-10 改了依赖）和 `pnpm run build`（见事实索引第 5 节的开发命令）。换 DSH 提交时逐条重做并重新核对。

| 编号 | 文件（相对 `dsh\`） | 改法 | 原因 | 验证方法 |
|---|---|---|---|---|
| P-10 | `packages/boot/app-boot/src/profile.ts`；`apps/cli/package.json`；`pnpm-lock.yaml`（补丁 `P-10-profile-lawbench-dsh.patch`） | `PROFILE_TEMPLATES.web.bundles` 末尾加 `lawbench-dsh`；`@deepseek-ai/dsh`（`apps/cli`）依赖加 `"lawbench-dsh": "link:../../../dsh-ext"`，锁文件随之更新 | Spec 14.1、3.2 P-10：我方组合包进入桌面端 profile（桌面端用 `PROFILE_TEMPLATES.web` 初始化，无单独 desktop 模板） | 删掉旧 profile（或换一个空的 `DSH_HOME`）后启动，新 profile 的 `package.json` 中 `dsh.profile.bundles` 末尾是 `lawbench-dsh`；启动日志无 "skipping profile bundle"；插件树见 `docs\plan\evidence\T4\plugin-tree.txt` |
| P-03a | `apps/desktop/src/welcome-backend.ts`（补丁 `P-03a-welcome-no-account.patch`） | 读欢迎状态时，账号服务调用失败按"未登录"处理 | 补丁关掉 `deepseek-account` 行后，桌面端启动时欢迎状态读取失败，报 `desktop welcome: Web RPC failed`，主窗口进不了工作区（Spec 3.1"关掉某行导致其他插件加载失败的，按报错处理"）。临时处理，P-3（我方首次配置页）整体替换欢迎窗口时一并去掉 | 应用后启动，日志无 `desktop welcome` 错误，进入工作区 |
| P-12 | `apps/desktop-host/src/index.ts`（补丁 `P-12-desktop-no-office.patch`） | 不再挂载桌面端的 Office 组合（`desktop-office`：Office Skill 和 `load_workspace_dependencies` 工具） | 桌面端 Host 在补丁行之外直接挂载这两项，配置补丁关不掉；不关的话律师工作台会话里多出 `load_workspace_dependencies` 工具（实测抓包），Office Skill 也会进 Skill 目录（违反 Spec 3.1 工具白名单、Spec 10.1 Skill 只从两处加载）。**Spec 3.2 未列此项，待主编排确认** | 抓包工具名集合恰为 {skill, ask_user_question, case_ping}（`docs\plan\evidence\T4\request-tools.json`） |

## 结论记录

| 事项 | 结论 | 依据 |
|---|---|---|
| 窗口条目（Spec 8.2〔待验证〕） | **只配一个 128K 条目**（Spec 8.2 备选）。pi-ai 把模型条目的 `id` 原样作为请求中的 `model` 发给网关，路由配置里没有单独的"上游模型名"字段（`packages/llm/llm-pi-ai/src/config.ts` 模型条目字段只有 id、name、contextWindow、maxTokens、input、reasoningEfforts、compat；pi-ai `openai-completions.js` 用 `model.id` 作请求 model）。同一路由下三个条目若都叫 `qwen38-27b`，id 重复无法区分，所以不能做三个窗口条目。律师选的窗口只控制 L1 长度和最大生成量，DSH 的历史压缩统一按 128K | 实测请求 `model` 为 `qwen38-27b`（`request-tools.json`） |
| 思考档参数（Spec 8.1〔待验证〕） | `qwen-chat-template` 格式只发 `enable_thinking`、不发 `reasoning_effort`，所以改用 `thinkingFormat: chat-template` 加 `chatTemplateKwargs`：`enable_thinking` 取 `thinking.enabled`，`reasoning_effort` 取 `thinking.effort`（关闭档省略） | 四档实测见 `request-tools.json` |
| "高"档的取值 | 6000D 不接受 `reasoning_effort: "high"`（400：只支持 xhigh（默认）、medium、low），界面"高"改发 `xhigh`。**与 Spec 8.2 表不一致，待主编排定夺并修订 Spec 8.2（流水线列同样受影响）** | 2026-09-29 实测，见 `request-tools.json` 中"高（high，网关拒绝 400）"一条 |
| 重试（Spec 8.3） | `llm-retry` 行没有配置项（写任何字段都报错），重试策略在 `llm-pi-ai` 路由的 `retryPolicy`：`mode: normal, maxRetries: 1`；默认可重试错误码只含空响应、限流、服务端、超时、传输错误，不含鉴权失败，401 / 403 不重试 | `packages/llm/llm/src/retry-policy.ts` |
| `credentials-local` 行 | 固定提交中不存在此行 id（Spec 3.1 表中的行）。凭据插件替换留给后续工单核对 | 全部组合包补丁文件检索 |
| G-2：打开工作区时从 `cwd` 读取的内容 | 未在 T4 核对（工单未列），留给后续工单 | — |
