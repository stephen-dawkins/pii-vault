"""PII detection.

Three layers, all running on this Mac:
1. Column rules: header names and value patterns classify whole spreadsheet columns.
2. Regex: emails, phones, SSNs, card numbers, IPs, dates of birth near "DOB"/"born".
3. Names in free text: the local Ollama model (stephen-qwen by default), falling back
   to spaCy if installed. Nothing here ever leaves the machine.
Every finding is a Span(start, end, text, category).
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass, asdict

# ------------------------------------------------------------------ regexes
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"(?<![\w.])(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?![\w])")
SSN_RE = re.compile(r"(?<!\d)(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}(?!\d)")
CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,16}(?!\d)")
IP_RE = re.compile(r"(?<!\d)(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?!\d)")
DATE_PAT = r"(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.? \d{1,2},? \d{4})"
DOB_RE = re.compile(r"(?i)\b(?:dob|d\.o\.b\.|date of birth|birth ?date|birthday|born(?: on)?)\b[^.\n]{0,45}?(" + DATE_PAT + ")")
LABELED_ID_RE = re.compile(
    r"(?i)\b(?:student|um|banner|employee|emp|net|web|user)\s*(?:id|#|number|no\.?)\s*[:#\-]?\s*([A-Za-z0-9]{5,12})\b")
STREET_RE = re.compile(
    r"\b\d{1,6}\s+(?:[NSEW]\.?\s+)?(?:(?:\d{1,3}(?:st|nd|rd|th)|[A-Z][a-z]+)\.?\s){1,4}(?:St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Ln|Lane|Blvd|Boulevard|Ct|Court|Cir|Circle|Way|Pl|Place|Hwy|Highway|Pkwy|Parkway)\b\.?(?:\s+[NSEW]\b\.?)?(?:,?\s*(?:Apt|Unit|Ste|Suite|#)\s*\w+)?"
    r"(?:,\s*[A-Z][a-zA-Z.]+(?:\s[A-Z][a-zA-Z.]+){0,2},\s*[A-Z]{2}(?:\s+\d{5}(?:-\d{4})?)?)?")
PERSON_LABELS = (r"(?:student(?: name)?|name|full name|legal name|preferred name|participant|resident|applicant|"
                 r"employee|patient|client|parent|guardian|emergency contact|contact person|signed by|signature|"
                 r"signer|prepared for|prepared by|submitted by|approved by|advisor|adviser|instructor|"
                 r"recipient|requester|requested by|witness|attendee|member|tenant|borrower|renter)")
LABELED_PERSON_RE = re.compile(
    r"(?i:\b" + PERSON_LABELS + r")\s*[:\-\u2013]\s*((?:[A-Z][a-zA-Z'\u2019\-]+\.?)(?:[ \t]+(?:[A-Z][a-zA-Z'\u2019\-]*\.?)){0,3})")
BY_PERSON_RE = re.compile(
    r"(?i:\b(?:signed|prepared|submitted|approved|requested|reviewed|completed|reported|referred) by|\bon behalf of)"
    r"\s+((?:[A-Z][a-zA-Z'\u2019\-]+\.?)(?:[ \t]+(?:[A-Z][a-zA-Z'\u2019\-]*\.?)){0,3})")
LABEL_ONLY_RE = re.compile(r"(?i)^\s*" + PERSON_LABELS + r"\s*:?\s*$")
HONORIFIC_RE = re.compile(r"\b(?:Mr|Mrs|Ms|Miss|Dr|Prof)\.?\s+([A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]+)?)")


def _luhn(digits: str) -> bool:
    s, alt = 0, False
    for d in reversed(digits):
        n = int(d)
        if alt:
            n *= 2
            if n > 9:
                n -= 9
        s += n
        alt = not alt
    return s % 10 == 0


@dataclass
class Span:
    start: int
    end: int
    text: str
    category: str
    source: str = "regex"

    def to_dict(self):
        return asdict(self)


def _person(m, group=1) -> "Span":
    """Name span from a label match, without a sentence-ending period ("Hope Grant." -> "Hope Grant")."""
    s, e, t = m.start(group), m.end(group), m.group(group)
    if t.endswith(".") and len(t.split()[-1]) > 2:
        t, e = t[:-1], e - 1
    return Span(s, e, t, "PERSON")


def regex_spans(text: str) -> list[Span]:
    spans: list[Span] = []
    for m in EMAIL_RE.finditer(text):
        spans.append(Span(m.start(), m.end(), m.group(), "EMAIL"))
    for m in SSN_RE.finditer(text):
        spans.append(Span(m.start(), m.end(), m.group(), "SSN"))
    for m in CARD_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 16 and _luhn(digits):
            spans.append(Span(m.start(), m.end(), m.group().strip(), "ACCOUNT"))
    for m in PHONE_RE.finditer(text):
        spans.append(Span(m.start(), m.end(), m.group(), "PHONE"))
    for m in IP_RE.finditer(text):
        spans.append(Span(m.start(), m.end(), m.group(), "IP"))
    for m in DOB_RE.finditer(text):
        spans.append(Span(m.start(1), m.end(1), m.group(1), "DOB"))
    for m in LABELED_ID_RE.finditer(text):
        if any(c.isdigit() for c in m.group(1)):
            spans.append(Span(m.start(1), m.end(1), m.group(1), "ID"))
    for m in STREET_RE.finditer(text):
        spans.append(Span(m.start(), m.end(), m.group(), "ADDRESS"))
    for rx in (LABELED_PERSON_RE, BY_PERSON_RE, HONORIFIC_RE):
        for m in rx.finditer(text):
            spans.append(_person(m))
    return spans


_known_cache: dict = {}
# Words that are names but also everyday capitalized words; never matched as a lone name part.
PART_STOPWORDS = {"the", "and", "for", "with", "from", "this", "that", "will", "may", "june", "april", "august",
                  "mark", "bill", "art", "dean", "major", "minor", "page", "rose", "summer", "winter", "fall",
                  "spring", "case", "law", "king", "jr", "sr", "ii", "iii", "iv", "university", "college",
                  "student", "advisor", "coach", "mississippi", "oxford", "miss", "ole"}


def known_value_spans(text: str, known: dict[str, str]) -> list[Span]:
    """Find values already identified elsewhere (a Name column, an earlier file, the vault) in free text."""
    if not known:
        return []
    # cache the compiled pattern; holding a reference to the dict means its id can't be reused
    if _known_cache.get("obj") is known and _known_cache.get("len") == len(known):
        rx_full, rx_part, lower = _known_cache["entry"]
    else:
        full = sorted((v for v, c in known.items() if len(v) >= 3 and not c.endswith("~")), key=len, reverse=True)
        parts = sorted((v for v, c in known.items() if len(v) >= 3 and c.endswith("~")), key=len, reverse=True)
        rx_full = re.compile(r"(?<![\w])(?:" + "|".join(re.escape(v) for v in full) + r")(?![\w])",
                             re.IGNORECASE) if full else None
        # lone first/last names: exact capitalization only, so "grant" (financial aid) is left alone
        rx_part = re.compile(r"(?<![\w])(?:" + "|".join(re.escape(v) for v in parts) + r")(?![\w])") if parts else None
        lower = {v.casefold(): c.rstrip("~") for v, c in known.items()}
        _known_cache.update(obj=known, len=len(known), entry=(rx_full, rx_part, lower))
    out = []
    for rx in (rx_full, rx_part):
        if rx is not None:
            out += [Span(m.start(), m.end(), m.group(), lower.get(m.group().casefold(), "PERSON"), "known")
                    for m in rx.finditer(text)]
    return out


def name_parts(full_name: str) -> list[str]:
    """'Carter, Tamika' -> ['Tamika', 'Carter']; 'Sarah Beth McAllister' -> ['Sarah Beth', 'Sarah', 'Beth', 'McAllister']."""
    s = full_name.strip()
    if "," in s:
        last, first = [p.strip() for p in s.split(",", 1)]
        words = first.split() + last.split()
        extra = [first] if len(first.split()) > 1 else []
    else:
        words = s.split()
        extra = [" ".join(words[:-1])] if len(words) > 2 else []
    out = []
    for w in extra + words:
        w = w.strip(".,")
        if len(w) >= 3 and w[0].isupper() and w.casefold() not in PART_STOPWORDS:
            out.append(w)
    return out


# ------------------------------------------------------------- local models
OLLAMA_URL = os.environ.get("PIIVAULT_OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("PIIVAULT_MODEL", "stephen-qwen")

LLM_PROMPT = """You are a PII detector. Find every personal identifier in the TEXT below:
people's names (full, first-only or last-only), email addresses, phone numbers, street addresses,
student or employee ID numbers, dates of birth, and any other value that identifies a specific person.
Do NOT flag organization names, course names, job titles, cities alone, or the university's name.
Copy each value EXACTLY as it appears in the text.
Reply with JSON only: {{"pii": [{{"text": "...", "type": "PERSON|EMAIL|PHONE|ADDRESS|ID|DOB|OTHER"}}]}}

