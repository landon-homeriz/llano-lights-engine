"""gigbar_lights: Mixxx-driven light show for the 12-light GigBAR rig.

  python -m tools.gigbar_lights run            live show (Mixxx + ENTTEC)
  python -m tools.gigbar_lights run --dry-run  live show, no DMX box (virtual rig only)
  python -m tools.gigbar_lights analyze        work out song sections for the Mixxx library
  python -m tools.gigbar_lights sim            fake Mixxx at 128 BPM, virtual rig in the terminal
  python -m tools.gigbar_lights test-lights    light each fixture in turn (address check)
  add --layout NAME to run/sim to aim from a saved room layout (default: the one in use)

Keys while running: b blackout, s strobe, space tap tempo, a autoloop override,
n/p next/previous autoloop, h hold autoloop, c color hold, +/- master,
[ ] lights earlier/later by 5 ms, 0 timing back to the music, q quit.
"""
from __future__ import annotations

import argparse
import math
import random
import sys
import time
from pathlib import Path

from .enttec import EnttecPro, NullOutput, OutputLoop
from .looks import LINEUP_SPOTS, PALETTES, LooksEngine
from .mixxx_db import MixxxLibrary
from .mixxx_link import DEFAULT_PORT_HINT, MidiInput, encode_audio, encode_tick, encode_track
from .rig import default_rig
from .show import DeckTrack, Show, default_cache_dir
from .show_script import ScriptCache, Section, ShowScript, analyze_track
from .venue import LayoutStore
from . import glide, show_settings, venue
from . import settings_contract as contract


# --- keyboard ---------------------------------------------------------------------------

class Keys:
    """Non-blocking single key reads on Windows and POSIX terminals."""

    def __enter__(self):
        self._old = None
        if sys.platform != "win32" and sys.stdin.isatty():
            import termios
            import tty
            self._old = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
        return self

    def __exit__(self, *exc):
        if self._old is not None:
            import termios
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self._old)

    def read(self) -> str | None:
        if sys.platform == "win32":
            import msvcrt
            return msvcrt.getwch() if msvcrt.kbhit() else None
        import select
        if sys.stdin.isatty() and select.select([sys.stdin], [], [], 0)[0]:
            return sys.stdin.read(1)
        return None


HOLD_HUES = [None, 0.0, 0.08, 0.33, 0.55, 0.66, 0.83]


def parse_aim(text: str) -> "dict | None":
    """The line-up page's one-spot aim (1.16.0) from its JSON: {"poses": [[bar, head, pan, tilt], ...],
    "focus": [bar, head] or null, "others": 0..1}. Anything malformed, or no poses, ends it (None)."""
    import json
    try:
        msg = json.loads(text) if text else None
        poses = {}
        for b, m, p, t in (msg or {}).get("poses") or []:
            if b not in (1, 2) or m not in (0, 1) or not (0.0 <= p <= 1.0 and 0.0 <= t <= 1.0):
                return None
            poses[(b, m)] = (float(p), float(t))
        focus = msg.get("focus") if msg else None
        focus = (int(focus[0]), int(focus[1])) if focus else None
        others = float(msg.get("others", 0.15)) if msg else 0.0
    except (ValueError, TypeError, KeyError, AttributeError):
        return None
    if not poses or (focus is not None and focus not in poses) or not 0.0 <= others <= 1.0:
        return None
    return {"poses": poses, "focus": focus, "others": others}


