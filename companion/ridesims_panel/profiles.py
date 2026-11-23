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
BUNDLE_TYPE = "ridesims-profiles"

MODES = ["none", "hold", "tap", "tap_both"]
MODE_LABELS = {
    "none": "Do nothing",
    "hold": "Hold key while active",
    "tap": "Tap key when activated",
    "tap_both": "Tap key on / tap other key off",
}
DISPATCH_MODES = ["separate", "either", "both"]
DISPATCH_LABELS = {
    "separate": "Separate (each button has its own binding)",
    "either": "Linked: either button dispatches",
    "both": "Linked: both buttons must be pressed",
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
    tone: int = 2          # /MP3/0002.mp3 on the SD card

    def to_dict(self) -> dict:
        return {"hold_ms": self.hold_ms, "tone": self.tone}


def default_binding(input_id: str) -> Binding:
    """Starting point for a new profile (keys are left blank on purpose)."""
    if input_id == "power_key":
        return Binding(mode="none")
    if input_id == "estop":
        return Binding(mode="tap", lamp="flash")
    if input_id in ("restart", "dispatch_left", "dispatch_right"):
        return Binding(mode="hold")
    if INPUT_BY_ID[input_id].kind == "switch":
        return Binding(mode="tap_both", lamp="off")
    return Binding(mode="tap")


@dataclass
class Profile:
    name: str = "New profile"
    bindings: Dict[str, Binding] = field(default_factory=dict)
    dispatch_mode: str = "separate"
    dispatch: Binding = field(default_factory=lambda: Binding(mode="hold"))   # used when the dispatch buttons are linked
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
            "dispatch_mode": self.dispatch_mode,
            "dispatch": self.dispatch.to_dict(),
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
            tone=max(1, min(255, int(er.get("tone", 2)))),
        )
        dm = d.get("dispatch_mode", "separate")
        p.dispatch_mode = dm if dm in DISPATCH_MODES else "separate"
        if isinstance(d.get("dispatch"), dict):
            p.dispatch = Binding.from_dict(d["dispatch"], Binding(mode="hold"))
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


def natural_key(name: str) -> list:
    """Sort key so "Ride 2" comes before "Ride 10" and case is ignored."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def export_bundle(profiles: List[Profile], app_version: str = "") -> dict:
    """Everything needed to restore a set of profiles, in one file."""
    return {
        "type": BUNDLE_TYPE,
        "schema": SCHEMA,
        "app_version": app_version,
        "profiles": [p.to_dict() for p in profiles],
    }


def parse_import(data) -> List[Profile]:
    """Accepts a bundle (all profiles), a list of profiles, or a single profile file from older versions.

    Raises ValueError if it is none of those."""
    if isinstance(data, dict) and isinstance(data.get("profiles"), list):
        items = data["profiles"]
    elif isinstance(data, list):
        items = data
    elif isinstance(data, dict) and ("bindings" in data or "name" in data):
        items = [data]
    else:
        raise ValueError("this is not a RideSims Panel profile file")
    out = []
    for d in items:
        if isinstance(d, dict):
            out.append(Profile.from_dict(d))
    if not out:
        raise ValueError("there are no profiles in this file")
    return out


class ProfileStore:
    """Profiles live in <data_dir>/profiles/<slug>.json, settings in settings.json."""

    DEFAULT_SETTINGS = {
        "active_profile": "",
        "port": "auto",
        "autoconnect": True,
        "send_keys": True,
        "pause_when_focused": True,
        "check_updates": True,
        "theme": "dark",
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
        for f in self.dir.glob("*.json"):
            try:
                names.append(str(json.loads(f.read_text("utf-8")).get("name", f.stem)))
            except (OSError, ValueError):
                continue
        return sorted(names, key=natural_key)

    def load_all(self) -> List[Profile]:
        out = []
        for n in self.list_names():
            p = self.load(n)
            if p is not None:
                out.append(p)
        return out

    def conflicts(self, profiles: List[Profile]) -> List[str]:
        """Names in `profiles` that already exist here."""
        have = {slugify(n).lower() for n in self.list_names()}
        return [p.name for p in profiles if slugify(p.name).lower() in have]

    def import_profiles(self, profiles: List[Profile], on_conflict: str = "keep_both") -> List[str]:
        """Save imported profiles. on_conflict is "keep_both" (rename the newcomer), "replace" or "skip".

        Returns the names that ended up saved."""
        before = {slugify(n).lower() for n in self.list_names()}
        saved = []
        for p in profiles:
            exists = slugify(p.name).lower() in before
            if exists and on_conflict == "skip":
                continue
            if not (exists and on_conflict == "replace"):
                p.name = self.unique_name(p.name)
            self.save(p)
            saved.append(p.name)
        return saved

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
