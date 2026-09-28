# probe_395.ps1 - read-only inventory of the 395 node (Spec section 6, G-5/G-6).
# Run ON the 395 machine:  powershell -NoProfile -ExecutionPolicy Bypass -File probe_395.ps1
# Changes nothing. Writes the same report to probe_395_result.txt next to this script.
# Labels are English on purpose: Windows PowerShell 5.1 misreads non-ASCII in scripts saved without BOM.

$ErrorActionPreference = 'SilentlyContinue'
$out = New-Object System.Collections.Generic.List[string]
function W($s) { $out.Add([string]$s); Write-Host $s }
function Section($t) { W ''; W "==== $t ====" }

Section 'System'
$os = Get-CimInstance Win32_OperatingSystem
W ("OS: {0} {1} build {2}" -f $os.Caption, $os.Version, $os.BuildNumber)
W ("Host: {0}   User: {1}" -f $env:COMPUTERNAME, $env:USERNAME)
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
W "Running as administrator: $isAdmin"

Section 'CPU / RAM / GPU'
Get-CimInstance Win32_Processor | ForEach-Object { W ("CPU: {0}  cores={1} threads={2}" -f $_.Name.Trim(), $_.NumberOfCores, $_.NumberOfLogicalProcessors) }
$cs = Get-CimInstance Win32_ComputerSystem
W ("RAM visible to Windows: {0:N1} GB" -f ($cs.TotalPhysicalMemory / 1GB))
Get-CimInstance Win32_VideoController | ForEach-Object { W ("GPU: {0}  driver={1}  date={2}" -f $_.Name, $_.DriverVersion, $_.DriverDate) }
$vk = Test-Path "$env:WINDIR\System32\vulkan-1.dll"
W "Vulkan loader (System32\vulkan-1.dll) present: $vk"
$vi = Get-Command vulkaninfo -ErrorAction SilentlyContinue
if ($vi) { W 'vulkaninfo --summary:'; & vulkaninfo --summary 2>$null | Select-Object -First 40 | ForEach-Object { W "  $_" } } else { W 'vulkaninfo: not installed (fine; llama.cpp only needs the driver)' }
$hip = Get-ChildItem 'C:\Program Files\AMD\ROCm' -Directory
W ("AMD HIP SDK (ROCm for Windows): " + ($(if ($hip) { ($hip.Name -join ', ') } else { 'not installed' })))

Section 'Disks'
Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Used -ne $null } | ForEach-Object { W ("{0}:  free {1:N0} GB / total {2:N0} GB" -f $_.Name, ($_.Free/1GB), (($_.Used+$_.Free)/1GB)) }

Section 'Security settings (Spec 6.1)'
$bl = Get-BitLockerVolume -MountPoint 'C:'
if ($bl) { W ("BitLocker C: {0}, protection {1}" -f $bl.VolumeStatus, $bl.ProtectionStatus) } else { W 'BitLocker C: unknown (needs administrator, or BitLocker not available on this edition)' }
W 'powercfg /a (hibernate availability):'
powercfg /a 2>$null | ForEach-Object { W "  $_" }
Get-CimInstance Win32_PageFileUsage | ForEach-Object { W ("Pagefile: {0}  allocated {1} MB" -f $_.Name, $_.AllocatedBaseSize) }
Get-NetFirewallProfile | ForEach-Object { W ("Firewall {0}: enabled={1} inbound={2}" -f $_.Name, $_.Enabled, $_.DefaultInboundAction) }
$rdp = (Get-ItemProperty 'HKLM:\System\CurrentControlSet\Control\Terminal Server').fDenyTSConnections
W ("Remote Desktop enabled: " + ($rdp -eq 0))
Get-SmbShare | ForEach-Object { W ("SMB share: {0} -> {1}" -f $_.Name, $_.Path) }
$sshd = Get-Service sshd
W ("sshd service: " + ($(if ($sshd) { "$($sshd.Status), start=$($sshd.StartType)" } else { 'not installed' })))

Section 'Network'
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | ForEach-Object { W ("IPv4: {0}/{1}  ({2})" -f $_.IPAddress, $_.PrefixLength, $_.InterfaceAlias) }
foreach ($p in 9000, 9101, 9102) {
  $c = Get-NetTCPConnection -LocalPort $p -State Listen
  W ("Port $p in use: " + ($(if ($c) { "YES (pid $($c[0].OwningProcess))" } else { 'no' })))
}
$t = Test-NetConnection 192.168.8.77 -Port 8000 -WarningAction SilentlyContinue
W ("Reach 6000D gateway 192.168.8.77:8000: " + $t.TcpTestSucceeded)

Section 'Internet (for downloading llama.cpp and models)'
foreach ($u in 'https://github.com', 'https://huggingface.co', 'https://hf-mirror.com', 'https://www.modelscope.cn', 'https://pypi.org') {
  try { $r = Invoke-WebRequest -Uri $u -Method Head -TimeoutSec 8 -UseBasicParsing; W "$u -> $($r.StatusCode)" }
  catch { W "$u -> FAILED ($($_.Exception.Message.Split([Environment]::NewLine)[0]))" }
}

Section 'Software'
foreach ($cmd in 'python', 'py', 'git', 'llama-server') {
  $c = Get-Command $cmd -ErrorAction SilentlyContinue
  if ($c) { $v = (& $cmd --version 2>&1 | Select-Object -First 1); W "$cmd : $($c.Source)  $v" } else { W "$cmd : not found" }
}

$file = Join-Path $PSScriptRoot 'probe_395_result.txt'
$out | Out-File -FilePath $file -Encoding utf8
W ''
W "Report saved to $file"
