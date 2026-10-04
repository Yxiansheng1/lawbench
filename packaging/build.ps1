<#
  lawbench Windows installer build (T20). One command builds the installer; every step can also run alone.

  Usage (repository root, PowerShell 5+):
    .\packaging\build.ps1                      # all steps except 'package' (see below)
    .\packaging\build.ps1 -Step brand,python   # only these steps, in the given order
    .\packaging\build.ps1 -List                # print the steps
    .\packaging\build.ps1 -Package             # also run the final 'package' step (electron-builder, NSIS)

  Status 2026-10-04 (order 1756): first candidate installer. Network use: a one-time fetch (DSH runtime cache check,
  electron-builder NSIS toolsets, PyInstaller wheels; docs\plan\evidence\T20\payload-fetch.txt) and, on every
  'package' run, DSH's prepare:dsh installing the bundled runtime's third-party npm packages from registry.npmjs.org
  (versions pinned by packaging\runtime-lock\pnpm-lock.yaml once it exists). Everything else runs offline.
  Step 6 (clean-machine offline install, capture-hosts) is the owner's.

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
  [switch]$DryRun,
  # 'dsh' step: pnpm content-addressable store for the offline install (the folder that holds v11\). Default: the
  # storeDir recorded in dsh\node_modules\.modules.yaml by an earlier install. Without it pnpm falls back to the
  # user's default store, which may lack packages (T17 round 9 finding), so a clean clone must pass this.
  [string]$PnpmStore = ''
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
# pnpm store for the dsh step: -PnpmStore, else storeDir from dsh\node_modules\.modules.yaml; neither -> stop.
# .modules.yaml records the versioned folder (D:\\.pnpm-store\\v11, JSON-escaped); --store-dir takes its parent.
function Resolve-PnpmStore([string]$dshDir) {
  $store = $PnpmStore
  $yaml = Join-Path $dshDir 'node_modules\.modules.yaml'
  if (-not $store -and (Test-Path $yaml)) {
    $m = Select-String -Path $yaml -Pattern '^\s*"?storeDir"?\s*:\s*"?([^"]+?)"?\s*,?\s*$' | Select-Object -First 1
    if ($m) { $store = $m.Matches[0].Groups[1].Value.Replace('\\', '\') }
  }
  if (-not $store) {
    throw "pnpm store unknown: no -PnpmStore and no storeDir in $yaml. Pass -PnpmStore <folder that holds v11\> (where the offline packages were fetched)."
  }
  $store = $store -replace '[\\/]v\d+[\\/]?$', ''
  if (-not (Test-Path $store)) { throw "pnpm store folder not found: $store" }
  return $store
}
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
    # Product version shown in the sidebar (dsh-ext\shared\product.ts) must equal service\pyproject.toml until T20 picks a single source
    $uiVer = [regex]::Match((Get-Content -Raw (Join-Path $Root 'dsh-ext\shared\product.ts')), "PRODUCT_VERSION = '([^']+)'").Groups[1].Value
    $svcVer = [regex]::Match((Get-Content -Raw (Join-Path $Root 'service\pyproject.toml')), '(?m)^version = "([^"]+)"').Groups[1].Value
    if (-not $uiVer -or $uiVer -ne $svcVer) { throw "version mismatch: dsh-ext\shared\product.ts '$uiVer' vs service\pyproject.toml '$svcVer'" }
    Say 'tools present'
  }
  brand = {
    Run $BuildPython @((Join-Path $Root 'packaging\brand\make_brand.py'))
  }
  dsh = {
    # Store first: stop before touching dsh if the offline install could not run.
    $store = Resolve-PnpmStore $Dsh
    Say "pnpm store: $store"
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
      Run 'corepack' @('pnpm@11.7.0', 'install', '--frozen-lockfile', '--offline', '--store-dir', $store)
      Run 'corepack' @('pnpm@11.7.0', 'run', 'build')
    } finally { Pop-Location }
    # dsh-ext has its own dependencies (yaml, ajv, ajv-formats; dsh-ext\pnpm-lock.yaml): a clean clone has no
    # dsh-ext\node_modules, so install them offline from the same store before bundling.
    Push-Location (Join-Path $Root 'dsh-ext')
    try { Run 'corepack' @('pnpm@11.7.0', 'install', '--frozen-lockfile', '--offline', '--store-dir', $store) } finally { Pop-Location }
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
    # --no-compile: no __pycache__ in the shipped interpreter (T20 review P3-2: 640 of them came from pip's compile step)
    Run $py @('-I', '-m', 'pip', 'install', '--no-index', '--no-compile', '--no-warn-script-location', '--find-links', $Wheelhouse, '-r', $req)
    # pip's console launchers (Scripts\*.exe) embed the build machine's interpreter path: broken once installed
    Get-ChildItem -File (Join-Path $Stage 'python\Scripts') -Filter '*.exe' -ErrorAction SilentlyContinue | Remove-Item -Force
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
    # Bytecode caches left by local test runs are not part of the payload (T20 third review NOTE)
    foreach ($d in 'service', 'contracts', 'python') {
      Get-ChildItem -Recurse -Force -Directory -Filter '__pycache__' (Join-Path $Stage $d) | Remove-Item -Recurse -Force
      Get-ChildItem -Recurse -Force -File -Include '*.pyc', '*.pyo' (Join-Path $Stage $d) | Remove-Item -Force
    }
    # The Host starts the service as: <install>\python\python.exe -I -m lawbench
    Run $py @('-I', '-B', '-m', 'lawbench', '--help')  # -B: the check itself must not leave __pycache__ behind
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
      # GPL: ship pandoc's own license files next to it (T20 review P2-1). Source: the pandoc Windows install the exe
      # comes from (COPYING.rtf = GPL full text, COPYRIGHT.txt); a pandoc.exe without them stops the build.
      foreach ($f in 'COPYING.rtf', 'COPYRIGHT.txt') {
        $src = Join-Path (Split-Path $PandocExe) $f
        if (-not (Test-Path $src)) { throw "pandoc license file missing next to ${PandocExe}: $f" }
        Copy-Item -Force $src (Join-Path $Stage "tools\pandoc\$f")
      }
    } else { $missing += 'pandoc (-PandocExe <pandoc.exe>)' }
    if ($Tokenizer -and (Test-Path $Tokenizer)) {
      New-Item -ItemType Directory -Force (Join-Path $Stage 'service\lawbench\llm') | Out-Null
      Copy-Item -Force $Tokenizer (Join-Path $Stage 'service\lawbench\llm\tokenizer.json')
    } else { $missing += 'tokenizer.json (-Tokenizer <file>)' }
    if ($missing) { Pending ('payload sources not given: ' + ($missing -join '; ')) }
  }
  # The two small tools (tools\splitter, tools\convert) as windowed PyInstaller one-folder programs under
  # $Stage\tools\<name>\. Built with a separate copy of the same Python (build-tools\python, not shipped) holding
  # PyInstaller (packaging\build-tools\pyinstaller, fetched once, see evidence\T20\payload-fetch.txt) and the
  # tools' pinned dependencies from the offline wheelhouse. Offline: --no-index only.
  smalltools = {
    $pyLock = Get-Content -Raw (Join-Path $Dsh 'scripts\primary-runtime\lock.json') | ConvertFrom-Json
    $PyArchive = Join-Path $Dsh ('apps\desktop\.desktop-build\downloads\' + $pyLock.targets.'win-x64'.pythonSha256)
    if (-not (Test-Path $PyArchive)) { throw "DSH Python archive not in the download cache: $PyArchive" }
    $bt = Join-Path $PSScriptRoot 'build-tools'
    $piDir = Join-Path $bt 'pyinstaller'
    if (-not (Get-ChildItem -ErrorAction SilentlyContinue (Join-Path $piDir 'pyinstaller-*.whl'))) { throw "PyInstaller wheels missing in $piDir (see evidence\T20\payload-fetch.txt)" }
    if (-not (Test-Path $Wheelhouse)) { throw "offline wheelhouse missing: $Wheelhouse" }
    Reset-Dir (Join-Path $bt 'py')
    Run (Join-Path $env:SystemRoot 'System32\tar.exe') @('-xzf', $PyArchive, '-C', (Join-Path $bt 'py'))
    $bpy = Join-Path $bt 'py\python\python.exe'
    $want = 'pillow', 'numpy', 'pypdfium2', 'pypdf', 'python-docx', 'openpyxl', 'lxml', 'typing-extensions', 'et-xmlfile'
    $pins = foreach ($l in Get-Content (Join-Path $Root 'packaging\versions.lock')) {
      if ($l -match '^([A-Za-z0-9_.\-]+)==' -and ($want -contains $Matches[1].ToLower().Replace('_', '-'))) { $l }
    }
    $pins = @($pins | Select-Object -Unique)
    Run $bpy (@('-m', 'pip', 'install', '--no-index', '--no-warn-script-location', '--find-links', $Wheelhouse, '--find-links', $piDir, 'pyinstaller') + $pins)
    $entry = Join-Path $bt 'entry'
    Reset-Dir $entry
    foreach ($t in 'splitter', 'convert') {
      Set-Content -Encoding ascii (Join-Path $entry "$t-main.py") "from $t.app import main`r`nmain()`r`n"
      Reset-Dir (Join-Path $Stage "tools\$t")
      Remove-Item -Recurse -Force (Join-Path $Stage "tools\$t")
      Run $bpy @('-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed', '--onedir', '--name', $t,
                 '--distpath', (Join-Path $Stage 'tools'), '--workpath', (Join-Path $bt "work-$t"), '--specpath', $entry,
                 '--paths', (Join-Path $Root 'tools'), '--paths', (Join-Path $Root "tools\$t"),
                 '--hidden-import', 'pypdfium2', '--collect-all', 'pypdfium2', '--collect-all', 'pypdfium2_raw',
                 (Join-Path $entry "$t-main.py"))
      if (-not (Test-Path (Join-Path $Stage "tools\$t\$t.exe"))) { throw "small tool not built: $t" }
    }
    Say 'small tools: tools\splitter\splitter.exe, tools\convert\convert.exe'
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
    # The license table ships at the install root (T20 review P2-1)
    Copy-Item -Force (Join-Path $Root 'packaging\THIRD-PARTY-LICENSES.md') (Join-Path $Stage 'THIRD-PARTY-LICENSES.md')
  }
  package = {
    if (-not $Package -and -not $DryRun) { Say 'package skipped (pass -Package, or -DryRun to list the payload)'; return }
    # P-4 hands $Stage to electron-builder as extraFiles (next to the executable); requirements.txt is left out.
    $files = Get-ChildItem -Recurse -File $Stage | Where-Object { $_.FullName -ne (Join-Path $Stage 'requirements.txt') }
    Say ("payload from {0}: {1} files, {2:N0} MB" -f $Stage, $files.Count, (($files | Measure-Object -Sum Length).Sum / 1MB))
    $files | Group-Object { $_.FullName.Substring($Stage.Length + 1).Split('\')[0] } | Sort-Object Name | ForEach-Object {
      Say ("  {0,-10} {1,7} files {2,9:N1} MB" -f $_.Name, $_.Count, (($_.Group | Measure-Object -Sum Length).Sum / 1MB))
    }
    $missingPayload = @()
    foreach ($need in 'python\python.exe', 'python\python312._pth', 'service\lawbench\__main__.py', 'service\lawbench\llm\tokenizer.json',
                      'contracts\VERSION', 'skills', 'engines', 'tools\libreoffice\program\soffice.exe', 'tools\pandoc\pandoc.exe',
                      'installer\set-skills-acl.ps1', 'tools\splitter\splitter.exe', 'tools\convert\convert.exe') {
      if (-not (Test-Path (Join-Path $Stage $need))) { Say "  MISSING: $need"; $missingPayload += $need }
    }
    Say 'admin Skill folder: run packaging\installer\set-skills-acl.ps1 elevated once per machine (the NSIS installer is per-user)'
    # A missing payload item fails the step, -DryRun included (T20 third review NOTE: it used to exit 0)
    if ($missingPayload) { throw ('payload incomplete: ' + ($missingPayload -join ', ')) }
    if ($DryRun) { return }
    $env:LAWBENCH_STAGE_DIR = $Stage
    $env:CI = 'true'
    $env:COREPACK_ENABLE_NETWORK = '0'
    # DSH's packager reads its settings from apps\desktop\.env.windows (git-ignored; ambient DSH_DESKTOP_* values
    # are dropped). No secrets: unsigned build, no update feed. The mandatory-update origin is only validated, never
    # shipped (P-4 leaves the policy out of the package), so it points at the reserved .invalid domain.
    $envFile = Join-Path $Dsh 'apps\desktop\.env.windows'
    @(
      '# Written by packaging\build.ps1 (lawbench). No secrets. Unsigned build without update feed.',
      "DSH_DESKTOP_APP_ID=$AppId",
      'DSH_DESKTOP_AUTO_UPDATE_ENV=production',
      'DSH_DESKTOP_MANDATORY_UPDATE_PROD_ORIGIN=https://update.invalid',
      'DSH_DESKTOP_WINDOWS_SIGNATURE_CACHE_CONCURRENCY=4'
    ) | Set-Content -Encoding ascii $envFile
    # Network: Electron and the NSIS/rcedit/7za/icons toolsets come from their local caches (fetched once, see
    # evidence\T20\payload-fetch.txt); the cache listings before and after are logged to show nothing was added.
    # DSH's prepare:dsh installs the bundled runtime's third-party npm packages from registry.npmjs.org into a fresh
    # temporary store on every run (owner decision 2026-10-04: allowed for this step only; recorded in build.txt).
    $caches = @((Join-Path $env:LOCALAPPDATA 'electron\Cache'), (Join-Path $env:LOCALAPPDATA 'electron-builder\Cache\downloads'))
    $before = @($caches | ForEach-Object { Get-ChildItem -Recurse -File $_ -ErrorAction SilentlyContinue } | ForEach-Object { $_.FullName })
    # Electron for DSH's prepare-runtime comes from a 127.0.0.1 mirror of the local cache (packaging\electron-mirror.mjs):
    # the zip from %LOCALAPPDATA%\electron\Cache and a SHASUMS256.txt written from the official hashes shipped in the
    # electron npm package (node_modules\electron\checksums.json); @electron/get checks the zip against it.
    $eVer = (Get-Content -Raw (Join-Path $Dsh 'apps\desktop\node_modules\electron\package.json') | ConvertFrom-Json).version
    $eZip = "electron-v$eVer-win32-x64.zip"
    $cached = Get-ChildItem -Recurse -File (Join-Path $env:LOCALAPPDATA 'electron\Cache') -Filter $eZip -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $cached) { throw "Electron $eVer not in %LOCALAPPDATA%\electron\Cache (see evidence\T20\payload-fetch.txt)" }
    $mirror = Join-Path $PSScriptRoot 'build-tools\electron-mirror'
    Reset-Dir (Join-Path $mirror "v$eVer")
    Copy-Item -Force $cached.FullName (Join-Path $mirror "v$eVer\")
    $sums = Join-Path $mirror "v$eVer\SHASUMS256.txt"
    Run 'node' @('-e', "const c=require(process.argv[1]);require('fs').writeFileSync(process.argv[2],Object.entries(c).map(([f,h])=>h+' *'+f).join('\n')+'\n')",
                 (Join-Path $Dsh 'apps\desktop\node_modules\electron\checksums.json'), $sums)
    $want = (Select-String -Path $sums -SimpleMatch " *$eZip").Line.Split(' ')[0]
    if ((Get-FileHash -Algorithm SHA256 $cached.FullName).Hash.ToLower() -ne $want) { throw "cached $eZip does not match the official checksum" }
    # Third-party runtime npm versions pinned by packaging\runtime-lock\pnpm-lock.yaml (T20 review P2-2, P-4 prepare-dsh):
    # given to DSH's prepare:dsh, which seeds its build folder with it and writes the resolved lock back here.
    $pinnedLock = Join-Path $PSScriptRoot 'runtime-lock\pnpm-lock.yaml'
    $resolvedLock = Join-Path $Out 'runtime-pnpm-lock.yaml'
    if (Test-Path $resolvedLock) { Remove-Item -Force $resolvedLock }
    $env:LAWBENCH_RUNTIME_LOCK = $(if (Test-Path $pinnedLock) { $pinnedLock } else { '' })
    $env:LAWBENCH_RUNTIME_LOCK_OUT = $resolvedLock
    $port = 18780
    $mirrorLog = Join-Path $Out 'electron-mirror.log'
    New-Item -ItemType Directory -Force $Out | Out-Null
    $server = Start-Process -PassThru -WindowStyle Hidden -FilePath 'node' -ArgumentList @((Join-Path $PSScriptRoot 'electron-mirror.mjs'), $mirror, $port) -RedirectStandardOutput $mirrorLog
    $env:ELECTRON_MIRROR = "http://127.0.0.1:$port/"
    Push-Location (Join-Path $Dsh 'apps\desktop')
    try { Run 'corepack' @('pnpm@11.7.0', 'run', 'package:win:x64:unsigned') } finally {
      Pop-Location
      Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
      if (Test-Path $mirrorLog) { Get-Content $mirrorLog | ForEach-Object { Say $_ } }
    }
    if (-not (Test-Path $resolvedLock)) { throw "DSH prepare:dsh did not write the runtime lock to $resolvedLock" }
    if (Test-Path $pinnedLock) {
      Run 'node' @((Join-Path $PSScriptRoot 'runtime-lock-compare.mjs'), $pinnedLock, $resolvedLock)
    } else {
      New-Item -ItemType Directory -Force (Split-Path $pinnedLock) | Out-Null
      Copy-Item -Force $resolvedLock $pinnedLock
      Say "runtime lock pinned for the first time: $pinnedLock (commit it; later builds keep these third-party versions)"
    }
    $after = @($caches | ForEach-Object { Get-ChildItem -Recurse -File $_ -ErrorAction SilentlyContinue } | ForEach-Object { $_.FullName })
    $added = @($after | Where-Object { $before -notcontains $_ })
    Say ("electron / electron-builder caches: {0} files before, {1} after, added: {2}" -f $before.Count, $after.Count, $(if ($added) { $added -join ', ' } else { 'none' }))
    New-Item -ItemType Directory -Force $Out | Out-Null
    # electron-builder writes to .desktop-build\targets\win-x64\unsigned-artifacts (desktop-build-paths.mjs)
    $built = Get-ChildItem -Recurse -File (Join-Path $Dsh 'apps\desktop\.desktop-build\targets') -Filter 'lawbench-*-unsigned.exe' -ErrorAction SilentlyContinue |
      Where-Object { $_.FullName -notmatch '\\win-unpacked\\' } | Sort-Object LastWriteTime | Select-Object -Last 1
    if (-not $built) { throw 'installer not found under dsh\apps\desktop\.desktop-build\targets' }
    Copy-Item -Force $built.FullName $Out
    $outExe = Join-Path $Out $built.Name
    Say ("installer: {0}  {1:N0} MB  sha256 {2}" -f $outExe, ((Get-Item $outExe).Length / 1MB), (Get-FileHash -Algorithm SHA256 $outExe).Hash.ToLower())
  }
}

if ($List) { $Steps.Keys | ForEach-Object { $_ }; exit 0 }
# 'powershell -File build.ps1 -Step a,b' delivers one string "a,b"; split it
$Step = @($Step | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$todo = if ($Step.Count) { $Step } else { @($Steps.Keys) }
foreach ($s in $todo) {
  if (-not $Steps.Contains($s)) { throw "unknown step: $s (use -List)" }
  Say "== $s  (start $(Get-Date -Format 'HH:mm:ss'))"
  $t0 = Get-Date
  & $Steps[$s]
  Say ("== $s done in {0:N0} s" -f ((Get-Date) - $t0).TotalSeconds)
}
Say 'done'
