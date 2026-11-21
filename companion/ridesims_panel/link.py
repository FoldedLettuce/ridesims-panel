"""Serial connection to the panel (Qt event driven, no threads)."""

from typing import List, Optional

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtSerialPort import QSerialPort, QSerialPortInfo

from . import PROTOCOL_VERSION
from .protocol import parse_line

ARDUINO_VID = 0x2341
HELLO_TIMEOUT_MS = 2500
RECONNECT_MS = 2000


def list_ports() -> List[QSerialPortInfo]:
    return list(QSerialPortInfo.availablePorts())


def describe_port(info: QSerialPortInfo) -> str:
    desc = info.description() or "Serial port"
    return f"{info.portName()} - {desc}"


class PanelLink(QObject):
    """Opens the panel's serial port, handshakes, and emits parsed messages.

    port_name == "auto" means: try Arduino-looking ports first, then others,
    and keep retrying while not connected (handles unplug/replug).
    """

    connected = Signal(str, int, str)      # port name, protocol, firmware version
    disconnected = Signal()
    status = Signal(str)                   # human readable connection status
    state = Signal(int, bool)              # input mask, ready
    tracks = Signal(int)
    config = Signal(object)                # PanelConfig
    firmware_error = Signal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._port = QSerialPort(self)
        self._port.readyRead.connect(self._on_ready_read)
        self._port.errorOccurred.connect(self._on_error)
        self._buf = bytearray()

        self.port_name = "auto"
        self.want_connection = False
        self._handshaken = False
        self._closing = False
        self._tried: List[str] = []

        self._hello_timer = QTimer(self)
        self._hello_timer.setSingleShot(True)
        self._hello_timer.timeout.connect(self._on_hello_timeout)

        self._retry = QTimer(self)
        self._retry.setInterval(RECONNECT_MS)
        self._retry.timeout.connect(self._try_connect)

    # ------------------------------------------------------------ control --
    @property
    def is_open(self) -> bool:
        return self._port.isOpen()

    @property
    def is_ready(self) -> bool:
        return self._port.isOpen() and self._handshaken

    def start(self, port_name: str) -> None:
        self.port_name = port_name
        self.want_connection = True
        self._tried = []
        self._try_connect()
        self._retry.start()

    def stop(self) -> None:
        self.want_connection = False
        self._retry.stop()
        self._hello_timer.stop()
        self._close(graceful=True)
        self.status.emit("Disconnected")

    def send(self, line: str) -> None:
        if self._port.isOpen() and not self._closing:
            self._port.write((line + "\n").encode("ascii"))

    # ----------------------------------------------------------- internals --
    def _candidates(self) -> List[str]:
        if self.port_name != "auto":
            return [self.port_name]
        ports = list_ports()
        ard = [p.portName() for p in ports if p.vendorIdentifier() == ARDUINO_VID]
        other = [p.portName() for p in ports if p.vendorIdentifier() != ARDUINO_VID]
        return ard + other

    def _try_connect(self) -> None:
        if not self.want_connection or self._port.isOpen():
            return
        cands = self._candidates()
        if not cands:
            self.status.emit("Waiting for panel (no serial ports found)")
            return
        remaining = [c for c in cands if c not in self._tried]
        if not remaining:
            self._tried = []
            remaining = cands
        name = remaining[0]
        self._tried.append(name)

        self._port.setPortName(name)
        self._port.setBaudRate(115200)
        if not self._port.open(QSerialPort.ReadWrite):
            self.status.emit(f"Could not open {name}: {self._port.errorString()}")
            return
        # Leonardo only talks while DTR is set. Ignore errors from this call itself
        # (some virtual ports do not support it).
        self._port.blockSignals(True)
        self._port.setDataTerminalReady(True)
        self._port.blockSignals(False)
        self._buf.clear()
        self._handshaken = False
        self.status.emit(f"Connecting on {name}...")
        self.send("?")
        self._hello_timer.start(HELLO_TIMEOUT_MS)

    def _on_hello_timeout(self) -> None:
        if self._port.isOpen() and not self._handshaken:
            self.status.emit(f"{self._port.portName()} did not answer, trying next")
            self._close(graceful=True)

    def _close(self, graceful: bool) -> None:
        """Close the port. graceful=False is for a port that is already dead (unplugged):
        do not touch its control lines, because that raises more errors."""
        if self._closing:
            return
        self._closing = True
        was = self._handshaken
        self._port.blockSignals(True)   # no error signals while tearing down
        try:
            if self._port.isOpen():
                if graceful:
                    self._port.setDataTerminalReady(False)
                self._port.close()
        finally:
            self._port.blockSignals(False)
            self._closing = False
        self._handshaken = False
        self._buf.clear()
        if was:
            self.disconnected.emit()

    def _on_error(self, err) -> None:
        E = QSerialPort.SerialPortError
        # Errors that mean the port is gone. Windows reports an unplug as ResourceError,
        # PermissionError or DeviceNotFoundError depending on timing.
        fatal = (E.ResourceError, E.PermissionError, E.DeviceNotFoundError, E.ReadError, E.WriteError)
        if err not in fatal or self._closing:
            return
        if self._port.isOpen():
            # Unplugged ports report ResourceError, PermissionError, ReadError, WriteError...
            # Defer the close so we are not tearing the port down inside its own error signal.
            self.status.emit("Panel unplugged")
            QTimer.singleShot(0, lambda: self._close(graceful=False))

    def _on_ready_read(self) -> None:
        self._buf.extend(bytes(self._port.readAll()))
        while b"\n" in self._buf:
            raw, _, rest = self._buf.partition(b"\n")
            self._buf = bytearray(rest)
            self._handle(raw.decode("ascii", errors="ignore"))

    def _handle(self, line: str) -> None:
        msg = parse_line(line)
        if not msg:
            return
        kind = msg[0]
        if kind == "hello":
            if not self._handshaken:
                self._handshaken = True
                self._hello_timer.stop()
                if msg[1] != PROTOCOL_VERSION:
                    self.status.emit(
                        f"Firmware protocol v{msg[1]} but this app expects v{PROTOCOL_VERSION}, update the app or firmware"
                    )
                self.connected.emit(self._port.portName(), msg[1], msg[2])
        elif not self._handshaken:
            return
        elif kind == "state":
            self.state.emit(msg[1], msg[2])
        elif kind == "tracks":
            self.tracks.emit(msg[1])
        elif kind == "config":
            self.config.emit(msg[1])
        elif kind == "error":
            self.firmware_error.emit(msg[1])
