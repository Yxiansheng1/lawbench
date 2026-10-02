<#
  lawbench Windows installer build (T20). One command builds the installer; every step can also run alone.

  Usage (repository root, PowerShell 5+):
    .\packaging\build.ps1                      # all steps except 'package' (see below)
    .\packaging\build.ps1 -Step brand,python   # only these steps, in the given order
    .\packaging\build.ps1 -List                # print the steps
    .\packaging\build.ps1 -Package             # also run the final 'package' step (electron-builder, NSIS)

  Status 2026-10-02 (T20 preparation, order 2301): skeleton. Steps marked PENDING stop with a clear message;
  they belong to T20 step 3 (LibreOffice, pandoc, tokenizer, payload layout) and step 6 (clean-machine install,
  needs the owner). No installer is produced tonight.

  Keep this file ASCII-only: Windows PowerShell 5 reads BOM-less files in the ANSI code page.
  No keys, passwords or real case files are read or written here.
#>
param(
  [string[]]$Step = @(),
  [switch]$List,
  [switch]$Package,
  # Directory with the offline wheels for the client Python (pip download on a build machine with access;
  # nothing is downloaded at install or run time).
  [string]$Wheelhouse = (Join-Path $PSScriptRoot 'wheelhouse'),
  [string]$Stage = (Join-Path $PSScriptRoot 'stage'),
  [string]$Out = (Join-Path $PSScriptRoot 'out'),
  # Build-machine Python used for the helper scripts (brand assets need Pillow); not shipped.
  [string]$BuildPython = 'python',
  # Payload sources for the 'tools' step (offline: an installed LibreOffice folder, a pandoc.exe, the Qwen3
  # tokenizer.json). Versions and hashes are recorded by the 'lock' step.
  [string]$LibreOfficeDir = '',
  [string]$PandocExe = '',
  [string]$Tokenizer = '',
  # 'package' step: list what would be packaged instead of running electron-builder.
  [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Dsh = Join-Path $Root 'dsh'
$AppId = 'cn.lianyue.lawbench'
# Client Python = the same python-build-standalone 3.12.14 archive the DSH desktop bundles (same file, same sha256,
# taken from DSH's verified download cache), unpacked into our own directory: our packages go into its own
# site-packages, so child processes started with sys.executable (the ID-card driver) see them. The DSH payload is
# not modified. See dsh-patches\PATCHES.md "conclusions" and docs\plan\evidence\T20\python-reuse.txt.
# (DSH's lock.json is read inside the python step, so -List, preflight and brand work without the submodule.)

function Say([string]$m) { Write-Host "[build] $m" }
# Copy-Item -Recurse into an existing folder nests it (lawbench\lawbench): always start from an empty target.
function Reset-Dir([string]$dir) {
  if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }
  New-Item -ItemType Directory -Force $dir | Out-Null
}
function Pending([string]$what) { throw "PENDING (T20 step 3/6): $what" }
function Run([string]$exe, [string[]]$argv) {
  # Native tools write warnings to stderr; in Windows PowerShell 5.1 that becomes an error record when output is
  # redirected, which 'Stop' would turn fatal. Judge native commands by their exit code only.
  $saved = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try { & $exe @argv 2>&1 | ForEach-Object { "$_" } } finally { $ErrorActionPreference = $saved }
  if ($LASTEXITCODE -ne 0) { throw "failed ($LASTEXITCODE): $exe $($argv -join ' ')" }
}

$Steps = [ordered]@{
  preflight = {
    foreach ($t in 'git', 'node', $BuildPython) { if (-not (Get-Command $t -ErrorAction SilentlyContinue)) { throw "missing tool: $t" } }
    Run $BuildPython @('-c', 'import PIL')  # brand assets need Pillow
    Run 'git' @('-C', $Root, 'diff', '--quiet', '--', 'contracts')  # contracts must be committed
    Say 'tools present'
  }
  brand = {
    Run $BuildPython @((Join-Path $Root 'packaging\brand\make_brand.py'))
  }
  dsh = {
    # Apply the registered patches in order (dsh-patches\PATCHES.md), then copy the P-4 images.
    $patches = Select-String -Path (Join-Path $Root 'dsh-patches\PATCHES.md') -Pattern 'git -C dsh apply \.\.\\dsh-patches\\(\S+\.patch)' |
      ForEach-Object { $_.Matches[0].Groups[1].Value }
    $dirty = (& git -C $Dsh status --porcelain)
    if ($dirty) { Say 'dsh working tree already modified: assuming the patches are applied (check with git -C dsh diff)' }
    else { foreach ($p in $patches) { Run 'git' @('-C', $Dsh, 'apply', (Join-Path '..\dsh-patches' $p)) } }
    Copy-Item -Recurse -Force (Join-Path $Root 'packaging\brand\desktop\*') (Join-Path $Dsh 'apps\desktop\')
    Push-Location $Dsh
    try {
      $env:CI = 'true'
      $env:COREPACK_ENABLE_NETWORK = '0'  # corepack must not fetch pnpm either
      Run 'corepack' @('pnpm@11.7.0', 'install', '--frozen-lockfile', '--offline')
      Run 'corepack' @('pnpm@11.7.0', 'run', 'build')
    } finally { Pop-Location }
    Run 'node' @((Join-Path $Root 'dsh-ext\scripts\build.mjs'))
  }
  python = {
    $pyLock = Get-Content -Raw (Join-Path $Dsh 'scripts\primary-runtime\lock.json') | ConvertFrom-Json
    $PySha = $pyLock.targets.'win-x64'.pythonSha256
    $PyArchive = Join-Path $Dsh ('apps\desktop\.desktop-build\downloads\' + $PySha)
    if (-not (Test-Path $PyArchive)) { throw "DSH Python archive not in the download cache: $PyArchive (run the dsh step first)" }
    $hash = (Get-FileHash -Algorithm SHA256 $PyArchive).Hash.ToLower()
    if ($hash -ne $PySha) { throw "DSH Python archive hash mismatch: $hash" }
    if (Test-Path (Join-Path $Stage 'python')) { Remove-Item -Recurse -Force (Join-Path $Stage 'python') }
    New-Item -ItemType Directory -Force $Stage | Out-Null
    # Windows' own bsdtar (Git's GNU tar on PATH misreads D:\ paths); unpacks to stage\python
    Run (Join-Path $env:SystemRoot 'System32\tar.exe') @('-xzf', $PyArchive, '-C', $Stage)
    $py = Join-Path $Stage 'python\python.exe'
    $site = Join-Path $Stage 'python\Lib\site-packages'
    $req = Join-Path $Stage 'requirements.txt'
    # The pinned set is [client.pip] in packaging\versions.lock
    $inClient = $false
    $pins = foreach ($l in Get-Content (Join-Path $Root 'packaging\versions.lock')) {
      if ($l -match '^\[') { $inClient = $l -match '^\[client\.pip\]'; continue }
      if ($inClient -and $l -match '^[A-Za-z0-9_.\-]+==') { $l }
    }
    if (-not $pins) { throw 'no [client.pip] pins in packaging\versions.lock (run the lock step)' }
    $pins | Set-Content -Encoding ascii $req
    if (-not (Test-Path $Wheelhouse)) { Pending "offline wheelhouse $Wheelhouse (pip download -r $req on a build machine)" }
    Run $py @('-I', '-m', 'pip', 'install', '--no-index', '--no-warn-script-location', '--find-links', $Wheelhouse, '-r', $req)
    # python312._pth fixes sys.path for every process using this interpreter, with or without -I (child processes
    # such as the ID-card driver included): no PYTHONPATH, no per-user site-packages; 'import site' keeps .pth
    # processing (pywin32). sitecustomize stays as a second guard.
    Copy-Item -Force (Join-Path $Root 'packaging\python\python312._pth') (Join-Path $Stage 'python\')
    Copy-Item -Force (Join-Path $Root 'packaging\python\sitecustomize.py') $site
    # Each step clears only what it places: keep the tokenizer.json the tools step put under service\ (re-running
    # the python step alone must not drop it).
    $tok = Join-Path $Stage 'service\lawbench\llm\tokenizer.json'
    $keptTok = $null
    if (Test-Path $tok) { $keptTok = Join-Path $Stage 'tokenizer.json.keep'; Move-Item -Force $tok $keptTok }
    Reset-Dir (Join-Path $Stage 'service')
    Copy-Item -Recurse -Force (Join-Path $Root 'service\lawbench') (Join-Path $Stage 'service\lawbench')
    if ($keptTok) { Move-Item -Force $keptTok $tok }
    # The service finds contracts\ at <install>\contracts (REPO_ROOT = parents[2] of service\lawbench\config.py)
    Reset-Dir (Join-Path $Stage 'contracts')
    Copy-Item -Recurse -Force (Join-Path $Root 'contracts\*') (Join-Path $Stage 'contracts')
    # The Host starts the service as: <install>\python\python.exe -I -m lawbench
    Run $py @('-I', '-m', 'lawbench', '--help')
  }
  tools = {
    $missing = @()
    if ($LibreOfficeDir -and (Test-Path (Join-Path $LibreOfficeDir 'program\soffice.exe'))) {
      Reset-Dir (Join-Path $Stage 'tools\libreoffice')
      Copy-Item -Recurse -Force (Join-Path $LibreOfficeDir '*') (Join-Path $Stage 'tools\libreoffice')
    } else { $missing += 'LibreOffice (-LibreOfficeDir <folder with program\soffice.exe>)' }
    if ($PandocExe -and (Test-Path $PandocExe)) {
      New-Item -ItemType Directory -Force (Join-Path $Stage 'tools\pandoc') | Out-Null
      Copy-Item -Force $PandocExe (Join-Path $Stage 'tools\pandoc\pandoc.exe')
    } else { $missing += 'pandoc (-PandocExe <pandoc.exe>)' }
    if ($Tokenizer -and (Test-Path $Tokenizer)) {
      New-Item -ItemType Directory -Force (Join-Path $Stage 'service\lawbench\llm') | Out-Null
      Copy-Item -Force $Tokenizer (Join-Path $Stage 'service\lawbench\llm\tokenizer.json')
    } else { $missing += 'tokenizer.json (-Tokenizer <file>)' }
    if ($missing) { Pending ('payload sources not given: ' + ($missing -join '; ')) }
  }
  skills = {
    Reset-Dir (Join-Path $Stage 'skills')
    Run $BuildPython @((Join-Path $Root 'skills\_scripts\install.py'), '--out', (Join-Path $Stage 'skills'))
    # the one-time elevated step for the admin Skill folder ships with the install
    New-Item -ItemType Directory -Force (Join-Path $Stage 'installer') | Out-Null
    Copy-Item -Force (Join-Path $Root 'packaging\installer\set-skills-acl.ps1') (Join-Path $Stage 'installer\')
  }
  engines = {
    Reset-Dir (Join-Path $Stage 'engines')
    Copy-Item -Recurse -Force (Join-Path $Root 'engines\*') (Join-Path $Stage 'engines')
  }
  lock = {
    Run $BuildPython @((Join-Path $Root 'packaging\gen_lock.py'), '--site', (Join-Path $Stage 'python\Lib\site-packages'), '--stage', $Stage)
  }
  package = {
    if (-not $Package -and -not $DryRun) { Say 'package skipped (pass -Package, or -DryRun to list the payload)'; return }
    # P-4 hands $Stage to electron-builder as extraFiles (next to the executable); requirements.txt is left out.
    $files = Get-ChildItem -Recurse -File $Stage | Where-Object { $_.FullName -ne (Join-Path $Stage 'requirements.txt') }
    Say ("payload from {0}: {1} files, {2:N0} MB" -f $Stage, $files.Count, (($files | Measure-Object -Sum Length).Sum / 1MB))
    $files | Group-Object { $_.FullName.Substring($Stage.Length + 1).Split('\')[0] } | Sort-Object Name | ForEach-Object {
      Say ("  {0,-10} {1,7} files {2,9:N1} MB" -f $_.Name, $_.Count, (($_.Group | Measure-Object -Sum Length).Sum / 1MB))
    }
    foreach ($need in 'python\python.exe', 'python\python312._pth', 'service\lawbench\__main__.py', 'service\lawbench\llm\tokenizer.json',
                      'contracts\VERSION', 'skills', 'engines', 'tools\libreoffice\program\soffice.exe', 'tools\pandoc\pandoc.exe',
                      'installer\set-skills-acl.ps1') {
      if (-not (Test-Path (Join-Path $Stage $need))) { Say "  MISSING: $need" }
    }
    Say 'admin Skill folder: run packaging\installer\set-skills-acl.ps1 elevated once per machine (the NSIS installer is per-user)'
    if ($DryRun) { return }
    Pending 'real installer build: run after T20 step 3 payloads are final and with the owner present (step 6)'
    $env:DSH_DESKTOP_APP_ID = $AppId
    $env:LAWBENCH_STAGE_DIR = $Stage
    Push-Location (Join-Path $Dsh 'apps\desktop')
    try { Run 'corepack' @('pnpm@11.7.0', 'run', 'package:win:x64:unsigned') } finally { Pop-Location }
  }
}

if ($List) { $Steps.Keys | ForEach-Object { $_ }; exit 0 }
# 'powershell -File build.ps1 -Step a,b' delivers one string "a,b"; split it
$Step = @($Step | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$todo = if ($Step.Count) { $Step } else { @($Steps.Keys) }
foreach ($s in $todo) {
  if (-not $Steps.Contains($s)) { throw "unknown step: $s (use -List)" }
  Say "== $s"
  & $Steps[$s]
}
Say 'done'
