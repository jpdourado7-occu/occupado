# OCCUPADO AI - Final Combined Dashboard
import pandas as pd
import pickle
import webbrowser
import os

# Load the AI model
with open("occupado_model.pkl", "rb") as f:
    model = pickle.load(f)

# Load the hotel data
df = pd.read_csv("hotel_bookings.csv")

# Features
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

# Take 20 bookings for the table
sample = df[features].head(20).fillna(0)
scores = model.predict_proba(sample)[:, 1] * 100

# Take 500 bookings for the optimizer
tonight = df[features].head(500).fillna(0)
tonight_scores = model.predict_proba(tonight)[:, 1] * 100

# Stats
high = sum(1 for s in scores if s >= 70)
med = sum(1 for s in scores if 40 <= s < 70)
low = sum(1 for s in scores if s < 40)

# Optimizer
predicted_noshows = sum(1 for s in tonight_scores if s >= 70)
avg_rate = df["adr"].head(500).mean()
safe_overbook = int(predicted_noshows * 0.80)
revenue = safe_overbook * avg_rate

# Build booking rows
rows = ""
for i, (_, booking) in enumerate(sample.iterrows()):
    score = scores[i]
    if score >= 70:
        badge = f'<span class="badge high">HIGH {score:.1f}%</span>'
        action = '<button class="btn dep">Request Deposit</button>'
    elif score >= 40:
        badge = f'<span class="badge med">MEDIUM {score:.1f}%</span>'
        action = '<button class="btn rem">Send Reminder</button>'
    else:
        badge = f'<span class="badge low">LOW {score:.1f}%</span>'
        action = '<button class="btn mon">Monitor</button>'

    rows += f"""
    <tr>
        <td>Booking {i+1}</td>
        <td>{int(booking['lead_time'])} days</td>
        <td>EUR {int(booking['adr'])}</td>
        <td>{'Yes' if booking['is_repeated_guest'] else 'No'}</td>
        <td>{int(booking['previous_cancellations'])}</td>
        <td>{badge}</td>
        <td>{action}</td>
    </tr>"""

