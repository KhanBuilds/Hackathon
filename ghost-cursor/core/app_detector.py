import platform
import psutil
from utils.logger import log


def get_active_app() -> str:
    """Returns lowercase process name of the focused window."""
    system = platform.system()

    try:
        if system == "Windows":
            import win32gui
            import win32process
            hwnd = win32gui.GetForegroundWindow()
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            name = psutil.Process(pid).name().lower()
            log(f"Active app (Windows): {name}")
            return name

        elif system == "Darwin":
            from AppKit import NSWorkspace
            name = NSWorkspace.sharedWorkspace().frontmostApplication().localizedName().lower()
            log(f"Active app (macOS): {name}")
            return name

        elif system == "Linux":
            import subprocess
            pid = subprocess.check_output(
                ["xdotool", "getactivewindow", "getwindowpid"]
            ).decode().strip()
            name = subprocess.check_output(
                ["ps", "-p", pid, "-o", "comm="]
            ).decode().strip().lower()
            log(f"Active app (Linux): {name}")
            return name

    except Exception as e:
        log(f"App detection failed: {e}", level="WARNING")

    return "unknown"
