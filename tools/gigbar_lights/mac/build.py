"""Build "Llano Lights.app" for every Mac (Apple Silicon and Intel in one app), from Linux (Llano BL #12517).

  python tools/gigbar_lights/mac/build.py                      # ad-hoc signed: runs, not notarized
  python tools/gigbar_lights/mac/build.py --identity DIR       # Developer ID signed, hardened runtime
  python tools/gigbar_lights/mac/build.py --identity DIR --notarize KEY.json   # + notarized, stapled

Writes out/Llano-Lights-<version>-mac.zip (what a Mac copy updates itself with: the whole .app) and,
with --dmg, out/Llano-Lights-<version>-mac.dmg (what a new user drags into Applications).

Like the Windows build (windows/build.py) it reads its downloaded parts from LLANO_LIGHTS_MAC_PARTS
(default: parts/ beside this file, which stays local):
  dl/cpython-3.12.*-aarch64-apple-darwin-install_only.tar.gz and the x86_64 one (python-build-standalone)
  wheels-arm64/ and wheels-x86_64/: see README.md for the pip download lines
and its tools from PATH (or env): rcodesign (RCODESIGN), zig (ZIG, or `python -m ziglang`).

The two runtimes are joined file by file: the same file once, two builds of one Mach-O as one
universal (fat) file, anything else from Apple Silicon's. Symlinks become real files, so the zip
needs nothing but names, bytes and modes. Every Mach-O is signed (rcodesign); with --identity the
Python carries the entitlements a Python needs under the hardened runtime (entitlements.plist).

--identity DIR holds the Developer ID Application certificate as cert.pem and its key as key.pem
(never in the repo; Llano keeps them in its secret store). --notarize KEY.json is an App Store
Connect API key in rcodesign's JSON form. Neither is needed to build and test an ad-hoc app.
"""
from __future__ import annotations

import argparse
import datetime
import os
import plistlib
import re
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

M = Path(__file__).resolve().parent
REPO = next(p for p in M.parents if (p / "tools" / "gigbar_lights").is_dir())
W = REPO / "tools" / "gigbar_lights" / "windows"
sys.path.insert(0, str(W))
sys.path.insert(1, str(M))
from history import app_files, build_info_source, central_label, source_commit  # noqa: E402

APP = "Llano Lights.app"
BUNDLE_ID = "app.llano.lights"
ARCHES = {"arm64": "aarch64", "x86_64": "x86_64"}       # Mac name -> python-build-standalone name
ZIG_TARGETS = {"arm64": "aarch64-macos.11.0", "x86_64": "x86_64-macos.10.15"}
MIN_MACOS = "11.0"
REQUIRED_WHEELS = ("python_rtmidi", "pyserial", "numpy", "soundfile", "segno", "cffi", "pycparser")
# What the app never uses, left out of the runtime (about 40 MB): Tk, IDLE, the test suite, pip.
DROP = ("lib/python3.12/test", "lib/python3.12/idlelib", "lib/python3.12/tkinter", "lib/python3.12/turtledemo",
        "lib/python3.12/ensurepip", "lib/python3.12/lib2to3", "lib/python3.12/site-packages/pip",
        "lib/python3.12/config-3.12-darwin", "lib/tcl9", "lib/tcl9.0", "lib/tk9.0", "lib/itcl4.3.8",
        "lib/libtcl9.0.dylib", "lib/thread3.0.6", "lib/libtcl9tk9.0.dylib", "lib/libpython3.12.dylib", "lib/pkgconfig",
        "include", "share")
DROP_GLOB = ("lib/python3.12/lib-dynload/_tkinter*", "lib/python3.12/site-packages/pip-*")

FAT_MAGIC = 0xCAFEBABE
MH_MAGIC_64 = 0xFEEDFACF
FAT_ALIGN = 14   # 16 KB, what lipo uses for arm64 slices


# --- Mach-O: tell one apart, join two into one universal file -----------------------------------

def macho_cpu(data: bytes) -> "tuple[int, int] | None":
    """(cputype, cpusubtype) of a thin 64-bit Mach-O, else None (a script, data, a fat file)."""
    if len(data) < 12 or struct.unpack("<I", data[:4])[0] != MH_MAGIC_64:
        return None
    return struct.unpack("<ii", data[4:12])


CPU_X86_64, CPU_ARM64 = 0x01000007, 0x0100000C


