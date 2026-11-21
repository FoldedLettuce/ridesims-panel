"""Profiles (one per ride/sim) and app settings, stored as JSON files."""

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .protocol import INPUTS, INPUT_BY_ID

SCHEMA = 1

MODES = ["none", "hold", "tap", "tap_both"]
MODE_LABELS = {
    "none": "Do nothing",
    "hold": "Hold key while active",
    "tap": "Tap key when activated",
    "tap_both": "Tap key on / tap other key off",
}
LAMP_MODES = ["off", "on", "flash", "active", "inactive"]
LAMP_LABELS = {
    "off": "Always off",
    "on": "Always on",
    "flash": "Always flashing",
    "active": "On while active",
    "inactive": "On while NOT active",
}


@dataclass
class Binding:
    mode: str = "none"
    key: str = ""
    key2: str = ""        # only used by tap_both (key sent when switched off)
    lamp: str = "active"

    def to_dict(self) -> dict:
        return {"mode": self.mode, "key": self.key, "key2": self.key2, "lamp": self.lamp}

    @staticmethod
    def from_dict(d: dict, default: "Binding") -> "Binding":
        mode = d.get("mode", default.mode)
        lamp = d.get("lamp", default.lamp)
        return Binding(
            mode=mode if mode in MODES else default.mode,
            key=str(d.get("key", "")),
            key2=str(d.get("key2", "")),
            lamp=lamp if lamp in LAMP_MODES else default.lamp,
        )


@dataclass
class EstopReset:
    hold_ms: int = 3000
    key: str = ""
    tone: int = 2          # /MP3/0002.mp3 on the SD card

    def to_dict(self) -> dict:
        return {"hold_ms": self.hold_ms, "key": self.key, "tone": self.tone}


def default_binding(input_id: str) -> Binding:
    kind = INPUT_BY_ID[input_id].kind
    if kind == "power":
        return Binding(mode="none")
    if kind == "estop":
        return Binding(mode="hold", lamp="flash")
    if kind == "switch":
        return Binding(mode="tap_both", lamp="off")
    return Binding(mode="tap")


@dataclass
class Profile:
    name: str = "New profile"
    bindings: Dict[str, Binding] = field(default_factory=dict)
    estop_reset: EstopReset = field(default_factory=EstopReset)
    volume: int = 20       # DFPlayer volume 0-30
    tap_ms: int = 60       # how long a "tap" holds the key down

    def __post_init__(self) -> None:
        for i in INPUTS:
            self.bindings.setdefault(i.id, default_binding(i.id))

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA,
            "name": self.name,
            "volume": self.volume,
            "tap_ms": self.tap_ms,
            "estop_reset": self.estop_reset.to_dict(),
            "bindings": {k: v.to_dict() for k, v in self.bindings.items()},
        }

    @staticmethod
    def from_dict(d: dict) -> "Profile":
        p = Profile(name=str(d.get("name", "Imported profile")))
        p.volume = max(0, min(30, int(d.get("volume", 20))))
        p.tap_ms = max(10, min(1000, int(d.get("tap_ms", 60))))
        er = d.get("estop_reset", {})
        p.estop_reset = EstopReset(
            hold_ms=max(100, min(30000, int(er.get("hold_ms", 3000)))),
            key=str(er.get("key", "")),
            tone=max(1, min(255, int(er.get("tone", 2)))),
        )
        for input_id, bd in d.get("bindings", {}).items():
            if input_id in INPUT_BY_ID and isinstance(bd, dict):
                p.bindings[input_id] = Binding.from_dict(bd, default_binding(input_id))
        return p

    def copy(self) -> "Profile":
        return Profile.from_dict(self.to_dict())


def data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "RideSimsPanel"


def slugify(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._ -]+", "", name).strip().replace(" ", "-")
    return s or "profile"


class ProfileStore:
    """Profiles live in <data_dir>/profiles/<slug>.json, settings in settings.json."""

    DEFAULT_SETTINGS = {
        "active_profile": "",
        "port": "auto",
        "autoconnect": True,
        "send_keys": True,
        "pause_when_focused": True,
    }

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root) if root else data_dir()
        self.dir = self.root / "profiles"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.settings = dict(self.DEFAULT_SETTINGS)
        self._load_settings()

    # ---- settings
    def _load_settings(self) -> None:
        try:
            self.settings.update(json.loads((self.root / "settings.json").read_text("utf-8")))
        except (OSError, ValueError):
            pass

    def save_settings(self) -> None:
        (self.root / "settings.json").write_text(json.dumps(self.settings, indent=2), "utf-8")

    # ---- profiles
    def _path(self, name: str) -> Path:
        return self.dir / f"{slugify(name)}.json"

    def list_names(self) -> List[str]:
        names = []
        for f in sorted(self.dir.glob("*.json")):
            try:
                names.append(str(json.loads(f.read_text("utf-8")).get("name", f.stem)))
            except (OSError, ValueError):
                continue
        return names

    def load(self, name: str) -> Optional[Profile]:
        try:
            return Profile.from_dict(json.loads(self._path(name).read_text("utf-8")))
        except (OSError, ValueError, TypeError):
            return None

    def save(self, profile: Profile) -> None:
        self._path(profile.name).write_text(json.dumps(profile.to_dict(), indent=2), "utf-8")

    def delete(self, name: str) -> None:
        try:
            self._path(name).unlink()
        except OSError:
            pass

    def rename(self, old: str, new: str) -> Optional[Profile]:
        p = self.load(old)
        if p is None:
            return None
        self.delete(old)
        p.name = new
        self.save(p)
        return p

    def unique_name(self, base: str) -> str:
        existing = {slugify(n).lower() for n in self.list_names()}
        if slugify(base).lower() not in existing:
            return base
        n = 2
        while slugify(f"{base} {n}").lower() in existing:
            n += 1
        return f"{base} {n}"

    def ensure_default(self) -> str:
        names = self.list_names()
        if not names:
            self.save(Profile(name="Default"))
            names = ["Default"]
        return names[0]
