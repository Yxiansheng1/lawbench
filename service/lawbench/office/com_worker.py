"""Word / WPS 转 PDF 的子进程（Spec 12.3）：python -m lawbench.office.com_worker <progid> <源副本> <输出 pdf>

由 office/convert.py 在单独的子进程里启动，超时由父进程结束本进程和它让 COM 启动的 Word / WPS。
- DispatchEx：新起一个 Word / WPS 实例，不接管律师自己开着的那个；
- Visible=False、DisplayAlerts=0、AutomationSecurity=3（禁用宏，不持久）；
- Word：打开前把 Options.UpdateLinksAtOpen 关掉、用完恢复原值（这个选项会存进律师的 Word 设置；进程被超时
  结束时停在"关"，那是更安全的一边）；
- Documents.Open(只读、AddToRecentFiles=False、不弹格式转换确认)；ExportAsFixedFormat(out, 17)；
  关闭不保存；Quit()。不调用任何打印接口，不改默认打印机。
退出码：0 成功；2 COM 起不来（没装该程序）；3 打开或导出出错。只往 stdout 写一行 ok / 错误类名，不写路径和内容。
"""
from __future__ import annotations

import sys

WD_EXPORT_PDF = 17
FORCE_DISABLE_MACROS = 3  # msoAutomationSecurityForceDisable


def main(progid: str, src: str, out: str) -> int:
    import pythoncom
    import pywintypes
    import win32com.client

    pythoncom.CoInitialize()
    try:
        try:
            app = win32com.client.DispatchEx(progid)
        except pywintypes.com_error:
            print("no_app", flush=True)
            return 2
        restore = None
        try:
            app.Visible = False
            app.DisplayAlerts = 0
            try:
                app.AutomationSecurity = FORCE_DISABLE_MACROS
            except Exception:  # noqa: BLE001 WPS 没有这个属性
                pass
            try:
                restore = app.Options.UpdateLinksAtOpen
                app.Options.UpdateLinksAtOpen = False
            except Exception:  # noqa: BLE001
                restore = None
            doc = app.Documents.Open(src, False, True, False)   # FileName, ConfirmConversions, ReadOnly, AddToRecentFiles
            try:
                doc.ExportAsFixedFormat(out, WD_EXPORT_PDF)
            finally:
                doc.Close(0)
            print("ok", flush=True)
            return 0
        except Exception as e:  # noqa: BLE001
            print(type(e).__name__, flush=True)
            return 3
        finally:
            if restore is not None:
                try:
                    app.Options.UpdateLinksAtOpen = restore
                except Exception:  # noqa: BLE001
                    pass
            try:
                app.Quit(0)
            except Exception:  # noqa: BLE001
                pass
    finally:
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