def thin_slices(data: bytes) -> "dict[int, bytes] | None":
    """{cputype: thin Mach-O} of a thin or fat (universal) file, else None. numpy's wheels ship
    libgcc_s already fat, with a different build of it in each architecture's wheel."""
    if macho_cpu(data):
        return {macho_cpu(data)[0]: data}
    if len(data) < 8 or struct.unpack(">I", data[:4])[0] != FAT_MAGIC:
        return None
    n = struct.unpack(">I", data[4:8])[0]
    if not 0 < n <= 8:   # a Java .class shares the magic; its "count" is a version number
        return None
    out = {}
    for i in range(n):
        cpu, _sub, off, size, _align = struct.unpack(">iiIII", data[8 + 20 * i: 28 + 20 * i])
        if not macho_cpu(data[off:off + size]):
            return None
        out[cpu] = data[off:off + size]
    return out


def fat(slices: list[bytes]) -> bytes:
    """One universal Mach-O from thin ones, each slice on a 16 KB boundary (what `lipo -create` writes)."""
    align = 1 << FAT_ALIGN
    head_len = 8 + 20 * len(slices)
    offsets, at = [], -(-head_len // align) * align
    for s in slices:
        offsets.append(at)
        at = -(-(at + len(s)) // align) * align
    out = bytearray(struct.pack(">II", FAT_MAGIC, len(slices)))
    for s, off in zip(slices, offsets):
        cpu, sub = macho_cpu(s)
        out += struct.pack(">iiIII", cpu, sub & 0x00FFFFFF, off, len(s), FAT_ALIGN)
    for s, off in zip(slices, offsets):
        out += b"\0" * (off - len(out)) + s
    return bytes(out)


def merge(arm: Path, intel: Path, out: Path) -> dict:
    """Join two runtimes into `out`. Returns counts, for the build line."""
    seen = {"same": 0, "universal": 0, "arm_only": 0, "intel_only": 0, "differs": []}
    rels = {p.relative_to(arm) for p in arm.rglob("*")} | {p.relative_to(intel) for p in intel.rglob("*")}
    for rel in sorted(rels, key=str):
        a, b, dst = arm / rel, intel / rel, out / rel
        if a.is_dir() or b.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not b.exists():
            seen["arm_only"] += 1
            shutil.copyfile(a, dst)
        elif not a.exists():
            seen["intel_only"] += 1
            shutil.copyfile(b, dst)
        else:
            da, db = a.read_bytes(), b.read_bytes()
            if da == db:
                seen["same"] += 1
                dst.write_bytes(da)
            elif (sa := thin_slices(da)) and (sb := thin_slices(db)) and CPU_ARM64 in sa and CPU_X86_64 in sb:
                seen["universal"] += 1
                dst.write_bytes(fat([sb[CPU_X86_64], sa[CPU_ARM64]]))   # each chip's own build; Intel first, as lipo
            else:
                seen["differs"].append(str(rel))
                dst.write_bytes(da)
        src = a if a.exists() else b
        dst.chmod(stat.S_IMODE(src.stat().st_mode) | 0o644)
    return seen


# --- the runtime -------------------------------------------------------------------------------------

def runtime_for(arch: str, parts: Path, work: Path) -> Path:
    """One architecture's Python with the app's wheels, trimmed, symlinks made real."""
    tars = sorted((parts / "dl").glob(f"cpython-3.12.*-{ARCHES[arch]}-apple-darwin-install_only.tar.gz"))
    if not tars:
        sys.exit(f"mac/build.py: no python-build-standalone {ARCHES[arch]} runtime in {parts / 'dl'}")
    dest = work / arch
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    with tarfile.open(tars[-1]) as t:
        t.extractall(dest, filter="data")
    rt = dest / "python"
    for rel in DROP:
        p = rt / rel
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p)
        elif p.exists() or p.is_symlink():
            p.unlink()
    for pat in DROP_GLOB:
        for p in rt.glob(pat):
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    # bin/: only the interpreter, as python3 (the launcher and the Mac update swap run that name)
    exe = rt / "bin" / "python3.12"
    keep = rt / ".python3"
    shutil.move(str(exe), keep)
    shutil.rmtree(rt / "bin")
    (rt / "bin").mkdir()
    shutil.move(str(keep), rt / "bin" / "python3")
    for link in [p for p in rt.rglob("*") if p.is_symlink()]:
        target = link.resolve()
        link.unlink()
        if target.is_file():
            shutil.copy2(target, link)
    wheels = parts / f"wheels-{arch}"
    have = {w.name.split("-", 1)[0].lower() for w in wheels.glob("*.whl")}
    missing = [n for n in REQUIRED_WHEELS if n not in have]
    if missing:
        sys.exit(f"mac/build.py: {wheels} is missing {', '.join(missing)}; run the pip download lines in README.md")
    sp = rt / "lib" / "python3.12" / "site-packages"
    for whl in sorted(wheels.glob("*.whl")):
        with zipfile.ZipFile(whl) as z:
            z.extractall(sp)
    for p in sp.rglob("*.so"):
        p.chmod(0o755)
    for p in rt.rglob("__pycache__"):
        shutil.rmtree(p, ignore_errors=True)
    return rt


# --- the launcher, the bundle ------------------------------------------------------------------------

def zig() -> list[str]:
    if os.environ.get("ZIG"):
        return [os.environ["ZIG"]]
    if shutil.which("zig"):
        return ["zig"]
    return [sys.executable, "-m", "ziglang"]


def launcher(work: Path) -> bytes:
    slices = []
    for arch in ("x86_64", "arm64"):
        out = work / f"launcher-{arch}"
        subprocess.run([*zig(), "cc", "-target", ZIG_TARGETS[arch], "-O2",
                        "-Wl,-headerpad_max_install_names", "-o", str(out), str(M / "launcher.c")],
                       check=True)
        slices.append(out.read_bytes())
    return fat(slices)


def info_plist(version: str, build: int) -> bytes:
    short = re.match(r"\d+\.\d+\.\d+", version).group(0)
    return plistlib.dumps({
        "CFBundleName": "Llano Lights", "CFBundleDisplayName": "Llano Lights",
        "CFBundleIdentifier": BUNDLE_ID, "CFBundleExecutable": "Llano Lights",
        "CFBundlePackageType": "APPL", "CFBundleSignature": "????", "CFBundleIconFile": "llano-lights",
        "CFBundleShortVersionString": short, "CFBundleVersion": version if build else short,
        "CFBundleInfoDictionaryVersion": "6.0", "CFBundleDevelopmentRegion": "en",
        "LSMinimumSystemVersion": MIN_MACOS, "LSApplicationCategoryType": "public.app-category.music",
        # The window is a browser app window; this program has no window of its own, so no Dock icon
        # of its own either (one that bounced and vanished would read as a crash).
        "LSUIElement": True, "NSHighResolutionCapable": True,
        "NSAppleEventsUsageDescription": "Llano Lights asks Spotify and Music which song is playing, "
                                         "so the lights can follow it.",
        "NSAudioCaptureUsageDescription": "Llano Lights listens to what the Mac plays so the lights follow the beat.",
    })


def icns(png512: bytes) -> bytes:
    """A one-image .icns (512 px PNG as ic09); the Mac scales it for the Dock and Finder."""
    body = b"ic09" + struct.pack(">I", 8 + len(png512)) + png512
    return b"icns" + struct.pack(">I", 8 + len(body)) + body


def assemble(out_dir: Path, runtime: Path, launcher_bytes: bytes, version: str, build: int, channel: str,
             commit: str, now: datetime.datetime) -> Path:
    app = out_dir / APP
    if app.exists():
        shutil.rmtree(app)
    contents = app / "Contents"
    inner = contents / "Resources" / "Llano-Lights"
    (contents / "MacOS").mkdir(parents=True)
    exe = contents / "MacOS" / "Llano Lights"
    exe.write_bytes(launcher_bytes)
    exe.chmod(0o755)
    (contents / "Info.plist").write_bytes(info_plist(version, build))
    (contents / "PkgInfo").write_bytes(b"APPL????")
    (contents / "Resources" / "llano-lights.icns").parent.mkdir(parents=True, exist_ok=True)
    (contents / "Resources" / "llano-lights.icns").write_bytes(icns((W / "src" / "icons" / "icon-512.png").read_bytes()))
    shutil.copytree(runtime, inner / "runtime", symlinks=False)
    a = inner / "app"
    shutil.copytree(REPO / "tools" / "gigbar_lights", a / "tools" / "gigbar_lights",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "windows", "mac"))
    for f in app_files(W / "src"):
        shutil.copy2(f, a / f.name)
    shutil.copytree(W / "src" / "icons", a / "icons", ignore=shutil.ignore_patterns("*.py", "__pycache__"))
    (inner / "Mixxx mapping").mkdir()
    for f in ("Llano-Light-Link.js", "Llano-Light-Link.midi.xml"):
        shutil.copy2(REPO / "tools" / "gigbar_lights" / "mixxx" / f, inner / "Mixxx mapping" / f)
    (a / "tools" / "gigbar_lights" / "build_info.py").write_text(
        build_info_source(now, commit, channel=channel, build=build))
    return app


