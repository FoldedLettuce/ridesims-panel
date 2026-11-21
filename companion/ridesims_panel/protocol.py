"""Panel layout and serial protocol (see docs/PROTOCOL.md)."""

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class InputDef:
    id: str            # key used in profile files, never rename
    label: str         # shown in the UI
    bit: int           # bit position in the firmware S mask
    kind: str          # "button", "switch", "estop", "power"
    lamp_bit: Optional[int] = None   # bit in the firmware L mask, None = no lamp


# Order matches the firmware. Do not reorder bits.
INPUTS = [
    InputDef("power_key",         "Power key",          0, "power"),
    InputDef("function",          "Function (white)",   1, "button", 3),
    InputDef("restraints_unlock", "Restraints unlock",  2, "button", 2),
    InputDef("restart",           "Restart (blue)",     3, "button", 1),
    InputDef("estop",             "E-stop",             4, "estop",  0),
    InputDef("dispatch_left",     "Dispatch left",      5, "button", 4),
    InputDef("gates",             "Gates selector",     6, "switch"),
    InputDef("restraints_lock",   "Restraints lock",    7, "button", 6),
    InputDef("station",           "Station selector",   8, "switch"),
    InputDef("dispatch_right",    "Dispatch right",     9, "button", 5),
]

INPUT_BY_ID = {i.id: i for i in INPUTS}

POWER = INPUT_BY_ID["power_key"]
ESTOP = INPUT_BY_ID["estop"]
RESTART = INPUT_BY_ID["restart"]


def parse_line(line: str) -> Optional[Tuple]:
    """Parse one line from the firmware.

    Returns one of:
      ("hello", protocol:int, fw_version:str)
      ("state", mask:int, ready:bool)
      ("tracks", count:int)
      ("error", text:str)
    or None if the line is not understood.
    """
    line = line.strip()
    if not line:
        return None
    parts = line.split()
    try:
        if parts[0] == "HELLO" and len(parts) >= 4 and parts[1] == "RSP":
            return ("hello", int(parts[2]), parts[3])
        if parts[0] == "S" and len(parts) >= 3:
            return ("state", int(parts[1], 16), parts[2] == "1")
        if parts[0] == "T" and len(parts) >= 2:
            return ("tracks", int(parts[1]))
        if parts[0] == "E":
            return ("error", " ".join(parts[1:]))
    except ValueError:
        return None
    return None
