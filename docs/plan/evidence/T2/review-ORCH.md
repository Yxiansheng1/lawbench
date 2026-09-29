# T2 复核记录（主编排亲核）

- 复核对象：`line-A` 提交 `ab53c3a`（基座 `5232cf8`）
- 复核分级：子模块指针、空骨架和文档，不含产品代码 → 主编排亲核（`PROJECT-PROFILE.md` 第 6 节）
- 复核时间：2026-09-29 19:24–19:30
- 复核方式：只读 `git show` / `git diff`，没有动 `D:\lawbench-A`

## 结论

**收货。** 工单 T2 的验收各条满足，合并进 `main`。

## 逐项核对

| 验收 / 核对项 | 做法 | 结果 |
|---|---|---|
| 改动面 | `git diff --name-only 5232cf8..ab53c3a` | 13 个文件，全部在 `.gitmodules`、`dsh`（指针）、`dsh-patches\`、`dsh-ext\`、`docs\plan\evidence\T2\` |
| 子模块指针等于固定提交 | `git ls-tree ab53c3a dsh`；线 A 工作目录里 `git -C dsh rev-parse HEAD` | 都是 `477b4f420553e8a52c2fbccc464d7561b239c443` |
| 子模块地址 | `.gitmodules` | `https://github.com/deepseek-ai/deepseek-harness`，与事实索引一致 |
| 子模块内不放我方文件 | 提交里 `dsh` 只有一个指针条目 | 是 |
| 桌面端开发模式能打开主窗口 | 看截图 `desktop-dev.png` | DSH 主窗口，标题"DSH 本地构建"，版本 `0.1.7-rc.2-477b4f4`；截图里没有其他应用的内容 |
| DSH 自带测试，失败项与我方无关并列明 | 读 `dsh-test-gui.txt` 末尾和失败清单 | 9190 过 / 3 败 / 6 跳；3 败是 `present-open.host.spec.ts`（创建符号链接 `EPERM`）和 `binary-rpc.host.spec.ts` 两条（约 10 秒超时）。此时我方没有改过 DSH 任何代码，`dsh-ext\` 是空骨架，失败与我方无关成立 |
| `dsh-patches\PATCHES.md` | 读文件 | 格式五列齐全（编号、文件、改法、原因、验证方法），空表 |
| `dsh-ext\` 骨架 | 读文件 | `package.json` 名 `lawbench-dsh`、`dsh.bundle.patch` 指向 `cordis.patch.yml`；空补丁；四个目录各一个 README |
| 事实索引两行回填 | 线 A 按执行令写在交付说明第 5 节 | 主编排已在合并时填入事实索引第 5 节 |
| 无机密入库 | 用 `.env.local` 里的 Key 值扫描整个 diff | 无命中 |

## 记录在案的三件事

1. **Electron 下载改用镜像**：线 A 交付说明写明"经 owner 当场批准"。这只影响开发机的环境变量，不进仓库的产品配置。T20 正式打包时改回官方源或手动放入缓存并核对校验值，已写进事实索引。
2. **`CI=true`**：DSH 装 git 钩子的脚本在 worktree 布局下会失败，设 `CI=true` 跳过。没有改 DSH 代码。三条线以后跑 DSH 命令都要设，已写进事实索引。
3. **符号链接权限**：这台开发机普通权限下建不了符号链接，T1、T2、T3 都遇到了。不挡开发；需要符号链接实测的用例（T3 的 3 个跳过项）留到盲测或验收时在开了开发者模式的机器上补跑。
