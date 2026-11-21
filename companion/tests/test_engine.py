import json

from ridesims_panel.engine import Engine
from ridesims_panel.keys import NullSender, parse_combo
from ridesims_panel.profiles import Binding, Profile, ProfileStore
from ridesims_panel.protocol import INPUT_BY_ID, parse_line


def bit(*ids):
    m = 0
    for i in ids:
        m |= 1 << INPUT_BY_ID[i].bit
    return m


class Rig:
    def __init__(self):
        self.t = 100.0
        self.sent = []
        self.sender = NullSender()
        self.engine = Engine(self.sender, self.sent.append, clock=lambda: self.t)
        self.p = Profile(name="t")
        self.p.bindings["function"] = Binding("tap", "f")
        self.p.bindings["dispatch_left"] = Binding("hold", "space")
        self.p.bindings["gates"] = Binding("tap_both", "g", "h", "off")
        self.p.bindings["estop"] = Binding("hold", "e")
        self.p.estop_reset.key = "r"
        self.p.estop_reset.tone = 3
        self.p.estop_reset.hold_ms = 2000
        self.engine.set_profile(self.p)
        self.engine.on_connected()

    def state(self, *ids, ready=True):
        self.engine.on_state(bit(*ids), ready)

    def advance(self, s):
        self.t += s
        self.engine.tick()

    def downs(self):
        return [(c, e) for c, e, d in self.sender.events if d]

    def power_up(self, *ids):
        self.state("power_key", *ids, ready=False)
        self.state("power_key", *ids, ready=True)
        self.advance(0.1)                      # let the sync taps (gates 'off' key) finish


def test_parse_line():
    assert parse_line("HELLO RSP 1 0.0.1") == ("hello", 1, "0.0.1")
    assert parse_line("S 3FF 1") == ("state", 0x3FF, True)
    assert parse_line("S 11 0") == ("state", 0x11, False)
    assert parse_line("T 12") == ("tracks", 12)
    assert parse_line("garbage") is None
    assert parse_line("S zz 1") is None


def test_combo():
    assert parse_combo("ctrl+shift+f5") == ["lctrl", "lshift", "f5"]
    assert parse_combo("space") == ["space"]
    assert parse_combo("f+g") is None
    assert parse_combo("nope") is None
    assert parse_combo("") is None


def test_no_keys_until_ready():
    r = Rig()
    r.state("function")                         # power off, ignored
    r.state("power_key", "function", ready=False)   # starting up, ignored
    assert r.sender.events == []


def test_tap_and_hold():
    r = Rig()
    r.power_up()
    r.state("power_key", "function")
    assert r.sender.held == {"f"}
    r.advance(0.1)
    assert r.sender.held == set()               # tap released after tap_ms
    r.state("power_key", "dispatch_left")
    assert r.sender.held == {"space"}
    r.state("power_key")
    assert r.sender.held == set()


def test_tap_both_and_sync_on_ready():
    r = Rig()
    r.state("power_key", "gates", ready=False)
    r.state("power_key", "gates", ready=True)   # sync sends 'g'
    assert r.sender.held == {"g"}
    r.advance(0.1)
    r.state("power_key")                        # switched off sends 'h'
    assert r.sender.held == {"h"}


def test_power_off_releases_everything():
    r = Rig()
    r.power_up()
    r.state("power_key", "dispatch_left")
    assert r.sender.held == {"space"}
    r.state()                                   # key switched off
    assert r.sender.held == set()
    assert not r.engine.live


def test_estop_reset_full_hold():
    r = Rig()
    r.power_up()
    r.state("power_key", "estop")               # pressed in
    assert r.sender.held == {"e"}
    assert r.engine.estop_latched
    r.state("power_key")                        # twisted out
    assert r.sender.held == set()
    r.state("power_key", "restart")             # start holding
    assert r.sender.held == {"r"}
    assert "P 3" in r.sent
    r.advance(1.0)
    assert r.engine.estop_latched
    assert 0.4 < r.engine.reset_progress < 0.6
    r.advance(1.1)
    assert not r.engine.estop_latched           # done
    assert r.sender.held == {"r"}               # still held until released
    r.state("power_key")
    assert r.sender.held == set()
    assert "X" not in r.sent                    # tone not cut off