TEXT:
{chunk}"""

_ollama_ok: bool | None = None


def ollama_models() -> tuple[bool, list[str]]:
    """(is Ollama running, installed model names)."""
    try:
        with urllib.request.urlopen(OLLAMA_URL + "/api/tags", timeout=2) as r:
            return True, sorted(m["name"] for m in json.load(r).get("models", []))
    except Exception:
        return False, []
_spacy_nlp = None


def ollama_available() -> bool:
    global _ollama_ok
    if _ollama_ok is None:
        _, models = ollama_models()
        want = OLLAMA_MODEL if ":" in OLLAMA_MODEL else OLLAMA_MODEL + ":latest"
        _ollama_ok = any(m == OLLAMA_MODEL or m == want for m in models)
    return _ollama_ok


def _ollama_chunk(chunk: str) -> list[tuple[str, str]]:
    body = json.dumps({
        "model": OLLAMA_MODEL, "prompt": LLM_PROMPT.format(chunk=chunk), "stream": False,
        "format": "json", "think": False, "options": {"temperature": 0},
    }).encode()
    req = urllib.request.Request(OLLAMA_URL + "/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        resp = json.load(r).get("response", "{}")
    try:
        items = json.loads(resp).get("pii", [])
    except Exception:
        return []
    out = []
    for it in items:
        if isinstance(it, dict) and isinstance(it.get("text"), str) and it["text"].strip():
            out.append((it["text"].strip(), str(it.get("type", "OTHER")).upper()))
    return out


def _chunks(text: str, size: int = 1800) -> list[tuple[int, str]]:
    out, pos = [], 0
    while pos < len(text):
        end = min(len(text), pos + size)
        if end < len(text):
            cut = text.rfind("\n", pos, end)
            if cut <= pos:
                cut = text.rfind(" ", pos, end)
            end = cut if cut > pos else end
        out.append((pos, text[pos:end]))
        pos = end
    return out


def _spacy():
    global _spacy_nlp
    if _spacy_nlp is None:
        try:
            import spacy
            _spacy_nlp = spacy.load("en_core_web_sm")
        except Exception:
            _spacy_nlp = False
    return _spacy_nlp


def ner_engine() -> str:
    if os.environ.get("PIIVAULT_NER", "") == "off":
        return "none"
    if ollama_available():
        return f"ollama:{OLLAMA_MODEL}"
    if _spacy():
        return "spacy"
    return "none"


def ner_spans(text: str) -> list[Span]:
    """Names and other free-text PII via the local model."""
    engine = ner_engine()
    spans: list[Span] = []
    if engine.startswith("ollama"):
        found: dict[str, str] = {}
        for _, chunk in _chunks(text):
            if not chunk.strip():
                continue
            try:
                for val, typ in _ollama_chunk(chunk):
                    found.setdefault(val, typ if typ in
                                     {"PERSON", "EMAIL", "PHONE", "ADDRESS", "ID", "DOB", "OTHER"} else "OTHER")
            except Exception:
                continue
        for val, typ in found.items():
            if len(val) < 2:
                continue
            for m in re.finditer(r"(?<![\w])" + re.escape(val) + r"(?![\w])", text):
                spans.append(Span(m.start(), m.end(), m.group(), typ, "ollama"))
    elif engine == "spacy":
        nlp = _spacy()
        for off, chunk in _chunks(text, 50000):
            for ent in nlp(chunk).ents:
                if ent.label_ == "PERSON" and len(ent.text.strip()) > 1:
                    t = ent.text.strip()
                    if t.endswith(("'s", "’s")):
                        t = t[:-2]
                    s = off + ent.start_char
                    spans.append(Span(s, s + len(t), t, "PERSON", "spacy"))
    return spans


# Values the user unticked on the review screen ("Grant" the scholarship, not a person).
# Set per file by the CLI; resolve() drops any span whose text is in here.
IGNORE: set[str] = set()


def set_ignore(values) -> None:
    IGNORE.clear()
    IGNORE.update(_ig(v) for v in (values or []) if str(v).strip())


def _ig(v: str) -> str:
    return re.sub(r"\s+", " ", str(v)).strip().casefold()


def resolve(spans: list[Span]) -> list[Span]:
    """Drop overlaps, keeping the longest span (ties: earliest). Skips user-ignored values."""
    if IGNORE:
        spans = [s for s in spans if _ig(s.text) not in IGNORE]
    spans = sorted(spans, key=lambda s: (s.start, -(s.end - s.start)))
    out: list[Span] = []
    for s in spans:
        if s.end <= s.start:
            continue
        if out and s.start < out[-1].end:
            if (s.end - s.start) > (out[-1].end - out[-1].start):
                out[-1] = s
            continue
        out.append(s)
    return out


def find_values(text: str, known: dict[str, str] | None, use_ner: bool) -> tuple[dict[str, str], dict[str, str]]:
    """Run every detector over a whole document once.
    Returns (found: value -> category, origin: value -> which detector found it)."""
    found: dict[str, str] = dict(known or {})
    origin: dict[str, str] = {}
    for s in find_pii(text, known, use_ner):
        found.setdefault(s.text, s.category)
        origin.setdefault(s.text, s.source)
    add_family_names(text, found, origin)
    add_name_parts(found, origin)
    return drop_ignored(found), origin


NAME_WORD = r"[A-Z][a-z]+(?:['\u2019\-][A-Z]?[a-z]+)?"


def add_family_names(text: str, found: dict[str, str], origin: dict[str, str] | None = None) -> None:
    """Once 'Jasmine Carter' is a person, 'Linda Carter' later in the text is a person too
    (a parent, a sibling). Only a capitalized word right before a known surname counts."""
    surnames = set()
    for v, c in found.items():
        if c == "PERSON" and len(v.split()) > 1:
            v2 = re.sub(r"^(?:Mr|Mrs|Ms|Miss|Dr|Prof)\.?\s+", "", v)
            last = (v2.split(",", 1)[0] if "," in v2 else v2.split()[-1]).strip(" .,")
            if len(last) >= 3 and last.casefold() not in PART_STOPWORDS:
                surnames.add(last)
    if not surnames:
        return
    rx = re.compile(r"(?<![\w])(" + NAME_WORD + r")\s+(" + "|".join(re.escape(x) for x in surnames) + r")(?![\w])")
    for m in rx.finditer(text):
        first, full = m.group(1), m.group(0)
        if first.casefold() in PART_STOPWORDS or first in ("The", "Dear", "Hi", "Hello", "Mr", "Mrs", "Ms", "Dr"):
            continue
        if full not in found:
            found[full] = "PERSON"
            if origin is not None:
                origin.setdefault(full, "regex")


def add_name_parts(found: dict[str, str], origin: dict[str, str] | None = None) -> None:
    """'Marcus Delaney' also catches a later 'Marcus' or 'Delaney' on its own (exact capitalization)."""
    for v, c in list(found.items()):
        if c == "PERSON" and len(v.split()) > 1:
            for part in name_parts(re.sub(r"^(?:Mr|Mrs|Ms|Miss|Dr|Prof)\.?\s+", "", v)):
                if part not in found:
                    found[part] = "PERSON~"
                    if origin is not None:
                        origin.setdefault(part, origin.get(v, "regex"))


def find_pii(text: str, known: dict[str, str] | None = None, use_ner: bool = True) -> list[Span]:
    if not text or not text.strip():
        return []
    spans = regex_spans(text)
    if known:
        spans += known_value_spans(text, known)
    if use_ner:
        spans += ner_spans(text)
    # never re-tokenize an existing token
    from .vault import TOKEN_RE
    tok_ranges = [(m.start(), m.end()) for m in TOKEN_RE.finditer(text)]
    spans = [s for s in spans if not any(a <= s.start < b for a, b in tok_ranges)]
    return resolve(spans)


def drop_ignored(found: dict[str, str]) -> dict[str, str]:
    return {v: c for v, c in found.items() if _ig(v) not in IGNORE} if IGNORE else found


def review_values(review: dict | None) -> dict[str, str] | None:
    """The value list the user approved on the review screen, ready to use as `found`.
    One-word names match exact capitalization only, so "Hope" doesn't catch "hope"."""
    if not review:
        return None
    out = {}
    for v, c in (review.get("values") or {}).items():
        v = str(v).strip()
        if len(v) < 2:
            continue
        c = str(c).upper().rstrip("~")
        out[v] = "PERSON~" if c == "PERSON" and len(v.split()) == 1 else c
    add_name_parts(out)
    return out


