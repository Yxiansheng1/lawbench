# One-time migration after the 2026-09-28 requirement change.
# Run once in PowerShell from the repo root:  powershell -ExecutionPolicy Bypass -File scripts\migrate_20260928.ps1
#
# What it does (ASCII-only on purpose: Windows PowerShell 5.1 misreads UTF-8 without BOM):
#   1. skills\invoice-ledger-db_V3.9.4  -> engines\invoice-ledger   (files already updated in engines\ are kept;
#                                                                    the originals of those files are dropped)
#   2. skills\retainer-offline (3)      -> engines\retainer
#   3. skills\lawyer-archiving-1.0.0    -> docs\reference\client-skills\lawyer-archiving-1.0.0
#   4. deletes the invoice license files, skills\entries\, contracts\skill\entry.schema.json, __pycache__ folders
#   5. git add -A, then shows git status. It does NOT commit.

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root
Write-Host "repo: $root"

function Merge-Move([string]$src, [string]$dst) {
    if (-not (Test-Path -LiteralPath $src)) { Write-Host "skip (not found): $src"; return }
    if (-not (Test-Path -LiteralPath $dst)) {
        New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent) | Out-Null
        Move-Item -LiteralPath $src -Destination $dst
        Write-Host "moved: $src -> $dst"
        return
    }
    $srcFull = (Resolve-Path -LiteralPath $src).Path
    $kept = 0; $moved = 0
    Get-ChildItem -LiteralPath $srcFull -Recurse -File -Force | ForEach-Object {
        $rel = $_.FullName.Substring($srcFull.Length).TrimStart('\')
        $target = Join-Path $dst $rel
        if (Test-Path -LiteralPath $target) {
            Remove-Item -LiteralPath $_.FullName -Force; $kept++
        } else {
            New-Item -ItemType Directory -Force -Path (Split-Path $target -Parent) | Out-Null
            Move-Item -LiteralPath $_.FullName -Destination $target; $moved++
        }
    }
    Remove-Item -LiteralPath $srcFull -Recurse -Force
    Write-Host "merged: $src -> $dst (moved $moved, kept updated $kept)"
}

Merge-Move 'skills\invoice-ledger-db_V3.9.4' 'engines\invoice-ledger'
Merge-Move 'skills\retainer-offline (3)'     'engines\retainer'
Merge-Move 'skills\lawyer-archiving-1.0.0'   'docs\reference\client-skills\lawyer-archiving-1.0.0'

$remove = @(
    'engines\invoice-ledger\scripts\license_gate.py',
    'engines\invoice-ledger\scripts\license_cli.py',
    'engines\invoice-ledger\license-public.json',
    'engines\invoice-ledger\license.json',
    'skills\entries',
    'contracts\skill\entry.schema.json'
)
foreach ($p in $remove) {
    if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Recurse -Force; Write-Host "removed: $p" }
}
Get-ChildItem -Path engines, skills, contracts -Recurse -Directory -Force -Filter '__pycache__' -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }

$left = @('skills\invoice-ledger-db_V3.9.4', 'skills\retainer-offline (3)', 'skills\lawyer-archiving-1.0.0') |
    Where-Object { Test-Path -LiteralPath $_ }
if ($left) { throw "still present: $($left -join ', ')" }

git add -A
git status --short | Select-Object -First 40
Write-Host ''
Write-Host 'Next: run the checks, then commit:'
Write-Host '  python contracts\check_examples.py --skills skills'
Write-Host '  python skills\_scripts\build_skills.py --root skills --check'
Write-Host '  git commit -m "Requirement change 2026-09-28: PRD v4, Spec v3, contracts 1.1, capsules, client tools"'
