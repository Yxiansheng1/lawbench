# 界面假数据（fixtures）

用途：T13 执行令 Q11——按契约自造的虚构假数据，只供界面开发和截图，不进 `contracts\`。案件、人名、公司、金额、路径全部是虚构的，不含 Key。

## 命名规则

- `<接口名>.json`：该接口 `$defs/response` 的成功响应（完整外壳 `{"ok":true,"value":...}`）。
- `<接口名>.fail.json`：失败响应 `{"ok":false,"error":{code,message}}`，message 为面向律师的中文提示。
- `<接口名>.req.json`：该接口 `$defs/request` 的请求样例。
- 接口名即 `contracts\api\<接口名>.schema.json`。
- `capsules.json`、`capsules_reset.json`、`capsules.req.json` 取自 `skills\capsules.default.json`（配置，不是案件数据）。

校验：`node scripts/test.mjs tests/fixtures.spec.ts`（`tests\fixtures.spec.ts` 按契约逐个校验，并检查案件编号一致、`dewatermark` 为 false、不含 `sk-`）。

## 虚构案件

- case_id：`8c5e2a17-4b9d-4f36-a1c8-6d2e9b073f54`（周某诉青禾贸易借款合同纠纷，虚构）
- 材料 M0001–M0009，涵盖已解析、待识别、识别中、失败、原件已删除等状态；识别任务、出处、任务、wiki 建议都引用这些编号。
- 任务：完成且出处核对通过 `T-20260929093000-7c1f`；完成但未通过 `T-20260929101000-e5a3`；运行中 `T-20260929141500-b2e8`；失败 `T-20260928170000-04d9`；流水线运行中 `P-20260929103000-5f60`。

## contracts\examples\ 缺的样例

依据 `contracts\examples\manifest.json`（截至本次检查）。“成功响应”指 `$defs/response` 的成功样例。

| 接口 | 成功响应样例 | 备注 |
|---|---|---|
| case_open | 缺 | 只有 fail 样例 |
| case_recent | 缺 | |
| materials_scan | 缺 | 仅作为 materials_import 响应里的 scan 出现 |
| materials_import | 有 | `api_materials_import.res.json` |
| materials_list | 缺 | |
| ocr_submit | 缺 | 只有请求样例 |
| ocr_list | 有 | `api_ocr_list.res.json` |
| ocr_cancel | 缺 | |
| task_create | 缺 | |
| pipeline_run | 缺 | |
| pipeline_status | 缺 | |
| pipeline_cancel | 缺 | |
| tasks_list | 缺 | |
| redline | 缺 | |
| wiki_suggestions | 有 | `api_wiki_suggestions.res.json` |
| outputs_confirm | 缺 | |
| source | 有 | `api_source.res.json`（page_png_base64 为省略写法，不能直接校验） |
| search | 缺 | |
| capsules / capsules_reset | 缺 | 仅有 skill_capsules.json（文件契约） |
| archive_build | 缺 | 只有 fail 样例 |
| invoice_run | 缺 | 只有请求样例 |
| retainer_driver | 缺 | |
| connection_test、settings | 缺 | 本目录未做，界面另用 |
