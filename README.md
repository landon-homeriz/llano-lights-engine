# Llano Lights engine

A light show for mobile DJs that follows the music by itself. It runs on the DJ's laptop, reads the
beat from Mixxx (or from whatever the laptop is playing), and drives the lights over DMX: a looks engine
that builds, drops and calms with the song, moving heads that glide instead of stepping, a house show
for nights with no plan, and a phone remote that works on the local Wi-Fi with no internet at all.

This is the engine of [Llano Lights](https://llano.app), released under the Apache License 2.0.

## What is in here

- **DMX out** behind one seam: ENTTEC DMX USB Pro, FTDI-based "Open DMX" cables, Art-Net and sACN
  (`tools/gigbar_lights/dmx_outputs.py`, `enttec.py`).
- **Any light, from the open fixture libraries**: QLC+ `.qxf` files and Open Fixture Library JSON become
  profiles, and a rig is a list of lights by role (wash, movers, effects, strobes), so a look never writes
  channel numbers (`fixture_profiles.py`, `fixtures/`).
- **The beat link**: a Mixxx controller mapping plus a reader for Mixxx's library (beat grid, track
  names), or the laptop's own media session for Spotify and YouTube Music (`mixxx/`, `mixxx_link.py`,
  `system_audio.py`, `beat_clock.py`).
- **Looks and the show**: sections, builds, drops, scene pads, moments for a wedding night, a set
  arranger, and the house show (`looks.py`, `show.py`, `shows.py`, `moments.py`).
- **The window and the phone remote**: a local web app on 127.0.0.1 with a room picture of the rig, a
  line-up so moving heads aim at real spots on the floor, and a phone console served over the local
  network (`windows/src/`).
- **Three demo songs** (CC0) so the show can run with no music library.

## Not in here

The cloud layer of the hosted product stays closed: syncing a show with llano.app, the AI show
designer and the assistant. This edition runs entirely on the laptop. Settings live in
`settings.json` beside the saved layouts, and the "Link to Llano" box does not appear.

Auto-update is off in this edition. If you ship your own builds, point `UPDATE_URL` in
`tools/gigbar_lights/updater.py` at your own signed `latest.json` and put your Ed25519 public key in
`PUBLIC_KEY`.

## Run it

Python 3.12. From the repo root:

```
PYTHONPATH=. python -m tools.gigbar_lights --help
PYTHONPATH=. python tools/gigbar_lights/windows/src/gigbar_app.py            # the window
PYTHONPATH=. python tools/gigbar_lights/windows/src/gigbar_app.py demo --seconds 10 --no-browser
```

The window works on Linux for development; the DJ build targets Windows (see
`tools/gigbar_lights/windows/README.md` to build the no-install zip).

## Tests

```
pip install pytest numpy==2.4.6 soundfile==0.14.0
PYTHONPATH=. python -m pytest tests/gigbar_lights/ -q
```

Browser tests run when Playwright and Chromium are installed, and skip otherwise.

The package is still named `gigbar_lights` after the first rig it ran (Chauvet GigBAR Moves); it runs
any rig now.

## License and names

Apache License 2.0; see `LICENSE` and `NOTICE` (the QLC+ fixture files are Apache 2.0, the Open
Fixture Library format support follows its MIT-licensed data, the demo songs are CC0).

"Llano Lights" and "Llano" are names of the hosted product and are not licensed with this code. The
license covers the code, not the name: if you distribute your own build, give it a different name
and icon.
