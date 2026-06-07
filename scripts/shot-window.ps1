# shot-window.ps1 - bring a process main window to front and capture its screen rect to PNG.
# Uses real screen-pixel copy (CopyFromScreen), NOT PrintWindow, so WebView2 GPU-composited
# content is captured correctly (PrintWindow returns blank for WebView2).
# Used by DD-011 Phase 3-C for real-window visual checks (Playwright cannot run Tauri runtime).
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/shot-window.ps1 -Process app -Out c:/tmp/x.png
#   (-Process is the process name without .exe; -Out is the destination PNG path)
param(
    [string]$Process = "app",
    [Parameter(Mandatory = $true)][string]$Out
)

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32 {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
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
# DPI-aware にして物理ピクセルで矩形/キャプチャ/カーソルを揃える（click 側スクリプトと座標系を一致させる）
[void][Win32]::SetProcessDPIAware()

$proc = Get-Process -Name $Process -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $proc) {
    Write-Error "process '$Process' has no main window (is it running?)"
    exit 1
}
$h = $proc.MainWindowHandle

# robustly bring to foreground (AttachThreadInput beats the foreground lock)
[Win32]::Force($h)
Start-Sleep -Milliseconds 600

$r = New-Object Win32+RECT
[void][Win32]::GetWindowRect($h, [ref]$r)
$w = $r.Right - $r.Left
$ht = $r.Bottom - $r.Top
if ($w -le 0 -or $ht -le 0) {
    Write-Error ("invalid window rect: " + $w + "x" + $ht)
    exit 1
}

Add-Type -AssemblyName System.Drawing
$bmp = New-Object System.Drawing.Bitmap $w, $ht
$g = [System.Drawing.Graphics]::FromImage($bmp)
$sz = New-Object System.Drawing.Size($w, $ht)
$g.CopyFromScreen($r.Left, $r.Top, 0, 0, $sz)
$dir = Split-Path -Parent $Out
if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose()
$bmp.Dispose()
Write-Output ("saved " + $Out + " (" + $w + "x" + $ht + ")")
