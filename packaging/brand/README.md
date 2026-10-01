# 品牌素材

logo 原件放在仓库根 `D:\lawbench\logo\`（原件不改）。打安装包（工单 T20）时，从原件转出下表所需的文件放进本目录；缺的用占位图 `placeholder-*.png`，并在 T20 交付说明中列出。

| 本目录文件 | 来源 | 要求 |
|---|---|---|
| `firm-logo.png` | `logo\连越律师事务所-logo.png`（律所，主品牌） | 透明背景 PNG，宽度不小于 512 像素 |
| `vendor-logo.png` | `logo\技术公司-logo.png`（我方，"技术支持"）；`技术公司-logo2.jpg` 是另一版，JPG 无透明背景，只在需要时备用 | 透明背景 PNG，宽度不小于 256 像素 |
| `app-icon.png` / `.ico` | 由律所 logo 裁成方形 | 正方形，1024×1024 PNG，另出 Windows `.ico` |
| `names.txt` | 第一行律所全称"广东连越（深圳）律师事务所"；第二行软件名称（**待定**） | UTF-8 文本 |

原件分辨率不够或背景不透明时，在 T20 交付说明中写明，交主编排决定。

**生成**（T20 步骤 1）：仓库根下 `python packaging\brand\make_brand.py`（要 Pillow），上表文件和下面这些都由它从 `logo\` 原件生成，可重复：
- `installer-sidebar.bmp`：NSIS 安装向导左侧图（164×314）。
- `desktop\`：桌面端补丁 P-4 要换的图，目录结构同 `dsh\apps\desktop`（`resources\` 下的应用图标和托盘图标，`installer\assets\` 下的安装界面品牌图），打完 P-4 补丁后整个拷进去（见 `dsh-patches\PATCHES.md` 应用步骤）。

现状：律所原件是透明 PNG（1830×666），够用；**我方原件 `技术公司-logo.png` 是白底 RGB，没有透明背景**，`vendor-logo.png` 是把近白色转成透明得到的，边缘可能带浅色毛边，最好换一份透明底原件。软件名称未定，`names.txt` 第二行和 P-4 里暂用"连越律师工作台"。
