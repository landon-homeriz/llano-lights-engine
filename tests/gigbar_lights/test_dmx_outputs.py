"""DMX out behind one seam (Llano BL #12136): Art-Net, sACN and FTDI Open DMX beside the ENTTEC Pro.

Packet layouts are checked byte by byte against the specs (Art-Net 4 ArtDmx; ANSI E1.31-2018 data
packet), the network outputs really send over UDP to a socket on this machine, and Open DMX's break
timing runs against a stand-in serial port. Nothing here needs a box plugged in.
"""
import logging
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tools.gigbar_lights import dmx_outputs as dx
from tools.gigbar_lights.enttec import NullOutput, PluggableOutput


def _listener():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    s.settimeout(2.0)
    return s, s.getsockname()[1]


# --- Art-Net --------------------------------------------------------------------------------------

def test_artdmx_packet_layout():
    universe = bytes(range(1, 11))                         # 10 slots
    p = dx.artdmx_packet(universe, port_address=0x1234, sequence=7, physical=1)
    assert p[:8] == b"Art-Net\x00"
    assert p[8:10] == b"\x00\x50"                          # OpOutput / ArtDmx 0x5000, low byte first
    assert p[10:12] == b"\x00\x0e"                         # protocol 14, high byte first
    assert (p[12], p[13]) == (7, 1)                        # sequence, physical
    assert (p[14], p[15]) == (0x34, 0x12)                  # SubUni, Net
    assert p[16:18] == b"\x00\x0a"                         # length, high byte first
    assert p[18:] == universe and len(p) == 28


def test_artdmx_length_is_even_and_capped():
    assert dx.artdmx_packet(b"\x01\x02\x03")[16:] == b"\x00\x04\x01\x02\x03\x00"
    assert dx.artdmx_packet(b"")[16:] == b"\x00\x02\x00\x00"
    assert len(dx.artdmx_packet(bytes(600))) == 18 + 512
    with pytest.raises(ValueError, match="0-32767"):
        dx.artdmx_packet(b"", port_address=0x8000)


def test_artnet_output_sends_frames_with_a_rolling_sequence():
    rx, port = _listener()
    out = dx.ArtNetOutput("127.0.0.1", port_address=3, udp_port=port)
    try:
        out._seq = 253
        frames = [bytes([i]) * 192 for i in (1, 2, 3)]
        for f in frames:
            out.send(f)
        got = [rx.recvfrom(2048)[0] for _ in frames]
    finally:
        out.close()
        rx.close()
    assert [g[12] for g in got] == [254, 255, 1]           # wraps past 255 to 1, never 0
    assert all(g[14] == 3 and g[18:] == f for g, f in zip(got, frames))
    assert out.port == "Art-Net 127.0.0.1 universe 3"


# --- sACN -----------------------------------------------------------------------------------------

def test_sacn_packet_layout_full_universe():
    cid = bytes(range(16))
    data = bytes((i * 7) & 0xFF for i in range(512))
    p = dx.sacn_packet(data, universe_number=258, sequence=9, cid=cid, source="Llano Lights", priority=120)
    assert len(p) == 638
    assert p[0:2] == b"\x00\x10" and p[2:4] == b"\x00\x00"      # preamble, postamble
    assert p[4:16] == b"ASC-E1.17\x00\x00\x00"
    assert struct.unpack(">H", p[16:18])[0] == 0x7000 | 622     # root flags + length
    assert struct.unpack(">I", p[18:22])[0] == 0x00000004       # VECTOR_ROOT_E131_DATA
    assert p[22:38] == cid
    assert struct.unpack(">H", p[38:40])[0] == 0x7000 | 600     # framing flags + length
    assert struct.unpack(">I", p[40:44])[0] == 0x00000002       # VECTOR_E131_DATA_PACKET
    assert p[44:108].rstrip(b"\x00") == b"Llano Lights" and len(p[44:108]) == 64
    assert p[108] == 120                                        # priority
    assert p[109:111] == b"\x00\x00"                            # synchronization address
    assert (p[111], p[112]) == (9, 0)                           # sequence, options
    assert struct.unpack(">H", p[113:115])[0] == 258            # universe
    assert struct.unpack(">H", p[115:117])[0] == 0x7000 | 523   # DMP flags + length
    assert (p[117], p[118]) == (0x02, 0xA1)                     # VECTOR_DMP_SET_PROPERTY, address/data type
    assert struct.unpack(">HHH", p[119:125]) == (0, 1, 513)     # first address, increment, count
    assert p[125] == 0 and p[126:] == data                      # start code, slots


