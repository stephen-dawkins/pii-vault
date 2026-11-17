"""Command line interface. The Mac app calls these commands and reads JSON from stdout.

    piivault doctor
    piivault setup                      # make or repair the PII Vault folder (also moves older layouts)
    piivault ack-migration              # the "we moved your files" note was shown
    piivault scan FILE... [--options OPTIONS.json]
    piivault sanitize --prompt TEXT [--plan PLAN.json] [--pdf] FILE...
    piivault process-outputs            # restore anything new in AI Output, or downloaded with tokens in it
    piivault rehydrate FILE [--job ID] [--pdf]
    piivault restore FILE... [--job ID] # restore files the user dragged in (e.g. downloaded from the AI tool)
    piivault jobs
    piivault models                     # the short list of local models PII Vault offers
    piivault config [--set KEY=VALUE]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import time
import sys
import traceback
from datetime import datetime
from pathlib import Path

from . import __version__
from .vault import Vault, app_support_dir, new_job_id, save_job, load_job, list_jobs, TOKEN_RE
from . import detect
from .detect import ner_engine, find_pii, apply_spans
from .handlers import tabular, word, pdf, text as textfile
from .rehydrate import rehydrate, docx_to_pdf, SUPPORTED

# ONE folder for everyone, in the home folder (Macintosh HD > Users > <name> > PII Vault,
# or C: > Users > <name> > PII Vault on Windows, which OneDrive's folder backup never touches).
# Not in Documents on purpose: Documents is often synced to iCloud, which would copy restored
# student data to the cloud and can offload files so PII Vault can't read the AI's output.
#   PII Vault/For AI/Protected/<JOB>   protected copies (safe to attach or share with an AI tool)
#   PII Vault/For AI/AI Output/<JOB>   where folder-capable AI tools save (PII Vault restores from here)
#   PII Vault/Restored/<JOB>           restored files with real data (private, never shared)
HOME_DIR = Path.home() / "PII Vault"
WORKSPACE = HOME_DIR / "For AI"
LAYOUT_VERSION = 2
FOLDER_KEYS = ("sanitized_dir", "claude_output_dir", "results_dir")
FOLDER_NAMES = {"sanitized_dir": "Protected", "claude_output_dir": "AI Output", "results_dir": "Restored"}
from .winplat import IS_WINDOWS, downloads_dir
DOWNLOADS = downloads_dir()
COMPUTER = "PC" if IS_WINDOWS else "Mac"
DEFAULTS = {
    "sanitized_dir": str(WORKSPACE / "Protected"),
    "claude_output_dir": str(WORKSPACE / "AI Output"),
    "results_dir": str(HOME_DIR / "Restored"),
    "claude_os_dir": str(WORKSPACE),  # the folder the AI tool can read (warnings + prompt paths)
    "ai_tool": "",                    # chatgpt | copilot | gemini | claude | other (only changes the Open button)
    "use_local_model": True,
    "local_model": "",                # picked on first run from the installed models
    "review_unstructured": True,      # show the found-items list for Word, PDF and text
    "watch_downloads": True,          # restore AI files saved to Downloads automatically
    "layout": LAYOUT_VERSION,
}

# Older layouts, moved into HOME_DIR automatically the first time a new version runs:
#   v0.1 to v0.2 on Stephen's Macs: Claude OS/PII_Vault/Sanitized + Claude Output, ~/PII Vault Results
#   v0.2 to v0.3 for everyone else: Documents/PII Vault/For AI/Protected + AI Output, Documents/PII Vault/Restored
LEGACY_CLAUDE_OS = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/Documents/Claude OS"
LEGACY = {
    "sanitized_dir": str(LEGACY_CLAUDE_OS / "PII_Vault" / "Sanitized"),
    "claude_output_dir": str(LEGACY_CLAUDE_OS / "PII_Vault" / "Claude Output"),
    "results_dir": str(Path.home() / "PII Vault Results"),
}
OLD_DOCS_DIR = Path.home() / "Documents" / "PII Vault"
OLD_DOCS = {
    "sanitized_dir": str(OLD_DOCS_DIR / "For AI" / "Protected"),
    "claude_output_dir": str(OLD_DOCS_DIR / "For AI" / "AI Output"),
    "results_dir": str(OLD_DOCS_DIR / "Restored"),
}

# Local models PII Vault offers to download. Kept short on purpose: small, good at
# following "reply with JSON" instructions, and safe to run on a laptop.
MODEL_CATALOG = [
    {"name": "qwen3:4b", "title": "Qwen 3 (4B)", "size_gb": 2.5, "ram_gb": 8, "recommended": True,
     "blurb": f"Best balance of accuracy and speed. Good for most {COMPUTER}s."},
    {"name": "llama3.2:3b", "title": "Llama 3.2 (3B)", "size_gb": 2.0, "ram_gb": 8, "recommended": False,
     "blurb": "Smallest download. A little less accurate on unusual names."},
    {"name": "qwen3:8b", "title": "Qwen 3 (8B)", "size_gb": 5.2, "ram_gb": 16, "recommended": False,
     "blurb": "Most accurate. Needs 16 GB of memory and runs slower on long documents."},
]

TABLE_EXT = {".csv", ".tsv", ".xlsx", ".xlsm"}
TEXT_EXT = {".txt", ".md", ".markdown", ".rtf", ".text"}
WORD_EXT = {".docx"}
PDF_EXT = {".pdf"}


# ------------------------------------------------------------------ config
def config() -> dict:
    p = app_support_dir() / "settings.json"
    saved = json.loads(p.read_text()) if p.exists() else {}
    if saved.get("layout") != LAYOUT_VERSION:
        saved = migrate(saved)
        p.write_text(json.dumps(saved, indent=2))
    cfg = dict(DEFAULTS)
    cfg.update(saved)
    if not cfg.get("local_model"):
        _, installed = detect.ollama_models()
        pick = next((m["name"] for m in MODEL_CATALOG if m["name"] in installed), None)
        cfg["local_model"] = pick or (installed[0] if installed else MODEL_CATALOG[0]["name"])
    return cfg


# ----------------------------------------------------------------- folders
def _old_layouts(saved: dict) -> list[dict]:
    """Every older folder layout that might hold this person's files."""
    layouts = []
    if any(k in saved for k in FOLDER_KEYS):
        layouts.append({k: saved[k] for k in FOLDER_KEYS if saved.get(k)})
    layouts += [LEGACY, OLD_DOCS]
    seen, out = set(), []
    for lay in layouts:
        key = tuple(sorted(lay.items()))
        if key not in seen:
            seen.add(key)
            out.append(lay)
    return out


