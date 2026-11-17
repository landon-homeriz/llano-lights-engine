# Llano Lights Windows package

Builds the no-install Windows zip of `tools/gigbar_lights`: Python's embeddable runtime + Windows
wheels, a desktop window, and a Setup that adds Start/desktop shortcuts and copies the Mixxx
mapping into `%LOCALAPPDATA%\Mixxx\controllers`. Built from Linux; no Wine or Windows needed to build.

## The app

`src/gigbar_app.py` with no arguments opens the window: one local server on 127.0.0.1
(ports 8765-8784) serves `src/app.html` (start any mode, Stop, show buttons, setup checks, log)
with `src/preview.html` embedded (`/preview?embed=1`). It opens in an Edge app window (`--app`,
own profile in `%LOCALAPPDATA%\Llano Lights\window`) and quits when that window closes; without
Edge it opens the default browser and quits after two minutes with no page asking. A second
launch finds the running one and shows its window. Every POST carries a per-launch token baked
into the page and every request must name 127.0.0.1/localhost as Host, so no web page the DJ
visits can drive the lights. The log is `%LOCALAPPDATA%\Llano Lights\llano-lights.log`.

`gigbar_app.py menu` keeps the numbered text menu; `gigbar_app.py demo --seconds 10
--no-browser` (and the other modes) run straight from a terminal, Linux included
(`PYTHONPATH=<repo root>`).

## Build

```
cd tools/gigbar_lights/windows
mkdir -p dl && curl -sSfL -o dl/python-3.12.10-embed-amd64.zip https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip
python -m pip download --only-binary=:all: --platform win_amd64 --python-version 3.12 --implementation cp --abi cp312 -d wheels python-rtmidi pyserial numpy soundfile soundcard winrt-runtime winrt-Windows.Media.Control winrt-Windows.Foundation winrt-Windows.Foundation.Collections winrt-Windows.Networking.Connectivity winrt-Windows.Networking.NetworkOperators segno
python guide/render.py                     # guide/guide.html -> out/Llano Lights - How to install.pdf
python build.py "out/Llano Lights - How to install.pdf"   # -> out/Llano-Lights-<VERSION>.zip
```

Bump `tools/gigbar_lights/version.py` for each build. If you distribute a build, give it your own
name and icon (see the README's note on names).

## Updates

`tools/gigbar_lights/updater.py` checks a signed `latest.json` (Ed25519) at launch and swaps in a
newer zip, with a rollback if the new copy never comes up. In this edition `UPDATE_URL` is empty, so
updates are off and the window says so. To ship your own: generate an Ed25519 key pair, put the
public key in `PUBLIC_KEY`, serve `latest.json` and the zip from your own host, and set
`UPDATE_URL` (or `LLANO_LIGHTS_UPDATE_URL` for a test server). Never commit the private key.
