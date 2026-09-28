$conn = Get-NetTCPConnection -LocalPort 17801 -State Listen -ErrorAction SilentlyContinue
if (-not $conn) {
  Write-Host "  Engine is not running (port 17801 is free)."
  exit 0
}
$procIds = $conn | Select-Object -ExpandProperty OwningProcess -Unique
foreach ($procId in $procIds) {
  $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
  if ($p) {
    try {
      Stop-Process -Id $procId -Force -ErrorAction Stop
      Write-Host ("  Stopped: " + $p.ProcessName + " (PID " + $procId + ")")
    } catch {
      Write-Host ("  Failed to stop PID " + $procId + ": " + $_.Exception.Message)
    }
  } else {
    Write-Host ("  Skipped PID " + $procId + " (process not found)")
  }
}
