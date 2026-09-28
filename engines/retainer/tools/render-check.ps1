# tools/render-check.ps1 —— 模板版式渲染核验
#
# 用途：把 procedural-templates 下的全部 DOCX 渲染为 PDF，供核对分页与版式。
# 依赖：LibreOffice 的 soffice.exe（本机采用免安装提取方式，见下）。
# 用法：powershell -ExecutionPolicy Bypass -File tools/render-check.ps1
#
# 本机 LibreOffice 的取得方式（无需管理员权限）：
#   1) 下载官方 MSI：
#      https://download.documentfoundation.org/libreoffice/stable/26.2.6/win/x86_64/LibreOffice_26.2.6_Win_x86-64.msi
#   2) 以管理安装方式提取到目录（不注册、不写系统，故无需管理员）：
#      msiexec /a "<MSI 路径>" /qn TARGETDIR="D:\workbuddy测试文件夹\_lo_extract"
#   3) 可执行文件位于 <TARGETDIR>\program\soffice.exe
#
# 核验标准（渲染为 PDF 后应满足）：
#   页面 595 x 842 pt（A4）、标题 22pt 黑体、正文 12pt 仿宋、
#   正文左右边界各距页边 90pt（3.18cm）。
$ErrorActionPreference = 'Continue'

$cands = @(
  'D:\workbuddy测试文件夹\_lo_extract\program\soffice.exe',
  'C:\Program Files\LibreOffice\program\soffice.exe',
  "$env:LOCALAPPDATA\Programs\LibreOffice\program\soffice.exe"
)
$soffice = $cands | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $soffice) {
  Write-Host '未找到 soffice.exe。请先按脚本头部注释取得 LibreOffice。'
  Write-Host '已查找：'
  $cands | ForEach-Object { Write-Host "  $_" }
  exit 1
}

$root = Split-Path -Parent $PSScriptRoot
$src = Join-Path $root 'procedural-templates'
$out = Join-Path $env:TEMP 'procedural-render'
if (Test-Path $out) { Remove-Item $out -Recurse -Force -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Force -Path $out | Out-Null

$docs = Get-ChildItem $src -Recurse -Filter '*.docx'
Write-Host "soffice   = $soffice"
Write-Host "待渲染    = $($docs.Count) 份"
Write-Host "输出目录  = $out"
Write-Host ''

$okCount = 0
foreach ($d in $docs) {
  & $soffice --headless --norestore --convert-to pdf --outdir $out $d.FullName 2>&1 | Out-Null
  $pdf = Join-Path $out ([System.IO.Path]::GetFileNameWithoutExtension($d.Name) + '.pdf')
  if (Test-Path $pdf) { $okCount++; Write-Host ("[OK]   " + $d.Name) } else { Write-Host ("[FAIL] " + $d.Name) }
}
Write-Host ''
Write-Host "完成：成功 $okCount / 共 $($docs.Count) 份，PDF 位于 $out"
Write-Host '版式数值核验可用 Python 的 PyMuPDF 读取 PDF 后比对上述核验标准。'
