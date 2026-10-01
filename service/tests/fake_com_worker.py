"""假的 Word / WPS 转换子进程（test_convert 用）：python fake_com_worker.py <progid> <源> <输出>

行为按环境变量 FAKE_COM_<PROGID 前缀>（WORD.APPLICATION → FAKE_COM_WORD，KWPS / WPS → FAKE_COM_KWPS / FAKE_COM_WPS）：
- none：没装（退出 2）；fail：打开出错（退出 3）；ok：写一个一页的 PDF（退出 0）；
- hang：先起一个孙进程（模拟它让 COM 启动的程序）、把孙进程 pid 写进 FAKE_COM_PIDS，然后一直不返回
  （模拟卡在"等待打印机连接"）。
每次调用在 FAKE_COM_LOG 追加一行 progid。
"""
import os
import subprocess
import sys
import time

progid, src, out = sys.argv[1:4]
with open(os.environ["FAKE_COM_LOG"], "a", encoding="utf-8") as f:
    f.write(progid + "\n")
mode = os.environ.get("FAKE_COM_" + progid.split(".")[0].upper(), "none")
if mode == "none":
    sys.exit(2)
if mode == "fail":
    sys.exit(3)
if mode == "ok":
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(out)
    c.drawString(100, 700, "fake " + progid)
    c.showPage()
    c.save()
    sys.exit(0)
if mode == "hang":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    with open(os.environ["FAKE_COM_PIDS"], "a", encoding="utf-8") as f:
        f.write(f"{os.getpid()} {child.pid}\n")
    time.sleep(600)
