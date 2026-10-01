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
