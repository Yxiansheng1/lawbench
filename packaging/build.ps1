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
  [string]$BuildPython = 'python'
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Dsh = Join-Path $Root 'dsh'
$AppId = 'cn.lianyue.lawbench'
# Client Python = the same python-build-standalone 3.12.14 archive the DSH desktop bundles (same file, same sha256,
# taken from DSH's verified download cache), unpacked into our own directory: our packages go into its own
# site-packages, so child processes started with sys.executable (the ID-card driver) see them. The DSH payload is
# not modified. See dsh-patches\PATCHES.md "conclusions" and docs\plan\evidence\T20\python-reuse.txt.
$PyLock = Get-Content -Raw (Join-Path $Dsh 'scripts\primary-runtime\lock.json') | ConvertFrom-Json
$PySha = $PyLock.targets.'win-x64'.pythonSha256
$PyArchive = Join-Path $Dsh ('apps\desktop\.desktop-build\downloads\' + $PySha)

function Say([string]$m) { Write-Host "[build] $m" }
function Pending([string]$what) { throw "PENDING (T20 step 3/6): $what" }
function Run([string]$exe, [string[]]$argv) {
  & $exe @argv
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
      Run 'corepack' @('pnpm@11.7.0', 'install', '--frozen-lockfile')
      Run 'corepack' @('pnpm@11.7.0', 'run', 'build')
    } finally { Pop-Location }
    Run 'node' @((Join-Path $Root 'dsh-ext\scripts\build.mjs'))
  }
  python = {
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
    Run $py @('-I', '-m', 'pip', 'install', '--no-index', '--find-links', $Wheelhouse, '-r', $req)
    # sitecustomize drops the per-user site-packages for child processes; the .pth puts <install>\service on the path
    Copy-Item -Force (Join-Path $Root 'packaging\python\sitecustomize.py') $site
    Copy-Item -Force (Join-Path $Root 'packaging\python\lawbench-service.pth') $site
    Copy-Item -Recurse -Force (Join-Path $Root 'service\lawbench') (Join-Path $Stage 'service\lawbench')
    # The Host starts the service as: <install>\python\python.exe -I -m lawbench
    Run $py @('-I', '-m', 'lawbench', '--help')
  }
  tools = {
    Pending 'LibreOffice and pandoc payloads and tokenizer.json location (versions.lock [client] marks them PENDING)'
  }
  skills = {
    Run $BuildPython @((Join-Path $Root 'skills\_scripts\install.py'), '--out', (Join-Path $Stage 'skills'))
  }
  engines = {
    Copy-Item -Recurse -Force (Join-Path $Root 'engines') (Join-Path $Stage 'engines')
  }
  lock = {
    Run $BuildPython @((Join-Path $Root 'packaging\gen_lock.py'), '--site', (Join-Path $Stage 'python\site-packages'))
  }
  package = {
    if (-not $Package) { Say 'package skipped (pass -Package)'; return }
    Pending 'electron-builder extraResources for stage\ (python, service, skills, engines, tools) and the ProgramData skills ACL in installer.nsh'
    $env:DSH_DESKTOP_APP_ID = $AppId
    Push-Location (Join-Path $Dsh 'apps\desktop')
    try { Run 'corepack' @('pnpm@11.7.0', 'run', 'package:win:x64:unsigned') } finally { Pop-Location }
  }
}

if ($List) { $Steps.Keys | ForEach-Object { $_ }; exit 0 }
$todo = if ($Step.Count) { $Step } else { @($Steps.Keys) }
foreach ($s in $todo) {
  if (-not $Steps.Contains($s)) { throw "unknown step: $s (use -List)" }
  Say "== $s"
  & $Steps[$s]
}
Say 'done'
