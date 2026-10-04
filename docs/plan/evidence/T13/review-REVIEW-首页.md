# 首页 + 第二轮 AMEND 修法（line-A `31e2b35`/`4da1282`/`0e5cf00`/`edb75e7`，T13/T20）· 复核记录（单人，八项清单）

- target：四提交，父 `3a9a343`（第二轮三提交 rebase 后）；复核克隆 `D:\lawbench-rv\rv-A38`
- 派发：Opus 5.5 只读复核员，2026-10-04 15:0x
- 归档：主编排于 2026-10-04 15:16 (+08:00) 从复核员交回原文抄录，未改内容

## 复核员原文## 结论先说
四个提交都在范围内。第二轮 AMEND 的 F1、F2、F3 和 F7 中的一项都已关闭，首页按执行令 1426 做到了，分流提示也改好了。我独立跑的全量测试、tsc、禁词检查、契约检查、补丁链检查都通过，7 条变异里 6 条变红。唯一没变红的一条只说明作者的测试没钉住某个写法，产品行为是对的。没有阻断问题。

## Findings
1. **P3：F1 作者自己的用例钉不住"按名字判断超时"**
   - 问题：把 `daily-case.ts` 里 `name === 'TimeoutError' || name === 'AbortError' ||` 删掉，作者的 `daily-case.spec` 仍然全绿（10/10）。原因是他构造的超时异常用的是英文消息，又不带字符串 code，删了这句也会被后面"英文、无字符串 code"那条兜住。
   - 影响：现在行为没问题。我补了一个探针：超时异常带中文消息时，只有名字判断能把它归成 SERVICE_UNAVAILABLE；删掉名字判断，探针变红（1 失败 / 5 通过）。也就是说，以后有人删掉这句，作者的测试拦不住。
   - 最小修复：在 `daily-case.spec` 加一例"name 是 TimeoutError、消息是中文"的超时。
   - 归类：独立后续。
2. **NOTE：截图里有本机用户名**
   - 问题：入库截图 `evidence\T13\首页\01…png` 和 `02…png` 的卡片路径里显示 `C:\Users\<用户>\Documents\…`，用户名是实名可见的。
   - 影响：不是 Key 或密码，CLAUDE.md 没有禁止；但复核口径要求证据里不出现本机用户名，以前的截图大概也有同样情况。
   - 归类：独立后续，由主编排决定要不要统一处理。
3. **NOTE：首页还读了一次 `getSettings`**
   - 首页为了显示律师姓名，额外读了设置（`loadSettingsIntoState`）。这是已有接口，不是新接口，也不读文件系统。
   - 和复核包写的"只走 caseRecent / materialsList / outputsList / getCapsules"字面上差这一个；执行令本身要求显示律师姓名，所以算合理。
4. **NOTE（臆测）：启动晚了可能把人拉回首页**
   - 日常事务如果过了很久才取到（比如服务启动慢、要重试 30 秒以上），取到后会调一次 `goHome`。
   - 如果这段时间律师已经切到设置页、但还没进任何案件，会被拉回首页。只出现在启动早期，影响很小，我没有实测。
5. **NOTE：两处证据小出入**
   - F7（空的"未归入案件"不显示）只有单元测试，没有修后的截图。截图 02 里还能看到"未归入案件"，因为它是在 `0e5cf00` 拍的，早于修复提交 `edb75e7`。
   - 作者说补丁链"17 个"，PATCHES.md 和磁盘上实际都是 16 个；140 个路径的数字对得上。

