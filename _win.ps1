param(
  [Parameter(Mandatory=$true)]
  [ValidateSet('focus','rect','shot','printwin','shotvirtual','click','dblclick','move','type','key','drag')]
  [string]$Action,

  [string]$TitleMatch = 'Binance',
  [int]$X = 0,
  [int]$Y = 0,
  [int]$X2 = 0,
  [int]$Y2 = 0,
  [string]$Text = '',
  [string]$Out = 'G:\GrokMT5Bot\binance_hunter\_shots\app.png',
  [int]$DelayMs = 500
)

$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

if (-not ('Win32Win' -as [type])) {
  Add-Type @'
using System;
using System.Runtime.InteropServices;
public class Win32Win {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr after, int X, int Y, int cx, int cy, uint flags);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdc, uint flags);
  [DllImport("gdi32.dll")] public static extern IntPtr CreateCompatibleDC(IntPtr hdc);
  [DllImport("gdi32.dll")] public static extern IntPtr CreateCompatibleBitmap(IntPtr hdc, int w, int h);
  [DllImport("gdi32.dll")] public static extern IntPtr SelectObject(IntPtr hdc, IntPtr obj);
  [DllImport("gdi32.dll")] public static extern bool DeleteDC(IntPtr hdc);
  [DllImport("gdi32.dll")] public static extern bool DeleteObject(IntPtr obj);
  [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, IntPtr dwExtraInfo);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  public const uint LEFTDOWN = 0x0002, LEFTUP = 0x0004, MOVE = 0x0001;
  public static readonly IntPtr TOPMOST = new IntPtr(-1);
  public static readonly IntPtr NOTOPMOST = new IntPtr(-2);
  public const uint SWP_NOSIZE = 0x0001, SWP_NOMOVE = 0x0002, SWP_SHOWWINDOW = 0x0040;
}
'@
}

[void][Win32Win]::SetProcessDPIAware()

$script:Proc = $null

function Find-Win {
  $p = Get-Process -Name Binance -ErrorAction SilentlyContinue |
       Where-Object { $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -like "*$TitleMatch*" } |
       Select-Object -First 1
  if (-not $p) {
    $p = Get-Process -Name Binance -ErrorAction SilentlyContinue |
         Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
  }
  return $p
}

function Get-RectOf($hh) {
  $r = New-Object Win32Win+RECT
  [void][Win32Win]::GetWindowRect($hh, [ref]$r)
  return $r
}

function Raise-Win($hh) {
  if ([Win32Win]::IsIconic($hh)) {
    [void][Win32Win]::ShowWindow($hh, 6)
    Start-Sleep -Milliseconds 200
  }
  [void][Win32Win]::ShowWindow($hh, 9)
  Start-Sleep -Milliseconds 220
  [void][Win32Win]::SetWindowPos($hh, [Win32Win]::TOPMOST, 0, 0, 0, 0,
    ([Win32Win]::SWP_NOMOVE -bor [Win32Win]::SWP_NOSIZE -bor [Win32Win]::SWP_SHOWWINDOW))
  Start-Sleep -Milliseconds 120
  [void][Win32Win]::BringWindowToTop($hh)
  [void][Win32Win]::SetForegroundWindow($hh)
  Start-Sleep -Milliseconds 200
  [void][Win32Win]::SetWindowPos($hh, [Win32Win]::NOTOPMOST, 0, 0, 0, 0,
    ([Win32Win]::SWP_NOMOVE -bor [Win32Win]::SWP_NOSIZE -bor [Win32Win]::SWP_SHOWWINDOW))
  [void][Win32Win]::SetForegroundWindow($hh)
  Start-Sleep -Milliseconds 250

  if ([Win32Win]::GetForegroundWindow() -ne $hh) {
    # ALT tap grants our process foreground-change rights, then retry
    [System.Windows.Forms.SendKeys]::SendWait('%')
    Start-Sleep -Milliseconds 150
    [void][Win32Win]::BringWindowToTop($hh)
    [void][Win32Win]::SetForegroundWindow($hh)
    Start-Sleep -Milliseconds 300
  }
  return ([Win32Win]::GetForegroundWindow() -eq $hh)
}

$proc = Find-Win
if (-not $proc) { Write-Output '{"error":"no Binance window"}'; exit 1 }
$h = $proc.MainWindowHandle

