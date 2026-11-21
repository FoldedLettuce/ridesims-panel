"""Main window of the companion app."""

import json
import time
from typing import Dict, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QGroupBox,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QMainWindow, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QSlider, QSpinBox, QTableWidget,
    QVBoxLayout, QWidget, QGridLayout, QTabWidget,
)

from .. import __version__
from ..engine import Engine
from ..keys import make_sender
from ..link import PanelLink, describe_port, list_ports
from ..profiles import (
    LAMP_LABELS, LAMP_MODES, MODE_LABELS, MODES, Profile, ProfileStore,
)
from ..protocol import INPUTS, LAMPS, PanelConfig
from .widgets import KeyEdit

COL_NAME, COL_LIVE, COL_MODE, COL_KEY, COL_KEY2, COL_LAMP = range(6)


class MainWindow(QMainWindow):
    def __init__(self, store: Optional[ProfileStore] = None) -> None:
        super().__init__()
        self.setWindowTitle(f"RideSims Panel Companion v{__version__}")
        self.resize(900, 800)

        self.store = store or ProfileStore()
        self.profile = Profile()
        self._loading = False
        self._fw_version = ""

        self.link = PanelLink(self)
        self.engine = Engine(make_sender(), self.link.send, log=self.append_log)
        self.engine.output_enabled = self._output_enabled

        self._build_ui()
        self._wire()

        name = self.store.settings.get("active_profile") or ""
        if name not in self.store.list_names():
            name = self.store.ensure_default()
        self._refresh_profile_list(select=name)
        self._refresh_ports()
        self.chk_send.setChecked(bool(self.store.settings.get("send_keys", True)))
        self.chk_pause.setChecked(bool(self.store.settings.get("pause_when_focused", True)))
        self.chk_auto.setChecked(bool(self.store.settings.get("autoconnect", True)))
        saved_port = self.store.settings.get("port", "auto")
        idx = self.cmb_port.findData(saved_port)
        self.cmb_port.setCurrentIndex(idx if idx >= 0 else 0)

        self.timer = QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

        if self.chk_auto.isChecked():
            self._connect()

    # ------------------------------------------------------------------ UI --
    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        v = QVBoxLayout(root)

        # connection row
        row = QHBoxLayout()
        row.addWidget(QLabel("Panel port:"))
        self.cmb_port = QComboBox()
        self.cmb_port.setMinimumWidth(260)
        row.addWidget(self.cmb_port)
        self.btn_refresh = QPushButton("Refresh")
        row.addWidget(self.btn_refresh)
        self.btn_connect = QPushButton("Connect")
        row.addWidget(self.btn_connect)
        self.chk_auto = QCheckBox("Auto-connect")
        row.addWidget(self.chk_auto)
        row.addStretch(1)
        self.lbl_status = QLabel("Disconnected")
        self.lbl_status.setStyleSheet("font-weight: bold;")
        row.addWidget(self.lbl_status)
        v.addLayout(row)

        # profile row
        row = QHBoxLayout()
        row.addWidget(QLabel("Profile:"))
        self.cmb_profile = QComboBox()
        self.cmb_profile.setMinimumWidth(240)
        row.addWidget(self.cmb_profile)
        self.btn_new = QPushButton("New")
        self.btn_dup = QPushButton("Duplicate")
        self.btn_ren = QPushButton("Rename")
        self.btn_del = QPushButton("Delete")
        self.btn_imp = QPushButton("Import...")
        self.btn_exp = QPushButton("Export...")
        for b in (self.btn_new, self.btn_dup, self.btn_ren, self.btn_del, self.btn_imp, self.btn_exp):
            row.addWidget(b)
        row.addStretch(1)
        lbl = QLabel("Changes save automatically")
        lbl.setStyleSheet("color: gray;")
        row.addWidget(lbl)
        v.addLayout(row)

        # bindings table
        self.table = QTableWidget(len(INPUTS), 6)
        self.table.setHorizontalHeaderLabels(
            ["Control", "Live", "When it is operated", "Key", "Key when switched off", "Lamp"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(COL_NAME, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(COL_LIVE, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(COL_MODE, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(COL_KEY, QHeaderView.Stretch)
        hh.setSectionResizeMode(COL_KEY2, QHeaderView.Stretch)
        hh.setSectionResizeMode(COL_LAMP, QHeaderView.ResizeToContents)

        self.live_labels: Dict[str, QLabel] = {}
        self.mode_boxes: Dict[str, QComboBox] = {}
        self.key_edits: Dict[str, KeyEdit] = {}
        self.key2_edits: Dict[str, KeyEdit] = {}
        self.lamp_boxes: Dict[str, Optional[QComboBox]] = {}

        for r, inp in enumerate(INPUTS):
            self.table.setItem(r, COL_NAME, self._ro_item(inp.label))
            live = QLabel("●")
            live.setAlignment(Qt.AlignCenter)
            self._set_live(live, False, inp.kind == "estop")
            self.table.setCellWidget(r, COL_LIVE, live)
            self.live_labels[inp.id] = live

            mode = QComboBox()
            for m in MODES:
                mode.addItem(MODE_LABELS[m], m)
            self.table.setCellWidget(r, COL_MODE, mode)
            self.mode_boxes[inp.id] = mode

            k1, k2 = KeyEdit(), KeyEdit()
            self.table.setCellWidget(r, COL_KEY, k1)
            self.table.setCellWidget(r, COL_KEY2, k2)
            self.key_edits[inp.id], self.key2_edits[inp.id] = k1, k2

            if inp.lamp_bit is not None:
                lamp = QComboBox()
                for m in LAMP_MODES:
                    lamp.addItem(LAMP_LABELS[m], m)
                self.table.setCellWidget(r, COL_LAMP, lamp)
                self.lamp_boxes[inp.id] = lamp
            else:
                self.table.setItem(r, COL_LAMP, self._ro_item("no lamp"))
                self.lamp_boxes[inp.id] = None
            self.table.setRowHeight(r, 34)
        self.tabs = QTabWidget()
        ctl_page = QWidget()
        cv = QVBoxLayout(ctl_page)
        cv.setContentsMargins(0, 6, 0, 0)
        cv.addWidget(self.table, 1)

        # e-stop reset + audio
        grp = QGroupBox("E-stop reset and audio")
        g = QGridLayout(grp)
        g.addWidget(QLabel("Hold Restart for"), 0, 0)
        self.spn_hold = QDoubleSpinBox()
        self.spn_hold.setRange(0.1, 30.0)
        self.spn_hold.setSingleStep(0.1)
        self.spn_hold.setSuffix(" s")
        g.addWidget(self.spn_hold, 0, 1)
        g.addWidget(QLabel("Reset key (held the whole time)"), 0, 2)
        self.key_reset = KeyEdit()
        g.addWidget(self.key_reset, 0, 3)

        g.addWidget(QLabel("Reset tone (track #)"), 1, 0)
        self.spn_tone = QSpinBox()
        self.spn_tone.setRange(1, 99)
        g.addWidget(self.spn_tone, 1, 1)
        row = QHBoxLayout()
        self.btn_preview = QPushButton("Preview")
        self.btn_stop = QPushButton("Stop")
        row.addWidget(self.btn_preview)
        row.addWidget(self.btn_stop)
        self.lbl_tracks = QLabel("")
        self.lbl_tracks.setStyleSheet("color: gray;")
        row.addWidget(self.lbl_tracks)
        row.addStretch(1)
        g.addLayout(row, 1, 2, 1, 2)

        g.addWidget(QLabel("Volume"), 2, 0)
        self.sld_vol = QSlider(Qt.Horizontal)
        self.sld_vol.setRange(0, 30)
        g.addWidget(self.sld_vol, 2, 1, 1, 2)
        self.lbl_vol = QLabel("20")
        g.addWidget(self.lbl_vol, 2, 3)

        g.addWidget(QLabel("Reset progress"), 3, 0)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        g.addWidget(self.bar, 3, 1, 1, 3)
        cv.addWidget(grp)
        self.tabs.addTab(ctl_page, "Controls")

        # panel-level settings, stored on the Arduino
        grp2 = QGroupBox("Panel settings (stored on the panel itself, same for every profile)")
        g2 = QGridLayout(grp2)
        g2.addWidget(QLabel("Power-on tone (track #)"), 0, 0)
        self.spn_startup = QSpinBox()
        self.spn_startup.setRange(1, 99)
        g2.addWidget(self.spn_startup, 0, 1)
        self.btn_startup_prev = QPushButton("Preview")
        g2.addWidget(self.btn_startup_prev, 0, 2)
        g2.addWidget(QLabel("Lamp test length"), 0, 3)
        self.spn_test = QDoubleSpinBox()
        self.spn_test.setRange(0.0, 10.0)
        self.spn_test.setSingleStep(0.5)
        self.spn_test.setSuffix(" s")
        g2.addWidget(self.spn_test, 0, 4)
        g2.addWidget(QLabel("Debounce"), 1, 0)
        self.spn_deb = QSpinBox()
        self.spn_deb.setRange(5, 100)
        self.spn_deb.setSuffix(" ms")
        g2.addWidget(self.spn_deb, 1, 1)
        g2.addWidget(QLabel("Volume at power-up"), 1, 3)
        self.sld_boot_vol = QSlider(Qt.Horizontal)
        self.sld_boot_vol.setRange(0, 30)
        g2.addWidget(self.sld_boot_vol, 1, 4)

        g2.addWidget(QLabel("Lamps when no companion is running:"), 2, 0, 1, 5)
        lamp_row = QHBoxLayout()
        self.idle_boxes: Dict[int, QComboBox] = {}
        for bit_, label in LAMPS:
            col = QVBoxLayout()
            lab = QLabel(label.split(" (")[0])
            lab.setAlignment(Qt.AlignCenter)
            cb = QComboBox()
            cb.addItem("Off", 0)
            cb.addItem("On", 1)
            cb.addItem("Flashing", 2)
            col.addWidget(lab)
            col.addWidget(cb)
            lamp_row.addLayout(col)
            self.idle_boxes[bit_] = cb
        g2.addLayout(lamp_row, 3, 0, 1, 5)

        row2 = QHBoxLayout()
        self.btn_write_cfg = QPushButton("Write to panel")
        self.lbl_cfg = QLabel("Connect to the panel to read its settings")
        self.lbl_cfg.setStyleSheet("color: gray;")
        row2.addWidget(self.btn_write_cfg)
        row2.addWidget(self.lbl_cfg, 1)
        g2.addLayout(row2, 4, 0, 1, 5)
        set_page = QWidget()
        sv = QVBoxLayout(set_page)
        sv.addWidget(grp2)
        sv.addStretch(1)
        self.tabs.addTab(set_page, "Panel settings")
        v.addWidget(self.tabs, 1)
        self._set_cfg_enabled(False)

        # options + test
        row = QHBoxLayout()
        self.chk_send = QCheckBox("Send keys to the computer")
        self.chk_pause = QCheckBox("...but not while this window is focused")
        self.btn_lamptest = QPushButton("Lamp test")
        row.addWidget(self.chk_send)
        row.addWidget(self.chk_pause)
        row.addStretch(1)
        row.addWidget(self.btn_lamptest)
        v.addLayout(row)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumBlockCount(300)
        self.log_box.setMaximumHeight(130)
        v.addWidget(self.log_box)

    @staticmethod
    def _ro_item(text: str):
        from PySide6.QtWidgets import QTableWidgetItem
        it = QTableWidgetItem(text)
        it.setFlags(Qt.ItemIsEnabled)
        return it

    @staticmethod
    def _set_live(lbl: QLabel, active: bool, estop: bool = False) -> None:
        color = ("#e03131" if estop else "#2f9e44") if active else "#868e96"
        lbl.setStyleSheet(f"color: {color}; font-size: 16px;")

    # -------------------------------------------------------------- wiring --
    def _wire(self) -> None:
        self.btn_refresh.clicked.connect(self._refresh_ports)
        self.btn_connect.clicked.connect(self._toggle_connect)
        self.chk_auto.toggled.connect(lambda on: self._setting("autoconnect", on))
        self.cmb_port.currentIndexChanged.connect(
            lambda _i: self._setting("port", self.cmb_port.currentData())
        )
        self.chk_send.toggled.connect(lambda on: self._setting("send_keys", on))
        self.chk_pause.toggled.connect(lambda on: self._setting("pause_when_focused", on))

        self.cmb_profile.activated.connect(self._on_profile_chosen)
        self.btn_new.clicked.connect(self._new_profile)
        self.btn_dup.clicked.connect(self._dup_profile)
        self.btn_ren.clicked.connect(self._rename_profile)
        self.btn_del.clicked.connect(self._delete_profile)
        self.btn_imp.clicked.connect(self._import_profile)
        self.btn_exp.clicked.connect(self._export_profile)

        for inp in INPUTS:
            i = inp.id
            self.mode_boxes[i].currentIndexChanged.connect(lambda _x, i=i: self._on_mode(i))
            self.key_edits[i].changed.connect(lambda t, i=i: self._on_key(i, t, False))
            self.key2_edits[i].changed.connect(lambda t, i=i: self._on_key(i, t, True))
            if self.lamp_boxes[i] is not None:
                self.lamp_boxes[i].currentIndexChanged.connect(lambda _x, i=i: self._on_lamp(i))

        self.spn_hold.valueChanged.connect(self._on_reset_changed)
        self.key_reset.changed.connect(lambda _t: self._on_reset_changed())
        self.spn_tone.valueChanged.connect(self._on_reset_changed)
        self.sld_vol.valueChanged.connect(self._on_volume)
        self.btn_preview.clicked.connect(lambda: self.link.send(f"P {self.spn_tone.value()}"))
        self.btn_stop.clicked.connect(lambda: self.link.send("X"))
        self.btn_lamptest.clicked.connect(lambda: self.link.send("LT"))
        self.btn_startup_prev.clicked.connect(lambda: self.link.send(f"P {self.spn_startup.value()}"))
        self.btn_write_cfg.clicked.connect(self._write_cfg)
        self.link.config.connect(self._on_config)

        self.link.status.connect(self._on_link_status)
        self.link.connected.connect(self._on_connected)
        self.link.disconnected.connect(self._on_disconnected)
        self.link.state.connect(self._on_state)
        self.link.tracks.connect(self._on_tracks)
        self.link.firmware_error.connect(lambda t: self.append_log(f"firmware: {t}"))

    def _setting(self, key: str, value) -> None:
        self.store.settings[key] = value
        self.store.save_settings()

    def append_log(self, text: str) -> None:
        self.log_box.appendPlainText(f"{time.strftime('%H:%M:%S')}  {text}")

    def _output_enabled(self) -> bool:
        if not self.chk_send.isChecked():
            return False
        if self.chk_pause.isChecked() and self.isActiveWindow():
            return False
        return True

    # ---------------------------------------------------------- connection --
    def _refresh_ports(self) -> None:
        current = self.cmb_port.currentData()
        self.cmb_port.blockSignals(True)
        self.cmb_port.clear()
        self.cmb_port.addItem("Auto-detect", "auto")
        for p in list_ports():
            self.cmb_port.addItem(describe_port(p), p.portName())
        idx = self.cmb_port.findData(current)
        self.cmb_port.setCurrentIndex(idx if idx >= 0 else 0)
        self.cmb_port.blockSignals(False)

    def _connect(self) -> None:
        self.link.start(self.cmb_port.currentData() or "auto")
        self.btn_connect.setText("Disconnect")

    def _toggle_connect(self) -> None:
        if self.link.want_connection:
            self.link.stop()
            self.btn_connect.setText("Connect")
        else:
            self._connect()

    def _on_link_status(self, text: str) -> None:
        self.lbl_status.setText(text)
        self.lbl_status.setStyleSheet("font-weight: bold; color: #868e96;")

    def _on_connected(self, port: str, proto: int, fw: str) -> None:
        self._fw_version = fw
        self.append_log(f"connected on {port}, firmware {fw}, protocol {proto}")
        self.engine.on_connected()
        self._update_status()

    def _on_disconnected(self) -> None:
        self.append_log("panel disconnected")
        self.engine.on_disconnected()
        for inp in INPUTS:
            self._set_live(self.live_labels[inp.id], False, inp.kind == "estop")
        self.lbl_status.setText("Disconnected")
        self.lbl_status.setStyleSheet("font-weight: bold; color: #868e96;")
        self._set_cfg_enabled(False)
        self.lbl_cfg.setText("Connect to the panel to read its settings")

    def _on_state(self, mask: int, ready: bool) -> None:
        self.engine.on_state(mask, ready)
        for inp in INPUTS:
            self._set_live(self.live_labels[inp.id], bool(mask >> inp.bit & 1), inp.kind == "estop")
        self._update_status()

    def _set_cfg_enabled(self, on: bool) -> None:
        for w in (self.spn_startup, self.btn_startup_prev, self.spn_test, self.spn_deb,
                  self.sld_boot_vol, self.btn_write_cfg, *self.idle_boxes.values()):
            w.setEnabled(on)

    def _on_config(self, c: PanelConfig) -> None:
        self.spn_startup.setValue(c.startup_track)
        self.spn_test.setValue(c.lamp_test_ms / 1000.0)
        self.spn_deb.setValue(c.debounce_ms)
        self.sld_boot_vol.setValue(c.volume)
        for bit_, cb in self.idle_boxes.items():
            state = 2 if (c.idle_flash >> bit_) & 1 else (1 if (c.idle_on >> bit_) & 1 else 0)
            cb.setCurrentIndex(state)
        self._set_cfg_enabled(True)
        self.lbl_cfg.setText("Loaded from panel")

    def _write_cfg(self) -> None:
        on = flash = 0
        for bit_, cb in self.idle_boxes.items():
            if cb.currentData() == 1:
                on |= 1 << bit_
            elif cb.currentData() == 2:
                flash |= 1 << bit_
        cfg = PanelConfig(
            startup_track=self.spn_startup.value(),
            lamp_test_ms=int(round(self.spn_test.value() * 1000)),
            debounce_ms=self.spn_deb.value(),
            volume=self.sld_boot_vol.value(),
            idle_on=on, idle_flash=flash,
        )
        self.link.send(cfg.to_line())
        self.lbl_cfg.setText("Saved to panel")

    def _on_tracks(self, count: int) -> None:
        self.lbl_tracks.setText(f"{count} audio file(s) on SD card")

    def _update_status(self) -> None:
        if not self.link.is_ready:
            return
        e = self.engine
        if not e.powered:
            state, color = "panel OFF", "#868e96"
        elif not e.fw_ready:
            state, color = "starting up (lamp test)", "#f08c00"
        elif e.estop_latched:
            state, color = "E-STOP, hold Restart to reset", "#e03131"
        else:
            state, color = "READY", "#2f9e44"
        self.lbl_status.setText(f"Connected (fw {self._fw_version}) - {state}")
        self.lbl_status.setStyleSheet(f"font-weight: bold; color: {color};")

    def _tick(self) -> None:
        self.engine.tick()
        prog = self.engine.reset_progress
        self.bar.setValue(int((prog or 0.0) * 1000))
        if self.link.is_ready:
            self._update_status()

    # ------------------------------------------------------------ profiles --
    def _refresh_profile_list(self, select: str) -> None:
        self.cmb_profile.blockSignals(True)
        self.cmb_profile.clear()
        for n in self.store.list_names():
            self.cmb_profile.addItem(n)
        idx = self.cmb_profile.findText(select)
        self.cmb_profile.setCurrentIndex(max(idx, 0))
        self.cmb_profile.blockSignals(False)
        self._load_profile(self.cmb_profile.currentText())

    def _load_profile(self, name: str) -> None:
        p = self.store.load(name)
        if p is None:
            p = Profile(name=name)
        self.profile = p
        self._setting("active_profile", p.name)
        self._loading = True
        for inp in INPUTS:
            b = p.bindings[inp.id]
            self.mode_boxes[inp.id].setCurrentIndex(MODES.index(b.mode))
            self.key_edits[inp.id].set_text(b.key)
            self.key2_edits[inp.id].set_text(b.key2)
            if self.lamp_boxes[inp.id] is not None:
                self.lamp_boxes[inp.id].setCurrentIndex(LAMP_MODES.index(b.lamp))
            self._update_row_enabled(inp.id)
        self.spn_hold.setValue(p.estop_reset.hold_ms / 1000.0)
        self.key_reset.set_text(p.estop_reset.key)
        self.spn_tone.setValue(p.estop_reset.tone)
        self.sld_vol.setValue(p.volume)
        self.lbl_vol.setText(str(p.volume))
        self._loading = False
        self.engine.set_profile(p)

    def _save(self) -> None:
        if not self._loading:
            self.store.save(self.profile)

    def _on_profile_chosen(self, _idx: int) -> None:
        self._load_profile(self.cmb_profile.currentText())

    def _update_row_enabled(self, input_id: str) -> None:
        mode = self.profile.bindings[input_id].mode
        self.key_edits[input_id].setEnabled(mode != "none")
        self.key2_edits[input_id].setEnabled(mode == "tap_both")

    def _on_mode(self, input_id: str) -> None:
        if self._loading:
            return
        self.engine.release_all()
        self.profile.bindings[input_id].mode = self.mode_boxes[input_id].currentData()
        self._update_row_enabled(input_id)
        self._save()

    def _on_key(self, input_id: str, text: str, second: bool) -> None:
        if self._loading:
            return
        self.engine.release_all()
        b = self.profile.bindings[input_id]
        if second:
            b.key2 = text
        else:
            b.key = text
        self._save()

    def _on_lamp(self, input_id: str) -> None:
        if self._loading:
            return
        self.profile.bindings[input_id].lamp = self.lamp_boxes[input_id].currentData()
        self._save()

    def _on_reset_changed(self) -> None:
        if self._loading:
            return
        er = self.profile.estop_reset
        er.hold_ms = int(round(self.spn_hold.value() * 1000))
        er.key = self.key_reset.text()
        er.tone = self.spn_tone.value()
        self._save()

    def _on_volume(self, value: int) -> None:
        self.lbl_vol.setText(str(value))
        if self._loading:
            return
        self.profile.volume = value
        self._save()
        self.link.send(f"V {value}")

    def _ask_name(self, title: str, default: str = "") -> Optional[str]:
        text, ok = QInputDialog.getText(self, title, "Profile name (one per ride):", text=default)
        text = text.strip()
        return text if ok and text else None

    def _new_profile(self) -> None:
        name = self._ask_name("New profile")
        if not name:
            return
        p = Profile(name=self.store.unique_name(name))
        self.store.save(p)
        self._refresh_profile_list(select=p.name)

    def _dup_profile(self) -> None:
        p = self.profile.copy()
        p.name = self.store.unique_name(self.profile.name + " copy")
        self.store.save(p)
        self._refresh_profile_list(select=p.name)

    def _rename_profile(self) -> None:
        name = self._ask_name("Rename profile", self.profile.name)
        if not name or name == self.profile.name:
            return
        if name in self.store.list_names():
            QMessageBox.warning(self, "Rename", "A profile with that name already exists.")
            return
        self.store.rename(self.profile.name, name)
        self._refresh_profile_list(select=name)

    def _delete_profile(self) -> None:
        if len(self.store.list_names()) <= 1:
            QMessageBox.information(self, "Delete", "You need at least one profile.")
            return
        if QMessageBox.question(self, "Delete", f"Delete profile '{self.profile.name}'?") != QMessageBox.Yes:
            return
        self.store.delete(self.profile.name)
        self._refresh_profile_list(select=self.store.list_names()[0])

    def _import_profile(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import profile", "", "Profile (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                p = Profile.from_dict(json.load(f))
        except (OSError, ValueError, TypeError) as e:
            QMessageBox.warning(self, "Import", f"Could not read that file: {e}")
            return
        p.name = self.store.unique_name(p.name)
        self.store.save(p)
        self._refresh_profile_list(select=p.name)

    def _export_profile(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export profile", f"{self.profile.name}.json", "Profile (*.json)"
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.profile.to_dict(), f, indent=2)

    # --------------------------------------------------------------- close --
    def closeEvent(self, ev) -> None:
        self.engine.release_all()
        self.link.stop()
        super().closeEvent(ev)
