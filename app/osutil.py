"""The few things that differ between Windows and Linux, in one place:
opening links, finding game processes, starting a launcher detached from
our own process and closing it again.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import psutil
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

WINDOWS = sys.platform.startswith("win")
_GAME_PROCESSES = ("starcitizen.exe", "rsi launcher.exe")  # see GAME_EXE / LAUNCHER_EXE


def open_url(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


GAME_EXE = "starcitizen.exe"
LAUNCHER_EXE = "rsi launcher.exe"


def running_game_processes() -> set[str]:
    """Which of StarCitizen.exe / RSI Launcher.exe are running right now
    (lower-case names), in a single process scan."""
    found: set[str] = set()
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (proc.info["name"] or "").lower()
            argv0 = ((proc.info["cmdline"] or [""])[0] or "").lower().replace("\\", "/")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        for p in _GAME_PROCESSES:
            if name == p or argv0.endswith("/" + p) or argv0 == p:
                found.add(p)
    return found


def is_game_running() -> bool:
    """True if Star Citizen or the RSI Launcher is running. Under Wine the
    Windows executable names show up in the command line rather than as
    the process name, so both are checked (the program itself only, not
    any command line that merely mentions it).
    """
    return bool(running_game_processes())


def spawn(path: Path) -> subprocess.Popen:
    """Starts a launcher in its own process group/session so it outlives
    nothing of ours and can be closed as a whole. Shell scripts (LUG
    Helper's sc-launch.sh) run through bash.
    """
    argv = [str(path)]
    if path.suffix == ".sh":
        argv = ["/usr/bin/env", "bash", *argv]
    kwargs: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        kwargs["cwd"] = str(path.parent)
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(argv, **kwargs)


def terminate_tree(pid: int, timeout: float = 5.0) -> None:
    """Asks a process and everything it started to exit, then kills
    whatever is still around after `timeout` seconds.
    """
    try:
        root = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    procs = root.children(recursive=True) + [root]
    for p in procs:
        try:
            p.terminate()
        except psutil.NoSuchProcess:
            pass
    _gone, alive = psutil.wait_procs(procs, timeout=timeout)
    for p in alive:
        try:
            p.kill()
        except psutil.NoSuchProcess:
            pass


def make_executable(path: Path) -> None:
    """Sets the executable bit where there is one (AppImages downloaded
    through a browser usually lack it)."""
    if not WINDOWS and not os.access(path, os.X_OK):
        path.chmod(path.stat().st_mode | 0o111)
