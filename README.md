# RideSims Panel

A physical control panel for [ridesims.com](https://ridesims.com) (and other ride sims), built on an Arduino
Leonardo with a companion app for Windows.

Current version: **0.0.2**. Versions stay below 1.0 until the main release is final.

## How it works

- **Firmware** (`firmware/RideSimsPanel`) is deliberately dumb and never needs to change after the wiring is done. It reads the
  10 controls, drives the 7 button lamps, plays audio through a DFPlayer Mini, and runs the power-on sequence
  (panel-on tone + lamp test). That is all.
- **Companion app** (`companion/`) is where everything is configured. It turns control changes into keystrokes,
  runs the E-stop reset hold, drives the lamps, and stores one profile per ride.

Because all behavior lives in the companion, shipping a new feature means shipping a new `.exe`. You do not
reflash the Arduino. The only hard-coded thing is the pin wiring.

A few panel-level settings are stored on the Arduino itself (EEPROM) and set from the companion's
**Panel settings** section: power-on tone, lamp test length, debounce, volume at power-up, and which lamps
are steady or flashing when no companion is running. With no companion, the panel still powers on, plays the
tone, runs the lamp test, and then shows that standalone lamp pattern (default: E-stop lamp flashing). It
cannot send keystrokes without the companion.

## Companion app

- **Profiles** (one per ride): create, duplicate, rename, delete, import and export as JSON. They save
  automatically to `%APPDATA%\RideSimsPanel\profiles` (Help > Open profiles and settings folder), which is
  separate from the program, so updating or replacing the `.exe` never touches them.
- **Per control:** what it does when operated (hold the key while active, tap on activation, tap one key on and
  another off for switches, or nothing), the key or combo (type it or press **Rec**), and the lamp behavior
  (off, on, flashing, on while active, on while not active).
- **Dispatch buttons:** keep them **separate** (each has its own binding) or **linked** as one binding, either
  triggered by either button or only when both are pressed together.
- **E-stop reset:** how long Restart must be held, the key sent the entire time, and the tone played while
  holding. Release early and it aborts and stops the tone.
- **E-stop lamps:** the E-stop lamp flashes while idle. Press E-stop and it goes solid. Release it and the
  E-stop lamp stays solid while Restart flashes. Hold Restart and Restart goes solid. Finish the hold and
  everything returns to normal.
- Keys are sent as hardware scancodes. If a sim runs as administrator, run the companion as administrator too.
- Keys are not sent while the companion window itself is focused (so you can test the panel without typing into
  the settings). Untick that if you want otherwise.

When the panel powers up and the lamp test is acknowledged, the companion syncs the current switch positions
to the sim, so the sim matches the gates and station selector from the first moment.

### Power-on sequence

Key on plays the startup tone and starts the lamp test: the Restart lamp alternates with all the other lamps.
Press **Restart** to acknowledge and the panel goes live. (Panel settings can switch this to a timed test.)

### Panel settings (stored on the Arduino)

A few panel-level settings live in the Arduino's EEPROM and are set from the **Panel settings** tab with
**Write to panel**: power-on tone, whether the lamp test waits for Restart, timed test length, flash speed,
debounce, volume at power-up, and which lamps are steady or flashing when no companion is running. With no
companion the panel still powers on, plays the tone, runs the lamp test, and then shows that standalone lamp
pattern (default: E-stop lamp flashing). It cannot send keystrokes without the companion.

### Updates

The app checks GitHub releases when it launches (turn that off under Help) and on **Help > Check for updates**.
If there is a newer version it asks, downloads the new `.exe` next to the old one, verifies it, restarts into
it, and deletes the old one. This needs the repo (or at least its releases) to be **public**. If the app is
running from Python source instead of the `.exe`, it just opens the releases page.

If the app ever closes unexpectedly, look at `crash.log` in the profiles and settings folder.

## Build and release

Pushing to `main` builds the `.exe` in GitHub Actions and test-compiles the firmware. The first time a new version
number shows up, the workflow also publishes a **GitHub release** with both files, named with the version:

```
RideSimsPanel-0.0.2.exe
RideSimsPanel-Firmware-0.0.2.ino
```

To release: bump `__version__` in `companion/ridesims_panel/__init__.py`, commit, push to `main`. A version that
already has a release is skipped. Pushing a `v*` tag does the same and must match `__version__`.

The exe is unsigned, so Windows SmartScreen may warn the first time you download it in a browser (the in-app
updater does not trigger that).

## Flashing the firmware (once)

Close the companion app (and any serial monitor) first, since they hold the COM port. Then open
`firmware/RideSimsPanel/RideSimsPanel.ino` in the Arduino IDE, pick **Arduino Leonardo**, and upload.
Releases include the sketch as `RideSimsPanel-Firmware-<version>.ino`. The Arduino IDE will offer to put it in a
folder of the same name when you open it, which is fine. Wiring is in [docs/WIRING.md](docs/WIRING.md) and the
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
