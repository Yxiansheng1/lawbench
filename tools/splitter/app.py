"""长截图切分 · 界面（tkinter）。不连网，不调用模型；原图不动。"""
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

IMAGE_TYPES = [("图片", "*.png *.jpg *.jpeg *.bmp *.webp"), ("所有文件", "*.*")]


class SplitterApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("长截图切分")
        root.geometry("720x520")
        self.files: list[Path] = []

        top = ttk.Frame(root, padding=10)
        top.pack(fill="x")
        ttk.Button(top, text="选择截图…", command=self.choose).pack(side="left")
        ttk.Label(top, text="  段高（像素）：").pack(side="left")
        self.height = tk.IntVar(value=core.DEFAULT_H)
        ttk.Spinbox(top, from_=500, to=10000, increment=100, textvariable=self.height, width=7).pack(side="left")
        self.pdf = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="合并为 PDF", variable=self.pdf).pack(side="left", padx=10)
        self.run_btn = ttk.Button(top, text="开始切分", command=self.run)
        self.run_btn.pack(side="right")

        ttk.Label(root, padding=(10, 0), foreground="#555",
                  text="优先在消息之间的空白处切开；切不开时重叠切分并提示。结果放在原图旁的"
                       f"“{core.OUT_DIR_NAME}”文件夹，原图不动。").pack(fill="x")

        self.listbox = tk.Listbox(root, height=18)
        self.listbox.pack(fill="both", expand=True, padx=10, pady=8)
        bottom = ttk.Frame(root, padding=(10, 0, 10, 10))
        bottom.pack(fill="x")
        self.progress = ttk.Progressbar(bottom, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True)
        ttk.Button(bottom, text="打开结果文件夹", command=self.open_out).pack(side="right", padx=(8, 0))

    def choose(self) -> None:
        names = filedialog.askopenfilenames(title="选择长截图", filetypes=IMAGE_TYPES)
        if names:
            self.files = [Path(n) for n in names]
            self.listbox.delete(0, "end")
            for f in self.files:
                self.listbox.insert("end", f"待处理：{f.name}")

    def run(self) -> None:
        if not self.files:
            messagebox.showinfo("长截图切分", "请先选择截图。")
            return
        try:
            h = int(self.height.get())
        except (tk.TclError, ValueError):
            messagebox.showerror("长截图切分", "段高请填数字。")
            return
        self.run_btn.state(["disabled"])
        self.listbox.delete(0, "end")
        self.progress["value"] = 0

        files, pdf = list(self.files), self.pdf.get()

        def work():
            res = []
            try:
                res = core.split_many(files, h, pdf,
                                      progress=lambda i, n: self.root.after(0, self._progress, i, n))
            except Exception:  # noqa: BLE001  兜底：结果一定显示、按钮一定恢复
                res = [(f, "无法处理：处理失败（程序内部错误）") for f in files]
            finally:
                self.root.after(0, self.show, res)

        threading.Thread(target=work, daemon=True).start()

    def _progress(self, i: int, n: int) -> None:
        self.progress["value"] = 100 * i / n

    def show(self, res) -> None:
        self.run_btn.state(["!disabled"])
        for src, r in res:
            if isinstance(r, str):
                self.listbox.insert("end", f"{src.name}：{r}")
                continue
            self.listbox.insert("end", f"{src.name}：切成 {len(r.outputs)} 段" + ("，已合并 PDF" if r.pdf else ""))
            for p, s in zip(r.outputs, r.segments):
                mark = f"　　⚠ {core.WARN}" if s.warn else ""
                self.listbox.insert("end", f"　　{p.name}（第 {s.top + 1}–{s.bottom} 行）{mark}")

    def open_out(self) -> None:
        if self.files:
            d = self.files[0].parent / core.OUT_DIR_NAME
            if d.exists():
                os.startfile(d)  # noqa: S606  只在 Windows 上用


def main() -> None:
    root = tk.Tk()
    SplitterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
