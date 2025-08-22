import re
from typing import List, Dict, Optional



FEDEX_HEADER = [
    'AWB', 'Data wysylki', 'Usługa', 'Sztuki', 'Waga',
    'Numer ref.', 'Podlega VAT', 'Bez VAT', 'Łącznie'
]

def is_kg_between_newlines(text: str) -> bool:
    """Check if 'kg' appears between newlines"""
    return bool(re.search(r"\nkg", text, re.IGNORECASE))

def is_there_reference_number(text: str) -> bool:
    """Check if there's a reference number in text"""
    return bool(re.search(r"[()_]", text))

def is_reference_number_between_newlines(text: str) -> bool:
    """Check if reference number appears between newlines"""
    return bool(re.search(r"\(\d+\)\n", text))

def is_there_underscore_in_reference_number(text: str) -> bool:
    """Check if reference number contains underscore"""
    return bool(re.search(r"[_]", text))

def handle_fedex_table(table: List[List[str]], numer_faktury) -> Optional[Dict]:
    # ... your existing full implementation unchanged ...

    if not table or len(table) < 2:
        return None

    headers = table[0]
    rows = table[1:]

    if not "AWB" in headers and not "Data wysylki" in headers:
        return None

    if headers != FEDEX_HEADER:
        return {"error": f"Error processing FedEx table: Nr faktury: {numer_faktury}. Niestandardowa struktura tabeli: {repr(headers)}"}

    AWB = rows[0][0].split('\n')[0].split(' ')[0]
    dane = rows[0][3]

    try:
        # Extract AWB and shipping date

        data_wysylki = rows[0][0].split('\n')[0].split(' ')[1]

        # Check for dimensions
        czy_wymiary = bool(re.search(r"Wymiary\s+\S+", rows[0][0].split('\n')[1]))

        dlugosc, szerokosc, wysokosc = (None, None, None)
        if czy_wymiary:
            wymiary_text = rows[0][0].split('\n')[1].split('Wymiary')[1].split('cm')[0].strip()
            wymiary = wymiary_text.split('x')
            if len(wymiary) == 3:
                dlugosc, szerokosc, wysokosc = map(float, wymiary)

        # Extract service and invoiced weight
        usluga = rows[0][2].split('Waga')[0].replace('\n', ' ').strip()
        match = re.search(r"([\d.,]+)", rows[0][2].split('Waga')[1])
        waga_zafakturowana = float(match.group(1).replace(",", ".")) if match else None

        # Process complex data field
        dane = rows[0][3]
        dane = dane.replace('.', '').replace(',', '.').replace('(PLN)', '')

        # Analyze data structure
        kg_2_lines = is_kg_between_newlines(dane)
        contains_reference_number = is_there_reference_number(dane)
        contains_underscore = False
        reference_number_in_2_lines = False

        if contains_reference_number:
            contains_underscore = is_there_underscore_in_reference_number(dane)
            if not contains_underscore:
                reference_number_in_2_lines = is_reference_number_between_newlines(dane)

        dane = re.sub(r"\s+", " ", dane).strip()

        # Initialize variables
        sztuki = None
        waga = None
        numer_referencyjny = None
        podlega_vat = None
        bez_vat = None
        lacznie = None

        dane_split = dane.split(' ')

        # Complex parsing logic (preserved from original)
        try:
            if not kg_2_lines: # waga w jednej linii

                if not contains_reference_number: # nie ma numeru referencyjnego
                    sztuki = int(dane_split[0])
                    waga = float(dane_split[1])
                    podlega_vat = float(dane_split[3])
                    bez_vat = float(dane_split[4])
                    lacznie = float(dane_split[5])

                else: # jest numer referencyjny
                    podlega_vat = float(dane_split[4])
                    bez_vat = float(dane_split[5])
                    lacznie = float(dane_split[6])

                    if contains_underscore: # jest podkreĹlnik w numerze referencyjnym
                        sztuki = int(dane_split[1])
                        waga = float(dane_split[2])
                        numer_referencyjny = dane_split[0] + dane_split[7]

                    else:
                        if not reference_number_in_2_lines: # numer referencyjny w jednej linii
                            sztuki = int(dane_split[0])
                            waga = float(dane_split[1])
                            numer_referencyjny = dane_split[3].replace("(", "").replace(")", "")
                        
                        else: # numer referencyjny w dwĂłch liniach
                            sztuki = int(dane_split[1])
                            waga = float(dane_split[2])
                            numer_referencyjny = dane_split[7].replace("(", "").replace(")", "")

            else: # waga w dwĂłch liniach

                if not contains_reference_number: # nie ma numeru referencyjnego
                    sztuki = int(dane_split[1])
                    waga = float(dane_split[0])
                    podlega_vat = float(dane_split[2])
                    bez_vat = float(dane_split[3])
                    lacznie = float(dane_split[4])
                else:
                    podlega_vat = float(dane_split[3])
                    bez_vat = float(dane_split[4])
                    lacznie = float(dane_split[5])

                    if contains_underscore: # jest podkreĹlnik w numerze referencyjnym
                        sztuki = int(dane_split[2])
                        waga = float(dane_split[0])
                        numer_referencyjny = dane_split[1] + dane_split[7]

                    else:
                        print(repr(rows[0][3]) , dane)
                        raise NotImplementedError("Nie obsługiwane jeszcze przypadki z wagą i numerem referencyjnym w dwóch liniach")
        except NotImplementedError as nie:
            if (dane and AWB):
                raise NotImplementedError(f"Nr faktury: {numer_faktury}. {nie} AWB: {AWB} Dane: {dane}") from None
            else:
                raise NotImplementedError(f"Nr faktury: {numer_faktury}. {nie}") from None
        except ValueError as ve:
            raise ValueError(f"Nr faktury: {numer_faktury}. Błąd parsowania danych FedEx: {ve}. AWB: {AWB} Dane: {dane}") from None
        except Exception as e:
            raise RuntimeError(f"Nr faktury: {numer_faktury}. Unexpected error: {e}. AWB: {AWB} Dane: {dane}") from None
        # Extract sender and recipient information
        informacje_nadawca = rows[1][0].replace('\n', ' ').replace('Nadawca ','').strip()
        informacje_odbiorca = rows[1][2].replace('\n', ' ').replace('Odbiorca ','').strip()

        # Extract delivery information
        odebral_match = re.search(r":\s*([^\d]+)", rows[2][0])
        odebral = odebral_match.group(1).strip() if odebral_match else None

        czas_match = re.search(r"\d.*", rows[2][0])
        czas_odebrania = czas_match.group(0) if czas_match else None

        return {
            "typ": "FedEx",
            "AWB": AWB,
            "data_wysylki": data_wysylki,
            "dlugosc": dlugosc,
            "szerokosc": szerokosc,
            "wysokosc": wysokosc,
            "usluga": usluga,
            "waga_zafakturowana": waga_zafakturowana,
            "sztuki": sztuki,
            "waga": waga,
            "numer_referencyjny": numer_referencyjny,
            "podlega_vat": podlega_vat,
            "bez_vat": bez_vat,
            "lacznie": lacznie,
            "informacje_nadawca": informacje_nadawca,
            "informacje_odbiorca": informacje_odbiorca,
            "odebral": odebral,
            "czas_odebrania": czas_odebrania
        }
    except Exception as e:
        return {"error": f"Error processing FedEx table: {str(e)}"}