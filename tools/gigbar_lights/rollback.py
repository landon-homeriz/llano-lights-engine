"""Go back to the stable copy from outside the app (1.14.0): the launcher's program.

"Llano Lights - go back to stable.cmd" (Start menu, and beside the install) runs this with the
STABLE copy's own Python and code (<install>.stable), so it works when the test build won't open
or crashes at start. It closes anything still running from the install, stages the same swap the
app uses (updater.stage_rollback) and exits at once, so the stable folder is free to be renamed
into place; the swap then starts the stable copy. No internet needed.

    <install>.stable\\runtime\\python.exe -m tools.gigbar_lights.rollback "<install>"
"""
from __future__ import annotations

import sys
from pathlib import Path

from . import updater


def main(argv: list[str]) -> int:
    here = updater.install_root()   # the stable copy this runs from
    root = Path(argv[0]) if argv else Path(str(here).removesuffix(".stable"))
    if updater.stable_path(root).resolve() != here.resolve():
        print(f"Run this from the stable copy beside {root} (it is at {updater.stable_path(root)}).")
        return 2
    print("Closing Llano Lights and putting the stable copy back...")
    updater.stop_copy(root)
    try:
        updater.launch_swap(updater.stage_rollback(root))
    except updater.UpdateError as e:
        print(f"Couldn't go back: {e}")
        return 1
    print("The stable copy opens in its own window in a few seconds.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