def test_sacn_short_frame_lengths_and_termination():
    p = dx.sacn_packet(bytes(192), universe_number=1, terminated=True)
    assert len(p) == 126 + 192
    assert struct.unpack(">H", p[16:18])[0] & 0x0FFF == len(p) - 16
    assert struct.unpack(">H", p[38:40])[0] & 0x0FFF == len(p) - 38
    assert struct.unpack(">H", p[115:117])[0] & 0x0FFF == len(p) - 115
    assert p[112] == 0x40                                       # Stream_Terminated


def test_sacn_groups_and_bounds():
    assert dx.sacn_group(1) == "239.255.0.1"
    assert dx.sacn_group(256) == "239.255.1.0"
    assert dx.sacn_group(63999) == "239.255.249.255"
    for bad in (0, 64000):
        with pytest.raises(ValueError, match="1-63999"):
            dx.sacn_group(bad)
    with pytest.raises(ValueError, match="16 bytes"):
        dx.sacn_packet(b"", cid=b"short")


def test_sacn_cid_is_the_same_every_run():
    assert dx.default_cid() == dx.default_cid() and len(dx.default_cid()) == 16


def test_sacn_output_unicasts_and_says_goodbye_on_close():
    rx, port = _listener()
    out = dx.SacnOutput(universe=5, host="127.0.0.1", udp_port=port)
    try:
        out.send(bytes([200]) * 192)
        first = rx.recvfrom(2048)[0]
        out.close()
        bye = [rx.recvfrom(2048)[0] for _ in range(3)]
    finally:
        rx.close()
    assert struct.unpack(">H", first[113:115])[0] == 5 and first[126:] == bytes([200]) * 192
    assert [b[112] for b in bye] == [0x40] * 3                  # three terminated packets
    assert [b[111] for b in bye] == [2, 3, 4]                   # the sequence carries on
    assert all(b[126:] == first[126:] for b in bye)            # with the last look, as E1.31 asks


def test_sacn_multicast_by_default():
    out = dx.SacnOutput(universe=2)
    try:
        assert out.host == "239.255.0.2" and out.port == "sACN universe 2"
    finally:
        out.close()


# --- Open DMX -------------------------------------------------------------------------------------

class _FakeSerial:
    def __init__(self, port, **kw):
        self.port, self.kw, self.calls, self._brk = port, kw, [], False

    @property
    def break_condition(self):
        return self._brk

    @break_condition.setter
    def break_condition(self, v):
        self._brk = v
        self.calls.append(("break", v))

    def flush(self):
        self.calls.append(("flush",))

    def write(self, data):
        self.calls.append(("write", bytes(data)))

    def close(self):
        self.calls.append(("close",))


class _FakeSerialModule:
    Serial = _FakeSerial


def test_open_dmx_makes_its_own_break_and_mark():
    slept, now = [], [100.0]
    out = dx.OpenDmx("COM4", slots=32, serial_module=_FakeSerialModule, sleep=slept.append, clock=lambda: now[0])
    s = out._serial
    assert s.kw["baudrate"] == 250000 and (s.kw["bytesize"], s.kw["parity"], s.kw["stopbits"]) == (8, "N", 2)
    out.send(bytes([9]) * 40)
    assert s.calls == [("break", True), ("break", False), ("write", b"\x00" + bytes([9]) * 32)]
    assert slept == [dx.BREAK_S, dx.MAB_S] and dx.BREAK_S >= 92e-6 and dx.MAB_S >= 12e-6
    out.send(b"\x01")                                           # a short frame is padded to its slots
    assert s.calls[-1] == ("write", b"\x00\x01" + bytes(31))
    out.close()
    assert s.calls[-1] == ("close",)
    assert ("flush",) not in s.calls                           # pyserial's flush polls 50 ms on Windows


def test_open_dmx_never_breaks_into_a_frame_still_on_the_wire():
    """The break waits out the last frame's wire time (44 us a slot at 250 kbaud) and no longer:
    a 193-byte frame is about 8.5 ms, so a 40 Hz loop (25 ms) never waits at all."""
    slept, now = [], [0.0]
    out = dx.OpenDmx("COM4", serial_module=_FakeSerialModule, sleep=slept.append, clock=lambda: now[0])
    assert out.slots == 192                                    # the rig's slots, like the ENTTEC path
    out.send(bytes(512))
    wire = 193 * 11 / 250000 + dx.DRAIN_S
    now[0] = 0.002                                             # the next frame comes too soon
    slept.clear()
    out.send(bytes(512))
    assert slept[0] == pytest.approx(wire - 0.002) and slept[1:] == [dx.BREAK_S, dx.MAB_S]
    now[0] += 0.025                                            # a 40 Hz frame later: no wait
    slept.clear()
    out.send(bytes(512))
    assert slept == [dx.BREAK_S, dx.MAB_S] and wire < 0.010


