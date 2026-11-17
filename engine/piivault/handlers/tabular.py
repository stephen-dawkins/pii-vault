"""CSV and Excel: find the real table, classify its columns, then tokenize per the user's plan.

Many exports (Banner class lists, Qualtrics, survey tools) put a block of report information
above the table: course title, term, CRN, enrollment counts. PII Vault finds the real header
row on its own and calls everything above it "extra info". The user picks:
    remove  (default) the extra rows are deleted, so the protected copy is just the table
    keep    the extra rows stay where they are, with any personal information in them tokenized
Sheets that aren't tables at all (instructions, notes) are "text tabs": scanned like a Word
document and kept, or left out of the protected copy, per sheet.

Plan format (what the app sends back after the review screen), per file:
    {"Sheet1": {"Student Name": "token", "DOB": "year", "Comments": "scan", "Major": "keep"},
     "_extra": "remove" | "keep",
     "_text_sheets": {"Notes": true, "Instructions": false},   # include this text tab?
     "_header_rows": {"Sheet1": 15}}                             # 1-based; 0 = treat as a text tab
CSV files use the sheet name "CSV".
"""
from __future__ import annotations

import csv
import io
import math
import re
from datetime import date, datetime, time
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils.cell import coordinate_from_string
from openpyxl.worksheet.cell_range import CellRange

from ..detect import classify_column, default_action, find_pii, apply_spans

HEADER_SCAN = 60          # look for the header row in the first 60 rows
EXTRA_DEFAULT = "remove"  # what to do with the report info above the table
NUMBER_RE = re.compile(r"^[\s$%(),.+-]*\d[\d\s$%(),.+-]*$")


# ------------------------------------------------------------------ reading
def _read_csv(path: Path) -> list[list[str]]:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    try:
        dialect = csv.Sniffer().sniff(text[:5000], delimiters=",\t;|")
    except csv.Error:
        dialect = csv.excel
    return [row for row in csv.reader(io.StringIO(text), dialect)]


def _is_csv(path: Path) -> bool:
    return path.suffix.lower() in (".csv", ".tsv", ".txt")


def _empty(v) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def _filled(row) -> list:
    return [v for v in row if not _empty(v)]


def _texty(v) -> bool:
    """Looks like a column label: words or a date, not a number."""
    if isinstance(v, (datetime, date, time)):
        return True
    return isinstance(v, str) and not NUMBER_RE.match(v)


