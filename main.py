import pdfplumber
import re


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
    
    return {
        "typ": "FedEx",
        "AWB": AWB,
        "data_wysylki": data_wysylki,
        "dlugosc": dlugosc,
        "szerokosc": szerokosc,
        "wysokosc": wysokosc,
    }



def main():
    path = "data/first_page.pdf"
    tables = extract_tables_single_strategy(path)
    fedex_tables = []
    for table in tables:
        if table and table[0] == FEDEX_HEADER:
            fedex_tables.append(table)
            for row in table:
                print(row)



if __name__ == "__main__":
    main()