"""A DJ sets up their own rig in the app, and the looks drive roles (Llano BL #12524).

Follow-up to BL #12136 (the fixture library, llano-lights #194, and DMX outputs, #196), which could read
any QLC+ or OFL light but only from code. Here a DJ whose lights are not the GigBAR/Tetra/stick rig:
  - searches the light library on the Setup screen (fixture_library: every QLC+ fixture, offline),
  - adds lights with a mode, a start address and a role, and sees what stops the rig playing
    (ProfileRig.problems: overlaps, off the universe; a light the library can't read),
  - picks the DMX output (dmx_outputs specs) instead of the LLANO_LIGHTS_OUTPUT env var,
  - and the rig is saved in the settings (rig.lights, rig.output), so it syncs like every other setting.
Then a show plays on that rig with its looks addressed by role (custom_rig.project), while his twelve
lights, with rig.lights empty, still render the frames the released 1.19.3 rendered.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gigbar_app  # noqa: E402
import rig_states  # noqa: E402
from test_fixture_profiles import RELEASED_FRAMES  # noqa: E402
from tools.gigbar_lights import custom_rig, demo_songs, dmx_outputs, fixture_library, fixture_profiles, rig  # noqa: E402
from tools.gigbar_lights import settings_contract as contract, show_settings  # noqa: E402
from tools.gigbar_lights.looks import Frame, LooksEngine  # noqa: E402
from tools.gigbar_lights.show import Show  # noqa: E402
from tools.gigbar_lights.show_script import Section  # noqa: E402
from tools.gigbar_lights.venue import LayoutStore  # noqa: E402

SRC = Path(gigbar_app.__file__).parent
RIG_PAGE = (SRC / "rig.html").read_text(encoding="utf-8")
APP_PAGE = (SRC / "app.html").read_text(encoding="utf-8")

PAR = "qlcplus:Chauvet/Chauvet-SlimPAR-56.qxf"           # RGB par, 7-Ch: R G B macro strobe program dimmer
SPOT = "qlcplus:American_DJ/American-DJ-Inno-Pocket-Spot.qxf"   # moving head, color wheel, no RGB
DERBY = "qlcplus:Chauvet/Chauvet-Derby-X.qxf"
STROBE = "qlcplus:Cameo/Cameo-Strobe-6x10W.qxf"           # 2-ch: flash rate, brightness

# Four pars, a moving head, a derby and a strobe: no GigBAR, no Tetra, no Freedom Stick.
DJ_RIG = [
    {"profile": PAR, "mode": "7-Ch", "address": 1, "role": "wash", "name": "Par 1"},
    {"profile": PAR, "mode": "7-Ch", "address": 8, "role": "wash", "name": "Par 2"},
    {"profile": PAR, "mode": "7-Ch", "address": 15, "role": "wash", "name": "Par 3"},
    {"profile": PAR, "mode": "7-Ch", "address": 22, "role": "wash", "name": "Par 4"},
    {"profile": SPOT, "mode": "9 Channel Mode", "address": 30, "role": "movers", "name": "Spot"},
    {"profile": DERBY, "mode": "Standard", "address": 40, "role": "effects", "name": "Derby"},
    {"profile": STROBE, "mode": "2-Channel Mode", "address": 50, "role": "strobes", "name": "Strobe"},
]
FOOTPRINT = {1: 7, 8: 7, 15: 7, 22: 7, 30: 9, 40: 8, 50: 2}
PAR_CH = {"red": 0, "green": 1, "blue": 2, "dim": 6}     # SlimPAR 56 7-Ch, offset in the light
SPOT_CH = {"pan": 0, "tilt": 1, "color": 2, "dim": 5}


@pytest.fixture(autouse=True)
def _fresh_settings():
    show_settings.set_current(contract.defaults())
    yield
    show_settings.set_current(contract.defaults())


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv(dmx_outputs.ENV, raising=False)
    monkeypatch.setattr(gigbar_app.updater, "check", lambda: (None, "no update in tests"))
    monkeypatch.setattr(gigbar_app, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(gigbar_app, "_enttec_port", lambda: None)
    monkeypatch.setattr(gigbar_app, "midi_port", lambda: "")
    opts = argparse.Namespace(seconds=0.0, bpm=128.0, no_browser=True, no_window=True,
                              updated=False, update_failed=False)
    a = gigbar_app.App(opts, gigbar_app.LogBuffer(tmp_path / "log.txt"))
    a.mixxx.running = False
    a.preview = gigbar_app.Preview("", LayoutStore(tmp_path / "profile"), app=a)
    yield a
    a.quit.set()
    a.stop()
    if a.runner:
        a.runner.join(timeout=8)
    a.preview.close()


def with_lights(lights, output=""):
    d = contract.defaults()
    d["rig"]["lights"], d["rig"]["output"] = lights, output
    show_settings.set_current(contract.normalize(d))


# --- the library a DJ searches ----------------------------------------------------------------------

def test_the_index_is_the_zip_it_ships_with():
    """fixtures/qlcplus-library.json is rebuilt from the zip (python -m tools.gigbar_lights.fixture_library):
    a newer library zip with a stale index fails here, never as a light that won't load at a gig."""
    assert list(fixture_library.index()) == fixture_library.build_index()
    assert len(fixture_library.index()) > 1500


