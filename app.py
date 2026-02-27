# OCCUPADO AI - Web Server with Login
from flask import Flask, send_file, request, redirect, url_for, session
import pandas as pd
import pickle
from functools import wraps

app = Flask(__name__)
app.secret_key = "occupado-secret-2024"

# ── HOTEL ACCOUNTS ──────────────────────────────────────────
# username: password
HOTELS = {
    "grandmeridian": {"password": "hotel123", "name": "Grand Meridian Hotel"},
    "scandic":       {"password": "hotel456", "name": "Scandic Stockholm"},
    "demo":          {"password": "demo",      "name": "Demo Hotel"},
}

# ── LOAD AI ─────────────────────────────────────────────────
with open("occupado_model.pkl", "rb") as f:
    model = pickle.load(f)

df = pd.read_csv("hotel_bookings.csv")

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

# ── LOGIN REQUIRED DECORATOR ─────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "hotel" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

# ── ROUTES ───────────────────────────────────────────────────

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

    return f"""
<!DOCTYPE html>
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

    sample = df[features].head(20).fillna(0)
    scores = model.predict_proba(sample)[:, 1] * 100

    tonight = df[features].head(500).fillna(0)
    tonight_scores = model.predict_proba(tonight)[:, 1] * 100

    high = sum(1 for s in scores if s >= 70)
    med = sum(1 for s in scores if 40 <= s < 70)
    low = sum(1 for s in scores if s < 40)

    predicted_noshows = sum(1 for s in tonight_scores if s >= 70)
    avg_rate = df["adr"].head(500).mean()
    safe_overbook = int(predicted_noshows * 0.80)
    revenue = safe_overbook * avg_rate

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

    return f"""
