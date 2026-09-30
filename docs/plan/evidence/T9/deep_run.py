"""在真正的中文深目录下跑一次全量（目录名在 Python 里建，不经 shell 传递，避免中文被转坏）。"""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

out = pathlib.Path(sys.argv[1])
base = pathlib.Path(tempfile.mkdtemp(prefix="lbdp-")) / ("甲某诉乙某买卖合同纠纷一审二审再审全部卷宗材料整理" * 2)
base.mkdir()  # 每次新建一个随机上级目录，不和上次没删干净的撞
bt = base / "pt"
bt.name.encode("mbcs")
str(bt).encode("mbcs")   # 本机代码页编得了：中文是真中文
env = dict(os.environ, PYTHONIOENCODING="utf-8")
with open(out, "w", encoding="utf-8") as f:
    f.write(f"basetemp 长度 {len(str(bt))} 字符，含中文（目录名见 lbdeep5\\<重复两遍的案件名>\\pt）\n")
    f.flush()
    r = subprocess.run([str(pathlib.Path(r"D:\lawbench-B\service\.venv\Scripts\python.exe")), "-m", "pytest", "-q",
                        "-p", "no:cacheprovider", "--basetemp", str(bt), "tests"],
                       cwd=r"D:\lawbench-B\service", stdout=f, stderr=subprocess.STDOUT, env=env)
    f.write(f"deep-rc={r.returncode}\n")
print(r.returncode)
