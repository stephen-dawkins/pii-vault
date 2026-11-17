"""Windows pieces of the engine. Everything here has a Mac twin elsewhere in the engine:

    Mac                                   Windows (this file)
    ~/Library/Application Support/...     %LOCALAPPDATA%/PII Vault  (not Roaming, so it never syncs)
    macOS Keychain                        Windows Credential Manager
    Apple Vision OCR (ocrmac)             Windows OCR (Windows.Media.Ocr, built into Windows 10/11)
    Word via AppleScript                  Word via COM automation
    WebKit HTML to PDF (in the Swift app) Microsoft Edge, headless, print to PDF
    ~/Downloads                           the Downloads known folder (it can be moved, so we ask Windows)

Nothing in this file sends data anywhere; it all runs on this PC.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
NO_WINDOW = 0x08000000 if IS_WINDOWS else 0  # CREATE_NO_WINDOW: no console flashes on screen


# ------------------------------------------------------------------ folders
def local_appdata() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "PII Vault"


def downloads_dir() -> Path:
    """The real Downloads folder, even if the person moved it (Properties > Location)."""
    if IS_WINDOWS:
        try:
            import ctypes
            from ctypes import wintypes
            import uuid

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                            ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

            u = uuid.UUID("{374DE290-123F-4565-9164-39C4925E467B}")  # FOLDERID_Downloads
            g = GUID(u.fields[0], u.fields[1], u.fields[2], (ctypes.c_ubyte * 8)(*u.bytes[8:]))
            p = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(p)) == 0:
                path = p.value
                ctypes.windll.ole32.CoTaskMemFree(p)
                if path:
                    return Path(path)
        except Exception:
            pass
    return Path.home() / "Downloads"


# --------------------------------------------------------------- vault key
CRED_SERVICE = "PII Vault"
CRED_ACCOUNT = "vault-key"


def _keyring():
    # Use the Windows backend directly (no plugin discovery, which is fragile in a packaged app).
    from keyring.backends.Windows import WinVaultKeyring
    return WinVaultKeyring()


def credential_get() -> bytes | None:
    try:
        v = _keyring().get_password(CRED_SERVICE, CRED_ACCOUNT)
        return v.encode() if v else None
    except Exception:
        return None


def credential_set(key: bytes) -> bool:
    try:
        _keyring().set_password(CRED_SERVICE, CRED_ACCOUNT, key.decode())
        return credential_get() == key
    except Exception:
        return False


# --------------------------------------------------------------------- OCR
def windows_ocr_available() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        from winrt.windows.media.ocr import OcrEngine
        return OcrEngine.try_create_from_user_profile_languages() is not None
    except Exception:
        return False


def windows_ocr(image_path: str) -> list[tuple[str, tuple[float, float, float, float]]]:
    """OCR an image with the OCR engine built into Windows.
    Returns (word, (x, y, width, height) in image pixels), in reading order."""
    import asyncio
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.storage import StorageFile, FileAccessMode

    async def run():
        f = await StorageFile.get_file_from_path_async(os.path.abspath(image_path))
        stream = await f.open_async(FileAccessMode.READ)
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        engine = OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            raise RuntimeError("Windows OCR has no language installed.")
        result = await engine.recognize_async(bitmap)
        words = []
        for line in result.lines:
            for w in line.words:
                r = w.bounding_rect
                words.append((w.text, (r.x, r.y, r.width, r.height)))
        return words

    return asyncio.run(run())


# --------------------------------------------------------------------- PDF
def _program_files() -> list[Path]:
    out = []
    for var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        v = os.environ.get(var)
        if v and Path(v) not in out:
            out.append(Path(v))
    return out


def soffice_path() -> str | None:
    found = shutil.which("soffice")
    if found:
        return found
    for pf in _program_files():
        p = pf / "LibreOffice" / "program" / "soffice.exe"
        if p.exists():
            return str(p)
    return None


def word_to_pdf(src: Path, dst: Path) -> bool:
    """Microsoft Word, driven in the background (it never shows a window)."""
    if not IS_WINDOWS:
        return False
    try:
        import pythoncom
        import win32com.client
    except Exception:
        return False
    word = doc = None
    try:
        pythoncom.CoInitialize()
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Open(str(src.resolve()), ReadOnly=True, AddToRecentFiles=False)
        doc.SaveAs2(str(dst.resolve()), FileFormat=17)  # wdFormatPDF
        return dst.exists()
    except Exception:
        return False
    finally:
        try:
            if doc is not None:
                doc.Close(False)
        except Exception:
            pass
        try:
            if word is not None:
                word.Quit()
        except Exception:
            pass


def browser_path() -> str | None:
    """Microsoft Edge is on every Windows 10/11 PC. Chrome is the fallback."""
    candidates = []
    for pf in _program_files():
        candidates += [pf / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                       pf / "Google" / "Chrome" / "Application" / "chrome.exe"]
    la = os.environ.get("LOCALAPPDATA")
    if la:
        candidates.append(Path(la) / "Google" / "Chrome" / "Application" / "chrome.exe")
    for c in candidates:
        if c.exists():
            return str(c)
    return shutil.which("msedge") or shutil.which("chrome") or shutil.which("chromium")


def html_to_pdf(src: Path, dst: Path) -> bool:
    """Print a restored HTML file to PDF with headless Edge. It runs in a throwaway profile,
    so it never touches the person's own browser, and the page gets a few seconds to draw charts."""
    exe = browser_path()
    if not exe:
        return False
    with tempfile.TemporaryDirectory() as profile:
        args = [exe, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                "--disable-extensions", f"--user-data-dir={profile}", "--no-pdf-header-footer",
                "--run-all-compositor-stages-before-draw", "--virtual-time-budget=8000",
                f"--print-to-pdf={dst.resolve()}", src.resolve().as_uri()]
        try:
            subprocess.run(args, capture_output=True, timeout=120, creationflags=NO_WINDOW)
        except Exception:
            return False
    return dst.exists() and dst.stat().st_size > 0