def handle_key(key: str, show: Show) -> bool:
    """Apply one key; False means quit."""
    ov = show.looks.overrides
    st = getattr(show, "studio", None)
    if st is not None and st.live and (key == "b" or key.startswith("scene:")):
        # The Light studio is the front page (1.20.0): a blackout or a scene pad from any older
        # screen (the classic window, a phone on an older page) is the studio's own, so the strip
        # shows it and the newest press wins everywhere.
        name = key[6:] if key != "b" else ""
        try:
            if key == "b":
                st.command({"op": "blackout"})
            elif name == "whiteout":
                st.command({"op": "hit", "name": "whiteout", "on": True})
            elif name == "blackout":
                st.command({"op": "blackout", "on": True})
            elif name in contract.SCENES:
                st.command({"op": "hit", "name": "whiteout", "on": False})
                st.command({"op": "look", "key": "scene:" + name})
            else:   # back to the show
                st.command({"op": "hit", "name": "whiteout", "on": False})
                st.command({"op": "blackout", "on": False})
                st.command({"op": "release"})
            show_settings.clear_scene()
        except ValueError:   # ok: a pad this studio does not have is ignored, like an unknown key
            pass
        return True
    if key.startswith("scene:"):   # a scene pad in the window (1.6.0); "scene:" = back to the show
        name = key[6:]
        ov.scene = name if name in contract.SCENES else None
        show_settings.clear_scene()   # the newest press wins: Llano's older pad is over here (looks.active_scene)
        return True
    if key.startswith("lineup:"):   # the line-up check (1.7.0); bar 0 = both; "lineup:" = done
        bar, _, spot = key[7:].partition(":")
        ov.lineup = (int(bar), spot) if bar in ("0", "1", "2") and spot in LINEUP_SPOTS else None
        if ov.lineup is None:   # leaving the line-up ends calibrating too, and the next one starts lit
            ov.raw_head, ov.aim_set, ov.lights_on, ov.lights_whole = None, None, True, False
        return True
    if key in ("lights:2", "lights:1", "lights:0"):   # Lights on (1.12.3): 1 the heads, 2 the whole bar (1.14.1)
        ov.lights_on, ov.lights_whole = key != "lights:0", key == "lights:2"
        return True
    if key.startswith("aim:"):   # Line up my lights, one spot (1.16.0); "aim:" = done
        ov.aim_set = parse_aim(key[4:])
        return True
    if key.startswith("cal:"):   # calibrating one head by raw pan/tilt (1.12.1); "cal:" = done
        parts = key[4:].split(":")
        try:
            bar, m, pan, tilt = int(parts[0]), int(parts[1]), float(parts[2]), float(parts[3])
            ok = bar in (1, 2) and m in (0, 1) and 0.0 <= pan <= 1.0 and 0.0 <= tilt <= 1.0
        except (ValueError, IndexError):
            ok = False
        ov.raw_head = (bar, m, pan, tilt) if ok else None
        return True
    if key == "q":
        return False
    if key == "b":
        ov.blackout = not ov.blackout
    elif key == "s":
        ov.strobe = not ov.strobe
    elif key in (" ", "t"):   # T in the window, where Space pauses the song it plays (1.7.0)
        show.tap_tempo()
    elif key == "a":
        ov.autoloop_override = not ov.autoloop_override
    elif key in "np":
        ov.loop_shift += 1 if key == "n" else -1
    elif key == "h":
        ov.hold_loop = not ov.hold_loop
    elif key == "c":
        ov.color_hold = HOLD_HUES[(HOLD_HUES.index(ov.color_hold) + 1) % len(HOLD_HUES)]
    elif key in "+=":
        ov.master = min(1.0, ov.master + 0.1)
    elif key in "-_":
        ov.master = max(0.0, ov.master - 0.1)
    elif key == "[":
        show.offset_ms += 5
    elif key == "]":
        show.offset_ms -= 5
    elif key == "0":   # back to the music's own timing (1.11.4, his 2:40 PM recording 0:29)
        show.offset_ms = 0.0
    return True


# --- virtual rig ------------------------------------------------------------------------

def _swatch(r: int, g: int, b: int, dim: int, label: str) -> str:
    k = dim / 255
    return f"\x1b[48;2;{int(r * k)};{int(g * k)};{int(b * k)}m {label} \x1b[0m"