def test_open_dmx_needs_a_port_and_at_least_24_slots():
    with pytest.raises(RuntimeError, match="name its port"):
        dx.OpenDmx("", serial_module=_FakeSerialModule)
    assert dx.OpenDmx("COM4", slots=3, serial_module=_FakeSerialModule).slots == 24


# --- picking one ----------------------------------------------------------------------------------

@pytest.mark.parametrize("spec, want", [
    ("enttec", dx.OutputSpec("enttec")),
    ("enttec:COM3", dx.OutputSpec("enttec", "COM3")),
    (" ArtNet : 192.168.1.50 : 1 ", dx.OutputSpec("artnet", "192.168.1.50", 1)),
    ("artnet", dx.OutputSpec("artnet", "", 0)),
    ("artnet:2.0.0.10", dx.OutputSpec("artnet", "2.0.0.10", 0)),
    ("sacn", dx.OutputSpec("sacn", "", 1)),
    ("sacn:7", dx.OutputSpec("sacn", "", 7)),
    ("sacn:7@192.168.1.60", dx.OutputSpec("sacn", "192.168.1.60", 7)),
    ("opendmx:COM4", dx.OutputSpec("opendmx", "COM4")),
    ("opendmx:/dev/ttyUSB0", dx.OutputSpec("opendmx", "/dev/ttyUSB0")),
    ("none", dx.OutputSpec("none")),
    ("artnet:192.168.1.255:1%192.168.1.10", dx.OutputSpec("artnet", "192.168.1.255", 1, "192.168.1.10")),
    ("sacn:2%192.168.1.10", dx.OutputSpec("sacn", "", 2, "192.168.1.10")),
])
def test_specs_parse(spec, want):
    assert dx.parse(spec) == want


@pytest.mark.parametrize("spec, says", [
    ("", "unknown DMX output"), ("dmxking", "unknown DMX output"), ("opendmx", "needs its port"),
    ("artnet:host:x", "not a number"), ("artnet:host:40000", "0-32767"), ("sacn:0", "1-63999"),
    ("sacn:abc", "not a number"), ("none:COM3", "takes nothing"),
    ("opendmx:COM4%10.0.0.1", "only artnet and sacn"), ("sacn:1%wifi", "not an IPv4 address"),
])
def test_bad_specs_say_why(spec, says):
    with pytest.raises(ValueError, match=says):
        dx.parse(spec)


def test_unset_or_bad_env_keeps_the_enttec_path(monkeypatch, caplog):
    monkeypatch.delenv(dx.ENV, raising=False)
    assert dx.from_env() is None
    monkeypatch.setenv(dx.ENV, "dmxking:9")
    with caplog.at_level(logging.WARNING):
        assert dx.from_env() is None
    assert "ignored" in caplog.text
    found = []
    out = dx.pluggable(lambda: found.append(1) or None, retry_s=60)
    try:
        assert found and out.port == "none"                    # it looked with the ENTTEC finder
    finally:
        out.close()


def test_the_app_output_reaches_an_artnet_node(monkeypatch):
    """LLANO_LIGHTS_OUTPUT=artnet:...: the run's PluggableOutput opens Art-Net at once and frames go out."""
    rx, port = _listener()
    monkeypatch.setenv(dx.ENV, "artnet:127.0.0.1:2")
    monkeypatch.setattr(dx, "find_port", lambda: pytest.fail("looked for an ENTTEC"))
    real = dx.ArtNetOutput
    monkeypatch.setattr(dx, "ArtNetOutput", lambda host, pa, iface="": real(host, pa, udp_port=port, iface=iface))
    seen = []
    out = dx.pluggable(on_change=seen.append, retry_s=60)
    try:
        assert out.connected and seen == ["Art-Net 127.0.0.1 universe 2"]
        out.send(bytes([42]) * 192)
        pkt = rx.recvfrom(2048)[0]
    finally:
        out.close()
        rx.close()
    assert pkt[14] == 2 and pkt[18:] == bytes([42]) * 192


