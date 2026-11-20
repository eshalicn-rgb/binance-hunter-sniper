$ErrorActionPreference = 'Stop'
$base = 'http://127.0.0.1:3245'

Write-Output "=== swarm skill loadout ==="
$sw = Invoke-RestMethod -Uri ($base + '/api/swarm') -TimeoutSec 30
foreach ($k in $sw.agents.PSObject.Properties.Name) {
  $a = $sw.agents.$k
  $sk = if ($a.skills) { $a.skills -join ', ' } else { '(none)' }
  Write-Output ("  {0,-12} {1,-8} tasks={2,-4} {3}" -f $k, $a.status, $a.tasks, $sk)
}

Write-Output ""
Write-Output "=== follow-up ledger: bullish only, coherent outcomes ==="
$sg = Invoke-RestMethod -Uri ($base + '/api/signals') -TimeoutSec 30
Write-Output ("total={0} open={1} closed={2} wins={3} losses={4} tp={5} sl={6} trail={7} to={8} win_rate={9}" -f `
  $sg.total, $sg.open, $sg.closed, $sg.wins, $sg.losses, $sg.tp, $sg.sl, $sg.trail, $sg.timeout, $sg.win_rate)
Write-Output ""
Write-Output "  sym        kind  status  outcome  mfe     mae     bars  stop-vs-entry"
foreach ($r in $sg.recent) {
  $pl = $r.plan
  $side = ''
  if ($pl -and $pl.stop -and $r.entry) {
    $side = if ([double]$pl.stop -lt [double]$r.entry) { 'below OK' } else { 'ABOVE !!!' }
  }
  Write-Output ("  {0,-10} {1,-5} {2,-7} {3,7}  {4,6}  {5,6}  {6,4}  {7}" -f `
    $r.symbol, $r.kind, $r.status, $r.outcome, $r.mfe_pct, $r.mae_pct, $r.bars, $side)
}

Write-Output ""
Write-Output "=== dashboard-critical endpoints ==="
$paths = @('/api/status', '/api/symbols', '/api/altfins', '/api/plan/ZECUSDT', '/api/backtest_all')
foreach ($p in $paths) {
  try { $r = Invoke-WebRequest -Uri ($base + $p) -TimeoutSec 40 -UseBasicParsing
        Write-Output ("  {0,-24} 200  {1} bytes" -f $p, $r.Content.Length) }
  catch { Write-Output ("  {0,-24} ERR  {1}" -f $p, $_.Exception.Message) }
}
