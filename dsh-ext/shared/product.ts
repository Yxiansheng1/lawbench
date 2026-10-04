// 产品名与版本（T14 派修 3：侧栏品牌位显示我方产品名和版本，不显示"DSH 本地构建 0.1.7-rc.2-…"）。
// 产品名是 packaging\brand\names.txt 的占位名（候 owner N58），与 dsh\apps\desktop 的 LAWBENCH_PRODUCT（P-4）一起改。
// 版本与 service\pyproject.toml 的 version 一致；正式版本号的规则候主编排定（T20 发版时一并定），这里只放一处。
export const PRODUCT_NAME = '连越律师工作台'
export const PRODUCT_VERSION = '0.1.0'
/** 技术公司全称（执行令 2026-10-04 11:56 第 2 条，用户定）：侧栏底部、首次配置页底部、关于里的"技术支持"一行。 */
export const VENDOR_NAME = '上海莫来特智能科技有限公司'
/** 律所全称（packaging\brand\names.txt 第一行）。 */
export const FIRM_NAME = '广东连越（深圳）律师事务所'
