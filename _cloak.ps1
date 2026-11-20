$ErrorActionPreference = 'Stop'

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public class DwmDiag {
  [DllImport("dwmapi.dll", PreserveSig = true)]
  public static extern int DwmGetWindowAttribute(IntPtr hwnd, int dwAttribute, out int pvAttribute, int cbAttribute);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern IntPtr GetWindow(IntPtr hWnd, uint uCmd);
  [DllImport("user32.dll")] public static extern int GetWindowLong(IntPtr hWnd, int nIndex);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr after, int x, int y, int cx, int cy, uint flags);
  [DllImport("user32.dll")] public static extern int GetWindowTextLength(IntPtr hWnd);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder s, int max);
}
"@

$proc = Get-Process -Name Binance -ErrorAction SilentlyContinue |
  Where-Object { $_.MainWindowHandle -ne 0 } |
  Select-Object -First 1

if (-not $proc) { '{"error":"no binance window"}'; exit 1 }

$h = $proc.MainWindowHandle
$cloaked = 0
$rcCloak = [DwmDiag]::DwmGetWindowAttribute($h, 14, [ref]$cloaked, 4)

$sb = New-Object System.Text.StringBuilder 512
[void][DwmDiag]::GetWindowText($h, $sb, 512)

$fg = [DwmDiag]::GetForegroundWindow()

# count cloaked among all top-level binance windows
$pw = Get-Process -Name Binance -ErrorAction SilentlyContinue
$rows = @()
foreach ($p in $pw) {
  foreach ($w in $p.MainWindowHandle) { }
}
$allWin = @()
Add-Type -TypeDefinition @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public class EnumW {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc f, IntPtr l);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int m);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetClassName(IntPtr h, StringBuilder s, int m);
  [DllImport("dwmapi.dll")] public static extern int DwmGetWindowAttribute(IntPtr h, int a, out int v, int s);
  public static List<string> Go(uint[] pids) {
    var outp = new List<string>();
    EnumWindows((h, l) => {
      uint pid; GetWindowThreadProcessId(h, out pid);
      if (Array.IndexOf(pids, pid) < 0) return true;
      var t = new StringBuilder(300); GetWindowText(h, t, 300);
      var c = new StringBuilder(300); GetClassName(h, c, 300);
      int ck = 0; int rc = DwmGetWindowAttribute(h, 14, out ck, 4);
      outp.Add(h.ToInt64() + "|" + pid + "|vis=" + IsWindowVisible(h) + "|cloak=" + ck + "|rc=" + rc + "|cls=" + c + "|title=" + t);
      return true;
    }, IntPtr.Zero);
    return outp;
  }
}
"@

$pids = [uint32[]]($pw | ForEach-Object { [uint32]$_.Id })
$all = [EnumW]::Go($pids)

[ordered]@{
  hwnd         = $h.ToInt64()
  pid          = $proc.Id
  title        = $sb.ToString()
  visible      = [DwmDiag]::IsWindowVisible($h)
  iconic       = [DwmDiag]::IsIconic($h)
  exStyle      = ('0x{0:X}' -f [DwmDiag]::GetWindowLong($h, -20))
  isForeground = ($fg -eq $h)
  cloakAttrRc  = $rcCloak
  cloaked      = $cloaked
  totalWindows = $all.Count
  windows      = $all
} | ConvertTo-Json -Depth 4
