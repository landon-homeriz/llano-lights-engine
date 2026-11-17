"""Render guide.html to the PDF that ships in the zip: python render.py (needs playwright + chromium)."""
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "out" / "Llano Lights - How to install.pdf"
OUT.parent.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    pg.goto((HERE / "guide.html").as_uri())
    pg.pdf(path=str(OUT), format="Letter", print_background=True, prefer_css_page_size=True)
    b.close()
print(OUT)
