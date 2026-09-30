# 小工具

两个独立的小程序（Spec 13.1、13.2；PRD F-TOOL-01、F-TOOL-02）：Python + tkinter，不连网，不调用模型，原文件不动。打包（PyInstaller）在 T20。

| 目录 | 工具 | 运行 |
|---|---|---|
| `splitter\` | 长截图切分：优先切在消息之间的空白处，切不开时重叠 120 像素并标注"此处可能切到文字"；可设段高、批量、合并 PDF；结果在原图旁的"切分结果"文件夹 | `python -m splitter`（在 `tools\` 下） |
| `convert\` | 格式互转：xls → xlsx、Word（docx）→ PDF（LibreOffice）；文字版 PDF → Word（只保留文字和段落）；Markdown ↔ Word（pandoc）；图片 → PDF（Pillow）；批量；结果在原文件旁的"转换结果"文件夹，同名加 (2) | `python -m convert`（在 `tools\` 下） |

**LibreOffice 和 pandoc 的查找顺序**（`convert\finder.py`）：环境变量 `LAWBENCH_SOFFICE` / `LAWBENCH_PANDOC` → 已安装客户端的内置路径（`%LOCALAPPDATA%\Programs\<客户端目录>\resources\libreoffice\program\soffice.exe`、`…\resources\pandoc\pandoc.exe`；目录名待 T20 定）→ 小工具自带（程序所在目录下的 `libreoffice\`、`pandoc\`）→ 系统安装（`Program Files\LibreOffice`、`%LOCALAPPDATA%\Pandoc`、`Program Files\Pandoc`）→ PATH。都找不到时给出中文提示。

转换时先把原文件复制到临时目录，LibreOffice 的配置目录也放在这个临时目录里，转换完一起删除（不在系统里留下"最近打开的文件"）。

**依赖**：Pillow、numpy、pypdfium2、pypdf、python-docx、openpyxl、olefile（BSD 许可；`convert\extlinks.py` 留档的外链检查用，小工具第一版不调用）；外部程序 LibreOffice、pandoc。

**测试**：`cd tools; python -m pytest -q tests`（需要 LibreOffice 和 pandoc；没有时相关用例跳过）。切分样本 `splitter\samples\` 的 3 张虚构聊天截图由 `make_samples.py` 生成。

**第一版的限制**：格式互转不转换旧版 Word / WPS 文件（.doc、.wps）。按文件头判断，不是 docx（zip）的一律不交给转换程序，提示“暂不支持旧版 Word / WPS 文件。请用 Word 或 WPS 打开后另存为 .docx，再来转换。”改了扩展名的 docx 照常转换；.xls → .xlsx 不受影响。原因：旧版格式里以链接引用的图片，转换程序会联网去取，现有的外链检查没有经过独立验证（候 owner 清单 N24，用户 2026-09-30 选 ②）。`convert\extlinks.py` 和它的测试留档，工作台服务（T5）同一思路，小工具不调用。
