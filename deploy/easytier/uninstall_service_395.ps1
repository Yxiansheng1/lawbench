# uninstall_service_395.ps1 - roll back install_service_395.ps1 on 395: remove the EasyTier service it installed and
# bring back what ran before, from the newest backup in C:\EasyTier\backup (old service definition, or the old
# hand-started command line). The old command line may contain the secret: it is used, never printed.
# Run ON 395, as administrator, from the console or a LAN session (not over EasyTier):
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\EasyTier\uninstall_service_395.ps1 [-RemoveOnly]
# -RemoveOnly: just remove the service, do not restore anything (EasyTier stays off).
# Labels are English on purpose: Windows PowerShell 5.1 misreads non-ASCII in scripts saved without BOM.
param(
  [string]$Dir = "C:\EasyTier",
  [string]$Name = "easytier",
  [switch]$RemoveOnly
)
$ErrorActionPreference = "Stop"
function Step($t) { Write-Host ""; Write-Host "==== $t ====" }
function Assert-Exit($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" } }
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { throw "Run as administrator." }
$cli = Join-Path $Dir "easytier-cli.exe"
$backup = Join-Path $Dir "backup"

Step "1. Remove the service"
if (Get-Service -Name $Name -ErrorAction SilentlyContinue) {
  Stop-Service -Name $Name -Force -ErrorAction SilentlyContinue
  & $cli service --name $Name uninstall
  if ($LASTEXITCODE -ne 0) { sc.exe delete $Name | Out-Null; Assert-Exit "sc.exe delete $Name" }
  for ($i = 0; $i -lt 20 -and (Get-Service -Name $Name -ErrorAction SilentlyContinue); $i++) { Start-Sleep 1 }
  Write-Host "Service '$Name' removed."
} else { Write-Host "No service '$Name'." }
Get-CimInstance Win32_Process -Filter "Name='easytier-core.exe'" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
if ($RemoveOnly) { Write-Host "RemoveOnly: nothing restored. EasyTier is off."; exit 0 }

Step "2. Restore what ran before"
$qc = Get-ChildItem $backup -Filter "service-qc-*.txt" -ErrorAction SilentlyContinue | Sort-Object Name | Select-Object -Last 1
$pr = Get-ChildItem $backup -Filter "processes-*.txt" -ErrorAction SilentlyContinue | Sort-Object Name | Select-Object -Last 1
$line = if ($qc) { (Get-Content $qc.FullName | Select-String "BINARY_PATH_NAME") } else { $null }
if ($line) {
  $bin = ($line.ToString() -split ":", 2)[1].Trim()
  sc.exe create $Name binPath= $bin start= auto | Out-Null; Assert-Exit "sc.exe create $Name"
  $qf = Get-ChildItem $backup -Filter "service-qfailure-*.txt" | Sort-Object Name | Select-Object -Last 1
  if ($qf -and ((Get-Content $qf.FullName) -join " ") -match "RESTART") {
    sc.exe failure $Name reset= 86400 actions= restart/5000/restart/10000/restart/30000 | Out-Null
  }
  Start-Service -Name $Name
  Write-Host "Old service definition restored from $($qc.Name) and started."
} elseif ($pr -and (Get-Content $pr.FullName | Where-Object { $_ })) {
  $cmd = (Get-Content $pr.FullName | Where-Object { $_ } | Select-Object -First 1)
  $exe, $rest = if ($cmd.StartsWith('"')) { $cmd.Substring(1) -split '" ', 2 } else { $cmd -split " ", 2 }
  Start-Process -FilePath $exe -ArgumentList $rest -WorkingDirectory $Dir -WindowStyle Hidden
  Write-Host "Old hand-started easytier-core restarted (command line from $($pr.Name)); it will NOT survive a reboot."
} else {
  Write-Host "No backup of a previous service or process: nothing to restore. EasyTier is off."
  exit 1
}
Start-Sleep 10
& (Join-Path $PSScriptRoot "check_service_395.ps1") -Name $Name
