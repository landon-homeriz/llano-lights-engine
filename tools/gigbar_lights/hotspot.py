"""The laptop's own Wi-Fi network for local mode (1.8.0): "Llano Lights", with a password.

Windows Mobile Hotspot, started through WinRT (NetworkOperatorTetheringManager). It needs a
network connection to hang the hotspot off; Windows is known to refuse when there is no
internet at all, so this tries the internet connection first and then every other
connection, and says plainly when Windows won't. The fallbacks then are a phone's own
hotspot or a small travel router: the laptop and the phone join that, and local mode works
the same. NOT YET PROVEN on his laptop: written against Microsoft's documented API and
tested here only for its refusals.

The password is made once and kept in ~/.gigbar_lights/hotspot.json, so a phone that joined
once rejoins on its own.

When Windows refuses (1.20.0, his ask 2026-11-13): the reason says so plainly, naming the missing
internet when that is why, and the app opens Windows' own Mobile hotspot screen (open_settings).
A hotspot he turns on there is noticed (status), with the name and password Windows gave it, so
the window shows the same join code either way.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Optional

SSID = "Llano Lights"
TIMEOUT_S = 25.0   # Windows can sit on a hotspot request with no answer (BL #12109): give up plainly
SETTINGS_URI = "ms-settings:network-mobilehotspot"   # Windows' own Mobile hotspot screen
NO_INTERNET = "The laptop has no internet connection, and Windows usually won't start a hotspot without one. "
OFF = {"on": False, "ssid": "", "password": ""}


def _file(root: Optional[Path]) -> Path:
    return (Path(root) if root else Path.home() / ".gigbar_lights") / "hotspot.json"


def password(root: Optional[Path] = None) -> str:
    p = _file(root)
    try:
        pw = json.loads(p.read_text(encoding="utf-8")).get("password")
        if isinstance(pw, str) and 8 <= len(pw) <= 63:
            return pw
    except (OSError, ValueError, AttributeError):  # ok: none yet, make one
        pass
    pw = "-".join(secrets.token_hex(2) for _ in range(3))   # 14 characters, easy to type
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"password": pw}), encoding="utf-8")
    return pw


def wifi_qr_text(ssid: str, pw: str) -> str:
    """The text a phone camera reads as "join this Wi-Fi"."""
    esc = lambda t: "".join("\\" + c if c in '\\;,:"' else c for c in t)  # noqa: E731
    return f"WIFI:T:WPA;S:{esc(ssid)};P:{esc(pw)};;"


async def _start(pw: str) -> str:
    from winrt.windows.networking.connectivity import NetworkInformation  # noqa: PLC0415
    from winrt.windows.networking.networkoperators import (  # noqa: PLC0415
        NetworkOperatorTetheringManager, TetheringOperationStatus)
    internet = NetworkInformation.get_internet_connection_profile()
    profiles = [internet] + list(NetworkInformation.get_connection_profiles())
    why = NO_INTERNET if internet is None else ""
    last = "Windows found no network connection to start a hotspot from"
    for prof in profiles:
        if prof is None:
            continue
        try:
            mgr = NetworkOperatorTetheringManager.create_from_connection_profile(prof)
            cfg = mgr.get_current_access_point_configuration()
            cfg.ssid, cfg.passphrase = SSID, pw
            await mgr.configure_access_point_async(cfg)
            res = await mgr.start_tethering_async()
        except Exception as e:  # noqa: BLE001 -- a profile that can't host one: try the next
            last = f"Windows refused: {e}"
            continue
        if res.status == TetheringOperationStatus.SUCCESS:
            return ""
        last = f"Windows refused ({res.additional_error_message or res.status})"
    return why + last


async def _status() -> dict:
    from winrt.windows.networking.connectivity import NetworkInformation  # noqa: PLC0415
    from winrt.windows.networking.networkoperators import (  # noqa: PLC0415
        NetworkOperatorTetheringManager, TetheringOperationalState)
    profiles = [NetworkInformation.get_internet_connection_profile()]
    profiles += list(NetworkInformation.get_connection_profiles())
    for prof in profiles:
        if prof is None:
            continue
        try:
            mgr = NetworkOperatorTetheringManager.create_from_connection_profile(prof)
            if mgr.tethering_operational_state != TetheringOperationalState.ON:
                continue
            cfg = mgr.get_current_access_point_configuration()
            return {"on": True, "ssid": str(cfg.ssid or ""), "password": str(cfg.passphrase or "")}
        except Exception:  # noqa: BLE001 -- ok: a profile that can't say; the next one may
            continue
    return dict(OFF)


def status(timeout: float = 6.0) -> dict:
    """Whether Windows' Mobile hotspot is on right now, however it was turned on, with the name and
    password Windows gave it: {"on", "ssid", "password"}. Never raises; unknown reads as off."""
    if not _on_windows():
        return dict(OFF)
    try:
        return asyncio.run(asyncio.wait_for(_status(), timeout))
    except Exception:  # noqa: BLE001 -- ok: no WinRT, no answer or a refusal all read as "not known to be on"
        return dict(OFF)


def open_settings() -> bool:
    """Open Windows' own Mobile hotspot screen: the fallback when Windows refuses this app's start."""
    if not _on_windows():
        return False
    try:
        os.startfile(SETTINGS_URI)  # noqa: S606 -- a fixed ms-settings address, nothing from outside
        return True
    except (OSError, AttributeError):
        return False


def _on_windows() -> bool:
    return sys.platform == "win32"


def start(root: Optional[Path] = None, timeout: float = TIMEOUT_S) -> tuple[bool, str]:
    """(started, plain reason when not). Never waits on Windows longer than `timeout` seconds."""
    if not _on_windows():
        return False, "the laptop's own Wi-Fi only works on Windows"
    try:
        err = asyncio.run(asyncio.wait_for(_start(password(root)), timeout))
    except (asyncio.TimeoutError, TimeoutError):
        err = f"Windows didn't answer in {int(timeout)} seconds"
    except ImportError:
        return False, "this copy is missing the Windows hotspot files: download Llano Lights again"
    except Exception as e:  # noqa: BLE001 -- never let a hotspot problem reach the show
        err = f"Windows refused: {e}"
    if err:
        return False, err + ". Use your phone's hotspot or a travel router instead: join the laptop and the phone to it."
    return True, ""
