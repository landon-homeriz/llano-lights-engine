"""The night names Mixxx's two Auto DJ buttons the way Mixxx shows them, with a picture (Llano BL #11473).

A proof run in a freshly installed Mixxx 2.5.4 (llano-lights run 43688062579) found that Mixxx writes
neither "Enable Auto DJ" nor "Fade Now" anywhere: both are small icons at the top of the Auto DJ page,
the first a power symbol, the second two crossing lines whose tooltip reads "Trigger the transition to
the next track". He cannot find a button by a name it does not show, so the sheet says which button
and shows it. The same run: after (replace) the first row may still be the old song; a hold lasts an
hour; closing Mixxx while a deck plays asks "Exit Mixxx?" with No highlighted.
"""
import base64
import re

from tools.gigbar_lights import run_of_show as ros
from tools.gigbar_lights import setup_guide


def S(artist, title, secs=200):
    return {"artist": artist, "title": title, "secs": secs}


def _night():
    parts = {"cocktail": [S("A", "a"), S("A", "b")], "dinner": [S("B", "c"), S("B", "d")],
             "dancing": [S("C", "e"), S("C", "f")]}
    return ros.plan(parts, {"first-dance": S("R", "F")},
                    order=("cocktail", "entrance", "dinner", "first-dance", "dancing", "send-off"))


def _header(page: str) -> str:
    return page[:page.index("<table>")]


def _text(html_part: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html_part))


def test_the_header_names_the_first_and_second_button_and_the_tooltip():
    head = _text(_header(ros.sheet_html("C & M", _night())))
    assert "Click the first one, a power symbol: that is Enable Auto DJ, and it turns orange." in head
    assert "Fade Now is the second button in that row, with two crossing lines." in head
    assert "Mixxx does not write Fade Now on it; rest the mouse on it and it says Trigger the transition to the next track." in head
    assert "Shift + F11 may do the same on your laptop, but the click always works." in head
    assert "a row of small buttons with no words on them (picture below)" in head
    # Never the bare name without saying which button it is.
    assert "press Enable Auto DJ" not in head and "then click that first button." in head


def test_the_header_embeds_exactly_one_picture_with_its_caption():
    page = ros.sheet_html("C & M", _night())
    imgs = re.findall(r"<img\b[^>]*>", page)
    assert len(imgs) == 1
    src = re.search(r'src="([^"]+)"', imgs[0]).group(1)
    assert src.startswith("data:image/png;base64,"), "embedded, so the printed sheet works offline"
    assert base64.b64decode(src.split(",", 1)[1]) == ros.BUTTONS_PICTURE.read_bytes()
    assert "<figcaption>1 is Enable Auto DJ. 2 is Fade Now.</figcaption>" in page
    assert 'alt="' in imgs[0]
    head = _header(page)
    # The picture sits after the Fade Now paragraph and before the count line, in the brief's order.
    i = [head.index(t) for t in ("To start the night:", "What a HOLD is:", "is the second button in that row",
                                 "<figure>", "Tonight you press Fade Now", "may still be the song Mixxx had lined up",
                                 "If anything goes wrong:")]
    assert i == sorted(i)


def test_the_header_says_a_hold_waits_up_to_an_hour_and_explains_the_leftover_row():
    head = _text(_header(ros.sheet_html("C & M", _night())))
    assert "It waits until you press Fade Now. It waits up to an hour." in head
    assert ("After you choose Add to Auto DJ Queue (replace), the first row of the list may still be the song Mixxx "
            "had lined up. That is fine: Fade Now goes to the new playlist.") in head
    assert "will not move on by itself" not in ros.sheet_html("C & M", _night())


def test_rows_keep_the_short_press_line():
    rows = ros.sheet_rows(_night())
    holds = [r for r in rows if r["detail"] == ros.HOLD_DETAIL]
    assert holds and all(r["next"].startswith("When you are ready, press Fade Now in Mixxx") for r in holds[:-1])
    assert not any("crossing lines" in r["next"] or "second button" in r["next"] for r in rows)


def test_the_picture_file_is_small():
    assert ros.BUTTONS_PICTURE.is_file()
    assert ros.BUTTONS_PICTURE.stat().st_size < 60_000
    assert ros.BUTTONS_PICTURE.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_an_empty_night_still_renders_with_the_picture():
    page = ros.sheet_html("Empty", [])
    assert "Nothing is planned for tonight yet." in page and page.count("<img") == 1
    assert "<table>" in page


def test_no_picture_file_means_no_figure_not_a_crash(monkeypatch, tmp_path):
    monkeypatch.setattr(ros, "BUTTONS_PICTURE", tmp_path / "missing.png")
    ros._buttons_data_uri.cache_clear()
    try:
        page = ros.sheet_html("C & M", _night())
        assert "<img" not in page and "Click the first one, a power symbol" in page
    finally:
        ros._buttons_data_uri.cache_clear()


def test_the_setup_guide_says_click_yes_and_names_the_sec_box():
    steps = {s["key"]: s for s in setup_guide.steps({})}
    assert steps["built"]["do"].startswith(
        "Close Mixxx. If Mixxx asks whether to exit while a deck is playing, click Yes. In Shows")
    assert ("in Mixxx click Auto DJ in the list on the left, pick Full Track in the box at the top, and type 2 in "
            "the box beside it marked sec.") in steps["autodj"]["do"]


def test_the_header_has_no_dash_punctuation():
    head = _text(_header(ros.sheet_html("C & M", _night())))
    assert "—" not in head and "–" not in head and " -- " not in head
