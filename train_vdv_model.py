"""
Train a VdV-specific cancellation risk model using only features
reliably available from Shiji PMS exports.

Features used (7):
  lead_time, arrival_date_week_number, stays_in_weekend_nights,
  stays_in_week_nights, adults, is_repeated_guest, adr

Output: occupado_model_vdv.pkl
"""
import os, re, pickle, warnings
import numpy as np
import pandas as pd
from datetime import datetime

warnings.filterwarnings('ignore')

VDV_DIR = 'VDV-Data'
FEATURES = [
    'arrival_date_week_number',
    'arrival_month',
    'arrival_day_of_week',
    'stays_in_weekend_nights', 'stays_in_week_nights',
    'is_repeated_guest'
]

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def parse_date(s):
    s = str(s).strip()[:10]
    for fmt in ('%d/%m/%Y', '%m/%d/%Y', '%Y-%m-%d'):
        try: return datetime.strptime(s, fmt)
        except: pass
    return None

def weekend_split(arrival, nights):
    if arrival is None or nights <= 0: return 0, max(nights, 0)
    wknd = sum(1 for d in range(int(nights))
               if (arrival + pd.Timedelta(days=d)).weekday() in (4, 5))
    return wknd, int(nights) - wknd

def safe_float(s):
    try: return float(str(s).replace('.','').replace(',','.').strip())
    except: return None

# ─────────────────────────────────────────────────────────────────────────────
# PARSE CANCELLATIONS (RES_036 x3 + RES_037 x2)
# ─────────────────────────────────────────────────────────────────────────────
def parse_cancellations():
    """
    RES_036 row structure (openpyxl, 0-indexed):
      Guest row:  [name, room_type, company, arr_date, nights, rate_plan, rate_amt, created_date, cxl_datetime, cxl_no]
      Sub-row:    [room_no, dep_date, adults/children, rate_amt, channel, agent, ...]
    RES_037 (no-shows) has a similar structure.
    """
    import openpyxl
    records = []
    files = [f for f in os.listdir(VDV_DIR)
             if f.startswith(('RES_036', 'RES_037')) and f.endswith('.xlsx')]
    print(f'Cancellation files: {files}')

    for fn in files:
        path = os.path.join(VDV_DIR, fn)
        wb = openpyxl.load_workbook(path, read_only=True)
        rows = list(wb.active.iter_rows(values_only=True))
        wb.close()
        file_count = 0

        # Exact column map (verified via openpyxl debug):
        # Guest row: col[8]=arrival, col[9]=nights, col[13]=rate_amt, col[14]=created
        # Sub-row:   col[9]=adults/children
        for i, row in enumerate(rows):
            if i < 7: continue
            if not row or len(row) < 15: continue
            c8  = str(row[8]).strip()  if row[8]  is not None else ''
            c9  = str(row[9]).strip()  if row[9]  is not None else ''
            c13 = str(row[13]).strip() if row[13] is not None else ''
            c14 = str(row[14]).strip() if row[14] is not None else ''

            # Identify guest row: col[8] is dd/mm/yyyy, col[9] is digit
            if not re.match(r'\d{2}/\d{2}/\d{4}$', c8): continue
            if not c9.isdigit(): continue

            arr     = parse_date(c8)
            nights  = int(c9)
            rate    = safe_float(c13)
            created = parse_date(c14)
            if arr is None: continue

            # Adults from sub-row col[9] which has "x/y" format
            adults = 1
            for j in range(i + 1, min(i + 5, len(rows))):
                sub = rows[j]
                if not sub or len(sub) < 10: continue
                v = str(sub[9]).strip() if sub[9] is not None else ''
                if '/' in v:
                    parts = v.split('/')
                    if len(parts) == 2 and all(p.strip().isdigit() for p in parts):
                        a = int(parts[0].strip())
                        if 1 <= a <= 10: adults = a
                break

            lead = max(0, (arr - created).days) if created else 25
            adr  = rate / max(nights, 1) if rate and nights > 0 else rate
            wknd, wkday = weekend_split(arr, nights)

            records.append({
                'arrival': arr, 'nights': nights, 'adults': adults,
                'lead_time': lead,
                'arrival_date_week_number': int(arr.isocalendar()[1]),
                'arrival_month': arr.month,
                'arrival_day_of_week': arr.weekday(),
                'stays_in_weekend_nights': wknd,
                'stays_in_week_nights': wkday,
                'adr': adr,
                'is_repeated_guest': 0,
                'is_canceled': 1,
                'source': fn
            })
            file_count += 1

        print(f'  {fn}: {file_count:,} records')

    if not records:
        print('  WARNING: no cancellation records parsed')
        return pd.DataFrame(columns=['lead_time','arrival_date_week_number',
            'stays_in_weekend_nights','stays_in_week_nights','adults',
            'is_repeated_guest','adr','is_canceled','source','arrival','nights'])
    df = pd.DataFrame(records)
    df = df[df['lead_time'] < 730]
    print(f'  Cancellations parsed: {len(df):,}')
    return df


