"""Check GitHub releases for a newer version, download it, and apply it.

Two kinds of install are handled:
  * installed with the Setup program: download RideSimsPanel-Setup-<version>.exe and run it silently
    (it upgrades in place, keeps the profiles, and starts the app again);
  * a loose RideSimsPanel-<version>.exe: download the new exe next to the old one and swap them.

Needs the repo to be public (or at least its releases to be readable without a token).
The app only ever downloads .exe assets from this project's own releases page.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from PySide6.QtCore import QObject, Signal

from . import __version__
from .profiles import data_dir

REPO = "FoldedLettuce/ridesims-panel"
API_URL = f"https://api.github.com/repos/{REPO}/releases?per_page=15"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
ASSET_RE = re.compile(r"^RideSimsPanel-[0-9][^/\\]*\.exe$", re.I)          # loose exe
SETUP_RE = re.compile(r"^RideSimsPanel-Setup-[0-9][^/\\]*\.exe$", re.I)    # installer
USER_AGENT = f"RideSimsPanel/{__version__} (updater)"


def parse_version(text: str) -> Optional[Tuple[int, int, int]]:
    m = re.match(r"\s*v?(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(x) for x in m.groups()) if m else None   # type: ignore[return-value]


@dataclass
class ReleaseInfo:
    version: str
    tag: str
    notes: str
    page_url: str
    asset_name: str
    asset_url: str
    asset_size: int
    sha256: str


def pick_release(releases: list, current: str, want_setup: bool = False) -> Optional[ReleaseInfo]:
    """Newest non-draft release (pre-releases count) that has the right exe, if newer than `current`.

    want_setup picks releases that carry the installer, for copies that were installed with it."""
    pattern = SETUP_RE if want_setup else ASSET_RE
    cur = parse_version(current)
    best = None
    for r in releases:
        if r.get("draft"):
            continue
        v = parse_version(r.get("tag_name", ""))
        if v is None:
            continue
        asset = next((a for a in r.get("assets", []) if pattern.match(a.get("name", ""))), None)
        if asset is None:
            continue
        if best is None or v > best[0]:
            best = (v, r, asset)
    if best is None or cur is None or best[0] <= cur:
        return None
    v, r, a = best
    digest = a.get("digest") or ""
    return ReleaseInfo(
        version=".".join(str(x) for x in v),
        tag=r.get("tag_name", ""),
        notes=r.get("body") or "",
        page_url=r.get("html_url") or RELEASES_PAGE,
        asset_name=a["name"],
        asset_url=a["browser_download_url"],
        asset_size=int(a.get("size") or 0),
        sha256=digest.split(":", 1)[1].lower() if digest.lower().startswith("sha256:") else "",
    )


def _open(url: str, timeout: float = 20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_latest(current: str, api_url: Optional[str] = None, want_setup: Optional[bool] = None) -> Optional[ReleaseInfo]:
    """Raises RuntimeError with a friendly message if the releases cannot be read."""
    try:
        with _open(api_url or API_URL) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise RuntimeError("Could not read the releases. The GitHub repo is probably still private.")
        if e.code == 403:
            raise RuntimeError("GitHub is rate limiting update checks right now. Try again later.")
        raise RuntimeError(f"GitHub answered HTTP {e.code}.")
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise RuntimeError(f"Could not reach GitHub ({e}).")
    return pick_release(data, current, is_installed() if want_setup is None else want_setup)


def download_asset(
    info: ReleaseInfo,
    dest_dir: Path,
    progress: Optional[Callable[[int, int], None]] = None,
) -> Path:
    """Download to dest_dir/<asset_name>, verify, return the path. Raises RuntimeError on any problem."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / info.asset_name
    part = dest_dir / (info.asset_name + ".part")
    sha = hashlib.sha256()
    try:
        with _open(info.asset_url, timeout=30) as resp, open(part, "wb") as f:
            total = int(resp.headers.get("Content-Length") or info.asset_size or 0)
            done = 0
            first = True
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                if first:
                    if chunk[:2] != b"MZ":
                        raise RuntimeError("The download is not a Windows program.")
                    first = False
                f.write(chunk)
                sha.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except (urllib.error.URLError, OSError) as e:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"Download failed ({e}).")
    except RuntimeError:
        part.unlink(missing_ok=True)
        raise
    if info.asset_size and part.stat().st_size != info.asset_size:
        part.unlink(missing_ok=True)
        raise RuntimeError("The download is incomplete.")
    if info.sha256 and sha.hexdigest() != info.sha256:
        part.unlink(missing_ok=True)
        raise RuntimeError("The download failed its checksum, not installing it.")
    os.replace(part, final)
    return final


