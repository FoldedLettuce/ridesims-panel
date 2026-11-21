"""Panel logic: turns input state from the firmware into key presses, lamps and audio.

No Qt in here so it can be unit tested. The UI calls on_state()/tick() and
supplies the send_line() callback that writes to the serial port.
"""

import time
from typing import Callable, Dict, List, Optional, Tuple

from .keys import KeySender, parse_combo
from .profiles import Profile
from .protocol import ESTOP, INPUTS, INPUT_BY_ID, POWER, RESTART

HEARTBEAT_S = 1.0
BLINK_S = 0.5


class Engine:
    def __init__(
        self,
        sender: KeySender,
        send_line: Callable[[str], None],
        clock: Callable[[], float] = time.monotonic,
        log: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.sender = sender
        self._send_line = send_line
        self._clock = clock
        self._log = log or (lambda s: None)

        self.profile = Profile()
        self.output_enabled: Callable[[], bool] = lambda: True

        self.connected = False
        self.mask = 0
        self.fw_ready = False
        self.live = False                 # powered and startup sequence finished

        self.estop_latched = False        # e-stop was hit and has not been reset yet
        self._restart_consumed = False    # current restart press belongs to the reset hold
        self._reset_start: Optional[float] = None
        self._reset_done = False

        self._tap_releases: List[Tuple[float, str]] = []
        self._last_lamps: Optional[int] = None
        self._last_heartbeat = 0.0

    # ------------------------------------------------------------ helpers --
    def log(self, text: str) -> None:
        self._log(text)

    def _bit(self, input_id: str) -> bool:
        return bool((self.mask >> INPUT_BY_ID[input_id].bit) & 1)

    @property
    def powered(self) -> bool:
        return self._bit("power_key")

    @property
    def reset_progress(self) -> Optional[float]:
        """0..1 while the restart button is being held for an e-stop reset, else None."""
        if self._reset_start is None:
            return None
        if self._reset_done:
            return 1.0
        total = self.profile.estop_reset.hold_ms / 1000.0
        return min(1.0, (self._clock() - self._reset_start) / total)

    def _can_send(self) -> bool:
        return self.output_enabled()

    def _press(self, combo: str) -> None:
        if combo and self._can_send() and self.sender.press(combo):
            self.log(f"key down  {combo}")

    def _release(self, combo: str) -> None:
        if combo and combo in self.sender.held:
            self.sender.release(combo)
            self.log(f"key up    {combo}")

    def _tap(self, combo: str) -> None:
        if not combo or not self._can_send():
            return
        if self.sender.press(combo):
            self.log(f"tap       {combo}")
            self._tap_releases.append((self._clock() + self.profile.tap_ms / 1000.0, combo))

    # --------------------------------------------------------- connection --
    def set_profile(self, profile: Profile) -> None:
        self.release_all()
        self.profile = profile
        if self.connected:
            self._send_line(f"V {profile.volume}")
            self._sync_live_state()
        self._last_lamps = None

    def on_connected(self) -> None:
        self.connected = True
        self.mask = 0
        self.fw_ready = False
        self.live = False
        self._last_lamps = None
        self._last_heartbeat = self._clock()
        self._send_line("?")
        self._send_line(f"V {self.profile.volume}")

    def on_disconnected(self) -> None:
        self.release_all()
        self.connected = False
        self.mask = 0
        self.fw_ready = False
        self.live = False
        self.estop_latched = False
        self._cancel_reset(stop_tone=False)

    def release_all(self) -> None:
        self.sender.release_all()
        self._tap_releases.clear()

    # -------------------------------------------------------------- state --
    def on_state(self, mask: int, ready: bool) -> None:
        old = self.mask
        self.mask = mask
        self.fw_ready = ready
        changed = old ^ mask

        # power key edge is always reported, even during startup
        pbit = 1 << POWER.bit
        if changed & pbit:
            self._edge(POWER.id, bool(mask & pbit))

        powered = bool(mask & pbit)
        live = powered and ready
        if live and not self.live:
            self.live = True
            self.log("panel ready")
            self._sync_live_state()
            return
        if not live and self.live:
            self.live = False
            self.log("panel off")
            self.release_all()
            self.estop_latched = False
            self._cancel_reset(stop_tone=False)
            return
        if not live:
            return

        for inp in INPUTS:
            if inp.id == POWER.id:
                continue
            if changed & (1 << inp.bit):
                self._edge(inp.id, bool(mask & (1 << inp.bit)))

    def _sync_live_state(self) -> None:
        """Called when the panel becomes ready: make the sim match the current switch positions."""
        if not self.live:
            return
        if self._bit("estop"):
            self.estop_latched = True
        for inp in INPUTS:
            if inp.id == POWER.id:
                continue
            b = self.profile.bindings[inp.id]
            active = self._bit(inp.id)
            if b.mode == "hold" and active:
                self._press(b.key)
            elif b.mode == "tap_both":
                self._tap(b.key if active else b.key2)

    # -------------------------------------------------------------- edges --
    def _edge(self, input_id: str, active: bool) -> None:
        name = INPUT_BY_ID[input_id].label
        self.log(f"{name}: {'ACTIVE' if active else 'inactive'}")

        if input_id == ESTOP.id:
            if active:
                self.estop_latched = True
                self._cancel_reset(stop_tone=True)
        if input_id == RESTART.id and self._handle_restart_for_reset(active):
            return

        b = self.profile.bindings[input_id]
        if b.mode == "hold":
            if active:
                self._press(b.key)
            else:
                self._release(b.key)
        elif b.mode == "tap":
            if active:
                self._tap(b.key)
        elif b.mode == "tap_both":
            self._tap(b.key if active else b.key2)

    # ------------------------------------------------------- e-stop reset --
    def _handle_restart_for_reset(self, active: bool) -> bool:
        """Returns True if the restart edge was consumed by the e-stop reset logic."""
        er = self.profile.estop_reset
        if active:
            if not self.live or not self.estop_latched:
                return False
            self._restart_consumed = True
            if self._bit("estop"):
                self.log("restart ignored, e-stop is still pressed")
                return True
            self._reset_start = self._clock()
            self._reset_done = False
            self._press(er.key)
            self._send_line(f"P {er.tone}")
            self.log(f"e-stop reset: hold for {er.hold_ms / 1000:.1f}s")
            return True

        if self._restart_consumed:
            self._restart_consumed = False
            was_done = self._reset_done
            self._release(er.key)
            if self._reset_start is not None and not was_done:
                self.log("e-stop reset aborted, released too early")
                self._send_line("X")
            self._reset_start = None
            self._reset_done = False
            return True
        return False

    def _cancel_reset(self, stop_tone: bool) -> None:
        if self._reset_start is not None:
            self._release(self.profile.estop_reset.key)
            if stop_tone and not self._reset_done:
                self._send_line("X")
        self._reset_start = None
        self._reset_done = False

    # --------------------------------------------------------------- lamps --
    def _lamp_mask(self) -> int:
        if not self.live:
            return 0
        blink_on = int(self._clock() / BLINK_S) % 2 == 0
        mask = 0
        for inp in INPUTS:
            if inp.lamp_bit is None:
                continue
            mode = self.profile.bindings[inp.id].lamp
            active = self._bit(inp.id)
            on = {"off": False, "on": True, "flash": blink_on, "active": active, "inactive": not active}[mode]
            if inp.id == RESTART.id and self.estop_latched and not self._bit("estop"):
                # prompt the operator to hold restart: blink, solid while holding
                on = True if self._reset_start is not None else blink_on
            if on:
                mask |= 1 << inp.lamp_bit
        return mask

    # ---------------------------------------------------------------- tick --
    def tick(self) -> None:
        now = self._clock()

        # taps
        if self._tap_releases:
            due = [t for t in self._tap_releases if t[0] <= now]
            self._tap_releases = [t for t in self._tap_releases if t[0] > now]
            for _, combo in due:
                self._release(combo)

        # reset hold progress
        if self._reset_start is not None and not self._reset_done:
            if now - self._reset_start >= self.profile.estop_reset.hold_ms / 1000.0:
                self._reset_done = True
                self.estop_latched = False
                self.log("e-stop reset complete")

        # output gate closed: never leave keys stuck down
        if self.sender.held and not self._can_send():
            self.sender.release_all()

        if not self.connected:
            return

        lamps = self._lamp_mask()
        if lamps != self._last_lamps:
            self._last_lamps = lamps
            self._send_line(f"L {lamps:X}")

        if now - self._last_heartbeat >= HEARTBEAT_S:
            self._last_heartbeat = now
            self._send_line("H")
