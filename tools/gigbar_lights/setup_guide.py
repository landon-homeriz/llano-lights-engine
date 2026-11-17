"""The setup guide (1.21, Llano PM #23415): one numbered path from a fresh install to a built night.

The ask, 2026-11-13: a dedicated walkthrough all the way from the music to getting it in
the mix, telling the DJ what to do at each step. This is the in-app copy that checks each step itself.

It is a guide, not a second flow: every step sends him to the page that already does the work (Test
each light, Line up my lights, Music no lights, the seven Shows steps) and only reads back whether it
worked. What the app can sense it checks (the lights box, the loopMIDI port, beats from Mixxx, a
saved line-up, a show with songs, a built night, Mixxx's Auto DJ). What it can't sense, it asks: DMX
only goes out, so "every light came on" is his tap.

`steps(facts)` is pure: the window gathers the facts (App.guide_facts) and this turns them into the
list the page draws. ok is True (done), False (not yet) or None (can't tell here).
"""
from __future__ import annotations

from typing import Optional

# Shown in this order; `next` is the first step not done.
KEYS = ("app", "box", "lights", "lineup", "loopmidi", "beat", "music", "built", "autodj")
CONFIRMABLE = {"lights"}   # steps only he can see: the page shows a "Yes, it worked" button


def _step(key: str, title: str, do: str, ok: Optional[bool], worked: str, fix: str,
          action: str = "", action_label: str = "", detail: str = "") -> dict:
    return {"key": key, "title": title, "do": do, "ok": ok, "worked": worked, "fix": fix,
            "action": action, "action_label": action_label, "detail": detail,
            "confirm": key in CONFIRMABLE}