def with_known(approved: dict[str, str], known: dict[str, str] | None) -> dict[str, str]:
    """The reviewed list plus every value already in the vault at sanitize time.

    The review list is built when the files are scanned. Values tokenized after that, for
    example the names in a spreadsheet protected in the same job as a Word note, must still
    be removed from the document, so they are added here (anything the person unticked stays
    out, because drop_ignored runs afterward)."""
    merged = dict(known or {})
    merged.update(approved)
    return merged


SOURCE_LABEL = {"table": "table column", "regex": "pattern", "known": "seen before", "ollama": "local model", "spacy": "spaCy"}


def findings(text: str, found: dict[str, str], origin: dict[str, str] | None = None, limit: int = 2000) -> list[dict]:
    """What would be replaced in `text`, grouped by value, with a short context snippet.
    Shown only on this Mac's review screen; never written to the AI-visible folders."""
    spans = resolve(known_value_spans(text, found) + find_pii(text, None, use_ner=False))
    groups: dict[tuple, dict] = {}
    for s in spans:
        key = (_ig(s.text), s.category)
        g = groups.get(key)
        if g is None:
            a, b = max(0, s.start - 50), min(len(text), s.end + 50)
            before = re.sub(r"\s+", " ", text[a:s.start]).lstrip()
            after = re.sub(r"\s+", " ", text[s.end:b]).rstrip()
            how = (origin or {}).get(s.text, s.source)
            g = groups[key] = {"value": s.text, "category": s.category, "count": 0,
                               "source": SOURCE_LABEL.get(how, how),
                               "before": ("…" if a > 0 else "") + before, "after": after + ("…" if b < len(text) else "")}
        g["count"] += 1
    out = sorted(groups.values(), key=lambda g: (-g["count"], g["value"].casefold()))
    return out[:limit]


