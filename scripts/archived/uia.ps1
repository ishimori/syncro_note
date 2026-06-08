# uia.ps1 - drive the real Tauri (WebView2) window via UI Automation.
# WebView2 exposes its DOM to UIA, so we can find elements by name and invoke them
# from another process (Playwright cannot, since it lacks the Tauri runtime).
#
# Modes:
#   -List                 dump clickable/text element names (debug the UIA tree)
#   -Invoke "サンプル"     find element whose Name contains the substring and click it
#                          (tries InvokePattern, then a real mouse click at its center)
# Common:
#   -Process app          process name (no .exe)
#   -Maximize             maximize the window first (so all elements are laid out)
param(
    [string]$Process = "app",
    [switch]$List,
    [string]$Invoke,
    [switch]$Maximize
)

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class U {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, IntPtr e);
}
"@
[void][U]::SetProcessDPIAware()
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

$proc = Get-Process -Name $Process -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $proc) { Write-Error "process '$Process' has no main window"; exit 1 }
$h = $proc.MainWindowHandle

if ($Maximize) { [void][U]::ShowWindow($h, 3) }  # 3 = SW_MAXIMIZE
[void][U]::SetForegroundWindow($h)
Start-Sleep -Milliseconds 600

$root = [System.Windows.Automation.AutomationElement]::FromHandle($h)
$scope = [System.Windows.Automation.TreeScope]::Descendants
$all = $root.FindAll($scope, [System.Windows.Automation.Condition]::TrueCondition)

if ($List) {
    foreach ($e in $all) {
        $n = $e.Current.Name
        $ct = $e.Current.ControlType.ProgrammaticName
        if ($n) { "{0,-22} {1}" -f ($ct -replace 'ControlType\.', ''), $n }
    }
    exit 0
}

if ($Invoke) {
    foreach ($e in $all) {
        if ($e.Current.Name -like "*$Invoke*") {
            $r = $e.Current.BoundingRectangle
            "match: '$($e.Current.Name)' [$($e.Current.ControlType.ProgrammaticName)] rect=$($r.X),$($r.Y),$($r.Width),$($r.Height)"
            # Prefer InvokePattern
            $pat = $null
            if ($e.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$pat)) {
                $pat.Invoke()
                "invoked via InvokePattern"
                exit 0
            }
            # Fallback: real mouse click at element center
            $cx = [int]($r.X + $r.Width / 2)
            $cy = [int]($r.Y + $r.Height / 2)
            [void][U]::SetCursorPos($cx, $cy)
            Start-Sleep -Milliseconds 120
            [U]::mouse_event(0x0002, 0, 0, 0, [IntPtr]::Zero) # LEFTDOWN
            [U]::mouse_event(0x0004, 0, 0, 0, [IntPtr]::Zero) # LEFTUP
            "clicked at $cx,$cy (mouse fallback)"
            exit 0
        }
    }
    Write-Error "no element name contains '$Invoke'"
    exit 2
}

Write-Error "specify -List or -Invoke <name>"
exit 1
