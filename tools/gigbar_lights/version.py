VERSION = "1.40.0"
# The Light studio Live screen is the front page for everyone from 1.20.0 (Llano PM #23195).
# LLANO_LIGHTS_STUDIO=0 on the laptop brings the classic window back as the front page.
STUDIO = True

# windows/build.py writes build_info.py beside this file in the shipped package, with the
# build time already in Central (the embeddable Python has no time zone data to convert it).
# A source checkout has no build_info.py, so it reads as a source copy.
try:
    from .build_info import BUILT_UTC, BUILT_CT
except ImportError:
    BUILT_UTC = BUILT_CT = ""
# A test-channel build (windows/build.py with LLANO_LIGHTS_CHANNEL=test) is VERSION.<build>, and
# build_info names its channel and number; it then updates itself from the test feed.
try:
    from .build_info import CHANNEL, BUILD
except ImportError:
    CHANNEL, BUILD = "stable", 0
if CHANNEL == "test" and BUILD:
    VERSION = f"{VERSION}.{BUILD}"


def label() -> str:
    """'1.1.1, built Nov 6, 2026, 2:40 PM CT' for the window and the log."""
    tag = f", test channel build {BUILD}" if CHANNEL == "test" else ""
    return f"{VERSION}{tag}, built {BUILT_CT}" if BUILT_CT else f"{VERSION}{tag} (source copy)"
