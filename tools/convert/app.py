"""格式互转 · 界面（tkinter）。不连网，不调用模型；原文件不动。"""
from __future__ import annotations

import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    from . import core
except ImportError:          # 直接运行 app.py 或打包后的入口
    import core  # type: ignore


class ConvertApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("格式互转")
        root.geometry("720x520")
        self.files: list[Path] = []
        self.busy = False
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        top = ttk.Frame(root, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="转换：").pack(side="left")
        self.kind = tk.StringVar(value=core.KINDS[0].label)
        box = ttk.Combobox(top, textvariable=self.kind, state="readonly", width=32,
                           values=[k.label for k in core.KINDS])
        box.pack(side="left")
        box.bind("<<ComboboxSelected>>", lambda e: self._update_note())
        ttk.Button(top, text="选择文件…", command=self.choose).pack(side="left", padx=10)
        self.run_btn = ttk.Button(top, text="开始转换", command=self.run)
        self.run_btn.pack(side="right")

        self.note = ttk.Label(root, padding=(10, 0), foreground="#b45309")
        self.note.pack(fill="x")
        ttk.Label(root, padding=(10, 0), foreground="#555",
                  text=f"结果放在原文件旁的“{core.OUT_DIR_NAME}”文件夹，原文件不动；"
                       "同名时自动加(2)，不覆盖。").pack(fill="x")
        self.listbox = tk.Listbox(root, height=18)
        self.listbox.pack(fill="both", expand=True, padx=10, pady=8)
        bottom = ttk.Frame(root, padding=(10, 0, 10, 10))
        bottom.pack(fill="x")
        self.progress = ttk.Progressbar(bottom, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True)
        ttk.Button(bottom, text="打开结果文件夹", command=self.open_out).pack(side="right", padx=(8, 0))
        self._update_note()

    def current(self) -> core.Kind:
        return next(k for k in core.KINDS if k.label == self.kind.get())

    def _update_note(self) -> None:
        key = self.current().key
        self.note["text"] = {"pdf2docx": core.PDF_TO_WORD_NOTE, "md2docx": core.IMAGES_NOTE,
                             "docx2md": core.IMAGES_NOTE, "doc2docx": core.LEGACY_WORD_REASON,
                             "word2pdf": core.LEGACY_WORD_REASON}.get(key, "")

    def on_close(self) -> None:
        if self.busy:
            messagebox.showinfo("格式互转", "转换进行中，请等它结束。")
            return
        self.root.destroy()

    def choose(self) -> None:
        k = self.current()
        pattern = " ".join(f"*{e}" for e in k.inputs)
        names = filedialog.askopenfilenames(title="选择文件", filetypes=[(k.label, pattern), ("所有文件", "*.*")])
        if names:
            self.files = [Path(n) for n in names]
            self.listbox.delete(0, "end")
            for f in self.files:
                self.listbox.insert("end", f"待转换：{f.name}")

    def run(self) -> None:
        if not self.files:
            messagebox.showinfo("格式互转", "请先选择文件。")
            return
        key = self.current().key
        self.busy = True
        self.run_btn.state(["disabled"])
        self.listbox.delete(0, "end")
        self.progress["value"] = 0
        files = list(self.files)

        def work():
            res = []
            try:
                res = core.convert_many(key, files,
                                        progress=lambda i, n: self.root.after(0, self._progress, i, n))
            except Exception:  # noqa: BLE001  兜底：结果一定显示、按钮一定恢复
                res = [(f, core.INTERNAL, []) for f in files]
            finally:
                self.root.after(0, self.show, res)

        threading.Thread(target=work, daemon=True).start()

    def _progress(self, i: int, n: int) -> None:
        self.progress["value"] = 100 * i / n

    def show(self, res) -> None:
        self.busy = False
        self.run_btn.state(["!disabled"])
        for src, r, notes in res:
            if isinstance(r, Path):
                self.listbox.insert("end", f"{src.name} → {r.name}")
            else:
                self.listbox.insert("end", f"{src.name}：{r}")
            for n in notes:
                self.listbox.insert("end", f"　　⚠ {n}")

    def open_out(self) -> None:
        if self.files:
            d = self.files[0].parent / core.OUT_DIR_NAME
            if d.exists():
                os.startfile(d)  # noqa: S606  只在 Windows 上用


def main() -> None:
    core.cleanup_stale()          # 上次转换中途被强行关掉时留下的临时目录
    root = tk.Tk()
    ConvertApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
