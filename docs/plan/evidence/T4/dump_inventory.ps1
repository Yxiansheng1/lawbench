# T4 取证：从运行中的桌面端 Host 读插件清单（pluginInventory/list，只读），存为 JSON。
# 清单里的 enabled 是 Loader 在桌面端语境下求值后的实际状态（含 !!js 条件）。
# 用法：.\dump_inventory.ps1 -Url '<启动日志里 dsh web: 那一行的地址>' -Out plugin-inventory-desktop.json
param([Parameter(Mandatory)] [string]$Url, [Parameter(Mandatory)] [string]$Out)
$u = [Uri]$Url
if ($u.Host -ne '127.0.0.1') { throw '只允许本机地址' }
$s = New-Object Microsoft.PowerShell.Commands.WebRequestSession
Invoke-WebRequest -Uri $Url -WebSession $s -UseBasicParsing | Out-Null
$body = @{ type = 'client-request'; rpcId = [guid]::NewGuid().ToString(); method = 'pluginInventory/list'; payload = @{ args = @{} } } | ConvertTo-Json -Depth 5
$r = Invoke-WebRequest -Uri "$($u.Scheme)://$($u.Authority)/api/pluginInventory/list" -Method Post -WebSession $s -ContentType 'application/json' -Body $body -UseBasicParsing
$Out = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Out)
$bytes = [Text.Encoding]::UTF8.GetBytes($r.Content)
[IO.File]::WriteAllBytes($Out, $bytes)
"saved $Out ($($bytes.Length) bytes)"