def steps(f: dict) -> list[dict]:
    """The guide's steps from what the window knows (see App.guide_facts for each key)."""
    night = f.get("night") or None
    autodj = f.get("autodj") or None
    shows_n = int(f.get("shows_with_songs") or 0)
    midi = f.get("midi")
    out = [
        _step("app", "Llano Lights is installed",
              "Nothing to do if this is green: Setup put the app and its Mixxx files in place.",
              bool(f.get("app_ok")) and bool(f.get("mapping")),
              "The app's files and the Mixxx mapping are in place.",
              "Download the newest Llano Lights zip and run its Setup again.",
              detail=str(f.get("app_detail") or "")),
        _step("box", "Plug in the USB lights box",
              "Close SoundSwitch if it is open, then plug the ENTTEC box's USB cable into this laptop.",
              bool(f.get("box")),
              f"The lights box is plugged in{(' on ' + str(f['box_port'])) if f.get('box_port') else ''}.",
              "Unplug the USB cable and plug it back in. Only one program can use the box, so close "
              "SoundSwitch. Everything else still works on screen without it.",
              action="check", action_label="Check again"),
        _step("lights", "Light every light once",
              "Set each light's own display to its address and mode from the patch sheet (Set up, Which light "
              "is which, or this laptop's /patch.html). Then press Test each light: each light should come on "
              "in turn, in the room and on screen.",
              True if f.get("lights_confirmed") else False,
              "You saw every light come on.",
              "A light that stays dark: check its power, that its display shows the address and mode on the "
              "patch sheet, and the cables into and out of it. "
              "If every light after one point is dark, swap the cable at that point.",
              action="run:test", action_label="Test each light"),
        _step("lineup", "Line up the moving heads",
              "Open Line up my lights, pick a spot, and nudge each head onto it. Do this once at each venue.",
              bool(f.get("lined_up")),
              "Your line-up is saved for this room layout.",
              "On the line-up page pick Middle of the floor. If the beams don't meet, press No, line them up "
              "one at a time, and nudge each head with the arrow keys.",
              action="page:/lineup.html", action_label="Line up my lights"),
        _step("loopmidi", "Add the Llano Mixxx port",
              "Install loopMIDI (free), open it, type Llano Mixxx in the New port-name box and click +.",
              None if midi is None else bool(midi),
              "loopMIDI has the Llano Mixxx port.",
              "Open loopMIDI (it sits by the clock). The port name must be exactly Llano Mixxx. Right-click "
              "its icon and tick Autostart so it is there every time.",
              action="link:https://www.tobias-erichsen.de/software/loopmidi.html", action_label="Get loopMIDI",
              detail="" if midi is not None else "This laptop couldn't list its MIDI ports."),
        _step("beat", "Hear Mixxx",
              "In Mixxx: Options, Preferences, Controllers, Llano Mixxx, Load Mapping Llano Light Link, tick "
              "Enabled, OK. Then press Listen to Mixxx here and play a track in Mixxx.",
              True if (f.get("heard_now") or f.get("heard_ever")) else False,
              "Beats are coming in from Mixxx: the lights follow your music.",
              "No beats yet. Check the mapping is Enabled in Mixxx, and that loopMIDI was open before Mixxx "
              "(close and reopen Mixxx if not). A track must be playing.",
              action="run:preview", action_label="Listen to Mixxx",
              detail="Listening now: play a track in Mixxx." if f.get("listening") and not f.get("heard_now") else ""),
        _step("music", "Put your songs in a show",
              "Your songs must be in a folder on this laptop first. From Google Drive: open the wedding folder in "
              "your browser, click the folder's name at the top, choose Download and wait for the zip. In "
              "Downloads, right click the zip, choose Extract All, then move the extracted folder into Music. "
              "Then press Open Shows, press New show, and under 1 Load the songs, on the A folder tab, press "
              "Browse, pick that folder, press Select Folder, then Add these songs. Wait for step 3 Listen to "
              "finish, then press Save show.",
              shows_n > 0,
              f"{shows_n} saved show{'s' if shows_n != 1 else ''} with songs.",
              "Shows walks you through it: Load, Moments, Listen, Mood, Review. If Browse does nothing, "
              "paste the folder's path and press Enter.",
              action="page:/shows", action_label="Open Shows"),
        _step("built", "Build the night and load it into Mixxx",
              "Close Mixxx. If Mixxx asks whether to exit while a deck is playing, click Yes. In Shows, at 6 Build the night, press Build the night and wait until it says it is "
              "done (about ten minutes for a full wedding). Then press Load Mixxx, right beside it. It puts the "
              "night's songs and numbered playlists into Mixxx, lines up playlist 1 in Auto DJ, and opens "
              "Mixxx. You do not import anything by hand.",
              bool(night),
              "A night is built" + (f" in {night['folder']}." if night and night.get("folder") else "."),
              "Build the night needs a saved show with songs (the step above). If it says a file is in use, "
              "close Mixxx and press it again. If Load Mixxx says it can't, it says why; the by-hand steps "
              "are on the Shows page under Build the night.",
              action="page:/shows", action_label="Open Shows"),
        _step("autodj", "Check Mixxx's Auto DJ",
              "Nothing to do if this is green: Load Mixxx already set Auto DJ to Full Track with 2 seconds. If "
              "it is not green: in Mixxx click Auto DJ in the list on the left, pick Full Track in the box at the "
              "top, and type 2 in the box beside it marked sec.",
              None if autodj is None else bool(autodj.get("ok")),
              "Mixxx's Auto DJ is set the way the built night expects.",
              _autodj_fix(autodj),
              action="check", action_label="Check again"),
    ]
    return out


def _autodj_fix(autodj: Optional[dict]) -> str:
    if not autodj:
        return "Open Mixxx once and close it, then check again."
    bad = [i.get("fix", "") for i in autodj.get("items") or [] if not i.get("ok")]
    return " ".join(b for b in bad if b) or "Open Mixxx once and close it, then check again."


def summary(items: list[dict]) -> dict:
    """{done, total, next}: next is the key of the first step not done ("" when all are)."""
    done = sum(1 for s in items if s["ok"] is True)
    nxt = next((s["key"] for s in items if s["ok"] is not True), "")
    return {"done": done, "total": len(items), "next": nxt, "complete": not nxt}


def lined_up(layout) -> bool:
    """A saved line-up: any GigBAR head with a center or a confirmed spot in this layout."""
    for bar in (1, 2):
        sp = (getattr(layout, "spots", None) or {}).get(f"bar{bar}")
        for c in getattr(sp, "cal", None) or ():
            if getattr(c, "center", None) or getattr(c, "anchors", None):
                return True
    return False
