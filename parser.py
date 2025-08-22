import pdfplumber
import re
import json
import os
from typing import List, Dict, Optional, Tuple
from handle_fedex_table import handle_fedex_table


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

    def detect_file_type(self, pdf: pdfplumber.PDF) -> Optional[str]:
        text = pdf.pages[0].extract_text() if pdf.pages else ""
        if not text:
            return None
        if "FedEx" in text:
            return "FedEx"
        # Extend with other types (e.g., 'UPS') detection logic here
        return "Unknown"

    def extract_invoice_number(self, pdf: pdfplumber.PDF, file_type: str) -> Optional[str]:
        if file_type == "FedEx":
            return self.extract_invoice_number_fedex(pdf)
        # Add other file_type conditions here
        return None

    def extract_invoice_number_fedex(self, pdf: pdfplumber.PDF) -> Optional[str]:
        text = pdf.pages[0].extract_text()
        match = re.search(r"Numer\s+faktury\s+VAT:\s*([0-9]+)", text)
        return match.group(1) if match else None

    def extract_invoice_date(self, pdf: pdfplumber.PDF, file_type: str) -> Optional[str]:
        if file_type == "FedEx":
            return self.extract_invoice_date_fedex(pdf)
        # Add other file_type conditions here
        return None

    def extract_invoice_date_fedex(self, pdf: pdfplumber.PDF) -> Optional[str]:
        text = pdf.pages[0].extract_text()
        match = re.search(r"Data\s+faktury:\s*([0-9]{2}/[0-9]{2}/[0-9]{4})", text)
        return match.group(1) if match else None

    def extract_tables(self, pdf: pdfplumber.PDF, file_type: str) -> List[List[List[str]]]:
        if file_type == "FedEx":
            return self.extract_tables_fedex(pdf)
        # Add other file_type conditions here
        return []

    def extract_tables_fedex(self, pdf: pdfplumber.PDF) -> List[List[List[str]]]:
        tables = []
        for page in pdf.pages:
            page_tables = page.extract_tables(self.TABLE_SETTINGS)
            tables.extend(page_tables)
        return tables


    def handle_tables(self, tables, numer_faktury, data_faktury=None, file_type=None):
        if file_type == "FedEx":
            return self.handle_fedex_tables(tables, numer_faktury, data_faktury)
        # Add other handlers for different file types here
        return [], []

    def handle_fedex_tables(self, tables, numer_faktury, data_faktury=None):
        
        airtable_records = []
        errors = []

        if tables:
            for table in tables:
                base_data = {
                    "numer_faktury": numer_faktury,
                    "data_faktury": data_faktury
                }
                result = handle_fedex_table(table, numer_faktury)
                if result is None:
                    continue
                if "error" in result:
                    errors.append(result["error"])
                else:
                    record = {**base_data, **result}
                    airtable_records.append({"fields": record})

        return airtable_records, errors

    def parse_pdf(self, pdf_path: str):
        try:
            with pdfplumber.open(pdf_path) as pdf:
                file_type = self.detect_file_type(pdf)

                invoice_number = self.extract_invoice_number(pdf, file_type)
                invoice_date = self.extract_invoice_date(pdf, file_type)

                tables = self.extract_tables(pdf, file_type)

            if not tables:
                return [], {"error": "No tables found in PDF", "file_type": file_type}

            records, errors = self.handle_tables(tables, invoice_number, invoice_date, file_type)

            metadata = {
                "invoice_number": invoice_number,
                "invoice_date": invoice_date,
                "file_type": file_type,
                "tables_found": len(tables),
                "records_created": len(records),
                "errors": errors
            }

            return records, metadata
        except Exception as e:
            return [], {"error": str(e)}

# Example usage for testing
if __name__ == "__main__":
    parser = InvoiceParser()
    pdf_path = "data/invoices/529504604.pdf"

    if os.path.exists(pdf_path):
        records, metadata = parser.parse_pdf(pdf_path)
        print("Metadata:", json.dumps(metadata, indent=2))
        print("Records:", json.dumps(records, indent=2))
    else:
        print("No test PDF file found. Use this class in your Flask application.")
