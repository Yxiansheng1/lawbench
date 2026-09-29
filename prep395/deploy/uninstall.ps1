# uninstall.ps1 - stop and remove the three prep395 services and the firewall rules. Run as administrator on 395.
# Keeps C:\prep395 (models, logs) and the service account; pass -RemoveAccount to delete the account too.
param([string]$Root = "C:\prep395", [string]$Account = "prep395svc", [switch]$RemoveAccount)
$ErrorActionPreference = "Continue"
foreach ($id in @("prep395", "prep395-llm9b", "prep395-ocr")) {
  $exe = Join-Path $Root "services\$id.exe"
  if (Test-Path $exe) { & $exe stop | Out-Null; & $exe uninstall | Out-Null; Write-Host "removed service $id" }
}
Get-NetFirewallRule -Group "lawbench-prep395" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
if ($RemoveAccount -and (Get-LocalUser -Name $Account -ErrorAction SilentlyContinue)) { Remove-LocalUser -Name $Account; Write-Host "removed account $Account" }
Write-Host "Done."