def _move_merge(src: Path, dst: Path, report: dict) -> None:
    """Move everything in src into dst. Folders with the same name are merged; a file that
    already exists in dst is kept, and the incoming one gets " (moved)" added to its name."""
    dst.mkdir(parents=True, exist_ok=True)
    for child in sorted(src.iterdir()):
        if child.name in (".DS_Store", "README - PII Vault.txt"):
            continue
        target = dst / child.name
        try:
            if target.exists() and child.is_dir() and target.is_dir():
                _move_merge(child, target, report)
                continue
            if target.exists():
                target = dst / f"{child.stem} (moved){child.suffix}"
            shutil.move(str(child), str(target))
            report["moved"] += 1
        except Exception as e:
            report["left_behind"].append(f"{child}: {type(e).__name__}: {e}")
    _remove_if_empty(src)


def _remove_if_empty(d: Path) -> None:
    try:
        for junk in (".DS_Store", "README - PII Vault.txt"):
            if (d / junk).exists() and all(c.name in (".DS_Store", "README - PII Vault.txt") for c in d.iterdir()):
                (d / junk).unlink()
        d.rmdir()
    except OSError:
        pass


def _rewrite_job_paths(moves: list[tuple[str, str]]) -> None:
    """Job records remember where their files were; point them at the new folders."""
    from .vault import jobs_dir
    for jp in jobs_dir().glob("JOB-*.json"):
        try:
            txt = jp.read_text()
            new = txt
            for old, now in moves:
                new = new.replace(json.dumps(old)[1:-1], json.dumps(now)[1:-1])
            if new != txt:
                jp.write_text(new)
        except Exception:
            continue


