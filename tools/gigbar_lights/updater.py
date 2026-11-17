"""Auto-update from his server: check a small signed file, download, verify, swap, restart.

The update file (latest.json) sits next to the zips in one public folder:

  {"format": 1, "manifest": "<base64 of the manifest JSON>", "signature": "<base64>"}
  manifest = {"product": "llano-lights", "version": "1.2.0", "zip": "Llano-Lights-1.2.0.zip",
              "sha256": "<hex>", "size": <bytes>, "notes": "<one line>", "published": "YYYY-MM-DD",
              "built": "<UTC ISO time>", "built_ct": "Nov 6, 2026, 2:40 PM CT"}

The signature is Ed25519 over the exact manifest bytes, checked against PUBLIC_KEY baked
into the app, so nobody who can change files on the server, or sit between him and it,
can push a fake update: a bad signature, another product, a version that is not newer,
a zip whose size or SHA-256 differs, or a zip name with a path in it is refused.

The zip holds the whole Llano-Lights folder. It is unpacked beside the install
(<install>.new), then a small swap program runs from a copy of Python in the temp
folder (the install's own Python is locked while it runs): it waits for this app to
exit, renames <install> -> <install>.old and <install>.new -> <install>, starts the new
version and removes the old one. If a rename keeps failing (a file held open), it puts
everything back and starts the old version, which says the update did not finish.
Saved layouts and settings live in the user's profile (~/.gigbar_lights and
%LOCALAPPDATA%\\Llano Lights), never inside the install, so a swap keeps them.

Offline, a slow server, or anything unexpected while checking: the app just runs.

Test channel (1.14.0): test.json beside latest.json is the same signed file for a test build
(version <release>.<build>, manifest `channel: "test"` and `build`), published on every merge by
Llano's test-channel job. A laptop Llano puts on the test channel hears of each new build in its
settings pull and shows "Test build N ready" with an Update button (gigbar_app.py); every other
laptop never reads test.json. The same key signs both, so a test build is checked exactly like a
release. Nothing installs without his click.

Going back to stable never needs the internet or a working test build: the first swap from a
stable copy into a test build KEEPS that stable copy beside the install (<install>.stable)
instead of deleting it. stage_rollback() swaps it back in, using the stable copy's own Python, and
rollback.py does the same from a "Llano Lights - go back to stable" launcher (Start menu, and in
the stable folder) that runs the stable copy's code, never the test build's, so it works when the
test build won't open or crashes at start. A new copy that never comes up is put back by the swap
itself, as before.

Mac (Llano BL #12517): a Mac copy reads latest-mac.json (test-mac.json on the test channel) in the
same folder, signed by the same key, whose manifest says `platform: "mac"` and names
Llano-Lights-<version>-mac.zip: the whole notarized "Llano Lights.app", zipped with ditto. Each copy
refuses the other platform's file, so Windows' latest.json is unchanged and pulling the Mac file stops
Mac updates without touching Windows. On a Mac the unit that is swapped is the .app bundle itself
(its signature seals everything inside it), the same rename dance beside it in /Applications.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from . import ed25519
from .version import CHANNEL, VERSION

PRODUCT = "llano-lights"
# No update feed in this edition: updates are off. A builder who wants them points UPDATE_URL
# (or LLANO_LIGHTS_UPDATE_URL) at their own latest.json and puts their own key in PUBLIC_KEY.
UPDATE_URL = ""
TEST_FEED = "test.json"   # the test channel's update file, in the same folder
PLATFORM = "mac" if sys.platform == "darwin" else "windows"
# Each platform's (stable, test) update files, side by side in the one folder (Llano BL #12517).
FEEDS = {"windows": ("latest.json", TEST_FEED), "mac": ("latest-mac.json", "test-mac.json")}
MAC_APP = "Llano Lights.app"
MAC_LAUNCHER = "Contents/MacOS/Llano Lights"
MAC_INNER = "Contents/Resources/Llano-Lights"   # runtime/ + app/ inside the bundle: install_root()
PUBLIC_KEY = bytes.fromhex("26fd96604450df9c052039cbc6ea026a5ae58887d59137b761d7ffa6d86e15e3")
CHECK_TIMEOUT_S = 4.0
MAX_ZIP_BYTES = 300 * 1024 * 1024
_ZIP_NAME = re.compile(r"Llano-Lights-[0-9][0-9A-Za-z.\-]{0,40}\.zip")
_VERSION = re.compile(r"\d+(\.\d+){1,3}")
TOP = "Llano-Lights"  # the zip's top folder (windows/build.py)


class UpdateError(Exception):
    """Plain-English reason an update can't go ahead."""