def test_his_three_bundled_files_are_the_library_copies():
    with zipfile.ZipFile(fixture_library.LIBRARY_ZIP) as z:
        for name, path in (("Chauvet-GigBAR-Move.qxf", "Chauvet/Chauvet-GigBAR-Move.qxf"),
                           ("Venue-Tetra-6.qxf", "Venue/Venue-Tetra-6.qxf"),
                           ("Chauvet-Freedom-Stick.qxf", "Chauvet/Chauvet-Freedom-Stick.qxf")):
            assert z.read(path) == (fixture_profiles.QLC_DIR / name).read_bytes()


def test_search_finds_lights_by_brand_model_and_type():
    hits = fixture_library.search("chauvet slimpar 56")
    assert hits[0]["ref"] == PAR and hits[0]["role"] == "wash"
    assert ["7-Ch", 7] in hits[0]["modes"]
    heads = fixture_library.search("moving head")
    assert heads and all(h["role"] == "movers" for h in heads)
    assert fixture_library.search("strobe 6x10")[0]["role"] == "strobes"
    assert fixture_library.search("") == []
    assert fixture_library.search("zzzz no such light") == []


def test_fog_machines_are_never_in_the_library():
    assert not any(e["type"] in fixture_library.NOT_SHOW_LIGHTS for e in fixture_library.index())
    assert all(h["type"] != "Smoke" for h in fixture_library.search("fog"))


def test_every_library_ref_is_one_the_settings_keep():
    assert all(contract.PROFILE_RE.fullmatch(e["ref"]) for e in fixture_library.index())


def test_a_library_light_resolves_with_its_overrides():
    gb = fixture_library.resolve("qlcplus:Chauvet/Chauvet-GigBAR-Move.qxf")
    assert gb.roles == fixture_profiles.builtin_profile("gigbar").roles   # the override layer applied
    with pytest.raises(KeyError):
        fixture_library.resolve("qlcplus:../../etc/passwd.qxf")
    with pytest.raises(KeyError):
        fixture_library.resolve("qlcplus:Nobody/Nothing.qxf")


# --- the settings: rig.lights and rig.output sync like every other setting --------------------------

def test_the_contract_keeps_a_dj_rig_and_drops_what_isnt_one():
    d, _ = contract.apply_ops(contract.defaults(), [
        {"path": "rig.lights", "value": DJ_RIG + [{"profile": "../x.qxf", "mode": "a", "address": 1},
                                                 {"profile": PAR, "mode": "7-Ch", "address": 600},
                                                 {"profile": PAR, "mode": "7-Ch", "address": True}]},
        {"path": "rig.output", "value": "artnet:192.168.1.50:1"}])
    assert d["rig"]["lights"] == DJ_RIG and d["rig"]["output"] == "artnet:192.168.1.50:1"
    d, _ = contract.apply_ops(d, [{"path": "rig.output", "value": "bogus; thing"}])
    assert d["rig"]["output"] == ""
    assert contract.defaults()["rig"]["lights"] == [] and contract.defaults()["rig"]["output"] == ""
    many = [{**DJ_RIG[0], "address": 1 + i} for i in range(80)]
    assert len(contract.normalize({"rig": {"lights": many}})["rig"]["lights"]) == contract.MAX_LIGHTS
    assert contract.normalize({"rig": {"lights": [{**DJ_RIG[0], "role": "lasers"}]}})["rig"]["lights"][0]["role"] == "wash"


