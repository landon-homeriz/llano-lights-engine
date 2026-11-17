"""DMX out behind one seam (Llano BL #12136, phase 1 of the Lights business plan).

Until now the show could only talk to an ENTTEC DMX USB Pro (enttec.py). Other DJs own other boxes,
so every output here is the same small shape, the one enttec.EnttecPro and NullOutput already have:

    .port            what it is talking to, for the status line ("COM3", "Art-Net 2.0.0.10 u0")
    .send(universe)  one frame, slot 1 first (up to 512 bytes)
    .close()

  enttec    ENTTEC DMX USB Pro (enttec.py, unchanged): the box times DMX itself.
  opendmx   An FTDI "Open DMX" class dongle (ENTTEC Open DMX USB and its many clones): a bare
            FT232R, so this side makes the DMX timing: a break, the mark after it, then the start
            code and slots at 250 kbaud, 8N2. Windows can stretch the break (that is allowed, up to
            a second); it can't shorten it.
  artnet    Art-Net 4 ArtDmx over UDP 6454, to a node's address (best) or a broadcast address.
  sacn      sACN (ANSI E1.31) over UDP 5568, multicast to the universe's group or unicast.

A network output can't tell whether anything hears it: UDP sends succeed with no node there. Its
status says "sending to", never "plugged in"; the address check (test-lights) is the proof. A
laptop with two networks (venue Wi-Fi plus a cable to the lights) names the cable's own address
after a '%' so broadcast and multicast leave the right way.
  none      Nothing (NullOutput).

Which one a run uses is a spec string: LLANO_LIGHTS_OUTPUT for the Windows app (pluggable()), or
--output for the command line. Unset, the app looks for the ENTTEC Pro exactly as before.

    enttec | enttec:COM3
    opendmx:COM4                        (an Open DMX is a bare FTDI chip: name its port)
    artnet | artnet:192.168.1.50 | artnet:192.168.1.50:1     (host, then Port-Address 0-32767)
    sacn | sacn:2 | sacn:2@192.168.1.60                      (universe 1-63999, then a unicast host)
    artnet:192.168.1.255%192.168.1.10, sacn:2%192.168.1.10   (send from this laptop address)
    none

Stdlib only, plus pyserial for the two USB boxes (already in the app).
"""
from __future__ import annotations

import logging
import os
import socket
import struct
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Optional

from .enttec import RIG_SLOTS, EnttecPro, NullOutput, PluggableOutput, find_port

_log = logging.getLogger(__name__)

UNIVERSE_SIZE = 512
ENV = "LLANO_LIGHTS_OUTPUT"
KINDS = ("enttec", "opendmx", "artnet", "sacn", "none")


# --- Art-Net ------------------------------------------------------------------------------------

ARTNET_PORT = 6454
ARTNET_BROADCAST = "255.255.255.255"
ARTNET_OP_DMX = 0x5000
ARTNET_PROTOCOL = 14


def _check_port_address(port_address: int) -> None:
    if isinstance(port_address, bool) or not isinstance(port_address, int) or not 0 <= port_address <= 0x7FFF:
        raise ValueError(f"Art-Net universe (Port-Address) {port_address!r} is outside 0-32767")


def _resolve(host: str) -> str:
    """A host name looked up once, when the output opens: never per frame on the 40 Hz thread."""
    return socket.gethostbyname(host)


def artdmx_packet(universe: bytes, port_address: int = 0, sequence: int = 0, physical: int = 0) -> bytes:
    """One ArtDmx packet (Art-Net 4): 'Art-Net', OpCode 0x5000 little-endian, protocol 14 big-endian,
    sequence, physical, Port-Address (SubUni then Net), length big-endian, the slots. The length is
    even and at least 2, as the spec asks, so an odd frame gets a 0 on the end."""
    _check_port_address(port_address)
    data = bytes(universe[:UNIVERSE_SIZE])
    if len(data) % 2:
        data += b"\x00"
    data = data.ljust(2, b"\x00")
    return (b"Art-Net\x00" + struct.pack("<H", ARTNET_OP_DMX) + struct.pack(">H", ARTNET_PROTOCOL)
            + bytes([sequence & 0xFF, physical & 0xFF]) + struct.pack("<H", port_address)
            + struct.pack(">H", len(data)) + data)


