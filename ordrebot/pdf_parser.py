import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Optional

import pdfplumber


@dataclass(frozen=True)
class OrderLine:
    leverandor: str
    varenr: str
    antall: int


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


def parse_order_pdf(path: str | Path, *, leverandor_hint: Optional[str] = None) -> List[Dict[str, object]]:
    """
    Leser en ordre-PDF og returnerer en liste med dict:
    {leverandor, varenr, antall}
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

    # - part: enten alfanumerisk som starter med bokstav (B0427), eller lange digit-strenger (00050000068)
    part_pattern = r"(?:[A-Z][A-Z0-9\\-]{2,20}|\d{5,20})"

    # Primær: tabellrad-heuristikk (som i ordre.pdf):
    # <part> <beskrivelse ...> <qty med desimal> <enhet> ...
    # Eksempel: "B0427 WINCH ... 1,00 Stk 2 975,00 ..."
    row_rx = re.compile(
        rf"^(?P<part>{part_pattern})\s+.*?\s+(?P<qty>\d+[\.,]\d+)\s+(?P<unit>[A-Za-zÆØÅæøå]{{2,10}})\b",
        re.MULTILINE,
    )

    # Fallback: part + qty rett ved siden av hverandre (kan forekomme i andre PDF-er)
    qty_pattern = r"(?:\d+(?:[\.,]\d+)?)"
    combined = re.compile(rf"(?P<part>{part_pattern})\s+(?P<qty>{qty_pattern})", re.MULTILINE)

    lines: List[OrderLine] = []
    seen = set()
    matched_any = False
    for m in row_rx.finditer(relevant):
        matched_any = True
        part = m.group("part").strip()
        qty = _normalize_qty(m.group("qty"))
        if qty is None:
            continue
        key = (leverandor, part, qty)
        if key in seen:
            continue
        seen.add(key)
        lines.append(OrderLine(leverandor=leverandor, varenr=part, antall=qty))

    if not matched_any:
        for m in combined.finditer(relevant):
            part = m.group("part").strip()
            qty = _normalize_qty(m.group("qty"))
            if qty is None:
                continue
            key = (leverandor, part, qty)
            if key in seen:
                continue
            seen.add(key)
            lines.append(OrderLine(leverandor=leverandor, varenr=part, antall=qty))

    return [{"leverandor": l.leverandor, "varenr": l.varenr, "antall": l.antall} for l in lines]


def parse_order_pdf_to_orderlines(path: str | Path, *, leverandor_hint: Optional[str] = None) -> List[OrderLine]:
    return [OrderLine(**d) for d in parse_order_pdf(path, leverandor_hint=leverandor_hint)]


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m ordrebot.pdf_parser <path-to-pdf>")
        raise SystemExit(2)
    pdf_path = sys.argv[1]
    print(json.dumps(parse_order_pdf(pdf_path), ensure_ascii=False, indent=2))

