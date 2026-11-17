"""Put real values back into whatever the AI tool produced.

Every token (PERSON_0042, EMAIL_0007...) found in the output is swapped for the real value
from the vault, with escaping that fits where it sits: HTML text, a <script> string,
JSON, a CSV cell, an Excel cell, or a Word paragraph. Tokens the AI invented (not in
the vault) are reported, never guessed.
"""
from __future__ import annotations

import csv
import html
import io
import json
import re
import shutil
import subprocess
from pathlib import Path

from .vault import TOKEN_RE, CATEGORIES

TEXT_EXT = {".md", ".txt", ".markdown", ".rtf", ".tex", ".xml", ".svg", ".yaml", ".yml", ".sql", ".py", ".r"}
HTML_EXT = {".html", ".htm"}
SUPPORTED = TEXT_EXT | HTML_EXT | {".json", ".js", ".csv", ".tsv", ".xlsx", ".xlsm", ".docx", ".pptx"}


class Rehydrator:
    def __init__(self, vault):
        self.vault = vault
        self.replaced = 0
        self.unknown: set[str] = set()

    def _sub(self, text: str, escape) -> str:
        def rep(m):
            tok = m.group(0)
            val = self.vault.value_for(tok)
            if val is None:
                if m.group(1) in CATEGORIES:
                    self.unknown.add(tok)
                return tok
            self.replaced += 1
            return escape(val)
        return TOKEN_RE.sub(rep, text)

    # ---------------------------------------------------------- escapers
    @staticmethod
    def js_escape(v: str) -> str:
        s = json.dumps(v, ensure_ascii=False)[1:-1]
        return s.replace("'", "\\'").replace("`", "\\`").replace("${", "\\${").replace("</", "<\\/")

    @staticmethod
    def json_escape(v: str) -> str:
        # valid inside a JSON string, and safe inside an HTML <script> block
        return json.dumps(v, ensure_ascii=False)[1:-1].replace("</", "<\\/")

    @staticmethod
    def html_escape(v: str) -> str:
        return html.escape(v, quote=True)

    # ---------------------------------------------------------- formats
    def html(self, text: str) -> str:
        out, pos = [], 0
        for m in re.finditer(r"(<script\b[^>]*>)(.*?)(</script\s*>)", text, flags=re.S | re.I):
            out.append(self._sub(text[pos:m.start()], self.html_escape))
            esc = self.json_escape if re.search(r"json", m.group(1), re.I) else self.js_escape
            out.append(m.group(1) + self._sub(m.group(2), esc) + m.group(3))
            pos = m.end()
        out.append(self._sub(text[pos:], self.html_escape))
        return "".join(out)

    def file(self, src: Path, dst: Path) -> dict:
        ext = src.suffix.lower()
        if ext in HTML_EXT:
            dst.write_text(self.html(src.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
        elif ext == ".json":
            dst.write_text(self._sub(src.read_text(encoding="utf-8"), self.json_escape), encoding="utf-8")
        elif ext == ".js":
            dst.write_text(self._sub(src.read_text(encoding="utf-8"), self.js_escape), encoding="utf-8")
        elif ext in (".csv", ".tsv"):
            delim = "\t" if ext == ".tsv" else ","
            rows = list(csv.reader(io.StringIO(src.read_text(encoding="utf-8-sig")), delimiter=delim))
            with open(dst, "w", newline="", encoding="utf-8") as f:
                csv.writer(f, delimiter=delim).writerows([[self._sub(c, str) for c in r] for r in rows])
        elif ext in (".xlsx", ".xlsm"):
            from openpyxl import load_workbook
            wb = load_workbook(src, keep_vba=(ext == ".xlsm"))
            for ws in wb.worksheets:
                for row in ws.iter_rows():
                    for cell in row:
                        if isinstance(cell.value, str) and TOKEN_RE.search(cell.value):
                            cell.value = self._sub(cell.value, str)
            wb.save(dst)
        elif ext == ".docx":
            from docx import Document
            from .handlers.word import iter_p_elements, text_nodes, replace_in_nodes, _xml_parts
            doc = Document(src)
            for p in iter_p_elements(doc):
                nodes = text_nodes(p)
                t = "".join(n.text or "" for n in nodes)
                reps = []
                for m in TOKEN_RE.finditer(t):
                    val = self.vault.value_for(m.group(0))
                    if val is None:
                        if m.group(1) in CATEGORIES:
                            self.unknown.add(m.group(0))
                        continue
                    reps.append((m.start(), m.end(), val))
                    self.replaced += 1
                replace_in_nodes(nodes, reps)
            for part, _ in _xml_parts(doc):
                for rel in part.rels.values():
                    if rel.is_external and TOKEN_RE.search(rel._target or ""):
                        rel._target = self._sub(rel._target, str)
            doc.save(dst)
        elif ext == ".pptx":
            from pptx import Presentation
            prs = Presentation(src)
            for slide in prs.slides:
                for shape in slide.shapes:
                    frames = []
                    if shape.has_text_frame:
                        frames.append(shape.text_frame)
                    if getattr(shape, "has_table", False) and shape.has_table:
                        frames += [c.text_frame for r in shape.table.rows for c in r.cells]
                    for tf in frames:
                        for para in tf.paragraphs:
                            for run in para.runs:
                                if TOKEN_RE.search(run.text):
                                    run.text = self._sub(run.text, str)
            prs.save(dst)
        elif ext in TEXT_EXT:
            dst.write_text(self._sub(src.read_text(encoding="utf-8", errors="replace"), str), encoding="utf-8")
        else:
            shutil.copy2(src, dst)
            return {"file": str(dst), "skipped": True,
                    "note": f"{ext} files can't be rehydrated directly; ask the AI for HTML, Word, Excel or CSV."}
        return {"file": str(dst), "skipped": False}


def rehydrate(src: Path, dst: Path, vault) -> dict:
    r = Rehydrator(vault)
    info = r.file(src, dst)
    info.update(replaced=r.replaced, unknown_tokens=sorted(r.unknown))
    return info


# --------------------------------------------------------------- PDF export
def docx_to_pdf(src: Path, dst: Path) -> bool:
    """Convert locally: LibreOffice if installed, else Microsoft Word (AppleScript on Mac, COM on Windows)."""
    from .winplat import IS_WINDOWS, NO_WINDOW, soffice_path, word_to_pdf
    if IS_WINDOWS:
        soffice = soffice_path() or ""
    else:
        soffice = shutil.which("soffice") or "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    if soffice and Path(soffice).exists():
        r = subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(dst.parent), str(src)],
                           capture_output=True, timeout=180, creationflags=NO_WINDOW)
        produced = dst.parent / (src.stem + ".pdf")
        if r.returncode == 0 and produced.exists():
            if produced != dst:
                produced.replace(dst)
            return True
    if IS_WINDOWS:
        return word_to_pdf(src, dst)
    if Path("/Applications/Microsoft Word.app").exists():
        script = f'''
        tell application "Microsoft Word"
            set d to open file name (POSIX file "{src}" as string)
            save as d file name (POSIX file "{dst}" as string) file format format PDF
            close d saving no
        end tell'''
        r = subprocess.run(["osascript", "-e", script], capture_output=True, timeout=180)
        return r.returncode == 0 and dst.exists()
    return False
