"""1.12.2: a saved crash report goes to Llano until Llano says it keeps it (Llano PM #22370).

The app sends a crash only during the run after it. The 1.5.0 report of 2026-11-07 (his 8:38
crash) reached Llano once, and the next clean launch dropped it before anyone read it. The app
now sends crash-report.txt again on later launches until Llano answers crash_kept.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"))
import gigbar_app  # noqa: E402

from test_live_screen import app  # noqa: E402,F401  (the running-app fixture)
from test_llano_sync import _until, llano  # noqa: E402,F401  (the fake Llano)

LINES = ["2026-11-07 22:07:24 Llano Lights 1.5.0 starting", "2026-11-07 22:07:25 Window server at x",
         "2026-11-08 08:38:01 --- Check my setup ---"]


def test_the_saved_report_reads_back_as_it_was_sent(tmp_path):
    sent = gigbar_app._report(tmp_path, "1.5.0", "2026-11-07 22:07:24", LINES, "Fatal Python error: x\n")
    assert gigbar_app.pending_crash(tmp_path) == sent


def test_once_llano_keeps_it_it_is_not_sent_again_until_a_new_crash(tmp_path):
    sent = gigbar_app._report(tmp_path, "1.5.0", "2026-11-07 22:07:24", LINES, "")
    gigbar_app.mark_crash_sent(tmp_path, sent)
    assert gigbar_app.pending_crash(tmp_path) is None
    gigbar_app._report(tmp_path, "1.12.2", "2026-11-09 20:00:00", ["later"], "")
    assert gigbar_app.pending_crash(tmp_path)["started"] == "2026-11-09 20:00:00"


def test_no_report_or_a_mangled_one_sends_nothing(tmp_path):
    assert gigbar_app.pending_crash(tmp_path) is None
    (tmp_path / "crash-report.txt").write_text("something else entirely\n\nlines")
    assert gigbar_app.pending_crash(tmp_path) is None
    (tmp_path / "crash-report.txt").write_bytes(b"\xff\xfe\x00garbage")
    assert gigbar_app.pending_crash(tmp_path) is None


def test_a_long_report_is_trimmed_to_what_llano_takes(tmp_path):
    gigbar_app._report(tmp_path, "1.5.0", "2026-11-07 22:07:24", [f"line {i} " + "x" * 200 for i in range(500)], "")
    rep = gigbar_app.pending_crash(tmp_path)
    assert rep["lines"][-1].startswith("line 499") and len(rep["lines"]) <= gigbar_app.CRASH_LINES


def test_only_llanos_crash_kept_marks_it_sent(app, tmp_path):
    app.crash = {"version": "1.5.0", "started": "2026-11-07 22:07:24", "lines": ["a"], "fault": ""}
    status = app._sync_status(False)
    app._status_sent(status, {"watch": False})                     # an older Llano that doesn't keep it
    assert not (tmp_path / gigbar_app.SENT_FLAG).exists()
    app._status_sent({"mode": ""}, {"crash_kept": True})           # a post without the crash
    assert not (tmp_path / gigbar_app.SENT_FLAG).exists()
    app._status_sent(status, {"watch": False, "crash_kept": True})
    assert (tmp_path / gigbar_app.SENT_FLAG).read_text() == "1.5.0 2026-11-07 22:07:24"


def test_the_link_hands_each_landed_status_and_reply_back(llano):
    link, fake, _ = llano
    got = []
    link.sent_fn = lambda status, reply: got.append((status, reply))
    link.link("ABCDE23456")
    link.start()
    assert _until(lambda: got)
    assert got[0][0]["mode"] == "demo" and got[0][1] == {"watch": False}


def test_a_launch_after_a_clean_run_sends_the_saved_report_without_a_banner():
    body = Path(gigbar_app.__file__).read_text()
    body = body[body.index("def gui(opts)"):body.index("def main(")]
    assert "resend = None if crash else pending_crash(base)" in body
    assert body.index("app.crash = resend") < body.index("if crash:")   # the banner is only for a new crash
