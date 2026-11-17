"""Updates from GitHub Releases, the same releases the Mac app uses.

A release carries the Mac files (PII-Vault.zip / .dmg) and the Windows files
(PII-Vault-Setup.exe and PII-Vault-Setup.exe.sha256). PII Vault for Windows looks for the
newest release that has a Windows installer, checks the download against its checksum,
then runs the installer silently. The installer closes PII Vault, swaps in the new version,
and reopens it. Folders, settings, the vault and jobs are untouched (they live outside the
install folder).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO = "stephen-dawkins/pii-vault"
ASSET = "PII-Vault-Setup.exe"
API = f"https://api.github.com/repos/{REPO}/releases?per_page=20"


def _ver(s: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", s)[:3]) or (0,)


def _get(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers={"User-Agent": "PII-Vault-Windows",
                                               "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout)


def check(current: str) -> dict:
    """{state: latest | available | error, version, notes, url, sha_url, message}"""
    try:
        with _get(API) as r:
            releases = json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"state": "error", "message": f"GitHub answered {e.code}. Try again later."}
    except Exception:
        return {"state": "error", "message": "Couldn't reach GitHub. Check your internet connection and try again."}
    best = None
    for rel in releases:
        if rel.get("draft") or rel.get("prerelease"):
            continue
        assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}
        if ASSET not in assets:
            continue
        if best is None or _ver(rel["tag_name"]) > _ver(best[0]["tag_name"]):
            best = (rel, assets)
    if best is None:
        return {"state": "latest", "message": "No Windows release has been published yet."}
    rel, assets = best
    version = rel["tag_name"].lstrip("v")
    if _ver(version) <= _ver(current):
        return {"state": "latest", "version": version}
    return {"state": "available", "version": version, "notes": rel.get("body") or "",
            "url": assets[ASSET], "sha_url": assets.get(ASSET + ".sha256")}


def download_and_install(info: dict, progress) -> None:
    """Download, verify, start the silent installer. The caller then quits the app."""
    if not info.get("sha_url"):
        raise RuntimeError("This release has no checksum, so it wasn't installed.")
    with _get(info["sha_url"]) as r:
        expected = r.read().decode().split()[0].strip().lower()
    dest = Path(tempfile.gettempdir()) / f"PII-Vault-Setup-{info['version']}.exe"
    h = hashlib.sha256()
    with _get(info["url"], timeout=60) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if total:
                progress(done / total)
    if h.hexdigest().lower() != expected:
        dest.unlink(missing_ok=True)
        raise RuntimeError("The download didn't match its checksum, so it wasn't installed. Try again later.")
    if sys.platform != "win32":
        raise RuntimeError("Updates install on Windows only.")
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([str(dest), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                     creationflags=flags, close_fds=True, cwd=os.environ.get("TEMP") or None)