@dataclass
class Offer:
    version: str
    notes: str
    zip_url: str
    sha256: str
    size: int
    published: str = ""
    built: str = ""  # the build time in Central, as windows/build.py stamped it
    channel: str = "stable"
    build: int = 0   # the test build number, 0 for a release
    commit: str = ""


def update_url(platform: str = "") -> str:
    # A test server can stand in (it names the exact file); the signature check still uses the baked-in key.
    override = os.environ.get("LLANO_LIGHTS_UPDATE_URL")
    if override:
        return override
    if not UPDATE_URL:   # no feed in this edition: none for any platform
        return ""
    return urllib.parse.urljoin(UPDATE_URL, FEEDS[platform or PLATFORM][0])


def test_url(platform: str = "") -> str:
    """The test channel's update file (test.json, test-mac.json) in the stable feed's folder."""
    base = update_url(platform)
    return urllib.parse.urljoin(base, FEEDS[platform or PLATFORM][1]) if base else ""


def version_tuple(v: str) -> tuple:
    if not isinstance(v, str) or not _VERSION.fullmatch(v):
        raise UpdateError(f"not a version number: {v!r}")
    return tuple(int(x) for x in v.split("."))


def is_newer(candidate: str, current: str = VERSION) -> bool:
    a, b = version_tuple(candidate), version_tuple(current)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def sign_manifest(manifest: dict, secret: bytes) -> dict:
    """Server side (windows/release.py): the latest.json body for this manifest."""
    body = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return {"format": 1, "manifest": base64.b64encode(body).decode(),
            "signature": base64.b64encode(ed25519.sign(secret, body)).decode()}


def parse_update_file(raw: bytes, base_url: str, current: str = VERSION,
                      public_key: bytes = PUBLIC_KEY, platform: str = "") -> Optional[Offer]:
    """The offer in a downloaded latest.json, None when nothing newer. Raises UpdateError
    for anything that is not a genuine, well-formed update for this product."""
    try:
        outer = json.loads(raw)
        body = base64.b64decode(outer["manifest"], validate=True)
        sig = base64.b64decode(outer["signature"], validate=True)
    except (ValueError, KeyError, TypeError) as e:
        raise UpdateError("the update server sent something that isn't an update file; running this version") from e
    if not isinstance(outer, dict) or outer.get("format") != 1:
        raise UpdateError("the update file is a format this version doesn't know")
    if not ed25519.verify(public_key, body, sig):
        raise UpdateError("the update file's signature is not ours, so it was ignored")
    try:
        m = json.loads(body)
        version, name, digest, size = m["version"], m["zip"], m["sha256"], m["size"]
    except (ValueError, KeyError, TypeError) as e:
        raise UpdateError("the signed update description is incomplete") from e
    if m.get("product") != PRODUCT:
        raise UpdateError("the update file is for a different product")
    if (m.get("platform") or "windows") != (platform or PLATFORM):   # a Windows zip never reaches a Mac
        raise UpdateError("the update file is for another kind of computer, so it was ignored")
    if not isinstance(name, str) or not _ZIP_NAME.fullmatch(name):
        raise UpdateError("the update names an unexpected file")
    if not (isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)):
        raise UpdateError("the update's checksum is malformed")
    if not (isinstance(size, int) and 0 < size <= MAX_ZIP_BYTES):
        raise UpdateError("the update's size is out of range")
    if not is_newer(version, current):
        return None
    return Offer(version=version, notes=str(m.get("notes") or "")[:300],
                 zip_url=urllib.parse.urljoin(base_url, name), sha256=digest, size=size,
                 published=str(m.get("published") or "")[:20],
                 built=str(m.get("built_ct") or "")[:40],
                 channel="test" if m.get("channel") == "test" else "stable",
                 build=m["build"] if isinstance(m.get("build"), int) and m.get("channel") == "test" else 0,
                 commit=str(m.get("commit") or "")[:40])


def _get(url: str, timeout: float):
    req = urllib.request.Request(url, headers={"User-Agent": f"LlanoLights/{VERSION}",
                                               "Cache-Control": "no-cache"})
    return urllib.request.urlopen(req, timeout=timeout)


UNREACHABLE = "Can't reach the update server yet; running this version"
NO_FEED = "Updates are off: this copy has no update feed (set LLANO_LIGHTS_UPDATE_URL to your own)"


