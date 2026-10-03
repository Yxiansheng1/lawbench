# install_service_395.ps1 - run EasyTier (node-395) as a Windows service: auto start on boot, restart on failure,
# parameters read from an admin-only config file (no secret on the command line or in this script).
# Run ON 395, as administrator, FROM THE 395 CONSOLE OR A LAN SESSION - never over EasyTier itself
# (the virtual network drops while the service is replaced):
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\EasyTier\install_service_395.ps1 [-SecureMode]
# Method: EasyTier 2.6.4's own "easytier-cli service install" (default: auto start + restart on failure; see
# docs\plan\evidence\T27\easytier-service-help.txt). WinSW is not needed.
# Rollback: uninstall_service_395.ps1 (restores whatever ran before, from the backup this script writes).
# Labels are English on purpose: Windows PowerShell 5.1 misreads non-ASCII in scripts saved without BOM.
param(
  [string]$Dir = "C:\EasyTier",
  [string]$Name = "easytier",
  [string]$Config = "C:\EasyTier\lawbench.toml",
  [switch]$SecureMode           # only after T27 A3 (all three nodes switch together)
)
$ErrorActionPreference = "Stop"
function Step($t) { Write-Host ""; Write-Host "==== $t ====" }
function Assert-Exit($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" } }

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { throw "Run as administrator." }
$core = Join-Path $Dir "easytier-core.exe"
$cli = Join-Path $Dir "easytier-cli.exe"
foreach ($p in @($core, $cli)) { if (-not (Test-Path $p)) { throw "Missing: $p" } }
$ver = (& $core --version) -join " "
Write-Host "easytier-core: $ver"
if ($ver -notmatch "2\.6\.") { throw "Expected EasyTier 2.6.x (service install verified for 2.6.4); got: $ver" }

Step "1. Backup current state (admin-only folder; contains the old command line, which may include the secret)"
$backup = Join-Path $Dir "backup"
New-Item -ItemType Directory -Force $backup | Out-Null
icacls $backup /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" | Out-Null; Assert-Exit "icacls backup"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$svc = Get-Service -Name $Name -ErrorAction SilentlyContinue
if ($svc) {
  sc.exe qc $Name > (Join-Path $backup "service-qc-$stamp.txt")
  sc.exe qfailure $Name > (Join-Path $backup "service-qfailure-$stamp.txt")
  Write-Host "Existing service '$Name': $($svc.Status), $($svc.StartType)"
} else { Write-Host "No existing service '$Name'." }
$procs = @(Get-CimInstance Win32_Process -Filter "Name='easytier-core.exe'")
$procs | ForEach-Object { $_.CommandLine } | Set-Content -Encoding utf8 (Join-Path $backup "processes-$stamp.txt")
Write-Host "Running easytier-core processes: $($procs.Count) (command lines saved, not shown)"

Step "2. Config file (admin-only)"
if (-not (Test-Path $Config)) {
  Write-Host "Creating $Config. Paste the network secret when asked (input hidden; not stored anywhere else)."
  New-Item -ItemType File -Force $Config | Out-Null
  icacls $Config /inheritance:r /grant:r "*S-1-5-32-544:F" "*S-1-5-18:F" | Out-Null; Assert-Exit "icacls config"
  $s = Read-Host "Network secret" -AsSecureString
  $k = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
  if (-not $k) { throw "Empty secret." }
  @"
hostname = "node-395"
ipv4 = "10.126.126.3"
dhcp = false
listeners = ["udp://0.0.0.0:11010"]
tcp_whitelist = ["9000"]

[network_identity]
network_name = "lawbench"
network_secret = "$k"

[[peer]]
uri = "tcp://47.107.140.75:11010"
"@ | Set-Content -Encoding utf8 $Config
  Remove-Variable k, s
}
$acl = (icacls $Config) -join "`n"
$others = ($acl -split "`n") | Where-Object { $_ -match ":\(" -and $_ -notmatch "BUILTIN\\Administrators|NT AUTHORITY\\SYSTEM" }
if ($others) { throw "Config file is readable by others; fix with: icacls $Config /inheritance:r /grant:r *S-1-5-32-544:F *S-1-5-18:F" }
Write-Host "Config ACL: Administrators + SYSTEM only."
& $core --config-file $Config --check-config | Out-Null; Assert-Exit "easytier-core --check-config"
Write-Host "check-config: OK"

Step "3. Stop what runs now (virtual network drops from here until step 5)"
if ($svc) {
  if ($svc.Status -ne "Stopped") { Stop-Service -Name $Name -Force }
  sc.exe delete $Name | Out-Null; Assert-Exit "sc.exe delete $Name"
  for ($i = 0; $i -lt 20 -and (Get-Service -Name $Name -ErrorAction SilentlyContinue); $i++) { Start-Sleep 1 }
}
Get-CimInstance Win32_Process -Filter "Name='easytier-core.exe'" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

Step "4. Install the service (easytier-cli service install)"
$coreArgs = @("--config-file", $Config)
if ($SecureMode) { $coreArgs += @("--secure-mode", "true") }
& $cli service --name $Name install --core-path $core --service-work-dir $Dir --display-name "EasyTier (lawbench node-395)" -- @coreArgs
Assert-Exit "easytier-cli service install"
sc.exe config $Name start= auto | Out-Null; Assert-Exit "sc.exe config start=auto"
sc.exe failure $Name reset= 86400 actions= restart/5000/restart/10000/restart/30000 | Out-Null; Assert-Exit "sc.exe failure"
sc.exe failureflag $Name 1 | Out-Null; Assert-Exit "sc.exe failureflag"

Step "5. Start and verify"
Start-Service -Name $Name
for ($i = 0; $i -lt 30 -and -not (Get-NetIPAddress -IPAddress 10.126.126.3 -ErrorAction SilentlyContinue); $i++) { Start-Sleep 1 }
& (Join-Path $PSScriptRoot "check_service_395.ps1") -Name $Name -Config $Config
if ($LASTEXITCODE -ne 0) { Write-Host "Check failed. Roll back with uninstall_service_395.ps1 if the network does not come up." ; exit 1 }
Write-Host ""
Write-Host "Done. Backup folder $backup holds the old command line (may contain the old secret); delete it after T27 A3."
