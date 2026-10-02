# 品牌素材

logo 原件放在仓库根 `D:\lawbench\logo\`（原件不改）。打安装包（工单 T20）时，从原件转出下表所需的文件放进本目录；缺的用占位图 `placeholder-*.png`，并在 T20 交付说明中列出。

| 本目录文件 | 来源 | 要求 |
|---|---|---|
| `firm-logo.png` | `logo\连越律师事务所-logo.png`（律所，主品牌） | 透明背景 PNG，宽度不小于 512 像素 |
| `vendor-logo.png` | `logo\技术公司-logo2.jpg`（技术公司，"技术支持"；用户 N58，2026-10-02 定用这一版）。JPG 白底无透明通道，近白色转透明 | 透明背景 PNG，宽 768 |
| `vendor-mark.png` | 同上，去掉下方标语行，只留圆形标志和"Ai"（小尺寸用：关于面板、安装界面角标） | 透明背景 PNG，高 256 |
| `app-icon.png` / `.ico` | 由律所 logo 裁成方形 | 正方形，1024×1024 PNG，另出 Windows `.ico` |
| `names.txt` | 第一行律所全称"广东连越（深圳）律师事务所"；第二行软件名称（**待定**） | UTF-8 文本 |

原件分辨率不够或背景不透明时，在 T20 交付说明中写明，交主编排决定。

**生成**（T20 步骤 1）：仓库根下 `python packaging\brand\make_brand.py`（要 Pillow），上表文件和下面这些都由它从 `logo\` 原件生成，可重复：
- `installer-sidebar.bmp`：NSIS 安装向导左侧图（164×314）。
- `desktop\`：桌面端补丁 P-4 要换的图，目录结构同 `dsh\apps\desktop`（`resources\` 下的应用图标和托盘图标，`installer\assets\` 下的安装界面品牌图——右下角是技术公司角标，`renderer\assets\vendor-logo.png` 是关于面板"技术支持"一行旁的技术公司标志），打完 P-4 补丁后整个拷进去（见 `dsh-patches\PATCHES.md` 应用步骤）。

现状：律所原件是透明 PNG（1830×666），够用。技术公司 logo 用 `技术公司-logo2.jpg`（1639×960 白底 JPG，没有透明通道）：`vendor-logo.png`、`vendor-mark.png` 是把近白色转成透明得到的；深色、浅色底上看过（`docs\plan\evidence\T20\logo\`），没有明显毛边。`技术公司-logo.png`（带公司全称的横版）不再用。软件名称未定，`names.txt` 第二行和 P-4 里暂用"连越律师工作台"。
