$ErrorActionPreference = 'Stop'
$base = 'http://127.0.0.1:3245'

function Try-Get($path) {
  try {
    $r = Invoke-WebRequest -Uri ($base + $path) -TimeoutSec 30 -UseBasicParsing
    return @{ ok = $true; code = $r.StatusCode; body = $r.Content }
  } catch {
    return @{ ok = $false; code = 'ERR'; body = $_.Exception.Message }
  }
}

$paths = @('/api/status', '/api/signals', '/api/symbols', '/api/altfins',
           '/api/plan/BTCUSDT', '/api/structure/BTCUSDT', '/api/backtest_all')

foreach ($p in $paths) {
  $r = Try-Get $p
  $len = if ($r.body) { $r.body.Length } else { 0 }
  Write-Output ("{0,-26} code={1,-5} bytes={2}" -f $p, $r.code, $len)
  if ($r.ok -and $len -gt 0 -and $len -lt 700) {
    Write-Output ("    " + ($r.body -replace '\s+', ' '))
  }
}

Write-Output ""
Write-Output "=== status keys ==="
$s = (Invoke-RestMethod -Uri ($base + '/api/status') -TimeoutSec 30)
Write-Output ("running={0} swept={1} tz={2} balance={3} watchlist={4} market={5}" -f `
  $s.running, $s.swept, $s.tz, $s.balance, ($s.watchlist | Measure-Object).Count, ($s.market | Measure-Object).Count)
Write-Output ("signals.total={0} open={1} win_rate={2} PF={3}" -f `
  $s.signals.total, $s.signals.open, $s.signals.win_rate, $s.signals.profit_factor)
Write-Output ("plans={0}  backtest.symbols={1} trades={2}  altfins.available={3} count={4} actionable={5}" -f `
  ($s.plans | Measure-Object).Count, $s.backtest.symbols, $s.backtest.trades, `
  $s.altfins.available, $s.altfins.count, $s.altfins.actionable)
Write-Output ("sweep={0}" -f $s.sweep)
Write-Output ""
Write-Output "=== symbols index ==="
$y = (Invoke-RestMethod -Uri ($base + '/api/symbols') -TimeoutSec 30)
Write-Output ("symbols={0} first5={1}" -f $y.count, (($y.symbols | Select-Object -First 5) -join ','))
Write-Output ""
Write-Output "=== plan BTCUSDT ==="
$pl = (Invoke-RestMethod -Uri ($base + '/api/plan/BTCUSDT') -TimeoutSec 30)
$pl | ConvertTo-Json -Depth 4 -Compress
