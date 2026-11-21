# RideSims Panel

A physical control panel for [ridesims.com](https://ridesims.com) (and other ride sims), built on an Arduino
Leonardo with a companion app for Windows.

Current version: **0.0.1**. Versions stay below 1.0 until the main release is final.

## How it works

- **Firmware** (`firmware/RideSimsPanel`) is deliberately dumb and should almost never change. It reads the
  10 controls, drives the 7 button lamps, plays audio through a DFPlayer Mini, and runs the power-on sequence
  (panel-on tone + lamp test). That is all.
- **Companion app** (`companion/`) is where everything is configured. It turns control changes into keystrokes,
  runs the E-stop reset hold, drives the lamps, and stores one profile per ride.

Because all behavior lives in the companion, shipping a new feature means shipping a new `.exe`. You do not
reflash the Arduino.

## Companion app (v0.0.1)

- Profiles (one per ride): create, duplicate, rename, delete, import and export as JSON. Changes save
  automatically to `%APPDATA%\RideSimsPanel\profiles`.
- Per control: what it does when operated (hold the key while active, tap on activation, tap one key on and
  another off for switches, or nothing), the key or combo (type it or press **Rec**), and the lamp behavior
  (off, on, flashing, on while active, on while not active). The E-stop lamp flashes by default.
- E-stop reset: how long Restart must be held, the key sent the entire time, and the tone played while holding.
  Release early and it aborts and stops the tone. The Restart lamp blinks while a reset is needed and goes
  solid while you hold.
- Keys are sent as hardware scancodes. If a sim runs as administrator, run the companion as administrator too.
- Keys are not sent while the companion window itself is focused (so you can test the panel without typing into
  the settings). Untick that if you want otherwise.

When the panel powers up (key on), the companion syncs the current switch positions to the sim, so the sim
matches the gates and station selector from the first moment.

## Build and release

Pushing to `main` builds the `.exe` and the firmware hex in GitHub Actions (download from the run's
artifacts). Pushing a tag like `v0.0.1` publishes a GitHub release with both, named with the version:

```
RideSimsPanel-0.0.1.exe
RideSimsPanel-Firmware-0.0.1.hex
```

To release: bump `__version__` in `companion/ridesims_panel/__init__.py`, commit, then
`git tag v0.0.2 && git push --tags`. The release job fails if the tag and the version disagree.

The exe is unsigned, so Windows SmartScreen will warn the first time.

## Flashing the firmware (once)

Open `firmware/RideSimsPanel/RideSimsPanel.ino` in the Arduino IDE, pick **Arduino Leonardo**, and upload.
Or flash the `.hex` from a release with any AVR uploader. Wiring is in [docs/WIRING.md](docs/WIRING.md) and the
serial protocol in [docs/PROTOCOL.md](docs/PROTOCOL.md).

## Running from source

```
cd companion
pip install -r requirements-dev.txt
python -m ridesims_panel
python -m pytest
```

## Roadmap

- Browser extension for ridesims.com (Chrome and Firefox), possibly two-way
- 1.0 is the final main release