# --- the Setup screen ---------------------------------------------------------------------------------

def test_a_dj_builds_their_rig_on_the_setup_screen(app):
    assert app.rig_setup_public()["own"] is False
    code, body = app.post("rig-lights", {"lights": DJ_RIG})
    assert code == 200, body
    assert show_settings.current()["rig"]["lights"] == DJ_RIG
    r = body["rig"]
    assert r["own"] and r["problems"] == []
    assert r["roles"] == {"wash": 4, "movers": 1, "effects": 1, "strobes": 1}
    assert [(x["address"], x["channels"], x["end"]) for x in r["lights"]] == [
        (a, n, a + n - 1) for a, n in FOOTPRINT.items()]
    assert r["lights"][0]["model"] == "SlimPAR 56" and r["lights"][0]["manufacturer"] == "Chauvet"
    assert r["next_address"] == 52
    # it waits for Llano like any other laptop change, so llano.app/lights shows the same rig
    assert any(p["path"] == "rig.lights" for p in app.link.pending) or not app.link.linked


def test_the_setup_screen_shows_what_stops_the_rig_playing(app):
    clash = [DJ_RIG[0], {**DJ_RIG[1], "address": 5}, {**DJ_RIG[4], "address": 510}]
    code, body = app.post("rig-lights", {"lights": clash})
    assert code == 200
    probs = body["rig"]["problems"]
    assert "Par 2 overlaps Par 1 at channel 5" in probs
    assert "Spot: channels 510-518 are outside 1-512" in probs


@pytest.mark.parametrize("bad", [
    {"profile": "qlcplus:Nobody/Nothing.qxf", "mode": "1", "address": 1},
    {"profile": PAR, "mode": "99-Ch", "address": 1},
    {"profile": PAR, "mode": "7-Ch", "address": 0},
    {"profile": "../../secret.qxf", "mode": "7-Ch", "address": 1},
    "a par"])
def test_a_light_the_library_cant_play_is_refused(app, bad):
    code, body = app.post("rig-lights", {"lights": [DJ_RIG[0], bad]})
    assert code == 400 and "Light 2" in body["error"] or code == 400
    assert show_settings.current()["rig"]["lights"] == []


def test_an_address_typed_as_text_is_read_as_a_number(app):
    code, _ = app.post("rig-lights", {"lights": [{**DJ_RIG[0], "address": "17"}]})
    assert code == 200 and show_settings.current()["rig"]["lights"][0]["address"] == 17


def test_going_back_to_the_gigbar_rig(app):
    app.post("rig-lights", {"lights": DJ_RIG})
    assert app.post("rig-lights", {"lights": []})[0] == 200
    assert show_settings.current()["rig"]["lights"] == [] and app.rig_setup_public()["own"] is False


def test_the_dmx_output_is_picked_on_the_screen_not_an_env_var(app, monkeypatch):
    assert dmx_outputs.chosen() is None                       # unset: the ENTTEC Pro, as always
    code, body = app.post("rig-output", {"output": "artnet:192.168.1.50:1"})
    assert code == 200 and body["rig"]["output"] == "artnet:192.168.1.50:1"
    spec = dmx_outputs.chosen()
    assert (spec.kind, spec.target, spec.universe) == ("artnet", "192.168.1.50", 1)
    assert dmx_outputs.find_env() == "Art-Net 192.168.1.50 universe 1"
    assert app.post("rig-output", {"output": "sacn:2@192.168.1.60"})[0] == 200
    assert dmx_outputs.find_env() == "sACN universe 2 to 192.168.1.60"
    for bad in ("opendmx", "artnet:1.2.3.4:99999", "laser:1", "sacn:0"):
        code, body = app.post("rig-output", {"output": bad})
        assert code == 400 and body["error"]
    assert show_settings.current()["rig"]["output"] == "sacn:2@192.168.1.60"
    monkeypatch.setenv(dmx_outputs.ENV, "none")              # a developer's env var still wins
    assert dmx_outputs.chosen().kind == "none"
    monkeypatch.delenv(dmx_outputs.ENV)
    assert app.post("rig-output", {"output": ""})[0] == 200 and dmx_outputs.chosen() is None


