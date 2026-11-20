# Verify every getElementById target used by _script.js exists in dashboard.html.
$root = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$html = [System.IO.File]::ReadAllText((Join-Path $root 'templates\dashboard.html'))
$js   = [System.IO.File]::ReadAllText((Join-Path $root 'templates\_script.js'))

$ids = [System.Collections.Generic.HashSet[string]]::new()
foreach ($m in [regex]::Matches($js, "\`$\('([A-Za-z0-9_]+)'\)")) { [void]$ids.Add($m.Groups[1].Value) }
foreach ($m in [regex]::Matches($js, "\`$\(""([A-Za-z0-9_]+)""\)")) { [void]$ids.Add($m.Groups[1].Value) }

$present = New-Object System.Collections.Generic.List[string]
$missing = New-Object System.Collections.Generic.List[string]
foreach ($id in ($ids | Sort-Object)) {
  if ($html -match ('id="' + [regex]::Escape($id) + '"')) { $present.Add($id) } else { $missing.Add($id) }
}

Write-Output "IDs referenced by script: $($ids.Count)"
Write-Output "  present: $($present.Count)"
Write-Output "  MISSING: $($missing.Count)"
if ($missing.Count) { Write-Output ("  -> " + ($missing -join ', ')) }

# Panel section ids used for jump()
Write-Output ""
Write-Output "=== panel anchors ==="
foreach ($p in @('p_market','p_dec','p_pos','p_risk','p_news','p_feeds','p_whale','p_surge','p_catch','p_push','p_ta','p_prepump','p_moving')) {
  Write-Output ("  {0,-10} {1}" -f $p, ($html -match ('id="' + $p + '"')))
}

# CSS hooks the layout fix depends on
Write-Output ""
Write-Output "=== css/struct hooks ==="
Write-Output ("  .grid rule        : " + [bool]([regex]::Match($html,'\.grid\{[^}]*\}').Success))
Write-Output ("  grid align-items  : " + ([regex]::Match($html,'\.grid\{[^}]*\}').Value))
Write-Output ("  .panel.spot rule  : " + ([regex]::Match($html,'\.panel\.spot\{[^}]*\}').Value))
Write-Output ("  .chartbox rule    : " + ([regex]::Match($html,'\.chartbox\{[^}]*\}').Value))
Write-Output ("  toast css    : " + [bool]([regex]::Match($html,'\.toast\{').Success))
Write-Output ("  toast div    : " + ($html -match 'id="toast"'))
Write-Output ("  clk div      : " + ($html -match 'id="clk"'))

# Jinja safety: dashboard.html goes through render_template, so a literal "{{",
# "{%" or "{#" anywhere in CSS/JS aborts the whole page with HTTP 500. A CSS
# media query written as "{#gatesTop{" is enough to take the dashboard down --
# exactly what happened once. Guard it here instead of finding out in the browser.
Write-Output ""
Write-Output "=== jinja opcodes (all must be 0) ==="
$jb1 = ([regex]::Matches($html, '\{\{')).Count
$jb2 = ([regex]::Matches($html, '\{%')).Count
$jb3 = ([regex]::Matches($html, '\{#')).Count
Write-Output ("  {{{{       : " + $jb1)
Write-Output ("  brace-pct  : " + $jb2)
Write-Output ("  brace-hash : " + $jb3)
$jinjaBad = (($jb1 + $jb2 + $jb3) -gt 0)
if ($jinjaBad) {
  Write-Output "  -> FAIL: render_template will 500. Put a space after the '{'."
  foreach ($m in [regex]::Matches($html, '.{0,40}(\{\{|\{%|\{#).{0,40}')) {
    Write-Output ("     " + $m.Value.Trim())
  }
}

Write-Output ""
if ($missing.Count -gt 0 -or $jinjaBad) {
  Write-Output "BUILD GATE: FAIL"
  exit 1
} else {
  Write-Output "BUILD GATE: PASS"
}
