$p = Get-NetTCPConnection -LocalPort 3245 -State Listen -ErrorAction SilentlyContinue |
     Select-Object -First 1 -ExpandProperty OwningProcess
if ($p) { Stop-Process -Id $p -Force; Write-Output "stopped pid $p" } else { Write-Output "no listener on 3245" }
Start-Sleep -Seconds 2
$q = Get-NetTCPConnection -LocalPort 3245 -State Listen -ErrorAction SilentlyContinue |
     Select-Object -First 1 -ExpandProperty OwningProcess
Write-Output "listener after stop: $q"
