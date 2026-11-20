Add-Type -AssemblyName System.Drawing

if (-not ('WinEnum' -as [type])) {
  Add-Type @'
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class WinEnum {
  public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr parent, EnumProc cb, IntPtr lParam);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder s, int n);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr hWnd, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern int GetWindowLong(IntPtr hWnd, int idx);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }

  public static List<string> Rows = new List<string>();
  public static uint Want;
  public static bool Cb(IntPtr h, IntPtr l) {
    uint pid; GetWindowThreadProcessId(h, out pid);
    if (pid != Want) return true;
    var t = new StringBuilder(512); GetWindowText(h, t, 512);
    var c = new StringBuilder(256); GetClassName(h, c, 256);
    RECT r; GetWindowRect(h, out r);
    int ex = GetWindowLong(h, -20);
    int st = GetWindowLong(h, -16);
    Rows.Add(string.Format(
      "hwnd={0} vis={1} icon={2} exstyle=0x{3:X} style=0x{4:X} rect=({5},{6},{7},{8}) {9}x{10} class='{11}' title='{12}'",
      h, IsWindowVisible(h), IsIconic(h), ex, st,
      r.Left, r.Top, r.Right, r.Bottom, r.Right - r.Left, r.Bottom - r.Top,
      c.ToString(), t.ToString()));
    return true;
  }
  public static List<string> ForPid(uint pid) {
    Want = pid; Rows = new List<string>();
    EnumWindows(new EnumProc(Cb), IntPtr.Zero);
    return Rows;
  }
  public static void Fg() {
    IntPtr fg = GetForegroundWindow();
    uint pid; GetWindowThreadProcessId(fg, out pid);
    var t = new StringBuilder(512); GetWindowText(fg, t, 512);
    var c = new StringBuilder(256); GetClassName(fg, c, 256);
    Console.WriteLine("FOREGROUND hwnd=" + fg + " pid=" + pid + " class='" + c + "' title='" + t + "'");
  }
}
'@
}

[void][WinEnum]::SetProcessDPIAware()
[WinEnum]::Fg()

$pids = (Get-Process -Name Binance -ErrorAction SilentlyContinue).Id
"=== Binance processes: $($pids -join ', ') ==="

foreach ($p in $pids) {
  $pinfo = Get-Process -Id $p -ErrorAction SilentlyContinue
  $rows = [WinEnum]::ForPid([uint32]$p)
  if ($rows.Count -gt 0) {
    "--- PID $p (MainWindowHandle=$($pinfo.MainWindowHandle)) ---"
    $rows | ForEach-Object { $_ }
  }
}

"=== screen bounds ==="
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Screen]::AllScreens | ForEach-Object {
  "device=$($_.DeviceName) primary=$($_.Primary) bounds=$($_.Bounds) working=$($_.WorkingArea)"
}
