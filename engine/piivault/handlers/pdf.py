"""PDF: text PDFs and scanned PDFs.

Text pages: each PII value is covered with a true redaction (the original text is removed
from the file, not just painted over) and the token is written in its place.
Scanned pages: the page is OCR'd on this computer (Apple Vision via ocrmac on Mac, the
OCR built into Windows on Windows, or Tesseract),
PII areas are redacted out of the image pixels, the token is stamped in, and an
invisible text layer is added so the AI can read the rest of the page.
Also cleaned: document metadata, comments/annotations, form-field values, bookmarks,
link targets, and embedded attachments.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pymupdf as fitz

from ..detect import find_pii, known_value_spans, resolve

SCANNED_MIN_CHARS = 25


# ----------------------------------------------------------------- OCR
def ocr_engine() -> str:
    try:
        import ocrmac  # noqa: F401  (macOS Vision framework)
        return "apple-vision"
    except Exception:
        pass
    from ..winplat import windows_ocr_available
    if windows_ocr_available():
        return "windows-ocr"
    if shutil.which("tesseract"):
        return "tesseract"
    return "none"


def _ocr_units(page, dpi: int = 300) -> list[tuple[str, fitz.Rect]]:
    """OCR one page. Returns (text, rect in PDF points) units, in reading order."""
    zoom = dpi / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    engine = ocr_engine()
    units: list[tuple[str, fitz.Rect]] = []
    with tempfile.TemporaryDirectory() as td:
        img = os.path.join(td, "page.png")
        pix.save(img)
        if engine == "apple-vision":
            from ocrmac import ocrmac
            res = ocrmac.OCR(img, recognition_level="accurate").recognize()
            W, H = page.rect.width, page.rect.height
            for text, _conf, (x, y, w, h) in res:  # normalized, origin bottom-left
                r = fitz.Rect(x * W, (1 - y - h) * H, (x + w) * W, (1 - y) * H)
                units.append((text, r))
            units.sort(key=lambda u: (round(u[1].y0 / 6), u[1].x0))
        elif engine == "windows-ocr":
            from ..winplat import windows_ocr
            for text, (x, y, w, h) in windows_ocr(img):  # pixels, origin top-left
                units.append((text, fitz.Rect(x / zoom, y / zoom, (x + w) / zoom, (y + h) / zoom)))
        elif engine == "tesseract":
            from ..winplat import NO_WINDOW
            out = subprocess.run(["tesseract", img, "stdout", "tsv"], capture_output=True, text=True, timeout=300,
                                 creationflags=NO_WINDOW)
            for line in out.stdout.splitlines()[1:]:
                f = line.split("\t")
                if len(f) < 12 or not f[11].strip():
                    continue
                l, t, w, h = (int(v) / zoom for v in f[6:10])
                units.append((f[11], fitz.Rect(l, t, l + w, t + h)))
    return units


def _units_text(units):
    """Join OCR units into one string, remembering where each unit starts."""
    parts, offsets, pos, prev = [], [], 0, None
    for text, rect in units:
        sep = ""
        if prev is not None:
            sep = "\n" if abs(rect.y0 - prev.y0) > max(4, prev.height * 0.6) else " "
        parts.append(sep)
        pos += len(sep)
        offsets.append(pos)
        parts.append(text)
        pos += len(text)
        prev = rect
    return "".join(parts), offsets


def _span_rects(span_start, span_end, units, offsets):
    """Rects covering [span_start, span_end) of the joined OCR text (proportional within a unit)."""
    rects = []
    for (text, r), off in zip(units, offsets):
        a, b = off, off + len(text)
        s, e = max(a, span_start), min(b, span_end)
        if s >= e or not text:
            continue
        cw = r.width / len(text)
        rects.append(fitz.Rect(r.x0 + (s - a) * cw - 1, r.y0 - 1, r.x0 + (e - a) * cw + 1, r.y1 + 1))
    return rects


# ------------------------------------------------------------ helpers
def _fit_size(token: str, rect: fitz.Rect) -> float:
    w1 = fitz.get_text_length(token, fontname="helv", fontsize=1) or 1
    return max(2.0, min(rect.height * 0.8, (rect.width - 1) / w1, 12))


def _redact(page, rect, token):
    page.add_redact_annot(rect, text=token, fontname="helv", fontsize=_fit_size(token, rect),
                          fill=(1, 1, 1), text_color=(0, 0, 0), align=fitz.TEXT_ALIGN_LEFT)


def _tok_text(text, found, vault, use_ner=False):
    spans = resolve(known_value_spans(text, found) + find_pii(text, None, use_ner=use_ner))
    for s in sorted(spans, key=lambda x: x.start, reverse=True):
        text = text[:s.start] + vault.token_for(s.text, s.category) + text[s.end:]
    return text, spans


def is_scanned(page) -> bool:
    return len(page.get_text("text").strip()) < SCANNED_MIN_CHARS and bool(page.get_images())


def _extract(doc):
    """Text of every page (scanned pages are OCR'd). Returns (texts, ocr_pages, warnings)."""
    texts, ocr_pages, warnings = [], {}, []
    for i, page in enumerate(doc):
        if is_scanned(page):
            if ocr_engine() == "none":
                warnings.append(f"Page {i + 1} is scanned but no OCR engine is installed; page left as is.")
                texts.append("")
                continue
            units = _ocr_units(page)
            t, offs = _units_text(units)
            ocr_pages[i] = (units, offs, t)
            texts.append(t)
        else:
            texts.append(page.get_text("text"))
    return texts, ocr_pages, warnings


def scan(path: Path, known: dict | None = None, use_ner: bool = True, with_findings: bool = False) -> dict:
    doc = fitz.open(path)
    scanned = sum(1 for p in doc if is_scanned(p))
    info = {"type": "pdf", "pages": doc.page_count, "scanned_pages": scanned, "ocr_engine": ocr_engine(),
            "form_fields": sum(1 for p in doc for _ in p.widgets()),
            "annotations": sum(len(list(p.annots())) for p in doc)}
    if with_findings:
        from ..detect import find_values, findings
        texts, _, _ = _extract(doc)
        extra = "\n".join(w.field_value for p in doc for w in p.widgets()
                          if isinstance(w.field_value, str) and w.field_value.strip())
        text = "\n\n".join(texts) + ("\n\n" + extra if extra else "")
        found, origin = find_values(text, known, use_ner)
        info["findings"] = findings(text, found, origin)
    return info


def sanitize(path: Path, out_path: Path, vault, use_ner: bool = True, known: dict | None = None,
             review: dict | None = None) -> dict:
    from ..detect import find_values, review_values, drop_ignored, with_known
    doc = fitz.open(path)
    # Pass 1: collect text (OCR scanned pages) and find PII across the whole document
    texts, ocr_pages, warnings = _extract(doc)
    approved = review_values(review)
    if approved is not None:
        found = drop_ignored(with_known(approved, known))
    else:
        found = find_values("\n\n".join(texts), known, use_ner)[0]
    vault.prime(found)

    count = 0
    for i, page in enumerate(doc):
        # annotations (sticky notes, comments carry author names) and form fields
        for annot in list(page.annots() or []):
            page.delete_annot(annot)
        for w in list(page.widgets() or []):
            if isinstance(w.field_value, str) and w.field_value.strip():
                nv, sp = _tok_text(w.field_value, found, vault)
                if sp:
                    w.field_value = nv
                    w.update()
                    count += len(sp)
        for link in page.get_links():
            uri = link.get("uri")
            if uri:
                nv, sp = _tok_text(uri, found, vault)
                if sp:
                    link["uri"] = nv
                    page.update_link(link)

        if i in ocr_pages:
            units, offs, t = ocr_pages[i]
            spans = resolve(known_value_spans(t, found) + find_pii(t, None, use_ner=False))
            redacted_ranges = []
            for s in spans:
                tok = vault.token_for(s.text, s.category)
                rects = _span_rects(s.start, s.end, units, offs)
                for j, r in enumerate(rects):
                    _redact(page, r, tok if j == 0 else "")
                redacted_ranges.append((s.start, s.end))
                count += 1
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS)
            # Invisible text layer so the AI can read the page. Each OCR unit is placed where it
            # sits on the page; PII parts are left out (the visible token stamp already covers them).
            pii = [(s_.start, s_.end) for s_ in spans]
            for (text, r), off in zip(units, offs):
                segs, cur = [], None
                for k, ch in enumerate(text):
                    g = off + k
                    inside = any(a_ <= g < b_ for a_, b_ in pii)
                    if inside:
                        cur = None
                        continue
                    if cur is None:
                        cur = [k, k]
                        segs.append(cur)
                    cur[1] = k + 1
                cw = r.width / max(1, len(text))
                for k0, k1 in segs:
                    seg = text[k0:k1].strip()
                    if not seg:
                        continue
                    lead = len(text[k0:k1]) - len(text[k0:k1].lstrip())
                    x = r.x0 + (k0 + lead) * cw
                    w1 = fitz.get_text_length(seg, fontname="helv", fontsize=1) or 1
                    fs = max(1.0, min(r.height * 0.9, (len(seg) * cw) / w1))
                    try:
                        page.insert_text(fitz.Point(x, r.y1 - r.height * 0.2), seg, fontsize=fs,
                                         fontname="helv", render_mode=3)
                    except Exception:
                        pass
            continue

        hits = 0
        placed: list = []  # longer values go first; a part ("Rachel") inside "Rachel Ortiz" is skipped

        def covered(r):
            c = fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
            return any(c in p_ for p_ in placed)

        for value, cat in sorted(found.items(), key=lambda kv: -len(kv[0])):
            if len(value) < 3:
                continue
            exact = cat.endswith("~")  # lone first/last name: match exact capitalization only
            tok = vault.token_for(value, cat.rstrip("~"))
            for r in page.search_for(value):
                if covered(r) or (exact and value not in page.get_textbox(r + (-1, -1, 1, 1))):
                    continue
                _redact(page, r, tok)
                placed.append(r)
                hits += 1
        # values the regex finds on this page that weren't in the global list
        for s in find_pii(texts[i], None, use_ner=False):
            if s.text not in found:
                found[s.text] = s.category
                for r in page.search_for(s.text):
                    if covered(r):
                        continue
                    _redact(page, r, vault.token_for(s.text, s.category))
                    placed.append(r)
                    hits += 1
        if hits:
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS)
            count += hits

    # bookmarks
    toc = doc.get_toc(simple=False)
    if toc:
        doc.set_toc([[lvl, _tok_text(title, found, vault)[0], pg, *rest] for lvl, title, pg, *rest in toc])
    # metadata and attachments
    doc.set_metadata({})
    try:
        doc.del_xml_metadata()
    except Exception:
        pass
    for name in list(doc.embfile_names()):
        doc.embfile_del(name)

    # Leak check: re-read the output and make sure no found value survived
    doc.save(out_path, garbage=4, deflate=True, clean=True)
    check = fitz.open(out_path)
    final_text = "\n".join(p.get_text("text") for p in check)
    leaks = sorted({v for v, c in found.items() if len(v) >= 3 and re.search(
        r"(?<![\w])" + re.escape(v) + r"(?![\w])", final_text, 0 if c.endswith("~") else re.IGNORECASE)})
    if leaks:
        warnings.append(f"{len(leaks)} value(s) could not be located for redaction and are still in the PDF text.")
    return {"replaced": {"token": count}, "values_found": len(found), "ocr_pages": len(ocr_pages),
            "warnings": warnings, "leak_count": len(leaks)}
