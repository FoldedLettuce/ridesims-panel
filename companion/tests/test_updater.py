import hashlib
import http.server
import json
import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ridesims_panel import updater  # noqa: E402
from ridesims_panel.updater import ReleaseInfo, Updater, fetch_latest, parse_version, pick_release  # noqa: E402


def rel(tag, assets=("RideSimsPanel-%s.exe",), draft=False, pre=True):
    return {
        "tag_name": tag, "draft": draft, "prerelease": pre, "body": "notes",
        "html_url": f"https://example.invalid/{tag}",
        "assets": [{"name": a % tag.lstrip("v"), "browser_download_url": f"https://example.invalid/{tag}/{a % tag.lstrip('v')}",
                    "size": 10} for a in assets],
    }


def test_parse_version():
    assert parse_version("v0.0.2") == (0, 0, 2)
    assert parse_version("1.10.3") == (1, 10, 3)
    assert parse_version("nope") is None
    assert parse_version("v0.0.10") > parse_version("v0.0.9")


def test_pick_release():
    rels = [rel("v0.0.1"), rel("v0.0.3"), rel("v0.0.2"), rel("v0.0.9", draft=True),
            rel("v0.1.0", assets=("RideSimsPanel-Firmware-%s.hex",))]
    got = pick_release(rels, "0.0.2")
    assert got and got.version == "0.0.3" and got.asset_name == "RideSimsPanel-0.0.3.exe"
    assert pick_release(rels, "0.0.3") is None      # already current
    assert pick_release(rels, "0.5.0") is None      # newer than anything published
    assert pick_release([], "0.0.1") is None


def test_pick_release_digest():
    r = rel("v0.0.5")
    r["assets"][0]["digest"] = "sha256:" + "AB" * 32
    assert pick_release([r], "0.0.1").sha256 == "ab" * 32


class Server:
    def __init__(self, routes):
        outer = self
        self.routes = routes

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = outer.routes.get(self.path)
                if body is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()


def pump_until(cond, ms=5000):
    app = QApplication.instance() or QApplication([])
    loop = QEventLoop()
    t = QTimer()
    t.timeout.connect(lambda: loop.quit() if cond() else None)
    t.start(20)
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    t.stop()


def test_check_and_download_roundtrip(tmp_path, monkeypatch):
    exe = b"MZ" + os.urandom(200_000)
    srv = Server({})
    base = f"http://127.0.0.1:{srv.port}"
    release = rel("v9.9.9")
    release["assets"][0].update({
        "browser_download_url": f"{base}/dl/RideSimsPanel-9.9.9.exe",
        "size": len(exe), "digest": "sha256:" + hashlib.sha256(exe).hexdigest()})
    srv.routes["/releases"] = json.dumps([release, rel("v0.0.1")]).encode()
    srv.routes["/dl/RideSimsPanel-9.9.9.exe"] = exe
    monkeypatch.setattr(updater, "download_dir", lambda: tmp_path)
    QApplication.instance() or QApplication([])
    try:
        u = Updater(api_url=f"{base}/releases")
        got = {}
        u.check_done.connect(lambda info, err: got.update(info=info, err=err, checked=True))
        u.check()
        pump_until(lambda: "checked" in got)
        assert got["err"] == "" and got["info"].version == "9.9.9"

        prog = []
        u.progress.connect(lambda d, t: prog.append((d, t)))
        u.download_done.connect(lambda path, err: got.update(path=path, derr=err, downloaded=True))
        u.download(got["info"])
        pump_until(lambda: "downloaded" in got)
        assert got["derr"] == "", got
        assert (tmp_path / "RideSimsPanel-9.9.9.exe").read_bytes() == exe
        assert prog and prog[-1][0] == len(exe)
        assert not list(tmp_path.glob("*.part"))
    finally:
        srv.close()


def test_download_rejects_bad_checksum_and_non_exe(tmp_path):
    good = b"MZ" + b"x" * 1000
    srv = Server({"/a.exe": good, "/b.exe": b"<html>not an exe</html>"})
    try:
        base = f"http://127.0.0.1:{srv.port}"
        info = ReleaseInfo("1.0.0", "v1.0.0", "", "", "RideSimsPanel-1.0.0.exe", f"{base}/a.exe", len(good), "00" * 32)
        with pytest.raises(RuntimeError, match="checksum"):
            updater.download_asset(info, tmp_path)
        assert not list(tmp_path.iterdir())
        info.asset_url = f"{base}/b.exe"
        info.sha256 = ""
        with pytest.raises(RuntimeError, match="not a Windows program"):
            updater.download_asset(info, tmp_path)
        assert not list(tmp_path.iterdir())
    finally:
        srv.close()


def test_private_repo_message():
    srv = Server({})
    try:
        with pytest.raises(RuntimeError, match="private"):
            fetch_latest("0.0.1", f"http://127.0.0.1:{srv.port}/nothing")
    finally:
        srv.close()