class ArtNetOutput:
    """Art-Net to one node (or everything on the network, by broadcast)."""

    def __init__(self, host: str = ARTNET_BROADCAST, port_address: int = 0, udp_port: int = ARTNET_PORT,
                 iface: str = "", sock: Optional[socket.socket] = None):
        _check_port_address(port_address)
        self.host, self.port_address, self.udp_port = host, port_address, udp_port
        self.addr = _resolve(host)
        self.port = f"Art-Net {host} universe {port_address}"
        self._sock = sock or socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        if iface:   # leave by the lights' network, not whichever one the laptop routes by default
            self._sock.bind((iface, 0))
        self._seq = 0

    def send(self, universe: bytes) -> None:
        self._seq = self._seq % 255 + 1   # 1..255; 0 would tell the node not to reorder
        self._sock.sendto(artdmx_packet(universe, self.port_address, self._seq), (self.addr, self.udp_port))

    def close(self) -> None:
        self._sock.close()


# --- sACN (E1.31) -------------------------------------------------------------------------------

SACN_PORT = 5568
SACN_ID = b"ASC-E1.17\x00\x00\x00"
SACN_PRIORITY = 100
SACN_TERMINATED = 0x40


def sacn_group(universe: int) -> str:
    """The multicast group a universe goes to: 239.255.<hi>.<lo>."""
    _check_sacn_universe(universe)
    return f"239.255.{universe >> 8}.{universe & 0xFF}"


def _check_sacn_universe(universe: int) -> None:
    if not 1 <= universe <= 63999:
        raise ValueError(f"sACN universe {universe} is outside 1-63999")


def default_cid() -> bytes:
    """This laptop's sACN source id: the same on every run, so receivers see one source, not one per
    restart (E1.31 asks for a CID that stays with the source)."""
    return uuid.uuid5(uuid.NAMESPACE_DNS, "llano-lights." + socket.gethostname()).bytes


def sacn_packet(universe: bytes, universe_number: int = 1, sequence: int = 0, cid: bytes = b"\x00" * 16,
                source: str = "Llano Lights", priority: int = SACN_PRIORITY, terminated: bool = False) -> bytes:
    """One E1.31 data packet: root layer (ACN id, vector 4, CID), framing layer (vector 2, source name,
    priority, sequence, options, universe), DMP layer (start code 0, then the slots)."""
    _check_sacn_universe(universe_number)
    if len(cid) != 16:
        raise ValueError("an sACN CID is 16 bytes")
    if not 0 <= priority <= 200:
        raise ValueError(f"sACN priority {priority} is outside 0-200")
    slots = bytes(universe[:UNIVERSE_SIZE])
    values = b"\x00" + slots                    # DMX start code, then the slots
    dmp = (struct.pack(">H", 0x7000 | (10 + len(values))) + bytes([0x02, 0xA1])
           + struct.pack(">HHH", 0, 1, len(values)) + values)
    name = source.encode("utf-8")[:63].ljust(64, b"\x00")
    framing_body = (struct.pack(">I", 0x00000002) + name + bytes([priority]) + struct.pack(">H", 0)
                    + bytes([sequence & 0xFF, SACN_TERMINATED if terminated else 0])
                    + struct.pack(">H", universe_number) + dmp)
    framing = struct.pack(">H", 0x7000 | (2 + len(framing_body))) + framing_body
    root_body = struct.pack(">I", 0x00000004) + cid + framing
    return (struct.pack(">HH", 0x0010, 0x0000) + SACN_ID
            + struct.pack(">H", 0x7000 | (2 + len(root_body))) + root_body)


