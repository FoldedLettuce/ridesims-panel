# Serial protocol (v1)

USB serial, 115200 8N1, ASCII lines ending in `\n`. The companion must set DTR (the Leonardo only talks while a
program has the port open). `PROTOCOL_VERSION` in the firmware and `ridesims_panel/__init__.py` must match.

## Firmware to PC

| Line | Meaning |
|---|---|
| `HELLO RSP <protocol> <fw_version>` | sent when the port opens and in reply to `?` |
| `S <mask_hex> <ready>` | input state, sent on every change. Bit set = ACTIVE. `ready` is 1 once the power-on sequence has finished |
| `T <count>` | number of files the DFPlayer found on the SD card |
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

## Power-on sequence (the only behavior in the firmware)

Power key on: play track 1, all lamps on for 2.5 s (lamp test), then lamps follow `L` commands and `S` reports
`ready = 1`. Power key off: stop audio, all lamps off. The companion ignores every control except the power key
until `ready = 1`.
