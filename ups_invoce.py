import pdfplumber
import re
import json
import os
from typing import List, Dict, Optional, Tuple

class InvoiceParser:
    """
    Updated invoice parser that integrates with web application
    Based on your original main.py but refactored for web use
    """

    def __init__(self):
        self.TABLE_SETTINGS = {
            "vertical_strategy": "lines",
            "horizontal_strategy": "lines", 
            "intersection_tolerance": 5,
            "snap_tolerance": 3,
            "join_tolerance": 3,
            "edge_min_length": 20,
            "snap_x_tolerance": 3,
            "snap_y_tolerance": 3,
        }

        self.FEDEX_HEADER = [
            'AWB', 'Data wysylki', 'Usługa', 'Sztuki', 'Waga', 
            'Numer ref.', 'Podlega VAT', 'Bez VAT', 'Łącznie'
        ]

    def extract_invoice_number(self, pdf: pdfplumber.PDF) -> Optional[str]:
        """Extract invoice number from PDF"""
        text = pdf.pages[0].extract_text()
        match = re.search(r"Numer\s+faktury\s+VAT:\s*([0-9]+)", text)
        return match.group(1) if match else None

    def extract_invoice_date(self, pdf: pdfplumber.PDF) -> Optional[str]:
        """Extract invoice date from PDF"""
        text = pdf.pages[0].extract_text()
        match = re.search(r"Data\s+faktury:\s*([0-9]{2}/[0-9]{2}/[0-9]{4})", text)
        return match.group(1) if match else None

    def extract_tables_single_strategy(self, path: str) -> Tuple[List, Optional[str], Optional[str]]:
        """
        Extract tables from PDF file

        Args:
            path: Path to PDF file

        Returns:
            Tuple of (tables, invoice_number, invoice_date)
        """
        try:
            with pdfplumber.open(path) as pdf:
                tables = []
                for page in pdf.pages:
                    page_tables = page.extract_tables(self.TABLE_SETTINGS)
                    tables.extend(page_tables)

                invoice_number = self.extract_invoice_number(pdf)
                invoice_date = self.extract_invoice_date(pdf)

                return tables, invoice_number, invoice_date
        except Exception as e:
            print(f"Error extracting tables: {e}")
            return [], None, None

    def is_kg_between_newlines(self, text: str) -> bool:
        """Check if 'kg' appears between newlines"""
        return bool(re.search(r"\nkg", text, re.IGNORECASE))

    def is_there_reference_number(self, text: str) -> bool:
        """Check if there's a reference number in text"""
        return bool(re.search(r"[()_]", text))

    def is_reference_number_between_newlines(self, text: str) -> bool:
        """Check if reference number appears between newlines"""
        return bool(re.search(r"\(\d+\)\n", text))

    def is_there_underscore_in_reference_number(self, text: str) -> bool:
        """Check if reference number contains underscore"""
        return bool(re.search(r"[_]", text))

    def handle_fedex_table(self, table: List[List[str]], numer_faktury) -> Optional[Dict]:
        """
        Process FedEx table data

        Args:
            table: 2D list representing table data

        Returns:
            Dictionary with processed data or None if processing fails
        """
        if not table or len(table) < 2:
            return None

        headers = table[0]
        rows = table[1:]

        if headers != self.FEDEX_HEADER:
            return None

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
            kg_2_lines = self.is_kg_between_newlines(dane)
            contains_reference_number = self.is_there_reference_number(dane)
            contains_underscore = False
            reference_number_in_2_lines = False

            if contains_reference_number:
                contains_underscore = self.is_there_underscore_in_reference_number(dane)
                if not contains_underscore:
                    reference_number_in_2_lines = self.is_reference_number_between_newlines(dane)

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
                    else:
                        podlega_vat = float(dane_split[3])
                        bez_vat = float(dane_split[4])
                        lacznie = float(dane_split[5])

                        if contains_underscore: # jest podkreślnik w numerze referencyjnym
                            sztuki = int(dane_split[2])
                            waga = float(dane_split[0])
                            numer_referencyjny = dane_split[1] + dane_split[7]

                        else:
                            print(repr(rows[0][3]) , dane)
                            raise NotImplementedError("Nie obsługiwane jeszcze przypadki z wagą i numerem referencyjnym w dwóch liniach")
            except NotImplementedError as nie:
                raise NotImplementedError(f"Nr faktury: {numer_faktury}. {nie} AWB: {AWB} Dane: {dane}") from None
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

    def handle_tables(self, tables, numer_faktury=None, data_faktury=None):
        tables_by_type = {"FedEx": []}
        for table in tables:
            if table and len(table) > 0 and table[0] == self.FEDEX_HEADER:
                tables_by_type["FedEx"].append(table)

        airtable_records = []
        errors = []

        for table_type in tables_by_type:
            if not tables_by_type[table_type]:
                continue
            if table_type == "FedEx":
                for table in tables_by_type[table_type]:
                    base_data = {
                        "numer_faktury": numer_faktury,
                        "data_faktury": data_faktury
                    }
                    result = self.handle_fedex_table(table, numer_faktury)
                    if result is None:
                        continue
                    if "error" in result:
                        errors.append(result["error"])
                    else:
                        record = {**base_data, **result}
                        airtable_records.append({"fields": record})

        return airtable_records, errors

    def parse_pdf(self, pdf_path: str):
        tables, invoice_number, invoice_date = self.extract_tables_single_strategy(pdf_path)
        if not tables:
            return [], {"error": "No tables found in PDF"}

        records, errors = self.handle_tables(tables, invoice_number, invoice_date)
        metadata = {
            "invoice_number": invoice_number,
            "invoice_date": invoice_date,
            "tables_found": len(tables),
            "records_created": len(records),
            "errors": errors
        }
        return records, metadata


# Example usage (for testing)
if __name__ == "__main__":
    parser = InvoiceParser()

    # Test with a PDF file
    pdf_path = "test_invoice.pdf"
    if os.path.exists(pdf_path):
        records, metadata = parser.parse_pdf(pdf_path)

        print("Metadata:", json.dumps(metadata, indent=2))
        print("Records:", json.dumps(records, indent=2))
    else:
        print("No test PDF file found. Use this class in your Flask application.")
