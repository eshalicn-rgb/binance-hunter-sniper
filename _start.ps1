Start-Process -FilePath "C:\Python314\pythonw.exe" -ArgumentList "app.py" `
  -WorkingDirectory "G:\GrokMT5Bot\binance_hunter"
Start-Sleep -Seconds 5
$q = Get-NetTCPConnection -LocalPort 3245 -State Listen -ErrorAction SilentlyContinue |
     Select-Object -First 1 -ExpandProperty OwningProcess
Write-Output "listening pid: $q"
