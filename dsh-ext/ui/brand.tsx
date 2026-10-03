// 侧栏品牌位（T14 派修 3）：产品名 + 我方版本号，替换原版的"DSH 本地构建 <DSH 构建号>"。
import { PRODUCT_NAME, PRODUCT_VERSION } from '../shared/product.ts'
import { C } from './kit.tsx'

export function BrandName() {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'baseline', gap: 6, minWidth: 0 }}>
      <span style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{PRODUCT_NAME}</span>
      <span style={{ fontSize: 11, color: C.sub }}>{PRODUCT_VERSION}</span>
    </span>
  )
}
