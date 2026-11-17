"""Word (.docx): find PII in every paragraph (body, tables, headers, footers) and tokenize it.

Word splits text into "runs" (formatting chunks), and a name can straddle two runs.
Each paragraph is handled as a whole: replacements are written back into the runs they
fall in, and a replacement that crosses runs is placed in the first run it touches.
"""
from __future__ import annotations

import re
from pathlib import Path

from docx import Document

from ..detect import find_pii


def _xml_parts(doc):
    """Every XML part of the package: body, headers, footers, footnotes, endnotes, comments."""
    for part in doc.part.package.iter_parts():
        el = getattr(part, "_element", None)
        if el is not None:
            yield part, el


def iter_p_elements(doc):
    """Every w:p anywhere (tables, text boxes, headers, footnotes...)."""
    for _, el in _xml_parts(doc):
        yield from el.iter(W + "p")


def text_nodes(p):
    """w:t nodes that belong to this paragraph itself (not to a nested text-box paragraph)."""
    out = []
    for t in p.iter(W + "t"):
        anc = t.getparent()
        while anc is not None and anc.tag != W + "p":
            anc = anc.getparent()
        if anc is p:
            out.append(t)
    return out


def full_text(path: Path) -> str:
    doc = Document(path)
    return "\n".join("".join(t.text or "" for t in text_nodes(p)) for p in iter_p_elements(doc))


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def replace_in_nodes(nodes, replacements: list[tuple[int, int, str]]) -> int:
    """replacements: (start, end, new_text) in joined-node-text coordinates, non overlapping.
    A replacement crossing nodes is written into the first node it touches."""
    if not nodes or not replacements:
        return 0
    texts = [n.text or "" for n in nodes]
    bounds, pos = [], 0
    for t in texts:
        bounds.append((pos, pos + len(t)))
        pos += len(t)
    for s, e, new in sorted(replacements, key=lambda x: x[0], reverse=True):
        first = next((i for i, (a, b) in enumerate(bounds) if a <= s < b), None)
        if first is None:
            continue
        last = next((i for i, (a, b) in enumerate(bounds) if a < e <= b), first)
        a0 = bounds[first][0]
        if first == last:
            t = texts[first]
            texts[first] = t[: s - a0] + new + t[e - a0:]
        else:
            al = bounds[last][0]
            texts[first] = texts[first][: s - a0] + new
            for i in range(first + 1, last):
                texts[i] = ""
            texts[last] = texts[last][e - al:]
    for n, t in zip(nodes, texts):
        n.text = t
        if t != t.strip():
            n.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    return len(replacements)


def _label_table_names(doc) -> dict[str, str]:
    """Names in tables laid out as  | Name | Olivia Nguyen |"""
    from ..detect import LABEL_ONLY_RE
    out: dict[str, str] = {}
    for tbl in doc.element.body.iter(W + "tbl"):
        for tr in tbl.iter(W + "tr"):
            cells = ["".join(t.text or "" for t in tc.iter(W + "t")).strip() for tc in tr.iter(W + "tc")]
            for a, b in zip(cells, cells[1:]):
                if (LABEL_ONLY_RE.match(a) and b and len(b) < 60 and not LABEL_ONLY_RE.match(b)
                        and re.fullmatch(r"[A-Z][a-zA-Z'\u2019\-]+(?:[ ,]+[A-Z][a-zA-Z'\u2019\-]+){1,3}", b)):
                    out.setdefault(b, "PERSON")
    return out


def find_values(path: Path, known: dict | None, use_ner: bool):
    """(found, origin, text) for the whole document, found once so names are caught consistently."""
    from ..detect import find_values as fv, drop_ignored, add_name_parts
    doc = Document(path)
    text = full_text(path)
    found, origin = fv(text, known, use_ner)
    for v, c in _label_table_names(doc).items():
        found.setdefault(v, c)
        origin.setdefault(v, "regex")
    add_name_parts(found, origin)
    return drop_ignored(found), origin, text


def scan(path: Path, known: dict | None, use_ner: bool, with_findings: bool) -> dict:
    from ..detect import findings
    text = full_text(path)
    info = {"type": "word", "paragraphs": len([l for l in text.splitlines() if l.strip()])}
    if with_findings:
        found, origin, text = find_values(path, known, use_ner)
        info["findings"] = findings(text, found, origin)
    return info


def sanitize(path: Path, out_path: Path, vault, use_ner: bool = True, known: dict | None = None,
             review: dict | None = None) -> dict:
    from ..detect import review_values, with_known, drop_ignored
    doc = Document(path)
    approved = review_values(review)
    if approved is not None:
        found = drop_ignored(with_known(approved, known))  # the user's reviewed list; the model already ran during the scan
    else:
        found = find_values(path, known, use_ner)[0]
    # then replace every occurrence of every found value, paragraph by paragraph
    from ..detect import known_value_spans, resolve
    count = 0
    for p in iter_p_elements(doc):
        nodes = text_nodes(p)
        ptxt = "".join(n.text or "" for n in nodes)
        if not ptxt.strip():
            continue
        local = resolve(known_value_spans(ptxt, found) + find_pii(ptxt, None, use_ner=False))
        reps = [(s.start, s.end, vault.token_for(s.text, s.category)) for s in local]
        count += replace_in_nodes(nodes, reps)
    # hyperlink targets such as mailto:jane@olemiss.edu
    for part, _ in _xml_parts(doc):
        for rel in list(part.rels.values()):
            if rel.is_external and rel.reltype.endswith("/hyperlink"):
                tgt = rel._target
                hs = resolve(known_value_spans(tgt, found) + find_pii(tgt, None, use_ner=False))
                if hs:
                    for h in sorted(hs, key=lambda x: x.start, reverse=True):
                        tgt = tgt[:h.start] + vault.token_for(h.text, h.category) + tgt[h.end:]
                    rel._target = tgt
    # document properties (author, last modified by, comments)
    cp = doc.core_properties
    cp.author = ""
    cp.last_modified_by = ""
    cp.comments = ""
    _strip_comments_and_tracked(doc)
    doc.save(out_path)
    final = full_text(out_path)
    leaks = [v for v, c in found.items() if len(v) >= 3 and known_value_spans(final, {v: c})]
    return {"replaced": {"token": count}, "values_found": len(found), "leak_count": len(leaks),
            "warnings": [f"{len(leaks)} value(s) are still in the document."] if leaks else []}


def _strip_comments_and_tracked(doc):
    """Remove reviewer comments and tracked-change author names."""
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    body = doc.element.body
    for tag in ("commentRangeStart", "commentRangeEnd", "commentReference"):
        for el in list(body.iter(ns + tag)):
            parent = el.getparent()
            if parent is not None:
                parent.remove(el)
    for el in body.iter():
        if el.get(ns + "author") is not None:
            el.set(ns + "author", "Reviewer")
    # drop the comments part itself
    try:
        part = doc.part
        for rel_id, rel in list(part.rels.items()):
            if rel.reltype.endswith("/comments"):
                part.drop_rel(rel_id)
    except Exception:
        pass
