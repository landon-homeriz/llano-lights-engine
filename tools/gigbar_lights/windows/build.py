"""Assemble the Llano Lights Windows folder + zip from the repo package and downloaded parts.

Test channel (2026-11-08): LLANO_LIGHTS_CHANNEL=test LLANO_LIGHTS_BUILD=<n> builds
Llano-Lights-<VERSION>.<n>.zip, stamped as test build n (the window shows the badge). The
downloaded parts (dl/, wheels/) are read from LLANO_LIGHTS_PARTS when set, so a build from a
clean worktree of any commit (scripts/lights/test_channel.py in Llano) uses the same parts.
"""
import datetime, os, re, shutil, zipfile, sys
from history import app_files, build_info_source, central_label, missing_wheels, source_commit
from pathlib import Path

W = Path(__file__).resolve().parent
REPO = next(p for p in W.parents if (p / "tools" / "gigbar_lights").is_dir())
OUT = W / "out" / "Llano-Lights"  # dl/, wheels/ and out/ stay local (see README)
PARTS = Path(os.environ.get("LLANO_LIGHTS_PARTS") or W)
CHANNEL = os.environ.get("LLANO_LIGHTS_CHANNEL") or "stable"
BUILD = int(os.environ.get("LLANO_LIGHTS_BUILD") or 0)
if CHANNEL not in ("stable", "test") or (CHANNEL == "test") != (BUILD > 0):
    sys.exit("LLANO_LIGHTS_CHANNEL=test needs LLANO_LIGHTS_BUILD=<n> (n > 0), and a stable build has neither")
if missing_wheels(PARTS / "wheels"):
    sys.exit(f"build.py: {PARTS / 'wheels'} is missing {', '.join(missing_wheels(PARTS / 'wheels'))}; "
             "run the pip download line in README.md into that folder")
if OUT.exists():
    shutil.rmtree(OUT)
(OUT / "runtime" / "Lib" / "site-packages").mkdir(parents=True)
zipfile.ZipFile(PARTS / "dl" / "python-3.12.10-embed-amd64.zip").extractall(OUT / "runtime")
sp = OUT / "runtime" / "Lib" / "site-packages"
for whl in sorted((PARTS / "wheels").glob("*.whl")):
    zipfile.ZipFile(whl).extractall(sp)
(OUT / "runtime" / "python312._pth").write_text(
    "python312.zip\r\n.\r\nLib\\site-packages\r\n..\\app\r\n")
app = OUT / "app"
shutil.copytree(REPO / "tools" / "gigbar_lights", app / "tools" / "gigbar_lights",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "windows"))  # windows/ = this builder + its out/
for f in app_files(W / "src"):
    shutil.copy2(f, app / f.name)
# gigbar_app.py serves these as /favicon.ico and /icons/*.png: the window's title bar and taskbar icon
shutil.copytree(W / "src" / "icons", app / "icons", ignore=shutil.ignore_patterns("*.py", "__pycache__"))
(OUT / "Mixxx mapping").mkdir()
for f in ("Llano-Light-Link.js", "Llano-Light-Link.midi.xml"):
    shutil.copy2(REPO / "tools" / "gigbar_lights" / "mixxx" / f, OUT / "Mixxx mapping" / f)
for f in (W / "src" / "win").iterdir():
    shutil.copy2(f, OUT / f.name)
for extra in sys.argv[1:]:  # the install guide
    shutil.copy2(extra, OUT / Path(extra).name)
VERSION = re.search(r'^VERSION = "(.+)"', (REPO / "tools" / "gigbar_lights" / "version.py").read_text(), re.M).group(1)
if BUILD:
    VERSION = f"{VERSION}.{BUILD}"   # 1.12.3.7: newer than 1.12.3, older than the next release
# The build time and source commit, stamped into this copy only (version.py reads the time;
# release.py signs both into the feed and refuses a build with no clean commit).
now = datetime.datetime.now(datetime.timezone.utc)
built_ct = central_label(now)
commit = source_commit(REPO)
(app / "tools" / "gigbar_lights" / "build_info.py").write_text(build_info_source(now, commit, channel=CHANNEL, build=BUILD))
# What this build put in the folder, one name per line: Uninstall deletes exactly these and
# leaves anything else (a folder unzipped straight into Documents keeps the rest of Documents).
names = sorted(p.name for p in OUT.iterdir()) + ["llano-lights.install"]
(OUT / "llano-lights.install").write_text("\r\n".join(names) + "\r\n")
zpath = W / "out" / f"Llano-Lights-{VERSION}.zip"  # updater.py only accepts this name shape
with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for p in sorted(OUT.rglob("*")):
        if p.is_file():
            z.write(p, p.relative_to(OUT.parent))
print(zpath, zpath.stat().st_size, "built", built_ct)
