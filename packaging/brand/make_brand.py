r"""从仓库根 logo\ 的原件生成 packaging\brand\ 下的品牌素材（T20 步骤 1；对应关系见本目录 README.md）。原件不改。

用法（仓库根下，任一装了 Pillow 的 Python）：python packaging\brand\make_brand.py
产出（都可重复生成，与原件一一对应）：
  firm-logo.png      律所 logo，裁掉四周透明边，宽 1024（原件 1830×666 透明 PNG）
  vendor-logo.png    技术公司 logo（"技术支持"，用户 N58 定用 logo\技术公司-logo2.jpg）：原件是白底 JPG，近白色转透明、裁边，宽 768
  vendor-mark.png    同上去掉下方的标语行，只留圆形标志和"Ai"（小尺寸用：关于面板、安装界面角标），高 256
  app-icon.png       律所标志里左侧的红色图形裁成方形，1024×1024 透明
  app-icon.ico       同上，16/24/32/48/64/128/256 七个尺寸
  installer-sidebar.bmp  NSIS 安装向导左侧图（164×314，白底，律所标志居中）
  ..\..\dsh-ext\ui\brand-assets.ts  界面插件常驻的律所 logo、技术公司小标志（data: URI，侧栏品牌位与底部"技术支持"一行）
  names.txt          第一行律所全称；第二行软件名称（未定，暂用占位名"连越律师工作台"）
  desktop\          桌面端 P-4 要换的图（尺寸与 DSH 原图一致，补丁 P-4 把它们放进 dsh\apps\desktop）：
                     resources\icon-windows.png、icon-macos.png（1024）、icon.png（1104）、tray-windows.ico（64）；
                     installer\assets\brand.png（600×196）、brand-2x.png（1200×392）、brand-dark*.png（深色：黑字换白）、
                     uninstaller-sidebar.png（164×314）；安装界面品牌图右下角放技术公司角标（用户 N58）；
                     renderer\assets\vendor-logo.png（关于面板"技术支持"一行旁的技术公司标志，高 56，界面按 28 显示）
"""
from __future__ import annotations

import pathlib

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[2]
LOGO = ROOT / "logo"
OUT = pathlib.Path(__file__).resolve().parent

FIRM_FULL_NAME = "广东连越（深圳）律师事务所"
# 软件名称待定（工单 T20 步骤 1）：先用占位名，定了只改这一行再重跑
PRODUCT_NAME_PLACEHOLDER = "连越律师工作台"


def trim(im: Image.Image) -> Image.Image:
    box = im.getchannel("A").getbbox()
    return im.crop(box) if box else im


def width_to(im: Image.Image, w: int) -> Image.Image:
    return im.resize((w, round(im.height * w / im.width)), Image.LANCZOS)


def white_to_alpha(im: Image.Image, lo: int = 225, hi: int = 250) -> Image.Image:
    """近白色转透明：亮度 ≥ hi 全透明，lo..hi 之间按比例，< lo 不动（保留字的抗锯齿边）。"""
    rgba = im.convert("RGBA")
    px = rgba.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, _ = px[x, y]
            v = min(r, g, b)
            if v >= hi:
                px[x, y] = (r, g, b, 0)
            elif v >= lo:
                px[x, y] = (r, g, b, round(255 * (hi - v) / (hi - lo)))
    return rgba


