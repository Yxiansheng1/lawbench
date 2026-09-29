"""SEC-12（上线必过第 5 项"395 每个请求结束后无残留"、16a 之后的复查）：395 上搜索测试样本的特征字符串。

AI 不保存、不索要 SSH 密码，所以分两步：
1. python acceptance\\sec\\residue_395.py --print-command   → 打印一段 PowerShell，
   由用户在 395 上（远程桌面，或自己 ssh pc@192.168.8.124）以管理员身份运行，结果存成 residue.txt；
2. 把 residue.txt 拷回本机，python acceptance\\sec\\residue_395.py --result residue.txt   → 判定。
搜索范围：C:\\prep395\\（含日志）、C:\\Windows\\Temp、各用户的 AppData\\Local\\Temp、推理后端目录（C:\\llama*）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import FAIL, FEATURES, PASS, UNMET, Report  # noqa: E402

COMMAND = r"""# 在 395 上以管理员身份运行（PowerShell）；结果写到桌面 residue.txt
$feats = @({feats})
$roots = @('C:\prep395', 'C:\Windows\Temp') + (Get-ChildItem 'C:\Users' -Directory | ForEach-Object {{ Join-Path $_.FullName 'AppData\Local\Temp' }}) + (Get-ChildItem 'C:\' -Directory -Filter 'llama*' | ForEach-Object FullName)
$out = Join-Path ([Environment]::GetFolderPath('Desktop')) 'residue.txt'
"ROOTS: $($roots -join ' | ')" | Out-File $out -Encoding utf8
$n = 0
foreach ($r in $roots) {{ if (Test-Path $r) {{
  Get-ChildItem $r -Recurse -File -Force -ErrorAction SilentlyContinue | Where-Object {{ $_.Length -lt 256MB }} | ForEach-Object {{
    $n++; $f = $_.FullName
    foreach ($enc in 'utf8','unicode') {{
      $hit = Select-String -LiteralPath $f -SimpleMatch -Pattern $feats -Encoding $enc -List -ErrorAction SilentlyContinue
      if ($hit) {{ "HIT: $f <- $($hit.Pattern)" | Out-File $out -Append -Encoding utf8; break }}
    }}
  }} }} }}
"FILES: $n" | Out-File $out -Append -Encoding utf8
"PREP395_TEMP_PREFIX: $((Get-ChildItem $roots -Recurse -Force -Filter 'prep395-*' -ErrorAction SilentlyContinue | Measure-Object).Count)" | Out-File $out -Append -Encoding utf8
"DONE" | Out-File $out -Append -Encoding utf8
Write-Host "已写入 $out"
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--print-command", action="store_true")
    ap.add_argument("--result", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    feats = ", ".join(f"'{f}'" for f in FEATURES.values())
    if a.print_command:
        print(COMMAND.format(feats=feats))
        return
    r = Report("residue_395", "SEC-12；上线必过第 5 项（395 无残留）", a.out)
    if not a.result or not a.result.exists():
        r.log("需要用户在 395 上运行下面的命令（--print-command 可单独打印），再用 --result 传回结果：")
        r.log(COMMAND.format(feats=feats))
        r.finish(UNMET, "还没有 395 上的搜索结果")
    text = a.result.read_text(encoding="utf-8-sig", errors="replace")
    if "DONE" not in text:
        r.finish(UNMET, "结果文件不完整（没有 DONE 行），请重新运行")
    hits = [ln for ln in text.splitlines() if ln.startswith("HIT:")]
    temp = [ln for ln in text.splitlines() if ln.startswith("PREP395_TEMP_PREFIX:")]
    for ln in text.splitlines():
        if ln.startswith(("ROOTS:", "FILES:", "PREP395_TEMP_PREFIX:")):
            r.log(ln)
    for h in hits:
        r.log(h)
    left = int(temp[0].split(":")[1]) if temp else 0
    if hits or left:
        r.finish(FAIL, f"395 上命中 {len(hits)} 处特征字符串，prep395- 前缀残留 {left} 个")
    r.finish(PASS, "395 的服务目录、临时目录、推理后端目录都没有测试案卷的特征字符串")


if __name__ == "__main__":
    main()