def check(url: Optional[str] = None, current: str = VERSION) -> tuple[Optional[Offer], str]:
    """(offer or None, a plain line on what happened). Never raises: offline means run."""
    url = url or update_url()
    if not url:   # a build with no feed (the open-source engine): nothing to ask, nothing fails
        return None, NO_FEED
    try:
        with _get(url, CHECK_TIMEOUT_S) as r:
            raw = r.read(64 * 1024 + 1)
        if len(raw) > 64 * 1024 or raw.lstrip()[:1] == b"<":  # a sign-in or error page, not latest.json
            return None, UNREACHABLE
        offer = parse_update_file(raw, url, current)
    except UpdateError as e:
        return None, str(e)
    except Exception:  # offline, DNS, TLS, timeout, 404: just run this version
        return None, UNREACHABLE
    if offer is None:
        return None, f"Llano Lights {current} is the newest version"
    return offer, f"Llano Lights {offer.version} is ready"


# --- applying ---------------------------------------------------------------------------

def install_root() -> Path:
    """The Llano-Lights folder this copy runs from (it holds runtime/ and app/)."""
    return Path(__file__).resolve().parents[3]


def is_installed(root: Optional[Path] = None) -> bool:
    """True for an unpacked build (runtime/ + app/; on a Mac the folder inside the .app), False for a source checkout."""
    root = root or install_root()
    return (root / "runtime").is_dir() and (root / "app" / "gigbar_app.py").is_file()


def app_bundle(root: Optional[Path] = None) -> Optional[Path]:
    """The .app a Mac copy runs inside (install_root is its Contents/Resources/Llano-Lights), else None."""
    root = root or install_root()
    b = root.parents[2] if len(root.parents) > 2 else None
    return b if b is not None and b.suffix == ".app" and root == b / MAC_INNER else None


def swap_root(root: Optional[Path] = None) -> Path:
    """What an update replaces: the install folder on Windows, the whole .app on a Mac."""
    root = root or install_root()
    return app_bundle(root) or root


def mac_inner(bundle: Path) -> Path:
    return bundle / MAC_INNER


def mac_update_refusal(bundle: Path) -> str:
    """Why this .app can't replace itself, in his words; "" when it can. A Mac runs an app opened
    straight from Downloads (or the disk image) from a read-only copy elsewhere (App Translocation),
    and an app in a folder he can't write to can't be swapped either."""
    if "/AppTranslocation/" in str(bundle) or str(bundle).startswith("/Volumes/"):
        return ("drag Llano Lights into your Applications folder and open it from there; "
                "a Mac can't update an app opened straight from the download")
    if not os.access(bundle.parent, os.W_OK):
        return f"this Mac doesn't let Llano Lights change {bundle.parent}; drag it into Applications"
    return ""


def download(offer: Offer, dest: Path, progress: Callable[[int, int], None] = lambda d, t: None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    h, done = hashlib.sha256(), 0
    tmp = dest.with_suffix(".part")
    try:
        with _get(offer.zip_url, 30) as r, open(tmp, "wb") as f:
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                done += len(chunk)
                if done > offer.size:
                    raise UpdateError("the download is bigger than the signed size; stopped")
                h.update(chunk)
                f.write(chunk)
                progress(done, offer.size)
    except UpdateError:
        tmp.unlink(missing_ok=True)
        raise
    except Exception as e:
        tmp.unlink(missing_ok=True)
        raise UpdateError(f"the download stopped ({type(e).__name__}); try again later") from e
    if done != offer.size or h.hexdigest() != offer.sha256:
        tmp.unlink(missing_ok=True)
        raise UpdateError("the download doesn't match the signed checksum; nothing was changed")
    os.replace(tmp, dest)
    return dest


def unpack(zpath: Path, staging: Path) -> Path:
    """Unpack the verified zip into `staging` (fresh), refusing any path that climbs out."""
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    root = staging.resolve()
    with zipfile.ZipFile(zpath) as z:
        for info in z.infolist():
            name = info.filename.replace("\\", "/")
            parts = name.split("/")
            if name.startswith("/") or ".." in parts or ":" in name or parts[0] != TOP:
                raise UpdateError("the update zip has an unexpected layout; nothing was changed")
            rel = "/".join(parts[1:])
            if not rel:
                continue
            target = (root / rel).resolve()
            if root not in target.parents:
                raise UpdateError("the update zip has an unexpected layout; nothing was changed")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
    for need in ("runtime/pythonw.exe", "app/gigbar_app.py"):
        if not (root / need).is_file():
            raise UpdateError(f"the update is missing {need}; nothing was changed")
    return root


def unpack_mac(zpath: Path, staging: Path) -> Path:
    """Unpack the verified Mac zip into `staging` (the new .app). The names are checked first (one
    top folder, the .app, nothing that climbs out); then ditto unpacks it, because a signed bundle
    holds symlinks and modes Python's zipfile drops; then the Mac checks the bundle's signature."""
    with zipfile.ZipFile(zpath) as z:
        for info in z.infolist():
            name = info.filename
            parts = name.split("/")
            kind = (info.external_attr >> 16) & 0o170000
            # mac/build.py writes no links: one in an update could point ditto's later writes outside the app
            if name.startswith("/") or ".." in parts or parts[0] != MAC_APP or kind == 0o120000:
                raise UpdateError("the update zip has an unexpected layout; nothing was changed")
    if staging.exists():
        shutil.rmtree(staging)
    work = Path(tempfile.mkdtemp(prefix=".llano-lights-unpack-", dir=staging.parent))
    try:
        r = subprocess.run(["/usr/bin/ditto", "-x", "-k", str(zpath), str(work)], capture_output=True, timeout=600)
        if r.returncode != 0:
            raise UpdateError("the update couldn't be unpacked; nothing was changed")
        app = work / MAC_APP
        if app.is_symlink() or not app.is_dir():
            raise UpdateError("the update zip has an unexpected layout; nothing was changed")
        for need in (MAC_LAUNCHER, f"{MAC_INNER}/app/gigbar_app.py"):
            if not (app / need).is_file():
                raise UpdateError(f"the update is missing {need}; nothing was changed")
        # The bundle is whole and unaltered (who made it is the signed manifest's job, already checked)
        r = subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)],
                           capture_output=True, timeout=300)
        if r.returncode != 0:
            raise UpdateError("the downloaded app's signature doesn't check out; nothing was changed")
        os.rename(app, staging)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return staging