# --- signing, notarizing, the zip and the disk image -------------------------------------------------

def rcodesign() -> str:
    exe = os.environ.get("RCODESIGN") or shutil.which("rcodesign")
    if not exe:
        sys.exit("mac/build.py: rcodesign isn't on PATH (or RCODESIGN); see README.md")
    return exe


def sign(app: Path, identity: "Path | None") -> None:
    py = "Contents/Resources/Llano-Lights/runtime/bin/python3"
    cmd = [rcodesign(), "sign", "--code-signature-flags", "runtime",
           "--entitlements-xml-file", f"{py}:{M / 'entitlements.plist'}"]
    if identity:
        cmd += ["--pem-file", str(identity / "cert.pem"), "--pem-file", str(identity / "key.pem"), "--for-notarization"]
    subprocess.run([*cmd, str(app)], check=True, stdout=subprocess.DEVNULL)


def notarize(path: Path, api_key: Path) -> None:
    subprocess.run([rcodesign(), "notary-submit", "--api-key-file", str(api_key), "--staple", "--wait",
                    str(path)], check=True)


def zip_app(app: Path, zpath: Path) -> None:
    """The .app as a zip with each file's mode (ditto unpacks it on the Mac, keeping them)."""
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(app.rglob("*")):
            rel = str(p.relative_to(app.parent))
            if p.is_dir():
                zi = zipfile.ZipInfo(rel + "/")
                zi.external_attr = (stat.S_IFDIR | 0o755) << 16
                z.writestr(zi, b"")
                continue
            zi = zipfile.ZipInfo.from_file(p, rel)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = (stat.S_IFREG | stat.S_IMODE(p.stat().st_mode)) << 16
            with open(p, "rb") as f:
                z.writestr(zi, f.read())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--identity", type=Path, help="folder with cert.pem + key.pem (Developer ID Application)")
    ap.add_argument("--notarize", type=Path, help="App Store Connect API key JSON (rcodesign encode-app-store-connect-api-key)")
    ap.add_argument("--dmg", action="store_true", help="also write the disk image (mac/dmg.py)")
    ap.add_argument("--out", type=Path, default=M / "out")
    a = ap.parse_args(argv)
    if a.notarize and not a.identity:
        sys.exit("--notarize needs --identity: Apple notarizes only a Developer ID signed app")
    parts = Path(os.environ.get("LLANO_LIGHTS_MAC_PARTS") or M / "parts")
    channel = os.environ.get("LLANO_LIGHTS_CHANNEL") or "stable"
    build = int(os.environ.get("LLANO_LIGHTS_BUILD") or 0)
    if channel not in ("stable", "test") or (channel == "test") != (build > 0):
        sys.exit("LLANO_LIGHTS_CHANNEL=test needs LLANO_LIGHTS_BUILD=<n> (n > 0), and a stable build has neither")
    version = re.search(r'^VERSION = "(.+)"', (REPO / "tools" / "gigbar_lights" / "version.py").read_text(), re.M).group(1)
    if build:
        version = f"{version}.{build}"
    work = a.out / "work"
    work.mkdir(parents=True, exist_ok=True)
    rts = {arch: runtime_for(arch, parts, work) for arch in ARCHES}
    uni = work / "universal"
    if uni.exists():
        shutil.rmtree(uni)
    seen = merge(rts["arm64"], rts["x86_64"], uni)
    print(f"runtime: {seen['universal']} universal binaries, {seen['same']} shared files, "
          f"{seen['arm_only']} Apple Silicon only, {seen['intel_only']} Intel only, {len(seen['differs'])} differ "
          f"(Apple Silicon's kept: {', '.join(seen['differs'][:4])}{'...' if len(seen['differs']) > 4 else ''})")
    now = datetime.datetime.now(datetime.timezone.utc)
    app = assemble(a.out, uni, launcher(work), version, build, channel, source_commit(REPO), now)
    sign(app, a.identity)
    if a.notarize:
        notarize(app, a.notarize)
    zpath = a.out / f"Llano-Lights-{version}-mac.zip"
    zip_app(app, zpath)
    print(zpath, zpath.stat().st_size, "built", central_label(now), "notarized" if a.notarize else
          ("signed (not notarized)" if a.identity else "ad-hoc signed (runs on a Mac after Open Anyway; not notarized)"))
    if a.dmg:
        from dmg import make_dmg  # noqa: PLC0415  (beside this file)
        dpath = make_dmg(app, a.out / f"Llano-Lights-{version}-mac.dmg")
        if a.identity:
            subprocess.run([rcodesign(), "sign", "--pem-file", str(a.identity / "cert.pem"),
                            "--pem-file", str(a.identity / "key.pem"), str(dpath)], check=True, stdout=subprocess.DEVNULL)
            if a.notarize:
                notarize(dpath, a.notarize)
        print(dpath, dpath.stat().st_size)
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
