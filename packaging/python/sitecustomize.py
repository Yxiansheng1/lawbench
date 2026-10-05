r"""客户端内置 Python 的 sitecustomize（T20 步骤 2）：去掉用户目录的 site-packages（%APPDATA%\Python\Python312\site-packages）。

服务自己用 -I 启动不受影响；但服务另起的子进程（证件识别驱动 driver.py 用 sys.executable、只带运行必需的环境变量）不带 -I，
不去掉的话律师自己装过的 Python 包会混进来。随包放进 <安装目录>\python\Lib\site-packages\。
"""
import site
import sys

site.ENABLE_USER_SITE = False
try:
    _user = site.getusersitepackages()
except Exception:  # noqa: BLE001 —— 取不到就没有可去的
    _user = None
if _user:
    _norm = lambda p: p.replace("/", "\\").rstrip("\\").lower()  # noqa: E731
    sys.path[:] = [p for p in sys.path if _norm(p) != _norm(_user)]

# 标准错误一律 UTF-8（T20 第二版前修法复核 P2-2）：服务以 -I 启动，PYTHONIOENCODING / PYTHONUTF8 都被忽略；中文系统上
# stderr 接管道时按系统代码页（cp936）编码，Host 按 UTF-8 读，异常消息里的中文（如"应用程序控制策略已阻止此文件"）成乱码。
# 只改 stderr，不开 UTF-8 模式（服务里还有按系统编码读子进程输出的地方，如 retainer\driver.py 读 PowerShell 输出）。
try:
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:  # noqa: BLE001 —— 没有 stderr（pythonw）或已被替换时不管
    pass
