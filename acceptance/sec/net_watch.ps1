<#
.SYNOPSIS
  上线必过第 1、24、25 项（SEC-03、SEC-10）：运行期间客户端相关进程只连律所两台服务器和本机。
.DESCRIPTION
  不装抓包软件的简易做法：每秒记录一次指定进程的 TCP 连接（Get-NetTCPConnection）的远端地址，
  并在开始、结束时各取一次 DNS 缓存，新增的域名解析也列出来（有解析就说明有程序想连外网）。
  结束后与白名单比对：不在白名单的远端地址 = 不通过；期间一个相关进程都没看到 = 前提不满足。
  UDP 和不经本机 DNS 缓存的解析看不到；正式验收同时按 acceptance\manual\抓包.md 用 pktmon 抓全量包。
.EXAMPLE
  .\acceptance\sec\net_watch.ps1 -Minutes 30          # 期间在客户端里走导入、识别、wiki、对话、导出、发票、委托材料
  .\acceptance\sec\net_watch.ps1 -Seconds 20 -ProcessName python   # 试跑
#>
param(
  [int]$Minutes = 0,
  [int]$Seconds = 0,
  [string[]]$ProcessName = @("律师工作台*", "lawbench*", "dsh*", "electron*", "python*", "pythonw*", "soffice*", "pandoc*", "node*", "WINWORD*", "wps*"),
  [string[]]$Allow = @("192.168.8.77", "10.126.126.1", "192.168.8.124", "10.126.126.3", "127.0.0.1", "::1"),
  [string]$Out = ""
)
$ErrorActionPreference = "Stop"
$duration = if ($Seconds -gt 0) { $Seconds } elseif ($Minutes -gt 0) { $Minutes * 60 } else { 60 }
if (-not $Out) { $Out = Join-Path $PSScriptRoot "..\_out" }
New-Item -ItemType Directory -Force $Out | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$file = Join-Path $Out "net_watch-$stamp.txt"
$lines = New-Object System.Collections.Generic.List[string]
function Log($s) { Write-Host $s; $lines.Add($s) }

Log "# net_watch　对应：SEC-03、SEC-10；上线必过第 1、24、25 项"
Log "# 运行时间：$(Get-Date -Format 'yyyy-MM-ddTHH:mm:sszzz')，时长 $duration 秒"
Log "# 进程名：$($ProcessName -join ', ')"
Log "# 白名单：$($Allow -join ', ')"

$dnsBefore = @{}
try { Get-DnsClientCache -ErrorAction Stop | ForEach-Object { $dnsBefore[$_.Entry] = 1 } } catch { Log "注意：读不到 DNS 缓存（$($_.Exception.GetType().Name)）" }

$seenProcs = @{}
$remotes = @{}
$end = (Get-Date).AddSeconds($duration)
while ((Get-Date) -lt $end) {
  $procs = @{}
  foreach ($pn in $ProcessName) {
    Get-Process -Name $pn -ErrorAction SilentlyContinue | ForEach-Object { $procs[$_.Id] = $_.ProcessName }
  }
  foreach ($id in $procs.Keys) { $seenProcs[$procs[$id]] = 1 }
  if ($procs.Count -gt 0) {
    Get-NetTCPConnection -ErrorAction SilentlyContinue | Where-Object { $procs.ContainsKey([int]$_.OwningProcess) } | ForEach-Object {
      $ra = $_.RemoteAddress
      if ($ra -and $ra -ne "0.0.0.0" -and $ra -ne "::") {
        $key = "${ra}:$($_.RemotePort)"
        if (-not $remotes.ContainsKey($key)) { $remotes[$key] = "$($procs[[int]$_.OwningProcess])（首次 $(Get-Date -Format 'HH:mm:ss')，状态 $($_.State)）" }
      }
    }
  }
  Start-Sleep -Seconds 1
}

$newDns = @()
try { $newDns = Get-DnsClientCache -ErrorAction Stop | Where-Object { -not $dnsBefore.ContainsKey($_.Entry) } | Select-Object -ExpandProperty Entry -Unique } catch { }

Log ""
Log "看到的相关进程：$((@($seenProcs.Keys) | Sort-Object) -join ', ')"
Log "远端地址（$($remotes.Count) 个）："
$bad = @()
foreach ($k in ($remotes.Keys | Sort-Object)) {
  $ip = $k.Substring(0, $k.LastIndexOf(":"))
  $ok = $Allow -contains $ip
  Log "  $k　$($remotes[$k])$(if (-not $ok) { '　← 白名单外' })"
  if (-not $ok) { $bad += $k }
}
Log "期间新增的 DNS 解析（全机，供参考）：$(if ($newDns) { $newDns -join ', ' } else { '无' })"

if ($seenProcs.Count -eq 0) { $verdict = "前提不满足"; $why = "期间没有看到任何相关进程（客户端没有运行）"; $code = 2 }
elseif ($bad.Count -gt 0) { $verdict = "不通过"; $why = "相关进程连接了白名单外的地址：$($bad -join ', ')"; $code = 1 }
else { $verdict = "通过"; $why = "相关进程只连接了律所两台服务器和本机" ; $code = 0 }
Log ""
Log "结论：$verdict（$why）"
$lines | Out-File -Encoding utf8 $file
Write-Host "证据文件：$file"
exit $code
