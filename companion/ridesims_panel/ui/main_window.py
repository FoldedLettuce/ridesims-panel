"""Main window of the companion app."""

import json
import time
from typing import Dict, Optional

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QGroupBox,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QMainWindow, QMenu,
    QMessageBox, QPlainTextEdit, QProgressBar, QProgressDialog, QPushButton, QSlider, QSpinBox,
    QTableWidget, QVBoxLayout, QWidget, QGridLayout, QTabWidget,
)

from .. import PROTOCOL_VERSION, __version__
from .. import updater as upd
from ..engine import Engine
from ..keys import make_sender
from ..link import PanelLink, describe_port, list_ports
from ..profiles import (
    DISPATCH_LABELS, DISPATCH_MODES, LAMP_LABELS, LAMP_MODES, MODE_LABELS, MODES,
    Profile, ProfileStore, export_bundle, parse_import,
)
from ..protocol import INPUTS, LAMPS, PanelConfig
from .theme import THEMES, apply_theme
from .widgets import KeyEdit

COL_NAME, COL_LIVE, COL_MODE, COL_KEY, COL_KEY2, COL_LAMP = range(6)


class MainWindow(QMainWindow):
    def __init__(self, store: Optional[ProfileStore] = None) -> None:
        super().__init__()
        self.setWindowTitle(f"RideSims Panel Companion v{__version__}")
        self.resize(1240, 900)

        self.store = store or ProfileStore()
        self.store.settings["theme"] = apply_theme(self.store.settings.get("theme", "dark"))
        self.profile = Profile()
        self._loading = False
        self._refreshing = False
        self._fw_version = ""
        self._proto = PROTOCOL_VERSION
        self._cfg: Optional[PanelConfig] = None
        self._manual_update = False
        self._dl_dialog: Optional[QProgressDialog] = None
        self.updater = upd.Updater(self)
        upd.cleanup_downloads()

        self.link = PanelLink(self)
        self.engine = Engine(make_sender(), self.link.send, log=self.append_log)
        self.engine.output_enabled = self._output_enabled

        self._build_ui()
        self._build_menu()
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
        if self.store.settings.get("check_updates", True):
            QTimer.singleShot(2500, lambda: self._check_updates(manual=False))

    # ------------------------------------------------------------------ UI --
    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.addWidget(self._build_sidebar())
        main = QWidget()
        outer.addWidget(main, 1)
        v = QVBoxLayout(main)
        v.setContentsMargins(0, 0, 0, 0)

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

        # which profile is being edited
        self.lbl_current = QLabel("")
        self.lbl_current.setStyleSheet("font-size: 15px; font-weight: bold;")
        v.addWidget(self.lbl_current)

        row = QHBoxLayout()
        row.addWidget(QLabel("Dispatch buttons:"))
        self.cmb_dispatch = QComboBox()
        for m in DISPATCH_MODES:
            self.cmb_dispatch.addItem(DISPATCH_LABELS[m], m)
        row.addWidget(self.cmb_dispatch)
        row.addStretch(1)
        v.addLayout(row)

        # bindings table
        self.table = QTableWidget(len(INPUTS), 6)
        self.table.setHorizontalHeaderLabels(
            ["Control", "Live", "When it is operated", "Key", "Key when switched off", "Lamp"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(10 * 34 + 34)
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
        self.name_items: Dict[str, object] = {}

        for r, inp in enumerate(INPUTS):
            item = self._ro_item(inp.label)
            self.table.setItem(r, COL_NAME, item)
            self.name_items[inp.id] = item
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
        g.addWidget(QLabel("Reset key (blank = Restart key)"), 0, 2)
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
        self.chk_ack = QCheckBox("Lamp test waits until Restart is pressed")
        g2.addWidget(self.chk_ack, 0, 3, 1, 2)
        g2.addWidget(QLabel("Lamp test length if it does not wait"), 2, 3)
        self.spn_test = QDoubleSpinBox()
        self.spn_test.setRange(0.0, 10.0)
        self.spn_test.setSingleStep(0.5)
        self.spn_test.setSuffix(" s")
        g2.addWidget(self.spn_test, 2, 4)
        g2.addWidget(QLabel("Flash speed (each on / off phase)"), 3, 3)
        self.spn_flash = QSpinBox()
        self.spn_flash.setRange(100, 5000)
        self.spn_flash.setSingleStep(100)
        self.spn_flash.setSuffix(" ms")
        g2.addWidget(self.spn_flash, 3, 4)
        g2.addWidget(QLabel("Debounce"), 1, 0)
        self.spn_deb = QSpinBox()
        self.spn_deb.setRange(5, 100)
        self.spn_deb.setSuffix(" ms")
        g2.addWidget(self.spn_deb, 1, 1)
        g2.addWidget(QLabel("Volume at power-up"), 1, 3)
        self.sld_boot_vol = QSlider(Qt.Horizontal)
        self.sld_boot_vol.setRange(0, 30)
        g2.addWidget(self.sld_boot_vol, 1, 4)

        g2.addWidget(QLabel("Lamps when no companion is running:"), 4, 0, 1, 5)
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
        g2.addLayout(lamp_row, 5, 0, 1, 5)

        row2 = QHBoxLayout()
        self.btn_write_cfg = QPushButton("Write to panel")
        self.lbl_cfg = QLabel("Connect to the panel to read its settings")
        self.lbl_cfg.setStyleSheet("color: gray;")
        row2.addWidget(self.btn_write_cfg)
        row2.addWidget(self.lbl_cfg, 1)
        g2.addLayout(row2, 6, 0, 1, 5)
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
        self.log_box.setMaximumHeight(90)
        v.addWidget(self.log_box)

    def _build_sidebar(self) -> QWidget:
        """Searchable list of every profile (one per ride) with the profile buttons under it."""
        box = QWidget()
        box.setFixedWidth(280)
        sv = QVBoxLayout(box)
        sv.setContentsMargins(0, 0, 0, 0)
        head = QLabel("Rides")
        head.setStyleSheet("font-size: 15px; font-weight: bold;")
        sv.addWidget(head)
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Search rides...  (Ctrl+F)")
        self.txt_search.setClearButtonEnabled(True)
        sv.addWidget(self.txt_search)
        self.lst_profiles = QListWidget()
        self.lst_profiles.setUniformItemSizes(True)
        self.lst_profiles.setContextMenuPolicy(Qt.CustomContextMenu)
        self.lst_profiles.setStyleSheet("QListWidget::item { padding: 5px 4px; }")
        sv.addWidget(self.lst_profiles, 1)
        self.lbl_count = QLabel("")
        self.lbl_count.setStyleSheet("color: gray;")
        sv.addWidget(self.lbl_count)

        grid = QGridLayout()
        self.btn_new = QPushButton("New")
        self.btn_dup = QPushButton("Duplicate")
        self.btn_ren = QPushButton("Rename")
        self.btn_del = QPushButton("Delete")
        self.btn_imp = QPushButton("Import...")
        self.btn_exp = QPushButton("Export all...")
        self.btn_imp.setToolTip("Load profiles from a file (a full export, or a single profile)")
        self.btn_exp.setToolTip("Save ALL profiles into one file (a backup you can import anywhere)")
        for i, b in enumerate((self.btn_new, self.btn_dup, self.btn_ren, self.btn_del, self.btn_imp, self.btn_exp)):
            grid.addWidget(b, i // 2, i % 2)
        sv.addLayout(grid)
        note = QLabel("Changes save automatically")
        note.setStyleSheet("color: gray;")
        sv.addWidget(note)
        return box

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

        self.cmb_dispatch.currentIndexChanged.connect(lambda _i: self._on_dispatch_mode())
        self.chk_ack.toggled.connect(lambda _on: self._refresh_cfg_enabled())
        self.updater.check_done.connect(self._on_update_checked)
        self.updater.progress.connect(self._on_update_progress)
        self.updater.download_done.connect(self._on_update_downloaded)
        self.lst_profiles.currentItemChanged.connect(self._on_profile_chosen)
        self.lst_profiles.customContextMenuRequested.connect(self._profile_menu)
        self.txt_search.textChanged.connect(lambda _t: self._apply_filter())
        self.txt_search.returnPressed.connect(self._search_enter)
        QShortcut(QKeySequence.Find, self, activated=self._focus_search)
        self.btn_new.clicked.connect(self._new_profile)
        self.btn_dup.clicked.connect(self._dup_profile)
        self.btn_ren.clicked.connect(self._rename_profile)
        self.btn_del.clicked.connect(self._delete_profile)
        self.btn_imp.clicked.connect(self._import_profile)
        self.btn_exp.clicked.connect(self._export_all_profiles)

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
        self._proto = proto
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
        self._cfg_enabled = on
        for w in (self.spn_startup, self.btn_startup_prev, self.spn_deb, self.spn_flash, self.chk_ack,
                  self.sld_boot_vol, self.btn_write_cfg, *self.idle_boxes.values()):
            w.setEnabled(on)
        self._refresh_cfg_enabled()

    def _refresh_cfg_enabled(self) -> None:
        # the timed lamp test length only matters when the test does not wait for Restart
        self.spn_test.setEnabled(getattr(self, "_cfg_enabled", False) and not self.chk_ack.isChecked())

    def _on_config(self, c: PanelConfig) -> None:
        self._cfg = c
        self.engine.set_panel_config(c)
        self.spn_startup.setValue(c.startup_track)
        self.spn_flash.setValue(c.flash_ms)
        self.chk_ack.setChecked(bool(c.ack_required))
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
            flash_ms=self.spn_flash.value(),
            ack_required=1 if self.chk_ack.isChecked() else 0,
        )
        self._cfg = cfg
        self.engine.set_panel_config(cfg)
        self.link.send(cfg.to_line())
        self.lbl_cfg.setText("Saved to panel")

    def _on_tracks(self, count: int) -> None:
        self.lbl_tracks.setText(f"{count} audio file(s) on SD card")

    def _update_status(self) -> None:
        if not self.link.is_ready:
            return
        e = self.engine
        if self._proto != PROTOCOL_VERSION:
            self.lbl_status.setText(
                f"Connected - FIRMWARE OUT OF DATE (protocol v{self._proto}), reflash the Arduino")
            self.lbl_status.setStyleSheet("font-weight: bold; color: #e03131;")
            return
        if not e.powered:
            state, color = "panel OFF", "#868e96"
        elif not e.fw_ready:
            if self._cfg is not None and self._cfg.ack_required:
                state, color = "lamp test, press Restart to continue", "#f08c00"
            else:
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
        self._refreshing = True
        self.lst_profiles.clear()
        names = self.store.list_names()
        self.lst_profiles.addItems(names)
        row = names.index(select) if select in names else 0
        self.lst_profiles.setCurrentRow(row)
        self._refreshing = False
        self._apply_filter()
        cur = self.lst_profiles.currentItem()
        if cur is not None and cur.isHidden():       # e.g. a new profile that the search text hides
            self.txt_search.clear()
        if cur is not None:
            self.lst_profiles.scrollToItem(cur)
            self._load_profile(cur.text())

    def _apply_filter(self) -> None:
        words = self.txt_search.text().lower().split()
        shown = 0
        for i in range(self.lst_profiles.count()):
            it = self.lst_profiles.item(i)
            hide = not all(w in it.text().lower() for w in words)
            it.setHidden(hide)
            shown += 0 if hide else 1
        total = self.lst_profiles.count()
        noun = "ride" if total == 1 else "rides"
        self.lbl_count.setText(f"{total} {noun}" if shown == total else f"{shown} of {total} {noun}")
        cur = self.lst_profiles.currentItem()
        if cur is not None and not cur.isHidden():
            self.lst_profiles.scrollToItem(cur)

    def _focus_search(self) -> None:
        self.txt_search.setFocus()
        self.txt_search.selectAll()

    def _search_enter(self) -> None:
        """Enter in the search box opens the first match."""
        for i in range(self.lst_profiles.count()):
            it = self.lst_profiles.item(i)
            if not it.isHidden():
                self.lst_profiles.setCurrentItem(it)
                self.lst_profiles.setFocus()
                return

    def _load_profile(self, name: str) -> None:
        p = self.store.load(name)
        if p is None:
            p = Profile(name=name)
        self.profile = p
        self._setting("active_profile", p.name)
        self.lbl_current.setText(f"Editing: {p.name}")
        self._populate_widgets()
        self.engine.set_profile(p)

    @property
    def _dispatch_linked(self) -> bool:
        return self.profile.dispatch_mode != "separate"

    def _binding(self, input_id: str):
        """The binding a table row edits. When dispatch is linked the left row edits the shared one."""
        if self._dispatch_linked and input_id == "dispatch_left":
            return self.profile.dispatch
        return self.profile.bindings[input_id]

    def _populate_widgets(self) -> None:
        p = self.profile
        self._loading = True
        self.cmb_dispatch.setCurrentIndex(DISPATCH_MODES.index(p.dispatch_mode))
        for inp in INPUTS:
            b = self._binding(inp.id)
            label = inp.label
            if self._dispatch_linked and inp.id == "dispatch_left":
                label = "Dispatch (linked)"
            elif self._dispatch_linked and inp.id == "dispatch_right":
                label = "Dispatch right (linked)"
            self.name_items[inp.id].setText(label)
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

    def _save(self) -> None:
        if not self._loading:
            self.store.save(self.profile)

    def _on_profile_chosen(self, cur, _prev) -> None:
        if self._refreshing or cur is None or cur.text() == self.profile.name:
            return
        self._load_profile(cur.text())

    def _profile_menu(self, pos) -> None:
        if self.lst_profiles.itemAt(pos) is None:
            return
        m = QMenu(self)
        m.addAction("Rename...", self._rename_profile)
        m.addAction("Duplicate", self._dup_profile)
        m.addAction("Export this profile only...", self._export_current_profile)
        m.addSeparator()
        m.addAction("Delete", self._delete_profile)
        m.exec(self.lst_profiles.viewport().mapToGlobal(pos))

    def _update_row_enabled(self, input_id: str) -> None:
        mode = self._binding(input_id).mode
        # the right dispatch row is just a mirror of the left one while they are linked
        follows = self._dispatch_linked and input_id == "dispatch_right"
        self.mode_boxes[input_id].setEnabled(not follows)
        self.key_edits[input_id].setEnabled(not follows and mode != "none")
        self.key2_edits[input_id].setEnabled(not follows and mode == "tap_both")
        if self.lamp_boxes[input_id] is not None:
            self.lamp_boxes[input_id].setEnabled(not follows)
        tip = "Linked to the Dispatch (linked) row above" if follows else ""
        for w in (self.mode_boxes[input_id], self.key_edits[input_id], self.key2_edits[input_id]):
            w.setToolTip(tip)

    def _on_dispatch_mode(self) -> None:
        if self._loading:
            return
        self.engine.release_all()
        self.profile.dispatch_mode = self.cmb_dispatch.currentData()
        self._save()
        self._populate_widgets()
        self.engine.set_profile(self.profile)

    def _on_mode(self, input_id: str) -> None:
        if self._loading:
            return
        self.engine.release_all()
        self._binding(input_id).mode = self.mode_boxes[input_id].currentData()
        self._update_row_enabled(input_id)
        self._save()

    def _on_key(self, input_id: str, text: str, second: bool) -> None:
        if self._loading:
            return
        self.engine.release_all()
        b = self._binding(input_id)
        if second:
            b.key2 = text
        else:
            b.key = text
        self._save()

    def _on_lamp(self, input_id: str) -> None:
        if self._loading:
            return
        self._binding(input_id).lamp = self.lamp_boxes[input_id].currentData()
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
        paths, _ = QFileDialog.getOpenFileNames(self, "Import profiles", "", "Profiles (*.json)")
        if not paths:
            return
        profiles, problems = [], []
        for path in paths:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    profiles.extend(parse_import(json.load(f)))
            except (OSError, ValueError, TypeError, AttributeError) as e:
                problems.append(f"{Path(path).name}: {e}")
        if problems:
            QMessageBox.warning(self, "Import", "Could not read:\n" + "\n".join(problems))
        if not profiles:
            return
        mode = "keep_both"
        dupes = self.store.conflicts(profiles)
        if dupes:
            shown = ", ".join(dupes[:4]) + (f" and {len(dupes) - 4} more" if len(dupes) > 4 else "")
            box = QMessageBox(self)
            box.setWindowTitle("Import")
            box.setText(f"{len(dupes)} of the {len(profiles)} profiles already exist here: {shown}.")
            box.setInformativeText("What should happen to the ones that already exist?")
            b_replace = box.addButton("Replace them", QMessageBox.AcceptRole)
            b_keep = box.addButton("Keep both", QMessageBox.AcceptRole)
            b_skip = box.addButton("Skip them", QMessageBox.AcceptRole)
            box.addButton(QMessageBox.Cancel)
            box.exec()
            clicked = box.clickedButton()
            if clicked is b_replace:
                mode = "replace"
            elif clicked is b_keep:
                mode = "keep_both"
            elif clicked is b_skip:
                mode = "skip"
            else:
                return
        saved = self.store.import_profiles(profiles, mode)
        self._refresh_profile_list(select=saved[0] if saved else self.profile.name)
        self.statusBar().showMessage(f"Imported {len(saved)} profile(s)", 6000)

    def _write_export(self, title: str, default_name: str, profiles) -> None:
        path, _ = QFileDialog.getSaveFileName(self, title, default_name, "Profiles (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(export_bundle(profiles, __version__), f, indent=2)
        except OSError as e:
            QMessageBox.warning(self, "Export", f"Could not save the file: {e}")
            return
        self.statusBar().showMessage(f"Exported {len(profiles)} profile(s) to {path}", 8000)

    def _export_all_profiles(self) -> None:
        self._save()
        profiles = self.store.load_all()
        self._write_export(
            "Export all profiles", f"RideSims-Panel-profiles-{time.strftime('%Y-%m-%d')}.json", profiles
        )

    def _export_current_profile(self) -> None:
        self._save()
        self._write_export("Export this profile", f"{self.profile.name}.json", [self.profile])

    # ---------------------------------------------------------- menu/update --
    def _set_theme(self, name: str) -> None:
        self._setting("theme", apply_theme(name))

    def _build_menu(self) -> None:
        view = self.menuBar().addMenu("&View")
        group = QActionGroup(self)
        group.setExclusive(True)
        self.theme_actions = {}
        for name in THEMES:
            act = QAction(f"{name.capitalize()} mode", self)
            act.setCheckable(True)
            act.setChecked(self.store.settings.get("theme") == name)
            act.triggered.connect(lambda _c=False, n=name: self._set_theme(n))
            group.addAction(act)
            view.addAction(act)
            self.theme_actions[name] = act
        m = self.menuBar().addMenu("&Help")
        act = QAction("Check for updates...", self)
        act.triggered.connect(lambda: self._check_updates(manual=True))
        m.addAction(act)
        self.act_auto_update = QAction("Check for updates on launch", self)
        self.act_auto_update.setCheckable(True)
        self.act_auto_update.setChecked(bool(self.store.settings.get("check_updates", True)))
        self.act_auto_update.toggled.connect(lambda on: self._setting("check_updates", on))
        m.addAction(self.act_auto_update)
        m.addSeparator()
        folder = QAction("Open profiles and settings folder", self)
        folder.triggered.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.root))))
        m.addAction(folder)
        about = QAction("About", self)
        about.triggered.connect(lambda: QMessageBox.about(
            self, "About",
            f"RideSims Panel Companion v{__version__}\n\nProfiles and settings are kept in:\n{self.store.root}"))
        m.addAction(about)

    def _check_updates(self, manual: bool) -> None:
        self._manual_update = manual
        if manual:
            self.statusBar().showMessage("Checking for updates...", 4000)
        self.updater.check()

    def _on_update_checked(self, info, err: str) -> None:
        manual = self._manual_update
        if err:
            self.append_log(f"update check: {err}")
            if manual:
                QMessageBox.information(self, "Updates", err)
            return
        if info is None:
            self.append_log(f"up to date (v{__version__})")
            if manual:
                QMessageBox.information(self, "Updates", f"You're up to date (v{__version__}).")
            return
        box = QMessageBox(self)
        box.setWindowTitle("Update available")
        box.setText(f"Version {info.version} is available. You have v{__version__}.")
        notes = (info.notes or "").strip()
        if notes:
            box.setInformativeText(notes[:600])
        if upd.can_self_update():
            go = box.addButton("Update now", QMessageBox.AcceptRole)
        else:
            go = box.addButton("Open download page", QMessageBox.AcceptRole)
        box.addButton("Later", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not go:
            return
        if not upd.can_self_update():
            QDesktopServices.openUrl(QUrl(info.page_url))
            return
        self._dl_dialog = QProgressDialog("Downloading update...", "", 0, 100, self)
        self._dl_dialog.setCancelButton(None)
        self._dl_dialog.setWindowModality(Qt.WindowModal)
        self._dl_dialog.setMinimumDuration(0)
        self._dl_dialog.setValue(0)
        self.updater.download(info)

    def _on_update_progress(self, done: int, total: int) -> None:
        if self._dl_dialog is not None and total > 0:
            self._dl_dialog.setValue(min(99, int(done * 100 / total)))

    def _on_update_downloaded(self, path: str, err: str) -> None:
        if self._dl_dialog is not None:
            self._dl_dialog.close()
            self._dl_dialog = None
        if err:
            QMessageBox.warning(self, "Update failed", err)
            return
        QMessageBox.information(self, "Update", "Downloaded. The app will restart to finish the update.")
        self.engine.release_all()
        self.link.stop()
        upd.apply_update(Path(path))
        QApplication.quit()

    # --------------------------------------------------------------- close --
    def closeEvent(self, ev) -> None:
        self.engine.release_all()
        self.link.stop()
        super().closeEvent(ev)
