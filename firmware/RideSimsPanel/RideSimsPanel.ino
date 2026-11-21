/*
  RideSims Panel firmware
  Target: Arduino Leonardo (ATmega32U4)

  Design goal: this sketch is generic and should (almost) never need to change.
  All behavior (keybinds, lamp logic, hold-to-reset, tones) lives in the
  companion app. The firmware only:
    - debounces the 10 inputs and reports them over USB serial
    - drives the 7 button lamps on command
    - plays DFPlayer Mini tracks on command
    - runs the power-on sequence (panel-on tone + lamp test)

  Serial protocol (115200 8N1, newline terminated ASCII), see docs/PROTOCOL.md

  Firmware -> PC
    HELLO RSP <protocol> <fw_version>
    S <input_mask_hex> <ready>     inputs changed (bit set = ACTIVE), ready=1 once startup is done
    T <count>                      number of audio files found on the SD card
    E <text>                       error / debug text

  PC -> Firmware
    ?            request HELLO + state + track count
    H            heartbeat (send about every 1 s)
    L <hex>      lamp mask (bit set = lamp on)
    P <n>        play track n    (/MP3/000n.mp3)
    X            stop audio
    V <0-30>     volume
    LT           run the lamp test again (only while powered)

  Wiring (see docs/WIRING.md)
*/

#define FW_VERSION "0.0.1"
#define PROTOCOL_VERSION 1

// ---------------------------------------------------------------- inputs ----
// Order here defines the bit order in the S message. Do not reorder.
//   bit 0 power key        D2
//   bit 1 function         D3
//   bit 2 restraints unlock D4
//   bit 3 restart          D5
//   bit 4 e-stop (NC)      D6   (ACTIVE = e-stop pressed OR wire broken)
//   bit 5 dispatch left    D7
//   bit 6 gates selector   D8
//   bit 7 restraints lock  D9
//   bit 8 station selector D10
//   bit 9 dispatch right   D11
const uint8_t NUM_INPUTS = 10;
const uint8_t INPUT_PINS[NUM_INPUTS] = {2, 3, 4, 5, 6, 7, 8, 9, 10, 11};
// Contacts are wired between the pin and GND, using INPUT_PULLUP.
// Normally open contact: closed (LOW) = active.
// Normally closed contact (e-stop): open (HIGH) = active, so a cut wire reads as e-stop.
const bool INPUT_ACTIVE_HIGH[NUM_INPUTS] = {false, false, false, false, true, false, false, false, false, false};
const uint8_t IDX_POWER = 0;

// ----------------------------------------------------------------- lamps ----
//   bit 0 e-stop            A0
//   bit 1 restart (blue)    A1
//   bit 2 restraints unlock A2
//   bit 3 function (white)  A3
//   bit 4 dispatch left     A4
//   bit 5 dispatch right    A5
//   bit 6 restraints lock   D12
const uint8_t NUM_LAMPS = 7;
const uint8_t LAMP_PINS[NUM_LAMPS] = {A0, A1, A2, A3, A4, A5, 12};

// ----------------------------------------------------------------- audio ----
// DFPlayer Mini on hardware Serial1 (Leonardo D0 = RX1, D1 = TX1).
// Track 1 (/MP3/0001.mp3) is the panel-on tone played by the firmware.
const uint8_t TRACK_STARTUP = 1;
const uint8_t DEFAULT_VOLUME = 20;

// ---------------------------------------------------------------- timing ----
const uint16_t DEBOUNCE_MS = 25;
const uint16_t LAMP_TEST_MS = 2500;
const uint16_t HEARTBEAT_TIMEOUT_MS = 4000;

// ----------------------------------------------------------------- state ----
uint16_t rawMask = 0;        // last raw read
uint16_t stableMask = 0;     // debounced
uint32_t rawChangedAt[NUM_INPUTS];
bool rawBit[NUM_INPUTS];

bool powered = false;
bool ready = false;          // startup sequence finished
bool lampTest = false;
uint32_t lampTestStart = 0;

uint8_t companionLamps = 0;
uint32_t lastHeartbeat = 0;
bool heardCompanion = false;

bool usbWasOpen = false;
uint16_t trackCount = 0;

// DFPlayer response parser
uint8_t dfBuf[10];
uint8_t dfPos = 0;

// serial line buffer
char lineBuf[24];
uint8_t linePos = 0;

// ------------------------------------------------------------- DFPlayer -----
void dfSend(uint8_t cmd, uint16_t param) {
  uint8_t p1 = param >> 8;
  uint8_t p2 = param & 0xFF;
  uint16_t sum = 0xFF + 0x06 + cmd + 0x00 + p1 + p2;
  uint16_t chk = 0 - sum;
  uint8_t frame[10] = {0x7E, 0xFF, 0x06, cmd, 0x00, p1, p2, (uint8_t)(chk >> 8), (uint8_t)(chk & 0xFF), 0xEF};
  Serial1.write(frame, 10);
}

void dfPlay(uint16_t track) { dfSend(0x12, track); }   // play /MP3/NNNN.mp3
void dfStop() { dfSend(0x16, 0); }
void dfVolume(uint8_t v) { if (v > 30) v = 30; dfSend(0x06, v); }

void dfHandle() {
  while (Serial1.available()) {
    uint8_t b = Serial1.read();
    if (dfPos == 0 && b != 0x7E) continue;
    dfBuf[dfPos++] = b;
    if (dfPos == 10) {
      dfPos = 0;
      if (dfBuf[9] != 0xEF) continue;
      uint8_t cmd = dfBuf[3];
      uint16_t param = ((uint16_t)dfBuf[5] << 8) | dfBuf[6];
      if (cmd == 0x48) {            // total files on TF card
        trackCount = param;
        if (Serial) { Serial.print(F("T ")); Serial.println(trackCount); }
      } else if (cmd == 0x40) {     // error
        if (Serial) { Serial.print(F("E dfplayer ")); Serial.println(param); }
      }
    }
  }
}