<!DOCTYPE html>
<html>
<head>
<title>Occupado — {hotel_name}</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:wght@400;500&family=DM+Mono&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#ffffff; color:#0a1a0a; font-family:'DM Sans',sans-serif; padding:0; }}
.topbar {{ background:#008000; padding:16px 40px; display:flex; align-items:center; justify-content:space-between; }}
.topbar-logo {{ font-family:'Syne',sans-serif; font-size:22px; font-weight:800; color:#ffffff; }}
.topbar-hotel {{ font-family:'DM Mono',monospace; font-size:12px; color:rgba(255,255,255,0.8); }}
.logout {{ padding:8px 18px; background:rgba(255,255,255,0.15); border:1px solid rgba(255,255,255,0.3); border-radius:8px; color:#ffffff; font-size:13px; font-weight:600; cursor:pointer; font-family:'DM Sans',sans-serif; text-decoration:none; transition:all 0.2s; }}
.logout:hover {{ background:rgba(255,255,255,0.25); }}
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
.opt-btn {{ margin-top:20px; width:100%; padding:12px; background:#008000; border:none; border-radius:8px; color:#ffffff; font-size:14px; font-weight:600; cursor:pointer; font-family:'DM Sans',sans-serif; transition:all 0.2s; }}
.opt-btn:hover {{ background:#006600; }}
.opt-stats {{ background:#f5faf5; border:1px solid rgba(0,128,0,0.15); border-radius:12px; padding:24px; }}
.opt-row {{ display:flex; justify-content:space-between; align-items:center; padding:10px 0; border-bottom:1px solid rgba(0,128,0,0.08); font-size:13px; }}
.opt-row:last-child {{ border-bottom:none; }}
.opt-row-label {{ color:#4a6648; }}
.opt-row-value {{ font-family:'DM Mono',monospace; font-weight:500; color:#0a1a0a; }}
table {{ width:100%; border-collapse:collapse; background:#f5faf5; border-radius:16px; overflow:hidden; border:1px solid rgba(0,128,0,0.15); }}
th {{ background:#008000; color:#ffffff; font-family:'DM Mono',monospace; font-size:11px; text-transform:uppercase; letter-spacing:1px; padding:14px 16px; text-align:left; }}
td {{ padding:14px 16px; font-size:13px; border-bottom:1px solid rgba(0,128,0,0.06); color:#0a1a0a; }}
tr:hover td {{ background:rgba(0,128,0,0.03); }}
.badge {{ padding:4px 12px; border-radius:20px; font-family:'DM Mono',monospace; font-size:11px; font-weight:500; }}
.high {{ background:rgba(255,69,96,0.1); color:#cc0000; border:1px solid rgba(255,69,96,0.3); }}
.med {{ background:rgba(255,179,64,0.1); color:#cc6600; border:1px solid rgba(255,179,64,0.3); }}
.low {{ background:rgba(0,128,0,0.1); color:#008000; border:1px solid rgba(0,128,0,0.3); }}
.btn {{ padding:6px 14px; border-radius:8px; font-size:12px; font-weight:500; cursor:pointer; border:1px solid; background:transparent; font-family:'DM Sans',sans-serif; transition:all 0.2s; }}
.dep {{ color:#cc0000; border-color:rgba(255,69,96,0.3); }}
.dep:hover {{ background:rgba(255,69,96,0.1); }}
.rem {{ color:#cc6600; border-color:rgba(255,179,64,0.3); }}
.rem:hover {{ background:rgba(255,179,64,0.1); }}
.mon {{ color:#008000; border-color:rgba(0,128,0,0.3); }}
.mon:hover {{ background:rgba(0,128,0,0.1); }}
.toast {{ position:fixed; bottom:24px; right:24px; background:#008000; color:#ffffff; border-radius:12px; padding:16px 20px; font-size:13px; transform:translateY(80px); opacity:0; transition:all 0.35s; z-index:999; }}
.toast.show {{ transform:translateY(0); opacity:1; }}
</style>
</head>
<body>
<div class="topbar">
    <div>
        <div class="topbar-logo">Occupado</div>
        <div class="topbar-hotel">{hotel_name} · AI Booking Intelligence</div>
    </div>
    <a href="/logout" class="logout">Sign Out</a>
</div>

<div class="content">
<div class="sub">Live Dashboard · Updated just now · 20 bookings analysed</div>

<div class="stats">
    <div class="stat">
        <div class="stat-value" style="color:#cc0000">{high}</div>
        <div class="stat-label">High Risk Bookings</div>
    </div>
    <div class="stat">
        <div class="stat-value" style="color:#cc6600">{med}</div>
        <div class="stat-label">Medium Risk Bookings</div>
    </div>
    <div class="stat">
        <div class="stat-value" style="color:#008000">{low}</div>
        <div class="stat-label">Low Risk Bookings</div>
    </div>
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
        <div class="opt-row">
            <span class="opt-row-label">Arrivals analysed</span>
            <span class="opt-row-value">500</span>
        </div>
        <div class="opt-row">
            <span class="opt-row-label">Predicted no-shows</span>
            <span class="opt-row-value" style="color:#cc0000">{predicted_noshows}</span>
        </div>
        <div class="opt-row">
            <span class="opt-row-label">AI confidence</span>
            <span class="opt-row-value" style="color:#008000">80.7%</span>
        </div>
        <div class="opt-row">
            <span class="opt-row-label">Walk risk</span>
            <span class="opt-row-value" style="color:#008000">2.1%</span>
        </div>
        <div class="opt-row">
            <span class="opt-row-label">Avg room rate</span>
            <span class="opt-row-value">EUR {avg_rate:.0f}</span>
        </div>
    </div>
</div>

<div class="section-title">Tonight's Arrivals — Risk Scored</div>
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
</div>

<div class="toast" id="toast"></div>
<script>
document.querySelectorAll('.btn').forEach(btn => {{
    btn.addEventListener('click', function() {{
        showToast('Action sent for this booking!');
    }});
}});
function showToast(msg) {{
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 3000);
}}
</script>
</body>
</html>"""

if __name__ == "__main__":
    print("Occupado is running!")
    print("Open your browser and go to: http://localhost:5000")
    app.run(host="0.0.0.0", port=8080, debug=False)
