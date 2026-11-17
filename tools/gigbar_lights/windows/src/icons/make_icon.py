"""Llano Lights icon: a light bar throwing three beams onto a dark tile, in the app's colours."""
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

BG_TOP, BG_BOT = (24, 27, 38), (7, 8, 11)
MINT = (124, 240, 200)
BEAMS = [((124, 240, 200), 0.0), ((255, 92, 178), -1.0), ((90, 150, 255), 1.0)]


def tile(n):
    """Rounded dark tile with a soft vertical gradient."""
    grad = Image.new("RGBA", (1, n))
    for y in range(n):
        t = y / (n - 1)
        grad.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOT)) + (255,))
    grad = grad.resize((n, n))
    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, n - 1, n - 1), radius=round(n * 0.22), fill=255)
    out = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    out.paste(grad, (0, 0), mask)
    return out, mask


def full(n=1024, beams=BEAMS, glow=True):
    img, mask = tile(n)
    ox, oy = n * 0.5, n * 0.24  # where the beams leave the bar
    floor = n * 0.86
    spread = n * 0.26
    half = n * 0.13
    layer = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    for color, side in beams:
        cx = ox + side * spread
        beam = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        d = ImageDraw.Draw(beam)
        d.polygon([(ox - n * 0.018, oy), (ox + n * 0.018, oy), (cx + half, floor), (cx - half, floor)],
                  fill=color + (150 if side else 205,))
        d.ellipse((cx - half, floor - n * 0.05, cx + half, floor + n * 0.05), fill=color + (235,))
        layer = Image.alpha_composite(layer, beam)
    if glow:
        layer = Image.alpha_composite(layer.filter(ImageFilter.GaussianBlur(n * 0.02)), layer)
    img = Image.alpha_composite(img, layer)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((n * 0.30, n * 0.16, n * 0.70, n * 0.25), radius=n * 0.04, fill=(232, 234, 240, 255))
    if glow:
        halo = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        ImageDraw.Draw(halo).ellipse((ox - n * 0.07, oy - n * 0.07, ox + n * 0.07, oy + n * 0.07), fill=MINT + (200,))
        img = Image.alpha_composite(img, halo.filter(ImageFilter.GaussianBlur(n * 0.03)))
    d = ImageDraw.Draw(img)
    d.ellipse((ox - n * 0.035, oy - n * 0.035, ox + n * 0.035, oy + n * 0.035), fill=MINT + (255,))
    a = ImageChops.multiply(img.getchannel("A"), mask)
    img.putalpha(a)
    return img


def small(n):
    """16 and 24 px: one bright beam reads; three turn to mush."""
    return full(512, beams=[BEAMS[0]], glow=False).resize((n, n), Image.LANCZOS)


def main(out_dir):
    out = Path(out_dir)
    big = full()
    sizes = {s: (small(s) if s <= 24 else big.resize((s, s), Image.LANCZOS)) for s in (16, 24, 32, 48, 64, 128, 256)}
    sizes[256].save(out / "llano-lights.ico", sizes=[(s, s) for s in sizes], append_images=[sizes[s] for s in sizes if s != 256])
    big.resize((512, 512), Image.LANCZOS).save(out / "icon-512.png")
    sizes[32].save(out / "icon-32.png")
    sizes[16].save(out / "icon-16.png")


if __name__ == "__main__":
    main(sys.argv[1])
