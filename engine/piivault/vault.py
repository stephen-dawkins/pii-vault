"""Encrypted token vault.

One global vault maps real values <-> tokens such as PERSON_0042. The same value
always gets the same token, across every file and every job, so the AI's counts,
joins and follow-up edits stay consistent and any output can be rehydrated later.

Storage (never inside a folder Cowork can read):
    ~/Library/Application Support/PII Vault/vault.enc   (Fernet encrypted JSON)
    ~/Library/Application Support/PII Vault/jobs/<id>.json (job records, no PII values)
The encryption key lives in the macOS Keychain (service "PII Vault").
Windows: %LOCALAPPDATA%\\PII Vault\\vault.enc, key in Windows Credential Manager ("PII Vault").
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet

KEYCHAIN_SERVICE = "PII Vault"
KEYCHAIN_ACCOUNT = "vault-key"

# Token pattern: CATEGORY_0001. Categories are upper-case letters only.
TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_])([A-Z]{2,12})_(\d{4,6})(?![0-9])")

CATEGORIES = {
    "PERSON": "Person name",
    "EMAIL": "Email address",
    "PHONE": "Phone number",
    "SSN": "Social Security number",
    "ID": "Student / employee ID",
    "DOB": "Date of birth",
    "ADDRESS": "Street address",
    "ACCOUNT": "Account / card number",
    "IP": "IP address",
    "URL": "Personal URL",
    "OTHER": "Other identifier",
}


def app_support_dir() -> Path:
    override = os.environ.get("PIIVAULT_HOME")
    if override:
        p = Path(override).expanduser()
    elif sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / "PII Vault"
    elif sys.platform == "win32":
        from .winplat import local_appdata
        p = local_appdata()
    else:
        p = Path.home() / ".piivault"
    p.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p, 0o700)
    except OSError:
        pass
    return p


def _keychain_get() -> bytes | None:
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT, "-w"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip().encode()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _keychain_set(key: bytes) -> bool:
    try:
        out = subprocess.run(
            ["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT,
             "-w", key.decode()],
            capture_output=True, text=True, timeout=10,
        )
        return out.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def load_key() -> bytes:
    """Keychain on macOS. Elsewhere (testing) a 0600 key file in the app dir."""
    env = os.environ.get("PIIVAULT_KEY")
    if env:
        return env.encode()
    if sys.platform == "darwin":
        key = _keychain_get()
        if key:
            return key
        key = Fernet.generate_key()
        if not _keychain_set(key):
            raise RuntimeError("Could not save the vault key to the macOS Keychain.")
        return key
    if sys.platform == "win32":
        from .winplat import credential_get, credential_set
        key = credential_get()
        if key:
            return key
        if (app_support_dir() / "vault.enc").exists():
            raise RuntimeError("The vault key is missing from Windows Credential Manager, so the vault can't be opened.")
        key = Fernet.generate_key()
        if not credential_set(key):
            raise RuntimeError("Could not save the vault key to Windows Credential Manager.")
        return key
    kf = app_support_dir() / "vault.key"
    if kf.exists():
        return kf.read_bytes().strip()
    key = Fernet.generate_key()
    kf.write_bytes(key)
    os.chmod(kf, 0o600)
    return key


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", str(value)).strip().casefold()


class Vault:
    """value <-> token map. Thread safe; call save() to persist."""

    def __init__(self, path: Path | None = None):
        self.path = path or (app_support_dir() / "vault.enc")
        self._fernet = Fernet(load_key())
        self._lock = threading.Lock()
        self.by_key: dict[str, str] = {}      # "CAT|normalized value" -> token
        self.by_token: dict[str, str] = {}    # token -> original value (first seen spelling)
        self.counters: dict[str, int] = {}
        if self.path.exists():
            data = json.loads(self._fernet.decrypt(self.path.read_bytes()))
            self.by_key = data["by_key"]
            self.by_token = data["by_token"]
            self.counters = data["counters"]

    def token_for(self, value: str, category: str) -> str:
        category = category if category in CATEGORIES else "OTHER"
        k = f"{category}|{_norm(value)}"
        with self._lock:
            tok = self.by_key.get(k)
            if tok:
                return tok
            n = self.counters.get(category, 0) + 1
            self.counters[category] = n
            tok = f"{category}_{n:04d}"
            self.by_key[k] = tok
            self.by_token[tok] = str(value).strip()
            return tok

    def value_for(self, token: str) -> str | None:
        return self.by_token.get(token)

    def save(self) -> None:
        data = json.dumps({"by_key": self.by_key, "by_token": self.by_token, "counters": self.counters})
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(self._fernet.encrypt(data.encode()))
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    def known_values(self) -> dict[str, str]:
        """Every value already in the vault (plus 'First Last' for 'Last, First' names),
        so a person tokenized in one file is caught in every later file."""
        out: dict[str, str] = {}
        for tok, val in self.by_token.items():
            cat = tok.rsplit("_", 1)[0]
            if cat in ("DOB",) or len(val) < 3:
                continue
            # a one-word name ("Hope") only matches with exact capitalization, so "hope" stays
            out[val] = "PERSON~" if (cat == "PERSON" and len(val.split()) == 1) else cat
            if cat == "PERSON":
                if "," in val:
                    last, first = [p.strip() for p in val.split(",", 1)]
                    if first and last:
                        out[f"{first} {last}"] = "PERSON"
                from .detect import name_parts
                for part in name_parts(val):
                    out.setdefault(part, "PERSON~")
        return out

    def stats(self) -> dict:
        return {"tokens": len(self.by_token), "by_category": dict(self.counters)}


# ---------------------------------------------------------------- job records

def jobs_dir() -> Path:
    d = app_support_dir() / "jobs"
    d.mkdir(exist_ok=True)
    return d


def new_job_id() -> str:
    return datetime.now().strftime("JOB-%Y%m%d-%H%M%S")


def save_job(job: dict) -> None:
    (jobs_dir() / f"{job['id']}.json").write_text(json.dumps(job, indent=2))


def load_job(job_id: str) -> dict | None:
    p = jobs_dir() / f"{job_id}.json"
    return json.loads(p.read_text()) if p.exists() else None


def list_jobs() -> list[dict]:
    out = []
    for p in sorted(jobs_dir().glob("JOB-*.json"), reverse=True):
        try:
            out.append(json.loads(p.read_text()))
        except Exception:
            continue
    return out
