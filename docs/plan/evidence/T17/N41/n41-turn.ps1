param([string]$Out)
# 发一条消息（n41-probe.mjs send），期间每 150 毫秒看一次有没有 git.exe 进程；前后数系统临时目录里的 dsh-workspace-changes-* 目录。
$d = 'C:\Users\<用户>\AppData\Local\Temp\claude\D--lawbench-A\83a515fe-3091-4d1d-bb29-68b2364c0be5\scratchpad'
$before = @(Get-ChildItem $env:TEMP -Directory -Filter 'dsh-workspace-changes-*' -ErrorAction SilentlyContinue).Name
$job = Start-Job -ScriptBlock { param($d) node "$d\n41-probe.mjs" send } -ArgumentList $d
$seen = @{}
$t0 = Get-Date
while ($job.State -eq 'Running' -and ((Get-Date) - $t0).TotalSeconds -lt 40) {
  Get-CimInstance Win32_Process -Filter "Name='git.exe'" -ErrorAction SilentlyContinue | ForEach-Object {
    if ($seen.ContainsKey($_.ProcessId)) { return }
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$($_.ParentProcessId)" -ErrorAction SilentlyContinue
    $fromDsh = [bool]($p -and ($p.CommandLine -like '*lawbench-A\dsh*' -or $p.ExecutablePath -like 'D:\lawbench-A\dsh\*'))
    $seen[$_.ProcessId] = "parent=$($p.Name) fromDSH=$fromDsh cmd=" + ($_.CommandLine -replace '\s+', ' ')
  }
  Start-Sleep -Milliseconds 150
}
$probe = Receive-Job $job -Wait
Remove-Job $job
$after = @(Get-ChildItem $env:TEMP -Directory -Filter 'dsh-workspace-changes-*' -ErrorAction SilentlyContinue).Name
$new = @($after | Where-Object { $before -notcontains $_ })
$lines = @("probe: $($probe -join ' ')", "git.exe processes seen: $($seen.Count)") + ($seen.Values | ForEach-Object { "  $_" }) + @("new dsh-workspace-changes-* dirs in TEMP: $($new.Count)") + ($new | ForEach-Object { "  $_" })
$lines | Set-Content -Encoding utf8 $Out
$lines
