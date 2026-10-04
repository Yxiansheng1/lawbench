<#
  Admin Skill directory: ordinary users may read, only SYSTEM and Administrators may write (T20 step 3 item 3;
  Spec 10.1 "%ProgramData%\<product>\skills, ordinary users read-only").

  Usage (elevated; the installer's optional finish-page item runs it the same way):  set-skills-acl.ps1
        (same as  set-skills-acl.ps1 -Dir "$env:ProgramData\lawbench\skills")
  Simulation (not elevated, any test folder you own):  set-skills-acl.ps1 -Dir <temp folder> -Verify

  - Inheritance from %ProgramData% is removed (by default it lets every user create files and folders there).
  - Grants use well-known SIDs so it works on any display language:
      S-1-5-18 SYSTEM, S-1-5-32-544 Administrators : full control
      S-1-5-32-545 Users                            : read and execute
  - The folder itself gets these rights (no /T: applied to files, /inheritance:r /grant:r would leave them with
    an empty ACL nobody can read); everything already inside is then reset to inherit from the folder.
  Keep this file ASCII-only (Windows PowerShell 5 reads BOM-less files in the ANSI code page).
#>
param(
  # Default: the admin Skill folder the client reads (%ProgramData%\lawbench\skills; dsh-ext\host\install-layout.ts
  # ADMIN_DIR_NAME). Run without arguments in most cases (note 2053: users did not know what to pass).
  [string]$Dir = (Join-Path $env:ProgramData 'lawbench\skills'),
  [switch]$Verify
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path $Dir)) { New-Item -ItemType Directory -Force $Dir | Out-Null }

& icacls.exe $Dir /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-32-545:(OI)(CI)RX' /C /Q
if ($LASTEXITCODE -ne 0) { throw "icacls failed ($LASTEXITCODE)" }
if (Get-ChildItem -Force $Dir) {
  & icacls.exe (Join-Path $Dir '*') /reset /T /C /Q
  if ($LASTEXITCODE -ne 0) { throw "icacls reset of the contents failed ($LASTEXITCODE)" }
}

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
  # existing content must stay readable (only the folder's own ACL changes; children inherit it)
  $unreadable = @()
  foreach ($f in Get-ChildItem -Recurse -File -Force $Dir) {
    try { [IO.File]::ReadAllBytes($f.FullName) | Out-Null } catch { $unreadable += $f.FullName.Substring($Dir.Length) }
  }
  "existing files readable as current user: $(-not $unreadable)$(if ($unreadable) { ' (not: ' + ($unreadable -join ', ') + ')' })"
  "write file as current (non-elevated) user: $writable"
  "create folder as current (non-elevated) user: $mkdir"
  if ($writable -or $mkdir -or $unreadable) { exit 1 }
}
