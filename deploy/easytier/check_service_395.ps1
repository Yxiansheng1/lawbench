# check_service_395.ps1 - is EasyTier on 395 a proper, self-starting service and is the virtual address up?
# Run ON 395 (administrator recommended; read-only, changes nothing):
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\EasyTier\check_service_395.ps1
# Prints PASS/FAIL per line, never the secret. Exit 0 = all PASS.
param(
  [string]$Dir = "C:\EasyTier",
  [string]$Name = "easytier",
  [string]$Config = "C:\EasyTier\lawbench.toml",
  [string]$VpnIp = "10.126.126.3",
  [string]$LanIp = "192.168.8.124",
  [string]$PeerIp = "10.126.126.1"
)
$bad = 0
function Row($ok, $what, $detail) {
  $script:bad += [int](-not $ok)
  Write-Host ("[{0}] {1} - {2}" -f ($(if ($ok) { "PASS" } else { "FAIL" })), $what, $detail)
}

$svc = Get-Service -Name $Name -ErrorAction SilentlyContinue
Row ($null -ne $svc) "service exists" $(if ($svc) { $svc.DisplayName } else { "no service '$Name'" })
if ($svc) {
  Row ($svc.Status -eq "Running") "service running" $svc.Status
  Row ($svc.StartType -eq "Automatic") "starts on boot" $svc.StartType
  $qf = (sc.exe qfailure $Name) -join " "
  Row ($qf -match "RESTART") "restarts on failure" $(if ($qf -match "RESTART") { "RESTART actions set" } else { "no RESTART action" })
  $bin = ((sc.exe qc $Name) | Select-String "BINARY_PATH_NAME").ToString()
  Row ($bin -match "--config-file") "reads the config file" $(if ($bin -match "--config-file") { "yes" } else { "no --config-file in BINARY_PATH_NAME" })
  Row ($bin -notmatch "network-secret") "no secret on the command line" $(if ($bin -notmatch "network-secret") { "yes" } else { "--network-secret found in BINARY_PATH_NAME" })
}
$svcPid = if ($svc) { (Get-CimInstance Win32_Service -Filter "Name='$Name'").ProcessId } else { -1 }
$manual = @(Get-CimInstance Win32_Process -Filter "Name='easytier-core.exe'" | Where-Object { $_.ProcessId -ne $svcPid -and $_.ParentProcessId -ne $svcPid })
Row ($manual.Count -eq 0) "no extra hand-started easytier-core" "$($manual.Count) extra"
if (Test-Path $Config) {
  $others = (icacls $Config) | Where-Object { $_ -match ":\(" -and $_ -notmatch "BUILTIN\\Administrators|NT AUTHORITY\\SYSTEM" }
  Row (-not $others) "config admin-only" $(if ($others) { "others can read it" } else { "Administrators + SYSTEM" })
} else { Row $false "config file" "missing: $Config" }
$vip = Get-NetIPAddress -IPAddress $VpnIp -ErrorAction SilentlyContinue
$ad = if ($vip) { Get-NetAdapter -InterfaceIndex $vip.InterfaceIndex -ErrorAction SilentlyContinue }
Row ($null -ne $vip -and $ad.Status -eq "Up") "virtual address $VpnIp" $(if ($vip) { "on '$($ad.Name)', $($ad.Status)" } else { "not present" })
$peer = Test-NetConnection -ComputerName $PeerIp -Port 8000 -WarningAction SilentlyContinue
Row $peer.TcpTestSucceeded "reach 6000D over EasyTier ($PeerIp`:8000)" $peer.TcpTestSucceeded
$lan = Get-NetIPAddress -IPAddress $LanIp -ErrorAction SilentlyContinue
Row ($null -ne $lan) "LAN address $LanIp" $(if ($lan) { "present, origin $($lan.PrefixOrigin)" } else { "not present (see the fixed-IP sheet in deploy\ on the dev machine)" })
if ($lan) { Row ($lan.PrefixOrigin -eq "Manual") "LAN address is static" $lan.PrefixOrigin }
Write-Host ""
Write-Host $(if ($bad -eq 0) { "RESULT: all PASS" } else { "RESULT: $bad FAIL" })
exit [int]($bad -ne 0)