def migrate(saved: dict) -> dict:
    """Move an older install's folders into ~/PII Vault so every install looks the same.
    Runs once per Mac (settings.json then says layout 2). Nothing is deleted: files are moved,
    and an old folder is removed only when it's empty. Anything that can't be moved is listed
    in migration.json, and the app shows it."""
    report = {"date": datetime.now().isoformat(timespec="seconds"), "moved": 0, "from": [], "left_behind": []}
    moves = []
    for lay in _old_layouts(saved):
        for k in FOLDER_KEYS:
            src = Path(lay.get(k) or "")
            dst = Path(DEFAULTS[k])
            if not lay.get(k) or not src.is_dir() or src.resolve() == dst.resolve():
                continue
            try:
                _move_merge(src, dst, report)
                report["from"].append(str(src))
                moves.append((str(src), str(dst)))
            except Exception as e:
                report["left_behind"].append(f"{src}: {type(e).__name__}: {e}")
    for d in (OLD_DOCS_DIR / "For AI", OLD_DOCS_DIR, LEGACY_CLAUDE_OS / "PII_Vault" / "Sanitized"):
        if d.is_dir():
            _remove_if_empty(d)
    if moves:
        _rewrite_job_paths(moves)
    if report["from"] or report["left_behind"]:
        (app_support_dir() / "migration.json").write_text(json.dumps(report, indent=2))
    keep = {k: v for k, v in saved.items() if k not in FOLDER_KEYS + ("claude_os_dir",)}
    keep["layout"] = LAYOUT_VERSION
    return keep


def migration_report() -> dict | None:
    p = app_support_dir() / "migration.json"
    try:
        return json.loads(p.read_text()) if p.exists() else None
    except Exception:
        return None


def ensure_folders(cfg: dict) -> list[dict]:
    """Make every folder PII Vault needs and prove each one can be written to.
    Returns one status line per folder, so the app can show exactly what's wrong."""
    status = []
    for k in FOLDER_KEYS:
        p = Path(cfg[k])
        item = {"key": k, "name": FOLDER_NAMES[k], "path": str(p), "ok": False}
        try:
            p.mkdir(parents=True, exist_ok=True)
            probe = p / ".piivault-check"
            probe.write_text("ok")
            probe.unlink()
            item["ok"] = True
        except Exception as e:
            item["error"] = f"{type(e).__name__}: {e}"
        status.append(item)
    try:
        os.chmod(Path(cfg["results_dir"]), 0o700)  # restored files: only this Mac user
    except OSError:
        pass
    readme = HOME_DIR / "README - PII Vault.txt"
    try:
        if HOME_DIR.is_dir() and not readme.exists():
            readme.write_text(
                "PII Vault keeps everything in this one folder.\n\n"
                "For AI/Protected: protected copies of your files (personal information replaced with tokens).\n"
                "    These are the only files you give to an AI tool.\n"
                f"For AI/AI Output: AI tools that can save files on your {COMPUTER} (like Claude's Cowork mode) save here,\n"
                "    and PII Vault restores them automatically. If your tool needs a folder, give it \"For AI\" only.\n"
                "Restored: your finished files with the real data put back. Private. Never upload or share these with an AI tool.\n\n"
                "Files you download from an AI tool into Downloads are restored automatically too.\n"
                "Your original files are never moved or changed.\n")
    except OSError:
        pass
    return status


def save_config(cfg: dict):
    (app_support_dir() / "settings.json").write_text(json.dumps(cfg, indent=2))


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def out(obj):
    print(json.dumps(obj, indent=2, default=str))


