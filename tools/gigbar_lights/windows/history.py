"""Build times and the version history (releases.json, newest first) for Llano Lights builds.

build.py stamps each build's time with central_label(); release.py reads it back out of the zip
and adds the build to releases.json; upload.py fills in download links. For the room:

  python history.py > history.md     # the table under Latest download (llano_room.py put)
"""
import datetime
import json
import re
import subprocess
import zipfile
from pathlib import Path
from zoneinfo import ZoneInfo

HISTORY = Path(__file__).resolve().parent / "releases.json"
BUILD_INFO = "Llano-Lights/app/tools/gigbar_lights/build_info.py"  # inside the zip
MAC_APP = "Llano Lights.app"
MAC_BUILD_INFO = f"{MAC_APP}/Contents/Resources/{BUILD_INFO}"     # inside the Mac zip (mac/build.py)
# notarytool's ticket, stapled into the bundle: present only once Apple has notarized this exact app
MAC_TICKET = f"{MAC_APP}/Contents/CodeResources"


def _build_info(z: zipfile.ZipFile) -> str:
    """build_info.py's text from a Windows or a Mac zip; KeyError when neither has it."""
    names = set(z.namelist())
    return z.read(MAC_BUILD_INFO if MAC_BUILD_INFO in names else BUILD_INFO).decode()


def notarized_in(zip_path: Path) -> bool:
    """True when the Mac zip's app carries Apple's stapled notarization ticket."""
    with zipfile.ZipFile(zip_path) as z:
        return MAC_TICKET in set(z.namelist())
# Every wheel the README's download line fetches (file names lowercase, dots as underscores). Each
# one past numpy only fails softly at run time (no Spotify/YouTube follow, no song names, no
# hotspot, no QR), so a parts folder missing one built 1.15.0 and 1.16.0 without them and nothing
# said so. build.py refuses instead (1.16.1).
REQUIRED_WHEELS = ("python_rtmidi", "pyserial", "numpy", "soundfile", "soundcard", "segno", "winrt_runtime",
                   "winrt_windows_media_control", "winrt_windows_foundation", "winrt_windows_foundation_collections",
                   "winrt_windows_networking_connectivity", "winrt_windows_networking_networkoperators")


def missing_wheels(wheels: Path) -> list[str]:
    """REQUIRED_WHEELS with no matching .whl in the folder (a name matches only up to its version)."""
    have = {w.name.split("-", 1)[0].lower() for w in wheels.glob("*.whl")}
    return [n for n in REQUIRED_WHEELS if n not in have]


def central_label(when: datetime.datetime) -> str:
    """'Nov 6, 2026, 2:40 PM CT' (CST or CDT as the date has it)."""
    ct = when.astimezone(ZoneInfo("America/Chicago"))
    return f"{ct:%b} {ct.day}, {ct.year}, {ct.hour % 12 or 12}:{ct:%M} {ct:%p} CT"


def build_info_source(when: datetime.datetime, commit: str = "", channel: str = "stable", build: int = 0) -> str:
    utc = when.astimezone(datetime.timezone.utc).replace(microsecond=0)
    src = f"BUILT_UTC = {utc.isoformat().replace('+00:00', 'Z')!r}\nBUILT_CT = {central_label(utc)!r}\n"
    src += f"BUILT_COMMIT = {commit!r}\n" if commit else ""
    return src + (f"CHANNEL = {channel!r}\nBUILD = {int(build)}\n" if channel == "test" else "")


def source_commit(repo: Path) -> str:
    """The full sha this checkout is at, with '-dirty' when tracked files differ from it
    (so a build of uncommitted code can never be signed as if it were that commit); '' outside git."""
    try:
        sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True,
                             text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=no"],
                               capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""
    return sha + ("-dirty" if dirty else "") if re.fullmatch(r"[0-9a-f]{40}", sha) else ""


def app_files(src: Path) -> list[Path]:
    """The files build.py puts beside gigbar_app.py in app/: the app, every page it serves and the
    scripts those pages load (studio_console.js, 1.20.0). A glob, not a list: 1.11.0 shipped without
    shows.html because the list missed it."""
    return [src / "gigbar_app.py", *sorted(src.glob("*.html")), *sorted(src.glob("*.js"))]


def build_time_in(zip_path: Path) -> tuple[str, str]:
    """(UTC ISO, Central label) that build.py stamped into this zip; ValueError if it has none."""
    try:
        with zipfile.ZipFile(zip_path) as z:
            src = _build_info(z)
    except KeyError:
        raise ValueError(f"{zip_path.name} has no build time in it; rebuild it with build.py") from None
    found = dict(re.findall(r"^(BUILT_UTC|BUILT_CT) = '([^']*)'$", src, re.M))
    if set(found) != {"BUILT_UTC", "BUILT_CT"}:
        raise ValueError(f"{zip_path.name} has a damaged build time; rebuild it with build.py")
    return found["BUILT_UTC"], found["BUILT_CT"]


