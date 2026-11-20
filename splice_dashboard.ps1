# Splice the new dashboard script into dashboard.html.
#
# dashboard.html still carries the OLD inline script (no #tfbar handler, no
# feeds/TA/whale rendering) -- that is why the timeframe buttons do nothing.
# We cut the file at the Lightweight Charts CDN tag, insert the #toast div,
# then emit the new _script.js as the single inline <script>.
$ErrorActionPreference = 'Stop'

$root     = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$htmlPath = Join-Path $root 'templates\dashboard.html'
$jsPath   = Join-Path $root 'templates\_script.js'

$lines = [System.IO.File]::ReadAllLines($htmlPath)
$anchor = -1
for ($i = 0; $i -lt $lines.Count; $i++) {
  if ($lines[$i] -match 'lightweight-charts@4\.1\.3') { $anchor = $i; break }
}
if ($anchor -lt 0) { throw "anchor (lightweight-charts CDN tag) not found" }

$js = [System.IO.File]::ReadAllText($jsPath)
if (-not $js.EndsWith("`n")) { $js += "`n" }

$sb = New-Object System.Text.StringBuilder
for ($i = 0; $i -le $anchor; $i++) { [void]$sb.AppendLine($lines[$i]) }
[void]$sb.AppendLine('<div class="toast" id="toast"></div>')
[void]$sb.AppendLine('<script>')
[void]$sb.Append($js)
[void]$sb.AppendLine('</script>')
[void]$sb.AppendLine('</body>')
[void]$sb.AppendLine('</html>')

# backup once
if (-not (Test-Path "$htmlPath.oldscript.bak")) { Copy-Item $htmlPath "$htmlPath.oldscript.bak" }

[System.IO.File]::WriteAllText($htmlPath, $sb.ToString(), (New-Object System.Text.UTF8Encoding($false)))

Write-Output "spliced at source line $($anchor + 1)"
Write-Output "new file: $((Get-Item $htmlPath).Length) bytes, $((Get-Content $htmlPath | Measure-Object -Line).Lines) lines"
