import os
import json
import tempfile
from flask import Flask, request, render_template, jsonify, flash, redirect, url_for
from werkzeug.utils import secure_filename
import requests
import pdfplumber
import re
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Airtable configuration
AIRTABLE_API_KEY = os.environ.get('AIRTABLE_API_KEY')
AIRTABLE_BASE_ID = os.environ.get('AIRTABLE_BASE_ID')
AIRTABLE_TABLE_NAME = os.environ.get('AIRTABLE_TABLE_NAME', 'Invoices')

# Table extraction settings (from original code)
TABLE_SETTINGS = {
    "vertical_strategy": "lines",
    "horizontal_strategy": "lines", 
    "intersection_tolerance": 5,
    "snap_tolerance": 3,
    "join_tolerance": 3,
    "edge_min_length": 20,
    "snap_x_tolerance": 3,
    "snap_y_tolerance": 3,
}

FEDEX_HEADER = ['AWB', 'Data wysylki', 'Usługa', 'Sztuki', 'Waga', 'Numer ref.', 'Podlega VAT', 'Bez VAT', 'Łącznie']

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() == 'pdf'

def extract_invoice_number(pdf):
    """Extract invoice number from PDF"""
    text = pdf.pages[0].extract_text()
    match = re.search(r"Numer\s+faktury\s+VAT:\s*([0-9]+)", text)
    if match:
        return match.group(1)
    return None

def extract_invoice_date(pdf):
    """Extract invoice date from PDF"""
    text = pdf.pages[0].extract_text()
    match = re.search(r"Data\s+faktury:\s*([0-9]{2}/[0-9]{2}/[0-9]{4})", text)
    if match:
        return match.group(1)
    return None

def extract_tables_from_pdf(pdf_file_path):
    """Extract tables from PDF file"""
    try:
        with pdfplumber.open(pdf_file_path) as pdf:
            tables = []
            for page in pdf.pages:
                tables.extend(page.extract_tables(TABLE_SETTINGS))

            invoice_number = extract_invoice_number(pdf)
            invoice_date = extract_invoice_date(pdf)

            return tables, invoice_number, invoice_date
    except Exception as e:
        print(f"Error extracting tables: {e}")
        return [], None, None

def is_kg_between_newlines(text):
    return bool(re.search(r"\nkg\n", text, re.IGNORECASE))

def is_there_reference_number(text):
    return bool(re.search(r"[()_]", text))

def is_reference_number_between_newlines(text):
    return bool(re.search(r"\n\(\d+\)\n", text))

def is_there_underscore_in_reference_number(text):
    return bool(re.search(r"[_]", text))

def handle_fedex_table(table):
    """Process FedEx table data (from original code)"""
    if not table or len(table) < 2:
        return None

    headers = table[0]
    rows = table[1:]

    if headers != FEDEX_HEADER:
        return None

    try:
        AWB = rows[0][0].split('\n')[0].split(' ')[0]
        data_wysylki = rows[0][0].split('\n')[0].split(' ')[1]

        czy_wymiary = bool(re.search(r"Wymiary\s+\S+", rows[0][0].split('\n')[1]))

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

        dane_split = dane.split(' ')

        # Original complex parsing logic from user's code
        if not kg_2_lines:
            if not contains_reference_number:
                sztuki = int(dane_split[0])
                waga = float(dane_split[1])
                podlega_vat = float(dane_split[3])
                bez_vat = float(dane_split[4])
                lacznie = float(dane_split[5])
            else:
                podlega_vat = float(dane_split[4])
                bez_vat = float(dane_split[5])
                lacznie = float(dane_split[6])

                if contains_underscore:
                    sztuki = int(dane_split[1])
                    waga = float(dane_split[2])
                    numer_referencyjny = dane_split[0] + dane_split[7]
                else:
                    if not reference_number_in_2_lines:
                        sztuki = int(dane_split[0])
                        waga = float(dane_split[1])
                        numer_referencyjny = dane_split[3].replace("(", "").replace(")", "")
                    else:
                        sztuki = int(dane_split[1])
                        waga = float(dane_split[2])
                        numer_referencyjny = dane_split[7].replace("(", "").replace(")", "")
        else:
            if not contains_reference_number:
                sztuki = int(dane_split[1])
                waga = float(dane_split[0])
                podlega_vat = float(dane_split[2])
                bez_vat = float(dane_split[3])
                lacznie = float(dane_split[4])

        informacje_nadawca = rows[1][0].replace('\n', ' ').replace('Nadawca ','').strip()
        informacje_odbiorca = rows[1][2].replace('\n', ' ').replace('Odbiorca ','').strip()

        odebral = re.search(r":\s*([^\d]+)", 
                           rows[2][0]).group(1).strip() if re.search(r":\s*([^\d]+)", rows[2][0]) else None
        czas_odebrania = re.search(r"\d.*", rows[2][0]).group(0) if re.search(r"\d.*", rows[2][0]) else None

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
        print(f"Error processing FedEx table: {e}")
        return None

def handle_tables(tables, numer_faktury=None, data_faktury=None):
    """Process extracted tables"""
    tables_by_type = {"FedEx": []}

    for table in tables:
        if table and table[0] == FEDEX_HEADER:
            tables_by_type["FedEx"].append(table)

    airtable_records = []

    for table_type in tables_by_type:
        if not tables_by_type[table_type]:
            continue

        if table_type == "FedEx":
            for table in tables_by_type[table_type]:
                result = {"numer_faktury": numer_faktury,
                         "data_faktury": data_faktury} | handle_fedex_table(table)
                if result:
                    airtable_records.append({"fields": result})

    return airtable_records

def send_to_airtable(records):
    """Send records to Airtable"""
    if not AIRTABLE_API_KEY or not AIRTABLE_BASE_ID:
        raise ValueError("Airtable configuration missing")

    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}",
        "Content-Type": "application/json"
    }

    successful_records = 0
    failed_records = 0
    errors = []

    # Airtable allows max 10 records per batch
    batch_size = 10
    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]

        payload = {"records": batch}

        try:
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()

            result = response.json()
            successful_records += len(result.get('records', []))

        except requests.exceptions.RequestException as e:
            failed_records += len(batch)
            error_msg = f"Batch {i//batch_size + 1} failed: {str(e)}"
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.json()
                    error_msg += f" - {error_detail}"
                except:
                    error_msg += f" - {e.response.text}"
            errors.append(error_msg)

    return {
        "successful": successful_records,
        "failed": failed_records,
        "errors": errors
    }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['file']

        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        if not allowed_file(file.filename):
            return jsonify({'error': 'Only PDF files are allowed'}), 400

        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
            file.save(tmp_file.name)
            temp_path = tmp_file.name

        try:
            # Process the PDF
            tables, invoice_number, invoice_date = extract_tables_from_pdf(temp_path)

            if not tables:
                return jsonify({'error': 'No tables found in PDF'}), 400

            # Convert to Airtable format
            records = handle_tables(tables, invoice_number, invoice_date)

            if not records:
                return jsonify({'error': 'No valid data found to process'}), 400

            # Send to Airtable
            result = send_to_airtable(records)

            return jsonify({
                'message': 'File processed successfully',
                'filename': secure_filename(file.filename),
                'invoice_number': invoice_number,
                'invoice_date': invoice_date,
                'records_processed': len(records),
                'airtable_result': result
            })

        finally:
            # Clean up temporary file
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    except Exception as e:
        return jsonify({'error': f'Processing error: {str(e)}'}), 500

@app.route('/health')
def health_check():
    """Health check endpoint for Railway"""
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('FLASK_ENV') == 'development')