# ---------------------------------------------------------------- commands
def cmd_doctor(_args):
    cfg = config()
    deps = {}
    mods = ("openpyxl", "docx", "pymupdf", "cryptography", "pptx", "spacy")
    mods += ("keyring", "winrt.windows.media.ocr", "win32com.client", "striprtf") if IS_WINDOWS else ("ocrmac",)
    for mod in mods:
        try:
            __import__(mod)
            deps[mod] = True
        except Exception:
            deps[mod] = False
    try:
        Vault()
        vault_ok = True
    except Exception as e:  # noqa
        vault_ok = str(e)
    folders = ensure_folders(cfg)
    results_inside = _inside(Path(cfg["results_dir"]), Path(cfg["claude_os_dir"]))
    running, models = detect.ollama_models()
    out({"version": __version__, "python": sys.version.split()[0], "deps": deps, "vault": vault_ok,
         "home_dir": str(HOME_DIR), "folders": folders, "folders_ok": all(f["ok"] for f in folders),
         "migration": migration_report(),
         "ollama_running": running, "ollama_models": models, "local_model": detect.OLLAMA_MODEL,
         "ner_engine": ner_engine(), "ocr_engine": pdf.ocr_engine(), "config": cfg,
         "warnings": (["The Results folder is inside the folder your AI tool can read, so it could see restored files."]
                      if results_inside else [])})


def cmd_setup(_args):
    """Make (or repair) the PII Vault folder. The app runs this on every launch and after updates."""
    cfg = config()
    folders = ensure_folders(cfg)
    out({"home_dir": str(HOME_DIR), "folders": folders, "folders_ok": all(f["ok"] for f in folders),
         "migration": migration_report()})


def cmd_ack_migration(_args):
    """The person has seen the "we moved your files" note; don't show it again."""
    p = app_support_dir() / "migration.json"
    if p.exists():
        p.rename(p.with_name("migration-shown.json"))
    out({"ok": True})


def _kind(path: Path) -> str:
    e = path.suffix.lower()
    if e in TABLE_EXT:
        return "table"
    if e in WORD_EXT:
        return "word"
    if e in PDF_EXT:
        return "pdf"
    if e in TEXT_EXT:
        return "text"
    return "unsupported"


def cmd_scan(args):
    cfg = config()
    use_ner = bool(cfg.get("use_local_model", True))
    review = bool(cfg.get("review_unstructured", True))
    known = {}
    if review or any(_kind(Path(f)) == "table" for f in args.files):
        try:
            known = Vault().known_values()  # people already protected in earlier jobs
        except Exception:
            known = {}
    options = json.loads(Path(args.options).read_text()) if args.options else {}
    results = []
    for f in args.files:
        p = Path(f).expanduser()
        k = _kind(p)
        item = {"file": str(p), "name": p.name, "kind": k}
        if _inside(p, Path(cfg["claude_os_dir"])):
            item["warning"] = (f"This file is inside {Path(cfg['claude_os_dir']).name}, which your AI tool can already read. "
                               "Move the original somewhere else to keep it private.")
        try:
            if k == "table":
                item.update(tabular.scan(p, known, use_ner, options.get(str(p)) or options.get(p.name)))
            elif k == "pdf":
                item.update(pdf.scan(p, known, use_ner, review))
            elif k == "word":
                item.update(word.scan(p, known, use_ner, review))
            elif k == "text":
                item.update(textfile.scan(p, known, use_ner, review))
            else:
                item["error"] = "Unsupported file type. Use CSV, Excel, Word (.docx), PDF, or text (.txt, .md, .rtf)."
        except Exception as e:
            item["error"] = f"{type(e).__name__}: {e}"
        results.append(item)
    out({"files": results, "review": review,
         "ner_engine": ner_engine() if use_ner else "none"})


def _claude_path(path: str, cfg: dict) -> str:
    """How the AI tool should refer to a folder: relative to the folder the user connected."""
    root = Path(cfg["claude_os_dir"])
    try:
        return f"{root.name}/{Path(path).resolve().relative_to(root.resolve()).as_posix()}"
    except ValueError:
        return Path(path).as_posix()


