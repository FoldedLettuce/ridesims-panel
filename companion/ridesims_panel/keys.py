"""Key names, scancodes and the Windows key injector.

Keys are stored in profiles as text like "f", "space", "ctrl+shift+f5".
Injection uses hardware scancodes (SendInput + KEYEVENTF_SCANCODE) because
that is what games and most sims listen to.
"""

import sys
from typing import Dict, List, Optional, Set, Tuple

# name -> (set-1 scancode, extended)
_K: Dict[str, Tuple[int, bool]] = {}


def _add(name: str, code: int, ext: bool = False) -> None:
    _K[name] = (code, ext)


for _n, _c in zip("qwertyuiop", range(0x10, 0x1A)):
    _add(_n, _c)
for _n, _c in zip("asdfghjkl", range(0x1E, 0x27)):
    _add(_n, _c)
for _n, _c in zip("zxcvbnm", range(0x2C, 0x33)):
    _add(_n, _c)
for _n, _c in zip("1234567890", range(0x02, 0x0C)):
    _add(_n, _c)
for _i in range(1, 11):
    _add(f"f{_i}", 0x3A + _i)
_add("f11", 0x57)
_add("f12", 0x58)

for _n, _c in {
    "esc": 0x01, "minus": 0x0C, "equals": 0x0D, "backspace": 0x0E, "tab": 0x0F,
    "lbracket": 0x1A, "rbracket": 0x1B, "enter": 0x1C, "semicolon": 0x27,
    "quote": 0x28, "backtick": 0x29, "backslash": 0x2B, "comma": 0x33,
    "period": 0x34, "slash": 0x35, "space": 0x39, "capslock": 0x3A,
    "numlock": 0x45, "scrolllock": 0x46,
    "lctrl": 0x1D, "lshift": 0x2A, "rshift": 0x36, "lalt": 0x38,
    "nummul": 0x37, "num7": 0x47, "num8": 0x48, "num9": 0x49, "numminus": 0x4A,
    "num4": 0x4B, "num5": 0x4C, "num6": 0x4D, "numplus": 0x4E, "num1": 0x4F,
    "num2": 0x50, "num3": 0x51, "num0": 0x52, "numdot": 0x53,
}.items():
    _add(_n, _c)

for _n, _c in {
    "numenter": 0x1C, "rctrl": 0x1D, "numdiv": 0x35, "ralt": 0x38,
    "home": 0x47, "up": 0x48, "pageup": 0x49, "left": 0x4B, "right": 0x4D,
    "end": 0x4F, "down": 0x50, "pagedown": 0x51, "insert": 0x52,
    "delete": 0x53, "lwin": 0x5B, "rwin": 0x5C,
}.items():
    _add(_n, _c, True)

_ALIASES = {
    "ctrl": "lctrl", "control": "lctrl", "shift": "lshift", "alt": "lalt",
    "win": "lwin", "return": "enter", "escape": "esc", "spacebar": "space",
    "pgup": "pageup", "pgdn": "pagedown", "del": "delete", "ins": "insert",
    "-": "minus", "=": "equals", ",": "comma", ".": "period", "/": "slash",
    ";": "semicolon", "'": "quote", "`": "backtick", "\\": "backslash",
    "[": "lbracket", "]": "rbracket",
}

MODIFIERS = {"lctrl", "rctrl", "lshift", "rshift", "lalt", "ralt", "lwin", "rwin"}

KeyCode = Tuple[int, bool]


def canonical(name: str) -> Optional[str]:
    n = name.strip().lower()
    n = _ALIASES.get(n, n)
    return n if n in _K else None


def parse_combo(text: str) -> Optional[List[str]]:
    """'ctrl+shift+f1' -> ['lctrl', 'lshift', 'f1'] or None if invalid/empty.

    Everything before the last part must be a modifier.
    """
    text = (text or "").strip()
    if not text:
        return None
    parts = text.split("+")
    names = []
    for p in parts:
        c = canonical(p)
        if c is None:
            return None
        names.append(c)
    if any(n not in MODIFIERS for n in names[:-1]):
        return None
    return names


def normalize_combo(text: str) -> Optional[str]:
    names = parse_combo(text)
    return "+".join(names) if names else None


class KeySender:
    """Base class. Subclasses implement _emit(). Tracks what is held."""

    def __init__(self) -> None:
        self._held: Dict[str, int] = {}   # combo -> hold count

    def _emit(self, code: int, ext: bool, down: bool) -> None:
        raise NotImplementedError

    def press(self, combo: str) -> bool:
        names = parse_combo(combo)
        if not names:
            return False
        for n in names:
            self._emit(*_K[n], True)
        self._held[combo] = self._held.get(combo, 0) + 1
        return True

    def release(self, combo: str) -> None:
        names = parse_combo(combo)
        if not names or combo not in self._held:
            return
        for n in reversed(names):
            self._emit(*_K[n], False)
        self._held[combo] -= 1
        if self._held[combo] <= 0:
            del self._held[combo]

    def release_all(self) -> None:
        for combo in list(self._held):
            while combo in self._held:
                self.release(combo)

    @property
    def held(self) -> Set[str]:
        return set(self._held)


class NullSender(KeySender):
    """Records events instead of sending them. Used on non-Windows and in tests."""

    def __init__(self) -> None:
        super().__init__()
        self.events: List[Tuple[int, bool, bool]] = []

    def _emit(self, code: int, ext: bool, down: bool) -> None:
        self.events.append((code, ext, down))


class WindowsSender(KeySender):
    def __init__(self) -> None:
        super().__init__()
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        ULONG_PTR = ctypes.c_size_t

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", ULONG_PTR)]

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                        ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                        ("wParamH", wintypes.WORD)]

        class _U(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

        class INPUT(ctypes.Structure):
            _anonymous_ = ("u",)
            _fields_ = [("type", wintypes.DWORD), ("u", _U)]

        self._INPUT = INPUT
        self._KEYBDINPUT = KEYBDINPUT
        self._send = ctypes.windll.user32.SendInput
        self._send.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
        self._send.restype = wintypes.UINT

    def _emit(self, code: int, ext: bool, down: bool) -> None:
        flags = 0x0008  # KEYEVENTF_SCANCODE
        if ext:
            flags |= 0x0001  # KEYEVENTF_EXTENDEDKEY
        if not down:
            flags |= 0x0002  # KEYEVENTF_KEYUP
        inp = self._INPUT(type=1, ki=self._KEYBDINPUT(0, code, flags, 0, 0))
        self._send(1, self._ctypes.byref(inp), self._ctypes.sizeof(inp))


def make_sender() -> KeySender:
    if sys.platform == "win32":
        return WindowsSender()
    return NullSender()
