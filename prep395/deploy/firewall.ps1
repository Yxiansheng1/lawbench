# firewall.ps1 - inbound rules for the 395 node (Spec 6.1, 15). Run as administrator on 395.
# Allows TCP 9000 only from the firm LAN and the EasyTier virtual network. 9101/9102 are not opened
# (the llama-server backends listen on 127.0.0.1 only). Idempotent: removes its own old rules first.
# Labels are English on purpose: Windows PowerShell 5.1 misreads non-ASCII in scripts saved without BOM.
param(
  [string[]]$AllowFrom = @("192.168.8.0/24", "10.126.126.0/24")
)
$ErrorActionPreference = "Stop"
Get-NetFirewallRule -Group "lawbench-prep395" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName "lawbench prep395 9000 in" -Group "lawbench-prep395" -Direction Inbound `
  -Protocol TCP -LocalPort 9000 -RemoteAddress $AllowFrom -Action Allow -Profile Any | Out-Null
foreach ($p in 9101, 9102) {
  New-NetFirewallRule -DisplayName "lawbench prep395 block $p in" -Group "lawbench-prep395" -Direction Inbound `
    -Protocol TCP -LocalPort $p -Action Block -Profile Any | Out-Null
}
Get-NetFirewallRule -Group "lawbench-prep395" | Format-Table DisplayName, Enabled, Action -AutoSize
Write-Host "Note: the existing EasyTier rule 'EasyTier-9000-In' is left as is."
