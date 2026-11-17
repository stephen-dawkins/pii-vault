"""Plain text: .txt, .md, and .rtf files, plus text pasted into the app.

The whole text is scanned once (rules, values already in the vault, and the local model),
every occurrence of every found value is replaced with its token, and the output is
re-read to make sure nothing survived. RTF is converted to plain text first (macOS
`textutil`, or the striprtf library elsewhere), so the protected copy is a .txt file.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from ..detect import find_values, findings, known_value_spans, find_pii, resolve, apply_spans, drop_ignored

TEXT_INPUT_EXT = {".txt", ".md", ".markdown", ".rtf", ".text"}


def read_text(path: Path) -> str:
    if path.suffix.lower() == ".rtf":
        if shutil.which("textutil"):
            r = subprocess.run(["textutil", "-convert", "txt", "-stdout", str(path)],
                               capture_output=True, timeout=60)
            if r.returncode == 0:
                return r.stdout.decode("utf-8", errors="replace")
        raw = path.read_text(encoding="utf-8", errors="replace")
        try:
            from striprtf.striprtf import rtf_to_text
            return rtf_to_text(raw, errors="ignore")
        except Exception:
            pass
        # crude fallback: drop RTF control words
        raw = re.sub(r"\\[a-z]+-?\d* ?|[{}]", "", raw)
        return raw
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def out_suffix(path: Path) -> str:
    return ".txt" if path.suffix.lower() in (".rtf", ".text") else path.suffix.lower()


def scan(path: Path, known: dict | None, use_ner: bool, with_findings: bool) -> dict:
    text = read_text(path)
    info = {"type": "text", "paragraphs": len([l for l in text.splitlines() if l.strip()]),
            "characters": len(text)}
    if with_findings:
        found, origin = find_values(text, known, use_ner)
        info["findings"] = findings(text, found, origin)
    return info


def sanitize(path: Path, out_path: Path, vault, use_ner: bool = True, known: dict | None = None,
             review: dict | None = None) -> dict:
    from ..detect import review_values, with_known
    text = read_text(path)
    approved = review_values(review)
    found = drop_ignored(with_known(approved, known)) if approved is not None else find_values(text, known, use_ner)[0]
    spans = resolve(known_value_spans(text, found) + find_pii(text, None, use_ner=False))
    clean = apply_spans(text, spans, vault)
    for s in spans:
        found.setdefault(s.text, s.category)
    out_path.write_text(clean, encoding="utf-8")
    final = out_path.read_text(encoding="utf-8")
    leaks = [v for v, c in found.items() if len(v) >= 3 and known_value_spans(final, {v: c})]
    return {"replaced": {"token": len(spans)}, "values_found": len(found), "leak_count": len(leaks),
            "warnings": [f"{len(leaks)} value(s) are still in the text."] if leaks else []}