# ─────────────────────────────────────────────────────────────────────────────
# PARSE COMPLETED STAYS (RES_001 x10)
# ─────────────────────────────────────────────────────────────────────────────
def parse_stays():
    import openpyxl
    records = []
    files = sorted([f for f in os.listdir(VDV_DIR)
                    if f.startswith('RES_001') and f.endswith('.xlsx')])
    print(f'Arrival files: {len(files)}')

    for fn in files:
        path = os.path.join(VDV_DIR, fn)
        try:
            wb = openpyxl.load_workbook(path, read_only=True)
            rows = list(wb.active.iter_rows(values_only=True))
            wb.close()
        except Exception as e:
            print(f'  Skip {fn}: {e}'); continue

        file_records = 0
        for i, row in enumerate(rows):
            if i < 10: continue
            if not row or row[0] is None: continue
            cols = [str(c).strip() if c is not None else '' for c in row]
            if len(cols) < 6: continue

            arr = None; nights = None; adults = 1; rate = None

            # Find arrival datetime (has time component)
            for ci in range(len(cols)):
                if '/' in cols[ci] and ':' in cols[ci]:
                    d = parse_date(cols[ci])
                    if d and 2020 <= d.year <= 2027:
                        arr = d; break

            # Nights: digit 1-30
            for ci in range(len(cols)):
                v = cols[ci].split('.')[0]
                if v.isdigit() and 1 <= int(v) <= 30:
                    nights = int(v); break

            # Adults from "x/y"
            for ci in range(len(cols)):
                if '/' in cols[ci]:
                    parts = cols[ci].split('/')
                    if len(parts) == 2 and all(p.strip().isdigit() for p in parts):
                        a = int(parts[0].strip())
                        if 1 <= a <= 10: adults = a; break

            # Rate from "EUR" value
            for ci in range(len(cols)):
                if 'EUR' in cols[ci]:
                    r = safe_float(cols[ci].replace('EUR', ''))
                    if r and 20 < r < 10000: rate = r; break

            if arr is None or nights is None: continue

            adr = rate / max(nights, 1) if rate else None
            wknd, wkday = weekend_split(arr, nights)

            records.append({
                'arrival': arr, 'nights': nights, 'adults': adults,
                'lead_time': 25,  # median — not available in RES_001
                'arrival_date_week_number': int(arr.isocalendar()[1]),
                'arrival_month': arr.month,
                'arrival_day_of_week': arr.weekday(),
                'stays_in_weekend_nights': wknd,
                'stays_in_week_nights': wkday,
                'adr': adr,
                'is_repeated_guest': 0,
                'is_canceled': 0,
                'source': fn
            })
            file_records += 1

        print(f'  {fn}: {file_records:,} stays')

    df = pd.DataFrame(records)
    print(f'  Completed stays total: {len(df):,}')
    return df


# ─────────────────────────────────────────────────────────────────────────────
# ENRICH WITH REPEAT GUESTS (RES_042)
# ─────────────────────────────────────────────────────────────────────────────
def enrich_repeat_guests(df):
    import openpyxl
    path = os.path.join(VDV_DIR, 'RES_042_RepeatReservationsReport (1).xlsx')
    if not os.path.exists(path): return df
    wb = openpyxl.load_workbook(path, read_only=True)
    rows = list(wb.active.iter_rows(values_only=True))
    wb.close()
    repeat_dates = set()
    for row in rows:
        if not row or row[0] is None: continue
        col4 = row[4] if len(row) > 4 else None
        if col4 and '/' in str(col4):
            d = parse_date(str(col4))
            if d: repeat_dates.add(d.strftime('%Y-%m-%d'))
    df['is_repeated_guest'] = df['arrival'].apply(
        lambda x: 1 if x.strftime('%Y-%m-%d') in repeat_dates else 0
    )
    print(f'  Repeat guests marked: {df["is_repeated_guest"].sum():,}')
    return df


# ─────────────────────────────────────────────────────────────────────────────
# BUILD DATASET
# ─────────────────────────────────────────────────────────────────────────────
print('='*60)
print('BUILDING VdV TRAINING DATASET')
print('='*60)