def apply_spans(text: str, spans: list[Span], vault) -> str:
    out, last = [], 0
    for s in spans:  # full names first, so "Jasmine" can share "Jasmine Carter"'s token
        if s.category == "PERSON" and len(s.text.split()) > 1:
            vault.token_for(s.text, s.category)
    for s in sorted(spans, key=lambda x: x.start):
        out.append(text[last:s.start])
        out.append(vault.token_for(s.text, s.category))
        last = s.end
    out.append(text[last:])
    return "".join(out)


# --------------------------------------------------------- column classing
HEADER_RULES: list[tuple[str, str]] = [
    (r"\b(ssn|social security)", "SSN"),
    (r"e-?mail", "EMAIL"),
    (r"\b(phone|cell|mobile|telephone|tel)\b", "PHONE"),
    (r"\b(dob|birth ?date|date of birth|birthday)\b", "DOB"),
    (r"\b(street|address|addr)\b", "ADDRESS"),
    (r"\b(student|um|banner|employee|emp|net|web|person|user)[ _-]?(id|number|num|no)\b|\b(pidm|emplid|netid|webid|username|uid)\b|^id$", "ID"),
    (r"\b(name|first|last|middle|surname|given|preferred|fname|lname|full ?name|student|advisor|instructor|parent|guardian|contact|signer|signed by|recipient)\b", "PERSON"),
]
# header words that mean "not a person" even when a PERSON word is present
NOT_PERSON = re.compile(r"(?i)\b(course|class|program|department|dept|org|organization|school|college|"
                        r"major|minor|term|section|event|file|sheet|building|company|business|count|type|"
                        r"status|level|year|date|time|gpa|score|hours|credits|flag|code|title|category|comment|comments|note|notes|description|reason|feedback|response|summary)\b")