def build_commit_in(zip_path: Path) -> str:
    """The full commit sha build.py stamped into this zip; ValueError when it has none or the
    build was made from uncommitted changes (the feed must name the exact commit it was built from)."""
    try:
        with zipfile.ZipFile(zip_path) as z:
            src = _build_info(z)
    except KeyError:
        raise ValueError(f"{zip_path.name} has no build stamp in it; rebuild it with build.py") from None
    m = re.search(r"^BUILT_COMMIT = '([^']*)'$", src, re.M)
    if not m:
        raise ValueError(f"{zip_path.name} does not say which commit it was built from; rebuild it with build.py")
    if not re.fullmatch(r"[0-9a-f]{40}", m.group(1)):
        raise ValueError(f"{zip_path.name} was built from uncommitted changes ({m.group(1)[:12]}...); "
                         "commit, then rebuild from a clean checkout")
    return m.group(1)


def build_number_in(zip_path: Path) -> int:
    """The test-channel build number build.py stamped into this zip, 0 for a stable build."""
    with zipfile.ZipFile(zip_path) as z:
        src = _build_info(z)
    m = re.search(r"^BUILD = (\d+)$", src, re.M)
    return int(m.group(1)) if m and re.search(r"^CHANNEL = 'test'$", src, re.M) else 0


def load(path: Path = HISTORY) -> dict:
    return json.loads(path.read_text()) if path.exists() else {"product": "llano-lights", "releases": []}


def save(history: dict, path: Path = HISTORY) -> None:
    path.write_text(json.dumps(history, indent=1) + "\n")


def add_release(history: dict, manifest: dict) -> dict:
    """Put a signed build at the top; a version already listed is refused (bump VERSION instead)."""
    if any(r["version"] == manifest["version"] for r in history["releases"]):
        raise ValueError(f"{manifest['version']} is already in releases.json; bump VERSION in version.py and rebuild")
    history["releases"].insert(0, {"version": manifest["version"], "built_utc": manifest["built"],
                                   "built_ct": manifest["built_ct"], "notes": manifest["notes"],
                                   "zip": manifest["zip"], "sha256": manifest["sha256"],
                                   "size": manifest["size"], "download": ""})
    if manifest.get("commit"):
        history["releases"][0]["commit"] = manifest["commit"]
    return history


def add_mac(history: dict, manifest: dict, dmg: "dict | None" = None) -> dict:
    """Put a signed Mac build on its version's row as `mac` (Llano BL #12517). The Windows build of
    that version must already be listed, from the same commit: a Mac build is the same release for
    the other computer, never a release of its own. dmg = {"name", "sha256", "size"} of the download
    a new user installs from; the zip is what a Mac copy updates itself with."""
    row = next((r for r in history["releases"] if r["version"] == manifest["version"]), None)
    if row is None:
        raise ValueError(f"{manifest['version']} isn't in releases.json yet: release the Windows build first")
    if row.get("commit") and manifest.get("commit") and row["commit"] != manifest["commit"]:
        raise ValueError(f"the Mac build is from {manifest['commit'][:12]}, but {manifest['version']} was released "
                         f"from {row['commit'][:12]}; build the Mac app from that commit")
    if row.get("mac"):
        raise ValueError(f"{manifest['version']} already has a Mac build; bump VERSION for a new one")
    row["mac"] = {"zip": manifest["zip"], "sha256": manifest["sha256"], "size": manifest["size"],
                  "built_utc": manifest["built"], "notarized": bool(manifest.get("notarized")), "download": ""}
    if dmg:
        row["mac"].update(dmg=dmg["name"], dmg_sha256=dmg["sha256"], dmg_size=dmg["size"])
    return history


def set_download(history: dict, zip_name: str, link: str) -> dict:
    for r in history["releases"]:
        if r["zip"] == zip_name:
            r["download"] = link
        mac = r.get("mac") or {}
        if zip_name and zip_name == mac.get("zip"):
            mac["download"] = link
        if zip_name and zip_name == mac.get("dmg"):
            mac["dmg_download"] = link
    return history


def _cell(text) -> str:
    return " ".join(str(text).split()).replace("|", "/")


def render(history: dict) -> str:
    """The markdown table for the room, newest first."""
    rows = ["| Version | Built (Central) | What changed | Download |", "|---|---|---|---|"]
    for i, r in enumerate(history["releases"]):
        name = "Newest (same link as above)" if i == 0 else r["zip"]
        link = f"[{name}]({r['download']})" if r.get("download") else "not uploaded"
        when = _cell(r["built_ct"]) + ("\\*" if r.get("backfilled") else "")
        mac = r.get("mac") or {}
        if mac.get("dmg_download") or mac.get("download"):
            link += f" · [Mac]({mac.get('dmg_download') or mac['download']})"
        rows.append(f"| **{_cell(r['version'])}** | {when} | {_cell(r['notes'])} | {link} |")
    if any(r.get("backfilled") for r in history["releases"]):
        rows += ["", "\\* From before builds carried their own version and time: numbered afterwards, "
                     "and the time is when it reached your Drive, a minute or two after it was built."]
    return "\n".join(rows)


if __name__ == "__main__":
    print(render(load()))