## 核对表
| 项 | 结论 | 独立证据 |
|---|---|---|
| 身份 | 符合 | 复核克隆 HEAD=`edb75e7`，状态干净；4 个提交作者都是 Yxiansheng1，父提交 `3a9a343` |
| 逐提交归类 | 符合 | `31e2b35`：T13 首页、P-21、改提示词。`4da1282`：T20 深色 logo。`0e5cf00`：T13 首页启动时重读。`edb75e7`：T13 第二轮 AMEND |
| P-21 只做排序和隐藏，不夹带 | 符合 | 逐段看过：`SidebarRoot` 只把面板按 order ≤ -1000 分上下两段；`WorkspaceBrowser` 只多一个"默认工作区且没有会话就不显示"的过滤；另外改 1 个旧测试、加 2 个新测试，没有别的改动 |
| F1 关闭 | 关闭 | 复核探针 6 例全过：①Node 真实的 `DOMException TimeoutError`（code 23）和 `AbortSignal.timeout` 的超时，都归 SERVICE_UNAVAILABLE；②服务返回 INTERNAL 时照传 INTERNAL，界面在重试名单里；③INVALID_ARGUMENT、CASE_IN_SYNC_FOLDER 照传。界面侧：先后返回"服务不可用、INTERNAL、云同步目录"三次，前两次重试（等待 2 次），第三次停下并在侧栏提示；INVALID_ARGUMENT 第 1 次就停 |
| F1 变异 | 见 Finding 1 | 删名字判断：作者用例**没变红**，我的探针变红。删"服务错误码照传"：作者用例变红 |
| F2 关闭 | 关闭 | `rightbar.spec` 两例都在。变异"openCase 只开材料"变红；变异"去掉每个会话只开一次"变红 |
| F3 关闭 | 关闭 | 直接用正式脚本的正则测，再走一遍整个扫描流程：`'…工作区\n…'` 命中（旧正则不命中）；`工作区\\临时` 放过；`工作区/成果` 放过；`\t`、`\u4e00` 命中 |
| F7 之一 | 关闭 | DSH 用例通过；变异"去掉空的默认工作区隐藏"变红 |
| 首页入口在"新会话"上方 | 符合 | DSH 新用例通过；变异"去掉分段"变红；`HOME_ORDER=-1000`；截图 01 可见 |
| 启动和首次配置后落首页 | 符合（静态核加作者截图） | 页面登记时只调一次 `selectPanel(HOME)`；日常事务打开后再 `goHome`；截图 02 是新数据目录首次配置后的画面 |
| 首页数据来源 | 符合 | 只调用 caseRecent、materialsList、outputsList、getCapsules，外加已有的 getSettings；`host` 没加方法，`contracts\` 没改；新增行里没有 fs、fetch、log |
| 最多 12 张卡片 | 符合 | 用例覆盖；变异"去掉上限"变红 |
| 日常事务排第一且样式区分 | 符合 | 有用例；浅蓝底加对话气泡图标；截图可见 |
| 空状态、底部技术支持一行 | 符合 | 有用例；两张截图都可见 |
| 拖入导入走原路径 | 符合 | 卡片仍调原来的 `startImport(c, paths, '案件卡片')`，不往上冒泡给 DSH；P-9 补丁没动 |
| 禁词为 0 | 符合 | `check_ui_words --dsh <我自己打完补丁的克隆>`：零命中 |
| 分流提示改词 | 符合 | `skills\capsules.default.json`、`docs\src\PRD.md`、`docs\PRD.html`、3 个界面夹具都改了；仓库里（除 evidence 外）已搜不到"本地工作区"；服务端胶囊用例 16 项通过；`check_examples` 通过 |
| T20 深色 logo | 符合 | 我在副本里重跑 `make_brand.py`：`brand-assets.ts` 除换行符外与提交一致，其余品牌素材零差异；截图 02 深色下是白字 logo；`brand.spec` 通过 |

## 八项清单
1. **契约一致**：通过。`contracts\` 没有改动，Host 没加方法。`serviceCode` 只是异常对象上多带的一个属性，不进任何数据格式。
2. **边界输入**：通过。12 张上限、只有日常事务、完全没有案件、文件夹不在原处（不能点、不能导入）都覆盖到了；`last_opened` 缺失时排在最后。
3. **错误路径**：通过。见 F1 的核对；首页读失败时显示"重试"，服务未就绪时显示"连接中"。
4. **日志不含正文**：通过。新增行里没有任何日志调用。
5. **路径闸门未被绕过**：通过。导入仍走 `startImport`，P-9 和 P-15 没动，首页不读文件系统。
6. **无外连**：通过。没有新增任何网络请求；我的实验也没起服务、没占端口。
7. **测试覆盖新代码**：基本通过。首页 5 例、右侧栏 2 例、F1 2 例、DSH 2 例。缺口是 Finding 1 那一条。
8. **无机密入库**：通过。diff 里没有 Key 或令牌；用户名的事见 Finding 2。

## 实际跑过的命令（都在 `D:\lawbench-rv\x38\`，都带超时）
- 把复核克隆克隆到 `x38\w` 并 detach 到 `edb75e7`。用 robocopy 拷依赖，重建 12 个联接。`w\dsh` 用联接只读指向 `D:\lawbench-A\dsh`。
- `node scripts\test.mjs`：43 个文件，**591 通过、6 跳过**。
- `tsc -p tsconfig.json --noEmit`：退出码 0。
- 干净 DSH 克隆在 `477b4f4` 上，按 PATCHES.md 顺序对 16 个补丁逐个 `apply --check` 再 `apply`：**全部 0 错**，改动路径 **140** 个。P-21 的 4 个文件与 `D:\lawbench-A\dsh` 的哈希一致（只读比较）。
- `check_ui_words.py --dsh x38\dshp`：零命中。`check_examples.py --skills skills`：通过。
- 服务端：`pytest tests\test_api_case.py tests\test_t3_rework.py -k capsule`，16 通过（PYTHONPATH 指向副本）。
- DSH：vitest 跑 `lawbench-top-panels` 和 `workspace-browser` 两个文件，108 通过。依赖用逐项联接，缓存落在我自己的真实目录里。
- 变异 7 条：dsh-ext 5 条加 DSH 2 条，见核对表。每条改完都逐字节复原并校验。
- 复核探针 `zz-rv-probe.spec.ts`（6 例，只放在副本里）。
- 重跑 `make_brand.py` 比对品牌素材。

## 残留审计
- 进程：没有起常驻进程，所有命令都是同步跑完的。
- 端口：19390–19399 没有监听。
- 目录：先用 `rmdir` 拆掉全部联接（指向作者树的：DSH 根依赖 37 个、包依赖 316 个，加 `w\dsh` 1 个；副本内部 12 个），确认重解析点为 0 后才删除 `D:\lawbench-rv\x38`，现在已不存在。
- 作者树：删完后 `D:\lawbench-A\dsh\node_modules\vitest` 和 `D:\lawbench-A\dsh-ext\node_modules\ajv` 都还在。
- 复核克隆 `rv-A38` 状态干净。`D:\lawbench-A` 和 `D:\lawbench-coord` 没有任何写入。

## 证据缺口
- 没有做桌面端真机实测，也没跑 DSH 全量构建：启动落首页、首次配置后落首页、深色切换，依据的是静态核对加作者截图。
- F7 修复后没有截图。
- Finding 4 只是推测，没有复现。

T13: PASS
T20: PASS