def build_prompt(user_prompt: str, job_id: str, files: list[str], want_pdf: bool, cfg: dict) -> str:
    """Instructions that work in any AI tool (ChatGPT, Copilot, Gemini, Claude...)."""
    names = ", ".join(f"`{n}`" for n in files)
    sdir = _claude_path(str(Path(cfg["sanitized_dir"]) / job_id), cfg)
    odir = _claude_path(str(Path(cfg["claude_output_dir"]) / job_id), cfg)
    lines = [
        user_prompt.strip(),
        "",
        f"[PII Vault job {job_id}] Use the attached file(s): {names}. "
        f"(If nothing is attached and you are working directly in my files, they are in `{sdir}/`.)",
        "Personal information in them was replaced with tokens like PERSON_0001, EMAIL_0003, ID_0012. Birth dates are years only.",
        "- Treat each token as the real value. Copy tokens exactly as written, e.g. PERSON_0001: never shorten, "
        "reword, translate, merge, or invent tokens, and never write them as \"Person 1\".",
        "- Don't try to guess or recover the real values.",
        "- For HTML output, keep row-level data in one `<script id=\"data\" type=\"application/json\">` block and build the page from it.",
        f"- Give me the result as a file to download (HTML, Word, Excel, CSV, or Markdown) with `{job_id}` in its file name. "
        f"A download is all I need: PII Vault puts the real values back when I download it. "
        f"(Only if you are already working directly in my files, as in Claude's Cowork mode, save it to `{odir}/` instead. "
        f"Don't mention that folder otherwise.)",
    ]
    if want_pdf:
        lines.append("- I need a PDF in the end: make a Word (.docx) or HTML file instead; "
                     "PII Vault converts it to PDF after putting the real values back.")
    return "\n".join(lines)


def cmd_sanitize(args):
    cfg = config()
    use_ner = bool(cfg.get("use_local_model", True))
    plan = json.loads(Path(args.plan).read_text()) if args.plan else {}
    vault = Vault()
    job_id = new_job_id()
    sdir = Path(cfg["sanitized_dir"]) / job_id
    tmp = app_support_dir() / "staging" / job_id
    tmp.mkdir(parents=True, exist_ok=True)
    files, blocked = [], False
    order = {"table": 0, "text": 1, "word": 2, "pdf": 3}
    for f in sorted(args.files, key=lambda x: order.get(_kind(Path(x)), 3)):
        src = Path(f).expanduser()
        known = vault.known_values()  # everything tokenized so far, this job and earlier ones
        k = _kind(src)
        # file names can contain names too ("Jane Doe transcript.pdf")
        stem_spans = find_pii(src.stem.replace("_", " "), known, use_ner)
        safe_stem = apply_spans(src.stem.replace("_", " "), stem_spans, vault) if stem_spans else src.stem
        suffix = textfile.out_suffix(src) if k == "text" else src.suffix.lower()
        dst = tmp / (safe_stem + suffix)
        fplan = plan.get(str(src), plan.get(src.name)) or {}
        review = fplan.get("_review") if isinstance(fplan, dict) else None
        detect.set_ignore((review or {}).get("ignore"))
        rec = {"source": str(src), "sanitized_name": dst.name, "kind": k}
        try:
            if k == "table":
                cols = {k2: v for k2, v in fplan.items() if not k2.startswith("_")}
                opts = {k2: v for k2, v in fplan.items() if k2.startswith("_")}
                rec.update(tabular.sanitize(src, dst, vault, cols or None, use_ner, known, opts))
            elif k in ("word", "pdf", "text"):
                handler = {"word": word, "pdf": pdf, "text": textfile}[k]
                rec.update(handler.sanitize(src, dst, vault, use_ner, known, review))
                if review is not None:
                    rec["reviewed"] = True
                if rec.get("leak_count"):
                    blocked = True
            else:
                rec["error"] = "unsupported"
                blocked = True
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"
            rec["trace"] = traceback.format_exc(limit=3)
            blocked = True
        files.append(rec)
    detect.set_ignore(None)
    vault.save()

    job = {"id": job_id, "created": datetime.now().isoformat(timespec="seconds"), "prompt": args.prompt,
           "want_pdf": bool(args.pdf), "files": files, "outputs": {}, "status": "blocked" if blocked else "ready"}
    if not blocked or args.force:
        bad = [f for f in ensure_folders(cfg) if not f["ok"]]
        if bad:
            raise RuntimeError(f"PII Vault can't save to its {bad[0]['name']} folder ({bad[0]['path']}): "
                               f"{bad[0].get('error')}. Open PII Vault > Settings > Folders and click Repair.")
        sdir.mkdir(parents=True, exist_ok=True)
        for rec in files:
            if "error" not in rec:
                shutil.move(str(tmp / rec["sanitized_name"]), sdir / rec["sanitized_name"])
        (Path(cfg["claude_output_dir"]) / job_id).mkdir(parents=True, exist_ok=True)
        job["status"] = "sent"
        job["sanitized_dir"] = str(sdir)
    shutil.rmtree(tmp, ignore_errors=True)
    job["cowork_prompt"] = build_prompt(args.prompt or "", job_id,
                                        [r["sanitized_name"] for r in files if "error" not in r], bool(args.pdf), cfg)
    save_job(job)
    out(job)


