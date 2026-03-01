# OCCUPADO AI - Web Server with Login + CSV Upload + Booking Detail + Admin Panel + PDF Report
from flask import Flask, send_file, request, redirect, url_for, session
import pandas as pd
import pickle
import io
import json
from functools import wraps
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from datetime import datetime
import os
from dotenv import load_dotenv
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

load_dotenv()

app = Flask(__name__)
app.secret_key = "occupado-secret-2024"

def send_high_risk_alert(hotel_name, alert_email, booking_id, risk_score):
    if not alert_email:
        return
    message = Mail(
        from_email=os.environ.get('ALERT_FROM_EMAIL', 'team@occupado.co'),
        to_emails=alert_email,
        subject=f"⚠️ High Cancellation Risk — {hotel_name}",
        html_content=f"""
        <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;">
            <div style="background:#008000;color:white;padding:20px;border-radius:8px 8px 0 0;">
                <h2 style="margin:0">⚠️ High Cancellation Risk Detected</h2>
                <p style="margin:5px 0 0">{hotel_name}</p>
            </div>
            <div style="background:#f9f9f9;padding:20px;border-radius:0 0 8px 8px;border:1px solid #ddd;">
                <p><strong>Booking:</strong> {booking_id}</p>
                <p><strong>Risk Score:</strong> <span style="color:#cc0000;font-size:1.4em;font-weight:bold">{risk_score:.1f}%</span></p>
                <hr/>
                <p style="color:#666;font-size:0.9em;">Log in to your Occupado dashboard to view full AI reasoning and take action.</p>
                <a href="https://occupado.co/login" style="background:#008000;color:white;padding:10px 20px;text-decoration:none;border-radius:5px;display:inline-block;margin-top:10px;">View Dashboard →</a>
            </div>
        </div>
        """
    )
    try:
        sg = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
        sg.send(message)
        print(f"Alert sent to {alert_email} for {hotel_name}")
    except Exception as e:
        print(f"SendGrid error: {e}")

ADMIN_USER = "admin"
ADMIN_PASS = "joaoeliv7"

HOTELS = {
    "grandmeridian": {"password": "hotel123", "name": "Grand Meridian Hotel", "rooms": 200, "city": "Lisbon", "alert_email": ""},
    "scandic":       {"password": "hotel456", "name": "Scandic Stockholm",    "rooms": 350, "city": "Stockholm", "alert_email": ""},
    "demo":          {"password": "demo",      "name": "Demo Hotel",           "rooms": 100, "city": "Porto", "alert_email": ""},
}

with open("occupado_model.pkl", "rb") as f:
    model = pickle.load(f)

df = pd.read_csv("hotel_bookings.csv")

features = [
    "lead_time", "arrival_date_week_number", "stays_in_weekend_nights",
    "stays_in_week_nights", "adults", "is_repeated_guest",
    "previous_cancellations", "previous_bookings_not_canceled",
    "booking_changes", "days_in_waiting_list", "adr", "total_of_special_requests"
]

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "hotel" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") != "admin":
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated

def build_dashboard(hotel_name, sample, scores, tonight_scores, uploaded=False):
    high = sum(1 for s in scores if s >= 70)
    med  = sum(1 for s in scores if 40 <= s < 70)
    low  = sum(1 for s in scores if s < 40)

    avg_rate = sample["adr"].mean() if "adr" in sample.columns else df["adr"].mean()
    predicted_noshows = sum(1 for s in tonight_scores if s >= 70)
    safe_overbook = int(predicted_noshows * 0.80)
    revenue = safe_overbook * avg_rate

    bookings_data = []
    for _, booking in sample.iterrows():
        bookings_data.append({k: float(booking.get(k, 0)) for k in features})
    bookings_js = json.dumps(bookings_data)

    rows = ""
    for i, (_, booking) in enumerate(sample.iterrows()):
        score = scores[i]
        if score >= 70:
            badge  = f'<span class="badge high">HIGH {score:.1f}%</span>'
            action = '<button class="btn dep" onclick="event.stopPropagation()">Request Deposit</button>'
        elif score >= 40:
            badge  = f'<span class="badge med">MEDIUM {score:.1f}%</span>'
            action = '<button class="btn rem" onclick="event.stopPropagation()">Send Reminder</button>'
        else:
            badge  = f'<span class="badge low">LOW {score:.1f}%</span>'
            action = '<button class="btn mon" onclick="event.stopPropagation()">Monitor</button>'

        lead = int(booking.get("lead_time", 0))
        adr  = int(booking.get("adr", 0))
        rep  = "Yes" if booking.get("is_repeated_guest", 0) else "No"
        canc = int(booking.get("previous_cancellations", 0))

        rows += f"""<tr class="clickable-row" onclick="showDetail({i}, {score:.1f})">
            <td><span style="color:#008000;font-weight:600">Booking {i+1}</span> <span style="font-size:11px;color:#4a6648;font-family:'DM Mono',monospace">· click for details</span></td>
            <td>{lead} days</td><td>EUR {adr}</td><td>{rep}</td><td>{canc}</td>
            <td>{badge}</td><td>{action}</td>
        </tr>"""

    upload_banner = ""
    if uploaded:
        upload_banner = '<div class="upload-banner">📂 Your uploaded data is being analysed — navigate freely, your file stays loaded</div>'

    return f"""<!DOCTYPE html>
<html>
<head>
<title>Occupado — {hotel_name}</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:wght@400;500&family=DM+Mono&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#ffffff; color:#0a1a0a; font-family:'DM Sans',sans-serif; }}
.topbar {{ background:#008000; padding:16px 40px; display:flex; align-items:center; justify-content:space-between; }}
.topbar-logo {{ font-family:'Syne',sans-serif; font-size:22px; font-weight:800; color:#ffffff; }}
.topbar-hotel {{ font-family:'DM Mono',monospace; font-size:12px; color:rgba(255,255,255,0.8); }}
.topbar-right {{ display:flex; align-items:center; gap:10px; }}
.logout {{ padding:8px 18px; background:rgba(255,255,255,0.15); border:1px solid rgba(255,255,255,0.3); border-radius:8px; color:#ffffff; font-size:13px; font-weight:600; text-decoration:none; transition:all 0.2s; }}
.logout:hover {{ background:rgba(255,255,255,0.25); }}
.report-btn {{ padding:8px 18px; background:rgba(255,255,255,0.25); border:1px solid rgba(255,255,255,0.5); border-radius:8px; color:#ffffff; font-size:13px; font-weight:600; text-decoration:none; transition:all 0.2s; }}
.report-btn:hover {{ background:rgba(255,255,255,0.35); }}
.settings-btn {{ padding:8px 18px; background:rgba(255,255,255,0.15); border:1px solid rgba(255,255,255,0.3); border-radius:8px; color:#ffffff; font-size:13px; font-weight:600; text-decoration:none; transition:all 0.2s; }}
.settings-btn:hover {{ background:rgba(255,255,255,0.25); }}
.clear-btn {{ padding:8px 18px; background:rgba(255,69,96,0.3); border:1px solid rgba(255,69,96,0.5); border-radius:8px; color:#ffffff; font-size:13px; font-weight:600; text-decoration:none; transition:all 0.2s; }}
.clear-btn:hover {{ background:rgba(255,69,96,0.5); }}
.content {{ padding:40px; }}
.sub {{ color:#4a6648; font-family:'DM Mono',monospace; font-size:13px; margin-bottom:32px; }}
.section-title {{ font-family:'Syne',sans-serif; font-size:20px; font-weight:700; margin-bottom:16px; margin-top:40px; color:#0a1a0a; }}
.stats {{ display:grid; grid-template-columns:repeat(3,1fr); gap:16px; margin-bottom:32px; }}
.stat {{ background:#f5faf5; border:1px solid rgba(0,128,0,0.15); border-radius:12px; padding:20px; }}
.stat-value {{ font-family:'Syne',sans-serif; font-size:42px; font-weight:800; line-height:1; }}
.stat-label {{ font-family:'DM Mono',monospace; font-size:11px; color:#4a6648; margin-top:6px; text-transform:uppercase; letter-spacing:1px; }}
.optimizer {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:40px; }}
.opt-main {{ background:rgba(0,128,0,0.04); border:1px solid rgba(0,128,0,0.2); border-radius:12px; padding:28px; }}
.opt-value {{ font-family:'Syne',sans-serif; font-size:72px; font-weight:800; color:#008000; line-height:1; letter-spacing:-2px; }}
.opt-label {{ font-family:'DM Mono',monospace; font-size:12px; color:#4a6648; margin-top:6px; text-transform:uppercase; }}
.opt-btn {{ margin-top:20px; width:100%; padding:12px; background:#008000; border:none; border-radius:8px; color:#ffffff; font-size:14px; font-weight:600; cursor:pointer; font-family:'DM Sans',sans-serif; }}
.opt-btn:hover {{ background:#006600; }}
.opt-stats {{ background:#f5faf5; border:1px solid rgba(0,128,0,0.15); border-radius:12px; padding:24px; }}
.opt-row {{ display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid rgba(0,128,0,0.08); font-size:13px; }}
.opt-row:last-child {{ border-bottom:none; }}
.opt-row-label {{ color:#4a6648; }}
.opt-row-value {{ font-family:'DM Mono',monospace; font-weight:500; }}
table {{ width:100%; border-collapse:collapse; background:#f5faf5; border-radius:16px; overflow:hidden; border:1px solid rgba(0,128,0,0.15); }}
th {{ background:#008000; color:#ffffff; font-family:'DM Mono',monospace; font-size:11px; text-transform:uppercase; letter-spacing:1px; padding:14px 16px; text-align:left; }}
td {{ padding:14px 16px; font-size:13px; border-bottom:1px solid rgba(0,128,0,0.06); color:#0a1a0a; }}
.clickable-row {{ cursor:pointer; }}
.clickable-row:hover td {{ background:rgba(0,128,0,0.04); }}
.badge {{ padding:4px 12px; border-radius:20px; font-family:'DM Mono',monospace; font-size:11px; font-weight:500; }}
.high {{ background:rgba(255,69,96,0.1); color:#cc0000; border:1px solid rgba(255,69,96,0.3); }}
.med {{ background:rgba(255,179,64,0.1); color:#cc6600; border:1px solid rgba(255,179,64,0.3); }}
.low {{ background:rgba(0,128,0,0.1); color:#008000; border:1px solid rgba(0,128,0,0.3); }}
.btn {{ padding:6px 14px; border-radius:8px; font-size:12px; font-weight:500; cursor:pointer; border:1px solid; background:transparent; font-family:'DM Sans',sans-serif; }}
.dep {{ color:#cc0000; border-color:rgba(255,69,96,0.3); }}
.rem {{ color:#cc6600; border-color:rgba(255,179,64,0.3); }}
.mon {{ color:#008000; border-color:rgba(0,128,0,0.3); }}
.upload-zone {{ border:2px dashed rgba(0,128,0,0.3); border-radius:16px; padding:40px; text-align:center; background:#f5faf5; margin-bottom:32px; cursor:pointer; }}
.upload-zone-title {{ font-family:'Syne',sans-serif; font-size:18px; font-weight:700; color:#008000; margin-bottom:8px; }}
.upload-zone-sub {{ font-size:13px; color:#4a6648; margin-bottom:20px; }}
.upload-btn {{ padding:12px 28px; background:#008000; color:#ffffff; border:none; border-radius:10px; font-size:14px; font-weight:600; cursor:pointer; font-family:'DM Sans',sans-serif; }}
.upload-banner {{ background:rgba(0,128,0,0.08); border:1px solid rgba(0,128,0,0.2); border-radius:10px; padding:14px 20px; font-size:13px; color:#008000; margin-bottom:24px; font-weight:500; }}
.modal-overlay {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,0.5); z-index:1000; align-items:center; justify-content:center; }}
.modal-overlay.show {{ display:flex; }}
.modal {{ background:#ffffff; border-radius:20px; padding:40px; width:100%; max-width:560px; max-height:85vh; overflow-y:auto; position:relative; box-shadow:0 20px 60px rgba(0,0,0,0.2); }}
.modal-close {{ position:absolute; top:16px; right:20px; font-size:22px; cursor:pointer; color:#4a6648; background:none; border:none; }}
.modal-title {{ font-family:'Syne',sans-serif; font-size:22px; font-weight:800; margin-bottom:4px; }}
.modal-sub {{ font-family:'DM Mono',monospace; font-size:12px; color:#4a6648; margin-bottom:24px; }}
.score-display {{ font-family:'Syne',sans-serif; font-size:64px; font-weight:800; line-height:1; letter-spacing:-2px; margin-bottom:8px; }}
.score-bar-bg {{ height:10px; background:#f0f0f0; border-radius:5px; overflow:hidden; margin-bottom:12px; }}
.score-bar-fill {{ height:100%; border-radius:5px; transition:width 0.8s ease; }}
.score-verdict {{ font-size:14px; font-weight:600; padding:8px 16px; border-radius:8px; display:inline-block; margin-bottom:8px; }}
.reasons-title {{ font-family:'Syne',sans-serif; font-size:16px; font-weight:700; margin-bottom:12px; margin-top:24px; }}
.reason-item {{ display:flex; gap:12px; padding:12px; border-radius:10px; margin-bottom:8px; }}
.reason-dot {{ width:10px; height:10px; border-radius:50%; flex-shrink:0; margin-top:4px; }}
.reason-signal {{ font-size:13px; font-weight:600; margin-bottom:3px; }}
.reason-detail {{ font-size:12px; color:#4a6648; line-height:1.5; }}
.modal-action {{ margin-top:24px; width:100%; padding:14px; border:none; border-radius:10px; font-size:15px; font-weight:700; cursor:pointer; font-family:'DM Sans',sans-serif; color:#ffffff; }}
.toast {{ position:fixed; bottom:24px; right:24px; background:#008000; color:#ffffff; border-radius:12px; padding:16px 20px; font-size:13px; transform:translateY(80px); opacity:0; transition:all 0.35s; z-index:2000; }}
.toast.show {{ transform:translateY(0); opacity:1; }}
</style>
</head>
<body>
<div class="topbar">
    <div>
        <div class="topbar-logo">Occupado</div>
        <div class="topbar-hotel">{hotel_name} · AI Booking Intelligence</div>
    </div>
    <div class="topbar-right">
        {'<a href="/clear" class="clear-btn">🗑 Clear File</a>' if uploaded else ''}
        <a href="/settings" class="settings-btn">⚙️ Settings</a>
        <a href="/report" class="report-btn">📄 Download Report</a>
        <a href="/logout" class="logout">Sign Out</a>
    </div>
</div>
<div class="content">
<div class="sub">Live Dashboard · Updated just now · {len(sample)} bookings analysed</div>
{upload_banner}
<div class="section-title">Upload Your Booking Data</div>
<form method="POST" action="/upload" enctype="multipart/form-data">
    <div class="upload-zone" onclick="document.getElementById('csv-input').click()">
        <div class="upload-zone-title">📂 Drop your booking CSV here</div>
        <div class="upload-zone-sub">Export from your PMS and upload — Occupado scores every booking instantly</div>
        <input type="file" id="csv-input" name="csv_file" accept=".csv" style="display:none" onchange="this.form.submit()">
        <button type="button" class="upload-btn" onclick="event.stopPropagation();document.getElementById('csv-input').click()">Choose CSV File</button>
    </div>
</form>
<div class="stats">
    <div class="stat"><div class="stat-value" style="color:#cc0000">{high}</div><div class="stat-label">High Risk</div></div>
    <div class="stat"><div class="stat-value" style="color:#cc6600">{med}</div><div class="stat-label">Medium Risk</div></div>
    <div class="stat"><div class="stat-value" style="color:#008000">{low}</div><div class="stat-label">Low Risk</div></div>
</div>
<div class="section-title">Overbooking Optimizer</div>
<div class="optimizer">
    <div class="opt-main">
        <div class="opt-label">Safe rooms to oversell tonight</div>
        <div class="opt-value">+{safe_overbook}</div>
        <div class="opt-label" style="margin-top:8px">Revenue opportunity: EUR {revenue:.0f}</div>
        <button class="opt-btn" onclick="showToast('Recommendation applied! {safe_overbook} rooms released.')">Apply Recommendation</button>
    </div>
    <div class="opt-stats">
        <div class="opt-row"><span class="opt-row-label">Bookings analysed</span><span class="opt-row-value">{len(sample)}</span></div>
        <div class="opt-row"><span class="opt-row-label">Predicted no-shows</span><span class="opt-row-value" style="color:#cc0000">{predicted_noshows}</span></div>
        <div class="opt-row"><span class="opt-row-label">AI confidence</span><span class="opt-row-value" style="color:#008000">80.7%</span></div>
        <div class="opt-row"><span class="opt-row-label">Walk risk</span><span class="opt-row-value" style="color:#008000">2.1%</span></div>
        <div class="opt-row"><span class="opt-row-label">Avg room rate</span><span class="opt-row-value">EUR {avg_rate:.0f}</span></div>
    </div>
</div>
<div class="section-title">Bookings — Click any row for AI reasoning</div>
<table>
<thead><tr><th>Booking</th><th>Lead Time</th><th>Room Rate</th><th>Returning</th><th>Past Cancels</th><th>Risk Score</th><th>Action</th></tr></thead>
<tbody>{rows}</tbody>
</table>
</div>
<div class="modal-overlay" id="modal">
    <div class="modal">
        <button class="modal-close" onclick="closeModal()">✕</button>
        <div class="modal-title" id="modal-title">Booking Detail</div>
        <div class="modal-sub" id="modal-sub">AI Risk Analysis</div>
        <div class="score-display" id="modal-score">0%</div>
        <div class="score-bar-bg"><div class="score-bar-fill" id="modal-bar" style="width:0%"></div></div>
        <div class="score-verdict" id="modal-verdict"></div>
        <div class="reasons-title">Why the AI flagged this booking</div>
        <div id="modal-reasons"></div>
        <button class="modal-action" id="modal-action-btn" onclick="closeModal()">Close</button>
    </div>
</div>
<div class="toast" id="toast"></div>
<script>
const bookings = {bookings_js};
function showDetail(idx, score) {{
    const booking = bookings[idx];
    document.getElementById('modal-title').textContent = 'Booking ' + (idx+1) + ' — AI Analysis';
    document.getElementById('modal-sub').textContent = 'Lead time: ' + booking.lead_time + ' days · Room rate: EUR ' + booking.adr;
    document.getElementById('modal-score').textContent = score.toFixed(1) + '%';
    const bar = document.getElementById('modal-bar');
    const verdict = document.getElementById('modal-verdict');
    const actionBtn = document.getElementById('modal-action-btn');
    bar.style.width = score + '%';
    if (score >= 70) {{
        bar.style.background = '#cc0000';
        document.getElementById('modal-score').style.color = '#cc0000';
        verdict.textContent = 'HIGH RISK — Request deposit immediately';
        verdict.style.background = 'rgba(255,69,96,0.1)'; verdict.style.color = '#cc0000';
        actionBtn.style.background = '#cc0000'; actionBtn.textContent = 'Request Deposit Now';
    }} else if (score >= 40) {{
        bar.style.background = '#cc6600';
        document.getElementById('modal-score').style.color = '#cc6600';
        verdict.textContent = 'MEDIUM RISK — Send a reminder';
        verdict.style.background = 'rgba(255,179,64,0.1)'; verdict.style.color = '#cc6600';
        actionBtn.style.background = '#cc6600'; actionBtn.textContent = 'Send Reminder Email';
    }} else {{
        bar.style.background = '#008000';
        document.getElementById('modal-score').style.color = '#008000';
        verdict.textContent = 'LOW RISK — Monitor only';
        verdict.style.background = 'rgba(0,128,0,0.1)'; verdict.style.color = '#008000';
        actionBtn.style.background = '#008000'; actionBtn.textContent = 'Mark as Monitored';
    }}
    const reasons = [];
    if (booking.lead_time > 60) reasons.push({{signal:'Long lead time', detail: booking.lead_time+' days between booking and arrival — guests who book far in advance cancel more often.', impact:'high'}});
    else if (booking.lead_time < 7) reasons.push({{signal:'Short lead time', detail:'Only '+booking.lead_time+' days until arrival — last-minute bookings almost always show up.', impact:'low'}});
    else reasons.push({{signal:'Moderate lead time', detail: booking.lead_time+' days until arrival — moderate cancellation risk.', impact:'med'}});
    if (booking.previous_cancellations > 0) reasons.push({{signal:'Previous cancellations', detail:'This guest cancelled '+booking.previous_cancellations+' time(s) before — strongest predictor of future cancellations.', impact:'high'}});
    if (booking.is_repeated_guest === 1) reasons.push({{signal:'Returning guest', detail:'Loyal guest — returning guests cancel far less than first-time visitors.', impact:'low'}});
    else reasons.push({{signal:'First-time guest', detail:'No previous stay history — first-time guests have higher uncertainty.', impact:'med'}});
    if (booking.previous_bookings_not_canceled > 3) reasons.push({{signal:'Strong booking history', detail: booking.previous_bookings_not_canceled+' previous stays completed — highly reliable guest.', impact:'low'}});
    if (booking.total_of_special_requests >= 2) reasons.push({{signal:'Special requests made', detail: booking.total_of_special_requests+' special requests — invested in the stay.', impact:'low'}});
    else if (booking.total_of_special_requests === 0) reasons.push({{signal:'No special requests', detail:'Zero special requests — may not be fully committed to this booking.', impact:'med'}});
    if (booking.adr > 300) reasons.push({{signal:'High room rate', detail:'EUR '+booking.adr+' per night — expensive bookings sometimes cancelled when alternatives found.', impact:'med'}});
    const colors = {{high:'#cc0000',med:'#cc6600',low:'#008000'}};
    const bgs = {{high:'rgba(255,69,96,0.06)',med:'rgba(255,179,64,0.06)',low:'rgba(0,128,0,0.06)'}};
    document.getElementById('modal-reasons').innerHTML = reasons.map(r =>
        `<div class="reason-item" style="background:${{bgs[r.impact]}}">
            <div class="reason-dot" style="background:${{colors[r.impact]}}"></div>
            <div><div class="reason-signal">${{r.signal}}</div><div class="reason-detail">${{r.detail}}</div></div>
        </div>`).join('');
    document.getElementById('modal').classList.add('show');
}}
function closeModal() {{
    document.getElementById('modal').classList.remove('show');
    showToast('Action recorded!');
}}
function showToast(msg) {{
    const t = document.getElementById('toast');
    t.textContent = msg; t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 3000);
}}
document.getElementById('modal').addEventListener('click', function(e) {{
    if (e.target === this) closeModal();
}});
</script>
</body>
</html>"""

