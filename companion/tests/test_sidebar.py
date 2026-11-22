import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog  # noqa: E402

from ridesims_panel.profiles import Profile, ProfileStore  # noqa: E402
from ridesims_panel.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(app, tmp_path):
    store = ProfileStore(tmp_path)
    store.settings["autoconnect"] = False
    store.settings["check_updates"] = False
    for n in ("Maxx Force", "Goliath", "Raging Bull", "Ride 10", "Ride 2", "Batman The Ride"):
        store.save(Profile(name=n))
    w = MainWindow(store)
    yield w
    w.close()


def visible(w):
    lst = w.lst_profiles
    return [lst.item(i).text() for i in range(lst.count()) if not lst.item(i).isHidden()]


def test_list_shows_every_profile_sorted(win):
    lst = win.lst_profiles
    assert [lst.item(i).text() for i in range(lst.count())] == [
        "Batman The Ride", "Goliath", "Maxx Force", "Raging Bull", "Ride 2", "Ride 10"]
    assert win.lbl_count.text() == "6 rides"


def test_search_filters_and_enter_opens_first_match(win):
    win.txt_search.setText("ride")
    assert visible(win) == ["Batman The Ride", "Ride 2", "Ride 10"]
    assert win.lbl_count.text() == "3 of 6 rides"
    win.txt_search.setText("ride 1")
    assert visible(win) == ["Ride 10"]
    win.txt_search.returnPressed.emit()
    assert win.profile.name == "Ride 10"
    assert "Ride 10" in win.lbl_current.text()
    win.txt_search.clear()
    assert len(visible(win)) == 6


def test_clicking_a_ride_switches_profile(win):
    item = win.lst_profiles.findItems("Goliath", Qt.MatchExactly)[0]
    win.lst_profiles.setCurrentItem(item)
    assert win.profile.name == "Goliath"
    assert win.store.settings["active_profile"] == "Goliath"


def test_edits_save_to_the_selected_profile(win):
    win.lst_profiles.setCurrentRow(1)
    name = win.profile.name
    win.key_edits["gates"].set_text("q")
    win.key_edits["gates"].changed.emit("q")
    assert win.store.load(name).bindings["gates"].key == "q"


def test_new_profile_hidden_by_search_clears_the_search(win, monkeypatch):
    win.txt_search.setText("goliath")
    monkeypatch.setattr(win, "_ask_name", lambda *a, **k: "Zzz Brand New")
    win._new_profile()
    assert win.profile.name == "Zzz Brand New"
    assert win.txt_search.text() == ""
    assert "Zzz Brand New" in visible(win)


def test_export_button_writes_all_profiles(win, tmp_path, monkeypatch):
    out = tmp_path / "all.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
    win._export_all_profiles()
    data = json.loads(out.read_text("utf-8"))
    assert len(data["profiles"]) == 6
    assert {p["name"] for p in data["profiles"]} == {
        "Maxx Force", "Goliath", "Raging Bull", "Ride 10", "Ride 2", "Batman The Ride"}


def test_export_current_only_from_menu_action(win, tmp_path, monkeypatch):
    out = tmp_path / "one.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
    win._export_current_profile()
    data = json.loads(out.read_text("utf-8"))
    assert [p["name"] for p in data["profiles"]] == [win.profile.name]


def test_import_all_into_empty_store(app, tmp_path, monkeypatch):
    src = ProfileStore(tmp_path / "src")
    for n in ("A", "B", "C"):
        src.save(Profile(name=n))
    from ridesims_panel.profiles import export_bundle
    f = tmp_path / "bundle.json"
    f.write_text(json.dumps(export_bundle(src.load_all())), "utf-8")

    store = ProfileStore(tmp_path / "dst")
    store.settings["autoconnect"] = False
    store.settings["check_updates"] = False
    w = MainWindow(store)       # starts with just "Default"
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda *a, **k: ([str(f)], "")))
    w._import_profile()
    assert store.list_names() == ["A", "B", "C", "Default"]
    w.close()


def test_dark_by_default_and_switchable(win):
    from PySide6.QtGui import QPalette
    assert win.store.settings["theme"] == "dark"
    assert win.theme_actions["dark"].isChecked()
    dark_bg = QApplication.instance().palette().color(QPalette.Window).lightness()
    win.theme_actions["light"].trigger()
    assert win.store.settings["theme"] == "light"
    assert QApplication.instance().palette().color(QPalette.Window).lightness() > dark_bg
    win.theme_actions["dark"].trigger()
    assert win.store.settings["theme"] == "dark"
    assert QApplication.instance().palette().color(QPalette.Window).lightness() == dark_bg