def test_estop_reset_released_early():
    r = Rig()
    r.power_up()
    r.state("power_key", "estop")
    r.state("power_key")
    r.state("power_key", "restart")
    r.advance(0.5)
    r.state("power_key")
    assert r.sender.held == set()
    assert "X" in r.sent                        # tone stopped
    assert r.engine.estop_latched               # still needs a full hold


def test_restart_ignored_while_estop_pressed():
    r = Rig()
    r.power_up()
    r.state("power_key", "estop")
    r.state("power_key", "estop", "restart")
    assert r.sender.held == {"e"}               # no reset key
    assert r.engine.reset_progress is None


def test_estop_at_power_on_is_latched():
    r = Rig()
    r.power_up("estop")
    assert r.engine.estop_latched
    assert r.sender.held == {"e"}


def test_restart_normal_when_not_latched():
    r = Rig()
    r.p.bindings["restart"] = Binding("tap", "x")
    r.engine.set_profile(r.p)
    r.power_up()
    r.state("power_key", "restart")
    assert r.sender.held == {"x"}


def test_lamps():
    r = Rig()
    r.p.bindings["function"].lamp = "active"
    r.engine.set_profile(r.p)
    r.power_up()
    r.state("power_key", "function")
    r.advance(0.0)
    mask = int([x for x in r.sent if x.startswith("L ")][-1].split()[1], 16)
    assert mask & (1 << INPUT_BY_ID["function"].lamp_bit)


def test_restart_lamp_blinks_when_reset_needed():
    r = Rig()
    r.power_up()
    r.state("power_key", "estop")
    r.state("power_key")
    lamp = 1 << INPUT_BY_ID["restart"].lamp_bit
    seen = set()
    for _ in range(6):
        r.advance(0.5)
        lamps = [x for x in r.sent if x.startswith("L ")]
        seen.add(bool(int(lamps[-1].split()[1], 16) & lamp))
    assert seen == {True, False}


def test_heartbeat():
    r = Rig()
    r.advance(1.1)
    assert "H" in r.sent


def test_output_gate_releases_keys():
    r = Rig()
    r.power_up()
    r.state("power_key", "dispatch_left")
    assert r.sender.held == {"space"}
    r.engine.output_enabled = lambda: False
    r.advance(0.0)
    assert r.sender.held == set()


def test_disconnect_releases():
    r = Rig()
    r.power_up()
    r.state("power_key", "dispatch_left")
    r.engine.on_disconnected()
    assert r.sender.held == set()


def test_profile_roundtrip(tmp_path):
    store = ProfileStore(tmp_path)
    p = Profile(name="Maxx Force / test")
    p.bindings["gates"] = Binding("tap_both", "g", "h", "off")
    p.estop_reset.hold_ms = 4500
    p.estop_reset.tone = 7
    store.save(p)
    assert store.list_names() == ["Maxx Force / test"]
    q = store.load("Maxx Force / test")
    assert q.to_dict() == p.to_dict()
    # unknown inputs and bad values in a file do not crash loading
    bad = p.to_dict()
    bad["bindings"]["nonsense"] = {"mode": "hold"}
    bad["bindings"]["gates"]["mode"] = "wat"
    bad["volume"] = 999
    r = Profile.from_dict(json.loads(json.dumps(bad)))
    assert r.volume == 30 and r.bindings["gates"].mode == "tap_both"


def test_estop_lamp_always_flashes_by_default():
    r = Rig()
    r.engine.set_profile(Profile(name="fresh"))
    r.power_up()
    lamp = 1 << INPUT_BY_ID["estop"].lamp_bit
    seen = set()
    for _ in range(6):
        r.advance(0.5)
        lamps = [x for x in r.sent if x.startswith("L ")]
        seen.add(bool(int(lamps[-1].split()[1], 16) & lamp))
    assert seen == {True, False}