# Copied into the temp folder and run by a copy of the CURRENT (known-good) Python there, so the
# install folder is free to be renamed once the app exits. Standard library only.
# Whatever happens, it ends with an install folder in place: the old copy is kept until the new
# one says it is up (it writes plan["ready"] once its window server listens), and is put back
# if the new one never says so.
# And whatever happens, a copy comes back up (BL #11612, his 11-08 1.12.1 -> 1.14.0: the window
# closed and nothing reopened, several tries): an old copy still holding its files after HANG_S is
# closed, every fallback start is confirmed like the new copy's, and when no copy comes up at all
# Windows shows a box saying so and where the log is. The last "FAILED: " line in the log is the
# plain reason the app shows (and sends Llano) when it comes back on the old version.
SWAP_PROGRAM = r'''
import json, os, shutil, subprocess, sys, time
plan = json.load(open(sys.argv[1], encoding="utf-8"))
if plan.get("mac"):   # all loaded now: on a Mac this Python's own folder is renamed under it. Never on
    import errno, select, selectors, signal   # Windows: its temp runtime has no select.pyd (BL #12517 review)
root, new, old, ready = plan["root"], plan["new"], plan["old"], plan["ready"]
keep, rollback = plan.get("keep"), bool(plan.get("rollback"))
bad = root + ".failed"
log = open(plan["log"], "a", encoding="utf-8")
def say(m):
    log.write(time.strftime("%Y-%m-%d %H:%M:%S ") + m + "\n"); log.flush()
def start(folder, *flags):
    mac = plan.get("mac")
    exe = os.path.join(folder, *(["Contents", "MacOS", "Llano Lights"] if mac else ["runtime", "pythonw.exe"]))
    if not os.path.isfile(exe):
        say("nothing to start at " + folder); return None
    try:
        if mac:   # the .app's own launcher, which runs its Python on its app
            return subprocess.Popen([exe, *flags], cwd=folder, close_fds=True, start_new_session=True,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        nt = os.name == "nt"
        return subprocess.Popen([exe, os.path.join(folder, "app", "gigbar_app.py"), *flags],
                                cwd=os.path.join(folder, "app"), close_fds=True,
                                creationflags=0x00000008 | 0x00000200 if nt else 0)  # DETACHED | NEW_GROUP
    except Exception as e:
        say(f"could not start {exe}: {e}"); return None
def rename(a, b, tries):
    err = None
    for i in range(tries):
        try:
            os.rename(a, b); return True
        except OSError as e:
            err = e; time.sleep(0.5)
    say(f"could not rename {a} -> {b}: {err}"); return False
why = ""
def failed(m):
    global why
    why = why or m
def close_copy(folder):
    """End every program running from folder's runtime (an old copy hung on its way out)."""
    if plan.get("mac"):   # every process whose program lies inside the old .app (its Python)
        inside = os.path.join(folder, "Contents") + os.sep
        try:
            ps = subprocess.run(["/bin/ps", "-axo", "pid=,comm="], capture_output=True, text=True, timeout=30).stdout
            for line in ps.splitlines():
                pid, _, prog = line.strip().partition(" ")
                if prog.strip().startswith(inside) and pid.isdigit() and int(pid) != os.getpid():
                    os.kill(int(pid), signal.SIGKILL)
                    say("closed the old copy's process " + pid)
        except Exception as e:
            say(f"could not close the old copy: {e}")
        return
    if os.name != "nt":
        return
    exe = (os.path.join(folder, "runtime") + "\\").replace("'", "''")
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                        "Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and "
                        "$_.ExecutablePath.StartsWith('" + exe + "', [StringComparison]::OrdinalIgnoreCase) } "
                        "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"],
                       capture_output=True, timeout=30, creationflags=0x08000000)   # CREATE_NO_WINDOW
    except Exception as e:
        say(f"could not close the old copy: {e}")
def comes_up(proc, flag, seconds):
    deadline = time.time() + seconds
    while proc and time.time() < deadline and not os.path.exists(flag) and proc.poll() is None:
        time.sleep(0.25)
    return os.path.exists(flag)
def box(text):
    """Windows' own message box (this Python has no ctypes: PowerShell shows it)."""
    say("told him: " + text)
    if plan.get("mac"):
        try:
            subprocess.Popen(["/usr/bin/osascript", "-e", "on run argv", "-e",
                              "display alert \"Llano Lights\" message (item 1 of argv) as warning", "-e", "end run",
                              text], close_fds=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            say(f"could not show the message: {e}")
        return
    if os.name != "nt":
        return
    env = dict(os.environ, LLANO_BOX=text)
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command",
                          "Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show("
                          "$env:LLANO_BOX, 'Llano Lights', 'OK', 'Warning') | Out-Null"],
                         env=env, close_fds=True, creationflags=0x08000000)
    except Exception as e:
        say(f"could not show the message: {e}")
def fall_back(folder):
    """Start folder as the copy that stays, with the reason, and make sure it comes up."""
    say("FAILED: " + (why or "the update didn't finish"))
    flag = ready + ".back"
    proc = start(folder, "--update-failed", "--ready-file", flag)
    if comes_up(proc, flag, plan.get("ready_s", 120)):
        say("Llano Lights " + folder + " is open again")
        return
    if proc and proc.poll() is None:
        say("it is still starting; leaving it to finish")
        return
    box("Llano Lights couldn't update to " + plan["version"] + " and didn't reopen on its own.\n\n"
        "Open Llano Lights from " + ("Applications" if plan.get("mac") else "the Start menu")
        + ". Your layouts and calibration are safe.\n\n"
        "What happened is in " + plan["log"])
# One rule: a swap never deletes a copy that could be the last good one. Only the previous copy
# after the new one is up (a plain update), and a downloaded copy that failed, are ever removed.
# The stable copy (keep, or the rollback's new) is only ever renamed.
say("swap started: " + plan["version"] + " into " + root)
open(plan["started"], "w").close()  # tells the old app the swap is alive, so it may exit
back = None        # where the previous copy sits once moved aside (old, or keep)
moved_new = False  # the new copy is at root
ok = False
try:
    if os.path.exists(old): shutil.rmtree(old, ignore_errors=True)   # a dead swap's leftover, never a keep
    if os.path.exists(bad): shutil.rmtree(bad, ignore_errors=True)
    say("waiting for Llano Lights to close")
    if plan.get("mac") and plan.get("pid"):
        # A Mac renames a running app's folder without complaint, so "the rename failed" can't say the
        # old copy is still open (Windows' signal): wait for its process, and close it if it hangs, so
        # the new copy never meets it holding the lock and the lights box (BL #12517 review).
        def alive(pid):
            try:
                os.kill(pid, 0); return True
            except ProcessLookupError:
                return False
            except OSError:
                return True
        hang = min(plan.get("hang_s", 20), plan.get("wait_s", 90))
        deadline = time.time() + hang
        while alive(plan["pid"]) and time.time() < deadline:
            time.sleep(0.25)
        if alive(plan["pid"]):
            say("the old copy is still open after " + str(hang) + " s; closing it")
            close_copy(root)
            deadline = time.time() + 10
            while alive(plan["pid"]) and time.time() < deadline:
                time.sleep(0.25)
    if os.path.exists(root):
        hang = min(plan.get("hang_s", 20), plan.get("wait_s", 90))
        moved = rename(root, old, int(hang * 2))
        if not moved:   # the old copy hung on its way out and still holds its files: close it
            say("the old copy is still open after " + str(hang) + " s; closing it")
            close_copy(root)
            time.sleep(2)
            moved = rename(root, old, int(max(plan.get("wait_s", 90) - hang, 10) * 2))
        if not moved:
            failed(("the Mac" if plan.get("mac") else "Windows") + " kept the old copy's files open, so the new version couldn't go in")
            fall_back(root); sys.exit(1)
        back = old
    else:
        say("no install in place (the copy there was removed); the new copy goes in directly")
    if not rename(new, root, 240 if rollback else 20):
        failed("the downloaded copy couldn't be moved into place")
        sys.exit(1)   # finally puts the previous copy back
    moved_new = True
    if keep and back:   # stable -> test: the stable copy is set aside BEFORE the new one starts
        if os.path.exists(keep):
            say("an older kept copy is at " + keep + "; it is replaced")
            shutil.rmtree(keep, ignore_errors=True)
        if not rename(old, keep, 40):
            failed("the stable copy couldn't be set aside")
            sys.exit(1)
        back = keep
        say("kept the previous copy at " + keep)
    say("swapped in " + plan["version"])
    proc = start(root, "--updated", "--ready-file", ready)
    if not comes_up(proc, ready, plan.get("ready_s", 120)):
        exited = proc is not None and proc.poll() is not None
        say("the new copy did not come up; putting the previous one back")
        failed(plan["version"] + (" closed as it started" if exited else " didn't open within "
                                  + str(plan.get("ready_s", 120)) + " s" if proc else " couldn't be started"))
        if proc and proc.poll() is None:
            proc.kill(); time.sleep(1)
        sys.exit(1)
    ok = True
    if back == old:
        for i in range(40):
            if not os.path.exists(old): break
            shutil.rmtree(old, ignore_errors=True)
            time.sleep(0.5)
    say("done")
finally:
    if not ok:
        if moved_new and back is None and rollback:
            say("the stable copy is the only copy; it stays as the install")
            fall_back(root)
        elif moved_new:
            # the copy that failed leaves root: a rollback's stable copy goes back to where it was
            dest = new if rollback else bad
            if not rename(root, dest, 120):
                say("COULD NOT move the failed copy aside; nothing was deleted (previous copy at "
                    + str(back) + ")")
                fall_back(root)
            elif back and rename(back, root, 240):
                say("previous copy restored")
                fall_back(root)
            else:
                say("COULD NOT RESTORE: the previous copy is at " + str(back) + ", the new one at " + dest)
                fall_back(back or dest)
            if not rollback and os.path.exists(bad) and os.path.exists(root):
                shutil.rmtree(bad, ignore_errors=True)   # the downloaded copy that failed, never a stable one
        elif back and not os.path.exists(root):
            ok_back = rename(back, root, 240)
            say("previous copy restored" if ok_back else "COULD NOT RESTORE: the previous copy is at " + back)
            fall_back(root if ok_back else back)
'''

