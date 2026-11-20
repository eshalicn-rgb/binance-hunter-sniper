param(
  [string]$Dir = 'G:\GrokMT5Bot\binance_hunter\_shots'
)

$ErrorActionPreference = 'Stop'

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class NU {
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
  [DllImport("user32.dll")] public static extern int GetWindowLong(IntPtr h, int idx);
  [DllImport("user32.dll", SetLastError = true)] public static extern bool GetLayeredWindowAttributes(IntPtr h, out int col, out byte alpha, out int flags);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
}
"@

$ff = 'C:\Users\BSArt\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe'

function Grab([string]$out) {
  & $ff -hide_banner -loglevel error -f lavfi -i 'ddagrab=output_idx=0:framerate=5' -frames:v 1 -vf 'hwdownload,format=bgra' -y $out 2>&1 | Out-Null
  return (Test-Path $out)
}

function DiffRegion([string]$a, [string]$b, [int]$x, [int]$y, [int]$w, [int]$h) {
  Add-Type -AssemblyName System.Drawing
  $ba = New-Object System.Drawing.Bitmap($a)
  $bb = New-Object System.Drawing.Bitmap($b)
  $step = 2
  $diff = 0L; $tot = 0L; $sum = 0L
  for ($yy = $y; $yy -lt [Math]::Min($y + $h, $ba.Height); $yy += $step) {
    for ($xx = $x; $xx -lt [Math]::Min($x + $w, $ba.Width); $xx += $step) {
      $ca = $ba.GetPixel($xx, $yy); $cb = $bb.GetPixel($xx, $yy)
      $d = [Math]::Abs($ca.R - $cb.R) + [Math]::Abs($ca.G - $cb.G) + [Math]::Abs($ca.B - $cb.B)
      $sum += $d
      if ($d -gt 24) { $diff++ }
      $tot++
    }
  }
  $ba.Dispose(); $bb.Dispose()
  return [ordered]@{
    pixels     = $tot
    changed    = $diff
    pctChanged = if ($tot -gt 0) { [Math]::Round(100.0 * $diff / $tot, 2) } else { 0 }
    meanAbsD   = if ($tot -gt 0) { [Math]::Round(1.0 * $sum / $tot, 2) } else { 0 }
  }
}

$proc = Get-Process -Name Binance -ErrorAction SilentlyContinue |
  Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $proc) { '{"error":"no binance window"}'; exit 1 }
$h = $proc.MainWindowHandle

$ex = [NU]::GetWindowLong($h, -20)
$layered = (($ex -band 0x80000) -ne 0)
$layInfo = $null
if ($layered) {
  $c = 0; [byte]$al = 0; $fl = 0
  $ok = [NU]::GetLayeredWindowAttributes($h, [ref]$c, [ref]$al, [ref]$fl)
  $layInfo = [ordered]@{ ok = $ok; alpha = $al; flags = $fl; colorKey = $c }
}

$r0 = New-Object NU+RECT
[void][NU]::GetWindowRect($h, [ref]$r0)

$pA = Join-Path $Dir 'nudgeA.png'
$pB = Join-Path $Dir 'nudgeB.png'
$okA = Grab $pA

# force a repaint: resize + move + show
[void][NU]::SetWindowPos($h, [IntPtr]::Zero, 120, 80, 1280, 860, 0x0040)
Start-Sleep -Milliseconds 2500
$okB = Grab $pB

$r1 = New-Object NU+RECT
[void][NU]::GetWindowRect($h, [ref]$r1)

$d = $null
if ($okA -and $okB) {
  $d = DiffRegion $pA $pB 120 80 1280 860
}

# restore to maximized
[void][NU]::ShowWindow($h, 3)
Start-Sleep -Milliseconds 600
$r2 = New-Object NU+RECT
[void][NU]::GetWindowRect($h, [ref]$r2)

[ordered]@{
  hwnd        = $h.ToInt64()
  exStyle     = ('0x{0:X}' -f $ex)
  layered     = $layered
  layeredInfo = $layInfo
  rectBefore  = "$($r0.L),$($r0.T),$($r0.R),$($r0.B)"
  rectNudged  = "$($r1.L),$($r1.T),$($r1.R),$($r1.B)"
  rectRestored= "$($r2.L),$($r2.T),$($r2.R),$($r2.B)"
  grabbedA    = $okA
  grabbedB    = $okB
  regionDiff  = $d
} | ConvertTo-Json -Depth 4
