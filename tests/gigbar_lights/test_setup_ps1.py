"""Setup.ps1 (1.2.2) run under PowerShell 7 with Windows' shortcut, process and registry calls stood in
(setup_harness.ps1): his PC with 1.1.0 still open, old copies removed, loud failures. Skips without pwsh."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


def find_setup():
    # LLANO_LIGHTS_SETUP_DIR = an unzipped build's Llano-Lights folder; else the repo's src/win
    env = os.environ.get("LLANO_LIGHTS_SETUP_DIR")
    for p in ([Path(env)] if env else []) + [HERE.parents[1] / "tools" / "gigbar_lights" / "windows" / "src" / "win"]:
        if (p / "setup.ps1").is_file():
            return p
    return None


@pytest.mark.skipif(not shutil.which("pwsh"), reason="PowerShell 7 (pwsh) not installed")
def test_setup_scenarios(tmp_path):
    setup = find_setup()
    assert setup, "setup.ps1 not found"
    r = subprocess.run(["pwsh", "-NoProfile", "-File", str(HERE / "setup_harness.ps1"), "-Setup", str(setup),
                        "-Work", str(tmp_path)], capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
    assert "0 failure(s)" in r.stdout
