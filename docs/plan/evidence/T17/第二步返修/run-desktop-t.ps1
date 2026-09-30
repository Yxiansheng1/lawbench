param([string]$Mode = 'start:desktop', [string]$Log, [string]$CaseRoot = '', [string]$LlmReply = '', [string]$FailContext = '')
# Dev launch with LOCALAPPDATA, APPDATA and DSH_HOME in a test directory outside the repo (ORCH note with N48).
# Keep this file ASCII-only: Windows PowerShell 5 reads BOM-less files in the ANSI code page.
$T = 'D:\lawbench-devhome-A'
if (-not $T) { throw 'test home not set' }
Set-Location D:\lawbench-A\dsh
$env:CI = 'true'
$env:ELECTRON_MIRROR = 'https://npmmirror.com/mirrors/electron/'
$env:LOCALAPPDATA = "$T\Local"
$env:APPDATA = "$T\Roaming"
$env:DSH_HOME = "$T\dsh-home"
$env:DSH_TELEMETRY_DISABLED = '1'
Remove-Item Env:LAWFIRM_KEY -ErrorAction SilentlyContinue
$env:LAWBENCH_SERVICE_CMD = '["D:\\node\\node.exe","D:\\lawbench-A\\dsh-ext\\dev\\fake-service.mjs","--calls","D:\\lawbench-devhome-A\\fake-calls.jsonl","--fixtures"]'
if ($CaseRoot) { $env:LAWBENCH_SERVICE_CMD = $env:LAWBENCH_SERVICE_CMD.TrimEnd(']') + ',' + (ConvertTo-Json '--case-root') + ',' + (ConvertTo-Json $CaseRoot) + ']' }
if ($LlmReply) { $env:LAWBENCH_SERVICE_CMD = $env:LAWBENCH_SERVICE_CMD.TrimEnd(']') + ',' + (ConvertTo-Json '--llm-reply') + ',' + (ConvertTo-Json $LlmReply) + ']' }
if ($FailContext) { $env:LAWBENCH_SERVICE_CMD = $env:LAWBENCH_SERVICE_CMD.TrimEnd(']') + ',"--fail-context","' + $FailContext + '"]' }
$env:LAWBENCH_SERVICE_PORTS = '18801-18809'
$env:LAWBENCH_SERVICE_CWD = 'D:\lawbench-A\dsh-ext'
$env:LAWBENCH_SKILLS_DIR = 'D:\lawbench-A\skills'
Remove-Item Env:DSH_TOOLS_MODE -ErrorAction SilentlyContinue
corepack pnpm@11.7.0 run $Mode *> $Log
