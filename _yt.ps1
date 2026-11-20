param(
  [string]$Dir = 'G:\GrokMT5Bot\binance_hunter\_shots',
  [int]$X = 120,
  [int]$Y = 80,
  [int]$W = 1280,
  [int]$H = 860,
  [int]$WaitMs = 3000
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

$ff = 'C:\Users\BSArt\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe'
if (-not (Test-Path $ff)) { $ff = (Get-Command ffmpeg -ErrorAction SilentlyContinue).Source }
if (-not $ff) { '{"error":"no ffmpeg"}'; exit 1 }
if (-not (Test-Path $Dir)) { New-Item -ItemType Directory -Path $Dir -Force | Out-Null }

if (-not ('YTW' -as [type])) {
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class YTW {
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
  public struct RECT { public int Left, Top, Right, Bottom; }
}
"@
}

$p = Get-Process -Name Binance -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $p) { '{"error":"no binance window"}'; exit 1 }
$hwnd = $p.MainWindowHandle

function Grab([string]$out) {
  $filter = "ddagrab=output_idx=0:framerate=5"
  & $ff -hide_banner -loglevel error -f lavfi -i $filter -frames:v 1 -vf 'hwdownload,format=bgra' -y $out 2>$null
  return (Test-Path $out)
}

function ScanBmp($bmp, [int]$rx, [int]$ry, [int]$rw, [int]$rh) {
  $yellow = 0; $bright = 0; $n = 0
  $sr = 0L; $sg = 0L; $sb = 0L
  $x2 = [Math]::Min($bmp.Width - 1, $rx + $rw - 1)
  $y2 = [Math]::Min($bmp.Height - 1, $ry + $rh - 1)
  for ($y = [Math]::Max(0, $ry); $y -le $y2; $y += 2) {
    for ($x = [Math]::Max(0, $rx); $x -le $x2; $x += 2) {
      $c = $bmp.GetPixel($x, $y)
      $r = $c.R; $g = $c.G; $b = $c.B
      $sr += $r; $sg += $g; $sb += $b; $n++
      if ($r -ge 195 -and $g -ge 140 -and $b -le 95 -and ($r - $b) -ge 120) { $yellow++ }
      if ($r -ge 200 -and $g -ge 200 -and $b -ge 200) { $bright++ }
    }
  }
  $o = [ordered]@{ samples = $n; yellow = $yellow; bright = $bright }
  if ($n -gt 0) {
    $o.meanR = [int]($sr / $n); $o.meanG = [int]($sg / $n); $o.meanB = [int]($sb / $n)
  }
  return $o
}

$rect = New-Object YTW+RECT
[YTW]::GetWindowRect($hwnd, [ref]$rect) | Out-Null

$aPath = Join-Path $Dir 'yt_before.png'
$bPath = Join-Path $Dir 'yt_after.png'
$cPath = Join-Path $Dir 'yt_crop.png'
$okA = Grab $aPath

[YTW]::SetWindowPos($hwnd, [IntPtr]::Zero, $X, $Y, $W, $H, 0x0040) | Out-Null
[YTW]::BringWindowToTop($hwnd) | Out-Null
[YTW]::SetForegroundWindow($hwnd) | Out-Null
Start-Sleep -Milliseconds $WaitMs
$okB = Grab $bPath

$res = [ordered]@{
  hwnd        = [int64]$hwnd
  pid         = $p.Id
  rectBefore  = "$($rect.Left),$($rect.Top),$($rect.Right),$($rect.Bottom)"
  grabbedA    = $okA
  grabbedB    = $okB
  region      = "$X,$Y,$W,$H"
  waitMs      = $WaitMs
}

if ($okB) {
  $bmp = New-Object System.Drawing.Bitmap($bPath)
  $res.afterInRegion = ScanBmp $bmp $X $Y $W $H
  $ctrlX = [Math]::Min($bmp.Width - 400, 1900)
  $res.afterControl = ScanBmp $bmp $ctrlX 1000 400 300
  # crop the app region for a cheap visual read
  $crop = New-Object System.Drawing.Bitmap($W, $H)
  $g = [System.Drawing.Graphics]::FromImage($crop)
  $g.DrawImage($bmp, (New-Object System.Drawing.Rectangle(0, 0, $W, $H)), (New-Object System.Drawing.Rectangle($X, $Y, $W, $H)), [System.Drawing.GraphicsUnit]::Pixel)
  $g.Dispose()
  $crop.Save($cPath, [System.Drawing.Imaging.ImageFormat]::Png)
  $crop.Dispose()
  $res.crop = $cPath
  $bmp.Dispose()
}

if ($okA) {
  $bmpA = New-Object System.Drawing.Bitmap($aPath)
  $res.beforeInRegion = ScanBmp $bmpA $X $Y $W $H
  $bmpA.Dispose()
}

[YTW]::ShowWindow($hwnd, 3) | Out-Null
$rect2 = New-Object YTW+RECT
[YTW]::GetWindowRect($hwnd, [ref]$rect2) | Out-Null
$res.rectRestored = "$($rect2.Left),$($rect2.Top),$($rect2.Right),$($rect2.Bottom)"

[pscustomobject]$res | ConvertTo-Json -Compress -Depth 6
