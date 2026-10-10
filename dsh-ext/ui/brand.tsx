// 侧栏品牌位（T14 派修 3）：产品名，替换原版的"DSH 本地构建 <DSH 构建号>"。
// 令 1818 第 1 条（用户 2026-10-10）：侧栏不再带版本号——带构建号后太长，把"连越律师工作台"挤成了"连越…"。
// 版本号（0.1.0+<构建号>）只在设置的"关于"里显示（ui\settings.tsx）。
// 律所 logo 常驻在产品名左侧（DSH 的 sidebar.brand.mark 位，高 24）；侧栏底部常驻"技术支持"一行（执行令 2026-10-04 11:56 第 1、2 条）。
import { FIRM_NAME, PRODUCT_NAME, VENDOR_NAME } from '../shared/product.ts'
import { FIRM_LOGO, FIRM_LOGO_DARK, VENDOR_MARK } from './brand-assets.ts'
import { C } from './kit.tsx'

export const VENDOR_LINE = `技术支持：${VENDOR_NAME}`

export function BrandName() {
  return (
    <span data-lawbench-brand-name="" style={{ display: 'inline-flex', alignItems: 'baseline', minWidth: 0 }}>
      <span style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{PRODUCT_NAME}</span>
    </span>
  )
}

/**
 * 律所 logo（DSH 给 size：品牌位的高度）。侧栏品牌位一行高 24、Windows 下整体下移 1 px，满高时底下"LIANYUE"一行被切，
 * 所以比给的高度小 2 px（真机截图核过）；空白会话大标题旁（conversation.hero.brand.mark，size 34）同样用它，替换 DSH 的鲸鱼标。
 */
export function BrandMark({ size = 24 }: { size?: number }) {
  ensureLogoStyle()
  const style = { height: Math.max(12, size - 2), width: 'auto' }
  return (
    <span style={{ display: 'inline-flex' }}>
      <img className="lb-logo-light" src={FIRM_LOGO} alt={FIRM_NAME} style={style} />
      <img className="lb-logo-dark" src={FIRM_LOGO_DARK} alt={FIRM_NAME} style={style} />
    </span>
  )
}

/**
 * 深色界面换白字版律所 logo（令 1426 真机截图时发现深色下"连越 LIANYUE"看不见）。DSH 把当前明暗写在根元素的
 * color-scheme 上（跟系统或律师在设置里选的），按它切换；只加一次样式。
 */
export const LOGO_STYLE = '.lb-logo-dark{display:none}:root[style*="color-scheme: dark"] .lb-logo-light{display:none}:root[style*="color-scheme: dark"] .lb-logo-dark{display:block}.lb-logo-light{display:block}'
function ensureLogoStyle(): void {
  if (typeof document === 'undefined' || document.getElementById('lb-logo-style')) return
  const el = document.createElement('style')
  el.id = 'lb-logo-style'
  el.textContent = LOGO_STYLE
  document.head.appendChild(el)
}

/**
 * 主窗口右下角常驻的技术支持一行（令 1515 第 1 条，用户："把技术公司的信息固定在右下角"）：固定在窗口一角，所有页面可见，
 * 不随滚动；不接鼠标（pointer-events: none），不挡下面的按钮。首页底部、侧栏底部那两行去掉；首次配置页（独立窗口）和"关于"保留。
 */
export function VendorCorner() {
  return (
    <div data-lawbench-vendor-corner="" style={{ position: 'fixed', right: 12, bottom: 6, zIndex: 5, pointerEvents: 'none', opacity: 0.75 }}>
      <VendorLine />
    </div>
  )
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