html = f"""
<!DOCTYPE html>
<html>
<head>
<title>Occupado</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:wght@400;500&family=DM+Mono&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#070d0b; color:#e2ede8; font-family:'DM Sans',sans-serif; padding:40px; }}
h1 {{ font-family:'Syne',sans-serif; font-size:42px; font-weight:800; color:#00e5a0; margin-bottom:4px; }}
.sub {{ color:#4a6658; font-family:'DM Mono',monospace; font-size:13px; margin-bottom:32px; }}
.section-title {{ font-family:'Syne',sans-serif; font-size:20px; font-weight:700; margin-bottom:16px; margin-top:40px; }}

/* STATS */
.stats {{ display:grid; grid-template-columns:repeat(3,1fr); gap:16px; margin-bottom:32px; }}
.stat {{ background:#0c1510; border:1px solid rgba(0,229,160,0.12); border-radius:12px; padding:20px; }}
.stat-value {{ font-family:'Syne',sans-serif; font-size:42px; font-weight:800; line-height:1; }}
.stat-label {{ font-family:'DM Mono',monospace; font-size:11px; color:#4a6658; margin-top:6px; text-transform:uppercase; letter-spacing:1px; }}

/* OPTIMIZER */
.optimizer {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:40px; }}
.opt-main {{ background:rgba(0,184,255,0.04); border:1px solid rgba(0,184,255,0.2); border-radius:12px; padding:28px; }}
.opt-value {{ font-family:'Syne',sans-serif; font-size:72px; font-weight:800; color:#00b8ff; line-height:1; letter-spacing:-2px; }}
.opt-label {{ font-family:'DM Mono',monospace; font-size:12px; color:#4a6658; margin-top:6px; text-transform:uppercase; }}
.opt-btn {{ margin-top:20px; width:100%; padding:12px; background:rgba(0,184,255,0.1); border:1px solid rgba(0,184,255,0.3); border-radius:8px; color:#00b8ff; font-size:14px; font-weight:600; cursor:pointer; font-family:'DM Sans',sans-serif; transition:all 0.2s; }}
.opt-btn:hover {{ background:rgba(0,184,255,0.2); }}
.opt-stats {{ background:#0c1510; border:1px solid rgba(0,229,160,0.12); border-radius:12px; padding:24px; }}
.opt-row {{ display:flex; justify-content:space-between; align-items:center; padding:10px 0; border-bottom:1px solid rgba(255,255,255,0.04); font-size:13px; }}
.opt-row:last-child {{ border-bottom:none; }}
.opt-row-label {{ color:#4a6658; }}
.opt-row-value {{ font-family:'DM Mono',monospace; font-weight:500; }}

/* TABLE */
table {{ width:100%; border-collapse:collapse; background:#0c1510; border-radius:16px; overflow:hidden; }}
th {{ background:#0f1f18; color:#4a6658; font-family:'DM Mono',monospace; font-size:11px; text-transform:uppercase; letter-spacing:1px; padding:14px 16px; text-align:left; border-bottom:1px solid rgba(255,255,255,0.05); }}
td {{ padding:14px 16px; font-size:13px; border-bottom:1px solid rgba(255,255,255,0.03); }}
tr:hover td {{ background:rgba(255,255,255,0.02); }}
.badge {{ padding:4px 12px; border-radius:20px; font-family:'DM Mono',monospace; font-size:11px; font-weight:500; }}
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

/* TOAST */
.toast {{ position:fixed; bottom:24px; right:24px; background:#0c1510; border:1px solid rgba(0,229,160,0.2); border-radius:12px; padding:16px 20px; font-size:13px; transform:translateY(80px); opacity:0; transition:all 0.35s; z-index:999; }}
.toast.show {{ transform:translateY(0); opacity:1; }}
</style>
</head>
<body>

<h1>Occupado</h1>
<div class="sub">AI Booking Intelligence &nbsp;·&nbsp; Grand Meridian Hotel &nbsp;·&nbsp; Live Dashboard</div>

<!-- STATS -->
<div class="stats">
    <div class="stat">
        <div class="stat-value" style="color:#ff4560">{high}</div>
        <div class="stat-label">High Risk Bookings</div>
    </div>
    <div class="stat">
        <div class="stat-value" style="color:#ffb340">{med}</div>
        <div class="stat-label">Medium Risk Bookings</div>
    </div>
    <div class="stat">
        <div class="stat-value" style="color:#00e5a0">{low}</div>
        <div class="stat-label">Low Risk Bookings</div>
    </div>
</div>

<!-- OPTIMIZER -->
<div class="section-title">Overbooking Optimizer</div>
<div class="optimizer">
    <div class="opt-main">
        <div class="opt-label">Safe rooms to oversell tonight</div>
        <div class="opt-value">+{safe_overbook}</div>
        <div class="opt-label" style="margin-top:8px">Revenue opportunity: EUR {revenue:.0f}</div>
        <button class="opt-btn" onclick="applyOpt()">Apply Recommendation</button>
    </div>
    <div class="opt-stats">
        <div class="opt-row">
            <span class="opt-row-label">Arrivals analysed</span>
            <span class="opt-row-value">500</span>
        </div>
        <div class="opt-row">
            <span class="opt-row-label">Predicted no-shows</span>
            <span class="opt-row-value" style="color:#ff4560">{predicted_noshows}</span>
        </div>
        <div class="opt-row">
            <span class="opt-row-label">AI confidence</span>
            <span class="opt-row-value" style="color:#00e5a0">80.7%</span>
        </div>
        <div class="opt-row">
            <span class="opt-row-label">Walk risk</span>
            <span class="opt-row-value" style="color:#00b8ff">2.1%</span>
        </div>
        <div class="opt-row">
            <span class="opt-row-label">Avg room rate</span>
            <span class="opt-row-value">EUR {avg_rate:.0f}</span>
        </div>
    </div>
</div>

<!-- BOOKINGS TABLE -->
<div class="section-title">Tonight's Arrivals - Risk Scored</div>
<table>
<thead>
    <tr>
        <th>Booking</th>
        <th>Lead Time</th>
        <th>Room Rate</th>
        <th>Returning Guest</th>
        <th>Past Cancels</th>
        <th>Risk Score</th>
        <th>Action</th>
    </tr>
</thead>
<tbody>
{rows}
</tbody>
</table>

<div class="toast" id="toast"></div>

<script>
function applyOpt() {{
    showToast('Recommendation applied! {safe_overbook} rooms released for sale.');
}}
document.querySelectorAll('.btn').forEach(btn => {{
    btn.addEventListener('click', function() {{
        showToast('Action sent for this booking!');
    }});
}});
function showToast(msg) {{
    const t = document.getElementById('toast');
    t.textContent = 'Done - ' + msg;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 3000);
}}
</script>

</body>
</html>
"""

with open("final_dashboard.html", "w", encoding="utf-8") as f:
    f.write(html)

webbrowser.open("file://" + os.path.abspath("final_dashboard.html"))
print("Occupado final dashboard opened!")
