"""Llano Lights in Windows' Settings > Apps (and Control Panel > Programs), with a working Uninstall.

The app writes its entry every time it starts, because an update swaps the install without
rerunning Setup. It is per user (HKCU), so no admin prompt. Uninstall runs uninstall.ps1 from
the install, which removes everything Setup and the updater put down and asks before deleting
saved layouts.
"""
from __future__ import annotations

import datetime
import os
from pathlib import Path
from typing import Optional

KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\LlanoLights"
MANIFEST = "llano-lights.install"  # build.py lists what it shipped; Uninstall removes only those


def folder_kb(root: Path) -> int:
    total = 0
    for dirpath, _, files in os.walk(root):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total // 1024


def entry(root: Path, version: str, size_kb: int, today: Optional[datetime.date] = None) -> dict:
    """The registry values, as {name: (value, is_dword)}."""
    ps = Path(os.environ.get("SystemRoot") or r"C:\Windows") / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return {
        "DisplayName": ("Llano Lights", False),
        "DisplayVersion": (version, False),
        "Publisher": ("Llano", False),
        "DisplayIcon": (str(root / "llano-lights.ico"), False),
        "InstallLocation": (str(root), False),
        "UninstallString": (f'"{ps}" -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden '
                            f'-File "{root / "uninstall.ps1"}"', False),
        "InstallDate": ((today or datetime.date.today()).strftime("%Y%m%d"), False),
        "EstimatedSize": (size_kb, True),
        "NoModify": (1, True),
        "NoRepair": (1, True),
    }


def register(root: Path, version: str, reg=None) -> bool:
    """Write the entry; False (and nothing written) off Windows or without uninstall.ps1 and the manifest."""
    if not ((root / "uninstall.ps1").is_file() and (root / MANIFEST).is_file()):
        return False
    if reg is None:
        try:
            import winreg as reg
        except ImportError:
            return False
    values = entry(root, version, folder_kb(root))
    with reg.CreateKeyEx(reg.HKEY_CURRENT_USER, KEY, 0, reg.KEY_ALL_ACCESS) as k:
        try:  # keep the first install date across updates
            values["InstallDate"] = (str(reg.QueryValueEx(k, "InstallDate")[0]), False)
        except OSError:
            pass
        for name, (value, dword) in values.items():
            reg.SetValueEx(k, name, 0, reg.REG_DWORD if dword else reg.REG_SZ, value)
    return True


# The window's "not running" screen (sw.js, Llano BL #12377) has a Start Llano Lights button: a
# llano-lights: link that Windows hands to this install's own Python, so the engine comes back with
# no internet and no hunting for the icon. Per user (HKCU), rewritten on every start like the entry
# above (an update keeps the folder, so the command stays right); Uninstall removes it.
LINK_KEY = r"Software\Classes\llano-lights"


def start_link_command(root: Path) -> str:
    return f'"{root / "runtime" / "pythonw.exe"}" "{root / "app" / "gigbar_app.py"}"'


def register_start_link(root: Path, reg=None) -> bool:
    """Write the llano-lights: link; False (and nothing written) off Windows or for a copy that isn't installed."""
    if not ((root / "runtime" / "pythonw.exe").is_file() and (root / "app" / "gigbar_app.py").is_file()):
        return False
    if reg is None:
        try:
            import winreg as reg
        except ImportError:
            return False
    with reg.CreateKeyEx(reg.HKEY_CURRENT_USER, LINK_KEY, 0, reg.KEY_ALL_ACCESS) as k:
        reg.SetValueEx(k, "", 0, reg.REG_SZ, "URL:Llano Lights")
        reg.SetValueEx(k, "URL Protocol", 0, reg.REG_SZ, "")
    with reg.CreateKeyEx(reg.HKEY_CURRENT_USER, LINK_KEY + r"\DefaultIcon", 0, reg.KEY_ALL_ACCESS) as k:
        reg.SetValueEx(k, "", 0, reg.REG_SZ, str(root / "llano-lights.ico"))
    with reg.CreateKeyEx(reg.HKEY_CURRENT_USER, LINK_KEY + r"\shell\open\command", 0, reg.KEY_ALL_ACCESS) as k:
        reg.SetValueEx(k, "", 0, reg.REG_SZ, start_link_command(root))
    return True