def _sheet_rows(path: Path):
    """Yield (sheet_name, rows) with plain values. CSV files are one sheet called "CSV"."""
    if _is_csv(path):
        yield "CSV", _read_csv(path)
        return
    wb = load_workbook(path, read_only=True, data_only=True)
    for ws in wb.worksheets:
        yield ws.title, [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()


# --------------------------------------------------------- finding the table
def find_header(rows: list[list]) -> int | None:
    """0-based index of the real header row, or None when the sheet isn't a table (a text tab).

    The header is the first row in the top 60 that is (1) at least three quarters as wide as the widest
    row up there, (2) mostly words or dates rather than numbers, and (3) followed by rows that
    are filled in about as wide. Report lines above a table ("Term | Fall 2026") are too narrow
    to qualify, so they become the extra info."""
    top = rows[:HEADER_SCAN]
    counts = [len(_filled(r)) for r in top]
    if not counts or max(counts) == 0:
        return None
    widest = max(counts)
    if widest == 1:
        # a one-column list ("Email" then emails) is still a table when its label says what it is
        first = next(i for i, c in enumerate(counts) if c)
        label = _filled(top[first])[0]
        below = [_filled(r)[0] for r in rows[first + 1:first + 201] if _filled(r)]
        if _texty(label) and below and classify_column(str(label), below)["category"]:
            return first
        return None
    for i, r in enumerate(top):
        f = _filled(r)
        if len(f) < max(2, 0.75 * widest):
            continue
        if sum(_texty(v) for v in f) / len(f) < 0.6:
            continue
        below = [len(_filled(b)) for b in rows[i + 1:i + 12] if _filled(b)][:6]
        if not below:
            continue
        if sum(1 for n in below if n >= max(2, 0.4 * len(f))) >= math.ceil(len(below) / 2):
            return i
    return None


def _header_index(name: str, rows: list[list], options: dict) -> int | None:
    """The header row the user set on the review screen (1-based, 0 = text tab), else our guess."""
    forced = (options.get("_header_rows") or {}).get(name)
    if forced is not None:
        n = int(forced)
        return None if n <= 0 or n > len(rows) else n - 1
    return find_header(rows)


def _cell_texts(rows: list[list]) -> list[str]:
    return [v for r in rows for v in r if isinstance(v, str) and v.strip()]


def _mask_found(s: str, known: dict, use_ner: bool) -> tuple[str, int]:
    spans = find_pii(s, known, use_ner)
    out, last = [], 0
    for sp in spans:
        out.append(s[last:sp.start])
        out.append("•" * min(8, max(3, sp.end - sp.start)))
        last = sp.end
    out.append(s[last:])
    return "".join(out), len(spans)


def _summary(rows: list[list], known: dict, use_ner: bool, limit: int = 6) -> tuple[list[str], int]:
    """Short preview lines for the review screen (found values blanked out) and how many values
    would be tokenized. The local model runs once over all the text, not once per cell."""
    texts = _cell_texts(rows)
    k = dict(known or {})
    if use_ner and texts:
        from ..detect import ner_spans
        k.update({s.text: s.category for s in ner_spans("\n".join(texts))})
    found, preview = 0, []
    for r in rows:
        cells = []
        for v in _filled(r):
            if isinstance(v, str):
                masked, n = _mask_found(v.strip(), k, False)
                found += n
                cells.append(masked)
            elif isinstance(v, (datetime, date)):
                cells.append(v.strftime("%m/%d/%Y"))
            else:
                cells.append(str(v))
        if cells and len(preview) < limit:
            line = "  ·  ".join(c.replace("\n", " ") for c in cells)
            preview.append(line[:90] + ("…" if len(line) > 90 else ""))
    return preview, found


# -------------------------------------------------------------------- scan
def scan(path: Path, known: dict | None = None, use_ner: bool = False, options: dict | None = None) -> dict:
    """options: {"_header_rows": {"Sheet1": 15}} when the person corrected the header row."""
    sheets = []
    for name, all_rows in _sheet_rows(path):
        if not any(_filled(r) for r in all_rows):
            continue  # empty sheet
        h = _header_index(name, all_rows, options or {})
        if h is None:
            preview, found = _summary(all_rows, known or {}, use_ner, limit=3)
            sheets.append({"name": name, "kind": "text", "header_row": 0, "guessed_header_row": (find_header(all_rows) or -1) + 1,
                           "lines": sum(1 for r in all_rows if _filled(r)),
                           "found": found, "preview": preview, "columns": [], "rows": 0})
            continue
        header = [("" if v is None else str(v)) for v in all_rows[h]]
        body = all_rows[h + 1:h + 1 + 2000]
        cols = []
        for i, hd in enumerate(header):
            values = [r[i] if i < len(r) else None for r in body]
            filled = [v for v in values if not _empty(v)]
            if not hd.strip() and not filled:
                continue  # blank spacer column
            info = classify_column(hd, values)
            cols.append({
                "index": i, "header": hd, "category": info["category"], "quasi": info["quasi"],
                "free_text": info["free_text"], "reason": info["reason"],
                "action": default_action(info), "filled": len(filled),
                # masked preview only, so the review screen never shows full values
                "preview": [_mask(v) for v in filled[:3]] if (info["category"] or info["free_text"]) else
                           [str(v)[:40] for v in filled[:3]],
            })
        extra_rows = [r for r in all_rows[:h] if _filled(r)]
        sheet = {"name": name, "kind": "table", "header_row": h + 1,
                 "rows": sum(1 for r in all_rows[h + 1:] if _filled(r)), "columns": cols,
                 "extra_rows": len(extra_rows)}
        if extra_rows:
            sheet["extra_preview"], sheet["extra_found"] = _summary(extra_rows, known or {}, use_ner)
        sheets.append(sheet)
    has_extra = any(s.get("extra_rows") for s in sheets)
    return {"type": "table", "sheets": sheets, "has_extra": has_extra,
            "has_text_sheets": any(s["kind"] == "text" for s in sheets), "extra_default": EXTRA_DEFAULT}


def _mask(v) -> str:
    s = str(v)
    if len(s) <= 2:
        return "*" * len(s)
    return s[0] + "*" * (min(len(s), 12) - 2) + s[-1]


# --------------------------------------------------------------- transforms
def _year(v):
    if isinstance(v, (datetime, date)):
        return v.year
    m = re.search(r"(19|20)\d{2}", str(v))
    if m:
        return int(m.group())
    m = re.search(r"\d{1,2}[/-]\d{1,2}[/-](\d{2})$", str(v).strip())
    if m:
        yy = int(m.group(1))
        return 2000 + yy if yy < 30 else 1900 + yy
    return None


def _transform(v, action: str, category: str | None, vault, known: dict, use_ner: bool):
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return v
    if action == "keep":
        return v
    if action == "drop":
        return None
    if action == "year":
        return _year(v)
    if action == "token":
        if isinstance(v, (datetime, date)):
            v = v.strftime("%Y-%m-%d")
        return vault.token_for(str(v), category or "OTHER")
    if action == "scan":
        return _scan_text(v, known, vault)
    return v


def _scan_text(v, known: dict, vault):
    """Free text: replace every name, email, ID... found in it (the model already ran in a batch)."""
    if not isinstance(v, str) or not v.strip():
        return v
    spans = find_pii(v, known, use_ner=False)
    return apply_spans(v, spans, vault) if spans else v


def _plan_for(sheet: str, header: list, plan: dict | None, scanned: dict) -> list[tuple[str, str | None]]:
    sp = (plan or {}).get(sheet, {})
    sc = {c["header"]: c for s in scanned["sheets"] if s["name"] == sheet for c in s["columns"]}
    out = []
    for h in header:
        h = "" if h is None else str(h)
        c = sc.get(h, {})
        out.append((sp.get(h, c.get("action", "keep")), c.get("category")))
    return out


def _ner_known(texts: list[str], use_ner: bool) -> dict[str, str]:
    """Run the local model once over a batch of text, not once per cell."""
    texts = sorted({t.strip() for t in texts if isinstance(t, str) and t.strip()})
    if not use_ner or not texts:
        return {}
    from ..detect import ner_spans
    return {s.text: s.category for s in ner_spans("\n".join(texts))}


def _batch_ner(rows, col_plan, use_ner) -> dict[str, str]:
    texts = []
    for i, (action, _) in enumerate(col_plan):
        if action == "scan":
            texts += [r[i] for r in rows if i < len(r)]
    return _ner_known(texts, use_ner)


def _collect_known(rows, col_plan, vault) -> dict[str, str]:
    """Values from tokenized PERSON/ID/EMAIL columns, used to catch them inside free text."""
    known: dict[str, str] = {}
    for i, (action, cat) in enumerate(col_plan):
        if action == "token" and cat in ("PERSON", "EMAIL", "ID", "PHONE"):
            for r in rows:
                v = r[i] if i < len(r) else None
                if v is None or str(v).strip() == "":
                    continue
                s = str(v).strip()
                known[s] = cat
                if cat == "PERSON":
                    # "Last, First" -> also "First Last", plus first and last names on their own
                    if "," in s:
                        last, first = [p.strip() for p in s.split(",", 1)]
                        if first and last:
                            known[f"{first} {last}"] = "PERSON"
                    from ..detect import name_parts
                    for part in name_parts(s):
                        known.setdefault(part, "PERSON~")
    return known


def _extra_known(extra_rows: list[list], known: dict, use_ner: bool) -> dict[str, str]:
    """Names, emails and IDs in the report info above the table ("Instructor: Jane Doe").
    Collected in both modes, so the same name is also caught in a comments column."""
    from ..detect import add_name_parts
    texts = _cell_texts(extra_rows)
    k = {**known, **_ner_known(texts, use_ner)}
    found: dict[str, str] = {}
    for t in texts:
        for sp in find_pii(t, k, use_ner=False):
            found.setdefault(sp.text, sp.category)
    add_name_parts(found)
    return found


def _bump(counts: dict, key: str, n: int = 1) -> None:
    counts[key] = counts.get(key, 0) + n


# ------------------------------------------------------- worksheet surgery
def _delete_top_rows(ws, n: int) -> None:
    """Delete rows 1..n and move everything below up, including merged cells, row heights,
    frozen panes and the filter range (openpyxl's delete_rows leaves those behind)."""
    if n <= 0:
        return
    merges = [CellRange(str(r)) for r in ws.merged_cells.ranges]
    for r in merges:
        ws.unmerge_cells(str(r))
    heights = {i: d.height for i, d in ws.row_dimensions.items() if d.height}
    ws.delete_rows(1, n)
    for r in merges:
        if r.min_row > n:
            r.shift(row_shift=-n)
            ws.merge_cells(r.coord)
    for i in list(ws.row_dimensions.keys()):
        ws.row_dimensions[i].height = None
    for i, h in heights.items():
        if i > n:
            ws.row_dimensions[i - n].height = h
    if ws.freeze_panes:
        col, row = coordinate_from_string(ws.freeze_panes)
        row = row - n if row > n else 1
        ws.freeze_panes = None if (row == 1 and col == "A") else f"{col}{row}"
    if ws.auto_filter.ref:
        af = CellRange(ws.auto_filter.ref)
        if af.min_row > n:
            af.shift(row_shift=-n)
            ws.auto_filter.ref = af.coord
        else:
            ws.auto_filter.ref = None
    # rules that point at rows (conditional formatting, dropdown lists) would land on the wrong rows
    ws.conditional_formatting = type(ws.conditional_formatting)()
    ws.data_validations.dataValidation = []
    ws.print_title_rows = None


def _scan_cells(ws, first_row: int, last_row: int, known: dict, vault, counts: dict, key: str) -> None:
    for row in ws.iter_rows(min_row=first_row, max_row=last_row):
        for cell in row:
            v = cell.value
            if not isinstance(v, str) or v.startswith("="):
                continue
            nv = _scan_text(v, known, vault)
            if nv != v:
                cell.value = nv
                _bump(counts, key)


# ----------------------------------------------------------------- sanitize
def sanitize(path: Path, out_path: Path, vault, plan: dict | None = None, use_ner: bool = True,
             known_extra: dict | None = None, options: dict | None = None) -> dict:
    options = options or {}
    extra_mode = options.get("_extra") or EXTRA_DEFAULT
    include_text = options.get("_text_sheets") or {}
    scanned = scan(path, options=options)  # columns only; values are tokenized below
    counts: dict[str, int] = {}
    report = {"extra": extra_mode, "removed_rows": 0, "text_sheets": [], "left_out": []}
    base_known = dict(known_extra or {})

    if _is_csv(path):
        rows = _read_csv(path)
        h = _header_index("CSV", rows, options)
        if h is None:  # no table at all: scan every cell as text
            known = {**base_known, **vault.known_values(), **_ner_known(_cell_texts(rows), use_ner)}
            out_rows = [[_scan_text(v, known, vault) for v in r] for r in rows]
            report["text_sheets"].append("CSV")
        else:
            extra, header, body = rows[:h], rows[h], rows[h + 1:]
            col_plan = _plan_for("CSV", header, plan, scanned)
            known = {**base_known, **_batch_ner(body, col_plan, use_ner), **_collect_known(body, col_plan, vault)}
            known.update(_extra_known(extra, known, use_ner))
            new_header, keep_idx = [], []
            for i, hd in enumerate(header):
                if col_plan[i][0] != "drop":
                    keep_idx.append(i)
                    hd = _scan_text(hd, known, vault)  # a header cell should never hold an email or name
                    new_header.append(hd + " (year)" if col_plan[i][0] == "year" else hd)
            out_rows = []
            if extra and extra_mode == "keep":
                for r in extra:
                    nr = [_scan_text(v, known, vault) for v in r]
                    if nr != r:
                        _bump(counts, "extra_info")
                    out_rows.append(nr)
            elif extra:
                report["removed_rows"] = len(extra)
            out_rows.append(new_header)
            for r in body:
                nr = []
                for i in keep_idx:
                    v = r[i] if i < len(r) else ""
                    nv = _transform(v, col_plan[i][0], col_plan[i][1], vault, known, use_ner)
                    if nv != v:
                        _bump(counts, col_plan[i][0])
                    nr.append("" if nv is None else nv)
                out_rows.append(nr)
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(out_rows)
        return {"replaced": counts, "tables": report}

    wb = load_workbook(path)  # full load keeps formatting, formulas and other sheets
    # Table tabs first, text tabs last, so a name found in a table (or its notes column) is also
    # caught when it appears on an instructions or notes tab of the same workbook.
    sheets = []
    for ws in list(wb.worksheets):
        rows = [[c.value for c in row] for row in ws.iter_rows()]
        sheets.append((ws, rows, _header_index(ws.title, rows, options) if any(_filled(r) for r in rows) else None))
    sheets.sort(key=lambda t: t[2] is None)
    for ws, rows, h in sheets:
        if not any(_filled(r) for r in rows):
            continue

        if h is None:  # a text tab: instructions, notes, a letter pasted into a sheet
            if not include_text.get(ws.title, True):
                if len(wb.worksheets) > 1:
                    wb.remove(ws)
                else:
                    ws.delete_rows(1, ws.max_row)
                report["left_out"].append(ws.title)
                continue
            known = {**base_known, **vault.known_values(), **_ner_known(_cell_texts(rows), use_ner)}
            _scan_cells(ws, 1, ws.max_row, known, vault, counts, "text_tab")
            report["text_sheets"].append(ws.title)
            continue

        hr = h + 1  # 1-based header row
        header = rows[h]
        body = rows[h + 1:]
        col_plan = _plan_for(ws.title, header, plan, scanned)
        known = {**base_known, **_batch_ner(body, col_plan, use_ner), **_collect_known(body, col_plan, vault)}
        known.update(_extra_known(rows[:h], known, use_ner))
        drops = []
        for i, (action, cat) in enumerate(col_plan):
            if action == "keep":
                continue
            if action == "drop":
                drops.append(i + 1)
                continue
            if action == "year":
                ws.cell(row=hr, column=i + 1).value = f"{header[i]} (year)"
            for r in range(hr + 1, ws.max_row + 1):
                cell = ws.cell(row=r, column=i + 1)
                v = cell.value
                if isinstance(v, str) and v.startswith("="):
                    continue  # leave formulas alone
                nv = _transform(v, action, cat, vault, known, use_ner)
                if nv != v:
                    cell.value = nv
                    if action == "year":
                        cell.number_format = "0"
                    _bump(counts, action)

        _scan_cells(ws, hr, hr, known, vault, counts, "header")  # a header cell should never hold an email or name
        if h > 0:
            if extra_mode == "keep":
                _scan_cells(ws, 1, h, known, vault, counts, "extra_info")
            else:
                report["removed_rows"] += h
        for col in sorted(drops, reverse=True):
            ws.delete_cols(col)
        if h > 0 and extra_mode != "keep":
            _delete_top_rows(ws, h)

        # cell comments can hold names ("checked by J. Smith"), so remove them
        for row in ws.iter_rows():
            for cell in row:
                if cell.comment is not None:
                    cell.comment = None
    # headers and footers on printed pages can hold an instructor's name
    for ws in wb.worksheets:
        for hf in (ws.oddHeader, ws.oddFooter, ws.evenHeader, ws.evenFooter, ws.firstHeader, ws.firstFooter):
            for part in (hf.left, hf.center, hf.right):
                if part.text:
                    part.text = _scan_text(part.text, base_known, vault)
    # strip author / last-modified-by metadata
    wb.properties.creator = None
    wb.properties.lastModifiedBy = None
    wb.save(out_path)
    return {"replaced": counts, "tables": report}
