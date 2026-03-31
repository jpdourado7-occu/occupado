"""One-time script: load VdV future bookings and push to Railway DB cache."""
import os, sys, json
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()

import psycopg2
from app import VDV_FUTURE_BOOKINGS, VDV_FUTURE_SCORES

print(f"Future bookings loaded: {len(VDV_FUTURE_BOOKINGS)}")
print(f"Scores: {len(VDV_FUTURE_SCORES)}")

if not VDV_FUTURE_BOOKINGS or not VDV_FUTURE_SCORES:
    print("ERROR: No data — make sure VDV-MEC files are present.")
    sys.exit(1)

conn = psycopg2.connect(os.environ["DATABASE_URL"])
cur  = conn.cursor()
b_ser = [{**b, "arr_date": b["arr_date"].isoformat()} for b in VDV_FUTURE_BOOKINGS]
cur.execute("DELETE FROM vdv_bookings_cache")
cur.execute(
    "INSERT INTO vdv_bookings_cache (bookings_json, scores_json) VALUES (%s, %s)",
    (json.dumps(b_ser), json.dumps(VDV_FUTURE_SCORES))
)
conn.commit()
cur.close()
conn.close()
print(f"Done — cached {len(VDV_FUTURE_BOOKINGS)} bookings to Railway DB.")
