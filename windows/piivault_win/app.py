"""PII Vault for Windows: the window and everything it can ask for.

The window is HTML (ui/index.html) shown in Microsoft Edge WebView2 through pywebview. It calls
the methods of `Api` below; long work runs on pywebview's worker threads so the window never
freezes. Every real job (scan, protect, restore) is done by the same engine the Mac app uses.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

if not getattr(sys, "frozen", False):  # running from source: use the repo's engine folder
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine"))

from . import engine, ollama, updater, winutil
from .engine import EngineError

APP_NAME = "PII Vault"
HOME_DIR = Path.home() / "PII Vault"
AI_TOOLS = {
    "chatgpt": ("ChatGPT", "https://chatgpt.com/"),
    "copilot": ("Copilot", "https://m365.cloud.microsoft/chat"),
    "gemini": ("Gemini", "https://gemini.google.com/app"),
    "claude": ("Claude", "https://claude.ai/new"),
    "other": ("your AI tool", ""),
}
PICK_TYPES = ("Files PII Vault can protect (*.csv;*.tsv;*.xlsx;*.xlsm;*.docx;*.pdf;*.txt;*.md;*.markdown;*.rtf)",
              "All files (*.*)")
RESTORE_TYPES = ("Files from your AI tool (*.html;*.htm;*.docx;*.xlsx;*.xlsm;*.csv;*.tsv;*.md;*.txt;*.json;*.pptx)",
                 "All files (*.*)")


def version() -> str:
    try:
        from piivault import __version__
        return __version__
    except Exception:
        init = Path(__file__).resolve().parents[2] / "engine" / "piivault" / "__init__.py"
        m = re.search(r'__version__\s*=\s*"([^"]+)"', init.read_text()) if init.exists() else None
        return m.group(1) if m else "0.0.0"


def app_data() -> Path:
    base = os.environ.get("PIIVAULT_HOME") or os.path.join(
        os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local"), "PII Vault")
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


class UIState:
    """Small window-only settings (the engine keeps the real settings in settings.json)."""

    def __init__(self):
        self.path = app_data() / "windows-ui.json"
        try:
            self.data = json.loads(self.path.read_text())
        except Exception:
            self.data = {}

    def get(self, k, default=None):
        return self.data.get(k, default)

    def set(self, k, v):
        self.data[k] = v
        try:
            self.path.write_text(json.dumps(self.data, indent=2))
        except OSError:
            pass


def _safe(fn):
    """Every call from the window returns a dict; an error becomes {"error": "..."}."""
    def wrap(*a, **kw):
        try:
            r = fn(*a, **kw)
            return {} if r is None else r
        except EngineError as e:
            return {"error": str(e)}
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return {"error": f"{type(e).__name__}: {e}"}
    wrap.__name__ = fn.__name__
    return wrap


class Api:
    def __init__(self):
        self.window = None
        self.ui = UIState()
        self.engine_lock = threading.Lock()   # one restore pass at a time
        self.update_info: dict | None = None
        self.pulling = False

    # ------------------------------------------------------------ helpers
    def _push(self, fn: str, payload) -> None:
        if self.window is not None:
            try:
                self.window.evaluate_js(f"window.App && App.{fn}({json.dumps(payload, default=str)})")
            except Exception:
                pass

    def _staging(self, name: str) -> Path:
        d = app_data() / "staging" / f"paste-{datetime.now():%Y%m%d-%H%M%S-%f}"
        d.mkdir(parents=True, exist_ok=True)
        return d / name

    # ------------------------------------------------------------ start-up
    @_safe
    def boot(self):
        setup = engine.run("setup")
        cfg = engine.run("config")
        return {"version": version(), "config": cfg, "setup": setup, "home_dir": str(HOME_DIR),
                "computer": "PC", "platform": "windows", "ui": self.ui.data, "app_data": str(app_data()),
                "tools": {k: v[0] for k, v in AI_TOOLS.items()}}

    @_safe
    def doctor(self):
        return engine.run("doctor")

    @_safe
    def ui_set(self, key, value):
        self.ui.set(key, value)
        return {"ok": True}

    @_safe
    def ack_migration(self):
        return engine.run("ack-migration")

    @_safe
    def repair(self):
        return engine.run("setup")

    @_safe
    def config_set(self, key, value):
        if isinstance(value, bool):
            value = "true" if value else "false"
        return engine.run("config", "--set", f"{key}={value}")

    # ------------------------------------------------------------ protect
    @_safe
    def choose_files(self, purpose="protect"):
        import webview
        types = RESTORE_TYPES if purpose == "restore" else PICK_TYPES
        start = str(winutil_downloads()) if purpose == "restore" else str(Path.home())
        res = self.window.create_file_dialog(webview.FileDialog.OPEN, directory=start,
                                             allow_multiple=purpose != "restore_one", file_types=types)
        return {"files": list(res or [])}

    @_safe
    def paste_to_file(self, text: str):
        """Pasted text is protected like a .txt file, then deleted (see forget_paste)."""
        p = self._staging("Pasted text.txt")
        p.write_text(text, encoding="utf-8")
        return {"file": str(p)}

    @_safe
    def forget_paste(self, path: str):
        p = Path(path)
        if p.is_file() and (app_data() / "staging") in p.parents:
            shutil.rmtree(p.parent, ignore_errors=True)
        return {"ok": True}

    @_safe
    def scan(self, files: list, options: dict | None = None):
        args = ["scan", *files]
        if options:
            op = self._staging("options.json")
            op.write_text(json.dumps(options))
            args += ["--options", str(op)]
        try:
            return engine.run(*args)
        finally:
            if options:
                shutil.rmtree(op.parent, ignore_errors=True)

    @_safe
    def sanitize(self, files: list, prompt: str, plan: dict, want_pdf: bool, force: bool = False):
        pp = self._staging("plan.json")
        pp.write_text(json.dumps(plan or {}))
        args = ["sanitize", *files, "--prompt", prompt or "", "--plan", str(pp)]
        if want_pdf:
            args.append("--pdf")
        if force:
            args.append("--force")
        try:
            return engine.run(*args)
        finally:
            shutil.rmtree(pp.parent, ignore_errors=True)

    # ------------------------------------------------------------ send
    @_safe
    def copy_files(self, sanitized_dir: str):
        d = Path(sanitized_dir)
        files = sorted(str(p) for p in d.iterdir() if p.is_file()) if d.is_dir() else []
        if not files:
            return {"error": "The protected files for this job are no longer in the PII Vault folder."}
        winutil.copy_files(files)
        return {"count": len(files)}

    @_safe
    def copy_text(self, text: str):
        winutil.copy_text(text)
        return {"ok": True}

    @_safe
    def open_tool(self, tool: str):
        url = AI_TOOLS.get(tool or "other", AI_TOOLS["other"])[1]
        if url:
            winutil.open_url(url)
        return {"ok": bool(url)}

    @_safe
    def reveal(self, path: str):
        winutil.reveal(path)
        return {"ok": True}

    @_safe
    def open_path(self, path: str):
        winutil.open_path(path)
        return {"ok": True}

    @_safe
    def open_url(self, url: str):
        if url.startswith("https://"):
            winutil.open_url(url)
        return {"ok": True}

    @_safe
    def open_ransomware_settings(self):
        """Windows Security > Ransomware protection (Controlled folder access can block new folders)."""
        if sys.platform == "win32":
            os.startfile("windowsdefender://ransomwareprotection")  # noqa: S606
        return {"ok": True}

    @_safe
    def show_folder(self, which: str = "home"):
        d = {"home": HOME_DIR, "protected": HOME_DIR / "For AI" / "Protected",
             "output": HOME_DIR / "For AI" / "AI Output", "restored": HOME_DIR / "Restored",
             "forai": HOME_DIR / "For AI"}.get(which, HOME_DIR)
        d.mkdir(parents=True, exist_ok=True)
        winutil.open_path(str(d))
        return {"ok": True}

    # ------------------------------------------------------------ restore
    @_safe
    def restore(self, files: list, job: str | None = None):
        with self.engine_lock:
            args = ["restore", *files] + (["--job", job] if job else [])
            return engine.run(*args)

    @_safe
    def restore_text(self, text: str, job: str | None = None):
        """The AI showed its answer as text: save it as HTML, CSV or Markdown, then restore."""
        t = text.strip()
        if re.search(r"<(html|body|div|table|script|!doctype)\b", t[:5000], re.I):
            ext = ".html"
        elif _looks_csv(t):
            ext = ".csv"
        else:
            ext = ".md"
        name = f"AI answer {job}{ext}" if job else f"AI answer {datetime.now():%Y-%m-%d %H%M}{ext}"
        p = self._staging(name)
        p.write_text(t + "\n", encoding="utf-8")
        try:
            with self.engine_lock:
                return engine.run("restore", str(p), *(["--job", job] if job else []))
        finally:
            shutil.rmtree(p.parent, ignore_errors=True)

    @_safe
    def process_outputs(self):
        with self.engine_lock:
            return engine.run("process-outputs")

    @_safe
    def jobs(self):
        return engine.run("jobs")

    # ------------------------------------------------------------ local model
    @_safe
    def models(self):
        r = engine.run("models")
        r["ollama_state"] = ollama.state()
        r["pulling"] = self.pulling
        return r

    @_safe
    def ollama_state(self):
        return {"state": ollama.state()}

    @_safe
    def ollama_open(self):
        return {"ok": ollama.open_app()}

    @_safe
    def ollama_download(self):
        winutil.open_url(ollama.DOWNLOAD_URL)
        return {"ok": True}

    @_safe
    def ollama_download_page(self):
        winutil.open_url(ollama.DOWNLOAD_PAGE)
        return {"ok": True}

    @_safe
    def pull_model(self, name: str):
        if self.pulling:
            return {"ok": True, "already": True}
        self.pulling = True

        def work():
            last = [0.0]
            try:
                def prog(frac, status):
                    if frac - last[0] >= 0.005 or status == "success":
                        last[0] = frac
                        self._push("onPullProgress", {"model": name, "fraction": frac, "status": status})
                ollama.pull(name, prog)
                engine.run("config", "--set", f"local_model={name}", "--set", "use_local_model=true")
                self._push("onPullDone", {"model": name})
            except Exception as e:  # noqa: BLE001
                self._push("onPullDone", {"model": name, "error": f"The download stopped: {e}"})
            finally:
                self.pulling = False
        threading.Thread(target=work, daemon=True).start()
        return {"ok": True}

    # ------------------------------------------------------------ updates
    @_safe
    def update_check(self, force: bool = False):
        last = self.ui.get("last_update_check", 0)
        if not force and time.time() - last < 86400 and self.ui.get("last_update_result"):
            res = self.ui.get("last_update_result")
            if res.get("state") == "available" and updater._ver(res.get("version", "0")) <= updater._ver(version()):
                res = {"state": "latest"}
        else:
            res = updater.check(version())
            if res.get("state") != "error":
                self.ui.set("last_update_check", time.time())
                self.ui.set("last_update_result", res)
        self.update_info = res if res.get("state") == "available" else None
        res = dict(res)
        res["current"] = version()
        return res

    @_safe
    def update_install(self):
        info = self.update_info or updater.check(version())
        if info.get("state") != "available":
            return {"error": "You have the latest version."}

        def work():
            try:
                updater.download_and_install(info, lambda f: self._push("onUpdateProgress", {"fraction": f}))
                self._push("onUpdateProgress", {"fraction": 1, "installing": True})
                time.sleep(1.5)
                os._exit(0)  # the installer reopens PII Vault when it's done
            except Exception as e:  # noqa: BLE001
                self._push("onUpdateProgress", {"error": str(e)})
        threading.Thread(target=work, daemon=True).start()
        return {"ok": True}


def winutil_downloads() -> Path:
    try:
        from piivault.winplat import downloads_dir
        return downloads_dir()
    except Exception:
        return Path.home() / "Downloads"


def _looks_csv(t: str) -> bool:
    lines = [l for l in t.splitlines()[:20] if l.strip()]
    if len(lines) < 2:
        return False
    counts = {l.count(",") for l in lines}
    return len(counts) == 1 and counts.pop() >= 1 and not t.lstrip().startswith(("#", "|", "-"))


# ---------------------------------------------------------------- watcher
class Watcher(threading.Thread):
    """Restores AI files without being asked: anything new in For AI > AI Output, and files
    downloaded from the AI tool into Downloads. It checks a cheap fingerprint of both folders
    every few seconds and only wakes the engine when something changed."""

    def __init__(self, api: Api, interval: float = 3.0):
        super().__init__(daemon=True)
        self.api, self.interval, self.last = api, interval, None

    def fingerprint(self) -> tuple:
        out = []
        root = HOME_DIR / "For AI" / "AI Output"
        try:
            for dirpath, _, names in os.walk(root):
                for n in names:
                    if not n.startswith((".", "~$")):
                        st = os.stat(os.path.join(dirpath, n))
                        out.append((dirpath, n, int(st.st_mtime), st.st_size))
        except OSError:
            pass
        dl = winutil_downloads()
        cutoff = time.time() - 7 * 86400
        try:
            with os.scandir(dl) as it:
                for e in it:
                    if e.is_file() and not e.name.startswith((".", "~$")):
                        st = e.stat()
                        if st.st_mtime >= cutoff:
                            out.append(("dl", e.name, int(st.st_mtime), st.st_size))
        except OSError:
            pass
        return tuple(sorted(out))

    def run(self):
        time.sleep(2)
        while True:
            try:
                fp = self.fingerprint()
                if fp != self.last:
                    self.last = fp
                    res = self.api.process_outputs()
                    items = res.get("processed") or []
                    if items:
                        self.api._push("onProcessed", items)
            except Exception:
                traceback.print_exc()
            time.sleep(self.interval)


# ---------------------------------------------------------------- start
def _single_instance() -> bool:
    if sys.platform != "win32":
        return True
    import ctypes
    ctypes.windll.kernel32.CreateMutexW(None, False, "PIIVaultWindowsApp")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        hwnd = ctypes.windll.user32.FindWindowW(None, APP_NAME)
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        return False
    return True


def ui_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "ui"
    return Path(__file__).resolve().parents[1] / "ui"


def main():
    if not _single_instance():
        return
    import webview
    from webview.dom import DOMEventHandler

    api = Api()
    window = webview.create_window(APP_NAME, url=str(ui_dir() / "index.html"), js_api=api,
                                   width=1120, height=780, min_size=(940, 640),
                                   background_color="#F6F7F9", text_select=True)
    api.window = window

    def on_drop(e):
        files = (e.get("dataTransfer") or {}).get("files") or []
        paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
        if paths:
            api._push("onDrop", paths)

    def on_loaded():
        doc = window.dom.document
        doc.events.dragover += DOMEventHandler(lambda e: None, True, False, debounce=500)
        doc.events.drop += DOMEventHandler(on_drop, True, True)

    window.events.loaded += on_loaded
    Watcher(api).start()
    storage = app_data() / "webview"
    webview.start(gui="edgechromium" if sys.platform == "win32" else None, private_mode=False,
                  storage_path=str(storage), debug=bool(os.environ.get("PIIVAULT_DEBUG")))


if __name__ == "__main__":
    main()
