
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Parser PDF: obsługa *wszystkich* tabel z pdfplumber.extract_tables().
- Dla tabel w układzie podobnym do przykładu (AWB/Nadawca/Odbiorca/Koszty/Odebrał) stosuje parser domenowy (FedEx-like).
- Dla pozostałych tabel: uogólnione czyszczenie, normalizacja nagłówków, konwersja liczb, prosta klasyfikacja.
- Wynik zapisywany jako JSON (po polsku).

Użycie:
    python parse_all_tables.py plik.pdf --out wynik.json
"""

import argparse
import json
import re
from typing import Any, Dict, List, Optional
# === [NOWE: Heurystyki bazujące na '\n'] =====================================
def _has_newline_before(sub: str, text: str) -> bool:
    """
    True jeśli tuż przed 'sub' (np. 'kg' albo '(') w surowym tekście występuje znak nowej linii.
    Pozwalamy na ewentualne spacje po \n.
    """
    if not text or not sub:
        return False
    return re.search(r"\n\s*" + re.escape(sub), text, flags=re.I) is not None

def _lines_before_suma(text: str) -> List[str]:
    """
    Zwraca listę linii do momentu 'Suma netto'/'Suma' (nagłówki / stopki odcinamy).
    """
    lines = [ln.strip() for ln in (text or '').splitlines()]
    out = []
    for ln in lines:
        if re.search(r"^\s*suma(\s+netto)?", ln, flags=re.I):
            break
        out.append(ln)
    # usuń puste na końcach
    while out and not out[-1]:
        out.pop()
    return out
# =============================================================================


# --- Utils ---
NBSP = '\xa0'
NARROW_NBSP = '\u202f'
THINSP = '\u2009'

AMOUNT_RE = r"\d{1,3}(?:[ \u00A0\u202F\u2009]\d{3})*(?:[.,]\d{2})"
NUMBER_RE = r"^-?\d+(?:[.,]\d+)?$"

def clean(s: Optional[str]) -> str:
    if s is None:
        return ''
    s = str(s).replace(NBSP, ' ').replace(NARROW_NBSP, ' ').replace(THINSP, ' ').replace('\xad', '')
    return re.sub(r"\s+", ' ', s).strip()

def to_float(txt: Optional[str]) -> Optional[float]:
    if not txt:
        return None
    t = str(txt).replace(' ', '').replace(NBSP, '').replace(NARROW_NBSP, '').replace(THINSP, '')

    # 1. Jeśli mamy przecinek, traktujemy go jako separator dziesiętny
    if ',' in t:
        t = t.replace('.', '')   # usuń kropki jako separatory tysięcy
        t = t.replace(',', '.')  # zamień przecinek na kropkę dziesiętną
    else:
        # 2. Brak przecinka
        if t.count('.') > 1:
            # wiele kropek → to separatory tysięcy
            t = t.replace('.', '')
        elif '.' in t:
            # jedna kropka – heurystyka:
            parts = t.split('.')
            if len(parts[-1]) == 3:  
                # np. 12.345 → separator tysięcy
                t = t.replace('.', '')
            else:
                # np. 1234.56 → traktuj jako separator dziesiętny
                pass
    try:
        return float(t)
    except ValueError:
        return None


# --- Ekstrakcja: pojedyncza strategia (konserwatywna) ---
def extract_tables_single_strategy(page):
    ts = dict(
        vertical_strategy="lines",
        horizontal_strategy="lines",
        intersection_tolerance=3,
        snap_tolerance=3,
        join_tolerance=0.5,
        edge_min_length=10,
        min_words_vertical=1,
        text_x_tolerance=1,
        text_y_tolerance=2,
    )
    try:
        return page.extract_tables(table_settings=ts) or []
    except Exception:
        return []
# --- New robust extractors for waga & numer referencyjny ---
def _strip_spaces_inside(s: str) -> str:
    return re.sub(r"[ \u00A0\u202F\u2009]+", "", s)

def extract_weight_kg(text: str) -> Optional[float]:
    t = text or ""
    # common: "0,50 kg", "0,50kg", also tolerate line breaks already collapsed by clean()
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*kg\b", t, flags=re.I)
    if m:
        return to_float(m.group(1))
    # fallback: after a keyword 'Waga' capture a number
    m2 = re.search(r"waga\s*(?:zafakturowana)?\s*(\d+(?:[.,]\d+)?)", t, flags=re.I)
    if m2:
        return to_float(m2.group(1))
    return None

def extract_long_reference(text: str) -> Optional[str]:
    t = text or ""
    cands = []
    # 1) Inside parentheses, allow spaces inside e.g. "(228959 992)"
    for grp in re.findall(r"\(\s*([A-Za-z0-9\- \u00A0\u202F\u2009]{6,})\s*\)", t):
        cleaned = _strip_spaces_inside(grp)
        if len(cleaned) >= 8:
            cands.append(cleaned)
    # 2) If nothing, consider long alphanum tokens (>=10) but avoid AWB by not scanning AWB cell
    for tok in re.findall(r"\b([A-Za-z0-9\-]{10,})\b", t):
        cands.append(tok)
    if not cands:
        return None
    # pick the longest; if tie, prefer the last occurrence
    cands_sorted = sorted(set(cands), key=lambda s: (len(s), t.rfind(s)))
    return cands_sorted[-1]

# --- Heurystyka: wykrywanie tabeli FedEx-like ---
def detect_fedex_like_table(raw: List[List[Optional[str]]]) -> bool:
    if not raw or not raw[0]:
        return False
    header = [clean(c).lower() for c in raw[0]]
    header_text = ' '.join(header)
    body_text = ' '.join(clean(c) for row in raw for c in (row or []) if c)

    signals = 0
    for kw in ['awb', 'usługa', 'sztuki', 'waga', 'bez vat', 'łącznie']:
        if kw in header_text:
            signals += 1
    for kw in ['nadawca', 'odbiorca', 'odebrał', 'łącznie pln', 'wymiary', 'waga zafakturowana']:
        if kw in body_text.lower():
            signals += 1
    return signals >= 4

# --- Parser FedEx-like ---
def parse_sender_block(text: str) -> Dict[str, Any]:
    lines = [l for l in re.split(r"\s*\n\s*", text or '') if l]
    out: Dict[str, Any] = {"pełny_tekst": clean(text)}
    if lines and re.search(r"nadawca", lines[0], re.I):
        lines = lines[1:]
    if lines:
        out["osoba"] = clean(lines[0])
    if len(lines) >= 2:
        out["firma"] = clean(lines[1])
    if len(lines) >= 3:
        out["ulica"] = clean(lines[2])
    if len(lines) >= 4:
        out["miasto_linia"] = clean(lines[3])
    if len(lines) >= 5:
        out["kraj"] = clean(lines[4])
    return out

def parse_receiver_block(text: str) -> Dict[str, Any]:
    lines = [l for l in re.split(r"\s*\n\s*", text or '') if l]
    out: Dict[str, Any] = {"pełny_tekst": clean(text)}
    if lines and re.search(r"odbiorca", lines[0], re.I):
        lines = lines[1:]
    if lines:
        out["osoba"] = clean(lines[0])
    if len(lines) >= 2:
        out["firma"] = clean(lines[1])
    if len(lines) >= 3:
        out["ulica"] = clean(lines[2])
    if len(lines) >= 4:
        out["miasto_linia"] = clean(lines[3])
    if len(lines) >= 5:
        out["kod_linia"] = clean(lines[4])
    if len(lines) >= 6:
        out["kraj"] = clean(lines[5])
    return out

def parse_costs_block(text: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {"pozycje": [], "suma_obliczona": None}
    total = 0.0
    for rawln in re.split(r"\s*\n\s*", text or ''):
        ln = clean(rawln)
        if not ln:
            continue
        m = re.search(r"(.+?)\s(-?\d+[.,]\d{2})", ln)
        if m:
            label = clean(m.group(1))
            val = to_float(m.group(2))
            out["pozycje"].append({"nazwa": label, "kwota": val})
            if val is not None:
                total += val
    out["suma_obliczona"] = round(total, 2) if out["pozycje"] else None
    return out

def extract_first_int(text: str) -> Optional[int]:
    m = re.search(r"\b(\d+)\b", text or '')
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    return None

def parse_shipment_row(awb_cell: str, service_cell: str, mixed_cell: str) -> Dict[str, Any]:
    awb_txt = clean(awb_cell)
    service_txt = clean(service_cell)
    mixed_txt = clean(mixed_cell)
    raw_mixed = mixed_cell or ''
    
    ### [NOWE] Flagi i kontekst linii (na bazie '\n' i nawiasów) -----------------
    # Waga w 2 liniach: gdy 'kg' jest w osobnej linii LUB przed 'kg' jest '\n'.
    lines_raw = _lines_before_suma(raw_mixed)
    kg_separate_line = any(ln.strip().lower() == 'kg' for ln in lines_raw)
    waga_w_2_linijkach = kg_separate_line or _has_newline_before('kg', raw_mixed)
    
    # Numer referencyjny w 2 liniach: gdy występuje linia typu '(.....)' osobno.
    ref_line_separate_idx = next((i for i, ln in enumerate(lines_raw) if re.match(r'^\(.*\)$', ln.strip())), None)
    numer_ref_w_2_linijkach = ref_line_separate_idx is not None
    # Czy w ogóle mamy referencję? (nawiasy lub długi token)
    has_reference = bool(re.search(r'\(.*\)', raw_mixed)) or bool(re.search(r'\b[A-Za-z0-9\-]{10,}\b', mixed_txt))
    # -----------------------------------------------------------------------------


    # AWB i data wysyłki
    awb_num = None
    m_awb = re.search(r"\b(\d{10,})\b", awb_txt)
    if m_awb:
        awb_num = m_awb.group(1)

    data_wysyłki = None
    m_d = re.search(r"(\d{2}[/-]\d{2}[/-]\d{4})", awb_txt)
    if m_d:
        data_wysyłki = m_d.group(1)

    # Usługa + waga zafakturowana
    usługa = None
    waga_zaf = None
    if service_txt:
        parts = re.split(r"\s+Waga\s+zafakturowana\s+", service_txt, flags=re.I)
        usługa = parts[0].strip()
        if len(parts) > 1:
            waga_zaf = extract_weight_kg(parts[1])

    # Sztuki
    sztuki = extract_first_int(mixed_txt)

    # Waga (1–2 linie, różne warianty zapisu KG)
    waga = extract_weight_kg(mixed_txt)

    # Numer referencyjny — wybieramy najdłuższy (ignorujemy krótsze)
    numer_ref = extract_long_reference(mixed_txt)

    # Kwoty (ostatnie trzy: podlega VAT / bez VAT / łącznie)
    kwoty = [to_float(x) for x in re.findall(r"(-?\d+[.,]\d{2})", mixed_txt)]
    podlega_vat = bez_vat = łącznie = None
    nonnull = [k for k in kwoty if k is not None]
    if len(nonnull) >= 3:
        podlega_vat, bez_vat, łącznie = nonnull[-3], nonnull[-2], nonnull[-1]


    ### [NOWE] Kolejność przypisania wg \n i nawiasów ----------------------------------
    # Ustal: linia z kwotami (ta, która zawiera >=2 kwoty pieniężne)
    amount_line_idx = next((i for i, ln in enumerate(lines_raw) if len(re.findall(r"(-?\d+[.,]\d{2})", ln)) >= 2), None)

    # Wstępnie: sztuki/kwoty liczymy z linii kwot (dokładniejsze niż globalne fallbacki)
    if amount_line_idx is not None:
        ln_amt = lines_raw[amount_line_idx]
        # Sztuki: pierwsza liczba całkowita na linii kwot
        szt_cand = extract_first_int(ln_amt)
        if szt_cand is not None:
            sztuki = szt_cand
        # Kwoty: ostatnie trzy
        kwoty_amt = [to_float(x) for x in re.findall(r"(-?\d+[.,]\d{2})", ln_amt)]
        nonnull_amt = [k for k in kwoty_amt if k is not None]
        if len(nonnull_amt) >= 3:
            podlega_vat, bez_vat, łącznie = nonnull_amt[-3], nonnull_amt[-2], nonnull_amt[-1]

    # Waga: 1-liniowa (gdy 'kg' razem z liczbą) vs 2-liniowa (gdy 'kg' osobno / poprzedzona \n)
    if waga_w_2_linijkach:
        # Szukamy wiersza z samym 'kg' i najbliższego powyżej kandydata na liczbę wagi.
        if kg_separate_line:
            kg_idx = next((i for i, ln in enumerate(lines_raw) if ln.strip().lower() == 'kg'), None)
        else:
            # brak osobnej linii 'kg', ale jest \n przed 'kg' gdzieś w środku: przyjmij, że liczba wagi stoi PRZED 'kg'
            # znajdź linię zawierającą 'kg' i użyj poprzedniej linii jako nośnik liczby wagi, jeśli istnieje
            kg_idx = next((i for i, ln in enumerate(lines_raw) if 'kg' in ln.lower()), None)
        weight_num = None
        if kg_idx is not None:
            # sprawdź poprzednie linie, od najbliższej do dalszych
            for j in range(kg_idx-1, -1, -1):
                cand = extract_weight_kg(lines_raw[j] + " kg")  # dolep 'kg', by wykorzystać istniejącą regułę
                if cand is not None:
                    weight_num = cand
                    break
        if weight_num is not None:
            waga = weight_num
        # Kolejność fragmentów: [waga(2 linie)], [ref?], [kwoty]
        kolejność_przypisania = []
        if kg_idx is not None:
            # Zakładamy, że waga to: (kg_idx-1) i kg_idx
            kolejność_przypisania.append({'pole': 'waga', 'slice': [max(0, kg_idx-1), kg_idx+1]})
        if has_reference:
            if ref_line_separate_idx is not None:
                kolejność_przypisania.append({'pole': 'numer_ref', 'slice': [ref_line_separate_idx, ref_line_separate_idx+1]})
            else:
                # referencja inline – bez osobnej rezerwacji linii
                kolejność_przypisania.append({'pole': 'numer_ref', 'slice': [amount_line_idx or 0, (amount_line_idx or 0)+1]})
        if amount_line_idx is not None:
            kolejność_przypisania.append({'pole': 'kwoty', 'slice': [amount_line_idx, None]})
    else:
        # Waga w 1 linii: poszukaj linii, która zawiera 'kg' + liczbę, preferuj amount_line (częsty przypadek)
        weight_num = None
        weight_line_idx = next((i for i, ln in enumerate(lines_raw) if re.search(r"\d+[.,]\d+\s*kg\b", ln, flags=re.I)), None)
        if weight_line_idx is None and amount_line_idx is not None and 'kg' in (lines_raw[amount_line_idx].lower() if amount_line_idx is not None else ''):
            weight_line_idx = amount_line_idx
        # jeśli dalej brak, sprawdź wszystkie linie
        if weight_line_idx is None:
            for i, ln in enumerate(lines_raw):
                cand = extract_weight_kg(ln)
                if cand is not None and 'kg' in ln.lower():
                    weight_line_idx = i
                    weight_num = cand
                    break
        if weight_num is None and weight_line_idx is not None:
            weight_num = extract_weight_kg(lines_raw[weight_line_idx])
        if weight_num is not None:
            waga = weight_num
        # Kolejność: [waga(1 linia)], [ref (0/1/2 linie)], [kwoty]
        kolejność_przypisania = []
        if weight_line_idx is not None:
            kolejność_przypisania.append({'pole': 'waga', 'slice': [weight_line_idx, weight_line_idx+1]})
        if has_reference:
            if ref_line_separate_idx is not None:
                kolejność_przypisania.append({'pole': 'numer_ref', 'slice': [ref_line_separate_idx, ref_line_separate_idx+1]})
            else:
                kolejność_przypisania.append({'pole': 'numer_ref', 'slice': [amount_line_idx or 0, (amount_line_idx or 0)+1]})
        if amount_line_idx is not None:
            kolejność_przypisania.append({'pole': 'kwoty', 'slice': [amount_line_idx, None]})

    # Jeśli nie ma referencji w ogóle, usuń wpis 'numer_ref' z kolejności
    if not has_reference and 'kolejność_przypisania' in locals():
        kolejność_przypisania = [k for k in kolejność_przypisania if k['pole'] != 'numer_ref']

    # Podgląd: jeżeli mamy zdefiniowaną kolejność, możemy też podjąć próbę doczytania
    # referencji z jej fragmentu (tylko gdy osobna linia)
    if has_reference and ref_line_separate_idx is not None:
        nr_candidate = extract_long_reference(lines_raw[ref_line_separate_idx])
        if nr_candidate:
            numer_ref = nr_candidate
    # ----------------------------------------------------------------------------------
    return {
        "awb": awb_num,
        "data_wysyłki": data_wysyłki,
        "usługa": usługa,
        "waga_zafakturowana_kg": waga_zaf,
        "sztuki": sztuki,
        "waga_kg": waga,
        "numer_referencyjny": numer_ref,
        "podlega_VAT_kwota": podlega_vat,
        "bez_VAT_kwota": bez_vat,
        "łącznie_kwota": łącznie,
        "waga_w_2_linijkach": waga_w_2_linijkach,
        "numer_ref_w_2_linijkach": numer_ref_w_2_linijkach,
        "kolejność_przypisania": locals().get("kolejność_przypisania"),
        "uwagi_awb": "Wymiary" if "Wymiary" in awb_txt else None,
        "surowy_opis": {
            "awb_cell": awb_txt,
            "service_cell": service_txt,
            "mixed_cell": mixed_txt,
            "mixed_cell_raw": raw_mixed,
            "mixed_cell_lines": lines_raw
        }
    }

# --- Heurystyka: wykrywanie tabeli FedEx-like ---
def detect_fedex_like_table(raw: List[List[Optional[str]]]) -> bool:
    if not raw or not raw[0]:
        return False
    header = [clean(c).lower() for c in raw[0]]
    header_text = ' '.join(header)
    body_text = ' '.join(clean(c) for row in raw for c in (row or []) if c)

    signals = 0
    for kw in ['awb', 'usługa', 'sztuki', 'waga', 'bez vat', 'łącznie']:
        if kw in header_text:
            signals += 1
    for kw in ['nadawca', 'odbiorca', 'odebrał', 'łącznie pln', 'wymiary', 'waga zafakturowana']:
        if kw in body_text.lower():
            signals += 1
    return signals >= 4

def parse_footer_row(cell0: str, cell1: str, cell8: str) -> Dict[str, Any]:
    odebrał = None
    c0 = clean(cell0)
    c1 = clean(cell1)
    c8 = clean(cell8)
    if c0.lower().startswith("odebrał"):
        m = re.search(r"Odebrał:\s*(.+)$", c0)
        if m:
            odebrał = clean(m.group(1)) or None
    nif = None
    data = None
    godzina = None
    m_nif = re.search(r"(?:NIP|NIF)\s*([A-Z0-9\- ]+)", c1, re.I)
    if m_nif:
        nif = m_nif.group(1).strip() or None
    m_dt = re.search(r"(\d{2}[/-]\d{2}[/-]\d{4})", c1)
    if m_dt:
        data = m_dt.group(1)
    m_tm = re.search(r"(\d{2}:\d{2})", c1)
    if m_tm:
        godzina = m_tm.group(1)
    łącznie = None
    m_tot = re.search(r"Łącznie\s*(?:PLN|zł)?\s*(-?\d+[.,]\d{2})", c8, re.I)
    if m_tot:
        łącznie = to_float(m_tot.group(1))
    return {
        "odebrał": odebrał,
        "nif_lub_nip": nif,
        "data": data,
        "godzina": godzina,
        "łącznie_z_podsumowania": łącznie
    }

def parse_fedex_like_table(raw: List[List[Optional[str]]]) -> Dict[str, Any]:
    headers = [clean(c) for c in (raw[0] if raw else [])]
    r1 = raw[1] if len(raw) > 1 else []
    r2 = raw[2] if len(raw) > 2 else []
    r3 = raw[3] if len(raw) > 3 else []
    dane_przesyłki = parse_shipment_row(
        r1[0] if len(r1) > 0 else '',
        r1[3] if len(r1) > 3 else '',
        r1[4] if len(r1) > 4 else ''
    )
    nadawca = parse_sender_block(r2[0] if len(r2) > 0 else '')
    odbiorca = parse_receiver_block(r2[3] if len(r2) > 3 else '')
    koszty = parse_costs_block(r2[4] if len(r2) > 4 else '')
    stopka = parse_footer_row(
        r3[0] if len(r3) > 0 else '',
        r3[1] if len(r3) > 1 else '',
        r3[8] if len(r3) > 8 else ''
    )
    łącznie_z_miesz = dane_przesyłki.get("łącznie_kwota")
    łącznie_z_stopki = stopka.get("łącznie_z_podsumowania")
    spójność = None
    if łącznie_z_miesz is not None and łącznie_z_stopki is not None:
        spójność = abs(łącznie_z_miesz - łącznie_z_stopki) < 0.01
    return {
        "typ": "fedex_like",
        "spis_treści": [
            "1. Dane przesyłki (AWB, data wysyłki, usługa, waga, sztuki, numer ref., kwoty VAT/bez VAT/łącznie)",
            "2. Strony (Nadawca i Odbiorca z adresami)",
            "3. Koszty (koszty transportu, rabat, dopłaty paliwowe i inne)",
            "4. Podsumowanie (Łącznie – kontrola zgodności wiersz vs. stopka)",
            "5. Stopka (Odebrał, NIF/NIP, data i godzina)"
        ],
        "nagłówki_tabeli": headers,
        "dane_przesyłki": dane_przesyłki,
        "strony": {"nadawca": nadawca, "odbiorca": odbiorca},
        "koszty": koszty,
        "podsumowanie": {
            "łącznie_z_wiersza_pozycji": łącznie_z_miesz,
            "łącznie_z_stopki": łącznie_z_stopki,
            "spójność_łącznie": spójność
        },
        "stopka": stopka
    }

# --- Fallback: generyczna obsługa tabeli ---
HEADER_MAP = {
    'lp': 'lp',
    'poz': 'lp',
    'nazwa': 'opis',
    'opis': 'opis',
    'towar': 'opis',
    'produkt': 'opis',
    'ilość': 'ilość',
    'ilosc': 'ilość',
    'jm': 'jm',
    'jednostka': 'jm',
    'cena netto': 'cena_jedn_netto',
    'netto cena': 'cena_jedn_netto',
    'wartość netto': 'wartość_netto',
    'netto wartość': 'wartość_netto',
    'stawka vat': 'stawka_vat',
    'vat %': 'stawka_vat',
    'kwota vat': 'kwota_vat',
    'brutto': 'wartość_brutto',
    'description': 'opis',
    'qty': 'ilość',
    'unit': 'jm',
    'unit price net': 'cena_jedn_netto',
    'net value': 'wartość_netto',
    'vat rate': 'stawka_vat',
    'vat amount': 'kwota_vat',
    'gross': 'wartość_brutto',
}

def normalize_header(cell: str) -> str:
    k = clean(cell).lower()
    k = re.sub(r"[^a-ząćęłńóśźż %]", ' ', k)
    k = re.sub(r"\s+", ' ', k).strip()
    return HEADER_MAP.get(k, k or 'kolumna')

def classify_table(headers: List[str], rows: List[List[str]]) -> str:
    hset = {h.lower() for h in headers}
    text = ' '.join(' '.join(r) for r in rows).lower()
    items_score = sum(int(kw in hset or kw in text) for kw in ['opis','ilość','jm','wartość_netto','stawka_vat','kwota_vat','wartość_brutto','cena'])
    vat_score = sum(int(kw in text) for kw in ['vat','stawka','podatek','netto','brutto','suma','razem'])
    pay_score = sum(int(kw in text) for kw in ['płatność','sposób płatności','termin','zapłaty','paid','method','due'])
    if items_score >= 3 and len(headers) >= 3:
        return 'pozycje'
    if vat_score >= 3:
        return 'zestawienie_vat'
    if pay_score >= 2:
        return 'płatności'
    return 'nieznana'

def handle_generic_table(raw: List[List[Optional[str]]]) -> Dict[str, Any]:
    table = [[clean(c) for c in (row or [])] for row in (raw or [])]
    table = [row for row in table if any(cell for cell in row)]
    if not table:
        return {"typ": "pusta", "nagłówki": [], "wiersze": []}
    headers = [normalize_header(c) for c in table[0]]
    width = len(headers)
    rows_norm: List[List[str]] = []
    for r in table[1:]:
        rr = (r + [''] * max(0, width - len(r)))[:width]
        rows_norm.append(rr)
    typ = classify_table(headers, rows_norm)
    rows_out = []
    for r in rows_norm:
        conv = []
        for c in r:
            if re.match(NUMBER_RE, c) or re.match(AMOUNT_RE, c):
                num = to_float(c)
                conv.append(num if num is not None else c)
            else:
                conv.append(c)
        rows_out.append({headers[i] if i < len(headers) else f'kol_{i}': conv[i] for i in range(width)})
    return {"typ": typ, "nagłówki": headers, "wiersze": rows_out}

# --- Ekstrakcja tabel z pdfplumber (pojedyncza strategia) ---
def try_extract_tables(page):
    return extract_tables_single_strategy(page)

# --- Pipeline ---
def process_pdf(path: str) -> Dict[str, Any]:
    import pdfplumber
    all_tables = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            all_tables.extend(try_extract_tables(page))
    out_tables = []
    for ti, table in enumerate(all_tables, start=1):
        if detect_fedex_like_table(table):
            parsed = parse_fedex_like_table(table)
            parsed['indeks'] = ti
            out_tables.append(parsed)
        else:
            # Nie-FedEx: pomijamy zgodnie z wymaganiem
            continue
    return {'plik': path, 'tabele': out_tables}

def main():
    ap = argparse.ArgumentParser(description="Parsuj i zapisuj dane ze wszystkich tabel (pdfplumber.extract_tables)")
    ap.add_argument("pdf", help="Ścieżka do pliku PDF")
    ap.add_argument("--out", help="Ścieżka wyjściowego JSON", default=None)
    args = ap.parse_args()

    data = process_pdf(args.pdf)
    js = json.dumps(data, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as f:
            f.write(js)
        print(f"Zapisano: {args.out}")
    else:
        print(js)

if __name__ == "__main__":
    main()
