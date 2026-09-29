<#
.SYNOPSIS
  SEC-01 / SEC-11 全盘搜索：案件目录以外不得出现测试案卷的特征字符串。
.DESCRIPTION
  T17 的 scripts\find_leaks.ps1 合并进 main 之前，本卡用这个实现（Python 按字节搜索 UTF-8 与 UTF-16LE）。
  T17 合并后，改为调用 scripts\find_leaks.ps1。
.EXAMPLE
  .\acceptance\sec\find_leaks.ps1 -Feature LBFX-CRIM01-7Q3Z -CaseDir D:\验收\criminal-01
#>
param(
  [string[]]$Feature,
  [string[]]$CaseDir,
  [string[]]$Root,
  [string[]]$Exclude,
  [int]$MaxMB = 256,
  [switch]$Fresh,
  [string]$Python = ""
)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $Python) {
  $venv = Join-Path $here "..\..\.venv\Scripts\python.exe"
  $Python = if (Test-Path $venv) { $venv } else { "python" }
}
$argv = @((Join-Path $here "find_leaks.py"), "--max-mb", $MaxMB)
foreach ($f in $Feature) { $argv += @("--feature", $f) }
foreach ($c in $CaseDir) { $argv += @("--case-dir", $c) }
foreach ($r in $Root) { $argv += @("--root", $r) }
foreach ($e in $Exclude) { $argv += @("--exclude", $e) }
if ($Fresh) { $argv += "--fresh" }
& $Python @argv
exit $LASTEXITCODE
