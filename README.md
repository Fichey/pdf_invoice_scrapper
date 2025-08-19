# PDF Invoice Parser

**What it does**
- Extracts text & tables from invoice PDFs (prefers `pdfplumber`, falls back to `PyPDF2`).
- Robust to scrambled token order in extracted text (e.g., lines mixing `Łącznie PLN`, `Odebrał:`, date/time, amount). The parser re-extracts atomic parts with regex and rebuilds them in the correct human order.
- Parses header fields (number, dates, payment method), parties (seller/buyer), totals (net, VAT, gross), and items (from tables, with a regex fallback).

**Install**
```bash
pip install -r requirements.txt
```

**Run**
```bash
python invoice_parser.py first_page.pdf --out parsed.json
```

**Output**
- JSON with `header`, `parties`, `totals`, `receiver` line, and `items` list.

**Why `pdfplumber` first?**
It preserves layout and can read tables, which matters on multi-page, big invoices. If it fails or isn't installed, the script will still work via `PyPDF2` + regex.

**Fix for out-of-order text**
The function `fix_out_of_order_segments()` detects any line that contains both `Odebrał:` and `Łącznie/Razem/Suma`, re-extracts `Odebrał: <name>`, `NIP/NIF`, `date`, `time`, and the total `amount`, then rebuilds:
```
Odebrał: <name> NIP <id> <dd/mm/yyyy> <hh:mm> Łącznie PLN <amount>
```
Missing pieces are gracefully skipped.
