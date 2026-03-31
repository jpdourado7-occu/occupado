import openpyxl
import hashlib
import re
import os

data_dir = r'C:\Users\jpdou\Desktop\Occupado\VDV-MEC'
out_dir  = r'C:\Users\jpdou\Desktop\Occupado\VDV-MEC\anonymized'
os.makedirs(out_dir, exist_ok=True)


def sha256_hash(value):
    return hashlib.sha256(str(value).strip().encode('utf-8')).hexdigest()


# Guest name: "Lastname, Firstname[, Title]" — no digits, no parentheses
NAME_RE  = re.compile(
    r'^[A-Za-z\xc0-\xff][A-Za-z\xc0-\xff\s\-\.\']+,'
    r'\s*[A-Za-z\xc0-\xff][A-Za-z\xc0-\xff\s\-\.\']*'
    r'(?:,\s*(?:Mr\.|Mrs\.|Ms\.|Dr\.|Dhr\.|Mevr\.))?$'
)
EMAIL_RE = re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b')
MEMB_RE  = re.compile(r'^\d[\d\s,\-]{6,}$')   # pure numeric membership strings

NON_PII = {
    'CorpBookings, Archived',
    'Van der Valk Hotel Mechelen',
    'Arrived Totals', 'Departed Totals', 'Date Totals',
    'Subtotals', 'Totals per Date',
    'Profile Notes',
    'Movement Report Detailed', 'Arrivals Report',
    'Arrivals Report Detailed', 'Cancelled Reservations',
    'No Show Reservations Report', 'Repeat Reservations Report',
    'Movement Report Summary',
}


def transform(value):
    if not isinstance(value, str):
        return value
    s = value.strip()
    if not s or s in NON_PII:
        return value
    # Guest name pattern — no digits, no parentheses
    if NAME_RE.match(s) and not any(c.isdigit() for c in s) and '(' not in s:
        return sha256_hash(s)
    # Pure membership / loyalty number strings
    if MEMB_RE.match(s):
        return sha256_hash(s)
    # Emails embedded in notes text
    if EMAIL_RE.search(s):
        return EMAIL_RE.sub(lambda m: sha256_hash(m.group(0)), s)
    return value


files = sorted(f for f in os.listdir(data_dir) if f.endswith('.xlsx'))

for filename in files:
    src = os.path.join(data_dir, filename)
    dst = os.path.join(out_dir, filename)
    wb = openpyxl.load_workbook(src)
    changes = 0
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str):
                    new_val = transform(cell.value)
                    if new_val != cell.value:
                        cell.value = new_val
                        changes += 1
    wb.save(dst)
    print(f'  {filename}: {changes} cells anonymized')

print('\nAll files saved to:', out_dir)
