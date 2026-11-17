"""Ollama on Windows: find it, open it, and download a model with progress.

Ollama is the free app that runs the small private name-finding model. Its Windows installer
puts it in %LOCALAPPDATA%\\Programs\\Ollama and starts it from the system tray at sign-in.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

URL = os.environ.get("PIIVAULT_OLLAMA_URL", "http://localhost:11434")
DOWNLOAD_URL = "https://ollama.com/download/OllamaSetup.exe"
DOWNLOAD_PAGE = "https://ollama.com/download/windows"
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def running() -> bool:
    try:
        with urllib.request.urlopen(URL + "/api/tags", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def app_path() -> Path | None:
    candidates = []
    for root, sub in ((os.environ.get("LOCALAPPDATA"), "Programs"), (os.environ.get("ProgramFiles"), "")):
        if root:
            base = Path(root) / sub / "Ollama" if sub else Path(root) / "Ollama"
            candidates += [base / "ollama app.exe", base / "ollama.exe"]
    return next((c for c in candidates if c.exists()), None)


def state() -> str:
    """not_installed | installed | running"""
    if running():
        return "running"
    return "installed" if app_path() else "not_installed"


def open_app() -> bool:
    p = app_path()
    if not p:
        return False
    if p.name == "ollama.exe":
        subprocess.Popen([str(p), "serve"], creationflags=NO_WINDOW)
    else:
        subprocess.Popen([str(p)], creationflags=NO_WINDOW)
    return True


def pull(model: str, progress) -> None:
    """Download a model. progress(fraction 0..1, status text) is called as it goes."""
    body = json.dumps({"model": model, "stream": True}).encode()
    req = urllib.request.Request(URL + "/api/pull", data=body, headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Ollama refused the download (HTTP {e.code}).")
    totals: dict[str, tuple[int, int]] = {}
    with resp:
        for line in resp:
            if not line.strip():
                continue
            msg = json.loads(line)
            if msg.get("error"):
                raise RuntimeError(msg["error"])
            if msg.get("total"):
                totals[msg.get("digest", "")] = (msg.get("completed", 0), msg["total"])
            done = sum(c for c, _ in totals.values())
            total = sum(t for _, t in totals.values()) or 1
            progress(min(done / total, 1.0), msg.get("status", ""))
            if msg.get("status") == "success":
                progress(1.0, "success")
                return