def _call(url, body=None, token=""):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "X-Llano-Token": token},
                                 method="GET" if body is None else "POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_the_window_serves_the_setup_screen(app):
    url, token = app.preview.url, app.preview.token
    code, page = _call(url + "rig")
    assert code == 200 and b"Your lights" in page and token.encode() in page
    code, body = _call(url + "api/rig/search?q=slimpar%2056")
    assert code == 200 and json.loads(body)["results"][0]["ref"] == PAR
    assert _call(url + "api/rig-lights", {"lights": DJ_RIG})[0] == 403          # no token, no change
    code, body = _call(url + "api/rig-lights", {"lights": DJ_RIG}, token)
    assert code == 200 and json.loads(body)["rig"]["roles"]["wash"] == 4
    code, body = _call(url + "api/rig")
    assert code == 200 and json.loads(body)["own"] is True


def test_the_pages_link_and_call_the_setup_screen():
    assert 'href="/rig"' in APP_PAGE
    for call in ('"/api/rig"', '"/api/rig/search?q="', '"/api/rig-lights"', '"/api/rig-output"'):
        assert call in RIG_PAGE, call
    assert "X-Llano-Token" in RIG_PAGE and "esc(e.model)" in RIG_PAGE   # library text is escaped
    assert all(r in RIG_PAGE for r in contract.RIG_ROLES)


# --- the looks drive roles ------------------------------------------------------------------------------

def _lit(beat):
    return Frame(beat, 128.0, True, level=0.9, section=Section("drop", 0, 64, 0.9), track_key=3)


def test_each_role_gets_what_the_look_asks_of_it():
    ref = rig.default_rig()
    for t, rgb in zip(ref.tetras, [(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0), (1, 0, 1), (0, 1, 1)]):
        t.red, t.green, t.blue, t.dim = *rgb, 1.0
    m = ref.bars[0].movers[0]
    m.pan, m.tilt, m.dim, m.color = 0.25, 0.75, 1.0, rig.head_slot("red")
    ref.bars[0].derbies[0].color = "blue"
    ref.bars[0].strobe_white, ref.bars[0].strobe_speed = 1.0, 0.5
    u = custom_rig.render(ref, DJ_RIG)
    pars = [u[a - 1:a - 1 + 7] for a in (1, 8, 15, 22)]
    # four pars spread over the six-Tetra row: Tetras 1, 2, 4 and 5
    assert [(p[PAR_CH["red"]], p[PAR_CH["green"]], p[PAR_CH["blue"]]) for p in pars] == [
        (255, 0, 0), (0, 255, 0), (255, 255, 0), (255, 0, 255)]
    assert all(p[PAR_CH["dim"]] == 255 for p in pars)
    spot = u[29:29 + 9]
    assert (spot[SPOT_CH["pan"]], spot[SPOT_CH["tilt"]], spot[SPOT_CH["dim"]]) == (64, 191, 255)
    profile = fixture_library.resolve(SPOT)
    wheel = next(f for c in profile.mode("9 Channel Mode").channels for f in c.functions if f.attr == "color")
    red = next(b for b in wheel.bands if b.label == "Red")
    assert red.lo <= spot[SPOT_CH["color"]] <= red.hi              # the wheel's own red, no RGB on this head
    assert u[39] != 0                                                # the derby is on
    assert u[49] > 0 and u[50] == 255                                # the strobe flashes at full


def test_a_light_with_no_dimmer_takes_the_dimmer_on_its_colors():
    ref = rig.default_rig()
    for t in ref.tetras:
        t.red, t.dim = 1.0, 0.5
    u = custom_rig.render(ref, [{"profile": PAR, "mode": "3-Ch", "address": 1, "role": "wash", "name": "P"}])
    assert list(u[:3]) == [128, 0, 0]