def _rehydrate_one(src: Path, job: dict | None, cfg: dict, vault: Vault, want_pdf: bool) -> dict:
    jid = job["id"] if job else "Restored"
    rdir = Path(cfg["results_dir"]) / jid
    rdir.mkdir(parents=True, exist_ok=True)
    dst = rdir / src.name
    info = rehydrate(src, dst, vault)
    info["source"] = str(src)
    if want_pdf and not info.get("skipped"):
        ext = dst.suffix.lower()
        if ext == ".docx":
            pdf_path = dst.with_suffix(".pdf")
            info["pdf"] = str(pdf_path) if docx_to_pdf(dst, pdf_path) else None
            if not info["pdf"]:
                info["pdf_note"] = "Install LibreOffice or Microsoft Word to convert Word files to PDF."
        elif ext in (".html", ".htm"):
            if IS_WINDOWS:  # Windows: headless Edge prints it here in the engine
                from .winplat import html_to_pdf
                pdf_path = dst.with_suffix(".pdf")
                info["pdf"] = str(pdf_path) if html_to_pdf(dst, pdf_path) else None
                if not info["pdf"]:
                    info["pdf_note"] = "Microsoft Edge couldn't turn this HTML file into a PDF. Open it and print to PDF."
            else:
                info["needs_html_pdf"] = True  # the Mac app renders HTML to PDF with WebKit
    return info


def cmd_rehydrate(args):
    cfg = config()
    src = Path(args.file).expanduser()
    job = load_job(args.job) if args.job else None
    if job is None:
        for part in src.parts:
            if part.startswith("JOB-"):
                job = load_job(part)
    out(_rehydrate_one(src, job, cfg, Vault(), args.pdf or bool(job and job.get("want_pdf"))))


JOB_IN_NAME = __import__("re").compile(r"JOB-\d{8}-\d{6}")


def cmd_restore(args):
    """Restore files the user dropped onto the app (for example a file downloaded from the AI tool)."""
    cfg = config()
    vault, done = Vault(), []
    for f in args.files:
        src = Path(f).expanduser()
        job = None
        m = JOB_IN_NAME.search(str(src))
        if m:
            job = load_job(m.group(0))
        if job is None and args.job:
            job = load_job(args.job)
        try:
            info = _rehydrate_one(src, job, cfg, vault, bool(job and job.get("want_pdf")))
            if job is None:
                info["note"] = "No job ID in the file name, so it was saved under Restored."
        except Exception as e:
            info = {"source": str(src), "error": f"{type(e).__name__}: {e}"}
        if job is not None:
            job.setdefault("outputs", {})[f"dropped/{src.name}"] = {**info, "processed": datetime.now().isoformat(timespec="seconds")}
            job["status"] = "complete"
            save_job(job)
        done.append({"job": job["id"] if job else "Restored", **info})
    out({"processed": done})


