<#
  Admin Skill directory: ordinary users may read, only SYSTEM and Administrators may write (T20 step 3 item 3;
  Spec 10.1 "%ProgramData%\<product>\skills, ordinary users read-only").

  Usage (elevated, from the installer):  set-skills-acl.ps1 -Dir "$env:ProgramData\lawbench\skills"
  Simulation (not elevated, any test folder you own):  set-skills-acl.ps1 -Dir <temp folder> -Verify

  - Inheritance from %ProgramData% is removed (by default it lets every user create files and folders there).
  - Grants use well-known SIDs so it works on any display language:
      S-1-5-18 SYSTEM, S-1-5-32-544 Administrators : full control
      S-1-5-32-545 Users                            : read and execute
  - Existing files below get the same rights (/T).
  Keep this file ASCII-only (Windows PowerShell 5 reads BOM-less files in the ANSI code page).
#>
param(
  [Parameter(Mandatory = $true)][string]$Dir,
  [switch]$Verify
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path $Dir)) { New-Item -ItemType Directory -Force $Dir | Out-Null }

& icacls.exe $Dir /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-32-545:(OI)(CI)RX' /T /C /Q
if ($LASTEXITCODE -ne 0) { throw "icacls failed ($LASTEXITCODE)" }

if ($Verify) {
  # The current process is not elevated here, so Administrators is a deny-only group in its token:
  # it can write only if Users (or the user itself) could.
  $probe = Join-Path $Dir ('.acl-probe-' + [guid]::NewGuid().ToString('N'))
  $writable = $true
  try { [IO.File]::WriteAllText($probe, '') } catch { $writable = $false }
  if ($writable) { Remove-Item -Force $probe }
  $sub = Join-Path $Dir ('acl-probe-dir-' + [guid]::NewGuid().ToString('N'))
  $mkdir = $true
  try { [IO.Directory]::CreateDirectory($sub) | Out-Null } catch { $mkdir = $false }
  if ($mkdir) { Remove-Item -Force $sub }
  "acl:"
  & icacls.exe $Dir
  "write file as current (non-elevated) user: $writable"
  "create folder as current (non-elevated) user: $mkdir"
  if ($writable -or $mkdir) { exit 1 }
}