cancels = parse_cancellations()
stays   = parse_stays()
df = pd.concat([cancels, stays], ignore_index=True)
df = enrich_repeat_guests(df)

# Fill missing ADR with segment median
median_adr = df['adr'].median()
df['adr'] = df['adr'].fillna(median_adr)
df = df.dropna(subset=['lead_time', 'adr'])

print(f'\nFinal dataset: {len(df):,} records')
print(f'  Cancellations: {df["is_canceled"].sum():,} ({df["is_canceled"].mean():.1%})')
print(f'  Completed stays: {(df["is_canceled"]==0).sum():,}')
print(f'  Median ADR: €{median_adr:.0f}')
print(f'  Lead time: median {df["lead_time"].median():.0f}d, mean {df["lead_time"].mean():.0f}d')

X = df[FEATURES].apply(pd.to_numeric, errors='coerce').fillna(0).astype(float)
y = df['is_canceled'].astype(int)

# ─────────────────────────────────────────────────────────────────────────────
# TRAIN — XGBoost with class weight balancing
# ─────────────────────────────────────────────────────────────────────────────
from xgboost import XGBClassifier
from sklearn.model_selection import StratifiedKFold, cross_validate
from sklearn.metrics import (accuracy_score, precision_score, recall_score,
                             roc_auc_score, confusion_matrix)

# Class balance
neg, pos = (y==0).sum(), (y==1).sum()
scale_pos = neg / pos
print(f'\nClass ratio: {neg:,} stays / {pos:,} cancellations -> scale_pos_weight={scale_pos:.2f}')

model = XGBClassifier(
    n_estimators=300,
    max_depth=5,
    learning_rate=0.05,
    subsample=0.8,
    colsample_bytree=0.8,
    scale_pos_weight=scale_pos,
    eval_metric='auc',
    random_state=42,
    verbosity=0
)

# ── 5-fold cross-validation ──────────────────────────────────────────────────
print('\nRunning 5-fold cross-validation...')
cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
cv_results = cross_validate(model, X, y, cv=cv,
    scoring=['accuracy','precision','recall','roc_auc'],
    return_train_score=False)

print('\n=== CROSS-VALIDATION RESULTS (5-fold) ===')
print(f'  AUC-ROC:   {cv_results["test_roc_auc"].mean():.3f} ± {cv_results["test_roc_auc"].std():.3f}')
print(f'  Accuracy:  {cv_results["test_accuracy"].mean():.1%} ± {cv_results["test_accuracy"].std():.1%}')
print(f'  Precision: {cv_results["test_precision"].mean():.1%} ± {cv_results["test_precision"].std():.1%}')
print(f'  Recall:    {cv_results["test_recall"].mean():.1%} ± {cv_results["test_recall"].std():.1%}')

# ── Train final model on full dataset ────────────────────────────────────────
print('\nTraining final model on full dataset...')
model.fit(X, y)

# Final predictions for tier analysis
probs = model.predict_proba(X)[:, 1]
preds = (probs >= 0.5).astype(int)

print('\n=== FINAL MODEL — TRAINING SET METRICS ===')
print(f'  AUC-ROC:   {roc_auc_score(y, probs):.3f}')
print(f'  Accuracy:  {accuracy_score(y, preds):.1%}')
print(f'  Precision: {precision_score(y, preds):.1%}')
print(f'  Recall:    {recall_score(y, preds):.1%}')

# Tier analysis
df2 = df.copy()
df2['score'] = probs
df2['tier'] = pd.cut(probs, bins=[0, .4, .7, 1.0], labels=['Low', 'Medium', 'High'])
tier = df2.groupby('tier', observed=True)['is_canceled'].agg(['mean', 'count'])
print('\n=== ACTUAL CANCEL RATE BY RISK TIER (VdV data) ===')
for t, row in tier.iterrows():
    print(f'  {t:6s}: {row["mean"]:.0%}  ({int(row["count"]):,} bookings)')

# Feature importance
fi = pd.Series(model.feature_importances_, index=FEATURES).sort_values(ascending=False)
print('\n=== FEATURE IMPORTANCES ===')
for feat, imp in fi.items():
    print(f'  {feat:<35s} {imp:.3f}')

# ── Save model ────────────────────────────────────────────────────────────────
out_path = 'occupado_model_vdv.pkl'
with open(out_path, 'wb') as f:
    pickle.dump(model, f)
print(f'\nModel saved -> {out_path}')
print(f'Features: {FEATURES}')
print('\nDone!')