_RUNTIME_FILES = ("pythonw.exe", "python.exe", "python3.dll", "vcruntime140.dll", "vcruntime140_1.dll")


def scratch_dir(root: Path) -> Path:
    """The temp folder, unless it sits inside the install (no TEMP set: Python falls back to
    the current folder, which is app/); then the folder beside the install."""
    d = Path(tempfile.gettempdir()).resolve()
    r = root.resolve()
    return r.parent if d == r or r in d.parents else d


def update_log(root: Optional[Path] = None) -> Path:
    """The swap's log (it outlives both copies: it sits in the temp folder)."""
    return scratch_dir(root or install_root()) / "llano-lights-update.log"


def last_swap(root: Optional[Path] = None, max_lines: int = 60) -> "tuple[list[str], str]":
    """The last swap's log lines (from its "swap started" line) and the plain reason it gave up
    ("" when it finished, or there is no log). A copy started with --update-failed shows it."""
    try:
        lines = update_log(root).read_text(encoding="utf-8", errors="replace").splitlines()[-2000:]
    except OSError:
        return [], ""
    starts = [i for i, ln in enumerate(lines) if " swap started: " in ln]
    run = lines[starts[-1]:] if starts else lines[-max_lines:]
    why = next((ln.split("FAILED: ", 1)[1] for ln in reversed(run) if "FAILED: " in ln), "")
    return run[-max_lines:], why


