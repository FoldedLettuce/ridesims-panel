"""End to end: fake firmware on a pty <-> PanelLink <-> Engine (Linux/macOS only)."""

import os
import sys
import threading
import time

import pytest

if sys.platform == "win32":
    pytest.skip("pty not available", allow_module_level=True)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pty  # noqa: E402
import tty  # noqa: E402

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ridesims_panel.engine import Engine  # noqa: E402
from ridesims_panel.keys import NullSender  # noqa: E402
from ridesims_panel.link import PanelLink  # noqa: E402
from ridesims_panel.profiles import Binding, Profile  # noqa: E402
from ridesims_panel.protocol import INPUT_BY_ID  # noqa: E402


class FakeFirmware(threading.Thread):
    def __init__(self, fd):
        super().__init__(daemon=True)
        self.fd = fd
        self.received = []
        self.running = True

    def send(self, text):
        os.write(self.fd, (text + "\n").encode())

    def run(self):
        buf = b""
        while self.running:
            try:
                data = os.read(self.fd, 256)
            except OSError:
                return
            buf += data
            while b"\n" in buf:
                line, _, buf = buf.partition(b"\n")
                line = line.decode().strip()
                self.received.append(line)
                if line == "?":
                    self.send("HELLO RSP 3 0.0.2")
                    self.send("C 1 2500 25 20 0 1 1000 1")
                    self.send("S 0 0")
                    self.send("T 5")


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def test_end_to_end():
    app = QApplication.instance() or QApplication([])
    master, slave = pty.openpty()
    tty.setraw(slave)
    fw = FakeFirmware(master)
    fw.start()

    link = PanelLink()
    sender = NullSender()
    eng = Engine(sender, link.send)
    p = Profile(name="sim")
    p.bindings["dispatch_left"] = Binding("hold", "space")
    eng.set_profile(p)

    got = {}
    link.connected.connect(lambda port, proto, fwv: (got.update(fw=fwv), eng.on_connected()))
    link.state.connect(eng.on_state)
    link.tracks.connect(lambda n: got.update(tracks=n))
    link.config.connect(lambda c: got.update(cfg=c))

    tick = QTimer()
    tick.timeout.connect(eng.tick)
    tick.start(20)

    link.start(os.ttyname(slave))
    pump(600)
    assert got.get("fw") == "0.0.2", link.status
    assert got.get("tracks") == 5
    assert got["cfg"].lamp_test_ms == 2500 and got["cfg"].idle_flash == 1
    assert "V 20" in fw.received

    power = 1 << INPUT_BY_ID["power_key"].bit
    left = 1 << INPUT_BY_ID["dispatch_left"].bit
    fw.send(f"S {power:X} 0")
    pump(100)
    fw.send(f"S {power:X} 1")
    pump(100)
    fw.send(f"S {power | left:X} 1")
    pump(100)
    assert sender.held == {"space"}
    fw.send(f"S {power:X} 1")
    pump(100)
    assert sender.held == set()
    assert any(x.startswith("L ") for x in fw.received)

    pump(1200)
    assert "H" in fw.received

    link.stop()
    fw.running = False


def test_unplug_does_not_crash():
    """Regression: unplugging used to recurse in the error handler until the process died."""
    app = QApplication.instance() or QApplication([])
    master, slave = pty.openpty()
    tty.setraw(slave)
    fw = FakeFirmware(master)
    fw.start()
    link = PanelLink()
    events = []
    link.connected.connect(lambda *a: events.append("connected"))
    link.disconnected.connect(lambda: events.append("disconnected"))
    link.start(os.ttyname(slave))
    pump(600)
    assert events == ["connected"]
    hb = QTimer()                    # the engine sends a heartbeat every second, like this
    hb.timeout.connect(lambda: link.send("H"))
    hb.start(100)
    fw.running = False
    os.close(master)                 # the "unplug"
    pump(1500)
    hb.stop()
    assert "disconnected" in events
    assert not link.is_ready
    link.stop()