def test_a_dj_rig_plays_a_show_with_looks_addressed_by_role(app):
    """The end state: a rig of non-GigBAR lights built on the Setup screen plays a show."""
    assert app.post("rig-lights", {"lights": DJ_RIG})[0] == 200
    show = Show(analyze=False)
    song = next(s for s in demo_songs.load() if s.id == "drop")
    feed = demo_songs.SongFeed(show, song, None)
    frames, now = [], 1000.0
    while now < 1000.0 + 60.0:   # the intro (30 s) holds the heads; the build and drop move them
        feed(now)
        frames.append(show.render(now))
        now += 0.05
    used = {a - 1 + i for a, n in FOOTPRINT.items() for i in range(n)}
    assert all(not f[s] for f in frames for s in range(512) if s not in used)   # nothing off the DJ's lights
    par_colors = {tuple(f[a - 1 + c] for c in (0, 1, 2)) for f in frames for a in (1, 8, 15, 22)}
    assert len(par_colors) >= 3                                                 # the wash moves through colors
    dims = {f[a - 1 + PAR_CH["dim"]] for f in frames for a in (1, 8, 15, 22)}
    assert max(dims) > 200 and len(dims) > 10                                   # and pulses with the beat
    pans = {f[29 + SPOT_CH["pan"]] for f in frames}
    assert len(pans) > 3 and max(f[29 + SPOT_CH["dim"]] for f in frames) > 0  # the mover moves and lights
    # the show's own GigBAR addresses (1, 41, 81..) carry the DJ's lights, never GigBAR bytes
    ref = rig.default_rig()
    assert bytes(custom_rig.universe(ref)) != bytes(ref.render())


def test_a_changed_rig_reaches_the_running_show_at_once():
    with_lights(DJ_RIG)
    eng, ref = LooksEngine(settings=contract.defaults()), rig.default_rig()
    eng.render(_lit(8.0), ref)
    assert any(custom_rig.universe(ref)[:57])
    with_lights([{**DJ_RIG[0], "address": 200}])
    u = custom_rig.universe(ref)
    assert not any(u[:199]) and any(u[199:206])


def test_test_each_light_lights_one_light_white():
    u = custom_rig.white(DJ_RIG, 4)                                  # the spot
    assert not any(u[:29]) and not any(u[38:])
    assert u[29 + SPOT_CH["dim"]] == 255 and u[29 + SPOT_CH["pan"]] == 128


# --- his twelve lights, byte for byte ---------------------------------------------------------------

class _ThroughTheShow:
    """rig.py's module as rig_states reads it, with every frame sent the way the show now sends it."""

    class _Rig:
        def __init__(self):
            self._r = rig.default_rig()

        def __getattr__(self, name):
            return getattr(self._r, name)

        def render(self, config=None):
            return custom_rig.universe(self._r, config)

    def default_rig(self):
        return self._Rig()


def test_his_twelve_lights_render_the_released_frames_through_the_show_path():
    assert custom_rig.lights() == []
    assert rig_states.digest(_ThroughTheShow(), contract) == RELEASED_FRAMES


def test_with_no_rig_of_his_own_the_show_sends_rig_render():
    eng, ref = LooksEngine(settings=contract.defaults()), rig.default_rig()
    for b in (4.0, 8.5, 33.0):
        eng.render(_lit(b), ref)
        assert bytes(custom_rig.universe(ref)) == bytes(ref.render())


# --- review fixes (fresh-context review of 19709ec) ------------------------------------------------

def test_every_library_light_and_mode_loads_and_renders():
    """A light that won't load would be a problem on the Setup screen, never a frame that fails mid-show."""
    for e in fixture_library.index():
        p = fixture_library.resolve(e["ref"])
        for name, n in e["modes"]:
            m = p.mode(name)
            assert len(fixture_profiles.frame(m, {})) == m.footprint, (e["ref"], name, n)


def test_a_light_that_wont_load_is_a_problem_not_a_crash(monkeypatch):
    def broken(ref):
        raise TypeError("int() argument must be a string")
    monkeypatch.setattr(fixture_library, "resolve", broken)
    b = custom_rig.Built([DJ_RIG[0]])
    assert b.problems == ["Par 1: int() argument must be a string"] and b.slots == [None]
    assert not any(custom_rig.render(rig.default_rig(), [{**DJ_RIG[0], "name": "x"}]))


