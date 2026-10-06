// 界面里少数按平台不同的说法（T28 macOS 版）。界面进程拿不到 process.platform，看 navigator。
type Nav = { platform?: string; userAgent?: string } | undefined

export function isMac(nav: Nav = (globalThis as { navigator?: Nav }).navigator): boolean {
  return /mac/i.test(nav?.platform ?? '') || /Macintosh/.test(nav?.userAgent ?? '')
}

/** Key 存在哪（设置页"个人 Key"一栏）。 */
export const keyStoreName = (mac = isMac()): string => (mac ? '钥匙串' : 'Windows 凭据管理器')

/** Mac 版不能用的功能统一说法（令 1424 第 1 条：发票引擎只有 Windows 版）。 */
export const MAC_NO_INVOICE = 'Mac 版暂不支持发票整理'
