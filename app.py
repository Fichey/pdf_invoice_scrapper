import os
import tempfile
from flask import Flask, request, jsonify, render_template
from parser import InvoiceParser
import requests

from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Airtable configuration from environment
AIRTABLE_API_KEY = os.environ.get("AIRTABLE_API_KEY")
BASE_ID = os.environ.get("AIRTABLE_BASE_ID")
TABLE_NAME = os.environ.get("AIRTABLE_TABLE_NAME", "Invoices")

headers = {
    "Authorization": f"Bearer {AIRTABLE_API_KEY}",
    "Content-Type": "application/json"
}

def find_existing_records(unique_values, unique_field):
    if not unique_values:
        return []

    records = []
    formula_parts = [f"{{{unique_field}}}='{v}'" for v in unique_values]
    filter_formula = "OR(" + ",".join(formula_parts) + ")"

    url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLE_NAME}?filterByFormula={filter_formula}"

    while url:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        records.extend(data.get("records", []))
        url = data.get("offset")
        if url:
            # Append offset query param for next page
            url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLE_NAME}?filterByFormula={filter_formula}&offset={url}"

    return records

def send_to_airtable(records, unique_field="AWB"):
    # Extract unique keys from incoming records
    unique_values = [rec["fields"].get(unique_field) for rec in records if unique_field in rec["fields"] and rec["fields"].get(unique_field) is not None]
    existing_records = find_existing_records(unique_values, unique_field)
    existing_map = {rec["fields"][unique_field]: rec["id"] for rec in existing_records}

    to_create = []
    to_update = []

    for record in records:
        key = record["fields"].get(unique_field)
        if key in existing_map:
            to_update.append({
                "id": existing_map[key],
                "fields": record["fields"]
            })
        else:
            to_create.append(record)

    created = []
    updated = []
    url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLE_NAME}"

    # Batch create new records (max 10 per batch)
    for i in range(0, len(to_create), 10):
        batch = to_create[i:i+10]
        resp = requests.post(url, json={"records": batch}, headers=headers)
        resp.raise_for_status()
        created.extend(resp.json().get("records", []))

    # Batch update existing records (max 10 per batch)
    for i in range(0, len(to_update), 10):
        batch = to_update[i:i+10]
        resp = requests.patch(url, json={"records": batch}, headers=headers)
        resp.raise_for_status()
        updated.extend(resp.json().get("records", []))

    return {
        "created_count": len(created),
        "updated_count": len(updated),
        "created_records": created,
        "updated_records": updated
    }

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() == 'pdf'

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file part in the request'}), 400

        file = request.files['file']

        if file.filename == '':
            return jsonify({'error': 'No selected file'}), 400

        if not allowed_file(file.filename):
            return jsonify({'error': 'Only PDF files are allowed'}), 400

        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
            file.save(tmp.name)
            temp_path = tmp.name

        parser = InvoiceParser()
        records, metadata = parser.parse_pdf(temp_path)

        if 'error' in metadata:
            return jsonify({'error': metadata['error']}), 400

        if not records and metadata.get("errors"):
            # Return parsing errors if no records
            return jsonify({'error': 'Parsing errors occurred', 'log': "\n".join(metadata["errors"])}), 400

        if not records:
            return jsonify({'error': 'No valid FedEx data found in PDF'}), 400

        airtable_result = send_to_airtable(records, unique_field="AWB")

        return jsonify({
            'message': 'File processed successfully',
            'invoice_number': metadata.get('invoice_number'),
            'invoice_date': metadata.get('invoice_date'),
            'records_processed': len(records),
            'airtable_result': airtable_result,
            'log': "\n".join(metadata.get('errors', []))  # Include parsing errors as log for UI
        })

    except NotImplementedError as nie:
        return jsonify({'error': f'Nie obsługiwane przypadki: {str(nie)}'}), 400
    except ValueError as ve:
        return jsonify({'error': f'Błąd parsowania: {str(ve)}'}), 400
    except Exception as e:
        return jsonify({'error': f'Processing error: {str(e)}'}), 500

@app.route('/health')
def health_check():
    return jsonify({'status': 'healthy'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('FLASK_ENV') == 'development')
