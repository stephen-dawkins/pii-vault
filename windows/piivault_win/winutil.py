"""Small Windows helpers: the clipboard (text and files), opening folders and links."""
from __future__ import annotations

import os
import struct
import subprocess
import sys
import webbrowser
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"


def copy_text(text: str) -> bool:
    if IS_WINDOWS:
        import win32clipboard
        import win32con
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
        finally:
            win32clipboard.CloseClipboard()
        return True
    return False


def copy_files(paths: list[str]) -> bool:
    """Put files on the clipboard the same way File Explorer's Copy does (CF_HDROP),
    so Ctrl+V in an AI tool's message box attaches them."""
    if not IS_WINDOWS or not paths:
        return False
    import win32clipboard
    import win32con
    files = "\0".join(str(Path(p).resolve()) for p in paths) + "\0\0"
    # DROPFILES: pFiles offset (20 bytes), pt.x, pt.y, fNC, fWide=1
    dropfiles = struct.pack("<IiiII", 20, 0, 0, 0, 1) + files.encode("utf-16-le")
    effect = struct.pack("<I", 1)  # DROPEFFECT_COPY
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_HDROP, dropfiles)
        fmt = win32clipboard.RegisterClipboardFormat("Preferred DropEffect")
        win32clipboard.SetClipboardData(fmt, effect)
    finally:
        win32clipboard.CloseClipboard()
    return True


def open_path(path: str) -> None:
    if IS_WINDOWS:
        os.startfile(path)  # noqa: S606 (opens with the default app, like double-clicking)
    else:
        subprocess.Popen(["xdg-open", path])


def reveal(path: str) -> None:
    """Show a file selected in File Explorer (or open a folder)."""
    p = Path(path)
    if IS_WINDOWS:
        if p.is_dir():
            os.startfile(str(p))
        else:
            subprocess.Popen(["explorer", "/select,", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p if p.is_dir() else p.parent)])


def open_url(url: str) -> None:
    webbrowser.open(url)


def read_text() -> str | None:
    """The clipboard's text, or None (no text, or the clipboard is busy)."""
    if not IS_WINDOWS:
        return None
    import win32clipboard
    import win32con
    try:
        win32clipboard.OpenClipboard()
    except Exception:
        return None
    try:
        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
            return win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
        return None
    except Exception:
        return None
    finally:
        try:
            win32clipboard.CloseClipboard()
        except Exception:
            pass


def clipboard_sequence() -> int:
    """Changes every time anything is copied; cheap to check."""
    if not IS_WINDOWS:
        return 0
    import ctypes
    return ctypes.windll.user32.GetClipboardSequenceNumber()


def flash_window(title: str) -> None:
    """Flash PII Vault's taskbar button so the person notices it while they're in their browser."""
    if not IS_WINDOWS:
        return
    import ctypes
    from ctypes import wintypes

    class FLASHWINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("hwnd", wintypes.HWND), ("dwFlags", wintypes.DWORD),
                    ("uCount", wintypes.UINT), ("dwTimeout", wintypes.DWORD)]

    hwnd = ctypes.windll.user32.FindWindowW(None, title)
    if hwnd:
        info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, 0x3 | 0xC, 5, 0)  # all, until focused
        ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
