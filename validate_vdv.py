# validate_vdv.py — Full VdV model validation
# Uses ALL available cancellation + arrival files, repeat guests, preferences, and EnteredOnAndBy

import re
import pickle
import numpy as np
import pandas as pd
import openpyxl
from datetime import datetime, timedelta
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, roc_auc_score,
    confusion_matrix, classification_report
)

BASE_DIR = r'C:\Users\jpdou\Desktop\Occupado'
RAW_DIR  = rf'{BASE_DIR}\VDV-MEC'
ANON_DIR = rf'{RAW_DIR}\anonymized'
MODEL_PATH = rf'{BASE_DIR}\occupado_model.pkl'

FEATURES = [
    'lead_time', 'arrival_date_week_number',
    'stays_in_weekend_nights', 'stays_in_week_nights',
    'adults', 'is_repeated_guest',
    'previous_cancellations', 'previous_bookings_not_canceled',
    'booking_changes', 'days_in_waiting_list',
    'adr', 'total_of_special_requests',
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_date(val):
    if val is None: return None
    s = str(val).strip()[:16]
    for fmt in ('%d/%m/%Y %H:%M', '%d/%m/%Y'):
        try: return datetime.strptime(s, fmt)
        except: pass
    return None

def parse_rate(val):
    if val is None: return None
    s = re.sub(r'[^\d,\.]', '', str(val))
    if ',' in s and '.' in s:
        s = s.replace('.', '').replace(',', '.')
    else:
        s = s.replace(',', '.')
    try: return float(s)
    except: return None

def parse_adults(val):
    if val is None: return None
    try: return int(str(val).split('/')[0])
    except: return None

def is_hash(val):
    return bool(val and re.match(r'^[0-9a-f]{60,}', str(val)))

def count_nights(arr_date, n):
    we = wd = 0
    for i in range(max(0, int(n))):
        d = arr_date + timedelta(days=i)
        if d.weekday() >= 5: we += 1
        else: wd += 1
    return we, wd

def load_wb_rows(path):
    wb = openpyxl.load_workbook(path, read_only=True)
    rows = list(wb.active.iter_rows(values_only=True))
    wb.close()
    return rows

# ---------------------------------------------------------------------------
# Parser: Cancelled Reservations (RES_036)
# Format confirmed by earlier exploration:
#   Row A: hash_guest | ... | arr_date[8] | nights[9] | ... | created_on[14]
#   Row B: None | ... | dep_date[8] | adults[9] | ... | rate[11]
# ---------------------------------------------------------------------------

def parse_cancelled(path):
    rows = load_wb_rows(path)
    records = []
    i = 0
    while i < len(rows):
        row = rows[i]
        if is_hash(row[0] if len(row) > 0 else None):
            row_b = None
            for j in range(i + 1, min(i + 6, len(rows))):
                r = rows[j]
                if r[0] is None and len(r) > 9 and r[9] is not None and '/' in str(r[9]):
                    row_b = r; break
            if row_b is not None:
                arr        = parse_date(row[8])   if len(row) > 8  else None
                created_on = parse_date(row[14])  if len(row) > 14 else None
                dep        = parse_date(row_b[8]) if len(row_b) > 8 else None
                adlt       = parse_adults(row_b[9]) if len(row_b) > 9 else None
                rate       = parse_rate(row_b[11]) if len(row_b) > 11 else None
                n          = row[9] if len(row) > 9 else None
                if arr:
                    try:    nights = int(n)
                    except: nights = 0
                    if nights == 0 and dep:
                        nights = max(0, (dep - arr).days)
                    we, wd = count_nights(arr, nights)
                    lead = (arr - created_on).days if created_on else np.nan
                    records.append({
                        'guest_hash': row[0],
                        'arr_date': arr,
                        'lead_time': lead,
                        'arrival_date_week_number': int(arr.isocalendar()[1]),
                        'stays_in_weekend_nights': we,
                        'stays_in_week_nights': wd,
                        'adults': adlt if adlt is not None else np.nan,
                        'is_repeated_guest': 0,
                        'previous_cancellations': 0,
                        'previous_bookings_not_canceled': 0,
                        'booking_changes': 0,
                        'days_in_waiting_list': 0,
                        'adr': rate if rate is not None else np.nan,
                        'total_of_special_requests': 0,
                        'is_canceled': 1,
                    })
        i += 1
    return records

# ---------------------------------------------------------------------------
# Parser: No-Shows (RES_037)
# ---------------------------------------------------------------------------

def parse_noshow(path):
    rows = load_wb_rows(path)
    records = []
    i = 0
    while i < len(rows):
        row = rows[i]
        hash_col = row[1] if len(row) > 1 else None
        if is_hash(hash_col):
            row_b = None
            for j in range(i + 1, min(i + 5, len(rows))):
                r = rows[j]
                if len(r) > 2 and r[2] and str(r[2]).startswith('MEC-F') and len(r) > 16 and r[16] is not None:
                    row_b = r; break
            if row_b is not None:
                arr  = parse_date(row[11]) if len(row) > 11 else None
                dep  = parse_date(row[13]) if len(row) > 13 else None
                n    = row[18] if len(row) > 18 else None
                adlt = parse_adults(row[20]) if len(row) > 20 else None
                rate = parse_rate(row_b[24]) if len(row_b) > 24 else None
                created_on = parse_date(row_b[16]) if len(row_b) > 16 else None
                if arr:
                    try:    nights = int(n)
                    except: nights = 0
                    if nights == 0 and dep:
                        nights = max(0, (dep - arr).days)
                    we, wd = count_nights(arr, nights)
                    lead = (arr - created_on).days if created_on else np.nan
                    records.append({
                        'guest_hash': hash_col,
                        'arr_date': arr,
                        'lead_time': lead,
                        'arrival_date_week_number': int(arr.isocalendar()[1]),
                        'stays_in_weekend_nights': we,
                        'stays_in_week_nights': wd,
                        'adults': adlt if adlt is not None else np.nan,
                        'is_repeated_guest': 0,
                        'previous_cancellations': 0,
                        'previous_bookings_not_canceled': 0,
                        'booking_changes': 0,
                        'days_in_waiting_list': 0,
                        'adr': rate if rate is not None else np.nan,
                        'total_of_special_requests': 0,
                        'is_canceled': 1,
                    })
        i += 1
    return records

# ---------------------------------------------------------------------------
# Parser: Completed Stays (RES_001)
# ---------------------------------------------------------------------------

def parse_arrivals_co(path):
    rows = load_wb_rows(path)
    STATUSES = {'CO', 'NS', 'CX', 'IH', 'DI', 'DO'}
    records = []
    pending1 = None

    for row in rows:
        col1 = row[1] if len(row) > 1 else None
        col7 = row[7] if len(row) > 7 else None

        if is_hash(col1) and len(row) > 4 and row[4] is not None:
            pending1 = row
        elif (col1 and str(col1).startswith('MEC-') and
              col7 and str(col7).strip() in STATUSES and pending1 is not None):
            if str(col7).strip() == 'CO':
                arr  = parse_date(pending1[4])
                dep  = parse_date(row[4])
                n    = pending1[7] if len(pending1) > 7 else None
                adlt = parse_adults(pending1[8]) if len(pending1) > 8 else None
                rate = parse_rate(row[12]) if len(row) > 12 else None
                if arr:
                    try:    nights = int(n)
                    except: nights = 0
                    if nights == 0 and dep:
                        nights = max(0, (dep - arr).days)
                    we, wd = count_nights(arr, nights)
                    records.append({
                        'guest_hash': pending1[1],
                        'arr_date': arr,
                        'lead_time': np.nan,
                        'arrival_date_week_number': int(arr.isocalendar()[1]),
                        'stays_in_weekend_nights': we,
                        'stays_in_week_nights': wd,
                        'adults': adlt if adlt is not None else np.nan,
                        'is_repeated_guest': 0,
                        'previous_cancellations': 0,
                        'previous_bookings_not_canceled': 0,
                        'booking_changes': 0,
                        'days_in_waiting_list': 0,
                        'adr': rate if rate is not None else np.nan,
                        'total_of_special_requests': 0,
                        'is_canceled': 0,
                    })
            pending1 = None

    return records

# ---------------------------------------------------------------------------
# Parser: Repeat Guests (RES_042)
# Returns set of guest hashes that are repeat guests
# ---------------------------------------------------------------------------

def parse_repeat_guests(path):
    rows = load_wb_rows(path)
    hashes = set()
    for row in rows:
        for cell in row:
            if is_hash(cell):
                hashes.add(str(cell))
    return hashes

# ---------------------------------------------------------------------------
# Parser: Special Requests / Preferences (RES_006)
# Returns dict: guest_hash -> count of preference rows
# ---------------------------------------------------------------------------

def parse_preferences(path):
    rows = load_wb_rows(path)
    prefs = {}
    for row in rows:
        # Find hash in any column, then count this row as a preference
        for cell in row:
            if is_hash(cell):
                h = str(cell)
                prefs[h] = prefs.get(h, 0) + 1
                break
    return prefs

# ---------------------------------------------------------------------------
# Parser: EnteredOnAndBy (RES_004) — created_on dates for completed stays
# Returns dict: guest_hash -> created_on datetime
# ---------------------------------------------------------------------------

def parse_entered_on(path):
    rows = load_wb_rows(path)
    created = {}
    for row in rows:
        if len(row) < 2: continue
        hash_val = row[0] if is_hash(row[0]) else (row[1] if len(row) > 1 and is_hash(row[1]) else None)
        if hash_val:
            # scan remaining cols for a date
            for cell in row[2:]:
                d = parse_date(cell)
                if d and d.year >= 2020:
                    created[str(hash_val)] = d
                    break
    return created

# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

print('=' * 65)
print('  Occupado — VdV Model Validation (Full Dataset)')
print('=' * 65)

# 1. Load model
print('\n[1] Loading model...')
with open(MODEL_PATH, 'rb') as f:
    model = pickle.load(f)
print(f'    Loaded: {MODEL_PATH}')

# 2. Parse all cancellation/no-show files
print('\n[2] Parsing cancellation files...')
cancelled_recs = []
for fname in [
    'RES_036_CancelledReservations (1).xlsx',
    'RES_036_CancelledReservations (2).xlsx',
]:
    path = rf'{ANON_DIR}\{fname}'
    recs = parse_cancelled(path)
    print(f'    {fname}: {len(recs)} records')
    cancelled_recs.extend(recs)

# Also check raw folder for file 3 (not in anonymized)
import os
raw_cxl3 = rf'{RAW_DIR}\RES_036_CancelledReservations (3).xlsx'
if os.path.exists(raw_cxl3):
    recs = parse_cancelled(raw_cxl3)
    print(f'    RES_036 (3) [raw]: {len(recs)} records')
    cancelled_recs.extend(recs)

print(f'    -> Total cancelled: {len(cancelled_recs)}')

# No-shows
print('\n[3] Parsing no-show files...')
noshow_recs = []
for fname in ['RES_037_NoShow (1).xlsx']:
    path = rf'{ANON_DIR}\{fname}'
    recs = parse_noshow(path)
    print(f'    {fname}: {len(recs)} records')
    noshow_recs.extend(recs)

raw_ns2 = rf'{RAW_DIR}\RES_037_NoShow (2).xlsx'
if os.path.exists(raw_ns2):
    recs = parse_noshow(raw_ns2)
    print(f'    RES_037_NoShow (2) [raw]: {len(recs)} records')
    noshow_recs.extend(recs)

print(f'    -> Total no-shows: {len(noshow_recs)}')

# 3. Parse completed stays (first 3 arrival files)
print('\n[4] Parsing completed stays (first 3 arrival files)...')
completed_recs = []
for fname in [
    'RES_001_ArrivalDetailed.xlsx',
    'RES_001_ArrivalDetailed (1).xlsx',
]:
    path = rf'{ANON_DIR}\{fname}'
    recs = parse_arrivals_co(path)
    print(f'    {fname}: {len(recs)} records')
    completed_recs.extend(recs)

# Also try file 2 from raw if needed
raw_arr2 = rf'{RAW_DIR}\RES_001_ArrivalDetailed (2).xlsx'
if os.path.exists(raw_arr2) and len(completed_recs) < 200:
    recs = parse_arrivals_co(raw_arr2)
    print(f'    RES_001 (2) [raw]: {len(recs)} records')
    completed_recs.extend(recs)

print(f'    -> Total completed stays: {len(completed_recs)}')

# 4. Load enrichment data
print('\n[5] Loading enrichment data...')

# Repeat guests
repeat_hashes = set()
for fname in ['RES_042_RepeatReservationsReport (1).xlsx', 'RES_042_RepeatReservationsReport (2).xlsx']:
    path = rf'{ANON_DIR}\{fname}'
    if os.path.exists(path):
        h = parse_repeat_guests(path)
        repeat_hashes.update(h)
print(f'    Repeat guest hashes: {len(repeat_hashes)}')

# Preferences / special requests
prefs = {}
pref_path = rf'{ANON_DIR}\RES_006_Preferences.xlsx'
if os.path.exists(pref_path):
    prefs = parse_preferences(pref_path)
print(f'    Preference records (guests with prefs): {len(prefs)}')

# Created-on dates for completed stays
entered = {}
for fname in ['RES_004_EnteredOnAndBy (1).xlsx']:
    path = rf'{ANON_DIR}\{fname}'
    if os.path.exists(path):
        e = parse_entered_on(path)
        entered.update(e)
print(f'    EnteredOnAndBy records: {len(entered)}')

# 5. Build combined DataFrame
print('\n[6] Building combined dataset...')
all_recs = cancelled_recs + noshow_recs + completed_recs
df = pd.DataFrame(all_recs)
print(f'    Total records before enrichment: {len(df)}')

# Apply repeat guest flag
df['is_repeated_guest'] = df['guest_hash'].apply(
    lambda h: 1 if str(h) in repeat_hashes else 0
)

# Apply special requests count (cap at 5 to match Kaggle scale)
df['total_of_special_requests'] = df['guest_hash'].apply(
    lambda h: min(prefs.get(str(h), 0), 5)
)

# Apply lead_time from entered-on dates for completed stays (where lead_time is NaN)
def enrich_lead_time(row):
    if not np.isnan(row['lead_time']):
        return row['lead_time']
    h = str(row['guest_hash'])
    if h in entered and row['arr_date'] is not None:
        lead = (row['arr_date'] - entered[h]).days
        if 0 <= lead <= 730:
            return lead
    return np.nan

df['lead_time'] = df.apply(enrich_lead_time, axis=1)

print(f'    Lead time known:  {df["lead_time"].notna().sum()} / {len(df)}')
print(f'    Lead time NaN:    {df["lead_time"].isna().sum()}')

# Impute remaining NaNs
lead_median = df['lead_time'].median()
if np.isnan(lead_median): lead_median = 68.0
df['lead_time'] = df['lead_time'].fillna(lead_median)
print(f'    Lead time median used for imputation: {lead_median:.0f} days')

adr_median = df['adr'].median()
if np.isnan(adr_median): adr_median = 150.0
df['adr'] = df['adr'].fillna(adr_median)

adults_median = df['adults'].median()
if np.isnan(adults_median): adults_median = 2.0
df['adults'] = df['adults'].fillna(adults_median)

# 6. Show feature availability summary
print('\n[7] Feature availability summary:')
feature_source = {
    'lead_time':                     'extracted (cancellations/no-shows) + imputed for completed stays',
    'arrival_date_week_number':      'fully extracted from arrival dates',
    'stays_in_weekend_nights':       'computed from arrival date + nights',
    'stays_in_week_nights':          'computed from arrival date + nights',
    'adults':                        'extracted from booking rows',
    'is_repeated_guest':             'enriched from RES_042 (repeat guest report)',
    'previous_cancellations':        'NOT AVAILABLE — defaulted to 0',
    'previous_bookings_not_canceled':'NOT AVAILABLE — defaulted to 0',
    'booking_changes':               'NOT AVAILABLE — defaulted to 0',
    'days_in_waiting_list':          'NOT AVAILABLE — defaulted to 0',
    'adr':                           'extracted from rate columns',
    'total_of_special_requests':     'enriched from RES_006 (preferences)',
}
for feat, src in feature_source.items():
    available = 'EXTRACTED' if 'NOT AVAILABLE' not in src else 'DEFAULT=0'
    print(f'    {feat:<38} [{available}]')

# 7. Run model
print('\n[8] Running model predictions...')
X = df[FEATURES].copy()
y_true = df['is_canceled'].values

proba = model.predict_proba(X)[:, 1]
y_pred = (proba >= 0.5).astype(int)

# 8. Metrics
print('\n' + '=' * 65)
print('  VALIDATION METRICS')
print('=' * 65)

acc  = accuracy_score(y_true, y_pred)
prec = precision_score(y_true, y_pred, zero_division=0)
rec  = recall_score(y_true, y_pred, zero_division=0)
auc  = roc_auc_score(y_true, proba)
cm   = confusion_matrix(y_true, y_pred)

n_total = len(df)
n_cxl   = int(y_true.sum())
n_co    = n_total - n_cxl

print(f'\n  Dataset breakdown:')
print(f'    Total records:     {n_total}')
print(f'    Cancellations+NS:  {n_cxl}  ({100*n_cxl/n_total:.1f}%)')
print(f'    Completed stays:   {n_co}   ({100*n_co/n_total:.1f}%)')

print(f'\n  Classification metrics (threshold = 50%):')
print(f'    Accuracy:          {acc:.3f}  ({acc*100:.1f}%)')
print(f'    Precision:         {prec:.3f}')
print(f'    Recall:            {rec:.3f}')
print(f'    AUC-ROC:           {auc:.3f}')

print(f'\n  Confusion matrix:')
print(f'                       Predicted Stay   Predicted Cancel')
print(f'    Actual Stay:       {cm[0,0]:<16}   {cm[0,1]}')
print(f'    Actual Cancel:     {cm[1,0]:<16}   {cm[1,1]}')

print(f'\n  Detailed classification report:')
print(classification_report(y_true, y_pred, target_names=['Completed', 'Cancelled'], digits=3))

# 9. Risk tier analysis
print('  Cancellation rate by risk tier:')
df['proba'] = proba
df['risk_tier'] = pd.cut(proba, bins=[0, 0.3, 0.6, 1.0], labels=['Low', 'Medium', 'High'])

for tier in ['Low', 'Medium', 'High']:
    sub = df[df['risk_tier'] == tier]
    if len(sub) == 0:
        print(f'    {tier:<8}: no records')
        continue
    cxl_rate = sub['is_canceled'].mean()
    avg_score = sub['proba'].mean() * 100
    print(f'    {tier:<8}: {len(sub):>4} bookings | actual cancel rate {cxl_rate*100:>5.1f}% | avg risk score {avg_score:>5.1f}%')

# 10. VdV statistics vs training data context
print('\n' + '=' * 65)
print('  VdV DATA STATISTICS vs TRAINING CONTEXT')
print('=' * 65)

df_cxl_only = df[df['is_canceled'] == 1]
df_co_only  = df[df['is_canceled'] == 0]

print(f'\n  VdV statistics:')
print(f'    Avg lead_time (cancellations):  {df_cxl_only["lead_time"].mean():.0f} days')
print(f'    Avg lead_time (completed):      {df_co_only["lead_time"].mean():.0f} days')
print(f'    Avg ADR (cancellations):        €{df_cxl_only["adr"].mean():.2f}')
print(f'    Avg ADR (completed):            €{df_co_only["adr"].mean():.2f}')
print(f'    Avg adults:                     {df["adults"].mean():.2f}')
print(f'    Avg weekend nights:             {df["stays_in_weekend_nights"].mean():.2f}')
print(f'    Avg weekday nights:             {df["stays_in_week_nights"].mean():.2f}')
print(f'    Repeat guest rate:              {df["is_repeated_guest"].mean()*100:.1f}%')
print(f'    Guests with special requests:   {(df["total_of_special_requests"]>0).mean()*100:.1f}%')
print(f'    VdV cancellation rate:          {y_true.mean()*100:.1f}%')

print(f'\n  Training data context (Kaggle - Portuguese city hotels):')
print(f'    Avg lead_time (all):            ~104 days')
print(f'    Avg ADR:                        ~102 EUR')
print(f'    Cancellation rate (Kaggle):     ~37%')
print(f'    Note: VdV is a Belgian conference/business hotel — different profile')

# 11. Score distribution
print('\n  Score distribution on VdV data:')
for threshold, label in [(0.0, '0-20%'), (0.2, '20-40%'), (0.4, '40-60%'), (0.6, '60-80%'), (0.8, '80-100%')]:
    upper = threshold + 0.2
    mask = (proba >= threshold) & (proba < upper)
    n = mask.sum()
    cxl_in_bin = y_true[mask].sum()
    print(f'    {label}: {n:>4} bookings ({100*n/len(df):>4.1f}%) — {cxl_in_bin} actual cancellations ({100*cxl_in_bin/max(n,1):.0f}%)')

print('\n' + '=' * 65)
print('  HONEST ASSESSMENT')
print('=' * 65)
print("""
  The model was retrained on Kaggle (Portuguese resort/city hotels,
  2015-2017) + a small VdV sample. It now runs on the full VdV dataset.

  Key caveats:
  1. 4 of 12 features are unavailable from Shiji exports and default to 0:
     previous_cancellations, previous_bookings_not_canceled,
     booking_changes, days_in_waiting_list.
     These are among the most predictive features in the Kaggle model.
  2. lead_time for completed stays is imputed with median (not extracted),
     because the Shiji arrival report doesn't include booking creation date.
  3. VdV is a Belgian conference/MICE hotel — different guest profile from
     Portuguese leisure hotels. The model may under-detect VdV-specific
     cancellation patterns.
  4. AUC-ROC is the most honest metric here: it measures ranking quality
     independent of threshold, and is robust to class imbalance.
  5. A high AUC (>0.75) with limited features would be encouraging.
     Anything above 0.70 on out-of-distribution hotel data is reasonable.
""")
