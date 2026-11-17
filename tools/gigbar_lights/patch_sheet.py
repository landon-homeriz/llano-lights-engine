"""The patch: which light is which by its DMX address (Llano BL #12378).

The report, 2026-11-15, setting up for a wedding: there was no way to tell which light is which
by its DMX address, so no way to know where to place each light; the light's number showed but not
its address.

Every light's start address and channel mode come from the rig block in force (settings `rig`, synced
from llano.app, the same numbers rig.render sends to), never from a copy typed into a page. Where it
stands comes from the layout in use (venue.Layout.measurements, the tape measurements from the DJ
booth's center). The room picture, Line up my lights, the Set up screen, the printable patch sheet
(/patch.html) and the printed run sheet all read these rows, so they can never disagree.
"""
from __future__ import annotations

import html
from typing import Optional

from .rig import active_counts
from .settings_contract import CHANNEL_NAMES, FIXTURES

# The fixture each kind is, as printed on its own label, and its name in the app.
MODELS = {"gigbar": "Chauvet GigBAR Move", "tetra": "Venue Tetra 6", "stick": "Chauvet Freedom Stick"}
SHORT = {"gigbar": "GigBAR", "tetra": "Tetra", "stick": "Stick"}
COUNT_KEY = {"gigbar": "bars", "tetra": "tetras", "stick": "sticks"}
FT = 0.3048


def addr3(a: int) -> str:
    """An address the way a fixture's display shows it: three digits ("081")."""
    return f"{int(a):03d}"


def _feet(m: float) -> str:
    inches = int(round(abs(m) / 0.0254))
    if inches < 12:
        return f"{inches} in"
    ft, inch = divmod(inches, 12)
    return f"{ft} ft" + (f" {inch} in" if inch else "")


def where_words(m: dict, kind: str) -> str:
    """Where a light stands, in his tape-measure terms: left or right of the DJ booth's center as the
    room picture draws it, then how far in front of that center (toward the dance floor) or behind it,
    and how high, for a GigBAR. The Set up screen, the room picture and the patch sheet all print these
    words. "in front of" and "behind" the booth's center replace "2 ft 11 in out" and "3 ft behind it"
    (his 11-15 QA: two words for one kind of distance, and "out" didn't say out of what)."""
    r = m.get("right", 0.0)
    side = "in line with the DJ booth's center" if abs(r) < 0.05 else \
        f"{_feet(r)} {'right' if r > 0 else 'left'} of the DJ booth's center"
    o = m.get("out", 0.0)
    out = ", level with the booth's center" if abs(o) < 0.05 else \
        f", {_feet(o)} {'in front of' if o > 0 else 'behind'} the booth's center"
    up = f", {_feet(m['height'])} up" if kind == "gigbar" and m.get("height") else ""
    return side + out + up


def rows(rig: dict, layout=None) -> list[dict]:
    """One row per light in address order: its number on the sheet, the app's name for it, the model,
    the start address and the last channel it uses, its channel mode, whether it is set up tonight
    (rig.counts), and where it stands in the layout in use (None without a layout)."""
    rig = rig if isinstance(rig, dict) else {}
    addresses = rig.get("addresses") or {}
    channels = rig.get("channels") or {}
    counts = active_counts(rig.get("counts"))
    spots = {}
    if layout is not None:
        try:
            spots = {m["id"]: m for m in layout.measurements()}
        except Exception:  # noqa: BLE001 -- ok: a layout missing a light only loses the where column
            spots = {}
    out, seen = [], {}
    for n, (fid, kind) in enumerate(FIXTURES.items(), start=1):
        seen[kind] = seen.get(kind, 0) + 1
        k = seen[kind]
        start = addresses.get(fid)
        width = len(channels.get(kind) or CHANNEL_NAMES[kind])
        m = spots.get(fid)
        out.append({
            "n": n, "id": fid, "kind": kind, "name": f"{SHORT[kind]} {k}", "model": MODELS[kind],
            "address": start, "last": (start + width - 1) if isinstance(start, int) else None,
            "channels": width, "mode": f"{width}-channel",
            "present": k <= counts[COUNT_KEY[kind]] and not (m or {}).get("is_out", False),
            "where": where_words(m, kind) if m else None,
        })
    return out