def square(im: Image.Image, size: int, pad: float = 0.08) -> Image.Image:
    side = max(im.width, im.height)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(im, ((side - im.width) // 2, (side - im.height) // 2), im)
    inner = round(size * (1 - 2 * pad))
    scaled = canvas.resize((inner, inner), Image.LANCZOS)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(scaled, ((size - inner) // 2, (size - inner) // 2), scaled)
    return out


def whiten(firm: Image.Image) -> Image.Image:
    """深色版律所 logo：红色图形不动，其余（黑字及其抗锯齿边）换白。"""
    logo = firm.copy()
    px = logo.load()
    for y in range(logo.height):
        for x in range(logo.width):
            r, g, b, a = px[x, y]
            if a and not (r > g + 60):
                px[x, y] = (255, 255, 255, a)
            elif not a:
                px[x, y] = (255, 255, 255, 0)  # 透明处也取白色，缩放时不把黑边混进白字
    return logo


def banner(firm: Image.Image, size: tuple[int, int], dark: bool, vendor: Image.Image | None = None) -> Image.Image:
    """安装界面顶部的品牌图：透明底，律所 logo 居中，高度占 60%；深色版把黑字换成白字。
    给了 vendor 时在右下角放技术公司角标（高度为图高的 16%，留边 3%；用户 N58：安装程序欢迎页、完成页角标）。"""
    logo = whiten(firm) if dark else firm.copy()
    h = round(size[1] * 0.6)
    logo = logo.resize((round(logo.width * h / logo.height), h), Image.LANCZOS)
    if logo.width > size[0] * 0.9:
        logo = width_to(logo, round(size[0] * 0.9))
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    out.paste(logo, ((size[0] - logo.width) // 2, (size[1] - logo.height) // 2), logo)
    if vendor is not None:
        vh = round(size[1] * 0.16)
        mark = vendor.resize((round(vendor.width * vh / vendor.height), vh), Image.LANCZOS)
        m = round(size[1] * 0.03)
        out.paste(mark, (size[0] - mark.width - m, size[1] - mark.height - m), mark)
    return out


def drop_tagline(im: Image.Image) -> Image.Image:
    """去掉标志下方的标语行：从高度一半往下找第一整行透明处，只留上面一段。"""
    alpha = im.getchannel("A")
    for y in range(im.height // 2, im.height):
        if not any(alpha.getpixel((x, y)) > 16 for x in range(0, im.width, 2)):
            return trim(im.crop((0, 0, im.width, y)))
    return im


def desktop_assets(firm: Image.Image, mark: Image.Image, vendor_mark: Image.Image) -> None:
    d = OUT / "desktop"
    (d / "resources").mkdir(parents=True, exist_ok=True)
    (d / "installer" / "assets").mkdir(parents=True, exist_ok=True)
    square(mark, 1024).save(d / "resources" / "icon-windows.png", optimize=True)
    square(mark, 1024).save(d / "resources" / "icon-macos.png", optimize=True)
    square(mark, 1104).save(d / "resources" / "icon.png", optimize=True)
    square(mark, 64, pad=0.04).save(d / "resources" / "tray-windows.ico", sizes=[(s, s) for s in (16, 20, 24, 32, 40, 48, 64)])
    a = d / "installer" / "assets"
    banner(firm, (600, 196), False, vendor_mark).save(a / "brand.png", optimize=True)
    banner(firm, (1200, 392), False, vendor_mark).save(a / "brand-2x.png", optimize=True)
    banner(firm, (600, 196), True, vendor_mark).save(a / "brand-dark.png", optimize=True)
    banner(firm, (1200, 392), True, vendor_mark).save(a / "brand-dark-2x.png", optimize=True)
    (d / "renderer" / "assets").mkdir(parents=True, exist_ok=True)
    vendor_mark.resize((round(vendor_mark.width * 56 / vendor_mark.height), 56), Image.LANCZOS).save(
        d / "renderer" / "assets" / "vendor-logo.png", optimize=True)
    side = Image.new("RGB", (164, 314), (255, 255, 255))
    small = square(mark, 120, pad=0.0)
    side.paste(small, ((164 - 120) // 2, 60), small)
    side.save(a / "uninstaller-sidebar.png", optimize=True)


def ui_assets(firm: Image.Image, vendor_mark: Image.Image) -> None:
    r"""界面插件常驻的两处小图（执行令 2026-10-04 11:56 第 1、2 条）：侧栏品牌位的律所 logo（高 48，界面按 24 显示）、
    侧栏底部"技术支持"一行的技术公司小标志（高 32，界面按 16 显示）。写成 data: URI 放进 dsh-ext\ui\brand-assets.ts，
    界面插件不必另带图片文件（界面插件不读本机文件，Spec 14.3）。"""
    import base64, io

    def uri(im: Image.Image, h: int) -> str:
        buf = io.BytesIO()
        im.resize((round(im.width * h / im.height), h), Image.LANCZOS).save(buf, "PNG", optimize=True)
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

    out = ROOT / "dsh-ext" / "ui" / "brand-assets.ts"
    out.write_text(
        "// 由 packaging\\brand\\make_brand.py 生成，不要手改（原件在仓库根 logo\\）。\n"
        f"/** 律所 logo（高 96 px：侧栏按 22 px、首页按 44 px 显示，高分屏也清楚）。 */\nexport const FIRM_LOGO = '{uri(firm, 96)}'\n"
        f"/** 深色界面用的律所 logo（黑字换白；令 1426 真机截图时发现深色下字看不见）。 */\nexport const FIRM_LOGO_DARK = '{uri(whiten(firm), 96)}'\n"
        f"/** 技术公司标志（高 32 px，按 16 px 显示）。 */\nexport const VENDOR_MARK = '{uri(vendor_mark, 32)}'\n",
        encoding="utf-8", newline="\n")
    print(f"{out.relative_to(ROOT)}  {out.stat().st_size} bytes")


def main() -> None:
    firm = trim(Image.open(LOGO / "连越律师事务所-logo.png").convert("RGBA"))
    width_to(firm, 1024).save(OUT / "firm-logo.png", optimize=True)

    # 用户 N58（2026-10-02）：技术公司 logo 用 logo\技术公司-logo2.jpg（白底 JPG，无透明通道：近白色转透明）
    vendor = trim(white_to_alpha(Image.open(LOGO / "技术公司-logo2.jpg")))
    width_to(vendor, 768).save(OUT / "vendor-logo.png", optimize=True)
    vendor_mark = drop_tagline(vendor)
    vendor_mark.resize((round(vendor_mark.width * 256 / vendor_mark.height), 256), Image.LANCZOS).save(OUT / "vendor-mark.png", optimize=True)

    # 律所标志：左侧红色图形约占原件宽度的 46%（文字"连越 LIANYUE"在右）；按透明列切开，取第一段
    alpha = firm.getchannel("A")
    cols = [any(alpha.getpixel((x, y)) > 0 for y in range(0, firm.height, 2)) for x in range(firm.width)]
    gap = next(x for x in range(firm.width // 4, firm.width) if not cols[x])
    mark = trim(firm.crop((0, 0, gap, firm.height)))
    icon = square(mark, 1024)
    icon.save(OUT / "app-icon.png", optimize=True)
    icon.save(OUT / "app-icon.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])

    side = Image.new("RGB", (164, 314), (255, 255, 255))
    small = square(mark, 120, pad=0.0)
    side.paste(small, ((164 - 120) // 2, 60), small)
    side.save(OUT / "installer-sidebar.bmp")

    desktop_assets(firm, mark, vendor_mark)
    ui_assets(firm, vendor_mark)
    (OUT / "names.txt").write_text(f"{FIRM_FULL_NAME}\n{PRODUCT_NAME_PLACEHOLDER}\n", encoding="utf-8", newline="\n")
    for p in sorted(OUT.rglob("*")):
        if p.suffix in (".png", ".ico", ".bmp"):
            with Image.open(p) as im:
                print(f"{p.relative_to(OUT)}  {im.size[0]}x{im.size[1]}  {im.mode}")


if __name__ == "__main__":
    main()
