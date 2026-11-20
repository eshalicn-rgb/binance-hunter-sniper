param(
  [int]$Idx = 0,
  [string]$Out = 'G:\GrokMT5Bot\binance_hunter\_shots\dd.png',
  [int]$Fps = 5,
  [switch]$Stats
)

$ff = 'C:\Users\BSArt\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe'
if (-not (Test-Path $ff)) { $ff = (Get-Command ffmpeg -ErrorAction SilentlyContinue).Source }
if (-not $ff) { Write-Output '{"error":"no ffmpeg"}'; exit 1 }

$dir = Split-Path -Parent $Out
if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }

$filter = "ddagrab=output_idx=${Idx}:framerate=$Fps"
& $ff -hide_banner -loglevel error -f lavfi -i $filter -frames:v 1 -vf 'hwdownload,format=bgra' -y $Out 2>&1 | ForEach-Object { "ffmpeg: $_" }
$code = $LASTEXITCODE

$res = [ordered]@{ idx = $Idx; out = $Out; exit = $code; exists = (Test-Path $Out) }

if ($res.exists) {
  Add-Type -AssemblyName System.Drawing
  $f = Get-Item $Out
  $res.bytes = $f.Length
  if ($Stats) {
    $bmp = New-Object System.Drawing.Bitmap($Out)
    $res.w = $bmp.Width; $res.h = $bmp.Height
    $sr = 0L; $sg = 0L; $sb = 0L; $n = 0L
    $sx = [Math]::Max(1, [int]($bmp.Width / 160))
    $sy = [Math]::Max(1, [int]($bmp.Height / 90))
    for ($y = 0; $y -lt $bmp.Height; $y += $sy) {
      for ($x = 0; $x -lt $bmp.Width; $x += $sx) {
        $c = $bmp.GetPixel($x, $y)
        $sr += $c.R; $sg += $c.G; $sb += $c.B; $n++
      }
    }
    $bmp.Dispose()
    if ($n -gt 0) {
      $res.meanR = [int]($sr / $n); $res.meanG = [int]($sg / $n); $res.meanB = [int]($sb / $n)
      $res.meanLum = [int](($sr + $sg + $sb) / (3 * $n))
      $res.samples = $n
    }
  }
}

[pscustomobject]$res | ConvertTo-Json -Compress
