# click.ps1 - click at a WINDOW-RELATIVE pixel coordinate in a process's main window.
# X,Y are pixels measured on a shot-window.ps1 capture. Both scripts are DPI-aware and use
# physical pixels, so coordinates match regardless of the display scale factor (no DPI math).
param(
    [string]$Process = "app",
    [Parameter(Mandatory = $true)][int]$X,
    [Parameter(Mandatory = $true)][int]$Y
)
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class C {
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr value);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, IntPtr e);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, IntPtr pid);
    [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool attach);
    public static void Force(IntPtr h) {
        uint fg = GetWindowThreadProcessId(GetForegroundWindow(), IntPtr.Zero);
        uint me = GetCurrentThreadId();
        AttachThreadInput(fg, me, true);
        BringWindowToTop(h); SetForegroundWindow(h);
        AttachThreadInput(fg, me, false);
    }
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
}
"@
# Per-Monitor-Aware V2(-4): どのモニタでも GetWindowRect/SetCursorPos を真の物理ピクセルで揃える。
try { [void][C]::SetProcessDpiAwarenessContext([IntPtr](-4)) } catch { [void][C]::SetProcessDPIAware() }
$proc = Get-Process -Name $Process -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $proc) { Write-Error "process '$Process' has no main window"; exit 1 }
$h = $proc.MainWindowHandle
[C]::Force($h)
Start-Sleep -Milliseconds 400
$r = New-Object C+RECT
[void][C]::GetWindowRect($h, [ref]$r)
$sx = $r.Left + $X
$sy = $r.Top + $Y
[void][C]::SetCursorPos($sx, $sy)
Start-Sleep -Milliseconds 150
[C]::mouse_event(0x0002, 0, 0, 0, [IntPtr]::Zero) # LEFTDOWN
Start-Sleep -Milliseconds 70                       # WebView2 はdown/up間に少し間が要る
[C]::mouse_event(0x0004, 0, 0, 0, [IntPtr]::Zero) # LEFTUP
Write-Output ("clicked window-rel ($X,$Y) -> screen ($sx,$sy); win origin ($($r.Left),$($r.Top))")