class SacnOutput:
    """sACN to a universe's multicast group, or to one receiver (unicast)."""

    def __init__(self, universe: int = 1, host: str = "", udp_port: int = SACN_PORT, priority: int = SACN_PRIORITY,
                 cid: Optional[bytes] = None, iface: str = "", sock: Optional[socket.socket] = None):
        _check_sacn_universe(universe)
        self.universe, self.priority, self.udp_port = universe, priority, udp_port
        self.host = _resolve(host) if host else sacn_group(universe)
        self.cid = cid or default_cid()
        self.port = f"sACN universe {universe}" + (f" to {host}" if host else "")
        self._sock = sock or socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if not host:
            self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 8)
            if iface:   # the multicast leaves by the lights' network
                self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(iface))
        if iface:
            self._sock.bind((iface, 0))
        self._seq = 0
        self._last = b""

    def _packet(self, universe: bytes, terminated: bool = False) -> bytes:
        self._seq = (self._seq + 1) & 0xFF
        return sacn_packet(universe, self.universe, self._seq, self.cid, priority=self.priority,
                           terminated=terminated)

    def send(self, universe: bytes) -> None:
        self._last = bytes(universe)
        self._sock.sendto(self._packet(universe), (self.host, self.udp_port))

    def close(self) -> None:
        """Tells receivers this source is gone (three terminated packets, E1.31 6.2.6), so they let go
        at once instead of holding the last look for 2.5 s."""
        try:
            for _ in range(3):
                self._sock.sendto(self._packet(self._last, terminated=True), (self.host, self.udp_port))
        except OSError:
            pass   # the network went first; receivers time out by themselves
        finally:
            self._sock.close()


# --- FTDI Open DMX ------------------------------------------------------------------------------

OPEN_DMX_BAUD = 250000
BYTE_S = 11 / OPEN_DMX_BAUD   # start bit, 8 data bits, 2 stop bits: 44 us a slot on the wire
DRAIN_S = 0.001     # USB hand-off to the chip, on top of the frame's own wire time
BREAK_S = 0.0002    # DMX512 asks at least 92 us; Windows sleeps longer, which is allowed
MAB_S = 0.00002     # mark after break, at least 12 us


class OpenDmx:
    """A bare FTDI FT232R on the DMX line: each frame is a break, a mark, then start code + slots.

    The break must not start while the last frame is still leaving the chip, and pyserial's flush()
    can't say when that is (on Windows it polls every 50 ms and only knows the driver handed the
    bytes on), so the wait is the frame's own wire time: 44 us a slot at 250 kbaud. Short frames as
    on the ENTTEC (RIG_SLOTS, about 8.5 ms) keep 40 Hz with room to spare."""

    def __init__(self, port: str, slots: int = RIG_SLOTS, serial_module=None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.perf_counter):
        if serial_module is None:
            import serial as serial_module  # noqa: PLC0415 - optional hardware dependency
        if not port:
            raise RuntimeError("An Open DMX dongle is a bare FTDI chip: name its port (opendmx:COM4).")
        self.port, self.slots, self._sleep, self._clock = port, max(24, min(UNIVERSE_SIZE, slots)), sleep, clock
        self._serial = serial_module.Serial(port, baudrate=OPEN_DMX_BAUD, bytesize=8, parity="N",
                                            stopbits=2, timeout=0.1, write_timeout=0.5)
        self._busy_until = 0.0

    def send(self, universe: bytes) -> None:
        s = self._serial
        wait = self._busy_until - self._clock()
        if wait > 0:              # the last frame is still on the wire: a break now would cut its end
            self._sleep(wait)
        s.break_condition = True
        self._sleep(BREAK_S)
        s.break_condition = False
        self._sleep(MAB_S)
        frame = b"\x00" + bytes(universe[:self.slots]).ljust(self.slots, b"\x00")
        s.write(frame)
        self._busy_until = self._clock() + len(frame) * BYTE_S + DRAIN_S

    def close(self) -> None:
        self._serial.close()


def _port_present(port: str) -> Optional[str]:
    try:
        from serial.tools import list_ports  # noqa: PLC0415
        return port if any(p.device.lower() == port.lower() for p in list_ports.comports()) else None
    except Exception:  # noqa: BLE001 -- ok: the port list failed this time; the next look retries
        return None


# --- Picking one ------------------------------------------------------------------------------


