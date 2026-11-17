"""Runs the PII Vault engine, exactly like the Mac app does: one engine process per command,
JSON back on stdout. Running it as its own process keeps a crash in a document library from
taking the window down, and keeps each job's state separate.

Packaged app: piivault-engine.exe sits next to PIIVault.exe.
From source: python -m piivault, with the repo's engine folder on the path.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class EngineError(Exception):
    pass


def _base_cmd() -> tuple[list[str], dict]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).with_name("piivault-engine.exe")
        return [str(exe)], env
    engine_dir = Path(__file__).resolve().parents[2] / "engine"
    env["PYTHONPATH"] = str(engine_dir) + os.pathsep + env.get("PYTHONPATH", "")
    return [sys.executable, "-m", "piivault"], env


def run(*args: str, timeout: int = 3600) -> dict:
    cmd, env = _base_cmd()
    try:
        p = subprocess.run(cmd + [str(a) for a in args], capture_output=True, env=env,
                           timeout=timeout, creationflags=NO_WINDOW)
    except FileNotFoundError:
        raise EngineError("The PII Vault engine is missing. Reinstall PII Vault.")
    except subprocess.TimeoutExpired:
        raise EngineError("The engine took too long and was stopped.")
    text = p.stdout.decode("utf-8", errors="replace").strip()
    try:
        data = json.loads(text) if text else {}
    except json.JSONDecodeError:
        tail = p.stderr.decode("utf-8", errors="replace").strip().splitlines()[-3:]
        raise EngineError("The engine returned something unexpected. " + " ".join(tail))
    if p.returncode != 0 or (isinstance(data, dict) and "error" in data and len(data) <= 2):
        raise EngineError(data.get("error") if isinstance(data, dict) else "The engine stopped with an error.")
    return data
