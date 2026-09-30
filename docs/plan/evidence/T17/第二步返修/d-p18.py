# P-18 增补（1516 令小项②）：快捷键说明里不再列"@ 打开引用菜单"（@ 引用菜单已由配置关掉）。用法：python d-p18.py <dsh 根目录>
import io, sys
root = sys.argv[1].rstrip('\\/') + '/packages/client/ui-conversation/'
p = root + 'src/client/apply.ts'
s = io.open(p, encoding='utf-8', newline='').read()
nl = '\r\n' if '\r\n' in s else '\n'
s = s.replace('\r\n', '\n')
a = """      { id: 'fixed.slash' as ShortcutCommandId, label: () => t('shortcut.slash'), keys: ['/'],
        bindings: [{ code: 'Slash', modifiers: [] }], group: 'input' },
      { id: 'fixed.mention' as ShortcutCommandId, label: () => t('shortcut.mention'), keys: ['@'],
        bindings: [{ code: 'Digit2', modifiers: ['shift'] }], group: 'input' },
    ]"""
b = """      { id: 'fixed.slash' as ShortcutCommandId, label: () => t('shortcut.slash'), keys: ['/'],
        bindings: [{ code: 'Slash', modifiers: [] }], group: 'input' },
      // lawbench P-18: no "@ opens the reference menu" row; the @ reference menu is disabled in the lawyer workbench
    ]"""
assert s.count(a) == 1
io.open(p, 'w', encoding='utf-8', newline='').write(s.replace(a, b).replace('\n', nl))
print('P-18 delta ok')
