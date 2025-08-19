
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Extract every table from a PDF (using pdfplumber.extract_tables) and handle them:
- Iterates all pages & tables
- Cleans cells (whitespace, non-breaking spaces)
- Picks a header row (first non-empty row)
- Normalizes header names to canonical fields (where possible)
- Converts numeric-looking cells to floats
- Classifies table type heuristically: items / vat_summary / payments / unknown
- Outputs structured JSON to stdout or file

Usage:
    python extract_tables.py <file.pdf> [--out out.json]
"""

import argparse
import json
import re
from typing import Any, Dict, List, Optional, Tuple

NBSP = '\xa0'
NARROW_NBSP = '\u202f'
THINSP = '\u2009'

AMOUNT_RE = r"\d{1,3}(?:[ \u00A0\u202F\u2009]\d{3})*(?:[.,]\d{2})"
NUMBER_RE = r"^-?\d+(?:[.,]\d+)?$"

HEADER_MAP = {
    # Polish
    'lp': 'lp',
    'poz': 'lp',
    'nazwa': 'description',
    'opis': 'description',
    'towar': 'description',
    'produkt': 'description',
    'ilość': 'qty',
    'ilosc': 'qty',
    'jm': 'unit',
    'jednostka': 'unit',
    'cena netto': 'unit_net_price',
    'netto cena': 'unit_net_price',
    'wartość netto': 'net_value',
    'netto wartość': 'net_value',
    'stawka vat': 'vat_rate',
    'vat %': 'vat_rate',
    'kwota vat': 'vat_value',
    'brutto': 'gross_value',
    # English fallbacks
    'description': 'description',
    'qty': 'qty',
    'unit': 'unit',
    'unit price net': 'unit_net_price',
    'net value': 'net_value',
    'vat rate': 'vat_rate',
    'vat amount': 'vat_value',
    'gross': 'gross_value',
}

def clean_text(s: Optional[str]) -> str:
    if s is None:
        return ''
    s = str(s)
    for ch in (NBSP, NARROW_NBSP, THINSP):
        s = s.replace(ch, ' ')
    s = re.sub(r"\s+", ' ', s).strip()
    return s

def to_number(s: str) -> Optional[float]:
    if not s:
        return None
    ss = s.replace(' ', '').replace('\u00A0', '').replace('\u202F', '').replace('\u2009', '')
    ss = ss.replace(',', '.')
    try:
        return float(ss)
    except ValueError:
        return None

def normalize_header(cell: str) -> str:
    k = clean_text(cell).lower()
    k = re.sub(r"[^a-ząćęłńóśźż %]", ' ', k)  # keep letters and %
    k = re.sub(r"\s+", ' ', k).strip()
    return HEADER_MAP.get(k, k)

def classify_table(headers: List[str], rows: List[List[str]]) -> str:
    hset = {h.lower() for h in headers}
    join_text = ' '.join([' '.join(r) for r in rows]).lower()

    items_score = sum(int(key in hset or key in join_text) for key in [
        'lp', 'description', 'qty', 'unit', 'net_value', 'vat_rate', 'vat_value', 'gross_value', 'cena', 'nazwa', 'ilość'
    ])

    vat_summary_score = sum(int(kw in join_text) for kw in [
        'vat', 'stawka', 'podatek', 'netto', 'brutto', 'suma', 'razem'
    ])

    payments_score = sum(int(kw in join_text) for kw in [
        'płatność', 'sposób płatności', 'termin', 'zapłaty', 'paid', 'method', 'due'
    ])

    if items_score >= 3 and len(headers) >= 3:
        return 'items'
    if vat_summary_score >= 3 and len(headers) <= 6:
        return 'vat_summary'
    if payments_score >= 2:
        return 'payments'
    return 'unknown'

def try_extract_tables(page) -> List[List[List[Optional[str]]]]:
    """Try multiple strategies to improve recall."""
    strategies = [
        dict(vertical_strategy="lines", horizontal_strategy="lines"),
        dict(vertical_strategy="text", horizontal_strategy="text"),
        dict(vertical_strategy="lines", horizontal_strategy="text"),
        dict(vertical_strategy="text", horizontal_strategy="lines"),
    ]
    seen = []
    out = []
    for ts in strategies:
        try:
            tables = page.extract_tables(table_settings=ts) or []
        except Exception:
            tables = []
        for t in tables:
            # Deduplicate by size signature
            sig = (len(t), len(t[0]) if t else 0)
            if sig in seen:
                continue
            seen.append(sig)
            out.append(t)
    return out

def handle_table(raw_table: List[List[Optional[str]]]) -> Dict[str, Any]:
    table = [[clean_text(c) for c in (row or [])] for row in (raw_table or [])]
    table = [row for row in table if any(cell for cell in row)]  # drop empty rows
    if not table:
        return {"headers": [], "rows": [], "type": "empty"}

    # Choose header as first non-empty row
    header = [normalize_header(c) for c in table[0]]
    data_rows = table[1:]

    # Normalize row lengths to header length
    width = len(header)
    norm_rows: List[List[Any]] = []
    for r in data_rows:
        rr = r + [''] * max(0, width - len(r))
        rr = rr[:width]
        # Try numeric conversion for values that look like numbers/amounts
        converted: List[Any] = []
        for cell in rr:
            if re.match(NUMBER_RE, cell) or re.match(AMOUNT_RE, cell):
                n = to_number(cell)
                converted.append(n if n is not None else cell)
            else:
                converted.append(cell)
        norm_rows.append(converted)

    table_type = classify_table(header, [[str(c) for c in row] for row in norm_rows])

    # Build list of dict rows
    dict_rows = []
    for r in norm_rows:
        row_dict = {header[i] if i < len(header) else f'col_{i}': r[i] for i in range(len(header))}
        dict_rows.append(row_dict)

    return {
        "headers": header,
        "rows": dict_rows,
        "type": table_type,
    }

def process_pdf(path: str) -> Dict[str, Any]:
    import pdfplumber
    out: Dict[str, Any] = {"file": path, "pages": []}
    with pdfplumber.open(path) as pdf:
        for pi, page in enumerate(pdf.pages, start=1):
            page_record = {"page": pi, "tables": []}
            for ti, table in enumerate(try_extract_tables(page), start=1):
                handled = handle_table(table)
                handled["index"] = ti
                page_record["tables"].append(handled)
            out["pages"].append(page_record)
    return out

def main():
    ap = argparse.ArgumentParser(description="Extract and handle all tables with pdfplumber.extract_tables")
    ap.add_argument("pdf", help="Path to PDF file")
    ap.add_argument("--out", help="Write JSON to this path", default=None)
    args = ap.parse_args()
    result = process_pdf(args.pdf)
    js = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as f:
            f.write(js)
        print(f"Wrote {args.out}")
    else:
        print(js)

if __name__ == "__main__":
    main()
