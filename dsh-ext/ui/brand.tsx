// 侧栏品牌位（T14 派修 3）：产品名 + 我方版本号，替换原版的"DSH 本地构建 <DSH 构建号>"。
// 律所 logo 常驻在产品名左侧（DSH 的 sidebar.brand.mark 位，高 24）；侧栏底部常驻"技术支持"一行（执行令 2026-10-04 11:56 第 1、2 条）。
import { FIRM_NAME, PRODUCT_NAME, PRODUCT_VERSION, VENDOR_NAME } from '../shared/product.ts'
import { FIRM_LOGO, VENDOR_MARK } from './brand-assets.ts'
import { C } from './kit.tsx'

export const VENDOR_LINE = `技术支持：${VENDOR_NAME}`

export function BrandName() {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'baseline', gap: 6, minWidth: 0 }}>
      <span style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{PRODUCT_NAME}</span>
      <span style={{ fontSize: 11, color: C.sub }}>{PRODUCT_VERSION}</span>
    </span>
  )
}

/** 律所 logo（DSH 给 size：品牌位的高度）。 */
export function BrandMark({ size = 24 }: { size?: number }) {
  return <img src={FIRM_LOGO} alt={FIRM_NAME} style={{ height: size, width: 'auto', display: 'block' }} />
}

/** "技术支持：上海莫来特智能科技有限公司"，带小标志。侧栏收起（wide 为假）时只留标志，全称放在提示里。 */
export function VendorLine({ wide = true }: { wide?: boolean }) {
  return (
    <div title={VENDOR_LINE} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 8px', fontSize: 11, color: C.faint, minWidth: 0 }}>
      <img src={VENDOR_MARK} alt="" style={{ height: 16, width: 'auto', flex: 'none' }} />
      {wide ? <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{VENDOR_LINE}</span> : null}
    </div>
  )
}
