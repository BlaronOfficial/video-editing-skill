"""Lightweight screen helpers for verification when no computer-use MCP is attached.

Screenshots let Claude *see* CapCut (e.g. confirm a generated project opened). Clicking is exposed for
simple, deterministic steps; anything interactive should go through Claude Code Desktop computer use or
Windows-MCP (see references/screen-control.md).
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from .paths import IS_MAC, IS_WINDOWS
from .util import VeditError

_PS_SHOT = r"""
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type @"
using System; using System.Runtime.InteropServices;
public class DPI { [DllImport("user32.dll")] public static extern bool SetProcessDPIAware(); }
"@
[void][DPI]::SetProcessDPIAware()
$b = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)
$bmp.Save('{out}', [System.Drawing.Imaging.ImageFormat]::Png)
Write-Output "$($b.Width)x$($b.Height)"
"""

_PS_CLICK = r"""
Add-Type @"
using System; using System.Runtime.InteropServices;
public class M {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, IntPtr e);
}
"@
[void][M]::SetProcessDPIAware()
[void][M]::SetCursorPos({x}, {y}); Start-Sleep -Milliseconds 80
for ($i = 0; $i -lt {clicks}; $i++) { [M]::mouse_event(2,0,0,0,[IntPtr]::Zero); [M]::mouse_event(4,0,0,0,[IntPtr]::Zero); Start-Sleep -Milliseconds 90 }
"""

_PS_FOREGROUND = r"""
Add-Type @"
using System; using System.Runtime.InteropServices;
public class FG { [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
                  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid); }
"@
$h = [FG]::GetForegroundWindow(); $fpid = 0; [void][FG]::GetWindowThreadProcessId($h, [ref]$fpid)
(Get-Process -Id $fpid -ErrorAction SilentlyContinue).ProcessName
"""

# Focus is only reported as successful when the target really owns the foreground afterwards:
# Windows may refuse SetForegroundWindow while the user works in another app, and keystrokes or
# clicks must never land in the user's window.
_PS_FOCUS = r"""
Add-Type @"
using System; using System.Runtime.InteropServices;
public class W { [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
                 [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
                 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
                 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid); }
"@
$procs = @(Get-Process -Name '{name}' -ErrorAction SilentlyContinue)
$p = $procs | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $p) { "missing"; exit }
[void][W]::ShowWindow($p.MainWindowHandle, 3); [void][W]::SetForegroundWindow($p.MainWindowHandle)
Start-Sleep -Milliseconds 250
$fpid = 0; [void][W]::GetWindowThreadProcessId([W]::GetForegroundWindow(), [ref]$fpid)
if ($procs.Id -contains $fpid) { "ok" } else { "blocked" }
"""


def _ps(script: str) -> str:
    proc = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise VeditError(proc.stderr.strip()[-800:])
    return proc.stdout.strip()


def screenshot(out: str | Path, *, max_width: int | None = 1600) -> Path:
    out = Path(out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if IS_WINDOWS:
        _ps(_PS_SHOT.replace("{out}", str(out)))
    elif IS_MAC:
        subprocess.run(["screencapture", "-x", str(out)], check=True)
    else:
        raise VeditError("Screenshots are supported on Windows and macOS only.")
    if max_width:
        from PIL import Image
        img = Image.open(out)
        if img.width > max_width:
            img = img.resize((max_width, round(img.height * max_width / img.width)))
            img.save(out)
    return out


def foreground_process() -> str:
    """Process name owning the foreground window (e.g. 'CapCut', 'claude', 'chrome')."""
    if not IS_WINDOWS:
        return ""
    return _ps(_PS_FOREGROUND)


def _require_foreground(expect: str | None) -> None:
    if expect and foreground_process().lower() != expect.lower():
        raise VeditError(f"Refusing to send input: the foreground window is '{foreground_process()}', not '{expect}'. "
                         f"The user may be working in another app; ask them before taking over the screen.")


def click(x: int, y: int, *, clicks: int = 1, expect: str | None = "CapCut") -> None:
    """Click at physical screen coordinates, only if `expect` owns the foreground (None = no check)."""
    if not IS_WINDOWS:
        raise VeditError("click() is Windows-only; use computer use on macOS.")
    _require_foreground(expect)
    _ps(_PS_CLICK.replace("{x}", str(int(x))).replace("{y}", str(int(y))).replace("{clicks}", str(clicks)))


def send_keys(keys: str, *, expect: str | None = "CapCut") -> None:
    """Send keystrokes (SendKeys syntax: "%{F4}" = Alt+F4) only if `expect` owns the foreground window."""
    if not IS_WINDOWS:
        raise VeditError("send_keys() is Windows-only; use computer use on macOS.")
    _require_foreground(expect)
    escaped = keys.replace("'", "''")
    _ps(f"$w = New-Object -ComObject WScript.Shell; Start-Sleep -Milliseconds 150; $w.SendKeys('{escaped}')")


def focus(process_name: str = "CapCut") -> bool:
    if not IS_WINDOWS:
        return False
    return _ps(_PS_FOCUS.replace("{name}", process_name)) == "ok"


def wait_for_window(process_name: str = "CapCut", timeout: float = 40.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if IS_WINDOWS and focus(process_name):
            return True
        time.sleep(1.0)
    return False