def cmd_models(_args):
    cfg = config()
    running, installed = detect.ollama_models()
    base = lambda n: n if ":" in n else n + ":latest"
    inst = set(installed) | {m.split(":")[0] for m in installed if m.endswith(":latest")}
    catalog = [{**m, "installed": m["name"] in inst or base(m["name"]) in inst} for m in MODEL_CATALOG]
    out({"ollama_running": running, "installed": installed, "catalog": catalog,
         "selected": cfg.get("local_model")})


def cmd_process_outputs(_args):
    """Rehydrate every new or changed file in Claude Output/<JOB>/."""
    cfg = config()
    root = Path(cfg["claude_output_dir"])
    vault, done = None, []
    if root.exists():
        for jdir in sorted(root.glob("JOB-*")):
            job = load_job(jdir.name)
            if job is None:
                continue
            changed = False
            for f in sorted(jdir.rglob("*")):
                if not f.is_file() or f.name.startswith((".", "~$")):
                    continue
                key = str(f.relative_to(jdir))
                mtime = f.stat().st_mtime
                prev = job["outputs"].get(key)
                if prev and prev.get("mtime") == mtime:
                    continue
                if vault is None:
                    vault = Vault()
                try:
                    info = _rehydrate_one(f, job, cfg, vault, job.get("want_pdf", False))
                except Exception as e:
                    info = {"source": str(f), "error": f"{type(e).__name__}: {e}"}
                info["mtime"] = mtime
                info["processed"] = datetime.now().isoformat(timespec="seconds")
                job["outputs"][key] = info
                done.append({"job": job["id"], **info})
                changed = True
            if changed:
                job["status"] = "complete"
                save_job(job)
    done += _process_downloads(cfg)
    out({"processed": done})


PARTIAL_DOWNLOAD = (".crdownload", ".download", ".part", ".partial", ".tmp")
ZIP_FORMATS = {".docx", ".xlsx", ".xlsm", ".pptx"}


def _tokens_in(path: Path) -> set[str]:
    """Tokens (PERSON_0001...) inside a file, read cheaply. Empty set if none or unreadable."""
    try:
        if path.suffix.lower() in ZIP_FORMATS:
            import zipfile
            with zipfile.ZipFile(path) as z:
                text = " ".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist()
                                if n.endswith(".xml") or n.endswith(".rels"))
        else:
            text = path.read_bytes()[:20_000_000].decode("utf-8", "ignore")
    except Exception:
        return set()
    return {m.group(0) for m in TOKEN_RE.finditer(text)}