switch ($Action) {
  'rect' {
    $r = Get-RectOf $h
    [pscustomobject]@{
      left = $r.Left; top = $r.Top
      width = ($r.Right - $r.Left); height = ($r.Bottom - $r.Top)
    } | ConvertTo-Json -Compress
  }

  'focus' {
    $ok = Raise-Win $h
    [pscustomobject]@{ focused = $ok; handle = $h; pid = $proc.Id } | ConvertTo-Json -Compress
  }

  'shot' {
    $ok = Raise-Win $h
    Start-Sleep -Milliseconds $DelayMs
    $r = Get-RectOf $h
    $w = $r.Right - $r.Left
    $ht = $r.Bottom - $r.Top
    $dir = Split-Path -Parent $Out
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $bmp = New-Object System.Drawing.Bitmap($w, $ht)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($r.Left, $r.Top, 0, 0, $bmp.Size)
    $bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $bmp.Dispose()
    $fg = ([Win32Win]::GetForegroundWindow() -eq $h)
    [pscustomobject]@{
      saved = $Out; foreground = $fg
      left = $r.Left; top = $r.Top; width = $w; height = $ht
    } | ConvertTo-Json -Compress
  }

  'printwin' {
    $ok = Raise-Win $h
    Start-Sleep -Milliseconds $DelayMs
    $r = Get-RectOf $h
    $w = $r.Right - $r.Left
    $ht = $r.Bottom - $r.Top
    $dir = Split-Path -Parent $Out
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $bmp = New-Object System.Drawing.Bitmap($w, $ht)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $hdc = $g.GetHdc()
    # PW_RENDERFULLCONTENT = 2 -> required for Chromium/Electron surfaces
    $pw = [Win32Win]::PrintWindow($h, $hdc, 2)
    $g.ReleaseHdc($hdc)
    $bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $bmp.Dispose()
    [pscustomobject]@{
      saved = $Out; printwindow = $pw; foreground = $ok
      width = $w; height = $ht
    } | ConvertTo-Json -Compress
  }

  'shotvirtual' {
    Add-Type -AssemblyName System.Windows.Forms
    $vs = [System.Windows.Forms.SystemInformation]::VirtualScreen
    $dir = Split-Path -Parent $Out
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $bmp = New-Object System.Drawing.Bitmap($vs.Width, $vs.Height)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($vs.Left, $vs.Top, 0, 0, $bmp.Size)
    $bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $bmp.Dispose()
    [pscustomobject]@{
      saved = $Out; left = $vs.Left; top = $vs.Top
      width = $vs.Width; height = $vs.Height
    } | ConvertTo-Json -Compress
  }

  'move' {
    [void][Win32Win]::SetCursorPos($X, $Y)
    Start-Sleep -Milliseconds 120
    [pscustomobject]@{ moved = "$X,$Y" } | ConvertTo-Json -Compress
  }

  'click' {
    $ok = Raise-Win $h
    [void][Win32Win]::SetCursorPos($X, $Y)
    Start-Sleep -Milliseconds 160
    [Win32Win]::mouse_event([Win32Win]::LEFTDOWN, 0, 0, 0, [IntPtr]::Zero)
    Start-Sleep -Milliseconds 70
    [Win32Win]::mouse_event([Win32Win]::LEFTUP, 0, 0, 0, [IntPtr]::Zero)
    Start-Sleep -Milliseconds 350
    [pscustomobject]@{ clicked = "$X,$Y"; foreground = $ok } | ConvertTo-Json -Compress
  }

  'dblclick' {
    $ok = Raise-Win $h
    [void][Win32Win]::SetCursorPos($X, $Y)
    Start-Sleep -Milliseconds 160
    foreach ($i in 1..2) {
      [Win32Win]::mouse_event([Win32Win]::LEFTDOWN, 0, 0, 0, [IntPtr]::Zero)
      Start-Sleep -Milliseconds 40
      [Win32Win]::mouse_event([Win32Win]::LEFTUP, 0, 0, 0, [IntPtr]::Zero)
      Start-Sleep -Milliseconds 70
    }
    Start-Sleep -Milliseconds 350
    [pscustomobject]@{ dblclicked = "$X,$Y"; foreground = $ok } | ConvertTo-Json -Compress
  }

  'drag' {
    $ok = Raise-Win $h
    [void][Win32Win]::SetCursorPos($X, $Y)
    Start-Sleep -Milliseconds 160
    [Win32Win]::mouse_event([Win32Win]::LEFTDOWN, 0, 0, 0, [IntPtr]::Zero)
    Start-Sleep -Milliseconds 130
    $steps = 14
    for ($i = 1; $i -le $steps; $i++) {
      $nx = [int]($X + ($X2 - $X) * $i / $steps)
      $ny = [int]($Y + ($Y2 - $Y) * $i / $steps)
      [void][Win32Win]::SetCursorPos($nx, $ny)
      Start-Sleep -Milliseconds 25
    }
    [Win32Win]::mouse_event([Win32Win]::LEFTUP, 0, 0, 0, [IntPtr]::Zero)
    Start-Sleep -Milliseconds 250
    [pscustomobject]@{ dragged = "$X,$Y -> $X2,$Y2"; foreground = $ok } | ConvertTo-Json -Compress
  }

  'type' {
    $ok = Raise-Win $h
    Start-Sleep -Milliseconds 150
    $esc = $Text -replace '([+^%~()\[\]{}])', '{$1}'
    [System.Windows.Forms.SendKeys]::SendWait($esc)
    Start-Sleep -Milliseconds 300
    [pscustomobject]@{ typed = "[$($Text.Length) chars]"; foreground = $ok } | ConvertTo-Json -Compress
  }

  'key' {
    $ok = Raise-Win $h
    Start-Sleep -Milliseconds 150
    [System.Windows.Forms.SendKeys]::SendWait($Text)
    Start-Sleep -Milliseconds 300
    [pscustomobject]@{ key = $Text; foreground = $ok } | ConvertTo-Json -Compress
  }
}
