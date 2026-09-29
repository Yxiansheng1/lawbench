# 小工具

两个独立的小程序（Spec 13.1、13.2；PRD F-TOOL-01、F-TOOL-02）：Python + tkinter，不连网，不调用模型，原文件不动。打包（PyInstaller）在 T20。

| 目录 | 工具 | 运行 |
|---|---|---|
| `splitter\` | 长截图切分：优先切在消息之间的空白处，切不开时重叠 120 像素并标注"此处可能切到文字"；可设段高、批量、合并 PDF；结果在原图旁的"切分结果"文件夹 | `python -m splitter`（在 `tools\` 下） |
| `convert\` | 格式互转：doc / wps → docx、xls → xlsx、Word → PDF（LibreOffice）；文字版 PDF → Word（只保留文字和段落）；Markdown ↔ Word（pandoc）；图片 → PDF（Pillow）；批量；结果在原文件旁的"转换结果"文件夹，同名加 (2) | `python -m convert`（在 `tools\` 下） |

**LibreOffice 和 pandoc 的查找顺序**（`convert\finder.py`）：环境变量 `LAWBENCH_SOFFICE` / `LAWBENCH_PANDOC` → 已安装客户端的内置路径（`%LOCALAPPDATA%\Programs\<客户端目录>\resources\libreoffice\program\soffice.exe`、`…\resources\pandoc\pandoc.exe`；目录名待 T20 定）→ 小工具自带（程序所在目录下的 `libreoffice\`、`pandoc\`）→ 系统安装（`Program Files\LibreOffice`、`%LOCALAPPDATA%\Pandoc`、`Program Files\Pandoc`）→ PATH。都找不到时给出中文提示。

转换时先把原文件复制到临时目录，LibreOffice 的配置目录也放在这个临时目录里，转换完一起删除（不在系统里留下"最近打开的文件"）。

**测试**：`cd tools; python -m pytest -q tests`（需要 LibreOffice 和 pandoc；没有时相关用例跳过）。切分样本 `splitter\samples\` 的 3 张虚构聊天截图由 `make_samples.py` 生成。
