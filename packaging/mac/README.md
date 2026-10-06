# macOS 版打包（T28 第一阶段，Apple 芯片）

`build.sh` 是 `packaging\build.ps1` 的 Mac 对应物：同样的载荷（内置 Python 与依赖、工作台服务、契约、Skill、律所工具、LibreOffice、pandoc、两个小工具），同样分步。只能在 Apple 芯片的 Mac 上跑（GitHub Actions 的 `macos-15`，或借来的 Mac）。不需要任何密钥。

```bash
bash packaging/mac/build.sh            # 全部步骤
bash packaging/mac/build.sh --list     # 列出步骤
LAWBENCH_TOKENIZER=/path/tokenizer.json bash packaging/mac/build.sh
```

| 步骤 | 做什么 |
|---|---|
| preflight | 系统、架构、Node、版本号一致、契约已提交 |
| dsh | 按 `dsh-patches\PATCHES.md` 顺序打补丁（含 P-22），装依赖、构建；构建 dsh-ext |
| python | python-build-standalone 3.12.14 aarch64（DSH 为 mac-arm64 锁定的同一份），装 `[client.pip]` 钉版（去掉 pywin32），放入服务和契约 |
| tools | LibreOffice 26.8.0 官方 dmg 里的 `LibreOffice.app`（保留官方签名）、pandoc 3.11 arm64 与 GPL 许可文件、tokenizer |
| smalltools | PyInstaller 打 `长截图切分.app`、`格式互转.app`，ad-hoc 签名，放在 dmg 里与主程序并排 |
| skills / engines / lock | Skill 安装、律所工具（发票引擎的 Windows 运行环境包不带）、许可证表与载荷清单 |
| scan | 暂存目录里查 Key 样式字串、`.env.local` 变量名、构建机家目录路径 |
| package | 经 DSH 打包脚本出 arm64 dmg（`LAWBENCH_MAC_ADHOC=1`：无开发者证书、不公证、不带更新源）；afterPack 调 `sign-adhoc.sh`；成品 .app 再扫一遍；输出 dmg 与 `.sha256` |

载荷来源与 sha256 见 `packaging\versions.lock` 的 `[mac]` 段，每次构建都核对。

**tokenizer**：6000D 同款分词文件不是公开文件（与 Hugging Face 上的 Qwen3 不同），仓库里也没有。云上构建从本仓库 Release `assets-v1` 的 `tokenizer.json` 取（用户在 GitHub 网页手工上传一次），按 sha256 `87a7830d…` 核对，不符即失败。**`assets-v1` 必须是已发布的 Release（不能是草稿：工作流的只读令牌看不到草稿），并且要先建好**——查询出任何错误（网络、权限、找不到这个 Release）都直接失败；只有查询成功、但资产列表里确实没有 `tokenizer.json` 时，才照打无 tokenizer 的包：服务按估算计 token，dmg 文件名带 `-smoke-no-tokenizer`，Release 草稿正文第一行写"冒烟包，无 tokenizer，不得交付律师"。本地构建用 `LAWBENCH_TOKENIZER=<文件>`。

**工作流**（`.github\workflows\mac-build.yml`，手动触发）：build（只读令牌，跑全部第三方代码）→ release（唯一有写权限的 job，只建草稿，不跑项目代码）与 smoke（只读，干净 Mac 上装好冒烟）。dmg 太大放不进 artifact 存储，job 之间经 Actions 缓存传递（按本次运行编号，下游按 sha256 核对）。第三方 action 一律钉 commit SHA。

**签名**：第一阶段 ad-hoc（令 1424 第 3 条）。`sign-adhoc.sh` 由内到外签：先签所有 Mach-O 文件，再签内嵌的 .app / .framework，最后签主程序；**不用 `--deep`**，`LibreOffice.app` 保留 The Document Foundation 的原签名。开发者证书（候 owner N74）定了以后走 DSH 原有的签名与公证流程，`LAWBENCH_SIGN_IDENTITY` 预留。

## 律师 Mac 上怎么装（写进安装指引）

1. 打开 dmg，把"连越律师工作台"和两个小工具一起拖进"应用程序"。
2. 第一次打开会被 macOS 拦下（没有经过苹果公证）。到 **系统设置 → 隐私与安全性**，页面下方点 **"仍要打开"**，再确认一次。macOS 15 起右键"打开"不再能绕过，只能这样做。
   懂终端的同事也可以执行：`xattr -dr com.apple.quarantine "/Applications/连越律师工作台.app"`。
3. 第一次存 Key 时，macOS 可能问是否允许访问钥匙串，选"始终允许"（真机待验，令 1424 第 7 条）。
4. 卸载：把程序拖进废纸篓；数据目录在 `~/Library/Application Support/lawbench`、`~/Library/Application Support/lawbench-desktop`，需要时手工删除。
5. Mac 版暂不支持发票整理（律所的发票引擎只有 Windows 版，候 owner N77）。
6. 所外访问需另装 EasyTier 客户端（有 macOS 版），由我方技术人员配置。

**管理员共享 Skill 目录**（可选，第一阶段手工做）：管理员在终端执行
`sudo mkdir -p "/Library/Application Support/lawbench/skills" && sudo chmod 755 "/Library/Application Support/lawbench/skills"`，把要覆盖的 Skill 放进去。
