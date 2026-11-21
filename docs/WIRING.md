# Wiring (Arduino Leonardo)

All input contacts go between the Arduino pin and **GND** (the firmware uses the internal pull-ups).
Daisy-chain the grounds. No external resistors needed.

## Inputs

| Control | Pin | Contact | Reads as active when |
|---|---|---|---|
| Power key | D2 | NO | key is on (contact closed) |
| Function (white) | D3 | NO | pressed |
| Restraints unlock (orange) | D4 | NO | pressed |
| Restart (blue) | D5 | NO | pressed |
| E-stop | D6 | **NC** | pressed in, or the wire is cut (fail-safe) |
| Dispatch left | D7 | NO | pressed |
| Gates selector | D8 | NO | contact closed |
| Restraints lock (orange) | D9 | NO | pressed |
| Station selector | D10 | NO | contact closed |
| Dispatch right | D11 | NO | pressed |

For the two selectors, "active" means the contact is closed. If the sim sees the switch backwards, either swap
the two keys in the profile (Key / Key when switched off) or move the wire to the other contact.

## Lamps

Each lamp goes from the pin to the lamp's positive side, and the lamp's other side to GND.

| Lamp | Pin |
|---|---|
| E-stop | A0 |
| Restart (blue) | A1 |
| Restraints unlock (orange) | A2 |
| Function (white) | A3 |
| Dispatch left | A4 |
| Dispatch right | A5 |
| Restraints lock (orange) | D12 |

Pins drive 5 V and should stay at 20 mA or less each (40 mA absolute max). Use LED lamps with a series
resistor sized for 5 V, or switch heavier loads with a transistor. The power key, gates selector and station
selector have no lamp.

## DFPlayer Mini

| DFPlayer | Leonardo |
|---|---|
| VCC | 5V |
| GND | GND |
| TX | D0 (RX1) |
| RX | D1 (TX1), through a **1 kΩ resistor** |
| SPK1 / SPK2 | speaker (3 W or less, or use DAC_R/DAC_L into an amp) |

The 1 kΩ in series with the DFPlayer RX line is what keeps the Leonardo's 5 V signal from making the module
noisy. Skipping it often still works but is the classic cause of clicking and random restarts.

### SD card

FAT32, with a folder named `MP3` at the root and files named with four digits:

```
/MP3/0001.mp3   panel-on tone (played by the firmware at power-on)
/MP3/0002.mp3   default e-stop reset tone
/MP3/0003.mp3   ...anything else you want to pick in the companion
```

## Power

The whole panel runs from the Leonardo's single USB connection. If lamps plus DFPlayer ever brown out the
board, a powered USB hub or a separate 5 V supply into the Leonardo's VIN/5V is the fix.
