# T13 契约 1.4 客户端跟进·第一批（版本 1.4、"移除此材料"放开、导入枚举）· 独立复核记录（PASS）

- 复核时刻：2026-10-11 03:00–03:12 (+08:00)；复核员：一名 Opus 只读复核员（克隆 `D:\lawbench-rv\rv-A61`，实验目录 `rv-A61-exp`）
- target：line-A `c85e2ce`；基座 `d7ff3b4`（main，契约 1.4 已合）；dsh-ext 约 20 文件 +293/-205
- 裁决（主编排）：**PASS**。P3-1（连点两次）与 P3-3（版本不一致提示语）令 A 顺手小修后主编排亲核，再打第八版；P3-2 截图补一张；NOTE-1（服务不列回 removed）暂不改；NOTE-4 `.vite-temp` 时间变化判为线 A 自跑（A 当时在做第二批）。

## 复核员报告（原文摘要，路径已去用户名）

**结论：PASS。** 三条都做到；Host 删文件旧路撤净；请求只能按材料编号走；两处变异即红。

### Findings
- **P3-1 连点两次发两次请求**（范围内，不阻断）：在途时按钮仍可点、无防重入；服务端按案件加锁，第二次 already_removed，界面多弹一次提示，不会多删。修：在途置灰 + 一例。
- **P3-2 截图 3、4 同一张**（MD5 同）；交付说明"14 项"实为 13 项（全量 768 对得上）。修：补关掉弹框后的列表截图。
- **P3-3 1.4 客户端配 1.3 服务时律师看到"服务未启动，请稍后重试"**（旧行为）：Supervisor 正确停在 `version_mismatch` 并记日志，但 `unavailableText()` 只对 `failed` 给原因。修：加一句"组件版本不一致，请重新安装律师工作台"。
- **NOTE-1** "已移除"标注真服务走不到（`materials.py:605/:504` list 过滤 removed），属实，无害。**NOTE-2** 移除成功后列表刷新两次（`.then(reloadMats)` + 事件），无害。**NOTE-3** 第 3 条只需改文案，客户端无自有枚举；剩余"云同步"字样属 CASE_IN_SYNC_FOLDER 路。**NOTE-4** 借用期间 `D:\lawbench-A\dsh-ext\node_modules\.vite-temp`（空目录）修改时间两次变化；复核员对照跑不变，推测线 A 自跑。

### 核对
删文件旧路：grep `rm(`/`rmSync`/`unlink`/`.remove(`/`trash`/`materialRemove`/`removableMaterial`/`feature-flags`/`MATERIAL_REMOVE_ENABLED`/`REMOVE_DISABLED_TIP`，剩余命中只有粘贴图片临时文件、设置回滚、自检探针、凭据存储；`DeskDeps.remove` 与 `desk-node` 的 `rm` 已删；`remote-methods.ts` 无 `materialRemove`、无调用方。请求面：`materialsRemove` 路由走 `callApi` 先按契约校验（`materials_remove` schema `additionalProperties:false`，case_id + material_ids `minItems 1`/`maxItems 100`/`uniqueItems`/格式引用 common），旧带路径形状被拒（有用例）；渲染层拼编号：格式错 Host 拒、不在本案服务整请求拒（`materials.py:511`）。三种结果分开显示、failed 原样、`wiki_needs_update` 提示、取消不调接口均有用例；日志只 `api.call` method/ok/code/ms。wiki 卡 `shaMap` 跳过 removed（有用例）。版本：`CONTRACT_VERSION === '1.4'` 且等于 `contracts\VERSION`。变异：去确认框直接调 7 红；failed 当成功 1 红。全量 767/1/6（brand.spec 环境缺 `dsh\apps`，计入即 768/0/6）；tsc 0；check_ui_words 产品零命中；4 截图无用户名。

### 跑过的命令
`git diff d7ff3b4 c85e2ce`；各项 grep；vitest 全量（实验目录配置与 cacheDir）、`zz-exp.spec.ts`（EXP1 版本、EXP2 连点）、两处变异各跑一次、联接对照跑；tsc；check_ui_words。6 联接已 rmdir；借用三目录修改时间不变；克隆干净。