def _process_downloads(cfg: dict) -> list[dict]:
    """Restore files the AI tool handed over as downloads.

    Chat-only AI tools (and Claude when it can't reach the AI Output folder) give the result as
    a download, which lands in Downloads, not in PII Vault's folder. PII Vault looks there for
    files saved in the last week that either have a job ID in the name or contain tokens from
    this Mac's vault, and restores each one once (into Restored/<JOB>/). The token copy in
    Downloads is left alone."""
    if not cfg.get("watch_downloads", True) or not DOWNLOADS.is_dir():
        return []
    jobs = [j for j in list_jobs() if j.get("status") in ("sent", "complete")]
    if not jobs:
        return []
    created = sorted(datetime.fromisoformat(j["created"]).timestamp() for j in jobs if j.get("created"))
    cutoff = max(time.time() - 7 * 86400, created[0] - 60) if created else time.time() - 7 * 86400
    seen_path = app_support_dir() / "downloads_seen.json"
    try:
        seen = set(json.loads(seen_path.read_text()))
    except Exception:
        seen = set()
    vault, done, new_seen = None, [], set()
    try:
        entries = sorted(DOWNLOADS.iterdir())
    except Exception:
        return []  # no permission to read Downloads (the app shows how to allow it)
    for f in entries:
        try:
            if (f.name.startswith((".", "~$")) or not f.is_file() or f.suffix.lower() not in SUPPORTED
                    or f.name.lower().endswith(PARTIAL_DOWNLOAD)):
                continue
            st = f.stat()
            if st.st_mtime < cutoff or st.st_size > 50_000_000:
                continue
            key = f"{f}|{int(st.st_mtime)}|{st.st_size}"
            new_seen.add(key)
            if key in seen:
                continue
            m = JOB_IN_NAME.search(f.name)
            job = load_job(m.group(0)) if m else None
            if job is None:
                toks = _tokens_in(f)
                if not toks:
                    continue
                if vault is None:
                    vault = Vault()
                if not any(vault.value_for(t) is not None for t in toks):
                    continue  # tokens from somewhere else, not this Mac's vault
                # the newest job started before this file was saved
                before = [j for j in jobs if j.get("created") and
                          datetime.fromisoformat(j["created"]).timestamp() <= st.st_mtime + 60]
                job = max(before, key=lambda j: j["created"]) if before else None
            if vault is None:
                vault = Vault()
            info = _rehydrate_one(f, job, cfg, vault, bool(job and job.get("want_pdf")))
            info["from_downloads"] = True
            if job is not None:
                job.setdefault("outputs", {})[f"downloads/{f.name}"] = {
                    **info, "processed": datetime.now().isoformat(timespec="seconds")}
                job["status"] = "complete"
                save_job(job)
            done.append({"job": job["id"] if job else "Restored", **info})
        except Exception as e:
            done.append({"job": "Restored", "source": str(f), "error": f"{type(e).__name__}: {e}"})
    try:
        seen_path.write_text(json.dumps(sorted(new_seen)))  # only recent files that are still there
    except Exception:
        pass
    return done


def cmd_jobs(_args):
    out({"jobs": list_jobs()})


def cmd_config(args):
    cfg = config()
    for kv in args.set or []:
        k, v = kv.split("=", 1)
        cfg[k] = (v.lower() == "true") if v.lower() in ("true", "false") else v
    if args.set:
        save_config(cfg)
    out(cfg)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="piivault")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    sub.add_parser("setup")
    sub.add_parser("ack-migration")
    s = sub.add_parser("scan"); s.add_argument("files", nargs="+")
    s.add_argument("--options", help='JSON file: {"<file>": {"_header_rows": {"Sheet1": 15}}}')
    s = sub.add_parser("sanitize")
    s.add_argument("files", nargs="+"); s.add_argument("--prompt", default="")
    s.add_argument("--plan"); s.add_argument("--pdf", action="store_true")
    s.add_argument("--force", action="store_true", help="send even if a leak check failed")
    s = sub.add_parser("rehydrate"); s.add_argument("file"); s.add_argument("--job"); s.add_argument("--pdf", action="store_true")
    sub.add_parser("process-outputs")
    sub.add_parser("jobs")
    sub.add_parser("models")
    s = sub.add_parser("restore"); s.add_argument("files", nargs="+"); s.add_argument("--job")
    s = sub.add_parser("config"); s.add_argument("--set", action="append")
    args = ap.parse_args(argv)
    detect.OLLAMA_MODEL = config().get("local_model") or detect.OLLAMA_MODEL
    try:
        {"doctor": cmd_doctor, "scan": cmd_scan, "sanitize": cmd_sanitize, "rehydrate": cmd_rehydrate,
         "process-outputs": cmd_process_outputs, "jobs": cmd_jobs, "config": cmd_config,
         "restore": cmd_restore, "models": cmd_models,
         "setup": cmd_setup, "ack-migration": cmd_ack_migration}[args.cmd](args)
    except Exception as e:
        out({"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc(limit=5)})
        sys.exit(1)


if __name__ == "__main__":
    main()
