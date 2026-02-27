# OCCUPADO AI - Dashboard
import pandas as pd
import pickle
import webbrowser
import os

# Load the AI model
with open("occupado_model.pkl", "rb") as f:
    model = pickle.load(f)

# Load the hotel data
df = pd.read_csv("hotel_bookings.csv")

# Pick the features
features = [
    "lead_time",
    "arrival_date_week_number",
    "stays_in_weekend_nights",
    "stays_in_week_nights",
    "adults",
    "is_repeated_guest",
    "previous_cancellations",
    "previous_bookings_not_canceled",
    "booking_changes",
    "days_in_waiting_list",
    "adr",
    "total_of_special_requests"
]

# Take the first 20 bookings
sample = df[features].head(20).fillna(0)

# Score every booking
scores = model.predict_proba(sample)[:, 1] * 100

# Build the HTML dashboard
rows = ""
for i, (_, booking) in enumerate(sample.iterrows()):
    score = scores[i]
    if score >= 70:
        badge = f'<span class="badge high">🔴 {score:.1f}%</span>'
        action = '<button class="btn dep">💳 Request Deposit</button>'
    elif score >= 40:
        badge = f'<span class="badge med">🟠 {score:.1f}%</span>'
        action = '<button class="btn rem">📧 Send Reminder</button>'
    else:
        badge = f'<span class="badge low">🟢 {score:.1f}%</span>'
        action = '<button class="btn mon">👁 Monitor</button>'

    rows += f"""
    <tr>
        <td>Booking {i+1}</td>
        <td>{int(booking['lead_time'])} days</td>
        <td>€{int(booking['adr'])}</td>
        <td>{'Yes' if booking['is_repeated_guest'] else 'No'}</td>
        <td>{int(booking['previous_cancellations'])}</td>
        <td>{badge}</td>
        <td>{action}</td>
    </tr>"""

html = f"""
<!DOCTYPE html>
<html>
<head>
<title>Occupado Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:wght@400;500&family=DM+Mono&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#070d0b; color:#e2ede8; font-family:'DM Sans',sans-serif; padding:40px; }}
h1 {{ font-family:'Syne',sans-serif; font-size:36px; font-weight:800; color:#00e5a0; margin-bottom:6px; }}
.sub {{ color:#4a6658; font-family:'DM Mono',monospace; font-size:13px; margin-bottom:32px; }}
table {{ width:100%; border-collapse:collapse; background:#0c1510; border-radius:16px; overflow:hidden; }}
th {{ background:#0f1f18; color:#4a6658; font-family:'DM Mono',monospace; font-size:11px; text-transform:uppercase; letter-spacing:1px; padding:14px 16px; text-align:left; border-bottom:1px solid rgba(255,255,255,0.05); }}
td {{ padding:14px 16px; font-size:13px; border-bottom:1px solid rgba(255,255,255,0.03); }}
tr:hover td {{ background:rgba(255,255,255,0.02); }}
.badge {{ padding:4px 12px; border-radius:20px; font-family:'DM Mono',monospace; font-size:12px; font-weight:500; }}
.high {{ background:rgba(255,69,96,0.15); color:#ff4560; border:1px solid rgba(255,69,96,0.3); }}
.med {{ background:rgba(255,179,64,0.15); color:#ffb340; border:1px solid rgba(255,179,64,0.3); }}
.low {{ background:rgba(0,229,160,0.15); color:#00e5a0; border:1px solid rgba(0,229,160,0.3); }}
.btn {{ padding:6px 14px; border-radius:8px; font-size:12px; font-weight:500; cursor:pointer; border:1px solid; background:transparent; font-family:'DM Sans',sans-serif; transition:all 0.2s; }}
.dep {{ color:#ff4560; border-color:rgba(255,69,96,0.3); }}
.dep:hover {{ background:rgba(255,69,96,0.1); }}
.rem {{ color:#ffb340; border-color:rgba(255,179,64,0.3); }}
.rem:hover {{ background:rgba(255,179,64,0.1); }}
.mon {{ color:#00e5a0; border-color:rgba(0,229,160,0.3); }}
.mon:hover {{ background:rgba(0,229,160,0.1); }}
.stats {{ display:grid; grid-template-columns:repeat(3,1fr); gap:16px; margin-bottom:32px; }}
.stat {{ background:#0c1510; border:1px solid rgba(0,229,160,0.12); border-radius:12px; padding:20px; }}
.stat-value {{ font-family:'Syne',sans-serif; font-size:36px; font-weight:800; line-height:1; }}
.stat-label {{ font-family:'DM Mono',monospace; font-size:11px; color:#4a6658; margin-top:6px; text-transform:uppercase; }}
</style>
</head>
<body>
<h1>Occupado</h1>
<div class="sub">AI Booking Intelligence · {len(sample)} bookings analysed · Model accuracy 80.7%</div>

<div class="stats">
    <div class="stat">
        <div class="stat-value" style="color:#ff4560">{sum(1 for s in scores if s >= 70)}</div>
        <div class="stat-label">High Risk Bookings</div>
    </div>
    <div class="stat">
        <div class="stat-value" style="color:#ffb340">{sum(1 for s in scores if 40 <= s < 70)}</div>
        <div class="stat-label">Medium Risk Bookings</div>
    </div>
    <div class="stat">
        <div class="stat-value" style="color:#00e5a0">{sum(1 for s in scores if s < 40)}</div>
        <div class="stat-label">Low Risk Bookings</div>
    </div>
</div>

<table>
<thead>
    <tr>
        <th>Booking</th>
        <th>Lead Time</th>
        <th>Room Rate</th>
        <th>Returning</th>
        <th>Past Cancels</th>
        <th>Risk Score</th>
        <th>Action</th>
    </tr>
</thead>
<tbody>
{rows}
</tbody>
</table>
</body>
</html>
"""

# Save and open in browser
with open("dashboard.html", "w", encoding="utf-8") as f:
    f.write(html)

webbrowser.open("file://" + os.path.abspath("dashboard.html"))
print("Dashboard opened in your browser!")
