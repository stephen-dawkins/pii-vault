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