def stage_swap(root: Path, staging: Path, version: str, wait_s: float = 90.0,
               keep: Optional[Path] = None, runtime: Optional[Path] = None, rollback: bool = False) -> list[str]:
    """Write the swap program and a small Python beside it in the temp folder; return the
    command that runs it. The running install's own runtime is copied: it is known to work
    (Windows lets running exe/dll files be read); a rollback copies the stable copy's instead.
    `keep`: move the replaced copy there instead of deleting it."""
    work = Path(tempfile.mkdtemp(prefix="llano-lights-swap-", dir=scratch_dir(root)))
    if root.suffix == ".app" and (root / MAC_LAUNCHER).is_file():   # a Mac copy swaps its whole bundle
        return _stage_swap_mac(work, root, staging, version, wait_s, keep, runtime, rollback)
    rt = runtime or root / "runtime"
    for f in rt.iterdir():
        if f.name in _RUNTIME_FILES or re.fullmatch(r"python3\d+\.(dll|zip)", f.name):
            shutil.copyfile(f, work / f.name)  # not copy2: Python 3.12 copy2 needs CopyFile2, absent under Wine
    pth = next((p.name for p in work.glob("python3*.zip")), None)
    if pth:
        (work / pth.replace(".zip", "._pth")).write_text(f"{pth}\r\n.\r\n")
    (work / "llano_swap.py").write_text(SWAP_PROGRAM, encoding="utf-8")
    plan = {"root": str(root), "new": str(staging), "old": str(root) + ".old", "version": version,
            "wait_s": wait_s, "log": str(update_log(root)),
            "started": str(work / "started"), "ready": str(work / "ready"), "ready_s": 120, "hang_s": 20,
            "keep": str(keep) if keep else None, "rollback": rollback}
    (work / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    exe = work / ("pythonw.exe" if (work / "pythonw.exe").exists() else "python.exe")
    return [str(exe), str(work / "llano_swap.py"), str(work / "plan.json")]


def _stage_swap_mac(work: Path, bundle: Path, staging: Path, version: str, wait_s: float,
                    keep: Optional[Path], runtime: Optional[Path], rollback: bool) -> list[str]:
    """The Mac swap: the same program, run by the running copy's own Python in place (a Mac lets a
    running program's folder be renamed; the program loads every module it needs before it does).
    It swaps whole .app bundles and starts the new one through its launcher."""
    py = (runtime or mac_inner(bundle) / "runtime") / "bin" / "python3"
    (work / "llano_swap.py").write_text(SWAP_PROGRAM, encoding="utf-8")
    plan = {"root": str(bundle), "new": str(staging), "old": str(bundle) + ".old", "version": version,
            "wait_s": wait_s, "log": str(update_log(mac_inner(bundle))),
            "started": str(work / "started"), "ready": str(work / "ready"), "ready_s": 120, "hang_s": 20,
            "keep": str(keep) if keep else None, "rollback": rollback, "mac": True, "pid": os.getpid()}
    (work / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    # -B: no .pyc written. This Python lives inside the signed bundle, and a cache file added there
    # breaks the seal of the copy kept for Go back (the launcher sends the app's caches elsewhere).
    return [str(py), "-B", "-E", "-s", str(work / "llano_swap.py"), str(work / "plan.json")]


def launch_swap(cmd: list[str], wait_s: float = 15.0) -> None:
    """Start the swap and wait until it says it is alive; raise UpdateError (and leave the
    app running, nothing changed) if it never does."""
    flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    started = Path(cmd[-1]).parent / "started"   # the command ends: swap program, plan
    try:
        proc = subprocess.Popen(cmd, cwd=str(Path(cmd[-2]).parent), creationflags=flags, close_fds=True,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        raise UpdateError(f"the installer couldn't start ({e})") from e
    deadline = time.time() + wait_s
    while time.time() < deadline:
        if started.exists():
            return
        if proc.poll() is not None:
            break
        time.sleep(0.1)
    if proc.poll() is None:
        proc.kill()
    raise UpdateError("the installer didn't start, so nothing was changed")


def prepare(offer: Offer, root: Optional[Path] = None,
            progress: Callable[[int, int], None] = lambda d, t: None) -> list[str]:
    """Download, verify and unpack the offer beside the install; return the swap command.
    Nothing in the install changes until the swap runs after the app exits. Going from a stable
    copy to a test build keeps the stable copy (stable_path) for Go back to stable."""
    root = root or install_root()
    if not is_installed(root):
        raise UpdateError("this copy isn't an installed Llano Lights folder, so it can't update itself")
    bundle = app_bundle(root)
    if bundle is not None:
        return _prepare_mac(offer, root, bundle, progress)
    parent = root.parent
    zpath = download(offer, parent / f".llano-lights-download" / Path(urllib.parse.urlparse(offer.zip_url).path).name,
                     progress)
    staging = unpack(zpath, Path(str(root) + ".new"))
    try:
        zpath.unlink()
    except OSError:
        pass
    keep = stable_path(root) if CHANNEL == "stable" and offer.channel == "test" else None
    if keep:
        write_rollback_launchers(root)
    return stage_swap(root, staging, offer.version, keep=keep)


def _prepare_mac(offer: Offer, root: Path, bundle: Path, progress: Callable[[int, int], None]) -> list[str]:
    why = mac_update_refusal(bundle)
    if why:
        raise UpdateError(why)
    zpath = download(offer, bundle.parent / ".llano-lights-download" / Path(urllib.parse.urlparse(offer.zip_url).path).name,
                     progress)
    try:
        staging = unpack_mac(zpath, Path(str(bundle) + ".new"))
    finally:
        zpath.unlink(missing_ok=True)
    keep = stable_path(root) if CHANNEL == "stable" and offer.channel == "test" else None
    return stage_swap(bundle, staging, offer.version, keep=keep)


# --- going back to stable (no internet, no working test build needed) ---------------------------

ROLLBACK_NAME = "Llano Lights - go back to stable.cmd"


def stable_path(root: Optional[Path] = None) -> Path:
    """Beside the install folder; on a Mac beside the .app ("Llano Lights.app.stable")."""
    return Path(str(swap_root(root)) + ".stable")


def stable_copy(root: Optional[Path] = None) -> Optional[Path]:
    """The stable copy kept on disk, or None when there is none (or it is not a whole install)."""
    root = root or install_root()
    p = stable_path(root)
    return p if is_installed(mac_inner(p) if app_bundle(root) else p) else None


def stage_rollback(root: Optional[Path] = None) -> list[str]:
    """The swap command that puts the stable copy back as the install (its own Python runs it)."""
    root = root or install_root()
    stable = stable_copy(root)
    if stable is None:
        raise UpdateError("there is no stable copy on this laptop to go back to")
    inner = mac_inner(stable) if app_bundle(root) else stable
    return stage_swap(swap_root(root), stable, "the stable copy", runtime=inner / "runtime", rollback=True)


def stop_copy(root: Path) -> None:
    """Close any Llano Lights still running from `root` (a test build that hangs), Windows only."""
    if os.name != "nt":
        return
    exe = (str(root / "runtime") + "\\").replace("'", "''")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                    "Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and "
                    "$_.ExecutablePath.StartsWith('" + exe + "', [StringComparison]::OrdinalIgnoreCase) } "
                    "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"],
                   capture_output=True, timeout=30, creationflags=0x08000000)   # CREATE_NO_WINDOW


def _start_menu() -> Optional[Path]:
    appdata = os.environ.get("APPDATA")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" if appdata else None


def rollback_launcher_text(root: Path) -> str:
    """UTF-8 with chcp 65001 first (cmd reads a batch file in the OEM codepage otherwise, which
    garbles a path like C:\\Users\\José), and % doubled so cmd never expands a path."""
    stable, here = str(stable_path(root)).replace("%", "%%"), str(root).replace("%", "%%")
    return ("@echo off\r\nchcp 65001 >nul\r\n"
            "rem Llano Lights: put the stable copy back (it runs the stable copy's own code).\r\n"
            f'"{stable}\\runtime\\python.exe" -m tools.gigbar_lights.rollback "{here}"\r\n'
            "if not \"%errorlevel%\"==\"0\" pause\r\n")


def write_rollback_launchers(root: Path) -> list[Path]:
    """Write the go-back launcher into the Start menu and beside the install folder (not inside
    either copy: both get renamed). Best effort: the in-app button works without them."""
    out = []
    text = rollback_launcher_text(root)
    for folder in (_start_menu(), root.parent):
        if folder is None:
            continue
        try:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / ROLLBACK_NAME).write_text(text, encoding="utf-8")
            out.append(folder / ROLLBACK_NAME)
        except OSError:
            pass
    return out


def remove_rollback_launchers(root: Path) -> None:
    for folder in (_start_menu(), root.parent):
        if folder is not None:
            try:
                (folder / ROLLBACK_NAME).unlink(missing_ok=True)
            except OSError:
                pass


def clean_leftovers(root: Optional[Path] = None) -> None:
    """After a swap: drop the old copy, the download folder and spent temp runtimes."""
    root = root or install_root()
    if not is_installed(root):
        return
    top = swap_root(root)
    for p in (Path(str(top) + ".old"), Path(str(top) + ".failed") if top != root else None,
              top.parent / ".llano-lights-download"):
        if p is not None:
            shutil.rmtree(p, ignore_errors=True)
    if CHANNEL == "stable":   # back on a stable copy: a kept stable copy is stale, and so is its launcher
        shutil.rmtree(stable_path(root), ignore_errors=True)
        if top == root:
            remove_rollback_launchers(root)
    cutoff = time.time() - 600
    for p in scratch_dir(root).glob("llano-lights-swap-*"):
        try:
            if p.stat().st_mtime < cutoff:
                shutil.rmtree(p, ignore_errors=True)
        except OSError:
            pass