def overlaps(rs: list[dict]) -> list[str]:
    """Two lights set up tonight whose channels overlap: each would also answer the other's channels."""
    on = sorted((r for r in rs if r["present"] and isinstance(r["address"], int)), key=lambda r: r["address"])
    return [f"{a['name']} (channels {addr3(a['address'])} to {addr3(a['last'])}) overlaps {b['name']} "
            f"(starts at {addr3(b['address'])})" for a, b in zip(on, on[1:]) if b["address"] <= a["last"]]


def label(r: dict) -> str:
    """One light on one line: "Tetra 3: address 101, 6-channel mode"."""
    return f"{r['name']}: address {addr3(r['address'])}, {r['mode']} mode"


_STYLE = """
.patch table{border-collapse:collapse;width:100%}
.patch td,.patch th{border:1px solid #bbb;padding:7px 9px;text-align:left;vertical-align:top}
.patch th{background:#eee}
.patch td.a{font:700 26px/1 ui-monospace,Consolas,monospace;white-space:nowrap}
.patch td.n{font-weight:700;width:34px;text-align:center}
.patch tr.off td{color:#888}
.patch tr{break-inside:avoid}
"""


def table_html(rs: list[dict]) -> str:
    """The patch as one table: number, light, address (big), mode, channels and where it stands."""
    e = html.escape
    has_where = any(r["where"] for r in rs)
    head = ("<tr><th>#</th><th>Light</th><th>Address</th><th>Mode</th><th>Uses channels</th>"
            + ("<th>Where it stands</th>" if has_where else "") + "</tr>")
    body = "".join(
        f"<tr class=\"{'' if r['present'] else 'off'}\"><td class=n>{r['n']}</td>"
        f"<td><b>{e(r['name'])}</b><br><small>{e(r['model'])}</small>"
        + ("" if r["present"] else "<br><small>not set up tonight</small>") + "</td>"
        f"<td class=a>{addr3(r['address']) if isinstance(r['address'], int) else '?'}</td>"
        f"<td>{e(r['mode'])}</td>"
        f"<td>{addr3(r['address']) + ' to ' + addr3(r['last']) if isinstance(r['address'], int) else ''}</td>"
        + (f"<td>{e(r['where'] or '')}</td>" if has_where else "") + "</tr>" for r in rs)
    return f"<table>{head}{body}</table>"


def sheet_html(rs: list[dict], layout_label: str = "", title: str = "") -> str:
    """The patch on one printable page: set each light's own display to its address and mode, then
    put it where the last column says. Overlapping addresses are named at the top."""
    e = html.escape
    clash = overlaps(rs)
    warn = "".join(f"<li>{e(c)}</li>" for c in clash)
    sub = f"Room layout: {e(layout_label)}. " if layout_label else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{e(title or 'Llano Lights')}: patch sheet</title>
<style>
body{{font:15px/1.4 system-ui,Segoe UI,Arial,sans-serif;margin:24px;color:#111;background:#fff}}
h1{{font-size:24px;margin:0 0 4px}} p{{margin:4px 0 10px;color:#333}} ul{{color:#b00020;font-weight:700}}
.p{{float:right;font:inherit;font-weight:700;padding:8px 16px;border:1px solid #111;border-radius:6px;background:#111;color:#fff;cursor:pointer}}
.b{{float:right;margin-right:10px;font:inherit;font-weight:700;padding:8px 16px;border:1px solid #111;border-radius:6px;color:#111;text-decoration:none}}
@media print{{body{{margin:10mm}} .p,.b{{display:none}}}}
{_STYLE}</style></head><body>
<button class=p type=button onclick="window.print()">Print this page</button>
<a class=b id=backlink href="/">Back to Llano Lights</a>
<script>if (new URLSearchParams(location.search).has("embed")) document.getElementById("backlink").remove();</script>
<h1>{e(title + ': which' if title else 'Which')} light is which</h1>
<p>{sub}On each light's own display, set the <b>address</b> and the <b>mode</b> in its row, then put it where the row
says. Left and right are as the room picture shows them, measured from the center of the DJ booth.</p>
{f'<ul>{warn}</ul>' if warn else ''}
<div class=patch>{table_html(rs)}</div>
</body></html>
"""
