"""Process incarnation checks: PID reuse must not look like the original owner."""

import os
from pathlib import Path


def process_identity(pid):
    """Return a creation token, 'missing', or 'unknown' (never assume unknown is dead)."""
    if type(pid) is not int or pid <= 0:
        return "missing"
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return "missing" if ctypes.get_last_error() == 87 else "unknown"
        try:
            values = [wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle, *(ctypes.byref(v) for v in values)):
                return "unknown"
            return str((values[0].dwHighDateTime << 32) | values[0].dwLowDateTime)
        finally:
            kernel.CloseHandle(handle)
    try:
        # Linux starttime is stable for this PID incarnation; closing ')' may occur in comm.
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except FileNotFoundError:
        return "missing"
    except (OSError, IndexError):
        return "unknown"
