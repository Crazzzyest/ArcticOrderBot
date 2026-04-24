import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional

import pdfplumber


@dataclass(frozen=True)
class OrderLine:
    leverandor: str
    varenr: str
    antall: int


@dataclass(frozen=True)
class ParseResult:
    """
    Strukturert resultat av PDF-parsing.

    - `lines`: trygt ekstraherte ordrelinjer.
    - `unparsed`: råtekst for linjer som lignet tabellrader (inneholdt
      `<desimal> <enhet>`) men som ikke matchet forventet kolonneformat.
    - `vendor`: leverandør som ble detektert.
    """
    lines: List[OrderLine]
    unparsed: List[str] = field(default_factory=list)
    vendor: str = "unknown"

    @property
    def is_complete(self) -> bool:
        return not self.unparsed

    def as_dicts(self) -> List[Dict[str, object]]:
        return [{"leverandor": l.leverandor, "varenr": l.varenr, "antall": l.antall} for l in self.lines]


class ParseIncompleteError(Exception):
    """Heves når én eller flere kandidat-rader ikke kunne parses trygt."""

    def __init__(self, pdf_path: str | Path, result: ParseResult):
        self.pdf_path = str(pdf_path)
        self.result = result
        parsed_desc = ", ".join(f"{l.varenr} x{l.antall}" for l in result.lines) or "(ingen)"
        super().__init__(
            f"Ufullstendig parsing av {self.pdf_path}: "
            f"{len(result.unparsed)} linje(r) kunne ikke tolkes. "
            f"Parsede linjer: {parsed_desc}. "
            f"Uparsede linjer: {result.unparsed}"
        )


_VENDOR_ALIASES = {
    "polaris": ["polaris"],
    "kellox": ["kellox", "honda"],
    "ktm": ["ktm"],
}


def detect_vendor(text: str) -> str:
    t = (text or "").lower()
    for vendor, needles in _VENDOR_ALIASES.items():
        if any(n in t for n in needles):
            return vendor
    return "unknown"


def _normalize_qty(qty_raw: str) -> Optional[int]:
    s = (qty_raw or "").strip()
    if not s:
        return None
    s = s.replace(" ", "").replace("\u00a0", "")
    s = s.replace(",", ".")
    try:
        val = float(s)
    except ValueError:
        return None
    if val <= 0:
        return None
    return int(round(val))


def _extract_relevant_text(full_text: str) -> str:
    """
    Prøver å hente området som typisk inneholder linjene:
    mellom 'Deres varenr' og 'Totalt'.
    """
    text = full_text or ""
    start = text.lower().find("deres varenr")
    if start == -1:
        return text
    sub = text[start:]
    end = sub.lower().find("totalt")
    if end == -1:
        return sub
    return sub[:end]


# - part: alfanumerisk som starter med bokstav (B0427), lange digit-strenger
#   (00050000068), eller varenr med bindestrek-suffiks (5456441-266).
_PART_PATTERN = r"(?:[A-Z][A-Z0-9]{1,20}(?:-[A-Z0-9]+)*|\d{4,20}(?:-[A-Z0-9]+)*)"

# Enhet: hvitliste så vi ikke forveksler forkortelser i beskrivelsen
# (f.eks. "13.91 CD" i produktnavn) med faktisk enhet.
_UNIT_PATTERN = r"(?:[Ss]tk|[Pp]cs|[Ss]t|[Ee]a|[Kk]g|[Ll]|[Mm]|[Cc]m|[Mm]m|[Pp]k|[Pp]ar)"

# En "kandidat-rad" er en linje som inneholder `<desimal> <enhet>` — typisk
# signatur for en tabellrad. Brukes til å oppdage stille drop.
_CANDIDATE_RX = re.compile(rf"\b\d+[\.,]\d+\s+{_UNIT_PATTERN}\b")

# Primær row-match, anker på starten av linjen:
# <part> <beskrivelse ...> <qty med desimal> <enhet> ...
_ROW_LINE_RX = re.compile(
    rf"^(?P<part>{_PART_PATTERN})\s+.*?\s+(?P<qty>\d+[\.,]\d+)\s+(?P<unit>{_UNIT_PATTERN})\b",
)

# Fallback: part + qty rett ved siden av hverandre (PDF-er uten enhet-kolonne).
_FALLBACK_RX = re.compile(
    rf"(?P<part>{_PART_PATTERN})\s+(?P<qty>\d+(?:[\.,]\d+)?)",
    re.MULTILINE,
)


def parse_order_pdf(path: str | Path, *, leverandor_hint: Optional[str] = None) -> ParseResult:
    """
    Leser en ordre-PDF og returnerer et `ParseResult` med både parsede og
    eventuelt uparsede kandidat-linjer. Kaster `FileNotFoundError` hvis
    filen mangler. Stille drop unngås ved at kandidat-rader som ikke
    matcher ender i `result.unparsed` — det er opp til kalleren å
    håndtere dette (typisk ved å heve `ParseIncompleteError`).
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(str(p))

    all_text_parts: List[str] = []
    with pdfplumber.open(str(p)) as pdf:
        for page in pdf.pages:
            all_text_parts.append(page.extract_text() or "")

    full_text = "\n".join(all_text_parts)
    leverandor = (leverandor_hint or detect_vendor(full_text)).lower()

    relevant = _extract_relevant_text(full_text)

    parsed: List[OrderLine] = []
    unparsed: List[str] = []
    seen: set = set()

    candidate_lines = [ln.strip() for ln in relevant.splitlines() if _CANDIDATE_RX.search(ln)]

    for ln in candidate_lines:
        m = _ROW_LINE_RX.match(ln)
        if m is None:
            unparsed.append(ln)
            continue
        part = m.group("part").strip()
        qty = _normalize_qty(m.group("qty"))
        if qty is None:
            unparsed.append(ln)
            continue
        key = (leverandor, part, qty)
        if key in seen:
            continue
        seen.add(key)
        parsed.append(OrderLine(leverandor=leverandor, varenr=part, antall=qty))

    # Fallback kun når det ikke fantes noen kandidat-rader (PDF-format uten
    # enhet-kolonne). Da har vi ikke noe godt signal for silent-drop-deteksjon,
    # så `unparsed` forblir tom — det er den beste innsatsen for dette formatet.
    if not candidate_lines:
        for m in _FALLBACK_RX.finditer(relevant):
            part = m.group("part").strip()
            qty = _normalize_qty(m.group("qty"))
            if qty is None:
                continue
            key = (leverandor, part, qty)
            if key in seen:
                continue
            seen.add(key)
            parsed.append(OrderLine(leverandor=leverandor, varenr=part, antall=qty))

    return ParseResult(lines=parsed, unparsed=unparsed, vendor=leverandor)


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m ordrebot.pdf_parser <path-to-pdf>")
        raise SystemExit(2)
    pdf_path = sys.argv[1]
    result = parse_order_pdf(pdf_path)
    print(json.dumps({
        "vendor": result.vendor,
        "lines": result.as_dicts(),
        "unparsed": result.unparsed,
        "is_complete": result.is_complete,
    }, ensure_ascii=False, indent=2))