// ------------------------------------------------------------- reporting ----
void sendHello() {
  Serial.print(F("HELLO RSP "));
  Serial.print(PROTOCOL_VERSION);
  Serial.print(' ');
  Serial.println(F(FW_VERSION));
}

void sendState() {
  Serial.print(F("S "));
  Serial.print(stableMask, HEX);
  Serial.print(' ');
  Serial.println(ready ? 1 : 0);
}

// ---------------------------------------------------------------- lamps -----
void applyLamps() {
  uint8_t mask = 0;
  if (powered) {
    if (lampTest) mask = 0xFF;
    else if (ready) mask = companionLamps;
  }
  for (uint8_t i = 0; i < NUM_LAMPS; i++) {
    digitalWrite(LAMP_PINS[i], (mask >> i) & 1 ? HIGH : LOW);
  }
}

// ------------------------------------------------------- power sequence -----
void powerOn() {
  powered = true;
  ready = false;
  lampTest = true;
  lampTestStart = millis();
  dfPlay(TRACK_STARTUP);
  applyLamps();
  sendState();
}

void powerOff() {
  powered = false;
  ready = false;
  lampTest = false;
  dfStop();
  applyLamps();
  sendState();
}

void runPowerSequence() {
  if (powered && lampTest && millis() - lampTestStart >= LAMP_TEST_MS) {
    lampTest = false;
    ready = true;
    applyLamps();
    sendState();
  }
}

// --------------------------------------------------------------- inputs -----
void readInputs() {
  uint32_t now = millis();
  bool changed = false;
  for (uint8_t i = 0; i < NUM_INPUTS; i++) {
    bool level = digitalRead(INPUT_PINS[i]);
    bool active = INPUT_ACTIVE_HIGH[i] ? level : !level;
    if (active != rawBit[i]) {
      rawBit[i] = active;
      rawChangedAt[i] = now;
    }
    bool stable = (stableMask >> i) & 1;
    if (rawBit[i] != stable && now - rawChangedAt[i] >= DEBOUNCE_MS) {
      if (rawBit[i]) stableMask |= (1u << i);
      else stableMask &= ~(1u << i);
      changed = true;
      if (i == IDX_POWER) {
        if (rawBit[i]) powerOn(); else powerOff();
      }
    }
  }
  if (changed) sendState();
}

// --------------------------------------------------------------- serial -----
void handleLine(char *s) {
  if (s[0] == '?') {
    sendHello();
    sendState();
    if (trackCount) { Serial.print(F("T ")); Serial.println(trackCount); }
    else dfSend(0x48, 0);
    return;
  }
  heardCompanion = true;
  lastHeartbeat = millis();
  if (s[0] == 'H') return;
  if (s[0] == 'L' && s[1] == 'T') {
    if (powered) { lampTest = true; ready = false; lampTestStart = millis(); applyLamps(); sendState(); }
    return;
  }
  if (s[0] == 'L') {
    companionLamps = (uint8_t)strtoul(s + 1, NULL, 16);
    applyLamps();
  } else if (s[0] == 'P') {
    dfPlay((uint16_t)atoi(s + 1));
  } else if (s[0] == 'X') {
    dfStop();
  } else if (s[0] == 'V') {
    dfVolume((uint8_t)atoi(s + 1));
  }
}

void readSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (linePos) {
        lineBuf[linePos] = 0;
        handleLine(lineBuf);
        linePos = 0;
      }
    } else if (linePos < sizeof(lineBuf) - 1) {
      lineBuf[linePos++] = c;
    } else {
      linePos = 0;   // overflow, drop line
    }
  }
}

// ------------------------------------------------------------ main loop -----
void setup() {
  for (uint8_t i = 0; i < NUM_INPUTS; i++) {
    pinMode(INPUT_PINS[i], INPUT_PULLUP);
    rawBit[i] = false;
    rawChangedAt[i] = 0;
  }
  for (uint8_t i = 0; i < NUM_LAMPS; i++) {
    pinMode(LAMP_PINS[i], OUTPUT);
    digitalWrite(LAMP_PINS[i], LOW);
  }

  Serial.begin(115200);
  Serial1.begin(9600);

  delay(1000);                 // DFPlayer boot time
  dfVolume(DEFAULT_VOLUME);
  delay(50);
  dfSend(0x48, 0);             // ask for file count

  // Establish the initial debounced state without triggering events
  for (uint8_t i = 0; i < NUM_INPUTS; i++) {
    bool level = digitalRead(INPUT_PINS[i]);
    bool active = INPUT_ACTIVE_HIGH[i] ? level : !level;
    rawBit[i] = active;
    if (active) stableMask |= (1u << i);
  }
  if (stableMask & (1u << IDX_POWER)) powerOn();   // key already on at boot
}

void loop() {
  readInputs();
  runPowerSequence();
  dfHandle();

  bool usbOpen = Serial;       // true while a program has the port open (DTR)
  if (usbOpen && !usbWasOpen) {
    sendHello();
    sendState();
  }
  if (!usbOpen && usbWasOpen) {
    companionLamps = 0;        // companion went away
    heardCompanion = false;
    applyLamps();
  }
  usbWasOpen = usbOpen;

  if (usbOpen) readSerial();

  // Companion vanished without closing the port (crash, hang): drop its lamps
  if (heardCompanion && millis() - lastHeartbeat > HEARTBEAT_TIMEOUT_MS) {
    heardCompanion = false;
    companionLamps = 0;
    applyLamps();
  }
}
