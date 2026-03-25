# Code for Age Extraction from PDF Clinical Records

import PyPDF2
import re

def extract_age_from_pdf(pdf_file):
    age_pattern = re.compile(r'\b(?:Age|age)\s*[:=]\s*(\d+)\b')
    ages = []

    with open(pdf_file, 'rb') as file:
        reader = PyPDF2.PdfReader(file)
        for page in reader.pages:
            text = page.extract_text()
            if text:
                matches = age_pattern.findall(text)
                ages.extend(matches)

    return ages

# Example usage:
# age_list = extract_age_from_pdf('sample.pdf')
# print(age_list)