QUASI_RE = re.compile(r"(?i)\b(zip|postal|postcode|county|city|hometown|high school|hs name|gender|sex|race|ethnicity|age)\b")


def classify_column(header: str, values: list[str]) -> dict:
    """Return {'category': CAT|None, 'quasi': bool, 'free_text': bool, 'reason': str}."""
    h = str(header or "").strip()
    hl = h.lower()
    vals = [str(v).strip() for v in values if v is not None and str(v).strip() != ""]
    sample = vals[:200]
    n = max(1, len(sample))

    def share(rx):
        return sum(1 for v in sample if rx.fullmatch(v)) / n

    result = {"category": None, "quasi": bool(QUASI_RE.search(hl)), "free_text": False, "reason": ""}

    for rx, cat in HEADER_RULES:
        if re.search(rx, hl):
            if cat == "PERSON" and NOT_PERSON.search(hl):
                continue
            result.update(category=cat, reason=f"header '{h}'")
            break

    if result["category"] is None and sample:
        if share(EMAIL_RE) > 0.6:
            result.update(category="EMAIL", reason="values look like emails")
        elif share(SSN_RE) > 0.6:
            result.update(category="SSN", reason="values look like SSNs")
        elif share(PHONE_RE) > 0.6:
            result.update(category="PHONE", reason="values look like phone numbers")

    avg_len = sum(len(v) for v in sample) / n if sample else 0
    wordy = sum(1 for v in sample if len(v.split()) >= 4) / n
    if result["category"] == "PERSON" and (avg_len > 35 or wordy > 0.3):
        result["category"] = None  # sentences, not a name column
    texty_header = re.search(r"(?i)\b(comments?|notes?|description|feedback|responses?|remarks?|narrative|explanation|reason)\b", hl)
    if result["category"] is None and (avg_len > 35 or wordy >= 0.15 or (texty_header and avg_len > 8)):
        result.update(free_text=True, reason="free-text column, will be scanned for names and contact info")
    return result


# Actions the user can pick per column
ACTIONS = ["token", "year", "drop", "scan", "keep"]


def default_action(info: dict) -> str:
    if info["category"] == "DOB":
        return "year"
    if info["category"]:
        return "token"
    if info["free_text"]:
        return "scan"
    return "keep"