def virtual_rig(universe: bytes) -> str:
    """One terminal line showing what each light is doing."""
    u = universe
    parts = []
    for base, name in ((0, "G1"), (40, "G2")):
        r, g, b, _uv, shutter = u[base:base + 5]
        dim = 255 if shutter >= 128 else shutter * 2
        heads = f"{u[base + 23]:3d}/{u[base + 24]:3d}"
        strobe = "*" if u[base + 20] else " "
        parts.append(_swatch(r, g, b, dim, f"{name}{strobe}{heads}"))
    for i in range(6):
        a = 80 + 10 * i
        r, g, b, amber, dim, strobe = u[a:a + 6]
        parts.append(_swatch(min(255, r + amber), min(255, g + amber // 2), b, dim, "T*" if strobe else "T "))
    for i in range(4):
        a = 150 + 10 * i
        dim, r, g, b = u[a:a + 4]
        parts.append(_swatch(r, g, b, dim, "S"))
    return "".join(parts)


# --- commands ---------------------------------------------------------------------------

class NoKeys:
    """Stands in for Keys when there is no console (the Windows app's show thread)."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def read(self) -> None:
        return None


def park(show: Show, output, hz: int = 40, clock=time.perf_counter, sleep=time.sleep) -> int:
    """Glide every head home before the rig goes dark (1.16.0, glide.py): frames at the output rate
    until the heads are home or PARK_MAX_S passes. A show without a glide (tests' stand-ins) skips it.
    Returns the frames sent."""
    if not callable(getattr(show, "park", None)) or not hasattr(show, "glide"):
        return 0
    started, n = clock(), 0
    while clock() - started < glide.PARK_MAX_S:
        now = clock()
        try:
            output.send(show.park(now))
        except Exception:  # noqa: BLE001 -- ok: the box went away; stop parking, the final frame still tries
            break
        n += 1
        if show.glide.parked():
            break
        sleep(1.0 / hz)
    return n


def _run_loop(show: Show, output, seconds: float = 0.0, feed=None, view: bool = True,
              read_keys: bool = True) -> int:
    loop = OutputLoop(output, show.render)
    loop.start()
    started = time.perf_counter()
    last_status = 0.0
    try:
        with (Keys() if read_keys else NoKeys()) as keys:
            while True:
                now = time.perf_counter()
                if feed:
                    feed(now)
                show.control_tick(now)
                key = keys.read()
                if key and not handle_key(key, show):
                    break
                if view and now - last_status > 0.1:
                    last_status = now
                    universe = getattr(output, "last", None)
                    line = virtual_rig(universe) + "  " if universe else ""
                    print(f"\r{line}{show.status(now)}\x1b[K", end="", flush=True)
                if seconds and now - started > seconds:
                    break
                time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        loop.stop()
        show_settings.set_soft_now(False)   # the night's part of the evening ends with the Live show
        show_settings.set_still_now(False)
        show_settings.set_gentle_now(False)
        parked = park(show, output)
        try:
            # Leave the rig dark with every head where park left it (1.16.4: an all-zero frame here
            # threw each head from its rest to pan 0 at full motor speed, a full turn on his head 4).
            output.send(show.park(time.perf_counter()) if parked else bytes(512))
        except Exception:  # noqa: BLE001 -- ok: an unplugged box at Stop; there is nothing left to light
            pass
        output.close()
        print()
    if loop.errors:
        print(f"DMX send errors: {loop.errors}", file=sys.stderr)
        return 1
    return 0


def cmd_run(args) -> int:
    library = MixxxLibrary(args.db) if args.db else MixxxLibrary()
    if not library.available():
        print(f"Mixxx library not found at {library.path}; track names and sections are off.")
    show = Show(library, ScriptCache(default_cache_dir()), latency_ms=args.latency_ms,
                offset_ms=args.offset_ms, venue=_layout(args.layout))
    midi = MidiInput(show.on_midi, args.midi)
    print(f"Listening to Mixxx on '{midi.port_name}'.")
    output = _output(args)
    print(f"DMX out: {output.port}. Press q to quit.")
    try:
        return _run_loop(show, output)
    finally:
        midi.close()


def cmd_analyze(args) -> int:
    library = MixxxLibrary(args.db) if args.db else MixxxLibrary()
    if not library.available():
        print(f"Mixxx library not found at {library.path}", file=sys.stderr)
        return 1
    cache = ScriptCache(default_cache_dir())
    tracks = library.analyzable_tracks(args.limit)
    done = failed = skipped = 0
    for info in tracks:
        if not args.force and cache.get(info.track_id, info.location):
            skipped += 1
            continue
        try:
            script = analyze_track(info.location, info.grid)
        except Exception as e:  # noqa: BLE001 - report and keep going through the crate
            print(f"  failed: {info.label}: {e}")
            failed += 1
            continue
        if script is None:
            print(f"  too short to analyze: {info.label}")
            failed += 1
            continue
        cache.put(info.track_id, script)
        done += 1
        kinds = " ".join(f"{s.kind}@{s.start_beat // 4 + 1}" for s in script.sections)
        print(f"  {info.label}: {kinds}")
    print(f"Analyzed {done}, already done {skipped}, failed {failed}, of {len(tracks)} tracks.")
    return 1 if failed and not done else 0


DEMO_SCRIPT = ShowScript([
    Section("intro", 0, 32, 0.2), Section("build", 32, 64, 0.5), Section("drop", 64, 96, 0.9),
    Section("main", 96, 128, 0.85), Section("breakdown", 128, 160, 0.3),
    Section("build", 160, 192, 0.55), Section("drop", 192, 256, 0.95), Section("outro", 256, 288, 0.2),
])


class FakeMixxx:
    """Sends what the Mixxx mapping would: one tick per ~11.6 ms buffer, with delivery jitter."""

    def __init__(self, show: Show, bpm: float = 128.0, samplerate: int = 44100, seed: int = 1,
                 loop: bool = False):
        self.show, self.bpm, self.rate = show, bpm, samplerate
        # loop: the pretend song starts over at its end instead of stopping, so a scene or moment
        # picked with no music holds (BL #12093: after one 2:15 pass the lights fell into the
        # autoloops, a fast dancing look, while Photo mode still read as on).
        self.loop = loop
        self.rng = random.Random(seed)
        self.t0 = None
        self.next_tick = 0.0
        self.sent_meta = 0.0

    def __call__(self, now: float) -> None:
        if self.t0 is None:
            self.t0 = now
            duration = 288 * 60 / self.bpm
            self.show.on_midi(encode_track(1, self.rate, duration, self.bpm), now)
            self.show.on_midi(encode_audio(23.2), now)
            self.show.tracks[1] = DeckTrack(serial=1, script=DEMO_SCRIPT)
        song_s = 288 * 60 / self.bpm
        while self.next_tick <= now - self.t0:
            t = self.next_tick % song_s if self.loop else self.next_tick
            beats = t * self.bpm / 60
            section, _ = DEMO_SCRIPT.at(beats)
            level = 0.15 + 0.7 * (section.energy if section else 0.2) + 0.1 * math.exp(-4 * (beats % 1))
            pos = int(t * self.rate)
            self.show.on_midi(encode_tick(1, True, True, self.bpm, beats % 1, pos, 0.9, level),
                              self.t0 + t + self.rng.uniform(0, 0.006))
            self.next_tick += 512 / self.rate


def _layout(name):
    store = LayoutStore()
    lay = store.get(name) if name else store.current()
    if lay is None:
        raise SystemExit(f"No layout named {name!r}. Known: {', '.join(store.all())}")
    print(f"Room layout: {lay.label}")
    return lay


def cmd_sim(args) -> int:
    show = Show(analyze=False, venue=_layout(args.layout))
    feed = FakeMixxx(show, args.bpm)
    print("Simulated Mixxx at %.0f BPM through intro, build, drop, breakdown... q quits." % args.bpm)
    return _run_loop(show, NullOutput(), seconds=args.seconds, feed=feed)


def light_white(fx) -> None:
    """One fixture full white: a GigBAR's pars and heads, or a Tetra or stick."""
    if hasattr(fx, "pars"):
        for p in fx.pars:
            p.red = p.green = p.blue = p.dim = 1.0
        for m in fx.movers:
            m.dim = 1.0
    else:
        fx.red = fx.green = fx.blue = fx.dim = 1.0


def _output(args):
    """The run's DMX out: none on --dry-run, --output's (dmx_outputs.parse) when given, else the ENTTEC Pro."""
    if args.dry_run:
        return NullOutput()
    spec = getattr(args, "output", None)   # already a dmx_outputs.OutputSpec (argparse type=_output_spec)
    if spec is not None:
        return spec.open(spec.find() if spec.network else spec.target or args.port)
    return EnttecPro(args.port)


def _output_spec(text: str):
    """--output, checked before the show starts: a bad one is a usage error, not a traceback."""
    from . import dmx_outputs  # noqa: PLC0415
    try:
        return dmx_outputs.parse(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


def cmd_test_lights(args) -> int:
    output = _output(args)
    rig = default_rig()
    try:
        for fx in rig.fixtures:
            rig.reset()
            light_white(fx)
            print(f"{fx.name}: address {fx.address:03d} should be lit white now.")
            end = time.perf_counter() + args.seconds
            while time.perf_counter() < end:
                output.send(rig.render())
                time.sleep(0.025)
    finally:
        output.send(bytes(512))
        output.close()
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="gigbar_lights", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="live show")
    run.add_argument("--port", help="ENTTEC COM port (found automatically)")
    run.add_argument("--output", type=_output_spec, help="another DMX out: opendmx:COM4, artnet:192.168.1.50[:universe], "
                     "sacn[:universe[@host]] (default: the ENTTEC Pro)")
    run.add_argument("--midi", default=DEFAULT_PORT_HINT, help="loopMIDI port name to listen on")
    run.add_argument("--db", type=Path, help="mixxxdb.sqlite path (found automatically)")
    run.add_argument("--latency-ms", type=float, help="override Mixxx's reported output latency")
    run.add_argument("--offset-ms", type=float, default=0.0, help="lights earlier (+) or later (-)")
    run.add_argument("--dry-run", action="store_true", help="no DMX box; virtual rig only")
    run.add_argument("--layout", help="room layout name (default: the one in use)")
    an = sub.add_parser("analyze", help="work out song sections for the Mixxx library")
    an.add_argument("--db", type=Path)
    an.add_argument("--limit", type=int, default=0)
    an.add_argument("--force", action="store_true", help="re-analyze tracks already done")
    sim = sub.add_parser("sim", help="simulated Mixxx feed + virtual rig")
    sim.add_argument("--bpm", type=float, default=128.0)
    sim.add_argument("--seconds", type=float, default=0.0)
    sim.add_argument("--layout", help="room layout name (default: the one in use)")
    tl = sub.add_parser("test-lights", help="light each fixture in turn")
    tl.add_argument("--port")
    tl.add_argument("--output", type=_output_spec, help="as for run")
    tl.add_argument("--seconds", type=float, default=2.0)
    tl.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    return {"run": cmd_run, "analyze": cmd_analyze, "sim": cmd_sim, "test-lights": cmd_test_lights}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
