# install.ps1 - install prep395 + two llama-server backends as Windows services on the 395 node (Spec 6.1).
# Run ON 395 as administrator:
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\prep395\deploy\install.ps1 `
#     -LanIp 192.168.8.124 -OcrModel <file.gguf> -OcrMmproj <mmproj.gguf> -LlmModel <file.gguf>
# Before running (see README.md): C:\prep395\llama\llama-server.exe, C:\prep395\python\python.exe,
# C:\prep395\winsw\WinSW-x64.exe, models under C:\prep395\models\, source under C:\prep395\src\prep395\.
# The service account password is generated here, used once, and never printed or stored.
# Labels are English on purpose: Windows PowerShell 5.1 misreads non-ASCII in scripts saved without BOM.
param(
  [Parameter(Mandatory = $true)][string]$LanIp,
  [string]$VpnIp = "10.126.126.3",     # EasyTier; "" = LAN only
  [Parameter(Mandatory = $true)][string]$OcrModel,
  [string]$OcrMmproj = "",
  [Parameter(Mandatory = $true)][string]$LlmModel,
  [int]$OcrParallel = 2,
  [int]$OcrCtx = 8192,
  [int]$LlmCtx = 16384,
  [string]$LlmBase = "http://192.168.8.77:8000",
  [string]$AdminUser = "",
  [string]$AdminPassSha256 = "",
  [string]$Root = "C:\prep395",
  [string]$Account = "prep395svc"
)
$ErrorActionPreference = "Stop"
function Step($t) { Write-Host ""; Write-Host "==== $t ====" }

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { throw "Run as administrator." }

Step "Check files"
$llama = Join-Path $Root "llama\llama-server.exe"
$py = Join-Path $Root "python\python.exe"
$winsw = Join-Path $Root "winsw\WinSW-x64.exe"
$src = Join-Path $Root "src\prep395"
$models = Join-Path $Root "models"
foreach ($p in @($llama, $py, $winsw, (Join-Path $src "pyproject.toml"), (Join-Path $models $OcrModel), (Join-Path $models $LlmModel))) {
  if (-not (Test-Path $p)) { throw "Missing: $p" }
}
if ($OcrMmproj -and -not (Test-Path (Join-Path $models $OcrMmproj))) { throw "Missing: $OcrMmproj" }

Step "Install prep395 into the bundled Python"
& $py -m pip install --no-warn-script-location --upgrade $src
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

Step "Service account $Account"
Add-Type -AssemblyName System.Web
$pw = [System.Web.Security.Membership]::GeneratePassword(32, 6)
$sec = ConvertTo-SecureString $pw -AsPlainText -Force
if (Get-LocalUser -Name $Account -ErrorAction SilentlyContinue) {
  Set-LocalUser -Name $Account -Password $sec -PasswordNeverExpires $true
} else {
  New-LocalUser -Name $Account -Password $sec -PasswordNeverExpires -UserMayNotChangePassword -Description "prep395 service (low privilege)" | Out-Null
}
# Grant "Log on as a service" (SeServiceLogonRight) via secedit
$sid = (New-Object System.Security.Principal.NTAccount($Account)).Translate([System.Security.Principal.SecurityIdentifier]).Value
$tmpInf = Join-Path $env:TEMP "lb395-secedit.inf"; $tmpDb = Join-Path $env:TEMP "lb395-secedit.sdb"
secedit /export /cfg $tmpInf /areas USER_RIGHTS | Out-Null
$lines = Get-Content $tmpInf
$line = $lines | Where-Object { $_ -like "SeServiceLogonRight*" }
if (-not $line) { $lines = $lines -replace "^\[Privilege Rights\]$", "[Privilege Rights]`r`nSeServiceLogonRight = *$sid" }
elseif ($line -notmatch [regex]::Escape($sid)) { $lines = $lines -replace "^SeServiceLogonRight = (.*)$", "SeServiceLogonRight = `$1,*$sid" }
$lines | Set-Content $tmpInf -Encoding Unicode
secedit /configure /db $tmpDb /cfg $tmpInf /areas USER_RIGHTS | Out-Null
Remove-Item $tmpInf, $tmpDb -Force -ErrorAction SilentlyContinue

