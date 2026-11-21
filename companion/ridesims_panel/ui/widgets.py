"""Small reusable widgets."""

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QWidget

from ..keys import parse_combo

_SPECIAL = {
    Qt.Key_Space: "space", Qt.Key_Return: "enter", Qt.Key_Enter: "enter",
    Qt.Key_Tab: "tab", Qt.Key_Backspace: "backspace", Qt.Key_Delete: "delete",
    Qt.Key_Insert: "insert", Qt.Key_Home: "home", Qt.Key_End: "end",
    Qt.Key_PageUp: "pageup", Qt.Key_PageDown: "pagedown",
    Qt.Key_Up: "up", Qt.Key_Down: "down", Qt.Key_Left: "left", Qt.Key_Right: "right",
    Qt.Key_Minus: "minus", Qt.Key_Equal: "equals", Qt.Key_Comma: "comma",
    Qt.Key_Period: "period", Qt.Key_Slash: "slash", Qt.Key_Backslash: "backslash",
    Qt.Key_Semicolon: "semicolon", Qt.Key_Apostrophe: "quote",
    Qt.Key_QuoteLeft: "backtick", Qt.Key_BracketLeft: "lbracket",
    Qt.Key_BracketRight: "rbracket", Qt.Key_CapsLock: "capslock",
}
# keys Qt reports when Shift is held (US layout), mapped back to the base key
_SHIFTED = {
    Qt.Key_Exclam: "1", Qt.Key_At: "2", Qt.Key_NumberSign: "3", Qt.Key_Dollar: "4",
    Qt.Key_Percent: "5", Qt.Key_AsciiCircum: "6", Qt.Key_Ampersand: "7",
    Qt.Key_Asterisk: "8", Qt.Key_ParenLeft: "9", Qt.Key_ParenRight: "0",
    Qt.Key_Underscore: "minus", Qt.Key_Plus: "equals", Qt.Key_BraceLeft: "lbracket",
    Qt.Key_BraceRight: "rbracket", Qt.Key_Bar: "backslash", Qt.Key_Colon: "semicolon",
    Qt.Key_QuoteDbl: "quote", Qt.Key_Less: "comma", Qt.Key_Greater: "period",
    Qt.Key_Question: "slash", Qt.Key_AsciiTilde: "backtick",
}
_KEYPAD = {
    Qt.Key_Asterisk: "nummul", Qt.Key_Minus: "numminus", Qt.Key_Plus: "numplus",
    Qt.Key_Period: "numdot", Qt.Key_Slash: "numdiv", Qt.Key_Enter: "numenter",
    Qt.Key_Return: "numenter",
}
_MOD_KEYS = {Qt.Key_Shift: "shift", Qt.Key_Control: "ctrl", Qt.Key_Alt: "alt", Qt.Key_Meta: "win"}


def event_to_combo(ev: QKeyEvent) -> Optional[str]:
    """Qt key event -> combo text like 'ctrl+f5'. None for modifier-only presses."""
    k = ev.key()
    if k in _MOD_KEYS or k == Qt.Key_unknown:
        return None
    mods = ev.modifiers()
    keypad = bool(mods & Qt.KeypadModifier)
    if keypad and Qt.Key_0 <= k <= Qt.Key_9:
        name = f"num{k - Qt.Key_0}"
    elif keypad and k in _KEYPAD:
        name = _KEYPAD[k]
    elif Qt.Key_A <= k <= Qt.Key_Z:
        name = chr(k).lower()
    elif Qt.Key_0 <= k <= Qt.Key_9:
        name = chr(k)
    elif Qt.Key_F1 <= k <= Qt.Key_F12:
        name = f"f{k - Qt.Key_F1 + 1}"
    elif k in _SPECIAL:
        name = _SPECIAL[k]
    elif k in _SHIFTED:
        name = _SHIFTED[k]
    else:
        return None
    parts = []
    if mods & Qt.ControlModifier:
        parts.append("ctrl")
    if mods & Qt.ShiftModifier:
        parts.append("shift")
    if mods & Qt.AltModifier:
        parts.append("alt")
    if mods & Qt.MetaModifier:
        parts.append("win")
    parts.append(name)
    return "+".join(parts)


class _CaptureEdit(QLineEdit):
    captured = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.recording = False
        self._mod_alone: Optional[str] = None

    def keyPressEvent(self, ev: QKeyEvent) -> None:
        if not self.recording:
            return super().keyPressEvent(ev)
        if ev.isAutoRepeat():
            return
        if ev.key() == Qt.Key_Escape:
            self.recording = False
            self.clearFocus()
            self.captured.emit("")   # empty = cancelled, handled by KeyEdit
            return
        if ev.key() in _MOD_KEYS:
            self._mod_alone = _MOD_KEYS[ev.key()]
            return
        combo = event_to_combo(ev)
        if combo:
            self._mod_alone = None
            self.recording = False
            self.captured.emit(combo)

    def keyReleaseEvent(self, ev: QKeyEvent) -> None:
        if self.recording and not ev.isAutoRepeat() and ev.key() in _MOD_KEYS:
            if self._mod_alone == _MOD_KEYS[ev.key()]:   # modifier pressed and released alone
                self.recording = False
                self.captured.emit(self._mod_alone)
                self._mod_alone = None
            return
        super().keyReleaseEvent(ev)

    def focusNextPrevChild(self, nxt: bool) -> bool:   # let Tab be recorded
        return False if self.recording else super().focusNextPrevChild(nxt)


class KeyEdit(QWidget):
    """Text box + Record button for a key combo. Emits changed(text) with a valid, normalized combo."""

    changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.edit = _CaptureEdit()
        self.edit.setPlaceholderText("none")
        self.btn = QPushButton("Rec")
        self.btn.setFixedWidth(40)
        self.btn.setToolTip("Click, then press the key (or combo) to bind. Esc cancels.")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.btn)

        self.btn.clicked.connect(self._start_record)
        self.edit.captured.connect(self._on_captured)
        self.edit.editingFinished.connect(self._commit)
        self.edit.editingFinished.connect(self._end_record_ui)

    def text(self) -> str:
        return self.edit.text().strip()

    def set_text(self, text: str) -> None:
        self.edit.blockSignals(True)
        self.edit.setText(text)
        self.edit.setStyleSheet("")
        self.edit.blockSignals(False)

    def setEnabled(self, on: bool) -> None:   # noqa: N802 (Qt naming)
        super().setEnabled(on)

    def _start_record(self) -> None:
        self.edit.recording = True
        self.edit.setPlaceholderText("press a key...")
        self.edit.setFocus()

    def _end_record_ui(self) -> None:
        self.edit.recording = False
        self.edit.setPlaceholderText("none")

    def _on_captured(self, combo: str) -> None:
        self._end_record_ui()
        if combo:
            self.set_text(combo)
            self.changed.emit(combo)

    def _commit(self) -> None:
        txt = self.edit.text().strip()
        if not txt:
            self.edit.setStyleSheet("")
            self.changed.emit("")
            return
        if parse_combo(txt) is None:
            self.edit.setStyleSheet("border: 1px solid #d33;")
            self.edit.setToolTip("Not a valid key. Examples: f, space, ctrl+f5, up, num5")
            return
        self.edit.setStyleSheet("")
        self.edit.setToolTip("")
        txt = txt.lower()
        self.set_text(txt)
        self.changed.emit(txt)
