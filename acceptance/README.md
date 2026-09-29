# 验收脚本与操作单

PRD 第 12 节"上线必过"全部 27 项（第 1–26 条和 16a）逐条对应到脚本或人工操作单；保密要求 SEC-01～SEC-14 的验证方法见 Spec 第 16 节。T22 全量验收时按本表执行，证据放 `docs\plan\evidence\T22\`。

- **脚本**在 `sec\`，用仓库 `.venv` 的 Python 运行（`.\.venv\Scripts\python acceptance\sec\<脚本>.py`）。每个脚本最后打印"结论：通过 / 不通过 / 前提不满足"，退出码 0 / 1 / 2，证据文件写到 `acceptance\_out\`（不进 git；可用环境变量 `LB_ACCEPT_OUT` 改位置）。证据里不写 Key、密码和案卷正文。
- **人工操作单**在 `manual\`。需要 SSH 登录服务器的步骤由用户执行，AI 不保存、不索要密码。
- 需要工作台服务的脚本读环境变量 `LB_URL`、`LB_TOKEN`（`manual\案件隔离.md` 写了怎么取）；需要 Key 的读仓库根 `.env.local`。

## 上线必过 27 项

| 项 | 内容（PRD 12） | SEC | 脚本 | 人工操作单 | 其他工单的自动测试 |
|---|---|---|---|---|---|
| 1 | 抓包只见律所两台服务器 | 03、10 | `sec\net_watch.ps1` | `manual\抓包.md` | — |
| 2 | 案件 A 读不到案件 B 和其他文件（含 `../`、链接、junction） | 05 | `sec\case_isolation.py` | `manual\案件隔离.md` | T3 路径闸门测试 |
| 3 | 植入越权指令无效；案件内配置、指令文件、Skill 不被加载 | 07 | `sec\injection_check.py` | `manual\越权植入.md` | T7、T17 |
| 4 | 原件哈希不变 | 08 | `sec\hash_originals.py`（验收前 snapshot、验收后 compare） | — | T5、T23 |
| 5 | 6000D、395（含硬盘和系统临时目录）和本机案件目录外都查不到测试案卷正文；395 每个请求结束后无残留 | 01、09、11、12 | 本机：`sec\find_leaks.py`（或 `find_leaks.ps1`）；395：`sec\residue_395.py` | `manual\395残留检查.md`、`manual\6000D残留检查.md` | T6（50 张图不落盘）、T17 |
| 6 | 无 Key / 停用 Key 不能用；局域网不能绕过网关 | 06、13 | `sec\key_check.py`、`sec\port_scan.py` | — | T6（Key 校验） |
| 7 | 覆盖清单准确，引用能回读原文 | — | — | `manual\功能验收.md` 第 7 项 | T5、T10 |
| 8 | 各格式能导入；外发数据与路由表和界面一致；几百页卷宗后台识别、进度、通知、断点续做 | 02 | `sec\net_watch.ps1`（路由部分） | `manual\功能验收.md` 第 8 项、`manual\抓包.md` | T5、T12、T14 |
| 9 | 395 停机时暂停并提示，恢复后继续，推理不受影响 | — | — | `manual\功能验收.md` 第 9 项 | T12 |
| 10 | Word / Markdown 导出；修订版在 Word、WPS 中逐条接受 / 拒绝，范围外提示 | — | — | `manual\功能验收.md` 第 10 项 | T15 |
| 11 | 参数生效，超限有提示 | — | — | `manual\功能验收.md` 第 11 项 | T8、T18 |
| 12 | 取消后服务端确实停止；断网、重启正常 | — | — | `manual\功能验收.md` 第 12 项 | T6（取消）、T12、T16 |
| 13 | 中文检索验证集全部命中 | — | — | `manual\功能验收.md` 第 13 项 | T9（`search-cases.json`） |
| 14 | 缺依据的法律内容都标"法律依据待律师核实" | — | — | `manual\功能验收.md` 第 14 项 | T18 |
| 15 | 14 个胶囊能打开；Skill 类都能跑通；成果可被后续 Skill 选用并记录版本 | — | — | `manual\功能验收.md` 第 15 项 | T13、T18 |
| 16 | 业务 Skill 符合六部分规格；必问问题规则；自检结果显示 | — | `contracts\check_examples.py --skills skills` | `manual\功能验收.md` 第 16 项 | T18 |
| 16a | 去水印后原件不变，印章、签名、手写批注未被去除，引用仍指向原件 | 12 | `sec\dewatermark_395.py` | `manual\395残留检查.md` 第 1 步 | T6（去水印测试）、T12 |
| 17 | 预算到上限停并存草稿；草稿确认后才进成果目录 | — | — | `manual\功能验收.md` 第 17 项 | T8、T15 |
| 18 | 长截图切分符合 F-TOOL-01 | — | — | `manual\功能验收.md` 第 18 项 | T19 |
| 19 | Windows 10 / 11 能安装运行，界面全中文 | 03 | — | `manual\功能验收.md` 第 19 项 | T20 |
| 20 | 案件文件夹位于云同步目录时拒绝打开并提示 | 14 | `sec\cloud_sync.py` | — | T3 |
| 21 | 拖入文件和文件夹复制进案件并解析；软件自己的附件目录为空；原文件和已有原件哈希不变 | 01、08 | `sec\dsh_locations.py`、`sec\hash_originals.py`、`sec\find_leaks.py` | `manual\功能验收.md` 第 21 项 | T5、T17 |
| 22 | 胶囊管理：排序、改名、隐藏、新增、恢复默认，重启后保持；没有删除入口 | — | — | `manual\功能验收.md` 第 22 项 | T13 |
| 23 | 案卷归档：生成四个文件，页码连续且与立卷申请书一致；办案结果未确认不能生成 | 08 | `sec\hash_originals.py`（归档后） | `manual\功能验收.md` 第 23 项 | T23 |
| 24 | 发票整理走完一期；全过程抓包只见两台服务器和本机 | 03 | `sec\net_watch.ps1`、`sec\engine_net_inventory.py` | `manual\抓包.md` 第 3 步 | T25 |
| 25 | 委托材料进入"01委托手续"、同名不覆盖；证件识别不发往服务器；窗口抓包只见本机 | 03 | `sec\net_watch.ps1`、`sec\engine_net_inventory.py` | `manual\抓包.md` 第 3 步 | T25、T26 |
| 26 | 刑期计算：跨月末、闰年、多段羁押样例正确 | — | — | `manual\功能验收.md` 第 26 项 | T24（`sentence-cases.json`） |

另有两份不属于 27 项、但同样要在盲测或 T22 做的：`manual\符号链接补跑.md`（开发机建不了文件符号链接而跳过的用例，换一台开了开发人员模式的机器补跑；OWNER 件 2026-09-29 19:31）；`manual\网络打印机.md`（默认打印机是连不上的网络打印机时，Word / WPS / LibreOffice 转换不卡住；Spec 12.3，OWNER 件 2026-09-29）。

## 脚本一览

| 脚本 | 做什么 | 前提 |
|---|---|---|
| `sec\find_leaks.py` / `find_leaks.ps1` | 案件目录外按字节搜索特征字符串（UTF-8、UTF-16LE），不跟随链接 | 无；搜索范围缺省为用户目录、AppData、临时目录、`$DSH_HOME`。T17 的 `scripts\find_leaks.ps1` 合并后改调它 |
| `sec\hash_originals.py` | 原件区 sha256 快照与比对 | 案件目录 |
| `sec\case_isolation.py` | 以案件 A 的 task_id 调 `/core/tool`，用 `../`、绝对路径、链接、联接、案件 B 材料名等越权参数读 | 工作台服务（T3）；`LB_URL`、`LB_TOKEN`、`LB_TASK_A` |
| `sec\injection_check.py` | 在 attack-01 副本的工作区里找读系统文件、加载 evil、外发的痕迹 | 已按操作单做过对话 |
| `sec\key_check.py` | 无 Key、错误 Key、停用 Key 调 6000D 和 395 | 在律所网络内；甲方开启 require_key；停用 Key 放 `LAWFIRM_REVOKED_KEY` |
| `sec\port_scan.py` | 两台服务器只开 8000 / 9000（运维端口 22、3389 只提示） | 在律所网络或 EasyTier 虚拟网内 |
| `sec\residue_395.py` | 打印 395 上要执行的搜索命令；判定结果文件 | 用户在 395 上执行 |
| `sec\dewatermark_395.py` | 真实 395 去水印前后红章、蓝色批注像素数不变，原件不变 | 395 已部署（T11）；`.env.local` 的测试 Key |
| `sec\cloud_sync.py` | OneDrive、"坚果云""百度网盘"目录下的案件被拒绝，普通目录能打开 | 工作台服务（T3） |
| `sec\dsh_locations.py` | Spec 3.3：附件目录为空、会话不在 `$DSH_HOME`、凭据文件无 Key、无溢出文件 | 客户端装好并走过一遍（T17 之后） |
| `sec\net_watch.ps1` | 运行期间相关进程的 TCP 远端地址与白名单比对，另列新增 DNS 解析 | 客户端在运行 |
| `sec\engine_net_inventory.py` | 引擎里的联网代码与已知清单（`engine_net_known.json`）比对；核对发票调用代码不引用它们 | 发票调用代码（T25）存在时才能给出"通过" |
