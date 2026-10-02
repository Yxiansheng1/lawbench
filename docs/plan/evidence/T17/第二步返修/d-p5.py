# P-5 增补（T17 第二步返修 B-F1）：输入框收文件时先问已登记的导入钩子，钩子接手就跳过聊天图片上限预检。
# 用法：python d-p5.py <dsh 根目录>
import io, sys
root = sys.argv[1].rstrip('\\/') + '/packages/client/ui-conversation/'


def edit(name, pairs):
    p = root + name
    s = io.open(p, encoding='utf-8', newline='').read()
    nl = '\r\n' if '\r\n' in s else '\n'
    s = s.replace('\r\n', '\n')
    for a, b in pairs:
        assert s.count(a) == 1, (name, a[:80], s.count(a))
        s = s.replace(a, b)
    io.open(p, 'w', encoding='utf-8', newline='').write(s.replace('\n', nl))


edit('src/client/contract/slots.ts', [
    ("""  addFiles: ((files: readonly File[], directories?: ReadonlySet<File>) => string | null) | undefined
  removeAttachment:""", """  addFiles: ((files: readonly File[], directories?: ReadonlySet<File>) => string | null) | undefined
  /**
   * lawbench P-5: offer one batch to the registered file-intake hooks before
   * any client-side attachment limit applies. Resolves to the taking hook's
   * result (rejection copy or null), or undefined when no hook took it.
   */
  intakeFirst?: ((files: readonly File[], directories?: ReadonlySet<File>) => string | null | undefined) | undefined
  removeAttachment:"""),
])
edit('src/client/apply.ts', [
    ("""          keyboard: undefined,
          addFiles: undefined,
""", """          keyboard: undefined,
          addFiles: undefined,
          intakeFirst: undefined,
"""),
    ("""        keyboard: shell,
        addFiles: (files, directories = new Set()) => {""", """        keyboard: shell,
        // lawbench P-5: the composer asks the hooks before its image-limit pre-check,
        // so a batch over the chat attachment limits still reaches the import hook.
        intakeFirst: (files, directories = new Set()) => {
          if (sessions.binding(sessionId) === undefined) return undefined
          for (const hook of intakeHooks) {
            const taken = hook(sessionId, files, directories)
            if (taken !== undefined) return taken
          }
          return undefined
        },
        addFiles: (files, directories = new Set()) => {"""),
])
edit('src/client/skeleton/InputBar.tsx', [
    ("  useSession, useInput, inputActions, keyboard, addFiles, removeAttachment, resolveDraftAttachments,",
     "  useSession, useInput, inputActions, keyboard, addFiles, intakeFirst, removeAttachment, resolveDraftAttachments,"),
    ("""    if (subagent !== null || addFiles === undefined || files.length === 0) return
    const rejected = ((): string | null => {""", """    if (subagent !== null || addFiles === undefined || files.length === 0) return
    // lawbench P-5: a registered import hook takes the batch before any chat attachment limit applies.
    const taken = intakeFirst?.(files, directories)
    if (taken !== undefined) {
      if (taken !== null) showToast(taken)
      return
    }
    const rejected = ((): string | null => {"""),
    ("  }, [subagent, addFiles, attachments, imageLimits, showToast, t])",
     "  }, [subagent, addFiles, intakeFirst, attachments, imageLimits, showToast, t])"),
])
edit('tests/input-bar.client.spec.tsx', [
    ("""  addFiles?: (files: readonly File[], directories?: ReadonlySet<File>) => string | null
""", """  addFiles?: (files: readonly File[], directories?: ReadonlySet<File>) => string | null
  /** lawbench P-5: the injected import-hook probe (absent = no hook registered). */
  intakeFirst?: (files: readonly File[], directories?: ReadonlySet<File>) => string | null | undefined
"""),
    ("""    addFiles: over?.addFiles ?? (() => null),
""", """    addFiles: over?.addFiles ?? (() => null),
    intakeFirst: over?.intakeFirst,
"""),
    ("""  it('announces the format problem before any limit when the batch holds a non-image', () => {""",
     """  it('lawbench P-5: a registered import hook takes batches over the chat image limits, with no limit toast', () => {
    const limits = {
      maxImageBytes: 1024 * 1024,
      maxImagesPerMessage: 20,
      maxMessageImageBytes: 200 * 1024 * 1024,
      maxImagePixels: 40_000_000,
      maxImageDimension: 2000,
      mediaTypes: ['image/png'] as const,
    }
    const png = (bytes: number, name: string) => new File([new ArrayBuffer(bytes)], name, { type: 'image/png' })
    for (const files of [
      Array.from({ length: 21 }, (_, i) => png(8, `scan-${i}.png`)),
      [png(1024 * 1024 + 1, 'big.png')],
    ]) {
      const intakeFirst = vi.fn(() => null)
      const result = bench({ addFiles: vi.fn(() => null), intakeFirst, imageLimits: limits })
      act(() => { attachmentOwner(result.slotCalls).onAddFiles(files) })
      expect(intakeFirst).toHaveBeenCalledWith(files, undefined)
      expect(result.props.addFiles).not.toHaveBeenCalled()
      expect(result.view.queryByRole('alert')).toBeNull()
      cleanup()
    }
    // A hook that declines (undefined) leaves the limit pre-check in force.
    const declined = bench({ addFiles: vi.fn(() => null), intakeFirst: vi.fn(() => undefined), imageLimits: limits })
    act(() => { attachmentOwner(declined.slotCalls).onAddFiles([png(1024 * 1024 + 1, 'big.png')]) })
    expect(declined.view.getByRole('alert').textContent).toContain('单张图片不能超过 1MB')
    cleanup()
    // A hook that refuses shows its own copy.
    const refused = bench({ addFiles: vi.fn(() => null), intakeFirst: vi.fn(() => '材料只能导入到案件里'), imageLimits: limits })
    act(() => { attachmentOwner(refused.slotCalls).onAddFiles([png(8, 'a.png')]) })
    expect(refused.view.getByRole('alert').textContent).toContain('材料只能导入到案件里')
  })

  it('announces the format problem before any limit when the batch holds a non-image', () => {"""),
])
print('P-5 delta ok')