@dataclass(frozen=True)
class OutputSpec:
    """Which output a run uses (parse() reads it from a spec string)."""
    kind: str
    target: str = ""       # a serial port, or a host
    universe: int = 0      # Art-Net Port-Address, or sACN universe
    iface: str = ""        # the laptop address network packets leave from ('%' in the spec)

    @property
    def network(self) -> bool:
        return self.kind in ("artnet", "sacn")

    def find(self) -> Optional[str]:
        """What PluggableOutput's finder returns: the port to open (None while it is absent), or for a
        network output what it sends to (always there: UDP can't tell whether a node listens)."""
        if self.kind == "enttec":
            return _port_present(self.target) if self.target else find_port()
        if self.kind == "opendmx":
            return _port_present(self.target)
        if self.kind == "artnet":
            return f"Art-Net {self.target or ARTNET_BROADCAST} universe {self.universe}"
        if self.kind == "sacn":
            return f"sACN universe {self.universe or 1}" + (f" to {self.target}" if self.target else "")
        return None

    def open(self, where: Optional[str] = None):
        """The output itself (PluggableOutput's opener; `where` is what find() returned)."""
        if self.kind == "enttec":
            return EnttecPro(where or self.target or None)
        if self.kind == "opendmx":
            return OpenDmx(self.target or where or "")
        if self.kind == "artnet":
            return ArtNetOutput(self.target or ARTNET_BROADCAST, self.universe, iface=self.iface)
        if self.kind == "sacn":
            return SacnOutput(self.universe or 1, self.target, iface=self.iface)
        return NullOutput()


def status(where: Optional[str]) -> str:
    """A status line for what find() returned: a box is plugged in; a network output only sends."""
    if not where:
        return "not plugged in"
    if where.startswith(("Art-Net ", "sACN ")):
        return f"sending to {where} (check the lights answer: test-lights)"
    return f"plugged in on {where}"


def parse(spec: str) -> OutputSpec:
    """'artnet:192.168.1.50:1' -> OutputSpec('artnet', '192.168.1.50', 1). ValueError says what is wrong."""
    s = (spec or "").strip()
    kind, _, rest = s.partition(":")
    kind = kind.strip().lower()
    rest, _, iface = rest.partition("%")
    rest, iface = rest.strip(), iface.strip()
    if iface:
        if kind not in ("artnet", "sacn"):
            raise ValueError("only artnet and sacn take a '%' laptop address")
        try:
            socket.inet_aton(iface)
        except OSError:
            raise ValueError(f"{iface!r} after '%' is not an IPv4 address of this laptop") from None
    if kind not in KINDS:
        raise ValueError(f"unknown DMX output {s!r}: use one of {', '.join(KINDS)} (e.g. artnet:192.168.1.50)")
    if kind in ("enttec", "opendmx", "none"):
        if kind == "none" and rest:
            raise ValueError("'none' takes nothing after it")
        if kind == "opendmx" and not rest:
            raise ValueError("an Open DMX dongle needs its port: opendmx:COM4")
        return OutputSpec(kind, rest)
    if kind == "artnet":
        host, _, uni = rest.partition(":")
        try:
            u = int(uni) if uni else 0
        except ValueError:
            raise ValueError(f"Art-Net universe {uni!r} is not a number") from None
        _check_port_address(u)
        return OutputSpec(kind, host.strip(), u, iface)
    uni, _, host = rest.partition("@")
    try:
        u = int(uni) if uni.strip() else 1
    except ValueError:
        raise ValueError(f"sACN universe {uni!r} is not a number") from None
    _check_sacn_universe(u)
    return OutputSpec(kind, host.strip(), u, iface)


def from_env() -> Optional[OutputSpec]:
    """LLANO_LIGHTS_OUTPUT as a spec, None when unset. A spec that doesn't parse is logged and read as
    unset (the ENTTEC path), never a run that won't start."""
    raw = (os.environ.get(ENV) or "").strip()
    if not raw:
        return None
    try:
        return parse(raw)
    except ValueError as e:
        _log.warning("%s=%r ignored (%s); looking for the ENTTEC Pro", ENV, raw, e)
        return None


def find_env() -> Optional[str]:
    """What a run would open: LLANO_LIGHTS_OUTPUT's port or network target, else the ENTTEC Pro's port.
    The app's one port scan (its window dots, its run and its probe read the same answer)."""
    spec = from_env()
    return spec.find() if spec else find_port()


def open_env(where: Optional[str] = None):
    """Open what find_env() found: LLANO_LIGHTS_OUTPUT's output, else the ENTTEC Pro."""
    spec = from_env()
    return spec.open(where) if spec else EnttecPro(where)


def pluggable(finder: Callable[[], Optional[str]] = find_env, **kw) -> PluggableOutput:
    """The lights output for a run: LLANO_LIGHTS_OUTPUT's when set, else the ENTTEC Pro, exactly as
    before. `finder` is the app's own scan (which holds its port lock and asks find_env). Either way
    it never refuses and picks the box up by itself."""
    return PluggableOutput(finder=finder, opener=open_env, **kw)
