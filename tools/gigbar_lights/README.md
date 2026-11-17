# gigbar_lights: Mixxx drives our own light show (Path B)

Room: `gigbar-laptop-controller` ("Two paths, run in parallel", Path B).

```
Mixxx 2.5 ──(Llano Light Link mapping, SysEx)──> loopMIDI "Llano Mixxx" ──> gigbar_lights ──USB──> ENTTEC DMX USB Pro ──> 12 lights
           mixxxdb.sqlite (read-only: track name, beat grid) ──────────────────┘
```

## How Mixxx hands over the beat

Mixxx has no OSC, no Ableton Link and no MIDI clock out (checked against the 2.5.6
release and the development branch, Nov 2026). Its controller scripting is the clean
door: a mapping's JavaScript reads each deck's `beat_distance` (fraction of the way to
the next beat), `bpm`, `play`, volume/crossfader, `vu_meter`, loop state and Mixxx's
output latency, and sends them as SysEx. The track's name and beat grid come from
Mixxx's library file, opened read-only. Song sections (intro, build, drop, ...) come
from our own analysis of each track's audio (`analyze`), our version of SoundSwitch's
autoscript; tracks without one run autoloops.

## Setup on the Windows laptop (one time)

1. Install **Mixxx 2.5.x** (mixxx.org) and **loopMIDI** (tobias-erichsen.de, free). In
   loopMIDI add a port named `Llano Mixxx`.