def can_self_update() -> bool:
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def is_installed() -> bool:
    """True when running from a copy that the Setup program installed (it leaves unins000.exe beside the app)."""
    return can_self_update() and (Path(sys.executable).parent / "unins000.exe").exists()


def download_dir() -> Path:
    """Installer downloads go to the data folder. A loose exe goes next to itself when we can write there."""
    if is_installed():
        return data_dir() / "updates"
    if can_self_update():
        d = Path(sys.executable).parent
        try:
            probe = d / ".rsp_write_test"
            probe.write_text("x")
            probe.unlink()
            return d
        except OSError:
            pass
    return data_dir() / "updates"


def cleanup_downloads() -> None:
    """Delete installers left over from earlier updates."""
    d = data_dir() / "updates"
    try:
        for f in d.glob("RideSimsPanel-*"):
            f.unlink(missing_ok=True)
    except OSError:
        pass


def install_and_relaunch(setup_exe: Path) -> None:
    """Run the downloaded installer silently. It replaces the app in place and starts it again."""
    env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
    CREATE_NO_WINDOW, DETACHED_PROCESS = 0x08000000, 0x00000008
    subprocess.Popen(
        [str(setup_exe), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
        creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS, close_fds=True, env=env,
    )


def apply_update(downloaded: Path) -> None:
    if is_installed():
        install_and_relaunch(downloaded)
    else:
        swap_and_relaunch(downloaded)


def swap_and_relaunch(new_exe: Path) -> None:
    """Start a helper that waits for this exe to exit, deletes it, and launches the new one."""
    old = Path(sys.executable)
    bat = Path(tempfile.gettempdir()) / "ridesims_panel_update.bat"
    bat.write_text(
        "@echo off\r\n"
        "set n=0\r\n"
        ":wait\r\n"
        "set /a n+=1\r\n"
        "ping 127.0.0.1 -n 2 >nul\r\n"
        f'del /f /q "{old}" >nul 2>&1\r\n'
        f'if exist "{old}" if %n% LSS 40 goto wait\r\n'
        "set PYINSTALLER_RESET_ENVIRONMENT=1\r\n"
        f'start "" "{new_exe}"\r\n'
        '(goto) 2>nul & del "%~f0"\r\n',
        encoding="ascii",
    )
    env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
    CREATE_NO_WINDOW, DETACHED_PROCESS = 0x08000000, 0x00000008
    subprocess.Popen(["cmd", "/c", str(bat)], creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
                     close_fds=True, env=env)


class Updater(QObject):
    """Runs checks and downloads on background threads and reports back with signals."""

    check_done = Signal(object, str)      # ReleaseInfo or None, error text ("" if fine)
    progress = Signal(int, int)           # bytes done, total
    download_done = Signal(str, str)      # path, error text

    def __init__(self, parent: Optional[QObject] = None, api_url: Optional[str] = None) -> None:
        super().__init__(parent)
        self.api_url = api_url

    def check(self) -> None:
        def work() -> None:
            try:
                info = fetch_latest(__version__, self.api_url)
                self.check_done.emit(info, "")
            except RuntimeError as e:
                self.check_done.emit(None, str(e))
        threading.Thread(target=work, daemon=True).start()

    def download(self, info: ReleaseInfo) -> None:
        def work() -> None:
            try:
                path = download_asset(info, download_dir(), lambda d, t: self.progress.emit(d, t))
                self.download_done.emit(str(path), "")
            except RuntimeError as e:
                self.download_done.emit("", str(e))
        threading.Thread(target=work, daemon=True).start()
