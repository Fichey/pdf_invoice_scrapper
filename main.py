import pdfplumber
import re
import json


TABLE_SETTINGS = {
    "vertical_strategy": "lines",       # tnij tylko po pionowych liniach
    "horizontal_strategy": "lines",     # tnij tylko po poziomych liniach
    "intersection_tolerance": 5,        # dopasowanie krzyżowania linii
    "snap_tolerance": 3,                # dociąganie końców linii
    "join_tolerance": 3,                # łączenie segmentów w jedną linię
    "edge_min_length": 20,              # minimalna długość linii (filtruje krótkie kreski)
    "snap_x_tolerance": 3,              # dokładność dla pionowych linii
    "snap_y_tolerance": 3,              # dokładność dla poziomych linii
}
FEDEX_HEADER = ['AWB', 'Data wysylki', 'Usługa', 'Sztuki', 'Waga', 'Numer ref.', 'Podlega VAT', 'Bez VAT', 'Łącznie']

def extract_tables_single_strategy(path: str):
    with pdfplumber.open(path) as pdf:
        tables = []
        for page in pdf.pages:
            tables.extend(page.extract_tables(TABLE_SETTINGS))
        return tables
    return []

def handle_tables(tables):
    tables_by_type = {
        "FedEx": []
    }
    for table in tables:
        if table and table[0] == FEDEX_HEADER:
            tables_by_type["FedEx"].append(table)

    airtable_records = []

    for type in tables_by_type:
        if not tables_by_type[type]:
            continue
        if type == "FedEx":
            for table in tables_by_type[type]:
                result = handle_fedex_table(table)
                if result:
                    airtable_records.append({
                        "fields": result
                    })

    return airtable_records


def is_kg_between_newlines(text: str) -> bool:
    return bool(re.search(r"\nkg\n", text, re.IGNORECASE))

def is_there_reference_number(text: str) -> bool:
    return bool(re.search(r"[()_]", text))

def is_reference_number_between_newlines(text: str) -> bool:
    return bool(re.search(r"\n\(\d+\)\n", text))

def is_there_underscore_in_reference_number(text: str) -> bool:
    return bool(re.search(r"[_]", text))

def handle_fedex_table(table):
    if not table or len(table) < 2:
        return None

    headers = table[0]
    rows = table[1:]

    if headers != FEDEX_HEADER:
        return None
    
    AWB = rows[0][0].split('\n')[0].split(' ')[0]
    data_wysylki = rows[0][0].split('\n')[0].split(' ')[1]
    czy_wymiary = bool(re.search(r"Wymiary\s+\S+", rows[0][0].split('\n')[1] ))
    dlugosc, szerokosc, wysokosc = (None, None, None)
    if czy_wymiary:
        wymiary = rows[0][0].split('\n')[1].split('Wymiary')[1].split('cm')[0].strip().split('x')
        if len(wymiary) == 3:
            dlugosc, szerokosc, wysokosc = map(float, wymiary)
    usluga = rows[0][2].split('Waga')[0].replace('\n', ' ').strip()

    match = re.search(r"([\d.,]+)", rows[0][2].split('Waga')[1])
    waga_zafakturowana = float(match.group(1).replace(",", ".")) if match else None

    dane = rows[0][3]
    dane = dane.replace('.', '').replace(',', '.').replace('(PLN)', '')

    kg_2_lines = is_kg_between_newlines(dane)
    contains_reference_number = is_there_reference_number(dane)
    contains_underscore = False
    reference_number_in_2_lines = False
    if contains_reference_number:
        contains_underscore = is_there_underscore_in_reference_number(dane)
        if not contains_underscore:
            reference_number_in_2_lines = is_reference_number_between_newlines(dane)

    dane = re.sub(r"\s+", " ", dane).strip()

    sztuki = None
    waga = None
    numer_referencyjny = None
    podlega_vat = None
    bez_vat = None
    lacznie = None

    # print(f"kg_2_lines: {kg_2_lines}")
    # tutaj przypisywanie tych danych da się zrobić bardziej elegancko, ale na razie zostawiam tak
    dane_split = dane.split(' ')

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

            if contains_underscore: # jest podkreślnik w numerze referencyjnym
                sztuki = int(dane_split[1])
                waga = float(dane_split[2])
                numer_referencyjny = dane_split[0] + dane_split[7]

            else:
                if not reference_number_in_2_lines: # numer referencyjny w jednej linii
                    sztuki = int(dane_split[0])
                    waga = float(dane_split[1])
                    numer_referencyjny = dane_split[3].replace("(", "").replace(")", "")
                
                else: # numer referencyjny w dwóch liniach
                    sztuki = int(dane_split[1])
                    waga = float(dane_split[2])
                    numer_referencyjny = dane_split[7].replace("(", "").replace(")", "")

    else: # waga w dwóch liniach

        if not contains_reference_number: # nie ma numeru referencyjnego
            sztuki = int(dane_split[1])
            waga = float(dane_split[0])
            podlega_vat = float(dane_split[2])
            bez_vat = float(dane_split[3])
            lacznie = float(dane_split[4])


        # else: # jest numer referencyjny
        #     podlega_vat = float(dane_split[4])
        #     bez_vat = float(dane_split[5])
        #     lacznie = float(dane_split[6])

        #     if contains_underscore: # jest podkreślnik w numerze referencyjnym
        #         sztuki = int(dane_split[0])
        #         waga = float(dane_split[1])
        #         numer_referencyjny = dane_split[3].replace('\n', '')

        #     else:
        #         if not reference_number_in_2_lines: # numer referencyjny w jednej linii
        #             sztuki = int(dane_split[0])
        #             waga = float(dane_split[1])
        #             numer_referencyjny = dane_split[3].replace("(", "").replace(")", "")
                
        #         else: # numer referencyjny w dwóch liniach
        #             sztuki = int(dane_split[1])
        #             waga = float(dane_split[2])
        #             numer_referencyjny = dane_split[7].replace("(", "").replace(")", "")



    # print(f"Dane: {dane}")
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
        "lacznie": lacznie
    }



def main():
    path = "data/invoice1.pdf"
    out_path = "data/records.json"
    tables = extract_tables_single_strategy(path)

    records = handle_tables(tables)


    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()