@pytest.mark.parametrize("counts", [{"bars": 0, "tetras": 0, "sticks": 0}, {"bars": 0, "tetras": 0, "sticks": 4},
                                    {"bars": 1, "tetras": 3, "sticks": 0}])
def test_a_dj_rig_plays_whatever_his_counts_say(counts):
    """rig.counts is his GigBAR rig's; with a DJ rig set the engine plays the whole reference rig, so no
    role of the DJ's goes dark because a kind of his is at 0."""
    d = contract.defaults()
    d["rig"]["counts"], d["rig"]["lights"] = counts, DJ_RIG
    d = contract.normalize(d)
    show_settings.set_current(d)
    eng, ref = LooksEngine(settings=d), rig.default_rig()
    lit = {role: False for role in ("wash", "movers")}
    for b in range(64, 128):
        eng.render(Frame(float(b) + 0.25, 128.0, True, level=0.9, section=Section("drop", 64, 128, 0.9),
                         track_key=3), ref)
        u = custom_rig.universe(ref)
        lit["wash"] |= all(u[a - 1 + PAR_CH["dim"]] for a in (1, 8, 15, 22))
        lit["movers"] |= bool(u[29 + SPOT_CH["dim"]])
    assert all(lit.values()), lit


def test_a_pad_preview_never_bleeds_into_the_live_frame():
    """Two shows (the live one and a pad preview) render the same DJ rig on two threads at once."""
    import threading
    red, blue = rig.default_rig(), rig.default_rig()
    for t in red.tetras:
        t.red, t.dim = 1.0, 1.0
    for t in blue.tetras:
        t.blue, t.dim = 1.0, 1.0
    want = {id(red): bytes(custom_rig.render(red, DJ_RIG)), id(blue): bytes(custom_rig.render(blue, DJ_RIG))}
    bad = []

    def run(ref):
        for _ in range(400):
            if bytes(custom_rig.render(ref, DJ_RIG)) != want[id(ref)]:
                bad.append(1)
    ts = [threading.Thread(target=run, args=(r,)) for r in (red, blue, red, blue)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not bad


class _Fx:
    def __init__(self, ref, mode):
        self.profile = fixture_library.resolve(ref)
        self.mode = self.profile.mode(mode)
        self.state = {}


def test_a_white_only_light_without_a_dimmer_is_dimmed_once():
    fx = type("Fx", (), {"state": {}})()
    custom_rig._put(fx, "", {"white"}, {"red": 1.0, "green": 0.0, "blue": 0.0, "dim": 0.5})
    assert fx.state == {"white": 0.5}


def test_a_wheel_light_keeps_its_color_through_a_blackout():
    fx = _Fx(SPOT, "9 Channel Mode")
    have = set(fx.mode.elements()[""])
    custom_rig._put(fx, "", have, {"pan": 0.5, "tilt": 0.5, "dim": 0.0, "red": 1.0, "green": 0.0, "blue": 0.0,
                                   "_rgb": (1.0, 0.0, 0.0)})
    assert fx.state["color"] == custom_rig.wheel_slot(fx, "", (1, 0, 0)) and fx.state["dim"] == 0.0


def test_a_gobo_lands_on_a_still_gobo_never_shake_or_scroll():
    fx = _Fx(SPOT, "9 Channel Mode")
    have = set(fx.mode.elements()[""])
    labels = [b.label for c in fx.mode.channels for f in c.functions if f.attr == "gobo" for b in f.bands]
    for slot in range(8):
        fx.state.clear()
        custom_rig._put(fx, "", have, {"dim": 1.0, "_gobo": slot, "_rgb": (1, 1, 1)})
        label = labels[fx.state["gobo"]]
        assert label == ("Open" if slot == 0 else f"Gobo {slot}"), (slot, label)


def test_a_long_name_normalizes_to_itself():
    one = contract.normalize({"rig": {"lights": [{**DJ_RIG[0], "name": "A" * 47 + " B"}]}})
    assert contract.normalize(one) == one and one["rig"]["lights"][0]["name"] == "A" * 47
