import pdfplumber

with pdfplumber.open("first_page.pdf") as pdf:
    first_page = pdf.pages[0]
    print(first_page.extract_tables())