Step "Directories and permissions"
$logs = Join-Path $Root "logs"; $tmp = Join-Path $Root "tmp"
New-Item -ItemType Directory -Force $logs, $tmp, (Join-Path $Root "services") | Out-Null
# Root: only Administrators/SYSTEM full, service account read+execute. Logs and tmp: service account modify.
# Set the root only, then make everything below inherit from it. (OI)(CI) on a file is invalid: with /T the grant
# failed on every file after /inheritance:r had already stripped it, leaving files with an empty ACL (395, 2026-09-30).
# SIDs instead of names so localized Windows resolves them: *S-1-5-32-544 Administrators, *S-1-5-18 SYSTEM.
function Icacls-Ok { & icacls @args | Out-Null; if ($LASTEXITCODE -ne 0) { throw "icacls failed: $($args -join ' ')" } }
Icacls-Ok $Root /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" "*${sid}:(OI)(CI)RX" /Q
Icacls-Ok "$Root\*" /reset /T /C /Q
Icacls-Ok $logs /grant:r "*${sid}:(OI)(CI)M" /Q
Icacls-Ok $tmp /grant:r "*${sid}:(OI)(CI)M" /Q

Step "Write WinSW service definitions"
$svcDir = Join-Path $Root "services"
$mm = if ($OcrMmproj) { "--mmproj `"$(Join-Path $models $OcrMmproj)`"" } else { "" }
$common = "--host 127.0.0.1 -ngl 99 --no-webui --log-disable"
$defs = @(
  @{ id = "prep395-ocr"; name = "prep395 OCR backend (llama-server)"; exe = $llama;
     args = "-m `"$(Join-Path $models $OcrModel)`" $mm --port 9101 -np $OcrParallel -c $($OcrCtx * $OcrParallel) $common"; env = @{} },
  @{ id = "prep395-llm9b"; name = "prep395 9B backend (llama-server)"; exe = $llama;
     args = "-m `"$(Join-Path $models $LlmModel)`" --port 9102 -np 1 -c $LlmCtx $common"; env = @{} },
  @{ id = "prep395"; name = "prep395 preprocessing service"; exe = $py; args = "-m prep395";
     env = @{ PREP395_HOST = (@($LanIp, $VpnIp) | Where-Object { $_ }) -join ","; PREP395_PORT = "9000"; PREP395_BACKEND = "llama"; PREP395_LLM_BASE = $LlmBase;
              PREP395_OCR_CONCURRENCY = "$OcrParallel"; PREP395_HOME = $Root;
              PREP395_ADMIN_USER = $AdminUser; PREP395_ADMIN_PASS_SHA256 = $AdminPassSha256 } }
)
foreach ($d in $defs) {
  $envXml = ($d.env.GetEnumerator() | Where-Object { $_.Value } | ForEach-Object { "  <env name=`"$($_.Key)`" value=`"$([Security.SecurityElement]::Escape($_.Value))`"/>" }) -join "`r`n"
  $dep = if ($d.id -eq "prep395") { "  <depend>prep395-ocr</depend>`r`n  <depend>prep395-llm9b</depend>" } else { "" }
  $xml = @"
<service>
  <id>$($d.id)</id>
  <name>$($d.name)</name>
  <description>lawbench 395 node. Processes requests in memory; logs metadata only.</description>
  <executable>$([Security.SecurityElement]::Escape($d.exe))</executable>
  <arguments>$([Security.SecurityElement]::Escape($d.args))</arguments>
  <workingdirectory>$Root</workingdirectory>
  <startmode>Automatic</startmode>
  <onfailure action="restart" delay="10 sec"/>
  <onfailure action="restart" delay="30 sec"/>
  <resetfailure>1 hour</resetfailure>
  <log mode="none"/>
$envXml
$dep
</service>
"@
  Set-Content -Path (Join-Path $svcDir "$($d.id).xml") -Value $xml -Encoding UTF8
  Copy-Item $winsw (Join-Path $svcDir "$($d.id).exe") -Force
}

Step "Register services"
foreach ($d in $defs) {
  $exe = Join-Path $svcDir "$($d.id).exe"
  if (Get-Service -Name $d.id -ErrorAction SilentlyContinue) { & $exe stop | Out-Null; & $exe uninstall | Out-Null }
  & $exe install | Out-Null
  sc.exe config $d.id obj= ".\$Account" password= $pw | Out-Null
  sc.exe failure $d.id reset= 3600 actions= restart/10000/restart/30000/restart/60000 | Out-Null
}
$pw = $null; $sec = $null

Step "Firewall"
& (Join-Path $PSScriptRoot "firewall.ps1")

Step "Hibernation off"
powercfg /h off

Step "Start services"
foreach ($id in @("prep395-ocr", "prep395-llm9b", "prep395")) { Start-Service $id }
Start-Sleep -Seconds 20
Get-Service prep395* | Format-Table Name, Status, StartType -AutoSize
try { (Invoke-WebRequest -UseBasicParsing "http://${LanIp}:9000/health" -TimeoutSec 10).Content } catch { Write-Host "health check failed: $($_.Exception.Message)" }
Write-Host "Done. BitLocker and remote-control software: follow the owner decision list (not changed by this script)."