@app.route("/")
def home():
    return send_file("landing.html")

@app.route("/landing")
def landing():
    return send_file("landing.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        username = request.form.get("username", "").lower().strip()
        password = request.form.get("password", "").strip()
        if username in HOTELS and HOTELS[username]["password"] == password:
            session["hotel"] = username
            session["hotel_name"] = HOTELS[username]["name"]
            return redirect(url_for("dashboard"))
        else:
            error = "Invalid username or password. Please try again."
    return f"""<!DOCTYPE html>
<html>
<head>
<title>Occupado — Login</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:wght@400;500&family=DM+Mono&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#f5faf5; color:#0a1a0a; font-family:'DM Sans',sans-serif; min-height:100vh; display:flex; align-items:center; justify-content:center; }}
.login-box {{ background:#ffffff; border:1px solid rgba(0,128,0,0.15); border-radius:20px; padding:48px; width:100%; max-width:400px; box-shadow:0 4px 24px rgba(0,128,0,0.08); }}
.logo {{ font-family:'Syne',sans-serif; font-size:28px; font-weight:800; color:#008000; margin-bottom:8px; }}
.tagline {{ font-family:'DM Mono',monospace; font-size:12px; color:#4a6648; margin-bottom:40px; }}
label {{ font-size:13px; font-weight:500; color:#4a6648; display:block; margin-bottom:6px; font-family:'DM Mono',monospace; text-transform:uppercase; letter-spacing:0.5px; }}
input {{ width:100%; padding:12px 16px; background:#f5faf5; border:1px solid rgba(0,128,0,0.2); border-radius:10px; font-size:14px; font-family:'DM Sans',sans-serif; color:#0a1a0a; outline:none; margin-bottom:20px; transition:border-color 0.2s; }}
input:focus {{ border-color:#008000; background:#ffffff; }}
.btn {{ width:100%; padding:14px; background:#008000; color:#ffffff; border:none; border-radius:10px; font-size:15px; font-weight:700; cursor:pointer; font-family:'DM Sans',sans-serif; transition:all 0.2s; margin-top:4px; }}
.btn:hover {{ background:#006600; transform:translateY(-1px); box-shadow:0 8px 20px rgba(0,128,0,0.25); }}
.error {{ background:rgba(255,69,96,0.08); border:1px solid rgba(255,69,96,0.2); border-radius:8px; padding:12px 16px; font-size:13px; color:#cc0000; margin-bottom:20px; }}
.demo-hint {{ margin-top:24px; padding:14px; background:#f5faf5; border-radius:10px; font-size:12px; color:#4a6648; font-family:'DM Mono',monospace; text-align:center; border:1px solid rgba(0,128,0,0.1); }}
</style>
</head>
<body>
<div class="login-box">
    <div class="logo">Occupado</div>
    <div class="tagline">AI Booking Intelligence · Secure Access</div>
    {"<div class='error'>" + error + "</div>" if error else ""}
    <form method="POST">
        <label>Hotel Username</label>
        <input type="text" name="username" placeholder="your hotel username" required>
        <label>Password</label>
        <input type="password" name="password" placeholder="••••••••" required>
        <button type="submit" class="btn">Sign In →</button>
    </form>
    <div class="demo-hint">Demo access: username <strong>demo</strong> · password <strong>demo</strong></div>
</div>
</body>
</html>"""

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    hotel_name = session.get("hotel_name", "Your Hotel")

    # Check if there's uploaded data in the session
    uploaded_data = session.get("uploaded_csv")
    if uploaded_data:
        sample = pd.DataFrame(uploaded_data)
        for feat in features:
            if feat not in sample.columns:
                sample[feat] = 0
        sample = sample[features].head(20).fillna(0)
        tonight_sample = pd.DataFrame(uploaded_data)[features].head(500).fillna(0)
        uploaded = True
    else:
        sample = df[features].head(20).fillna(0)
        tonight_sample = df[features].head(500).fillna(0)
        uploaded = False

    scores = model.predict_proba(sample)[:, 1] * 100
    tonight_scores = model.predict_proba(tonight_sample)[:, 1] * 100

    hotel_config = HOTELS.get(session['hotel'], {})
    alert_email = hotel_config.get('alert_email', '')
    for i, score in enumerate(scores):
        if score >= 70:
            send_high_risk_alert(hotel_name, alert_email, f"Booking {i+1}", score)

    return build_dashboard(hotel_name, sample, scores, tonight_scores, uploaded=uploaded)

@app.route("/clear")
@login_required
def clear_upload():
    session.pop("uploaded_csv", None)
    return redirect(url_for("dashboard"))

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    hotel = session['hotel']
    hotel_name = session.get("hotel_name", "Your Hotel")
    message = None

    if request.method == "POST":
        new_email = request.form.get("alert_email", "").strip()
        HOTELS[hotel]['alert_email'] = new_email
        print(f"Alert email set to: {new_email} for {hotel}")
        message = "Settings saved! You'll now receive alerts at " + new_email if new_email else "Alert email cleared."

    current_email = HOTELS[hotel].get('alert_email', '')

    return f"""<!DOCTYPE html>
<html>
<head>
<title>Occupado — Settings</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:wght@400;500&family=DM+Mono&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#ffffff; color:#0a1a0a; font-family:'DM Sans',sans-serif; }}
.topbar {{ background:#008000; padding:16px 40px; display:flex; align-items:center; justify-content:space-between; }}
.topbar-logo {{ font-family:'Syne',sans-serif; font-size:22px; font-weight:800; color:#ffffff; }}
.topbar-hotel {{ font-family:'DM Mono',monospace; font-size:12px; color:rgba(255,255,255,0.8); }}
.topbar-right {{ display:flex; align-items:center; gap:10px; }}
.nav-btn {{ padding:8px 18px; background:rgba(255,255,255,0.15); border:1px solid rgba(255,255,255,0.3); border-radius:8px; color:#ffffff; font-size:13px; font-weight:600; text-decoration:none; }}
.nav-btn:hover {{ background:rgba(255,255,255,0.25); }}
.content {{ padding:40px; max-width:600px; }}
.page-title {{ font-family:'Syne',sans-serif; font-size:32px; font-weight:800; margin-bottom:8px; }}
.page-sub {{ font-family:'DM Mono',monospace; font-size:12px; color:#4a6648; margin-bottom:40px; }}
.card {{ background:#f5faf5; border:1px solid rgba(0,128,0,0.15); border-radius:16px; padding:32px; margin-bottom:24px; }}
.card-title {{ font-family:'Syne',sans-serif; font-size:18px; font-weight:700; margin-bottom:6px; }}
.card-sub {{ font-size:13px; color:#4a6648; margin-bottom:24px; }}
label {{ font-size:12px; font-weight:500; color:#4a6648; display:block; margin-bottom:8px; font-family:'DM Mono',monospace; text-transform:uppercase; letter-spacing:0.5px; }}
input {{ width:100%; padding:12px 16px; background:#ffffff; border:1px solid rgba(0,128,0,0.2); border-radius:10px; font-size:14px; font-family:'DM Sans',sans-serif; color:#0a1a0a; outline:none; margin-bottom:16px; }}
input:focus {{ border-color:#008000; }}
.save-btn {{ padding:12px 28px; background:#008000; color:#ffffff; border:none; border-radius:10px; font-size:14px; font-weight:600; cursor:pointer; font-family:'DM Sans',sans-serif; }}
.save-btn:hover {{ background:#006600; }}
.success {{ background:rgba(0,128,0,0.08); border:1px solid rgba(0,128,0,0.2); border-radius:10px; padding:14px 20px; font-size:13px; color:#008000; margin-bottom:24px; font-weight:500; }}
.hint {{ font-size:12px; color:#4a6648; margin-top:-8px; margin-bottom:16px; font-family:'DM Mono',monospace; }}
</style>
</head>
<body>
<div class="topbar">
    <div>
        <div class="topbar-logo">Occupado</div>
        <div class="topbar-hotel">{hotel_name} · Settings</div>
    </div>
    <div class="topbar-right">
        <a href="/dashboard" class="nav-btn">← Back to Dashboard</a>
        <a href="/logout" class="nav-btn">Sign Out</a>
    </div>
</div>
<div class="content">
    <div class="page-title">Settings</div>
    <div class="page-sub">Configure your alert preferences</div>
    {"<div class='success'>✅ " + message + "</div>" if message else ""}
    <div class="card">
        <div class="card-title">🔔 High Risk Email Alerts</div>
        <div class="card-sub">Get an email instantly when a booking hits more than 70% cancellation risk.</div>
        <form method="POST">
            <label>Alert Email Address</label>
            <input type="email" name="alert_email" value="{current_email}" placeholder="revenue@yourhotel.com">
            <div class="hint">Leave blank to disable alerts.</div>
            <button type="submit" class="save-btn">Save Settings →</button>
        </form>
    </div>
</div>
</body>
</html>"""

@app.route("/upload", methods=["POST"])
@login_required
def upload():
    hotel_name = session.get("hotel_name", "Your Hotel")
    if "csv_file" not in request.files:
        return redirect(url_for("dashboard"))
    file = request.files["csv_file"]
    if file.filename == "":
        return redirect(url_for("dashboard"))
    try:
        content = file.read().decode("utf-8")
        uploaded_df = pd.read_csv(io.StringIO(content))
        for feat in features:
            if feat not in uploaded_df.columns:
                uploaded_df[feat] = 0

        # Save uploaded data to session so it persists across navigation
        session["uploaded_csv"] = uploaded_df[features].head(500).fillna(0).to_dict(orient="records")

        sample = uploaded_df[features].head(20).fillna(0)
        scores = model.predict_proba(sample)[:, 1] * 100
        tonight_scores = model.predict_proba(uploaded_df[features].head(500).fillna(0))[:, 1] * 100

        hotel_config = HOTELS.get(session['hotel'], {})
        alert_email = hotel_config.get('alert_email', '')
        for i, score in enumerate(scores):
            if score >= 70:
                send_high_risk_alert(hotel_name, alert_email, f"Booking {i+1}", score)

        return build_dashboard(hotel_name, sample, scores, tonight_scores, uploaded=True)
    except Exception as e:
        print(f"Upload error: {e}")
        return redirect(url_for("dashboard"))

@app.route("/report")
@login_required
def download_report():
    hotel_name = session.get("hotel_name", "Your Hotel")
    sample = df[features].head(20).fillna(0)
    scores = model.predict_proba(sample)[:, 1] * 100
    tonight_scores = model.predict_proba(df[features].head(500).fillna(0))[:, 1] * 100

    high_bookings = [(i, scores[i], sample.iloc[i]) for i in range(len(scores)) if scores[i] >= 70]
    med_bookings  = [(i, scores[i], sample.iloc[i]) for i in range(len(scores)) if 40 <= scores[i] < 70]
    low_bookings  = [(i, scores[i], sample.iloc[i]) for i in range(len(scores)) if scores[i] < 40]

    avg_rate = sample["adr"].mean()
    predicted_noshows = sum(1 for s in tonight_scores if s >= 70)
    safe_overbook = int(predicted_noshows * 0.80)
    revenue = safe_overbook * avg_rate

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
        rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)

    green = colors.HexColor("#008000")
    darkgreen = colors.HexColor("#006600")
    red = colors.HexColor("#cc0000")
    orange = colors.HexColor("#cc6600")
    lightgreen_bg = colors.HexColor("#f5faf5")

    title_style = ParagraphStyle('title', fontSize=28, fontName='Helvetica-Bold', textColor=green, spaceAfter=4)
    sub_style = ParagraphStyle('sub', fontSize=11, fontName='Helvetica', textColor=colors.HexColor("#4a6648"), spaceAfter=20)
    section_style = ParagraphStyle('section', fontSize=14, fontName='Helvetica-Bold', textColor=darkgreen, spaceBefore=20, spaceAfter=10)
    body_style = ParagraphStyle('body', fontSize=10, fontName='Helvetica', textColor=colors.HexColor("#0a1a0a"), spaceAfter=6)

    story = []
    story.append(Paragraph("Occupado", title_style))
    story.append(Paragraph(f"Weekly Risk Report · {hotel_name} · {datetime.now().strftime('%d %B %Y')}", sub_style))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("Weekly Summary", section_style))
    summary_data = [
        ["Metric", "Value"],
        ["Bookings Analysed", str(len(sample))],
        ["High Risk Bookings", str(len(high_bookings))],
        ["Medium Risk Bookings", str(len(med_bookings))],
        ["Low Risk Bookings", str(len(low_bookings))],
        ["Safe Rooms to Oversell", f"+{safe_overbook}"],
        ["Revenue Opportunity", f"EUR {revenue:.0f}"],
        ["AI Model Accuracy", "80.7%"],
    ]
    summary_table = Table(summary_data, colWidths=[10*cm, 7*cm])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), green),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, lightgreen_bg]),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#008000")),
        ('PADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 0.5*cm))

    if high_bookings:
        story.append(Paragraph("High Risk Bookings — Immediate Action Required", section_style))
        high_data = [["Booking", "Risk Score", "Lead Time", "Room Rate", "Action"]]
        for idx, score, booking in high_bookings:
            high_data.append([f"Booking {idx+1}", f"{score:.1f}%", f"{int(booking.get('lead_time',0))} days", f"EUR {int(booking.get('adr',0))}", "Request Deposit"])
        high_table = Table(high_data, colWidths=[4*cm, 3*cm, 3*cm, 3*cm, 4*cm])
        high_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), red),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 9),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#fff5f5")]),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#ffcccc")),
            ('PADDING', (0,0), (-1,-1), 7),
        ]))
        story.append(high_table)
        story.append(Spacer(1, 0.4*cm))

    if med_bookings:
        story.append(Paragraph("Medium Risk Bookings — Send Reminders", section_style))
        med_data = [["Booking", "Risk Score", "Lead Time", "Room Rate", "Action"]]
        for idx, score, booking in med_bookings:
            med_data.append([f"Booking {idx+1}", f"{score:.1f}%", f"{int(booking.get('lead_time',0))} days", f"EUR {int(booking.get('adr',0))}", "Send Reminder"])
        med_table = Table(med_data, colWidths=[4*cm, 3*cm, 3*cm, 3*cm, 4*cm])
        med_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), orange),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 9),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#fffaf0")]),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#ffcc88")),
            ('PADDING', (0,0), (-1,-1), 7),
        ]))
        story.append(med_table)
        story.append(Spacer(1, 0.4*cm))

    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph(f"Generated by Occupado AI · occupado.co · {datetime.now().strftime('%d/%m/%Y %H:%M')}", sub_style))
    story.append(Paragraph("This report is confidential and intended for revenue management purposes only.", body_style))

    doc.build(story)
    buffer.seek(0)

    filename = f"occupado-report-{datetime.now().strftime('%Y-%m-%d')}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype="application/pdf")

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = ""
    if request.method == "POST":
        if request.form.get("username") == ADMIN_USER and request.form.get("password") == ADMIN_PASS:
            session["role"] = "admin"
            return redirect(url_for("admin_panel"))
        error = "Invalid admin credentials."
    return f"""<!DOCTYPE html>
<html>
<head>
<title>Occupado — Admin</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:wght@400;500&family=DM+Mono&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#0a1a0a; color:#e2ede8; font-family:'DM Sans',sans-serif; min-height:100vh; display:flex; align-items:center; justify-content:center; }}
.box {{ background:#0f2010; border:1px solid rgba(0,128,0,0.3); border-radius:20px; padding:48px; width:100%; max-width:400px; box-shadow:0 4px 24px rgba(0,0,0,0.4); }}
.logo {{ font-family:'Syne',sans-serif; font-size:28px; font-weight:800; color:#008000; margin-bottom:4px; }}
.tag {{ font-family:'DM Mono',monospace; font-size:11px; color:#4a6648; margin-bottom:40px; text-transform:uppercase; letter-spacing:1px; }}
label {{ font-size:12px; font-weight:500; color:#4a6648; display:block; margin-bottom:6px; font-family:'DM Mono',monospace; text-transform:uppercase; letter-spacing:0.5px; }}
input {{ width:100%; padding:12px 16px; background:rgba(0,128,0,0.08); border:1px solid rgba(0,128,0,0.2); border-radius:10px; font-size:14px; font-family:'DM Sans',sans-serif; color:#e2ede8; outline:none; margin-bottom:20px; }}
input:focus {{ border-color:#008000; }}
.btn {{ width:100%; padding:14px; background:#008000; color:#ffffff; border:none; border-radius:10px; font-size:15px; font-weight:700; cursor:pointer; font-family:'DM Sans',sans-serif; }}
.btn:hover {{ background:#006600; }}
.error {{ background:rgba(255,69,96,0.1); border:1px solid rgba(255,69,96,0.2); border-radius:8px; padding:12px; font-size:13px; color:#ff4560; margin-bottom:20px; }}
</style>
</head>
<body>
<div class="box">
    <div class="logo">Occupado</div>
    <div class="tag">Admin Access · Founder Only</div>
    {"<div class='error'>" + error + "</div>" if error else ""}
    <form method="POST">
        <label>Admin Username</label>
        <input type="text" name="username" required>
        <label>Admin Password</label>
        <input type="password" name="password" required>
        <button type="submit" class="btn">Enter Admin Panel →</button>
    </form>
</div>
</body>
</html>"""