def test_specs_open_their_outputs():
    a = dx.parse("artnet:127.0.0.1:4").open("127.0.0.1")
    s = dx.parse("sacn:3@127.0.0.1").open("127.0.0.1")
    try:
        assert isinstance(a, dx.ArtNetOutput) and a.port_address == 4
        assert isinstance(s, dx.SacnOutput) and (s.universe, s.host) == (3, "127.0.0.1")
        assert isinstance(dx.parse("none").open(), NullOutput)
        assert dx.parse("none").find() is None
        assert dx.parse("artnet").find() == "Art-Net 255.255.255.255 universe 0"   # UDP: always "there"
        assert dx.parse("sacn:3@10.0.0.9").find() == "sACN universe 3 to 10.0.0.9"
    finally:
        a.close()
        s.close()


def test_a_dropped_network_reopens_by_itself(monkeypatch):
    """A send that keeps failing (the network went away) drops the output and PluggableOutput opens a
    fresh one, as it does for an unplugged box."""
    opened = []

    class Flaky:
        port = "Art-Net x"

        def __init__(self):
            opened.append(self)

        def send(self, u):
            raise OSError("network unreachable")

        def close(self):
            pass

    monkeypatch.setattr(PluggableOutput, "STALL_S", 0.0)
    out = PluggableOutput(finder=lambda: "artnet", opener=lambda _w: Flaky(), retry_s=0.05)
    try:
        out.send(b"\x00")
        out.send(b"\x00")                                      # stalled: dropped
        deadline = time.monotonic() + 2
        while len(opened) < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
    finally:
        out.close()
    assert len(opened) >= 2


# --- from the fresh review of PR #196 -------------------------------------------------------------

def test_a_host_name_is_looked_up_once_not_every_frame(monkeypatch):
    rx, port = _listener()
    looked = []
    real = socket.gethostbyname
    monkeypatch.setattr(socket, "gethostbyname", lambda h: looked.append(h) or real("127.0.0.1"))
    out = dx.ArtNetOutput("lights-node.local", udp_port=port)
    try:
        for _ in range(5):
            out.send(b"\x01\x02")
            rx.recvfrom(2048)
    finally:
        out.close()
        rx.close()
    assert looked == ["lights-node.local"] and out.port == "Art-Net lights-node.local universe 0"


def test_a_laptop_address_picks_the_network_packets_leave_by():
    rx, port = _listener()
    out = dx.ArtNetOutput("127.0.0.1", udp_port=port, iface="127.0.0.1")
    s = dx.SacnOutput(4, iface="127.0.0.1")
    try:
        out.send(b"\x05\x06")
        data, src = rx.recvfrom(2048)
        assert src[0] == "127.0.0.1" and out._sock.getsockname()[0] == "127.0.0.1"
        assert socket.inet_ntoa(s._sock.getsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, 4)) == "127.0.0.1"
    finally:
        out.close()
        s.close()
        rx.close()


def test_a_network_output_says_sending_never_plugged_in():
    assert dx.status("COM3") == "plugged in on COM3"
    assert dx.status("Art-Net 192.168.1.50 universe 0").startswith("sending to Art-Net 192.168.1.50")
    assert dx.status("sACN universe 2").startswith("sending to sACN universe 2")
    assert dx.status(None) == "not plugged in"


def test_the_apps_scan_dots_and_probe_follow_the_spec(monkeypatch):
    """The window's dots and a Llano probe read the same scan as a run: with LLANO_LIGHTS_OUTPUT set
    they open that output, never an ENTTEC (an Open DMX probed as an ENTTEC lights nothing)."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"))
    import gigbar_app
    monkeypatch.setenv(dx.ENV, "artnet:127.0.0.1:6")
    monkeypatch.setattr(dx, "find_port", lambda: pytest.fail("looked for an ENTTEC"))
    assert gigbar_app._enttec_port() == "Art-Net 127.0.0.1 universe 6"
    out = gigbar_app._open_enttec()
    try:
        assert isinstance(out, dx.ArtNetOutput) and out.port_address == 6
    finally:
        out.close()
    monkeypatch.setenv(dx.ENV, "opendmx:COM_NOT_HERE")
    assert gigbar_app._enttec_port() is None and gigbar_app._open_enttec() is None


def test_a_bad_output_is_a_usage_error_before_the_show():
    root = Path(__file__).resolve().parents[2]
    r = subprocess.run([sys.executable, "-m", "tools.gigbar_lights", "test-lights", "--output", "artnet:host:x"],
                       cwd=root, capture_output=True, text=True, timeout=60)
    assert r.returncode == 2 and "is not a number" in r.stderr and "Traceback" not in r.stderr
