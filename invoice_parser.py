#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Invoice PDF parser (Polish invoices friendly).
- Extracts text and tables from PDF invoices.
- Robust to out-of-order tokens in raw text (e.g., "Łącznie PLN ... Odebrał:" mixed).
- Works on multi-page / large invoices.
- Outputs structured JSON (header, parties, totals, items).

Usage:
    python invoice_parser.py <path_to_pdf> [--out output.json]

Dependencies:
    See requirements.txt
"""
import argparse
import json
import re
from dataclasses import dataclass, asdict, field
from typing import List, Optional, Dict, Any

# Prefer pdfplumber (layout-aware). Fallback to PyPDF2.
try:
    import pdfplumber  # type: ignore
except Exception:
    pdfplumber = None

try:
    from PyPDF2 import PdfReader  # type: ignore
except Exception:
    PdfReader = None


@dataclass
class Party:
    name: Optional[str] = None
    address: Optional[str] = None
    tax_id: Optional[str] = None  # NIP / NIF / VAT ID
    note: Optional[str] = None


@dataclass
class Item:
    description: Optional[str] = None
    qty: Optional[float] = None
    unit: Optional[str] = None
    net_price: Optional[float] = None
    net_value: Optional[float] = None
    vat_rate: Optional[str] = None
    vat_value: Optional[float] = None
    gross_value: Optional[float] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Invoice:
    number: Optional[str] = None
    issue_date: Optional[str] = None  # ISO or dd/mm/yyyy
    sale_date: Optional[str] = None
    payment_due: Optional[str] = None
    payment_method: Optional[str] = None
    currency: Optional[str] = "PLN"
    total_net: Optional[float] = None
    total_vat: Optional[float] = None
    total_gross: Optional[float] = None
    buyer: Party = field(default_factory=Party)
    seller: Party = field(default_factory=Party)
    receiver: Optional[str] = None  # "Odebrał:"
    receiver_tax_id: Optional[str] = None
    receiver_datetime: Optional[str] = None  # "dd/mm/yyyy hh:mm"
    items: List[Item] = field(default_factory=list)
    raw_text: Optional[str] = None


# ---------- Utilities ----------

NBSP = u'\xa0'
THINSP = u'\u2009'
NARROW_NBSP = u'\u202f'

AMOUNT_RE = r'(?P<amount>\d{1,3}(?:[ \u00A0\u202F\u2009]\d{3})*(?:[.,]\d{2}))'
DATE_RE = r'(?P<date>\d{2}[./-]\d{2}[./-]\d{4})'
TIME_RE = r'(?P<time>\d{2}:\d{2})'
TOTAL_RE = r'(?:Łącznie|Razem|Suma)\s*(?:PLN|zł|PLN)?'
CURRENCY_RE = r'(PLN|zł)'
NIP_RE = r'(?:NIP|N\.?\s?NIF|NIF|VAT\s?ID)[^\w]?(?P<nip>[A-Z]{2}?\d[\d\- ]+|\d[\d\- ]+)'  # tolerant
RECEIVER_RE = r'Odebrał:\s*(?P<recv>[A-Za-zÀ-ÿĄąĆćĘęŁłŃńÓóŚśŹźŻż.\- ]{1,80})'
INVOICE_NO_RE = r'(?:Faktura(?:\s*VAT)?|Invoice)[^0-9A-Za-z]{0,5}(?P<num>[A-Za-z0-9\-\/]+)'
PAYMENT_METHOD_RE = r'(?:Sposób\s*płatności|Forma\s*płatności)\s*[:\-]?\s*(?P<pm>[A-Za-z ]+)'

def _to_float(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    s = s.replace(NBSP, ' ').replace(NARROW_NBSP, ' ').replace(THINSP, ' ')
    s = s.replace(' ', '')
    s = s.replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return None

def _cleanup_text(text: str) -> str:
    text = text.replace('\r', '\n')
    # Normalize weird spaces
    for ch in [NBSP, THINSP, NARROW_NBSP]:
        text = text.replace(ch, ' ')
    # Collapse duplicate spaces
    text = re.sub(r'[ \t]{2,}', ' ', text)
    # Ensure lines are not absurdly broken: keep original line breaks but also create a "flat" version for regex scanning
    return text

def extract_text_from_pdf(path: str) -> str:
    # Try pdfplumber for better layout
    if pdfplumber is not None:
        try:
            text_parts = []
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages:
                    # Extract text with layout; if tables exist we still want text for regex scanning
                    page_text = page.extract_text(x_tolerance=1.5, y_tolerance=2.0) or ''
                    text_parts.append(page_text)
            full = '\n'.join(text_parts)
            if full.strip():
                return full
        except Exception:
            pass

    # Fallback: PyPDF2
    if PdfReader is None:
        raise RuntimeError("Neither pdfplumber nor PyPDF2 is available.")
    reader = PdfReader(path)
    text_parts = []
    for p in reader.pages:
        try:
            text_parts.append(p.extract_text() or '')
        except Exception:
            text_parts.append('')
    return '\n'.join(text_parts)


def fix_out_of_order_segments(text: str) -> str:
    """
    Repairs lines where tokens like 'Łącznie PLN', 'Odebrał:', date, time, and amount
    are scrambled into an odd order by the extractor.

    Strategy: For each line, if it contains BOTH 'Odebrał:' and any of TOTAL_RE,
    we re-extract atomic fields with regex (order-agnostic) and then rebuild
    the canonical human order:
        'Odebrał: <name> <NIP/NIF?> <date> <time> Łącznie PLN <amount>'
    Missing pieces are skipped gracefully.
    """
    fixed_lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if 'Odebrał' in line and re.search(TOTAL_RE, line, flags=re.IGNORECASE):
            name = None
            nip = None
            date = None
            time = None
            amount = None

            m = re.search(RECEIVER_RE, line)
            if m:
                name = m.group('recv').strip()

            m = re.search(NIP_RE, line, flags=re.IGNORECASE)
            if m:
                nip = m.group('nip').strip()

            m = re.search(DATE_RE, line)
            if m:
                date = m.group('date')

            m = re.search(TIME_RE, line)
            if m:
                time = m.group('time')

            m = re.search(AMOUNT_RE, line)
            if m:
                amount = m.group('amount')

            # Recompose canonical order
            pieces = []
            if name:
                pieces.append(f'Odebrał: {name}')
            if nip:
                pieces.append(f'NIP {nip}')
            dt = ' '.join([x for x in [date, time] if x])
            if dt:
                pieces.append(dt)
            if amount:
                pieces.append(f'Łącznie PLN {amount}')
            rebuilt = ' '.join(pieces).strip()
            if rebuilt:
                fixed_lines.append(rebuilt)
                continue
        fixed_lines.append(raw_line)
    return '\n'.join(fixed_lines)


def parse_header_fields(text: str) -> Dict[str, Optional[str]]:
    header: Dict[str, Optional[str]] = {
        'number': None,
        'issue_date': None,
        'sale_date': None,
        'payment_due': None,
        'payment_method': None,
    }
    m = re.search(INVOICE_NO_RE, text, flags=re.IGNORECASE)
    if m:
        header['number'] = m.group('num').strip()

    # Issue date & sale date & due date (common labels on PL invoices)
    # Be liberal with labels and separators:
    for label, key in [
        (r'Data\s*wystawienia', 'issue_date'),
        (r'Data\s*sprzedaży', 'sale_date'),
        (r'Termin\s*płatności', 'payment_due'),
    ]:
        rm = re.search(label + r'\s*[:\-]?\s*' + DATE_RE, text, flags=re.IGNORECASE)
        if rm:
            header[key] = rm.group('date')

    # Payment method
    m = re.search(PAYMENT_METHOD_RE, text, flags=re.IGNORECASE)
    if m:
        header['payment_method'] = m.group('pm').strip()

    return header


def parse_parties(text: str) -> Dict[str, Party]:
    # Try to identify Seller/Buyer blocks. These vary a lot; we'll use nearby NIP/NIF and headings.
    seller = Party()
    buyer = Party()

    # Blocks by headings
    blocks = {}
    for heading in ['Sprzedawca', 'Wystawca', 'Dostawca', 'Nadawca', 'Buyer', 'Nabywca', 'Odbiorca']:
        pattern = heading + r'.{0,200}?(?=(Sprzedawca|Wystawca|Dostawca|Nadawca|Buyer|Nabywca|Odbiorca|$))'
        m = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if m:
            blocks[heading.lower()] = m.group(0)

    def party_from_block(block_text: str) -> Party:
        p = Party()
        # Name: first non-empty line after heading
        lines = [ln.strip() for ln in re.split(r'\n+', block_text) if ln.strip()]
        if lines:
            # remove the heading line itself
            lines = lines[1:] if re.search(r'^[A-Za-zĄąĆćĘęŁłŃńÓóŚśŹźŻż ]+:?$', lines[0]) else lines
        if lines:
            p.name = lines[0]
        # Address: next 1-2 lines that look like address (digits + street keywords)
        addr_lines = []
        for ln in lines[1:4]:
            if re.search(r'\d', ln) or re.search(r'ul\.|ulica|al\.|aleja|pl\.|plac|str\.', ln, flags=re.IGNORECASE):
                addr_lines.append(ln)
        if addr_lines:
            p.address = ', '.join(addr_lines)
        # Tax ID
        m = re.search(NIP_RE, block_text, flags=re.IGNORECASE)
        if m:
            p.tax_id = m.group('nip').strip()
        return p

    # Map to seller/buyer
    if 'sprzedawca' in blocks or 'wystawca' in blocks or 'dostawca' in blocks:
        blk = blocks.get('sprzedawca') or blocks.get('wystawca') or blocks.get('dostawca')
        seller = party_from_block(blk)
    if 'nabywca' in blocks or 'buyer' in blocks or 'odbiorca' in blocks:
        blk = blocks.get('nabywca') or blocks.get('buyer') or blocks.get('odbiorca')
        buyer = party_from_block(blk)

    # Fallback: if one of them missing, try first/second NIP occurrences
    if not seller.tax_id or not buyer.tax_id:
        nips = [m.group('nip').strip() for m in re.finditer(NIP_RE, text, flags=re.IGNORECASE)]
        if nips:
            if not seller.tax_id:
                seller.tax_id = nips[0]
            if len(nips) > 1 and not buyer.tax_id:
                buyer.tax_id = nips[1]

    return {'seller': seller, 'buyer': buyer}


def parse_totals(text: str) -> Dict[str, Optional[float]]:
    totals = {'total_net': None, 'total_vat': None, 'total_gross': None, 'currency': 'PLN'}
    # Gross total commonly labeled by Łącznie/Razem/Suma
    gross_patterns = [
        TOTAL_RE + r'.{0,20}?' + AMOUNT_RE,
        r'(?:Do\s*zapłaty|Razem\s*do\s*zapłaty).{0,20}?' + AMOUNT_RE,
    ]
    for pat in gross_patterns:
        m = re.search(pat, text, flags=re.IGNORECASE | re.DOTALL)
        if m:
            totals['total_gross'] = _to_float(m.group('amount'))
            break

    # Net and VAT (look for a little table summary lines)
    net_m = re.search(r'(?:Netto|Wartość\s*netto).{0,16}?' + AMOUNT_RE, text, flags=re.IGNORECASE)
    vat_m = re.search(r'(?:VAT|Podatek\s*VAT).{0,16}?' + AMOUNT_RE, text, flags=re.IGNORECASE)
    if net_m:
        totals['total_net'] = _to_float(net_m.group('amount'))
    if vat_m:
        totals['total_vat'] = _to_float(vat_m.group('amount'))

    # Currency if explicitly shown
    cur_m = re.search(CURRENCY_RE, text, flags=re.IGNORECASE)
    if cur_m:
        totals['currency'] = cur_m.group(1).upper()

    return totals


def parse_receiver_line(text: str) -> Dict[str, Optional[str]]:
    # Find a line with "Odebrał:" possibly near date/time and totals
    recv = None
    recv_tax = None
    recv_dt = None
    # Search line-wise to prefer close tokens
    for line in text.splitlines():
        if 'Odebrał' in line:
            name_m = re.search(RECEIVER_RE, line)
            if name_m:
                recv = name_m.group('recv').strip()
            nip_m = re.search(NIP_RE, line, flags=re.IGNORECASE)
            if nip_m:
                recv_tax = nip_m.group('nip').strip()
            date_m = re.search(DATE_RE, line)
            time_m = re.search(TIME_RE, line)
            dt_parts = []
            if date_m:
                dt_parts.append(date_m.group('date'))
            if time_m:
                dt_parts.append(time_m.group('time'))
            if dt_parts:
                recv_dt = ' '.join(dt_parts)
            # We only expect one such line
            break
    return {'receiver': recv, 'receiver_tax_id': recv_tax, 'receiver_datetime': recv_dt}


def _coerce_number(s: str) -> Optional[float]:
    try:
        return _to_float(s)
    except Exception:
        return None


def extract_items_with_pdfplumber(path: str) -> List[Item]:
    items: List[Item] = []
    if pdfplumber is None:
        return items

    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for tbl in tables or []:
                    # Heuristic: keep tables that have at least 3 columns and a header row that hints invoice items
                    if len(tbl) < 2 or len(tbl[0]) < 3:
                        continue
                    header_row = [ (c or '').strip().lower() for c in tbl[0] ]
                    # Signals: headers like 'lp', 'nazwa', 'ilość', 'jm', 'netto', 'vat', 'brutto'
                    header_score = sum(int(bool(re.search(r'(lp|poz|nazwa|opis|ilość|jm|netto|vat|brutto|cena)', h))) for h in header_row)
                    if header_score < 2:
                        continue
                    # Parse rows (skip header)
                    for row in tbl[1:]:
                        cells = [ (c or '').strip() for c in row ]
                        if not any(cells):
                            continue
                        # Map commonly seen columns by fuzzy match
                        desc = None
                        qty = None
                        unit = None
                        net_price = None
                        net_value = None
                        vat_rate = None
                        vat_value = None
                        gross_value = None

                        for idx, cell in enumerate(cells):
                            h = header_row[idx] if idx < len(header_row) else ''
                            if re.search(r'(nazwa|opis|produkt|towar)', h):
                                desc = cell or desc
                            elif re.search(r'(ilość|ilosc|qty)', h):
                                qty = _coerce_number(cell) or qty
                            elif re.search(r'(^jm$|jednostka|unit)', h):
                                unit = cell or unit
                            elif re.search(r'(cena.*netto|netto.*cena|price.*net)', h):
                                net_price = _coerce_number(cell) or net_price
                            elif re.search(r'(wartość.*netto|netto.*wartość|net.*value)', h):
                                net_value = _coerce_number(cell) or net_value
                            elif re.search(r'(stawka.*vat|vat.*%)', h):
                                vat_rate = cell or vat_rate
                            elif re.search(r'(kwota.*vat|vat.*kwota)', h):
                                vat_value = _coerce_number(cell) or vat_value
                            elif re.search(r'(brutto|gross)', h):
                                gross_value = _coerce_number(cell) or gross_value
                            else:
                                # Try to infer by content if headers are weak
                                if desc is None and not re.match(AMOUNT_RE, cell):
                                    desc = cell
                                elif qty is None and re.match(r'^\d+[.,]?\d*$', cell):
                                    qty = _coerce_number(cell)
                                elif any(k in h for k in ['lp', 'poz']):
                                    pass
                        items.append(Item(description=desc, qty=qty, unit=unit,
                                         net_price=net_price, net_value=net_value,
                                         vat_rate=vat_rate, vat_value=vat_value,
                                         gross_value=gross_value))
    except Exception:
        # Silent fallback; item extraction is best-effort
        return items
    return items


def extract_items_from_text(text: str) -> List[Item]:
    """
    Best-effort fallback if tables couldn't be read.
    Looks for lines that contain description + numbers typical for item rows.
    """
    items: List[Item] = []
    for line in text.splitlines():
        ln = line.strip()
        # Must contain at least two amounts or qty + amount to resemble an item row
        amounts = re.findall(AMOUNT_RE, ln)
        qty = re.search(r'\b\d+[.,]?\d*\b', ln)
        looks_like_desc = re.search(r'[A-Za-zĄąĆćĘęŁłŃńÓóŚśŹźŻż]', ln)
        if looks_like_desc and (len(amounts) >= 2 or (qty and amounts)):
            # crude split: description then trailing numbers
            parts = re.split(r'\s{2,}', ln)  # split by double spaces if present
            desc = parts[0] if parts else ln
            qty_val = _coerce_number(qty.group(0)) if qty else None
            # try to get the last amount as gross/net value
            net_val = _to_float(amounts[-1])
            items.append(Item(description=desc, qty=qty_val, net_value=net_val))
    return items


def parse_invoice(pdf_path: str) -> Invoice:
    raw_text = extract_text_from_pdf(pdf_path)
    cleaned = _cleanup_text(raw_text)
    repaired = fix_out_of_order_segments(cleaned)

    header = parse_header_fields(repaired)
    parties = parse_parties(repaired)
    totals = parse_totals(repaired)
    receiver = parse_receiver_line(repaired)

    inv = Invoice(
        number=header.get('number'),
        issue_date=header.get('issue_date'),
        sale_date=header.get('sale_date'),
        payment_due=header.get('payment_due'),
        payment_method=header.get('payment_method'),
        currency=totals.get('currency') or 'PLN',
        total_net=totals.get('total_net'),
        total_vat=totals.get('total_vat'),
        total_gross=totals.get('total_gross'),
        buyer=parties['buyer'],
        seller=parties['seller'],
        receiver=receiver.get('receiver'),
        receiver_tax_id=receiver.get('receiver_tax_id'),
        receiver_datetime=receiver.get('receiver_datetime'),
        raw_text=repaired
    )

    # Items
    items = extract_items_with_pdfplumber(pdf_path)
    if not items:
        items = extract_items_from_text(repaired)
    inv.items = items

    return inv


def main():
    parser = argparse.ArgumentParser(description="Parse a PDF invoice into structured JSON.")
    parser.add_argument("pdf", help="Path to invoice PDF")
    parser.add_argument("--out", help="Path to write JSON output", default=None)
    args = parser.parse_args()

    invoice = parse_invoice(args.pdf)
    payload = asdict(invoice)

    # Convert dataclasses inside items/parties to dicts
    payload['buyer'] = asdict(invoice.buyer)
    payload['seller'] = asdict(invoice.seller)
    payload['items'] = [asdict(it) for it in invoice.items]

    js = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as f:
            f.write(js)
        print(f"Wrote: {args.out}")
    else:
        print(js)


if __name__ == "__main__":
    main()