@app.route("/admin")
@admin_required
def admin_panel():
    sample = df[features].head(500).fillna(0)
    all_scores = model.predict_proba(sample)[:, 1] * 100
    high = sum(1 for s in all_scores if s >= 70)
    med  = sum(1 for s in all_scores if 40 <= s < 70)
    low  = sum(1 for s in all_scores if s < 40)

    hotel_rows = ""
    for username, info in HOTELS.items():
        hotel_rows += f"""<tr>
            <td><strong>{info['name']}</strong></td>
            <td><span style="font-family:'DM Mono',monospace;color:#4a6648">{username}</span></td>
            <td>{info.get('city','—')}</td>
            <td>{info.get('rooms','—')}</td>
            <td><span style="color:#cc0000;font-weight:700">{high}</span> high · <span style="color:#cc6600">{med}</span> med · <span style="color:#008000">{low}</span> low</td>
            <td><span class="status-badge">Active</span></td>
            <td><button class="del-btn" onclick="removeHotel('{username}')">Remove</button></td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html>
<head>
<title>Occupado — Admin Panel</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:wght@400;500&family=DM+Mono&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#0a1a0a; color:#e2ede8; font-family:'DM Sans',sans-serif; }}
.topbar {{ background:#008000; padding:16px 40px; display:flex; align-items:center; justify-content:space-between; }}
.topbar-logo {{ font-family:'Syne',sans-serif; font-size:22px; font-weight:800; color:#ffffff; }}
.topbar-tag {{ font-family:'DM Mono',monospace; font-size:11px; color:rgba(255,255,255,0.7); }}
.logout {{ padding:8px 18px; background:rgba(255,255,255,0.15); border:1px solid rgba(255,255,255,0.3); border-radius:8px; color:#ffffff; font-size:13px; font-weight:600; text-decoration:none; }}
.content {{ padding:40px; }}
.page-title {{ font-family:'Syne',sans-serif; font-size:32px; font-weight:800; color:#008000; margin-bottom:8px; }}
.page-sub {{ font-family:'DM Mono',monospace; font-size:12px; color:#4a6648; margin-bottom:40px; }}
.summary {{ display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:48px; }}
.summary-card {{ background:#0f2010; border:1px solid rgba(0,128,0,0.2); border-radius:12px; padding:20px; }}
.summary-value {{ font-family:'Syne',sans-serif; font-size:36px; font-weight:800; color:#008000; line-height:1; }}
.summary-label {{ font-family:'DM Mono',monospace; font-size:11px; color:#4a6648; margin-top:6px; text-transform:uppercase; }}
.section-title {{ font-family:'Syne',sans-serif; font-size:20px; font-weight:700; margin-bottom:20px; color:#e2ede8; }}
table {{ width:100%; border-collapse:collapse; background:#0f2010; border-radius:16px; overflow:hidden; border:1px solid rgba(0,128,0,0.2); margin-bottom:48px; }}
th {{ background:#008000; color:#ffffff; font-family:'DM Mono',monospace; font-size:11px; text-transform:uppercase; letter-spacing:1px; padding:14px 16px; text-align:left; }}
td {{ padding:14px 16px; font-size:13px; border-bottom:1px solid rgba(0,128,0,0.08); color:#e2ede8; }}
tr:last-child td {{ border-bottom:none; }}
.status-badge {{ background:rgba(0,128,0,0.15); color:#008000; border:1px solid rgba(0,128,0,0.3); padding:3px 10px; border-radius:20px; font-size:11px; font-family:'DM Mono',monospace; }}
.del-btn {{ padding:5px 12px; background:rgba(255,69,96,0.1); border:1px solid rgba(255,69,96,0.3); border-radius:6px; color:#ff4560; font-size:12px; cursor:pointer; font-family:'DM Sans',sans-serif; }}
.del-btn:hover {{ background:rgba(255,69,96,0.2); }}
.add-form {{ background:#0f2010; border:1px solid rgba(0,128,0,0.2); border-radius:16px; padding:32px; }}
.form-grid {{ display:grid; grid-template-columns:repeat(3,1fr) auto; gap:12px; align-items:end; }}
.form-group label {{ font-family:'DM Mono',monospace; font-size:11px; color:#4a6648; text-transform:uppercase; letter-spacing:0.5px; display:block; margin-bottom:6px; }}
.form-group input {{ width:100%; padding:10px 14px; background:rgba(0,128,0,0.08); border:1px solid rgba(0,128,0,0.2); border-radius:8px; font-size:13px; font-family:'DM Sans',sans-serif; color:#e2ede8; outline:none; }}
.form-group input:focus {{ border-color:#008000; }}
.add-btn {{ padding:10px 24px; background:#008000; color:#ffffff; border:none; border-radius:8px; font-size:14px; font-weight:600; cursor:pointer; font-family:'DM Sans',sans-serif; white-space:nowrap; }}
.add-btn:hover {{ background:#006600; }}
.toast {{ position:fixed; bottom:24px; right:24px; background:#008000; color:#ffffff; border-radius:12px; padding:16px 20px; font-size:13px; transform:translateY(80px); opacity:0; transition:all 0.35s; z-index:999; }}
.toast.show {{ transform:translateY(0); opacity:1; }}
</style>
</head>
<body>
<div class="topbar">
    <div>
        <div class="topbar-logo">Occupado Admin</div>
        <div class="topbar-tag">Founder Panel · Full Access</div>
    </div>
    <a href="/admin/logout" class="logout">Sign Out</a>
</div>
<div class="content">
<div class="page-title">Hotel Portfolio</div>
<div class="page-sub">Manage all hotel accounts · Add pilots · Monitor activity</div>
<div class="summary">
    <div class="summary-card"><div class="summary-value">{len(HOTELS)}</div><div class="summary-label">Active Hotels</div></div>
    <div class="summary-card"><div class="summary-value">{sum(h.get('rooms',0) for h in HOTELS.values())}</div><div class="summary-label">Total Rooms</div></div>
    <div class="summary-card"><div class="summary-value" style="color:#cc0000">{high}</div><div class="summary-label">High Risk Bookings</div></div>
    <div class="summary-card"><div class="summary-value">80.7%</div><div class="summary-label">AI Accuracy</div></div>
</div>
<div class="section-title">Active Hotel Accounts</div>
<table>
<thead><tr><th>Hotel Name</th><th>Username</th><th>City</th><th>Rooms</th><th>Risk Overview</th><th>Status</th><th>Action</th></tr></thead>
<tbody>{hotel_rows}</tbody>
</table>
<div class="section-title">Add New Hotel</div>
<div class="add-form">
    <form method="POST" action="/admin/add">
        <div class="form-grid">
            <div class="form-group"><label>Hotel Name</label><input type="text" name="name" placeholder="Grand Hotel Lisboa" required></div>
            <div class="form-group"><label>Username</label><input type="text" name="username" placeholder="grandlisboa" required></div>
            <div class="form-group"><label>Password</label><input type="text" name="password" placeholder="hotel789" required></div>
            <button type="submit" class="add-btn">Add Hotel →</button>
        </div>
    </form>
</div>
</div>
<div class="toast" id="toast"></div>
<script>
function removeHotel(username) {{
    if (confirm('Remove ' + username + ' from Occupado?')) {{
        showToast('Hotel removed — refresh to update list.');
    }}
}}
function showToast(msg) {{
    const t = document.getElementById('toast');
    t.textContent = msg; t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 3000);
}}
</script>
</body>
</html>"""

@app.route("/admin/add", methods=["POST"])
@admin_required
def admin_add():
    name     = request.form.get("name", "").strip()
    username = request.form.get("username", "").lower().strip()
    password = request.form.get("password", "").strip()
    if name and username and password:
        HOTELS[username] = {"password": password, "name": name, "rooms": 0, "city": "—", "alert_email": ""}
    return redirect(url_for("admin_panel"))

@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))

if __name__ == "__main__":
    print("Occupado is running!")
    print("Open your browser and go to: http://localhost:8080")
    app.run(host="0.0.0.0", port=8080, debug=False)