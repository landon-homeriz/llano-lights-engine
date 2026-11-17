"""The room's light as a phone can draw it (1.20.0, the Light studio, Llano PM #23195).

The laptop's Live screen draws the room from every DMX byte, with the layout's whole aiming model.
A phone has neither, so the laptop works the picture out for it: where each pool of light sits on
the floor plan, its color and how strong, and where each moving head's beam starts and lands. It is
made from the frame that was really sent (the truth, after every layer), a few hundred bytes, and
the one console (studio_console.js) draws it in the same style as the laptop's stage.

The bar, 2026-11-13: the approved drawing sets the look on both laptop and phone: the same
palette, glow and beam rendering.
"""
from __future__ import annotations

from typing import Optional

from .rig import HEAD_WHEEL, active_counts

# the moving heads' real color wheel by slot (rig.HEAD_WHEEL, checked on the units, BL #12147)
WHEEL = tuple(hx.lstrip("#") for _name, hx in HEAD_WHEEL)
BARS, TETRAS, STICKS = (0, 40), 80, 150   # where each kind starts in the universe (rig.default_rig)


def _hex(r: float, g: float, b: float) -> str:
    return "%02x%02x%02x" % tuple(max(0, min(255, int(round(v)))) for v in (r, g, b))


def _land(o: tuple, d: tuple, room: tuple, open_air: bool) -> tuple:
    """Where a ray from a head meets the floor, a wall or the ceiling (preview.html hitRoom)."""
    if open_air:
        t = -o[2] / d[2] if d[2] < -1e-6 else 25.0
        t = max(0.0, min(t, 25.0))
    else:
        t = 1e9
        for k in range(3):
            if d[k] > 1e-6:
                t = min(t, (room[k] - o[k]) / d[k])
            elif d[k] < -1e-6:
                t = min(t, (0 - o[k]) / d[k])
        t = max(0.0, min(t, 60.0))
    return o[0] + d[0] * t, o[1] + d[1] * t


def scene(universe: bytes, layout, counts=None) -> Optional[dict]:
    """{"pools": [[x, y, radius m, "rrggbb", strength 0..1]], "beams": [[x0, y0, x1, y1, "rrggbb", strength]],
    "bars": [[x0, y0, x1, y1]], "lamps": [[x, y, "t" | "s", "rrggbb", strength]]} in meters on the floor
    plan, or None when there is no layout or frame to read."""
    u = bytes(universe or b"")
    if layout is None or len(u) < 192:
        return None
    n = active_counts(counts)
    out = {"pools": [], "beams": [], "bars": [], "lamps": []}
    try:
        open_air = bool(getattr(layout, "open", False))
        for i in range(n["tetras"]):
            s = layout.spots.get(f"tetra{i + 1}")
            if s is None or s.out:
                continue
            a = TETRAS + 10 * i
            r, g, b, amber, dim = u[a:a + 5]
            col, k = _hex(r + amber, g + amber * 0.5, b), round(dim / 255, 2)
            out["lamps"].append([round(s.x, 2), round(s.y, 2), "t", col, k])
            if k > 0.02:
                out["pools"].append([round(s.x, 2), round(s.y, 2), 2.3, col, k])
        for i in range(n["sticks"]):
            s = layout.spots.get(f"stick{i + 1}")
            if s is None or s.out:
                continue
            a = STICKS + 10 * i
            dim, r, g, b = u[a:a + 4]
            col, k = _hex(r, g, b), round(dim / 255, 2)
            out["lamps"].append([round(s.x, 2), round(s.y, 2), "s", col, k])
            if k > 0.02:
                out["pools"].append([round(s.x, 2), round(s.y, 2), 1.6, col, k])
        for bi in range(n["bars"]):
            bar, base = bi + 1, BARS[bi]
            s = layout.spots.get(f"bar{bar}")
            if s is None or s.out:
                continue
            heads = layout.heads(bar)
            out["bars"].append([round(v, 2) for v in (heads[0][0], heads[0][1], heads[1][0], heads[1][1])])
            for j, off in enumerate((0, 5)):   # Par R, Par L
                r, g, b, uv, sh = u[base + off:base + off + 5]
                k = sh / 127 if sh < 128 else 1.0
                if k > 0.02 and max(r, g, b, uv) > 0:
                    hx, hy = heads[j][0], heads[j][1]
                    out["pools"].append([round((hx + s.x) / 2, 2), round((hy + s.y) / 2 + 0.5, 2), 1.9,
                                         _hex(r + uv * 0.5, g, b + uv), round(min(1.0, k), 2)])
            if u[base + 19] >= 10 and (u[base + 20] or u[base + 21]):   # the 4 strobes
                white = u[base + 20] > 0
                out["pools"].append([round(s.x, 2), round(s.y + 0.4, 2), 3.2, "ffffff" if white else "963cff",
                                     round((u[base + 20] if white else u[base + 21]) / 255 * 0.8, 2)])
            for m, off in enumerate((23, 29)):
                pan, tilt, dim, _strobe, colv = u[base + off:base + off + 5]
                if dim <= 0:
                    continue
                o = heads[m]
                x1, y1 = _land(o, layout.beam(bar, o, pan / 255, tilt / 255, m), layout.room, open_air)
                out["beams"].append([round(o[0], 2), round(o[1], 2), round(x1, 2), round(y1, 2),
                                     WHEEL[max(0, min(7, (colv - 4) // 32))], round(dim / 255, 2)])
    except Exception:  # noqa: BLE001 -- ok: a layout that can't say draws the plan with no light on it
        return None
    return out
