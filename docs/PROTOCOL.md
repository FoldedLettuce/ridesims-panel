# Serial protocol (v3)

USB serial, 115200 8N1, ASCII lines ending in `\n`. The companion must set DTR (the Leonardo only talks while a
program has the port open). `PROTOCOL_VERSION` in the firmware and `ridesims_panel/__init__.py` must match.

## Firmware to PC

| Line | Meaning |
|---|---|
| `HELLO RSP <protocol> <fw_version>` | sent when the port opens and in reply to `?` |
| `S <mask_hex> <ready>` | input state, sent on every change. Bit set = ACTIVE. `ready` is 1 once the power-on sequence has finished |
| `T <count>` | number of files the DFPlayer found on the SD card |
| `C <track> <test_ms> <debounce_ms> <volume> <idle_on_hex> <idle_flash_hex> <flash_ms> <ack>` | panel settings stored in EEPROM, sent after HELLO and after a set |
| `E <text>` | error or debug text |

Input bits: 0 power key, 1 function, 2 restraints unlock, 3 restart, 4 e-stop, 5 dispatch left, 6 gates,
7 restraints lock, 8 station, 9 dispatch right.

## PC to firmware

| Line | Meaning |
|---|---|
| `?` | send HELLO, current state and track count |
| `H` | heartbeat, send about every second. If none arrives for 4 s the firmware turns the companion's lamps off |
| `L <mask_hex>` | lamps. Bit set = on. 0 e-stop, 1 restart, 2 restraints unlock, 3 function, 4 dispatch left, 5 dispatch right, 6 restraints lock |
| `P <n>` | play `/MP3/000n.mp3` |
| `X` | stop audio |
| `V <0-30>` | volume |
| `LT` | run the lamp test again (only while powered) |
| `C <same 8 values>` | store panel settings in EEPROM (the firmware replies with a `C` line) |

## Power-on sequence (the only behavior in the firmware)

Power key on: play the startup track and start the lamp test. The lamp test alternates every `flash_ms`
between the Restart lamp alone and all the other lamps, starting with Restart. With `ack = 1` (default) it
runs until Restart is pressed, then `S` reports `ready = 1`. The press that acknowledged the test is hidden
from the companion (reported as not pressed) until the button is released, so it does not count as a normal
Restart press. With `ack = 0` the test ends by itself after `test_ms`.

Lamps then follow `L` commands from the companion. If no companion is connected (or it stops sending
heartbeats), the lamps show the stored standalone pattern instead (steady `idle_on`, flashing `idle_flash`,
default: e-stop lamp flashing). Power key off: stop audio, all lamps off. The companion ignores every control
except the power key until `ready = 1`.

Defaults after a fresh flash: track 1, wait for Restart, 2500 ms timed test length, 25 ms debounce, volume 20,
1000 ms flash phase, e-stop lamp flashing.
