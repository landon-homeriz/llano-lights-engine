# Llano Lights for Mac: building the app

One `Llano Lights.app` for every Mac (Apple Silicon and Intel), built on Linux or a Mac (Llano BL #12517).

```
python tools/gigbar_lights/mac/fetch_parts.py parts            # pinned Python runtimes, wheels, rcodesign (checksums checked)
pip install ziglang==0.13.0                                     # compiles the small launcher for both chips
LLANO_LIGHTS_MAC_PARTS=parts RCODESIGN=parts/bin/rcodesign python tools/gigbar_lights/mac/build.py
```

That writes `out/Llano-Lights-<version>-mac.zip`, ad-hoc signed: it runs on a Mac after
System Settings > Privacy & Security > Open Anyway, and is what the engine CI's macOS job builds and
launches. A release adds `--identity DIR` (Developer ID Application `cert.pem` + `key.pem`) and
`--notarize KEY.json` (an App Store Connect API key, `rcodesign encode-app-store-connect-api-key`), then
`--dmg` for the disk image a new user drags into Applications.

What is inside: `Contents/MacOS/Llano Lights` (launcher.c) runs the bundled Python
(`Contents/Resources/Llano-Lights/runtime/bin/python3`) on the same app the Windows build ships
(`Contents/Resources/Llano-Lights/app`). The window is Chrome, Edge, Brave or Chromium as an app window,
else the default browser. Settings and logs live in `~/Library/Application Support/Llano Lights` and
`~/.gigbar_lights`, never in the app, because an update replaces the whole .app (updater.py).

The update feed: `release.py --platform mac` signs the zip into `latest-mac.json` and adds a `mac`
entry to that version's row in `windows/releases.json`.