2. Copy `mixxx/Llano-Light-Link.midi.xml` and `mixxx/Llano-Light-Link.js` into
   `%LOCALAPPDATA%\Mixxx\controllers\`.
3. In Mixxx: Preferences > Controllers > `Llano Mixxx`, tick Enabled, load mapping
   "Llano Light Link", Apply.
4. Install Python 3.11+, the hardware libraries and (Windows) the Spotify / YouTube Music listeners:
   `pip install python-rtmidi pyserial numpy soundfile soundcard winrt-runtime winrt-Windows.Media.Control winrt-Windows.Foundation winrt-Windows.Foundation.Collections`
5. Plug in the ENTTEC. It shows up as a COM port; if it doesn't, Device Manager > the
   FTDI device > Advanced > tick "Load VCP".

## Use

From the repo root:

| Command | What it does |
|---|---|
| `python -m tools.gigbar_lights test-lights` | Lights each of the 12 fixtures white in turn: the address check |
| `python -m tools.gigbar_lights analyze` | Works out song sections for the Mixxx library (once per new track) |
| `python -m tools.gigbar_lights run` | The live show |
| `python -m tools.gigbar_lights run --dry-run` | The live show with no ENTTEC: virtual rig in the terminal |
| `python -m tools.gigbar_lights sim` | No Mixxx and no gear: a fake 128 BPM track through every section |

Keys while running: `b` blackout, `s` strobe, space tap tempo (when Mixxx isn't
running), `a` autoloops over scripts, `n`/`p` next/previous autoloop, `h` hold autoloop,
`c` cycle a held color, `+`/`-` master intensity, `[`/`]` lights 5 ms earlier/later, `q` quit
(leaves the rig dark).

## Room layouts (Show Designer)

`venue.py` places the 12 lights in a top-down room plan: four presets (small room or
wedding hall; Tetras across the front of the booth or uplighting the walls; sticks on the
dance floor corners) plus his own layouts saved from the Windows app's Show Designer
(`~/.gigbar_lights/layouts/*.json`; the one in use is in `~/.gigbar_lights/venue.json`).
From the layout the show aims each moving head at real room points from where it really
sits, runs chases in left-to-right order of where the lights stand, alternates sticks
left and right of the dance floor, and sweeps the beams from the left of the floor to
the right. A layout holds positions only; the address plan in `rig.py` never changes.
`run` and `sim` take `--layout NAME`; without it they use the layout in use.
His saved layouts are his venues (1.27.0, Llano BL #12380): the Show Designer lists them
under My venues, apart from the presets, to open, rename (the label only; the file and the
name Llano syncs it under stay) or delete (the file is set aside as `<name>.json.removed`,
and the venue comes off llano.app/lights too). The venue in use can't be deleted.
Draw my room keeps his line-up (1.27.1, Llano BL #12400): the room it draws from three numbers takes
each head's line-up from the room playing now (else his saved room with one), so the heads still face
the dance floor; the old room's spots stay behind, and two spots lined up at the venue set where the
bars really stand. Without it the guessed model points head 1 of each GigBAR backwards on his rig.

Fluid travel (1.27.1, Llano BL #12400): a slow glide or sweep travels at an even pace the heads play
smoothly and rests at both ends, instead of crawling and stopping half way (`looks.travel_share`);
`LLANO_LIGHTS_FLUID_TRAVEL=0` brings back 1.27.0's slow legs.

Who plays the music (1.27.2, Llano BL #12410): Mixxx plays the music and Llano Lights follows it,
said on the Live screen (laptop and phone). The Show Designer's player is "Preview the lights": it
runs the show's lights on the picture and makes sound only for songs that are files in his Mixxx
library, and says before the press how many of the show's songs that is (a show of none previews
silently, and says so). Rollback: a clean revert of the release commit; nothing is stored.

Which end Tetra 1 and stick 1 start at is a rig fact, `rig.numbering` (Llano BL
#12396): his Tetra cords run from the right, so Flip the Tetra numbers records "right", and
the Stage setup and every ready-made room number from there. A saved venue keeps the
numbers it was saved with.

## Other DMX boxes (Open DMX, Art-Net, sACN)

The ENTTEC DMX USB Pro is the default. `dmx_outputs.py` (Llano BL #12136) puts the others behind the
same seam: an FTDI Open DMX class dongle (this side makes the DMX break and timing, 192-slot frames
like the ENTTEC path), an Art-Net node (ArtDmx over UDP 6454) or sACN (E1.31 over UDP 5568,
multicast or to one receiver). Pick one with `LLANO_LIGHTS_OUTPUT` for the Windows app (its run, its
status dots and Llano's probes all use it), or `--output` on `run` and `test-lights`:

    opendmx:COM4            an Open DMX dongle (name its port: it is the same chip as the ENTTEC)
    artnet:192.168.1.50:1   an Art-Net node's own address and its universe (Port-Address 0-32767)
    sacn:2@192.168.1.60     sACN universe 2 to one receiver; sacn:2 = multicast to the universe's group
    artnet:192.168.1.255%192.168.1.10   broadcast or multicast from this laptop's address on the lights' network

Name the node's address when you can (Art-Net asks for unicast). A laptop on venue Wi-Fi with a cable
to the lights adds `%` and its cable-side address, or the packets go out the Wi-Fi. A network output
can't tell whether anything hears it, so the status says "sending to", not "plugged in": run
`test-lights --output ...` once at the venue. Unset, or set to something that doesn't parse (logged),
the app looks for the ENTTEC Pro as before. sACN tells receivers it has stopped when the show does.

## Sharing the ENTTEC with SoundSwitch

We only send DMX frames (API label 6). We never change the box's settings or firmware,
so SoundSwitch sees it exactly as before. One program at a time: quit this app before
opening SoundSwitch, and the other way round.

## Timing

- Mixxx updates beat position once per audio buffer (Preferences > Sound Hardware, about
  5 to 23 ms). The beat clock runs at the deck's exact BPM and averages that jitter out;
  seeks, cues and loops snap it at once.
- Mixxx works ahead of the speakers by its output latency, which the mapping reports, so
  the lights are delayed by the same amount.
- In simulation (95 to 140 BPM, 256/512/1024-sample buffers, delivery jitter) the drop's
  strobe fires 2 to 4.5 ms after the drop leaves the speakers. DMX adds up to one 25 ms
  frame; frames are rendered half a frame ahead and only the rig's 192 slots are sent
  (about 9 ms on the wire). Fine-tune by eye with `[` and `]`.
- Speaker sync (`rig.sync_ms`, Levels > Speaker sync): the time the speakers take after the
  laptop sends the sound, which nothing on the laptop can see (a Bluetooth speaker measured 0.98 s
  on 2026-11-15). Set it once with Tap along to set; every light waits for it.
  `LLANO_LIGHTS_SYNC=0` turns it off.
- A night's cut (Build the night) tags where its original's 0:00 sits, so its 8-bar phrases are
  counted from the original's first beat, not the cut's.

## Cue workspace

Cues on the Live screen's fold (or Studio's) opens the cue workspace (`/cues`, also on the phone over
the laptop's Wi-Fi): one song full screen with its waveform, the beats and Llano's parts on top, and
the show lane by lane underneath (wash, strobe, heads, sticks, laser, derby), worked out by the same
code the lights run (`cue_workspace.lanes`). Tap the song to set the cursor, drag to mark a stretch,
then pick a marker: Build starts, Drop, Blackout, White-out, Color flash, Strobe burst, Repeat (a
stretch played again from earlier, in a new color) or Note to Llano (sent to the Conductor on the
lights room). Markers snap to the nearest beat (Snap to beat), drag by their flag, nudge a beat with
the arrow keys (0.1 s with Shift), and Delete removes the picked one. Space plays the song from the
cursor right there, so he can check a marker by ear without Mixxx; the lanes redraw with each change.
Back to Llano's parts drops his section markers for that song.

Cues are saved per song (settings `cues`, original-recording seconds, 32 KB at most), play on the
next frame, land on the same note in a night's cut, and wait for Speaker sync. Any section cue
replaces the analysis for that song. Never over the Blackout button, a held look, a scene, a moment, or a
cocktail-hour/dinner song. `LLANO_LIGHTS_CUES=0` turns cues off.

Drops land where the song reaches its full level (`show_script.refine_drops`): the 8-bar phrase count
can label a loud pre-chorus as the drop (Sorry: 0:39), so each drop moves later, bar by bar, to the
first bar at full level (Sorry: 1:07.8), and the 8 bars before it are the build. It only ever moves a
drop later. `LLANO_LIGHTS_DROP_REFINE=0` gives the old labels for songs analysed from then on.

A Big hit is the white-out pad's look held a second (every wash and stick section white, heads open,
the GigBAR strobes bursting); a hit with a color (`"color": "#rrggbb"`) flashes the whole rig in it.

## Freedom Sticks in sections (48CH)

Set each stick to 48CH on its own menu (MENU until `48CH`, ENTER, then the start address) at 151, 199,
247 and 295, and name the 48CH channels in the rig block (`settings_contract.STICK_MODES["48ch"]`, with
those addresses). The sticks then chase and bounce a block in verses, fill bottom to top through a
build (full on the drop), and go fully white on every hit. If a stick fills top-down, list its sections
from seg16. 8-CH stays the default. `LLANO_LIGHTS_STICK_FX=0` lights every section as one.

A Big hit is the white-out pad's look held a second (every wash and stick section white, heads open,
the GigBAR strobes bursting); a hit with a color (`"color": "#rrggbb"`) flashes the whole rig in it.

## Freedom Sticks in sections (48CH)

Set each stick to 48CH on its own menu (MENU until `48CH`, ENTER, then the start address) at 151, 199,
247 and 295, and name the 48CH channels in the rig block (`settings_contract.STICK_MODES["48ch"]`, with
those addresses). The sticks then chase and bounce a block in verses, fill bottom to top through a
build (full on the drop), and go fully white on every hit. If a stick fills top-down, list its sections
from seg16. 8-CH stays the default. `LLANO_LIGHTS_STICK_FX=0` lights every section as one.

## Fixture library (any DJ's lights)

`fixture_profiles.py` (Llano BL #12136) reads a light from the two open fixture libraries: a QLC+
`.qxf` file (github.com/mcallegari/qlcplus `resources/fixtures`, Apache 2.0) or an Open Fixture
Library `.json` (open-fixture-library.org, MIT). Each mode becomes channels driven by named
attributes (`red`, `dim`, `strobe`, `pan`, `color`, `rotate`, ..., prefixed by the part of the light:
`par1.red`, `head2.pan`). `fixtures/overrides.json` holds what the libraries lack (the app's
channel names, program channels held at 0, strobe floors, the byte picked in a band, roles, D-Fi
notes); the library files stay unmodified. A rig of profiles is `{"fixtures": [{"profile":
"Venue-Tetra-6.qxf", "mode": "6 Channel", "address": 81, "role": "wash"}, ...]}`
(`fixture_profiles.load_rig`); roles are wash, movers, effects and strobes, and
`ProfileRig.set_role("wash", red=1.0)` sets every wash light whatever its brand.

His 12 lights run through it: the three files in `fixtures/qlcplus` plus their overrides give
exactly the bytes the hand-written classes in `rig.py` gave (pinned against frames the released
1.19.3 and 1.37.0 rendered, `tests/gigbar_lights/test_fixture_profiles.py`). Every fixture in both
libraries imports (all 1,781 QLC+ files and 653 OFL fixtures, checked 2026-11-17).
A Freedom Stick's library mode is its 8-CH one; in 48CH its 16 sections' bytes are added beside
those (Llano BL #12518). `LLANO_LIGHTS_PROFILES=0` sends the hand-written bytes again; so does a library file that won't load.

## Still to check on real gear

- A light other than his three kinds runs on library data plus the importer's reading of it: before
  a show on new gear, run the address check and the line-up check on it, and put any fix in
  `fixtures/overrides.json`.

- The GigBAR moving-head strobe, Tetra strobe and Freedom Stick channel values come from
  the QLC+ fixture library; confirm on the units (`test-lights`, then a strobe in `sim`).
- The pan/tilt model (pan 0.5 = the bar's facing, 540 degrees; the heads hang under the bar,
  manual p. 8, so tilt 0.5 = straight down and 1 = level toward the front) is a best guess on
  which side is the front; check it on arrival night with the line-up check ("down" first, then
  "center"; if "center" lands behind the bar, turn the bar 180 degrees) and correct a bar with its
  layout's `pan_trim` / `tilt_trim` (degrees) instead of touching any look.
- MP3/FLAC/WAV analyze through `soundfile`; AAC/M4A files need converting or stay on autoloops.
