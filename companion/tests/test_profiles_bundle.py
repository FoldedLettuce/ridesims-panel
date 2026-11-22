import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from ridesims_panel.profiles import (  # noqa: E402
    Binding, Profile, ProfileStore, export_bundle, natural_key, parse_import,
)
from ridesims_panel.updater import pick_release  # noqa: E402


def make(store, *names):
    for n in names:
        p = Profile(name=n)
        p.bindings["gates"] = Binding("tap", n[:1].lower(), "", "off")
        store.save(p)


def test_names_sort_naturally(tmp_path):
    store = ProfileStore(tmp_path)
    make(store, "Ride 10", "ride 2", "Alpha", "Ride 1")
    assert store.list_names() == ["Alpha", "Ride 1", "ride 2", "Ride 10"]
    assert natural_key("Ride 2") < natural_key("Ride 10")


def test_export_bundle_has_every_profile(tmp_path):
    store = ProfileStore(tmp_path)
    make(store, "Maxx Force", "Goliath", "Raging Bull")
    data = json.loads(json.dumps(export_bundle(store.load_all(), "9.9.9")))
    assert data["type"] == "ridesims-profiles"
    assert [p["name"] for p in data["profiles"]] == ["Goliath", "Maxx Force", "Raging Bull"]
    assert data["profiles"][0]["bindings"]["gates"]["key"] == "g"


def test_backup_restores_on_a_fresh_machine(tmp_path):
    a = ProfileStore(tmp_path / "a")
    make(a, "One", "Two", "Three")
    bundle = json.loads(json.dumps(export_bundle(a.load_all())))
    b = ProfileStore(tmp_path / "b")
    saved = b.import_profiles(parse_import(bundle))
    assert saved == ["One", "Three", "Two"] or sorted(saved) == ["One", "Three", "Two"]
    assert [p.to_dict() for p in b.load_all()] == [p.to_dict() for p in a.load_all()]


def test_old_single_profile_file_still_imports():
    single = Profile(name="Old export").to_dict()
    got = parse_import(single)
    assert [p.name for p in got] == ["Old export"]


def test_bad_files_are_rejected():
    for bad in ({"hello": 1}, [], 5, {"profiles": []}):
        with pytest.raises(ValueError):
            parse_import(bad)


def test_import_conflicts(tmp_path):
    store = ProfileStore(tmp_path)
    make(store, "Maxx Force", "Goliath")
    other = ProfileStore(tmp_path / "other")
    make(other, "Maxx Force", "Batman")
    other_profiles = other.load_all()
    assert store.conflicts(other_profiles) == ["Maxx Force"]

    store.import_profiles([Profile.from_dict(p.to_dict()) for p in other_profiles], "skip")
    assert store.list_names() == ["Batman", "Goliath", "Maxx Force"]

    store.import_profiles([Profile.from_dict(p.to_dict()) for p in other_profiles], "keep_both")
    assert store.list_names() == ["Batman", "Batman 2", "Goliath", "Maxx Force", "Maxx Force 2"]

    mf = Profile(name="Maxx Force")
    mf.bindings["gates"] = Binding("hold", "z", "", "off")
    store.import_profiles([mf], "replace")
    assert store.load("Maxx Force").bindings["gates"].key == "z"
    assert "Maxx Force 3" not in store.list_names()


def release(tag, *assets):
    return {"tag_name": tag, "draft": False, "prerelease": True, "body": "", "html_url": "x",
            "assets": [{"name": a, "browser_download_url": f"https://example.invalid/{a}", "size": 1} for a in assets]}


def test_installed_copies_pick_the_setup_asset():
    rels = [
        release("v0.0.4", "RideSimsPanel-0.0.4.exe"),
        release("v0.0.5", "RideSimsPanel-0.0.5.exe", "RideSimsPanel-Setup-0.0.5.exe"),
    ]
    portable = pick_release(rels, "0.0.4")
    assert portable.asset_name == "RideSimsPanel-0.0.5.exe"
    setup = pick_release(rels, "0.0.4", want_setup=True)
    assert setup.asset_name == "RideSimsPanel-Setup-0.0.5.exe"
    # a release without an installer is not offered to installed copies
    assert pick_release([release("v0.0.6", "RideSimsPanel-0.0.6.exe")], "0.0.5", want_setup=True) is None
