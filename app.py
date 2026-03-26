from flask import Flask, send_file, request, redirect, url_for, session
import pandas as pd
import pickle
import io
import json
from functools import wraps
from datetime import datetime, timedelta
import os
import secrets
import psycopg2
import psycopg2.extras
import bcrypt
import re
from dotenv import load_dotenv
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "occupado-secret-2024")
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5MB upload limit

@app.after_request
def add_security_headers(response):
    # Content Security Policy
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"
    )
    # Prevent clickjacking
    response.headers["X-Frame-Options"] = "DENY"
    # Prevent MIME sniffing
    response.headers["X-Content-Type-Options"] = "nosniff"
    # Force HTTPS
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # Hide server info
    response.headers["X-Powered-By"] = ""
    response.headers["Server"] = ""
    return response

TOKEN_DIR = "/tmp/occupado_tokens"
os.makedirs(TOKEN_DIR, exist_ok=True)

def get_db():
    DATABASE_URL = os.environ.get("DATABASE_URL", "")
    if not DATABASE_URL:
        # Railway sometimes exposes individual PG* vars instead of a single URL
        pghost = os.environ.get("PGHOST", "")
        pgport = os.environ.get("PGPORT", "5432")
        pgdb   = os.environ.get("PGDATABASE", "")
        pguser = os.environ.get("PGUSER", "")
        pgpass = os.environ.get("PGPASSWORD", "")
        if pghost and pgdb and pguser:
            DATABASE_URL = f"postgresql://{pguser}:{pgpass}@{pghost}:{pgport}/{pgdb}"
        else:
            raise RuntimeError(
                "No database connection found. "
                "Set DATABASE_URL (or PGHOST/PGDATABASE/PGUSER/PGPASSWORD) in Railway Variables."
            )
    conn = psycopg2.connect(DATABASE_URL)
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS registered_users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            verified INTEGER NOT NULL DEFAULT 0,
            signed_up TEXT DEFAULT ''
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS verification_tokens (
            token TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            expires_at TIMESTAMP NOT NULL DEFAULT (NOW() + INTERVAL '24 hours')
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            token TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            expires_at TIMESTAMP NOT NULL DEFAULT (NOW() + INTERVAL '1 hour')
        )
    """)
    conn.commit()
    cur.close()
    conn.close()
    # Migrate: add signed_up column in separate transaction
    try:
        conn2 = get_db()
        cur2 = conn2.cursor()
        cur2.execute("ALTER TABLE registered_users ADD COLUMN signed_up TEXT DEFAULT ''")
        conn2.commit()
        cur2.close()
        conn2.close()
    except:
        pass
    # Migrate: add expires_at column to verification_tokens
    try:
        conn3 = get_db()
        cur3 = conn3.cursor()
        cur3.execute("ALTER TABLE verification_tokens ADD COLUMN expires_at TIMESTAMP NOT NULL DEFAULT (NOW() + INTERVAL '24 hours')")
        conn3.commit()
        cur3.close()
        conn3.close()
    except:
        pass

try:
    init_db()
except Exception as _db_err:
    import sys
    print(f"[occupado] WARNING: Database init failed — {_db_err}", file=sys.stderr)
    print("[occupado] Set DATABASE_URL in Railway -> Variables to fix this.", file=sys.stderr)

# ── Rate limiting: track failed login attempts ──
# { ip: { "count": int, "locked_until": datetime | None } }
FAILED_ATTEMPTS = {}
MAX_ATTEMPTS    = 5
LOCKOUT_MINUTES = 15

def check_rate_limit(ip):
    """Returns (is_blocked, seconds_remaining)"""
    record = FAILED_ATTEMPTS.get(ip)
    if not record:
        return False, 0
    if record["locked_until"] and datetime.now() < record["locked_until"]:
        remaining = int((record["locked_until"] - datetime.now()).total_seconds())
        return True, remaining
    return False, 0

def record_failed_attempt(ip):
    if ip not in FAILED_ATTEMPTS:
        FAILED_ATTEMPTS[ip] = {"count": 0, "locked_until": None}
    FAILED_ATTEMPTS[ip]["count"] += 1
    if FAILED_ATTEMPTS[ip]["count"] >= MAX_ATTEMPTS:
        FAILED_ATTEMPTS[ip]["locked_until"] = datetime.now() + timedelta(minutes=LOCKOUT_MINUTES)

def reset_attempts(ip):
    FAILED_ATTEMPTS.pop(ip, None)

def sanitise(value, max_length=100):
    """Strip dangerous characters and limit length."""
    value = str(value).strip()
    value = re.sub(r"[<>\"'%;()&+]", "", value)
    return value[:max_length]

# Language Translations (English, Dutch, French)
TRANSLATIONS = {
    "en": {
        "occupado": "Occupado",
        "ai_booking": "AI Booking Intelligence",
        "settings": "Settings",
        "sign_out": "Sign Out",
        "live_dashboard": "Live Dashboard",
        "bookings_analysed": "bookings analysed",
        "upload_data": "Upload Your Booking Data",
        "drop_csv": "📂 Drop your booking CSV here",
        "export_pms": "Export from your PMS and upload",
        "choose_file": "Choose CSV File",
        "high_risk": "High Risk",
        "medium_risk": "Medium Risk",
        "low_risk": "Low Risk",
        "optimizer": "Overbooking Optimizer",
        "safe_rooms": "Safe rooms to oversell tonight",
        "revenue": "Revenue opportunity: EUR",
        "apply": "Apply Recommendation",
        "bookings_analysed_stat": "Bookings analysed",
        "predicted": "Predicted no-shows",
        "confidence": "AI confidence",
        "walk_risk": "Walk risk",
        "avg_rate": "Avg room rate",
        "take_action": "Take Action on High-Risk Bookings",
        "send_mass": "Send Mass Email",
        "send_high": "Send to all {high} high-risk bookings",
        "send_btn": "Send Email to All →",
        "request_dep": "Request Deposits",
        "dep_template": "Quick template for deposits",
        "dep_btn": "Send Deposit Request →",
        "reminders": "Send Reminders",
        "rem_template": "Quick template for reminders",
        "rem_btn": "Send Reminder →",
        "click_row": "Bookings — Click any row for AI reasoning",
        "booking": "Booking",
        "lead": "Lead Time",
        "rate": "Room Rate",
        "returning": "Returning",
        "cancels": "Past Cancels",
        "risk": "Risk Score",
        "action": "Action",
        "days": "days",
        "yes": "Yes",
        "no": "No",
        "high": "HIGH",
        "medium": "MEDIUM",
        "low": "LOW",
        "req_dep": "Request Deposit",
        "send_rem": "Send Reminder",
        "monitor": "Monitor",
        "email_guest": "Send Email to Guest",
        "guest_email": "Guest Email Address",
        "guest_name": "Guest Name",
        "subject": "Subject Line",
        "message": "Message to Guest",
        "send_email": "📧 Send Email",
        "cancel": "Cancel",
        "bulk_email": "Send Email to All High-Risk Bookings",
        "select_book": "Select Bookings to Send To",
        "selected_count": "bookings selected",
        "save_changes": "💾 Save Changes",
        "send_selected": "📧 Send to Selected",
        "fill_fields": "Please fill in all fields",
        "select_one": "Please select at least one booking",
        "sent_success": "✓ Emails sent to {count} guest(s)",
        "error": "Error sending emails",
        "settings_title": "Settings",
        "config_alert": "Configure your alert preferences",
        "alert_email": "🔔 Alert Email",
        "alert_desc": "Email address for high-risk booking alerts",
        "email_addr": "Email Address",
        "save": "Save Settings →",
        "saved": "✓ Settings saved!",
        "back": "← Back",
        "auto_pop": "Automatically populated with high-risk bookings. Remove any you don't want to contact.",
    },
    "nl": {
        "occupado": "Occupado",
        "ai_booking": "AI Boekingintelligentie",
        "settings": "Instellingen",
        "sign_out": "Afmelden",
        "live_dashboard": "Live Dashboard",
        "bookings_analysed": "boekingen geanalyseerd",
        "upload_data": "Upload uw boekingsgegevens",
        "drop_csv": "📂 Sleep uw boeking CSV hier",
        "export_pms": "Exporteer uit uw PMS en upload",
        "choose_file": "Kies CSV-bestand",
        "high_risk": "Hoog risico",
        "medium_risk": "Gemiddeld risico",
        "low_risk": "Laag risico",
        "optimizer": "Overbooking Optimizer",
        "safe_rooms": "Veilige kamers om vanavond te overboeken",
        "revenue": "Omzetmogelijkheid: EUR",
        "apply": "Aanbeveling toepassen",
        "bookings_analysed_stat": "Boekingen geanalyseerd",
        "predicted": "Voorspelde no-shows",
        "confidence": "AI-betrouwbaarheid",
        "walk_risk": "Walk-risico",
        "avg_rate": "Gem. kamerprijs",
        "take_action": "Maatregelen nemen voor risicovolle boekingen",
        "send_mass": "E-mail verzenden naar meerdere",
        "send_high": "Verzenden naar alle {high} risicovolle boekingen",
        "send_btn": "E-mail naar iedereen verzenden →",
        "request_dep": "Aanbetaling aanvragen",
        "dep_template": "Snelle sjabloon voor aanbetaling",
        "dep_btn": "Aanbetaling aanvragen →",
        "reminders": "Herinneringen verzenden",
        "rem_template": "Snelle sjabloon voor herinneringen",
        "rem_btn": "Herinnering verzenden →",
        "click_row": "Boekingen — Klik op een rij voor AI-redenering",
        "booking": "Boeking",
        "lead": "Aanlooptijd",
        "rate": "Kamerprijs",
        "returning": "Klant keert terug",
        "cancels": "Eerdere annuleringen",
        "risk": "Risicoscore",
        "action": "Actie",
        "days": "dagen",
        "yes": "Ja",
        "no": "Nee",
        "high": "HOOG",
        "medium": "GEMIDDELD",
        "low": "LAAG",
        "req_dep": "Aanbetaling aanvragen",
        "send_rem": "Herinnering verzenden",
        "monitor": "Bewaken",
        "email_guest": "E-mail naar gast verzenden",
        "guest_email": "E-mailadres gast",
        "guest_name": "Gastnaam",
        "subject": "Onderwerpregel",
        "message": "Bericht aan gast",
        "send_email": "📧 E-mail verzenden",
        "cancel": "Annuleren",
        "bulk_email": "E-mail verzenden naar alle risicovolle boekingen",
        "select_book": "Selecteer boekingen om naar te verzenden",
        "selected_count": "boekingen geselecteerd",
        "save_changes": "💾 Wijzigingen opslaan",
        "send_selected": "📧 Naar geselecteerden verzenden",
        "fill_fields": "Vul alstublieft alle velden in",
        "select_one": "Selecteer alstublieft minstens één boeking",
        "sent_success": "✓ E-mails verzonden naar {count} gast(en)",
        "error": "Fout bij verzenden van e-mails",
        "settings_title": "Instellingen",
        "config_alert": "Configureer uw waarschuwingsvoorkeuren",
        "alert_email": "🔔 Waarschuwing per e-mail",
        "alert_desc": "E-mailadres voor waarschuwingen van risicovolle boekingen",
        "email_addr": "E-mailadres",
        "save": "Instellingen opslaan →",
        "saved": "✓ Instellingen opgeslagen!",
        "back": "← Terug",
        "auto_pop": "Automatisch ingevuld met risicovolle boekingen. Verwijder degenen die u niet wilt contacteren.",
    },
    "fr": {
        "occupado": "Occupado",
        "ai_booking": "Intelligence de Réservation IA",
        "settings": "Paramètres",
        "sign_out": "Déconnexion",
        "live_dashboard": "Tableau de bord en direct",
        "bookings_analysed": "réservations analysées",
        "upload_data": "Téléchargez vos données de réservation",
        "drop_csv": "📂 Déposez votre CSV de réservation ici",
        "export_pms": "Exporter depuis votre PMS et télécharger",
        "choose_file": "Choisir un fichier CSV",
        "high_risk": "Risque élevé",
        "medium_risk": "Risque moyen",
        "low_risk": "Risque faible",
        "optimizer": "Optimiseur de Surréservation",
        "safe_rooms": "Chambres sûres à surréserver ce soir",
        "revenue": "Opportunité de revenus: EUR",
        "apply": "Appliquer la recommandation",
        "bookings_analysed_stat": "Réservations analysées",
        "predicted": "Absences prévues",
        "confidence": "Confiance IA",
        "walk_risk": "Risque d'annulation",
        "avg_rate": "Tarif moyen par chambre",
        "take_action": "Agir sur les réservations à risque élevé",
        "send_mass": "Envoyer un e-mail en masse",
        "send_high": "Envoyer à tous les {high} réservations à risque",
        "send_btn": "Envoyer un e-mail à tous →",
        "request_dep": "Demander les dépôts",
        "dep_template": "Modèle rapide pour dépôts",
        "dep_btn": "Demander un dépôt →",
        "reminders": "Envoyer des rappels",
        "rem_template": "Modèle rapide pour rappels",
        "rem_btn": "Envoyer un rappel →",
        "click_row": "Réservations — Cliquez sur une ligne pour le raisonnement IA",
        "booking": "Réservation",
        "lead": "Délai d'approche",
        "rate": "Tarif de la chambre",
        "returning": "Client de retour",
        "cancels": "Annulations antérieures",
        "risk": "Score de risque",
        "action": "Action",
        "days": "jours",
        "yes": "Oui",
        "no": "Non",
        "high": "ÉLEVÉ",
        "medium": "MOYEN",
        "low": "FAIBLE",
        "req_dep": "Demander un dépôt",
        "send_rem": "Envoyer un rappel",
        "monitor": "Surveiller",
        "email_guest": "Envoyer un e-mail à un client",
        "guest_email": "Adresse e-mail du client",
        "guest_name": "Nom du client",
        "subject": "Ligne d'objet",
        "message": "Message au client",
        "send_email": "📧 Envoyer un e-mail",
        "cancel": "Annuler",
        "bulk_email": "Envoyer un e-mail à toutes les réservations à risque",
        "select_book": "Sélectionnez les réservations à envoyer",
        "selected_count": "réservations sélectionnées",
        "save_changes": "💾 Enregistrer les modifications",
        "send_selected": "📧 Envoyer aux sélectionnés",
        "fill_fields": "Veuillez remplir tous les champs",
        "select_one": "Veuillez sélectionner au moins une réservation",
        "sent_success": "✓ E-mails envoyés à {count} client(s)",
        "error": "Erreur lors de l'envoi des e-mails",
        "settings_title": "Paramètres",
        "config_alert": "Configurez vos préférences d'alerte",
        "alert_email": "🔔 Alerte par e-mail",
        "alert_desc": "Adresse e-mail pour les alertes de réservations à risque",
        "email_addr": "Adresse e-mail",
        "save": "Enregistrer les paramètres →",
        "saved": "✓ Paramètres enregistrés!",
        "back": "← Retour",
        "auto_pop": "Rempli automatiquement avec les réservations à risque élevé. Supprimez celles que vous ne souhaitez pas contacter.",
    }
}

def t(key, lang="en", **kwargs):
    """Translate a key to the specified language"""
    text = TRANSLATIONS.get(lang, {}).get(key, TRANSLATIONS.get("en", {}).get(key, key))
    if kwargs:
        try:
            return text.format(**kwargs)
        except:
            return text
    return text

def generate_magic_token(hotel_username, csv_data):
    token = secrets.token_urlsafe(32)
    token_file = os.path.join(TOKEN_DIR, f"{token}.json")
    with open(token_file, 'w') as f:
        json.dump({"hotel": hotel_username, "csv_data": csv_data}, f)
    print(f"[TOKEN] Created: {token[:30]}...")
    return token

def get_token_data(token):
    token_file = os.path.join(TOKEN_DIR, f"{token}.json")
    if not os.path.exists(token_file):
        return None
    try:
        with open(token_file, 'r') as f:
            return json.load(f)
    except:
        return None

def delete_token(token):
    token_file = os.path.join(TOKEN_DIR, f"{token}.json")
    try:
        if os.path.exists(token_file):
            os.remove(token_file)
    except:
        pass

def send_consolidated_alert(hotel_name, alert_email, high_risk_bookings, hotel_username=None, csv_data=None):
    if not alert_email or not high_risk_bookings:
        return
    
    magic_link = "http://localhost:8080/login"
    if hotel_username and csv_data:
        token = generate_magic_token(hotel_username, csv_data)
        magic_link = f"http://localhost:8080/magic/{token}"
        print(f"[EMAIL] Magic link: {magic_link}")
    
    booking_rows = ""
    for booking in high_risk_bookings:
        booking_rows += f'<tr style="border-bottom:1px solid #e0e0e0;"><td style="padding:12px 16px;">{booking["id"]}</td><td style="padding:12px 16px;text-align:right;"><span style="background:#cc0000;color:white;padding:4px 12px;border-radius:20px;font-weight:600;">{booking["score"]:.1f}%</span></td></tr>'
    
    message = Mail(
        from_email=os.environ.get('ALERT_FROM_EMAIL', 'team@occupado.co'),
        to_emails=alert_email,
        subject=f"Alert: {len(high_risk_bookings)} High Cancellation Risk Bookings — {hotel_name}",
        html_content=f"""
        <div style="font-family:Arial,sans-serif;max-width:700px;margin:0 auto;">
            <div style="background:#008000;color:white;padding:24px;border-radius:12px 12px 0 0;">
                <h2 style="margin:0;font-size:22px;font-weight:700;">⚠️ High Cancellation Risk Alert</h2>
                <p style="margin:8px 0 0;font-size:14px;opacity:0.95;">{hotel_name}</p>
            </div>
            
            <div style="background:#f5faf5;padding:24px;border:1px solid #ddd;border-top:none;">
                <table style="width:100%;border-collapse:collapse;margin-bottom:24px;">
                    <thead>
                        <tr style="background:#f0f0f0;border-bottom:2px solid #008000;">
                            <th style="padding:12px 16px;text-align:left;font-family:'DM Mono',monospace;font-size:12px;color:#0a1a0a;font-weight:600;">Booking ID</th>
                            <th style="padding:12px 16px;text-align:right;font-family:'DM Mono',monospace;font-size:12px;color:#0a1a0a;font-weight:600;">Risk Score</th>
                        </tr>
                    </thead>
                    <tbody>{booking_rows}</tbody>
                </table>
                
                <center>
                    <a href="{magic_link}" style="background:#008000;color:white;padding:12px 32px;text-decoration:none;border-radius:8px;display:inline-block;font-weight:600;font-size:14px;">View Dashboard & Take Action →</a>
                </center>
            </div>
        </div>
        """
    )
    try:
        sg = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
        sg.send(message)
        print(f"[EMAIL] Sent to {alert_email}")
    except Exception as e:
        print(f"[ERROR] {e}")

def send_email_to_guest(guest_email, guest_name, hotel_name, subject, message_body):
    if not guest_email or not message_body:
        return False
    
    html_content = f"""
    <div style="font-family:'DM Sans',sans-serif;max-width:600px;margin:0 auto;background:#f5faf5;padding:24px;border-radius:12px;">
        <div style="background:#008000;color:white;padding:20px;border-radius:8px 8px 0 0;margin:-24px -24px 24px -24px;">
            <h2 style="margin:0;font-size:18px;">{hotel_name}</h2>
        </div>
        <div style="color:#0a1a0a;font-size:14px;line-height:1.8;white-space:pre-wrap;">
{message_body}
        </div>
        <div style="margin-top:24px;padding-top:16px;border-top:1px solid #ddd;color:#999;font-size:11px;text-align:center;">
            This email was sent from {hotel_name} via Occupado
        </div>
    </div>
    """
    
    message = Mail(
        from_email=os.environ.get('ALERT_FROM_EMAIL', 'team@occupado.co'),
        to_emails=guest_email,
        subject=subject,
        html_content=html_content
    )
    
    try:
        sg = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
        sg.send(message)
        return True
    except Exception as e:
        print(f"[ERROR] {e}")
        return False

HOTELS = {
    "grandmeridian":          {"password": "hotel123",    "name": "Grand Meridian Hotel",         "rooms": 200, "city": "Lisbon"},
    "scandic":                {"password": "hotel456",    "name": "Scandic Stockholm",             "rooms": 350, "city": "Stockholm"},
    "demo":                   {"password": "demo",        "name": "Demo Hotel",                    "rooms": 100, "city": "Porto"},
    "van der valk mechelen":  {"password": "Mechelen123", "name": "Van der Valk Hotel Mechelen",   "rooms": 150, "city": "Mechelen", "vdv": True},
}

with open("occupado_model.pkl", "rb") as f:
    model = pickle.load(f)

df = pd.read_csv("hotel_bookings.csv")

# ── VAN DER VALK MECHELEN — Pre-loaded data & enhanced dashboard ──────────────
VDV_HOTEL_KEY = "van der valk mechelen"
_VDV_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "VDV-Data")

def _parse_vdv_guests():
    """Parse RES_042 repeat reservations report for current/upcoming repeat guests."""
    path = os.path.join(_VDV_DIR, "RES_042_RepeatReservationsReport (1).xlsx")
    if not os.path.exists(path):
        return []
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True)
        rows = list(wb.active.iter_rows(values_only=True))
        wb.close()
        today = datetime.now()
        guests = []
        i = 0
        while i < len(rows):
            row = rows[i]
            col0 = str(row[0]).strip() if row[0] else ''
            col1 = str(row[1]).strip() if len(row) > 1 and row[1] else ''
            col4 = row[4] if len(row) > 4 else None
            col5 = row[5] if len(row) > 5 else None
            if ',' in col0 and col4 and '/' in str(col4):
                try:
                    arr = datetime.strptime(str(col4)[:10], '%d/%m/%Y')
                except Exception:
                    i += 1
                    continue
                adults = 1
                if col5:
                    try: adults = int(str(col5).split('/')[0])
                    except: pass
                dep = None
                for j in range(i + 1, min(i + 7, len(rows))):
                    r = rows[j]
                    r4 = r[4] if len(r) > 4 else None
                    if r4 and r[0] is None and '/' in str(r4):
                        try:
                            dep = datetime.strptime(str(r4)[:10], '%d/%m/%Y')
                            break
                        except: pass
                # Collect guest notes
                note_parts = []
                _skip = {'Repeat Reservations Report', 'Van der Valk Hotel Mechelen'}
                for j in range(i + 1, min(i + 22, len(rows))):
                    r = rows[j]
                    r6 = r[6] if len(r) > 6 else None
                    if r6:
                        n = str(r6).strip()
                        if n and n not in _skip and 'MIGRATED' not in n and 'CORPORATE 2025' not in n and 'central ar' not in n.lower() and '\n' not in n:
                            note_parts.append(n[:80])
                note = '; '.join(note_parts[:2]) if note_parts else ''
                nights = (dep - arr).days if dep else 1
                if dep and dep.date() < today.date():
                    status = 'Checked Out'
                elif arr.date() == today.date():
                    status = 'Arriving Today'
                elif arr.date() < today.date():
                    status = 'In House'
                else:
                    status = f'Arriving {arr.strftime("%d %b")}'
                guests.append({
                    'name': col0, 'membership': col1,
                    'arrival': arr.strftime('%d/%m/%Y'),
                    'departure': dep.strftime('%d/%m/%Y') if dep else '',
                    'arr_date': arr, 'dep_date': dep,
                    'adults': adults, 'nights': nights,
                    'status': status, 'note': note,
                })
            i += 1
        return guests
    except Exception as e:
        print(f"[VDV] Guest parse error: {e}")
        return []


def _parse_vdv_channel_stats():
    """Parse RES_036 cancelled reservations for channel breakdown."""
    path = os.path.join(_VDV_DIR, "RES_036_CancelledReservations (1).xlsx")
    if not os.path.exists(path):
        return {}
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True)
        rows = list(wb.active.iter_rows(values_only=True))
        wb.close()
        raw = {}
        for row in rows:
            if row[0] is None and len(row) > 3 and row[3]:
                seg = str(row[3]).strip()
                if seg and not seg.startswith('Subtotal') and not re.match(r'\d{2}/\d{2}/\d{4}', seg) and seg not in ('Market Segment', 'Company/Travel Agent'):
                    raw[seg] = raw.get(seg, 0) + 1
        return {
            'Booking.com':       sum(raw.get(k, 0) for k in ('BARWEB', 'BAROTAGROSS', 'DEALSOTA')),
            'Direct / Web':      sum(raw.get(k, 0) for k in ('DISCWEB', 'BARDIR', 'DISCDIR', 'DISCOTAGROSS')),
            'Corporate':         sum(raw.get(k, 0) for k in ('CORPFIX', 'CORPDYN')),
            'Packages / Groups': sum(raw.get(k, 0) for k in ('PACK', 'MTGBNS', 'BNSGRP')),
            'Other':             sum(raw.get(k, 0) for k in ('DEALS', 'OTHER', 'COMP')),
        }
    except Exception as e:
        print(f"[VDV] Channel stats error: {e}")
        return {}


def _score_vdv_guests(guests):
    """Score VdV repeat guests using the trained model."""
    if not guests:
        return []
    today = datetime.now()
    feat_rows = []
    for g in guests:
        arr = g['arr_date']
        dep = g['dep_date']
        lead = max(0, (arr - today).days)
        wkend = wkday = 0
        if dep:
            d = arr
            while d < dep:
                if d.weekday() >= 5: wkend += 1
                else: wkday += 1
                d += timedelta(days=1)
        week_num = int(arr.isocalendar()[1])
        adr = 149.0 if 'CORP' in g.get('membership', '') else (150.0 if g['nights'] >= 10 else 115.0)
        prev_ok = 5 if 'VIP' in g.get('membership', '') else 3
        feat_rows.append([lead, week_num, wkend, wkday, g['adults'],
                          1, 0, prev_ok, 0, 0, adr, 1 if g.get('note') else 0])
    feat_cols = ['lead_time','arrival_date_week_number','stays_in_weekend_nights',
                 'stays_in_week_nights','adults','is_repeated_guest',
                 'previous_cancellations','previous_bookings_not_canceled',
                 'booking_changes','days_in_waiting_list','adr','total_of_special_requests']
    df_feat = pd.DataFrame(feat_rows, columns=feat_cols)
    return [float(s) for s in model.predict_proba(df_feat)[:, 1] * 100]


def _parse_vdv_future_bookings():
    """Parse RES_004 EnteredOnAndBy for all future bookings with lead times & channels."""
    path = os.path.join(_VDV_DIR, "RES_004_EnteredOnAndBy (1).xlsx")
    if not os.path.exists(path):
        return []
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True)
        rows = list(wb.active.iter_rows(values_only=True))
        wb.close()
        today = datetime.now().date()
        bookings = []
        i = 0
        while i < len(rows):
            r = rows[i]
            c0 = str(r[0]).strip() if r[0] else ''
            c3 = str(r[3]).strip() if len(r) > 3 and r[3] else ''
            if (',' in c0 and c3.startswith('MEC-') and not c3.startswith('MEC-F')
                    and len(r) > 8 and r[8]):
                arr_str = str(r[8])[:10]
                try:
                    arr = datetime.strptime(arr_str, '%d/%m/%Y').date()
                except Exception:
                    i += 1
                    continue
                if arr < today:
                    i += 1
                    continue
                nights = int(r[9]) if r[9] and str(r[9]).isdigit() else 1
                adults_str = str(r[12]).split('/')[0].strip() if r[12] else '1'
                try:   adults = int(adults_str)
                except: adults = 1
                channel = str(r[25]).strip() if len(r) > 25 and r[25] else 'OTHER'
                rate_str = str(r[16]).strip() if len(r) > 16 and r[16] else ''
                try:
                    total_rate = float(rate_str.replace(',', '.'))
                    adr = total_rate / max(1, nights)
                except Exception:
                    adr = 130.0
                created = str(r[28])[:10] if len(r) > 28 and r[28] else ''
                lead = 0
                if created:
                    try:
                        cdate = datetime.strptime(created, '%d/%m/%Y').date()
                        lead = max(0, (arr - cdate).days)
                    except Exception:
                        pass
                gtd = 'NONE'
                for j in range(i + 1, min(i + 5, len(rows))):
                    rj = rows[j]
                    if len(rj) > 12 and rj[12]:
                        gtd = str(rj[12]).strip()
                        break
                wkend = wkday = 0
                d = datetime.combine(arr, datetime.min.time())
                for _ in range(nights):
                    if d.weekday() >= 5: wkend += 1
                    else: wkday += 1
                    d += timedelta(days=1)
                week_num = int(datetime.combine(arr, datetime.min.time()).isocalendar()[1])
                ch_map = {
                    'BARWEB': 'Booking.com', 'BAROTAGROSS': 'Booking.com',
                    'DEALSOTA': 'Booking.com', 'DISCOTAGROSS': 'Booking.com',
                    'DISCWEB': 'Direct/Web', 'BARDIR': 'Direct/Web', 'DISCDIR': 'Direct/Web',
                    'CORPFIX': 'Corporate', 'CORPDYN': 'Corporate',
                    'PACK': 'Package', 'MTGBNS': 'Package', 'BNSGRP': 'Package',
                    'DEALS': 'Other',
                }
                ch_label = ch_map.get(channel, 'Other')
                bookings.append({
                    'name': c0, 'arrival': arr.strftime('%d/%m/%Y'),
                    'arr_date': arr, 'nights': nights, 'adults': adults,
                    'channel': ch_label, 'channel_raw': channel,
                    'lead': lead, 'gtd': gtd, 'adr': round(adr, 2),
                    'wkend': wkend, 'wkday': wkday, 'week_num': week_num,
                })
            i += 1
        return bookings
    except Exception as e:
        print(f"[VDV] Future bookings parse error: {e}")
        return []


def _score_vdv_future(bookings):
    """Score VdV future bookings using the trained model."""
    if not bookings:
        return []
    feat_cols = ['lead_time','arrival_date_week_number','stays_in_weekend_nights',
                 'stays_in_week_nights','adults','is_repeated_guest',
                 'previous_cancellations','previous_bookings_not_canceled',
                 'booking_changes','days_in_waiting_list','adr','total_of_special_requests']
    rows_feat = []
    for b in bookings:
        is_corp = 1 if b['channel'] == 'Corporate' else 0
        rows_feat.append([b['lead'], b['week_num'], b['wkend'], b['wkday'],
                          b['adults'], is_corp, 0, 0, 0, 0, b['adr'], 0])
    df = pd.DataFrame(rows_feat, columns=feat_cols)
    return [float(s) for s in model.predict_proba(df)[:, 1] * 100]


def _parse_mice_data():
    """Parse RES_001 for MICE/corporate bookings and RES_033 for active group blocks."""
    path_res001 = os.path.join(_VDV_DIR, "RES_001_ArrivalDetailed (1).xlsx")
    path_res033 = os.path.join(_VDV_DIR, "RES_033_BillingInstructions.xlsx")
    MICE_SEGS = {'BNSGRP', 'CORPFIX', 'CORPDYN', 'MTGBNS'}
    SEG_LABELS = {
        'BNSGRP':  'Business Group',
        'CORPFIX': 'Corporate Fixed',
        'CORPDYN': 'Corporate Dynamic',
        'MTGBNS':  'Meeting Business',
    }
    result = {
        'total': 0,
        'total_nights': 0,
        'by_segment': {k: 0 for k in MICE_SEGS},
        'top_clients': [],
        'groups': [],
    }
    # --- Parse RES_001 for bookings ---
    if os.path.exists(path_res001):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(path_res001, read_only=True)
            rows = list(wb.active.iter_rows(values_only=True))
            wb.close()
            companies = {}
            for i in range(13, len(rows)):
                row = rows[i]
                if not row or len(row) < 18: continue
                market = str(row[17]).strip() if row[17] else ''
                if market not in MICE_SEGS: continue
                company = str(row[13]).strip() if row[13] else ''
                nights_raw = str(row[7]).strip() if row[7] else '0'
                room_type  = str(row[10]).strip() if row[10] else ''
                # Arrival date from col 4
                arr_raw = str(row[4]).strip() if row[4] else ''
                arr_date = arr_raw[:10] if arr_raw else ''
                try:
                    nights = int(nights_raw) if nights_raw.isdigit() else 1
                except:
                    nights = 1
                if company and company not in ('nan', 'Group', 'Company', 'Travel Agent', ''):
                    if company not in companies:
                        companies[company] = {'segment': SEG_LABELS.get(market, market),
                                              'seg_code': market, 'bookings': 0,
                                              'nights': 0, 'last_arrival': arr_date}
                    companies[company]['bookings'] += 1
                    companies[company]['nights']   += nights
                    if arr_date and arr_date > companies[company]['last_arrival']:
                        companies[company]['last_arrival'] = arr_date
                result['by_segment'][market] = result['by_segment'].get(market, 0) + 1
                result['total']        += 1
                result['total_nights'] += nights
            result['top_clients'] = sorted(
                [{'company': co, **data} for co, data in companies.items()],
                key=lambda x: -x['bookings']
            )[:12]
        except Exception as e:
            print(f"[VDV] MICE parse error (RES_001): {e}")
    # --- Parse RES_033 for group blocks ---
    if os.path.exists(path_res033):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(path_res033, read_only=True)
            rows = list(wb.active.iter_rows(values_only=True))
            wb.close()
            groups = {}
            for row in rows:
                if not row or row[0] is None: continue
                room = str(row[0]).strip()
                if not room or room in ('Room #', 'Res. Status', 'Totals', 'IH', 'CX'): continue
                try: int(room)  # must be a room number
                except: continue
                arr_raw  = str(row[7]).strip() if row[7] else ''
                dep_raw  = str(row[8]).strip() if row[8] else ''
                grp_raw  = str(row[10]).strip() if row[10] else ''
                company  = str(row[13]).strip() if row[13] else ''
                if not grp_raw or grp_raw == 'nan': continue
                # Parse group code and name from "MEC-GF10478 | Hyrox Mechelen 008646"
                parts = grp_raw.split('|')
                grp_code = parts[0].strip() if parts else grp_raw
                grp_name = parts[1].strip() if len(parts) > 1 else grp_code
                if grp_code not in groups:
                    groups[grp_code] = {
                        'code': grp_code, 'name': grp_name,
                        'company': company, 'rooms': [], 'arrival': arr_raw, 'departure': dep_raw
                    }
                groups[grp_code]['rooms'].append(room)
                if arr_raw and arr_raw < groups[grp_code]['arrival']:
                    groups[grp_code]['arrival'] = arr_raw
            result['groups'] = sorted(
                [g for g in groups.values() if len(g['rooms']) >= 2],
                key=lambda x: -len(x['rooms'])
            )
        except Exception as e:
            print(f"[VDV] MICE parse error (RES_033): {e}")
    return result


# Load VdV data once at startup
VDV_GUESTS_RAW      = []
VDV_CHANNEL_STATS   = {}
VDV_FUTURE_BOOKINGS = []
VDV_FUTURE_SCORES   = []
VDV_MICE_DATA       = {}
try:
    VDV_GUESTS_RAW      = _parse_vdv_guests()
    VDV_CHANNEL_STATS   = _parse_vdv_channel_stats()
    VDV_FUTURE_BOOKINGS = _parse_vdv_future_bookings()
    VDV_MICE_DATA       = _parse_mice_data()
    if VDV_FUTURE_BOOKINGS:
        VDV_FUTURE_SCORES = _score_vdv_future(VDV_FUTURE_BOOKINGS)
    print(f"[VDV] Loaded {len(VDV_GUESTS_RAW)} repeat guests, "
          f"{len(VDV_FUTURE_BOOKINGS)} future bookings, "
          f"{VDV_MICE_DATA.get('total',0)} MICE bookings, "
          f"channels: {list(VDV_CHANNEL_STATS.keys())}")
except Exception as _vdv_err:
    print(f"[VDV] Startup warning: {_vdv_err}")


def build_vdv_dashboard(hotel_name, lang="en", first_login=False):
    """VdV Mechelen dashboard — historical overview + current guests."""
    guests = VDV_GUESTS_RAW
    scores  = _score_vdv_guests(guests)
    ch_data = VDV_CHANNEL_STATS
    today   = datetime.now()
    today_str = today.strftime('%d %b %Y')

    # ── MICE data ────────────────────────────────────────────────────────────
    mice = VDV_MICE_DATA if VDV_MICE_DATA else {
        'total': 993, 'total_nights': 2163,
        'by_segment': {'BNSGRP': 179, 'CORPFIX': 443, 'CORPDYN': 173, 'MTGBNS': 198},
        'top_clients': [], 'groups': []
    }
    mice_total   = mice.get('total', 0)
    mice_nights  = mice.get('total_nights', 0)
    mice_seg     = mice.get('by_segment', {})
    mice_clients = mice.get('top_clients', [])
    mice_groups  = mice.get('groups', [])
    mice_avg_nights = round(mice_nights / mice_total, 1) if mice_total > 0 else 0
    # Estimated MICE revenue: avg corporate ADR €145 × avg nights
    mice_est_rev = int(mice_total * 145 * max(1, mice_avg_nights))
    mice_seg_js  = json.dumps([
        mice_seg.get('CORPFIX', 0), mice_seg.get('CORPDYN', 0),
        mice_seg.get('BNSGRP', 0),  mice_seg.get('MTGBNS', 0)
    ])

    # ── Historical numbers (real Shiji data) ───────────────────────────────
    MONTHS       = ['Oct 2025','Nov 2025','Dec 2025','Jan 2026','Feb 2026','Mar 2026']
    CX_MONTHLY   = [167, 315, 335, 255, 296, 318]   # cancellations per month
    NS_MONTHLY   = [43,  61,  75,  64,  58,  38]    # no-shows per month (verified from RES_037)
    LOST_MONTHLY = [c+n for c,n in zip(CX_MONTHLY, NS_MONTHLY)]

    total_cx     = sum(CX_MONTHLY)   # 1686
    total_ns     = sum(NS_MONTHLY)   # 339
    total_lost   = total_cx + total_ns   # 2025
    avg_adr      = 130.0
    avg_nights   = 1.8
    rev_lost     = int(total_lost * avg_adr * avg_nights)
    # Recoverable: 30% of cancellations + 25% of no-shows
    recoverable  = int(total_cx * 0.30 * avg_adr * avg_nights
                       + total_ns * 0.25 * avg_adr)

    # ── Future bookings risk (from RES_004 + model scoring) ────────────────
    fut_bookings = VDV_FUTURE_BOOKINGS
    fut_scores   = VDV_FUTURE_SCORES
    # Fallback pre-computed constants when files not loaded
    if not fut_bookings:
        fut_total     = 2795
        fut_high      = 735
        fut_med       = 1484
        fut_low       = 576
        fut_no_gtd    = 1149
        fut_table_html = ''
        fut_by_channel = {'Booking.com': 780, 'Direct/Web': 424, 'Corporate': 416,
                          'Package': 192, 'Other': 190}
        fut_month_labels = ['Mar 2026','Apr 2026','May 2026','Jun 2026',
                            'Jul 2026','Aug 2026','Sep 2026']
        fut_month_high   = [190, 267, 141, 68, 65, 36, 26]
        fut_month_med    = [148, 544, 297, 140, 136, 74, 58]
    else:
        fut_total = len(fut_bookings)
        fut_high  = sum(1 for s in fut_scores if s >= 70)
        fut_med   = sum(1 for s in fut_scores if 40 <= s < 70)
        fut_low   = sum(1 for s in fut_scores if s < 40)
        fut_no_gtd = sum(1 for b in fut_bookings if b['gtd'] == 'NONE')
        # Top 20 at-risk bookings table
        indexed = sorted(enumerate(fut_scores), key=lambda x: -x[1])[:20]
        fut_table_html = ''
        for rank, (idx, sc) in enumerate(indexed):
            b = fut_bookings[idx]
            ch = b['channel']
            gtd = b['gtd']
            if sc >= 70:
                bdg = f'<span class="badge high">{sc:.0f}%</span>'
                act = '<span class="abtn dep">Deposit</span>'
            elif sc >= 40:
                bdg = f'<span class="badge med">{sc:.0f}%</span>'
                act = '<span class="abtn rem">Reminder</span>'
            else:
                bdg = f'<span class="badge low">{sc:.0f}%</span>'
                act = '<span class="abtn mon">Monitor</span>'
            gtd_badge = ('<span class="gtd-none">No GTD</span>' if gtd == 'NONE'
                         else f'<span class="gtd-ok">{gtd}</span>')
            fut_table_html += (
                f'<tr><td>{rank+1}</td>'
                f'<td class="gn">{b["name"]}</td>'
                f'<td>{b["arrival"]}</td>'
                f'<td>{b["nights"]}n</td>'
                f'<td>{b["lead"]}d</td>'
                f'<td>{ch}</td>'
                f'<td>{gtd_badge}</td>'
                f'<td>{bdg}</td>'
                f'<td>{act}</td></tr>'
            )
        # Channel risk breakdown
        from collections import defaultdict
        ch_risk = defaultdict(lambda: {'high': 0, 'total': 0})
        for b, sc in zip(fut_bookings, fut_scores):
            ch_risk[b['channel']]['total'] += 1
            if sc >= 70: ch_risk[b['channel']]['high'] += 1
        fut_by_channel = {k: v['total'] for k, v in sorted(ch_risk.items(), key=lambda x: -x[1]['total'])}
        # Monthly risk
        from collections import Counter
        mo_high  = Counter()
        mo_med   = Counter()
        mo_total = Counter()
        for b, sc in zip(fut_bookings, fut_scores):
            mo_lbl = f"{b['arr_date'].strftime('%b')} {b['arr_date'].year}"
            mo_total[mo_lbl] += 1
            if sc >= 70: mo_high[mo_lbl] += 1
            elif sc >= 40: mo_med[mo_lbl] += 1
        # Sort months
        from datetime import datetime as _dt
        mo_sorted = sorted(mo_total.keys(),
                           key=lambda s: _dt.strptime(s, '%b %Y'))[:7]
        fut_month_labels = mo_sorted
        fut_month_high   = [mo_high.get(m, 0)  for m in mo_sorted]
        fut_month_med    = [mo_med.get(m, 0)   for m in mo_sorted]

    # ── Channel percentages ────────────────────────────────────────────────
    ch_total = sum(ch_data.values()) or 1
    ch_pcts  = {k: round(v/ch_total*100,1) for k,v in ch_data.items()}

    # ── Current guests ─────────────────────────────────────────────────────
    arriving   = [g for g in guests if g['status']=='Arriving Today']
    in_house   = [g for g in guests if g['status']=='In House']
    high_count = sum(1 for s in scores if s>=70)
    med_count  = sum(1 for s in scores if 40<=s<70)
    low_count  = sum(1 for s in scores if s<40)

    # ── Guest table rows ───────────────────────────────────────────────────
    def st_badge(s):
        if s=='Arriving Today': return '<span class="stb stb-a">Arriving Today</span>'
        if s=='In House':       return '<span class="stb stb-h">In House</span>'
        if s=='Checked Out':    return '<span class="stb stb-o">Checked Out</span>'
        return f'<span class="stb stb-f">{s}</span>'

    rows_html = ''
    for i,(g,sc) in enumerate(zip(guests,scores)):
        if sc>=70:
            bdg = f'<span class="badge high">{sc:.1f}%</span>'
            act = f'<button class="abtn dep" onclick="event.stopPropagation();openEmail({i},\'deposit\')">Deposit</button>'
        elif sc>=40:
            bdg = f'<span class="badge med">{sc:.1f}%</span>'
            act = f'<button class="abtn rem" onclick="event.stopPropagation();openEmail({i},\'reminder\')">Reminder</button>'
        else:
            bdg = f'<span class="badge low">{sc:.1f}%</span>'
            act = f'<button class="abtn mon" onclick="event.stopPropagation();openEmail({i},\'contact\')">Contact</button>'
        mb  = f' <span class="mb">{g["membership"]}</span>' if g.get('membership') else ''
        _note = g.get('note','')
        nt  = (f'<span class="nt" title="{_note}">{_note[:36]}{"..." if len(_note)>36 else ""}</span>' if _note else '&mdash;')
        rows_html += f'''<tr class="cr" onclick="openDetail({i},{sc:.1f})">
          <td><span class="gn">{g['name']}</span>{mb}</td>
          <td>{st_badge(g['status'])}</td>
          <td>{g['arrival']}</td><td>{g['nights']}n</td>
          <td>{bdg}</td><td class="ntd">{nt}</td><td>{act}</td>
        </tr>'''

    # ── Action plan items ──────────────────────────────────────────────────
    arriving_items = ''.join(
        f'<div class="pi"><b>{g["name"].split(",")[0]}</b> &mdash; {g.get("note") or "Prepare welcome"}</div>'
        for g in arriving
    ) or '<div class="pi empty">No arrivals today</div>'

    inhouse_items = ''.join(
        f'<div class="pi"><b>{g["name"].split(",")[0]}</b> &mdash; dep {g["departure"]}'
        + (f' · {g["note"][:50]}' if g.get('note') else '') + '</div>'
        for g in in_house
    ) or '<div class="pi empty">None in house</div>'

    # ── JS data ────────────────────────────────────────────────────────────
    guests_js       = json.dumps([{
        'name':g['name'],'arrival':g['arrival'],'departure':g.get('departure',''),
        'nights':g['nights'],'adults':g['adults'],'membership':g.get('membership',''),
        'status':g['status'],'note':g.get('note',''),'adr':149.0 if 'CORP' in g.get('membership','') else 115.0
    } for g in guests])
    scores_js       = json.dumps([round(s,1) for s in scores])
    months_js       = json.dumps(MONTHS)
    cx_js           = json.dumps(CX_MONTHLY)
    ns_js           = json.dumps(NS_MONTHLY)
    lost_js         = json.dumps(LOST_MONTHLY)
    ch_labels_js    = json.dumps(list(ch_data.keys()))
    ch_vals_js      = json.dumps(list(ch_data.values()))
    ch_pcts_js      = json.dumps([ch_pcts[k] for k in ch_data])
    gnames_js       = json.dumps([g['name'].split(',')[0] for g in guests])
    gcols_js        = json.dumps(['#dc2626' if s>=70 else ('#f59e0b' if s>=40 else '#22c55e') for s in scores])
    fut_mlabels_js  = json.dumps(fut_month_labels)
    fut_mhigh_js    = json.dumps(fut_month_high)
    fut_mmed_js     = json.dumps(fut_month_med)
    fut_ch_labels_js = json.dumps(list(fut_by_channel.keys()))
    fut_ch_vals_js   = json.dumps(list(fut_by_channel.values()))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Occupado — Van der Valk Mechelen</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*,*::before,*::after{{margin:0;padding:0;box-sizing:border-box;}}
body{{background:#f4f6f9;color:#0d1120;font-family:'Inter',sans-serif;-webkit-font-smoothing:antialiased;}}
a{{text-decoration:none;color:inherit;}}

/* TOPBAR */
.topbar{{height:58px;background:#fff;border-bottom:1px solid #e4e8f0;display:flex;align-items:center;padding:0 28px;position:sticky;top:0;z-index:100;gap:12px;}}
.tb-brand{{font-family:'Syne',sans-serif;font-size:16px;font-weight:800;color:#0d1120;letter-spacing:-.3px;}}
.tb-brand span{{color:#00d165;}}
.tb-hotel{{font-family:'JetBrains Mono',monospace;font-size:10px;color:#94a3b8;padding-left:12px;border-left:1px solid #e4e8f0;}}
.tb-right{{margin-left:auto;display:flex;gap:8px;align-items:center;}}
.tb-btn{{padding:6px 14px;border:1px solid #e4e8f0;border-radius:6px;font-size:12px;color:#64748b;background:transparent;cursor:pointer;font-family:'Inter',sans-serif;transition:all .15s;}}
.tb-btn:hover{{border-color:#cbd5e1;color:#0d1120;}}
.lang-sel{{padding:6px 10px;border:1px solid #e4e8f0;border-radius:6px;font-size:12px;color:#64748b;background:transparent;cursor:pointer;font-family:'Inter',sans-serif;outline:none;}}

/* LAYOUT */
.page{{max-width:1200px;margin:0 auto;padding:28px 28px 60px;}}
.row{{display:grid;gap:14px;margin-bottom:14px;}}
.row-3{{grid-template-columns:repeat(3,1fr);}}
.row-2{{grid-template-columns:1fr 1fr;}}
.row-2l{{grid-template-columns:2fr 1fr;}}
.row-hero{{grid-template-columns:1fr 1fr 1fr;}}

/* SECTION HEADER */
.sh{{display:flex;align-items:baseline;gap:10px;margin:28px 0 14px;}}
.sh-title{{font-family:'Syne',sans-serif;font-size:15px;font-weight:700;color:#0d1120;}}
.sh-sub{{font-family:'JetBrains Mono',monospace;font-size:10px;color:#94a3b8;}}

/* HERO METRICS */
.hero-card{{background:#0d1120;border-radius:14px;padding:28px 24px;color:#fff;position:relative;overflow:hidden;}}
.hero-card::after{{content:'';position:absolute;right:-20px;top:-20px;width:120px;height:120px;border-radius:50%;background:rgba(255,255,255,.03);}}
.hc-label{{font-family:'JetBrains Mono',monospace;font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:1px;margin-bottom:10px;}}
.hc-num{{font-family:'Syne',sans-serif;font-size:48px;font-weight:800;line-height:1;letter-spacing:-2px;}}
.hc-num.red{{color:#f87171;}}
.hc-num.green{{color:#00d165;}}
.hc-num.amber{{color:#fbbf24;}}
.hc-sub{{font-size:12px;color:#64748b;margin-top:8px;line-height:1.4;}}
.hc-tag{{display:inline-block;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.1);border-radius:4px;padding:3px 8px;font-family:'JetBrains Mono',monospace;font-size:10px;color:#94a3b8;margin-top:10px;}}

/* STANDARD CARDS */
.card{{background:#fff;border:1px solid #e4e8f0;border-radius:12px;padding:22px;}}
.card-title{{font-family:'Syne',sans-serif;font-size:13px;font-weight:700;color:#0d1120;margin-bottom:3px;}}
.card-sub{{font-family:'JetBrains Mono',monospace;font-size:10px;color:#94a3b8;margin-bottom:16px;text-transform:uppercase;letter-spacing:.5px;}}

/* STAT ROWS */
.stat-row{{display:flex;justify-content:space-between;align-items:center;padding:9px 0;border-bottom:1px solid #f1f5f9;font-size:12.5px;}}
.stat-row:last-child{{border-bottom:none;}}
.sr-label{{color:#64748b;}}
.sr-val{{font-family:'JetBrains Mono',monospace;font-weight:500;color:#0d1120;}}

/* TODAY STRIP */
.today-strip{{background:#fff;border:1px solid #e4e8f0;border-radius:12px;padding:16px 20px;display:grid;grid-template-columns:repeat(5,1fr);gap:0;margin-bottom:14px;}}
.ts-item{{text-align:center;padding:8px 0;border-right:1px solid #f1f5f9;}}
.ts-item:last-child{{border-right:none;}}
.ts-num{{font-family:'Syne',sans-serif;font-size:28px;font-weight:800;color:#0d1120;line-height:1;}}
.ts-num.g{{color:#00d165;}}
.ts-num.r{{color:#dc2626;}}
.ts-num.a{{color:#f59e0b;}}
.ts-label{{font-family:'JetBrains Mono',monospace;font-size:9px;color:#94a3b8;margin-top:4px;text-transform:uppercase;letter-spacing:.5px;}}

/* TABLE */
.tbl{{width:100%;border-collapse:collapse;background:#fff;border-radius:12px;overflow:hidden;border:1px solid #e4e8f0;}}
.tbl th{{background:#f8fafc;color:#94a3b8;font-family:'JetBrains Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:1px;padding:10px 12px;text-align:left;border-bottom:1px solid #e4e8f0;white-space:nowrap;}}
.tbl td{{padding:10px 12px;font-size:12px;border-bottom:1px solid #f8fafc;color:#374151;vertical-align:middle;}}
.cr{{cursor:pointer;transition:background .1s;}}
.cr:hover td{{background:#f8fafc;}}
.gn{{font-weight:600;color:#0d1120;font-size:12.5px;}}
.mb{{background:#eff6ff;color:#3b82f6;border:1px solid #bfdbfe;padding:1px 6px;border-radius:3px;font-family:'JetBrains Mono',monospace;font-size:9px;font-weight:600;margin-left:4px;}}
.badge{{padding:2px 8px;border-radius:99px;font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:600;border:1px solid;white-space:nowrap;}}
.high{{background:#fef2f2;color:#dc2626;border-color:#fecaca;}}
.med{{background:#fffbeb;color:#b45309;border-color:#fde68a;}}
.low{{background:#f0fdf4;color:#16a34a;border-color:#bbf7d0;}}
.abtn{{padding:4px 10px;border-radius:5px;font-size:10.5px;font-weight:500;cursor:pointer;border:1px solid;background:transparent;font-family:'Inter',sans-serif;transition:all .15s;white-space:nowrap;}}
.dep{{color:#dc2626;border-color:#fecaca;}}.dep:hover{{background:#fef2f2;}}
.rem{{color:#b45309;border-color:#fde68a;}}.rem:hover{{background:#fffbeb;}}
.mon{{color:#16a34a;border-color:#bbf7d0;}}.mon:hover{{background:#f0fdf4;}}
.stb{{padding:2px 8px;border-radius:99px;font-family:'JetBrains Mono',monospace;font-size:9px;font-weight:600;border:1px solid;white-space:nowrap;}}
.stb-a{{background:#fef3c7;color:#92400e;border-color:#fde68a;}}
.stb-h{{background:#eff6ff;color:#1d4ed8;border-color:#bfdbfe;}}
.stb-o{{background:#f8fafc;color:#94a3b8;border-color:#e4e8f0;}}
.stb-f{{background:#f0fdf4;color:#15803d;border-color:#bbf7d0;}}
.ntd{{max-width:180px;}}
.nt{{font-size:11px;color:#94a3b8;font-style:italic;}}

/* SAVINGS CARD */
.savings-card{{background:linear-gradient(135deg,#052e16,#0f2218);border-radius:12px;padding:24px;color:#fff;}}
.sv-row{{display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid rgba(255,255,255,.07);}}
.sv-row:last-child{{border-bottom:none;}}
.sv-label{{font-size:12.5px;color:#94a3b8;}}
.sv-val{{font-family:'JetBrains Mono',monospace;font-weight:600;color:#fff;}}
.sv-val.g{{color:#00d165;}}
.sv-val.r{{color:#f87171;}}
.slider-row{{margin-top:16px;}}
.slider-label{{font-family:'JetBrains Mono',monospace;font-size:10px;color:#94a3b8;margin-bottom:6px;display:flex;justify-content:space-between;}}
input[type=range]{{width:100%;accent-color:#00d165;cursor:pointer;}}
.slider-result{{margin-top:10px;font-family:'Syne',sans-serif;font-size:28px;font-weight:800;color:#00d165;}}
.slider-sub{{font-size:11px;color:#64748b;margin-top:2px;}}

/* ACTION PLAN */
.ap-grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px;}}
/* MICE */
.mice-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:18px;}}
.mice-card{{background:#fff;border:1px solid #e4e8f0;border-radius:12px;padding:18px 20px;}}
.mice-card.blue{{background:#eff6ff;border-color:#bfdbfe;}}
.mice-num{{font-family:'Syne',sans-serif;font-size:32px;font-weight:800;line-height:1;letter-spacing:-1px;color:#0d1120;}}
.mice-num.blue{{color:#1d4ed8;}}
.mice-lbl{{font-family:'JetBrains Mono',monospace;font-size:10px;color:#94a3b8;margin-top:5px;text-transform:uppercase;letter-spacing:1px;}}
.mice-sub{{font-size:11px;color:#64748b;margin-top:3px;}}
.mice-row{{display:grid;grid-template-columns:1fr 280px;gap:14px;margin-bottom:18px;align-items:start;}}
.mice-chart-card{{background:#fff;border:1px solid #e4e8f0;border-radius:12px;padding:18px 20px;}}
.mice-chart-title{{font-family:'Syne',sans-serif;font-size:13px;font-weight:700;color:#0d1120;margin-bottom:14px;}}
.mice-tbl{{width:100%;border-collapse:collapse;background:#fff;border-radius:12px;overflow:hidden;border:1px solid #e4e8f0;font-size:12px;}}
.mice-tbl th{{background:#f8fafc;color:#94a3b8;font-family:'JetBrains Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:1px;padding:10px 14px;text-align:left;border-bottom:1px solid #e4e8f0;}}
.mice-tbl td{{padding:10px 14px;border-bottom:1px solid #f1f5f9;color:#374151;}}
.mice-tbl tr:last-child td{{border-bottom:none;}}
.seg-pill{{display:inline-block;padding:2px 9px;border-radius:99px;font-size:10px;font-family:'JetBrains Mono',monospace;font-weight:500;border:1px solid;}}
.seg-corpfix{{background:#eff6ff;color:#1d4ed8;border-color:#bfdbfe;}}
.seg-corpdyn{{background:#f0fdf4;color:#15803d;border-color:#bbf7d0;}}
.seg-bnsgrp{{background:#fdf4ff;color:#7e22ce;border-color:#e9d5ff;}}
.seg-mtgbns{{background:#fff7ed;color:#c2410c;border-color:#fed7aa;}}
.grp-row{{display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid #f1f5f9;font-size:12px;}}
.grp-row:last-child{{border-bottom:none;}}
.grp-name{{font-weight:600;color:#0d1120;}}
.grp-co{{color:#64748b;font-size:11px;margin-top:2px;}}
.grp-rooms{{font-family:'JetBrains Mono',monospace;font-size:11px;color:#0d1120;font-weight:600;background:#f0fdf4;padding:3px 10px;border-radius:99px;border:1px solid #bbf7d0;color:#15803d;}}
.ap-card{{background:#fff;border:1px solid #e4e8f0;border-radius:12px;padding:20px;}}
.ap-head{{font-family:'Syne',sans-serif;font-size:13px;font-weight:700;color:#0d1120;margin-bottom:12px;display:flex;align-items:center;gap:8px;}}
.pi{{background:#f8fafc;border-radius:7px;padding:8px 11px;margin-bottom:6px;font-size:12px;line-height:1.5;color:#374151;}}
.pi b{{color:#0d1120;}}
.pi.empty{{color:#94a3b8;font-style:italic;}}
.ap-btn{{margin-top:12px;width:100%;padding:9px;background:#00d165;border:none;border-radius:7px;color:#080c14;font-size:12px;font-weight:700;cursor:pointer;font-family:'Inter',sans-serif;transition:all .15s;}}
.ap-btn:hover{{background:#04e270;}}
.ap-btn.ghost{{background:#fff;border:1px solid #e4e8f0;color:#0d1120;}}
.ap-btn.ghost:hover{{background:#f8fafc;}}

/* GTD BADGES */
.gtd-none{{background:#fef2f2;color:#dc2626;border:1px solid #fecaca;padding:1px 7px;border-radius:99px;font-family:'JetBrains Mono',monospace;font-size:9px;font-weight:600;white-space:nowrap;}}
.gtd-ok{{background:#f0fdf4;color:#16a34a;border:1px solid #bbf7d0;padding:1px 7px;border-radius:99px;font-family:'JetBrains Mono',monospace;font-size:9px;font-weight:600;white-space:nowrap;}}

/* ALERT CARD */
.alert-card{{background:#fff7ed;border:1px solid #fed7aa;border-radius:12px;padding:18px 20px;display:flex;align-items:center;gap:14px;}}
.alert-icon{{font-size:24px;flex-shrink:0;}}
.alert-body{{flex:1;}}
.alert-title{{font-family:'Syne',sans-serif;font-size:13px;font-weight:700;color:#9a3412;margin-bottom:2px;}}
.alert-sub{{font-size:11.5px;color:#c2410c;}}

/* FUTURE RISK STRIP */
.fstrip{{background:#fff;border:1px solid #e4e8f0;border-radius:12px;padding:16px 20px;display:grid;grid-template-columns:repeat(4,1fr);gap:0;margin-bottom:14px;}}
.fstrip .ts-item{{border-right:1px solid #f1f5f9;}}
.fstrip .ts-item:last-child{{border-right:none;}}

/* INSIGHT PILL */
.insight-row{{display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap;}}
.ip{{background:#fff;border:1px solid #e4e8f0;border-radius:99px;padding:5px 13px;font-size:11.5px;color:#374151;cursor:pointer;transition:all .15s;white-space:nowrap;}}
.ip:hover,.ip.active{{background:#0d1120;color:#fff;border-color:#0d1120;}}

/* MODAL */
.mo{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:1000;align-items:center;justify-content:center;backdrop-filter:blur(3px);}}
.mo.show{{display:flex;}}
.mb-inner{{background:#fff;border-radius:16px;padding:32px;width:100%;max-width:480px;max-height:88vh;overflow-y:auto;position:relative;box-shadow:0 16px 48px rgba(0,0,0,.12);}}
.mc{{position:absolute;top:12px;right:14px;font-size:18px;cursor:pointer;color:#94a3b8;background:none;border:none;}}
.mt{{font-family:'Syne',sans-serif;font-size:18px;font-weight:800;color:#0d1120;margin-bottom:2px;}}
.ms{{font-family:'JetBrains Mono',monospace;font-size:10px;color:#94a3b8;margin-bottom:16px;}}
.sd{{font-family:'Syne',sans-serif;font-size:52px;font-weight:800;line-height:1;margin-bottom:6px;}}
.sb-bg{{height:7px;background:#f1f5f9;border-radius:4px;overflow:hidden;margin-bottom:10px;}}
.sb-fill{{height:100%;border-radius:4px;}}
.sv-tag{{font-size:11.5px;font-weight:600;padding:5px 12px;border-radius:6px;display:inline-block;margin-bottom:14px;}}
.dr{{display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid #f1f5f9;font-size:12px;}}
.dr:last-child{{border-bottom:none;}}
.dl{{color:#64748b;}}
.dv{{font-family:'JetBrains Mono',monospace;color:#0d1120;font-weight:500;}}
.ri{{background:#f8fafc;border-radius:6px;padding:8px 11px;margin-bottom:5px;font-size:11.5px;color:#374151;border-left:3px solid #e4e8f0;}}
.ri.pos{{border-left-color:#00d165;}}
.ri.neg{{border-left-color:#f59e0b;}}

/* EMAIL COMPOSER */
.ec{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:1001;align-items:center;justify-content:center;backdrop-filter:blur(3px);}}
.ec.show{{display:flex;}}
.eb{{background:#fff;border-radius:16px;padding:28px;width:100%;max-width:560px;max-height:90vh;overflow-y:auto;box-shadow:0 16px 48px rgba(0,0,0,.12);}}
.el{{font-family:'JetBrains Mono',monospace;font-size:9.5px;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;display:block;margin-bottom:5px;font-weight:500;}}
.ei{{width:100%;padding:9px 12px;background:#f8fafc;border:1px solid #e4e8f0;border-radius:7px;font-size:13px;color:#0d1120;outline:none;margin-bottom:10px;font-family:'Inter',sans-serif;}}
.ei:focus{{border-color:#00d165;background:#fff;}}
.eta{{width:100%;padding:9px 12px;background:#f8fafc;border:1px solid #e4e8f0;border-radius:7px;font-size:12.5px;color:#0d1120;outline:none;resize:vertical;min-height:140px;margin-bottom:10px;font-family:'Inter',sans-serif;line-height:1.6;}}
.eta:focus{{border-color:#00d165;background:#fff;}}
.ea{{display:flex;gap:8px;margin-top:14px;}}
.es{{flex:1;padding:10px;background:#00d165;color:#080c14;border:none;border-radius:7px;font-size:12.5px;font-weight:700;cursor:pointer;font-family:'Inter',sans-serif;}}
.es:hover{{background:#04e270;}}
.ecc{{flex:1;padding:10px;background:#f8fafc;color:#64748b;border:1px solid #e4e8f0;border-radius:7px;font-size:12.5px;font-weight:500;cursor:pointer;}}

/* TOAST */
.toast{{position:fixed;bottom:22px;right:22px;background:#0d1120;color:#fff;border-radius:9px;padding:12px 16px;font-size:12.5px;transform:translateY(50px);opacity:0;transition:all .25s;z-index:2000;}}
.toast.show{{transform:translateY(0);opacity:1;}}
</style>
</head>
<body>

<div class="topbar">
  <span class="tb-brand">Occup<span>ado</span></span>
  <span class="tb-hotel">{hotel_name}</span>
  <div class="tb-right">
    <select class="lang-sel" onchange="location.href='/dashboard?lang='+this.value">
      <option value="en" {"selected" if lang=="en" else ""}>EN</option>
      <option value="nl" {"selected" if lang=="nl" else ""}>NL</option>
      <option value="fr" {"selected" if lang=="fr" else ""}>FR</option>
    </select>
    <a href="/settings" class="tb-btn">Settings</a>
    <a href="/logout" class="tb-btn">Sign Out</a>
  </div>
</div>

<div class="page">

<!-- HERO METRICS ─────────────────────────────────────────────────────── -->
<div class="sh"><span class="sh-title">6-Month Overview</span><span class="sh-sub">Oct 2025 – {today_str} · Shiji data</span></div>
<div class="row row-hero">
  <div class="hero-card">
    <div class="hc-label">Missed Stays</div>
    <div class="hc-num red">{total_lost:,}</div>
    <div class="hc-sub">{total_cx:,} cancellations + {total_ns} no-shows</div>
    <span class="hc-tag">avg {total_lost//6}/month</span>
  </div>
  <div class="hero-card">
    <div class="hc-label">Revenue Lost</div>
    <div class="hc-num amber">€{rev_lost//1000}k</div>
    <div class="hc-sub">Based on €{int(avg_adr)} ADR · {avg_nights} avg nights</div>
    <span class="hc-tag">€{rev_lost//6//1000}k/month avg</span>
  </div>
  <div class="hero-card">
    <div class="hc-label">Recoverable with AI</div>
    <div class="hc-num green">€{recoverable//1000}k</div>
    <div class="hc-sub">30% of cancellations preventable with early action</div>
    <span class="hc-tag">↑ adjust below</span>
  </div>
</div>

<!-- CHARTS ───────────────────────────────────────────────────────────── -->
<div class="sh"><span class="sh-title">Trends</span><span class="sh-sub">Monthly breakdown — click bars or points to filter</span></div>
<div class="row row-2">
  <div class="card">
    <div class="card-title">Cancellations & No-shows</div>
    <div class="card-sub">Per month — stacked</div>
    <canvas id="trendChart" height="160"></canvas>
  </div>
  <div class="card">
    <div class="card-title">Cancellation Sources</div>
    <div class="card-sub">{total_cx:,} total · share by channel</div>
    <canvas id="channelChart" height="160"></canvas>
  </div>
</div>

<!-- SAVINGS CALCULATOR ────────────────────────────────────────────────── -->
<div class="sh"><span class="sh-title">Savings Calculator</span><span class="sh-sub">Slide to adjust intervention rate</span></div>
<div class="row row-2l">
  <div class="savings-card">
    <div class="sv-row"><span class="sv-label">Cancellations tracked</span><span class="sv-val">{total_cx:,}</span></div>
    <div class="sv-row"><span class="sv-label">No-shows tracked</span><span class="sv-val">{total_ns}</span></div>
    <div class="sv-row"><span class="sv-label">Revenue lost (6 months)</span><span class="sv-val r">€{rev_lost:,}</span></div>
    <div class="slider-row">
      <div class="slider-label"><span>Intervention success rate</span><span id="rate-pct">30%</span></div>
      <input type="range" id="rate-slider" min="5" max="60" value="30" oninput="updateSavings(this.value)">
      <div class="slider-result" id="savings-num">€{recoverable:,}</div>
      <div class="slider-sub" id="savings-sub">estimated recoverable over 6 months</div>
    </div>
  </div>
  <div class="card">
    <div class="card-title">Key Insights</div>
    <div class="card-sub">From your Shiji data</div>
    <div class="stat-row"><span class="sr-label">Peak month</span><span class="sr-val">Dec 2025 (335 cx)</span></div>
    <div class="stat-row"><span class="sr-label">Best month</span><span class="sr-val">Oct 2025 (167 cx)</span></div>
    <div class="stat-row"><span class="sr-label">Top channel risk</span><span class="sr-val">Booking.com — {ch_pcts.get('Booking.com',0)}%</span></div>
    <div class="stat-row"><span class="sr-label">No-show rate</span><span class="sr-val">{round(total_ns/total_lost*100,1)}% of total</span></div>
    <div class="stat-row"><span class="sr-label">Model accuracy</span><span class="sr-val" style="color:#00d165">80.3%</span></div>
  </div>
</div>

<!-- TODAY ────────────────────────────────────────────────────────────── -->
<div class="sh"><span class="sh-title">Today</span><span class="sh-sub">{today_str}</span></div>
<div class="today-strip">
  <div class="ts-item"><div class="ts-num {'g' if len(arriving)>0 else ''}">{len(arriving)}</div><div class="ts-label">Arriving</div></div>
  <div class="ts-item"><div class="ts-num">{len(in_house)}</div><div class="ts-label">In House</div></div>
  <div class="ts-item"><div class="ts-num {'r' if high_count>0 else 'g'}">{high_count}</div><div class="ts-label">High Risk</div></div>
  <div class="ts-item"><div class="ts-num a">{med_count}</div><div class="ts-label">Medium Risk</div></div>
  <div class="ts-item"><div class="ts-num g">{low_count}</div><div class="ts-label">Low Risk</div></div>
</div>

<!-- FUTURE BOOKINGS RISK ─────────────────────────────────────────────── -->
<div class="sh"><span class="sh-title">Upcoming Bookings — Risk Forecast</span><span class="sh-sub">Apr – Dec 2026 · {fut_total:,} reservations scored</span></div>

<div class="alert-card" style="margin-bottom:14px;">
  <div class="alert-icon">&#9888;</div>
  <div class="alert-body">
    <div class="alert-title">{fut_no_gtd:,} bookings have no deposit or guarantee (GTD: NONE)</div>
    <div class="alert-sub">These reservations carry no financial commitment — highest no-show risk. Contact before arrival or request payment guarantee.</div>
  </div>
  <div style="font-family:'Syne',sans-serif;font-size:32px;font-weight:800;color:#ea580c;flex-shrink:0;">{round(fut_no_gtd/max(1,fut_total)*100)}%</div>
</div>

<div class="fstrip">
  <div class="ts-item"><div class="ts-num">{fut_total:,}</div><div class="ts-label">Total Upcoming</div></div>
  <div class="ts-item"><div class="ts-num r">{fut_high:,}</div><div class="ts-label">High Risk &ge;70%</div></div>
  <div class="ts-item"><div class="ts-num a">{fut_med:,}</div><div class="ts-label">Medium Risk 40–70%</div></div>
  <div class="ts-item"><div class="ts-num g">{fut_low:,}</div><div class="ts-label">Low Risk &lt;40%</div></div>
</div>

<div class="row row-2">
  <div class="card">
    <div class="card-title">Risk by Month</div>
    <div class="card-sub">High &amp; medium risk bookings per arrival month</div>
    <canvas id="futMonthChart" height="160"></canvas>
  </div>
  <div class="card">
    <div class="card-title">Risk by Channel</div>
    <div class="card-sub">Total upcoming bookings by source</div>
    <canvas id="futChannelChart" height="160"></canvas>
  </div>
</div>

{"" if not fut_table_html else f'''
<div class="sh"><span class="sh-title">Top 20 Highest-Risk Future Bookings</span><span class="sh-sub">Act now to prevent cancellation</span></div>
<table class="tbl">
<thead><tr>
  <th>#</th><th>Guest</th><th>Arrival</th><th>Nights</th><th>Lead</th><th>Channel</th><th>GTD</th><th>Risk</th><th>Action</th>
</tr></thead>
<tbody>{fut_table_html}</tbody>
</table>
'''}

<!-- GUEST TABLE ──────────────────────────────────────────────────────── -->
<div class="sh"><span class="sh-title">Repeat Guests This Week</span><span class="sh-sub">Click row for AI analysis</span></div>
<table class="tbl">
<thead><tr>
  <th>Guest</th><th>Status</th><th>Arrival</th><th>Nights</th><th>Risk</th><th>Notes</th><th>Action</th>
</tr></thead>
<tbody>{rows_html}</tbody>
</table>

<!-- ACTION PLAN ──────────────────────────────────────────────────────── -->
<div class="sh"><span class="sh-title">Action Plan</span><span class="sh-sub">Today</span></div>
<div class="ap-grid">
  <div class="ap-card">
    <div class="ap-head">🛬 Arrivals today ({len(arriving)})</div>
    {arriving_items}
    <button class="ap-btn" onclick="openBulk('welcome')">Send welcome email →</button>
  </div>
  <div class="ap-card">
    <div class="ap-head">🏨 In house ({len(in_house)})</div>
    {inhouse_items}
    <button class="ap-btn ghost" onclick="openBulk('departure')">Send departure reminder →</button>
  </div>
</div>

<!-- MICE & CORPORATE INTELLIGENCE ──────────────────────────────────── -->
<div class="sh"><span class="sh-title">MICE & Corporate Intelligence</span><span class="sh-sub">B2B · Meetings, Incentives, Conferences & Events</span></div>

<div class="mice-grid">
  <div class="mice-card blue">
    <div class="mice-num blue">{mice_total:,}</div>
    <div class="mice-lbl">MICE Bookings</div>
    <div class="mice-sub">in current dataset</div>
  </div>
  <div class="mice-card">
    <div class="mice-num">{mice_nights:,}</div>
    <div class="mice-lbl">Total Nights</div>
    <div class="mice-sub">{mice_avg_nights} avg per stay</div>
  </div>
  <div class="mice-card">
    <div class="mice-num" style="color:#15803d">€{mice_est_rev:,}</div>
    <div class="mice-lbl">Est. MICE Revenue</div>
    <div class="mice-sub">at €145 avg corporate ADR</div>
  </div>
  <div class="mice-card">
    <div class="mice-num">{len(mice_clients)}</div>
    <div class="mice-lbl">Corporate Accounts</div>
    <div class="mice-sub">active in period</div>
  </div>
</div>

<div class="mice-row">
  <div>
    <div class="mice-chart-title">Top Corporate Accounts</div>
    <table class="mice-tbl">
      <thead><tr><th>#</th><th>Company</th><th>Segment</th><th>Bookings</th><th>Nights</th><th>Avg Stay</th></tr></thead>
      <tbody>
        {"".join(
          f'<tr>'
          f'<td style="color:#94a3b8;font-family:monospace;font-size:11px">{i+1}</td>'
          f'<td style="font-weight:600;color:#0d1120">{c["company"]}</td>'
          f'<td><span class="seg-pill seg-{c["seg_code"].lower()}">{c["segment"]}</span></td>'
          f'<td style="font-family:monospace">{c["bookings"]}</td>'
          f'<td style="font-family:monospace">{c["nights"]}</td>'
          f'<td style="font-family:monospace">{round(c["nights"]/c["bookings"],1) if c["bookings"] else 0}n</td>'
          f'</tr>'
          for i, c in enumerate(mice_clients)
        ) if mice_clients else "<tr><td colspan='6' style='color:#94a3b8;text-align:center;padding:20px'>No data — local VDV-Data files required</td></tr>"}
      </tbody>
    </table>
  </div>
  <div class="mice-chart-card">
    <div class="mice-chart-title">Segment Mix</div>
    <canvas id="miceSegChart" height="200"></canvas>
    <div style="margin-top:14px">
      {"".join(
        f'<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid #f1f5f9;font-size:12px;">'
        f'<span style="color:#64748b">{lbl}</span>'
        f'<span style="font-family:monospace;font-weight:600">{cnt}</span>'
        f'</div>'
        for lbl, cnt in [
          ('Corporate Fixed (CORPFIX)', mice_seg.get('CORPFIX', 0)),
          ('Corporate Dynamic (CORPDYN)', mice_seg.get('CORPDYN', 0)),
          ('Business Group (BNSGRP)', mice_seg.get('BNSGRP', 0)),
          ('Meeting Business (MTGBNS)', mice_seg.get('MTGBNS', 0)),
        ]
      )}
    </div>
  </div>
</div>

{f"""<div class="mice-chart-title" style="margin-bottom:10px">Active Group Blocks</div>
<div style="background:#fff;border:1px solid #e4e8f0;border-radius:12px;padding:18px 20px;margin-bottom:18px;">
  {"".join(
    f'<div class="grp-row">'
    f'<div><div class="grp-name">{g["name"]}</div><div class="grp-co">{g["company"]} · {g["arrival"]} → {g["departure"]}</div></div>'
    f'<span class="grp-rooms">{len(g["rooms"])} rooms</span>'
    f'</div>'
    for g in mice_groups
  ) if mice_groups else '<div style="color:#94a3b8;font-size:12px;text-align:center;padding:12px">No active group blocks in dataset</div>'}
</div>""" if True else ""}

</div><!-- /page -->

<!-- DETAIL MODAL -->
<div class="mo" id="detailMo">
  <div class="mb-inner">
    <button class="mc" onclick="closeMo()">✕</button>
    <div class="mt" id="mo-name"></div>
    <div class="ms" id="mo-sub"></div>
    <div class="sd" id="mo-score"></div>
    <div class="sb-bg"><div class="sb-fill" id="mo-bar" style="width:0%"></div></div>
    <div class="sv-tag" id="mo-verd"></div>
    <div style="margin-top:14px;" id="mo-details"></div>
    <div style="margin-top:12px;font-family:'JetBrains Mono',monospace;font-size:9.5px;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;">Risk Factors</div>
    <div id="mo-reasons"></div>
    <div style="display:flex;gap:8px;margin-top:18px;">
      <button style="flex:1;padding:10px;background:#00d165;border:none;border-radius:7px;font-size:12.5px;font-weight:700;cursor:pointer;font-family:Inter,sans-serif;color:#080c14;" onclick="contactFromMo()">Contact Guest →</button>
      <button style="flex:1;padding:10px;background:#f8fafc;border:1px solid #e4e8f0;border-radius:7px;font-size:12.5px;font-weight:500;cursor:pointer;" onclick="closeMo()">Close</button>
    </div>
  </div>
</div>

<!-- EMAIL COMPOSER -->
<div class="ec" id="ecMo">
  <div class="eb">
    <div style="margin-bottom:16px;">
      <div style="font-family:'Syne',sans-serif;font-size:16px;font-weight:800;color:#0d1120;" id="ec-title">Email Guest</div>
      <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:#94a3b8;margin-top:2px;" id="ec-sub"></div>
    </div>
    <label class="el">To (email)</label><input type="email" id="ec-email" class="ei" placeholder="guest@example.com">
    <label class="el">Name</label><input type="text" id="ec-name" class="ei" placeholder="Guest name">
    <label class="el">Subject</label><input type="text" id="ec-subject" class="ei">
    <label class="el">Message</label><textarea id="ec-body" class="eta"></textarea>
    <div class="ea">
      <button class="es" onclick="sendEmail()">Send →</button>
      <button class="ecc" onclick="closeEc()">Cancel</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
const guests = {guests_js};
const scores = {scores_js};
let activeGuest = -1;

// ── CHARTS ────────────────────────────────────────────────────────────────────
const months   = {months_js};
const cxData   = {cx_js};
const nsData   = {ns_js};
const lostData = {lost_js};

const trendChart = new Chart(document.getElementById('trendChart'), {{
  type: 'bar',
  data: {{
    labels: months,
    datasets: [
      {{ label: 'Cancellations', data: cxData, backgroundColor: '#f87171', borderRadius: 4, borderWidth: 0, stack: 'a' }},
      {{ label: 'No-shows',      data: nsData, backgroundColor: '#fbbf24', borderRadius: 4, borderWidth: 0, stack: 'a' }}
    ]
  }},
  options: {{
    plugins: {{
      legend: {{ position:'bottom', labels:{{ font:{{family:'JetBrains Mono',size:10}},boxWidth:10,padding:12 }} }},
      tooltip: {{ callbacks: {{ afterBody: ctx => [`Total: ${{cxData[ctx[0].dataIndex]+nsData[ctx[0].dataIndex]}}`] }} }}
    }},
    scales: {{
      x: {{ grid:{{display:false}}, ticks:{{font:{{family:'JetBrains Mono',size:10}}}} }},
      y: {{ grid:{{color:'#f1f5f9'}}, ticks:{{font:{{family:'JetBrains Mono',size:10}},stepSize:50}} }}
    }},
    onClick: (e,el) => {{ if(el.length) filterByMonth(el[0].index); }},
    animation: {{ duration:700 }}
  }}
}});

const channelChart = new Chart(document.getElementById('channelChart'), {{
  type: 'bar',
  data: {{
    labels: {ch_labels_js},
    datasets: [{{ label:'Cancellations', data:{ch_vals_js}, backgroundColor:['#f87171','#fb923c','#60a5fa','#a78bfa','#94a3b8'], borderRadius:5, borderWidth:0 }}]
  }},
  options: {{
    indexAxis: 'y',
    plugins: {{
      legend:{{display:false}},
      tooltip:{{ callbacks:{{ label: ctx => ` ${{ctx.parsed.x}} (${{({ch_pcts_js})[ctx.dataIndex]}}%)` }} }}
    }},
    scales: {{
      x: {{ grid:{{color:'#f1f5f9'}}, ticks:{{font:{{family:'JetBrains Mono',size:10}}}} }},
      y: {{ grid:{{display:false}}, ticks:{{font:{{family:'JetBrains Mono',size:10}}}} }}
    }},
    animation: {{ duration:700 }}
  }}
}});

let filteredMonth = null;
function filterByMonth(idx) {{
  if (filteredMonth === idx) {{
    filteredMonth = null;
    channelChart.data.datasets[0].data = {ch_vals_js};
    channelChart.options.plugins.title = {{ display:false }};
  }} else {{
    filteredMonth = idx;
    // Show relative weight for selected month (proportional to share)
    const monthTotal = lostData[idx];
    const overall = lostData.reduce((a,b)=>a+b,0);
    const ratio = monthTotal/overall;
    const adjusted = {ch_vals_js}.map(v => Math.round(v*ratio));
    channelChart.data.datasets[0].data = adjusted;
    channelChart.options.plugins.title = {{ display:true, text: months[idx]+' estimate', font:{{family:'JetBrains Mono',size:10}}, color:'#94a3b8' }};
  }}
  channelChart.update();
}}

// ── FUTURE RISK CHARTS ────────────────────────────────────────────────────────
new Chart(document.getElementById('futMonthChart'), {{
  type: 'bar',
  data: {{
    labels: {fut_mlabels_js},
    datasets: [
      {{ label: 'High Risk', data: {fut_mhigh_js}, backgroundColor: '#f87171', borderRadius: 4, borderWidth: 0, stack: 'a' }},
      {{ label: 'Medium Risk', data: {fut_mmed_js}, backgroundColor: '#fbbf24', borderRadius: 4, borderWidth: 0, stack: 'a' }}
    ]
  }},
  options: {{
    plugins: {{ legend: {{ position:'bottom', labels:{{ font:{{family:'JetBrains Mono',size:10}},boxWidth:10,padding:10 }} }} }},
    scales: {{
      x: {{ grid:{{display:false}}, ticks:{{font:{{family:'JetBrains Mono',size:9}}}} }},
      y: {{ grid:{{color:'#f1f5f9'}}, ticks:{{font:{{family:'JetBrains Mono',size:10}}}} }}
    }},
    animation: {{ duration:700 }}
  }}
}});

new Chart(document.getElementById('futChannelChart'), {{
  type: 'doughnut',
  data: {{
    labels: {fut_ch_labels_js},
    datasets: [{{ data: {fut_ch_vals_js}, backgroundColor:['#f87171','#60a5fa','#a78bfa','#34d399','#94a3b8'], borderWidth:0, hoverOffset:6 }}]
  }},
  options: {{
    plugins: {{
      legend: {{ position:'right', labels:{{ font:{{family:'JetBrains Mono',size:10}},boxWidth:10,padding:8 }} }},
      tooltip: {{ callbacks: {{ label: ctx => ` ${{ctx.label}}: ${{ctx.parsed}} bookings` }} }}
    }},
    cutout: '62%',
    animation: {{ duration:700 }}
  }}
}});

// ── SAVINGS CALCULATOR ────────────────────────────────────────────────────────
const totalCx = {total_cx};
const totalNs = {total_ns};
const avgAdr  = {avg_adr};
const avgNights = {avg_nights};

function updateSavings(val) {{
  const pct = parseInt(val);
  document.getElementById('rate-pct').textContent = pct + '%';
  const saved = Math.round(totalCx * (pct/100) * avgAdr * avgNights
                           + totalNs * (pct/100) * 0.5 * avgAdr);
  document.getElementById('savings-num').textContent = '€' + saved.toLocaleString();
  document.getElementById('savings-sub').textContent =
    Math.round(totalCx*(pct/100)) + ' cancellations prevented · ' +
    Math.round(totalNs*(pct/100)*0.5) + ' no-shows charged';
}}

// ── DETAIL MODAL ──────────────────────────────────────────────────────────────
function openDetail(idx, score) {{
  const g = guests[idx]; activeGuest = idx;
  document.getElementById('mo-name').textContent = g.name;
  document.getElementById('mo-sub').textContent  = g.status + ' · ' + g.arrival + (g.departure?' – '+g.departure:'');
  document.getElementById('mo-score').textContent = score.toFixed(1)+'%';
  const bar = document.getElementById('mo-bar');
  const sd  = document.getElementById('mo-score');
  const vd  = document.getElementById('mo-verd');
  bar.style.width = score+'%';
  if (score>=70) {{
    bar.style.background='#dc2626'; sd.style.color='#dc2626';
    vd.textContent='HIGH RISK'; vd.style.background='#fef2f2'; vd.style.color='#dc2626';
  }} else if (score>=40) {{
    bar.style.background='#f59e0b'; sd.style.color='#f59e0b';
    vd.textContent='MEDIUM RISK'; vd.style.background='#fffbeb'; vd.style.color='#b45309';
  }} else {{
    bar.style.background='#00d165'; sd.style.color='#00d165';
    vd.textContent='LOW RISK'; vd.style.background='#f0fdf4'; vd.style.color='#16a34a';
  }}
  document.getElementById('mo-details').innerHTML = `
    <div class="dr"><span class="dl">Nights</span><span class="dv">${{g.nights}}</span></div>
    <div class="dr"><span class="dl">Adults</span><span class="dv">${{g.adults}}</span></div>
    <div class="dr"><span class="dl">Membership</span><span class="dv">${{g.membership||'—'}}</span></div>
    <div class="dr"><span class="dl">Rate</span><span class="dv">€${{g.adr}}/night</span></div>
    ${{g.note?`<div class="dr"><span class="dl">Notes</span><span class="dv" style="max-width:200px;text-align:right;font-size:11px">${{g.note}}</span></div>`:''}}
  `;
  const reasons = score<15
    ? [{{p:1,t:'Repeat guest — strong booking commitment'}},{{p:1,t:'Low lead time — very close to check-in'}},{{p:!!g.membership,t:g.membership?'Loyalty / corporate membership':'Standard booking — no loyalty flag'}}]
    : score<40
    ? [{{p:1,t:'Returning guest with positive history'}},{{p:0,t:'Slightly higher score — monitor recommended'}}]
    : [{{p:0,t:'Risk factors detected — proactive contact advised'}}];
  document.getElementById('mo-reasons').innerHTML = reasons.map(r =>
    `<div class="ri ${{r.p?'pos':'neg'}}">${{r.p?'✓':'⚠'}} ${{r.t}}</div>`).join('');
  document.getElementById('detailMo').classList.add('show');
}}
function closeMo() {{ document.getElementById('detailMo').classList.remove('show'); activeGuest=-1; }}
function contactFromMo() {{ closeMo(); if(activeGuest>=0) setTimeout(()=>openEmail(activeGuest,'contact'),80); }}

// ── EMAIL ─────────────────────────────────────────────────────────────────────
const TMPLS = {{
  contact:  {{subj:'Your upcoming stay at Van der Valk Hotel Mechelen', body:(n,arr,dep)=>`Dear ${{n}},\n\nWe look forward to welcoming you from ${{arr}} to ${{dep}}.\nPlease reach out if you have any requests.\n\nWarm regards,\nVan der Valk Hotel Mechelen`}},
  welcome:  {{subj:'Welcome to Van der Valk Hotel Mechelen', body:(n)=>`Dear ${{n}},\n\nWelcome! Your room is ready and our team is at your service.\n\nWarm regards,\nVan der Valk Hotel Mechelen`}},
  reminder: {{subj:'Your upcoming reservation', body:(n,arr,dep)=>`Dear ${{n}},\n\nThis is a reminder of your reservation from ${{arr}} to ${{dep}}.\nPlease confirm or contact us if your plans have changed.\n\nWarm regards,\nVan der Valk Hotel Mechelen`}},
  departure:{{subj:'Departure reminder — checkout tomorrow', body:(n,_,dep)=>`Dear ${{n}},\n\nCheckout is ${{dep}} at 12:00. Late checkout available on request.\nThank you for staying — we hope to see you again soon.\n\nWarm regards,\nVan der Valk Hotel Mechelen`}},
  deposit:  {{subj:'Reservation guarantee required', body:(n,arr,dep)=>`Dear ${{n}},\n\nTo secure your reservation from ${{arr}} to ${{dep}}, a deposit is required.\nPlease contact us at your earliest convenience.\n\nWarm regards,\nVan der Valk Hotel Mechelen`}},
  upsell:   {{subj:'Exclusive offers for your stay', body:(n)=>`Dear ${{n}},\n\nWe hope you are enjoying your time with us!\nToday's offers: restaurant priority, parking upgrade, late checkout.\n\nWarm regards,\nVan der Valk Hotel Mechelen`}}
}};

function openEmail(idx, type) {{
  const g  = guests[idx]; activeGuest=idx;
  const fn = g.name.split(',').slice(1).join(',').trim().split(' ').filter(Boolean)[0] || g.name.split(',')[0];
  const t  = TMPLS[type]||TMPLS.contact;
  document.getElementById('ec-title').textContent = 'Email — '+g.name;
  document.getElementById('ec-sub').textContent   = g.status+' · '+g.arrival+(g.departure?' – '+g.departure:'');
  document.getElementById('ec-name').value    = g.name;
  document.getElementById('ec-email').value   = '';
  document.getElementById('ec-subject').value = t.subj;
  document.getElementById('ec-body').value    = t.body(fn, g.arrival, g.departure);
  document.getElementById('ecMo').classList.add('show');
}}

function openBulk(type) {{
  const t = TMPLS[type]||TMPLS.welcome;
  document.getElementById('ec-title').textContent = 'Bulk — '+type;
  document.getElementById('ec-sub').textContent   = 'Fill in guest details per send';
  document.getElementById('ec-name').value    = '';
  document.getElementById('ec-email').value   = '';
  document.getElementById('ec-subject').value = t.subj;
  document.getElementById('ec-body').value    = t.body('[Guest Name]','[Arrival]','[Departure]');
  document.getElementById('ecMo').classList.add('show');
}}

function closeEc() {{ document.getElementById('ecMo').classList.remove('show'); }}

function sendEmail() {{
  const email=document.getElementById('ec-email').value.trim();
  const subj =document.getElementById('ec-subject').value.trim();
  const body =document.getElementById('ec-body').value.trim();
  if(!email||!subj||!body){{ toast('Fill in all fields','e'); return; }}
  fetch('/send-guest-email',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{guest_email:email,subject:subj,body}})}})
    .then(r=>r.json()).then(d=>{{ closeEc(); toast(d.status==='success'?'✓ Sent':'Error: '+d.message, d.status==='success'?'s':'e'); }})
    .catch(()=>toast('Error','e'));
}}

// ── UTILS ─────────────────────────────────────────────────────────────────────
function toast(msg,type){{
  const el=document.getElementById('toast');
  el.textContent=msg; el.style.background=type==='e'?'#dc2626':'#0d1120';
  el.classList.add('show'); setTimeout(()=>el.classList.remove('show'),3000);
}}
document.getElementById('detailMo').onclick = e=>{{ if(e.target===document.getElementById('detailMo')) closeMo(); }};
document.getElementById('ecMo').onclick     = e=>{{ if(e.target===document.getElementById('ecMo')) closeEc(); }};

// MICE segment doughnut
(function() {{
  const ctx = document.getElementById('miceSegChart');
  if (!ctx) return;
  new Chart(ctx, {{
    type: 'doughnut',
    data: {{
      labels: ['Corporate Fixed', 'Corporate Dynamic', 'Business Group', 'Meeting Business'],
      datasets: [{{
        data: {mice_seg_js},
        backgroundColor: ['#bfdbfe','#bbf7d0','#e9d5ff','#fed7aa'],
        borderColor:      ['#1d4ed8','#15803d','#7e22ce','#c2410c'],
        borderWidth: 1.5
      }}]
    }},
    options: {{
      cutout: '62%',
      plugins: {{
        legend: {{ display: false }}
      }}
    }}
  }});
}})();
</script>
</body>
</html>"""
    today     = datetime.now()

    arriving_today  = [g for g in guests if g['status'] == 'Arriving Today']
    in_house        = [g for g in guests if g['status'] == 'In House']
    checked_out     = [g for g in guests if g['status'] == 'Checked Out']
    departing_tmrw  = [g for g, s in zip(guests, scores)
                       if g.get('dep_date') and (g['dep_date'] - today).days == 1]

    # Risk counts
    high_count = sum(1 for s in scores if s >= 70)
    med_count  = sum(1 for s in scores if 40 <= s < 70)
    low_count  = sum(1 for s in scores if s < 40)
    avg_score  = (sum(scores) / len(scores)) if scores else 0

    # Revenue context
    avg_adr = 130.0
    rev_arriving = len(arriving_today) * avg_adr * 1.5  # avg ~1.5 nights
    rev_inhouse  = len(in_house) * avg_adr * 1.2

    # Chart data — risk donut
    risk_donut_js    = json.dumps([low_count, med_count, high_count])
    risk_donut_pct_js = json.dumps([
        round(low_count / len(scores) * 100) if scores else 0,
        round(med_count / len(scores) * 100) if scores else 0,
        round(high_count / len(scores) * 100) if scores else 0,
    ])

    # Chart data — channel cancellations
    ch_labels = json.dumps(list(ch_data.keys()))
    ch_values = json.dumps(list(ch_data.values()))
    ch_pcts   = json.dumps([round(v / sum(ch_data.values()) * 100, 1) if ch_data else 0 for v in ch_data.values()])

    # Chart data — guest risk scores bar
    guest_names_js = json.dumps([g['name'].split(',')[0] for g in guests])
    guest_scores_js = json.dumps([round(s, 1) for s in scores])
    guest_colors_js = json.dumps([
        '#dc2626' if s >= 70 else ('#f59e0b' if s >= 40 else '#00d165')
        for s in scores
    ])

    # Build table rows
    rows_html = ""
    for i, (g, score) in enumerate(zip(guests, scores)):
        if score >= 70:
            badge  = f'<span class="badge high">HIGH {score:.1f}%</span>'
            action = f'<button class="btn dep" onclick="event.stopPropagation();openVdvEmail({i},\'deposit\')">Request Deposit</button>'
        elif score >= 40:
            badge  = f'<span class="badge med">MEDIUM {score:.1f}%</span>'
            action = f'<button class="btn rem" onclick="event.stopPropagation();openVdvEmail({i},\'reminder\')">Send Reminder</button>'
        else:
            badge  = f'<span class="badge low">LOW {score:.1f}%</span>'
            action = f'<button class="btn mon" onclick="event.stopPropagation();openVdvEmail({i},\'contact\')">Contact Guest</button>'

        # Status badge
        if g['status'] == 'Arriving Today':
            st_badge = '<span class="st-badge st-arriving">Arriving Today</span>'
        elif g['status'] == 'In House':
            st_badge = '<span class="st-badge st-inhouse">In House</span>'
        elif g['status'] == 'Checked Out':
            st_badge = '<span class="st-badge st-out">Checked Out</span>'
        else:
            st_badge = f'<span class="st-badge st-future">{g["status"]}</span>'

        memb = g.get('membership', '')
        memb_badge = f' <span class="memb-badge">{memb}</span>' if memb else ''
        note_html  = f'<span class="guest-note" title="{g["note"]}">{g["note"][:38]}…</span>' if g.get('note') and len(g['note']) > 38 else (f'<span class="guest-note">{g.get("note","")}</span>' if g.get('note') else '—')

        rows_html += f"""<tr class="clickable-row" onclick="showVdvDetail({i},{score:.1f})">
            <td><span class="guest-name">{g['name']}</span>{memb_badge}</td>
            <td>{st_badge}</td>
            <td>{g['arrival']}</td>
            <td>{g.get('departure','—')}</td>
            <td>{g['nights']} night{'s' if g['nights']!=1 else ''}</td>
            <td>{g['adults']}</td>
            <td>{badge}</td>
            <td class="note-cell">{note_html}</td>
            <td>{action}</td>
        </tr>"""

    # Action plan cards
    arriving_plan = ""
    for g in arriving_today:
        specific = g.get('note', '')
        tip = specific if specific else 'Prepare welcome, confirm room assignment'
        arriving_plan += f'<div class="plan-item"><div class="plan-guest">{g["name"]}</div><div class="plan-tip">{tip}</div></div>'
    if not arriving_plan:
        arriving_plan = '<div class="plan-empty">No arrivals today</div>'

    inhouse_plan = ""
    for g in in_house:
        dep = g.get('dep_date')
        days_left = (dep - today).days if dep else '?'
        tip = f'{days_left} night{"s" if days_left != 1 else ""} remaining'
        if g.get('note'):
            tip = g['note'] + ' · ' + tip
        inhouse_plan += f'<div class="plan-item"><div class="plan-guest">{g["name"]}</div><div class="plan-tip">{tip}</div></div>'
    if not inhouse_plan:
        inhouse_plan = '<div class="plan-empty">No guests currently in house</div>'

    # Guests JSON for JS
    guests_js = json.dumps([{
        'name': g['name'], 'arrival': g['arrival'], 'departure': g.get('departure',''),
        'nights': g['nights'], 'adults': g['adults'], 'membership': g.get('membership',''),
        'status': g['status'], 'note': g.get('note',''), 'adr': 149.0 if 'CORP' in g.get('membership','') else 115.0
    } for g in guests])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Occupado — Van der Valk Hotel Mechelen</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*,*::before,*::after{{margin:0;padding:0;box-sizing:border-box;}}
body{{background:#f5f7fb;color:#0d1120;font-family:'Inter',sans-serif;-webkit-font-smoothing:antialiased;}}
a{{text-decoration:none;}}
/* TOPBAR */
.topbar{{height:62px;background:#ffffff;border-bottom:1px solid #e4e8f0;display:flex;align-items:center;padding:0 32px;position:sticky;top:0;z-index:100;}}
.topbar-brand{{display:flex;align-items:center;gap:6px;}}
.topbar-name{{font-family:'Syne',sans-serif;font-size:17px;font-weight:800;color:#0d1120;letter-spacing:-0.4px;}}
.topbar-name span{{color:#00d165;}}
.topbar-hotel{{font-family:'JetBrains Mono',monospace;font-size:11px;color:#94a3b8;margin-left:8px;padding-left:12px;border-left:1px solid #e4e8f0;}}
.topbar-right{{display:flex;align-items:center;gap:8px;margin-left:auto;}}
.btn-nav{{padding:7px 16px;background:transparent;border:1px solid #e4e8f0;border-radius:7px;color:#64748b;font-size:12px;font-weight:500;text-decoration:none;transition:all .2s;}}
.btn-nav:hover{{border-color:#cbd5e1;color:#0d1120;}}
.lang-selector{{padding:7px 12px;background:transparent;border:1px solid #e4e8f0;border-radius:7px;color:#64748b;font-size:12px;cursor:pointer;font-family:'Inter',sans-serif;outline:none;}}
/* HERO */
.hero{{background:linear-gradient(135deg,#0d1120 0%,#0f2218 100%);padding:40px 32px 36px;margin-bottom:0;}}
.hero-eyebrow{{font-family:'JetBrains Mono',monospace;font-size:11px;color:#00d165;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:10px;}}
.hero-title{{font-family:'Syne',sans-serif;font-size:32px;font-weight:800;color:#ffffff;letter-spacing:-0.8px;margin-bottom:6px;}}
.hero-sub{{font-size:13px;color:#94a3b8;}}
.hero-badges{{display:flex;gap:10px;margin-top:16px;flex-wrap:wrap;}}
.hero-badge{{background:rgba(0,209,101,0.12);border:1px solid rgba(0,209,101,0.25);border-radius:6px;padding:5px 12px;font-family:'JetBrains Mono',monospace;font-size:11px;color:#00d165;}}
.hero-badge.warn{{background:rgba(245,158,11,0.12);border-color:rgba(245,158,11,0.25);color:#f59e0b;}}
.hero-badge.info{{background:rgba(148,163,184,0.12);border-color:rgba(148,163,184,0.25);color:#94a3b8;}}
/* CONTENT */
.content{{padding:28px 32px;}}
.section-title{{font-family:'Syne',sans-serif;font-size:17px;font-weight:700;color:#0d1120;letter-spacing:-0.3px;margin-bottom:14px;margin-top:32px;}}
.section-sub{{font-family:'JetBrains Mono',monospace;font-size:10px;color:#94a3b8;margin-top:-10px;margin-bottom:16px;text-transform:uppercase;letter-spacing:0.5px;}}
/* KPI GRID */
.kpi-grid{{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin-bottom:12px;}}
.kpi-card{{background:#ffffff;border:1px solid #e4e8f0;border-radius:12px;padding:18px 20px;}}
.kpi-num{{font-family:'Syne',sans-serif;font-size:36px;font-weight:800;line-height:1;letter-spacing:-1.5px;}}
.kpi-label{{font-family:'JetBrains Mono',monospace;font-size:10px;color:#94a3b8;margin-top:5px;text-transform:uppercase;letter-spacing:0.8px;line-height:1.4;}}
.kpi-trend{{font-size:11px;margin-top:4px;font-weight:500;}}
.kpi-num.green{{color:#00d165;}}
.kpi-num.red{{color:#dc2626;}}
.kpi-num.orange{{color:#f59e0b;}}
.kpi-num.blue{{color:#3b82f6;}}
.kpi-num.neutral{{color:#0d1120;}}
.kpi-card.highlight-green{{border-color:#bbf7d0;background:#f0fdf4;}}
.kpi-card.highlight-red{{border-color:#fecaca;background:#fef2f2;}}
/* CHARTS ROW */
.charts-row{{display:grid;grid-template-columns:1fr 2fr 2fr;gap:14px;margin-bottom:28px;}}
.chart-card{{background:#ffffff;border:1px solid #e4e8f0;border-radius:14px;padding:22px;}}
.chart-title{{font-family:'Syne',sans-serif;font-size:14px;font-weight:700;color:#0d1120;letter-spacing:-0.2px;margin-bottom:4px;}}
.chart-sub{{font-family:'JetBrains Mono',monospace;font-size:10px;color:#94a3b8;margin-bottom:14px;text-transform:uppercase;letter-spacing:0.5px;}}
.donut-center{{text-align:center;margin-top:8px;}}
.donut-big{{font-family:'Syne',sans-serif;font-size:28px;font-weight:800;color:#00d165;}}
.donut-label{{font-family:'JetBrains Mono',monospace;font-size:10px;color:#94a3b8;}}
/* TABLE */
table{{width:100%;border-collapse:collapse;background:#ffffff;border-radius:14px;overflow:hidden;border:1px solid #e4e8f0;margin-bottom:28px;}}
th{{background:#f8fafc;color:#94a3b8;font-family:'JetBrains Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:1px;padding:12px 14px;text-align:left;border-bottom:1px solid #e4e8f0;white-space:nowrap;}}
td{{padding:12px 14px;font-size:12.5px;border-bottom:1px solid #f1f5f9;color:#374151;vertical-align:middle;}}
.clickable-row{{cursor:pointer;}}
.clickable-row:hover td{{background:#f8fafc;}}
.guest-name{{font-weight:600;color:#0d1120;font-size:13px;}}
.memb-badge{{background:#eff6ff;color:#3b82f6;border:1px solid #bfdbfe;padding:2px 7px;border-radius:4px;font-family:'JetBrains Mono',monospace;font-size:9px;font-weight:600;margin-left:4px;}}
.badge{{padding:3px 9px;border-radius:99px;font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:600;border:1px solid;white-space:nowrap;}}
.high{{background:#fef2f2;color:#dc2626;border-color:#fecaca;}}
.med{{background:#fffbeb;color:#b45309;border-color:#fde68a;}}
.low{{background:#f0fdf4;color:#16a34a;border-color:#bbf7d0;}}
.btn{{padding:5px 12px;border-radius:6px;font-size:11px;font-weight:500;cursor:pointer;border:1px solid;background:transparent;font-family:'Inter',sans-serif;transition:all .2s;white-space:nowrap;}}
.dep{{color:#dc2626;border-color:#fecaca;}}.dep:hover{{background:#fef2f2;}}
.rem{{color:#b45309;border-color:#fde68a;}}.rem:hover{{background:#fffbeb;}}
.mon{{color:#16a34a;border-color:#bbf7d0;}}.mon:hover{{background:#f0fdf4;}}
/* STATUS BADGES */
.st-badge{{padding:3px 9px;border-radius:99px;font-family:'JetBrains Mono',monospace;font-size:9px;font-weight:600;border:1px solid;white-space:nowrap;}}
.st-arriving{{background:#fef3c7;color:#92400e;border-color:#fde68a;}}
.st-inhouse{{background:#eff6ff;color:#1d4ed8;border-color:#bfdbfe;}}
.st-out{{background:#f8fafc;color:#94a3b8;border-color:#e4e8f0;}}
.st-future{{background:#f0fdf4;color:#15803d;border-color:#bbf7d0;}}
.note-cell{{max-width:200px;overflow:hidden;}}
.guest-note{{font-size:11px;color:#64748b;font-style:italic;}}
/* ACTION PLAN */
.action-plan-grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:28px;}}
.plan-card{{background:#ffffff;border:1px solid #e4e8f0;border-radius:14px;padding:22px;}}
.plan-card-header{{display:flex;align-items:center;gap:10px;margin-bottom:14px;}}
.plan-icon{{width:36px;height:36px;border-radius:9px;display:flex;align-items:center;justify-content:center;font-size:16px;flex-shrink:0;}}
.plan-icon.arriving{{background:#fef3c7;}}
.plan-icon.inhouse{{background:#eff6ff;}}
.plan-icon.intel{{background:#f0fdf4;}}
.plan-icon.bulk{{background:#faf5ff;}}
.plan-card-title{{font-family:'Syne',sans-serif;font-size:14px;font-weight:700;color:#0d1120;}}
.plan-card-sub{{font-family:'JetBrains Mono',monospace;font-size:10px;color:#94a3b8;}}
.plan-item{{background:#f8fafc;border:1px solid #e4e8f0;border-radius:8px;padding:10px 12px;margin-bottom:8px;}}
.plan-item:last-child{{margin-bottom:0;}}
.plan-guest{{font-weight:600;font-size:12px;color:#0d1120;margin-bottom:3px;}}
.plan-tip{{font-size:11.5px;color:#64748b;line-height:1.4;}}
.plan-empty{{font-family:'JetBrains Mono',monospace;font-size:11px;color:#94a3b8;padding:10px;}}
.plan-action-btn{{margin-top:12px;width:100%;padding:9px;background:#ffffff;border:1px solid #e4e8f0;border-radius:8px;color:#0d1120;font-size:12px;font-weight:600;cursor:pointer;font-family:'Inter',sans-serif;transition:all .2s;}}
.plan-action-btn:hover{{background:#f1f5f9;}}
.plan-action-btn.green-btn{{background:#00d165;border-color:#00d165;color:#080c14;}}
.plan-action-btn.green-btn:hover{{background:#04e270;}}
/* INTEL CARDS */
.intel-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:8px;}}
.intel-item{{background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:12px;}}
.intel-item.warn{{background:#fffbeb;border-color:#fde68a;}}
.intel-item.info{{background:#eff6ff;border-color:#bfdbfe;}}
.intel-num{{font-family:'Syne',sans-serif;font-size:22px;font-weight:800;color:#15803d;line-height:1;}}
.intel-num.warn{{color:#92400e;}}
.intel-num.info{{color:#1d4ed8;}}
.intel-label{{font-family:'JetBrains Mono',monospace;font-size:9px;color:#64748b;margin-top:4px;text-transform:uppercase;letter-spacing:0.5px;}}
/* OPTIMIZER */
.optimizer-card{{background:#ffffff;border:1px solid #e4e8f0;border-radius:14px;padding:24px;margin-bottom:28px;}}
.optimizer-row{{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:12px;margin-bottom:18px;}}
.opt-stat{{background:#f8fafc;border:1px solid #e4e8f0;border-radius:9px;padding:14px;}}
.opt-stat-val{{font-family:'Syne',sans-serif;font-size:26px;font-weight:800;color:#0d1120;line-height:1;}}
.opt-stat-label{{font-family:'JetBrains Mono',monospace;font-size:9px;color:#94a3b8;margin-top:4px;text-transform:uppercase;}}
/* BULK ACTIONS */
.bulk-zone{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:28px;}}
.bulk-card{{background:#f8fafc;border:1px solid #e4e8f0;border-radius:12px;padding:20px;transition:border-color .2s;}}
.bulk-card:hover{{border-color:#cbd5e1;}}
.bulk-icon{{font-size:24px;margin-bottom:8px;}}
.bulk-card-title{{font-family:'Syne',sans-serif;font-size:13px;font-weight:700;color:#0d1120;margin-bottom:4px;}}
.bulk-card-sub{{font-size:12px;color:#64748b;margin-bottom:14px;line-height:1.4;}}
.bulk-btn{{padding:9px 14px;background:#ffffff;border:1px solid #e4e8f0;border-radius:8px;color:#0d1120;font-size:12px;font-weight:600;cursor:pointer;width:100%;font-family:'Inter',sans-serif;transition:all .2s;}}
.bulk-btn:hover{{background:#f1f5f9;}}
.bulk-btn.green-btn{{background:#00d165;border-color:#00d165;color:#080c14;}}
.bulk-btn.green-btn:hover{{background:#04e270;}}
/* MODAL */
.modal-overlay{{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:1000;align-items:center;justify-content:center;backdrop-filter:blur(4px);}}
.modal-overlay.show{{display:flex;}}
.modal{{background:#ffffff;border:1px solid #e4e8f0;border-radius:20px;padding:36px;width:100%;max-width:520px;max-height:88vh;overflow-y:auto;position:relative;box-shadow:0 16px 48px rgba(0,0,0,0.1);}}
.modal-close{{position:absolute;top:14px;right:16px;font-size:20px;cursor:pointer;color:#94a3b8;background:none;border:none;}}
.modal-title{{font-family:'Syne',sans-serif;font-size:20px;font-weight:800;color:#0d1120;margin-bottom:2px;}}
.modal-sub{{font-family:'JetBrains Mono',monospace;font-size:11px;color:#94a3b8;margin-bottom:18px;}}
.score-display{{font-family:'Syne',sans-serif;font-size:56px;font-weight:800;line-height:1;margin-bottom:6px;}}
.score-bar-bg{{height:8px;background:#f1f5f9;border-radius:4px;overflow:hidden;margin-bottom:10px;}}
.score-bar-fill{{height:100%;border-radius:4px;}}
.score-verdict{{font-size:12px;font-weight:600;padding:6px 12px;border-radius:6px;display:inline-block;margin-bottom:14px;}}
.modal-section{{margin-bottom:14px;}}
.modal-section-title{{font-family:'JetBrains Mono',monospace;font-size:10px;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;}}
.modal-detail-row{{display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid #f1f5f9;font-size:12.5px;}}
.modal-detail-row:last-child{{border-bottom:none;}}
.modal-detail-label{{color:#64748b;}}
.modal-detail-val{{font-family:'JetBrains Mono',monospace;color:#0d1120;font-weight:500;}}
.reason-item{{background:#f8fafc;border-radius:7px;padding:10px 12px;margin-bottom:6px;font-size:12px;color:#374151;line-height:1.5;border-left:3px solid #e4e8f0;}}
.reason-item.pos{{border-left-color:#00d165;}}
.reason-item.neg{{border-left-color:#f59e0b;}}
/* EMAIL COMPOSER */
.email-composer{{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:1001;align-items:center;justify-content:center;backdrop-filter:blur(4px);}}
.email-composer.show{{display:flex;}}
.email-box{{background:#ffffff;border:1px solid #e4e8f0;border-radius:20px;padding:32px;width:100%;max-width:600px;max-height:90vh;overflow-y:auto;box-shadow:0 16px 48px rgba(0,0,0,0.1);}}
.email-title{{font-family:'Syne',sans-serif;font-size:17px;font-weight:800;color:#0d1120;margin-bottom:2px;}}
.email-label{{font-family:'JetBrains Mono',monospace;font-size:10px;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;display:block;margin-bottom:6px;font-weight:500;}}
.email-input{{width:100%;padding:10px 13px;background:#f8fafc;border:1px solid #e4e8f0;border-radius:8px;font-size:13px;color:#0d1120;outline:none;margin-bottom:12px;font-family:'Inter',sans-serif;}}
.email-input:focus{{border-color:#00d165;background:#fff;}}
.email-textarea{{width:100%;padding:10px 13px;background:#f8fafc;border:1px solid #e4e8f0;border-radius:8px;font-size:12.5px;color:#0d1120;outline:none;resize:vertical;min-height:160px;margin-bottom:12px;font-family:'Inter',sans-serif;line-height:1.6;}}
.email-textarea:focus{{border-color:#00d165;background:#fff;}}
.email-actions{{display:flex;gap:10px;margin-top:16px;}}
.email-send{{flex:1;padding:11px;background:#00d165;color:#080c14;border:none;border-radius:8px;font-size:13px;font-weight:700;cursor:pointer;font-family:'Inter',sans-serif;}}
.email-send:hover{{background:#04e270;}}
.email-cancel{{flex:1;padding:11px;background:#f8fafc;color:#64748b;border:1px solid #e4e8f0;border-radius:8px;font-size:13px;font-weight:500;cursor:pointer;}}
/* TOAST */
.toast{{position:fixed;bottom:24px;right:24px;background:#0d1120;color:#fff;border-radius:10px;padding:13px 17px;font-size:12.5px;transform:translateY(60px);opacity:0;transition:all 0.3s;z-index:2000;box-shadow:0 8px 24px rgba(0,0,0,0.15);}}
.toast.show{{transform:translateY(0);opacity:1;}}
/* WELCOME BANNER */
.welcome-banner{{background:#f0fdf4;border-bottom:1px solid #bbf7d0;padding:11px 32px;display:flex;align-items:center;justify-content:space-between;font-size:13px;color:#166534;}}
.welcome-close{{background:none;border:none;color:#94a3b8;font-size:18px;cursor:pointer;}}
</style>
</head>
<body>

<!-- TOPBAR -->
<div class="topbar">
  <div class="topbar-brand">
    <span class="topbar-name">Occup<span>ado</span></span>
    <span class="topbar-hotel">{hotel_name}</span>
  </div>
  <div class="topbar-right">
    <select class="lang-selector" onchange="window.location.href='/dashboard?lang='+this.value">
      <option value="en" {"selected" if lang=="en" else ""}>EN</option>
      <option value="nl" {"selected" if lang=="nl" else ""}>NL</option>
      <option value="fr" {"selected" if lang=="fr" else ""}>FR</option>
    </select>
    <a href="/settings" class="btn-nav">Settings</a>
    <a href="/logout" class="btn-nav">Sign Out</a>
  </div>
</div>

{f'''<div id="welcome-banner" class="welcome-banner">
  <span>Welcome back, <strong>{hotel_name}</strong>. Your live intelligence dashboard is ready.</span>
  <button onclick="document.getElementById('welcome-banner').style.display='none'" class="welcome-close">×</button>
</div>''' if first_login else ''}

<!-- HERO -->
<div class="hero">
  <div class="hero-eyebrow">Live Intelligence Dashboard</div>
  <div class="hero-title">Van der Valk Hotel Mechelen</div>
  <div class="hero-sub">{today_str} · {len(guests)} repeat guests tracked · Powered by Occupado AI</div>
  <div class="hero-badges">
    <span class="hero-badge">✓ Model accuracy 80.3%</span>
    <span class="hero-badge">✓ {len(arriving_today)} arriving today</span>
    <span class="hero-badge">✓ {len(in_house)} in house</span>
    <span class="hero-badge {'warn' if high_count > 0 else ''}">{'⚠ ' + str(high_count) + ' high risk' if high_count > 0 else '✓ 0 high risk today'}</span>
    <span class="hero-badge info">VDV Shiji · Data current</span>
  </div>
</div>

<div class="content">

<!-- KPI ROW 1: Today's operations -->
<div class="section-title" style="margin-top:0">Today at a Glance</div>
<div class="kpi-grid">
  <div class="kpi-card highlight-green">
    <div class="kpi-num green">{len(arriving_today)}</div>
    <div class="kpi-label">Arriving Today</div>
    <div class="kpi-trend" style="color:#16a34a">↑ Ready for check-in</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-num blue">{len(in_house)}</div>
    <div class="kpi-label">Currently In House</div>
    <div class="kpi-trend" style="color:#3b82f6">Repeat guests</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-num neutral">{len(departing_tmrw)}</div>
    <div class="kpi-label">Departing Tomorrow</div>
    <div class="kpi-trend" style="color:#64748b">Send departure reminders</div>
  </div>
  <div class="kpi-card {'highlight-red' if high_count > 0 else ''}">
    <div class="kpi-num {'red' if high_count > 0 else 'green'}">{high_count}</div>
    <div class="kpi-label">High Risk Bookings</div>
    <div class="kpi-trend" style="color:{'#dc2626' if high_count > 0 else '#16a34a'}">{'Action required' if high_count > 0 else '✓ All clear'}</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-num orange">{med_count}</div>
    <div class="kpi-label">Medium Risk</div>
    <div class="kpi-trend" style="color:#b45309">Monitor closely</div>
  </div>
  <div class="kpi-card highlight-green">
    <div class="kpi-num green">{low_count}</div>
    <div class="kpi-label">Low Risk</div>
    <div class="kpi-trend" style="color:#16a34a">Avg score {avg_score:.1f}%</div>
  </div>
</div>

<!-- KPI ROW 2: Historical intelligence -->
<div class="kpi-grid" style="margin-top:12px;margin-bottom:28px;">
  <div class="kpi-card">
    <div class="kpi-num neutral" style="font-size:28px;">15.2%</div>
    <div class="kpi-label">Historical Cancellation Rate</div>
    <div class="kpi-trend" style="color:#64748b">Based on 1,638 events</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-num neutral" style="font-size:28px;">4.7%</div>
    <div class="kpi-label">Historical No-show Rate</div>
    <div class="kpi-trend" style="color:#64748b">300 no-shows tracked</div>
  </div>
  <div class="kpi-card highlight-green">
    <div class="kpi-num green" style="font-size:28px;">80.3%</div>
    <div class="kpi-label">AI Model Accuracy</div>
    <div class="kpi-trend" style="color:#16a34a">Kaggle + Shiji data</div>
  </div>
  <div class="kpi-card highlight-green">
    <div class="kpi-num green" style="font-size:28px;">€0</div>
    <div class="kpi-label">Revenue at Risk Today</div>
    <div class="kpi-trend" style="color:#16a34a">All guests confirmed</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-num neutral" style="font-size:28px;">€{int(rev_arriving):,}</div>
    <div class="kpi-label">Expected Revenue — Arrivals</div>
    <div class="kpi-trend" style="color:#64748b">{len(arriving_today)} guests × avg rate</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-num neutral" style="font-size:28px;">€{int(rev_inhouse):,}</div>
    <div class="kpi-label">Active Revenue — In House</div>
    <div class="kpi-trend" style="color:#64748b">{len(in_house)} guests × avg rate</div>
  </div>
</div>

<!-- CHARTS ROW -->
<div class="section-title">Analytics</div>
<div class="charts-row">

  <!-- Donut: Risk distribution -->
  <div class="chart-card">
    <div class="chart-title">Booking Risk</div>
    <div class="chart-sub">Current guests distribution</div>
    <canvas id="riskDonut" height="180"></canvas>
    <div class="donut-center">
      <div class="donut-big">{round(low_count/len(scores)*100) if scores else 0}%</div>
      <div class="donut-label">Low Risk</div>
    </div>
  </div>

  <!-- Bar: Cancellation by channel -->
  <div class="chart-card">
    <div class="chart-title">Cancellations by Channel</div>
    <div class="chart-sub">Historical — {sum(ch_data.values()):,} total cancellations</div>
    <canvas id="channelChart" height="180"></canvas>
  </div>

  <!-- Bar: Guest risk scores -->
  <div class="chart-card">
    <div class="chart-title">Guest Cancellation Scores</div>
    <div class="chart-sub">AI prediction per guest — lower is better</div>
    <canvas id="scoreChart" height="180"></canvas>
  </div>

</div>

<!-- OVERBOOKING OPTIMIZER -->
<div class="section-title">Overbooking Optimizer</div>
<div class="optimizer-card">
  <div class="optimizer-row">
    <div class="opt-stat" style="background:#f0fdf4;border-color:#bbf7d0;">
      <div class="opt-stat-val" style="color:#00d165">+{max(0, round(len(guests)*0.05))}</div>
      <div class="opt-stat-label">Safe rooms to oversell</div>
    </div>
    <div class="opt-stat">
      <div class="opt-stat-val">{len(guests)}</div>
      <div class="opt-stat-label">Bookings analysed</div>
    </div>
    <div class="opt-stat">
      <div class="opt-stat-val" style="color:#dc2626">0</div>
      <div class="opt-stat-label">Predicted no-shows</div>
    </div>
    <div class="opt-stat">
      <div class="opt-stat-val">€130</div>
      <div class="opt-stat-label">Avg room rate</div>
    </div>
  </div>
  <div style="display:flex;gap:10px;align-items:center;background:#f8fafc;border:1px solid #e4e8f0;border-radius:9px;padding:14px 18px;">
    <div style="flex:1;font-size:13px;color:#374151;line-height:1.5;">
      <strong style="color:#0d1120;">Tonight's outlook:</strong> All {len(guests)} tracked repeat guests are confirmed.
      Historical no-show rate of 4.7% suggests <strong>{round(len(guests)*0.047,1)}</strong> potential gaps.
      Consider moderate overbooking for non-repeat segments.
    </div>
    <button onclick="showToast('Recommendation noted — coordinate with front desk')" style="padding:10px 20px;background:#00d165;border:none;border-radius:8px;color:#080c14;font-size:13px;font-weight:700;cursor:pointer;white-space:nowrap;font-family:Inter,sans-serif;">Apply Recommendation</button>
  </div>
</div>

<!-- GUEST TABLE -->
<div class="section-title">Repeat Guests — Click any row for AI analysis</div>
<div class="section-sub">Sorted by status: Arriving Today → In House → Checked Out</div>
<table>
<thead>
  <tr>
    <th>Guest</th><th>Status</th><th>Arrival</th><th>Departure</th>
    <th>Nights</th><th>Adults</th><th>Risk Score</th><th>Guest Notes</th><th>Action</th>
  </tr>
</thead>
<tbody>{rows_html}</tbody>
</table>

<!-- ACTION PLAN -->
<div class="section-title">Interactive Action Plan</div>
<div class="section-sub">Contextual tips and contact options per guest segment</div>

<div class="action-plan-grid">

  <!-- Arriving Today -->
  <div class="plan-card">
    <div class="plan-card-header">
      <div class="plan-icon arriving">🛬</div>
      <div>
        <div class="plan-card-title">Today's Arrivals ({len(arriving_today)})</div>
        <div class="plan-card-sub">Expected today · Pre-arrival actions</div>
      </div>
    </div>
    {arriving_plan}
    <button class="plan-action-btn green-btn" onclick="openBulkTemplate('welcome')" style="margin-top:14px;">
      Send Welcome Email to All →
    </button>
  </div>

  <!-- In House -->
  <div class="plan-card">
    <div class="plan-card-header">
      <div class="plan-icon inhouse">🏨</div>
      <div>
        <div class="plan-card-title">In-House Guests ({len(in_house)})</div>
        <div class="plan-card-sub">Currently staying · Experience & upsell</div>
      </div>
    </div>
    {inhouse_plan}
    <button class="plan-action-btn" onclick="openBulkTemplate('departure')" style="margin-top:14px;">
      Send Departure Reminder to All →
    </button>
  </div>

  <!-- Revenue Intelligence -->
  <div class="plan-card">
    <div class="plan-card-header">
      <div class="plan-icon intel">📊</div>
      <div>
        <div class="plan-card-title">Revenue Intelligence</div>
        <div class="plan-card-sub">Historical insights from Shiji data</div>
      </div>
    </div>
    <div class="intel-grid">
      <div class="intel-item warn">
        <div class="intel-num warn">31.6%</div>
        <div class="intel-label">Booking.com cancellations</div>
      </div>
      <div class="intel-item warn">
        <div class="intel-num warn">24.2%</div>
        <div class="intel-label">Corporate cancellations</div>
      </div>
      <div class="intel-item info">
        <div class="intel-num info">14.7%</div>
        <div class="intel-label">Direct / Web cancellations</div>
      </div>
    </div>
    <div style="margin-top:10px;background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:12px;font-size:12px;color:#92400e;line-height:1.5;">
      <strong>💡 Insight:</strong> Booking.com is your #1 cancellation source (518 cancellations tracked).
      Consider requiring prepayment on OTA bookings with high lead times.
    </div>
  </div>

  <!-- Tips & Best Practices -->
  <div class="plan-card">
    <div class="plan-card-header">
      <div class="plan-icon bulk">💡</div>
      <div>
        <div class="plan-card-title">Tips & Best Practices</div>
        <div class="plan-card-sub">AI-powered recommendations for VdV Mechelen</div>
      </div>
    </div>
    <div class="plan-item">
      <div class="plan-guest">Repeat Guest Program</div>
      <div class="plan-tip">Your repeat guests (like those tracked here) have significantly lower cancellation rates. Prioritise VIP recognition on check-in to reinforce loyalty.</div>
    </div>
    <div class="plan-item">
      <div class="plan-guest">Corporate Rate Management</div>
      <div class="plan-tip">Corporate guests (Alheembouw, CORP accounts) have fixed rates. Verify current-period rates are loaded correctly in Shiji before check-in.</div>
    </div>
    <div class="plan-item">
      <div class="plan-guest">No-show Protection</div>
      <div class="plan-tip">With a 4.7% historical no-show rate, consider implementing credit card guarantees for all bookings with lead time &gt; 30 days.</div>
    </div>
  </div>

</div>

<!-- BULK ACTIONS -->
<div class="section-title">Take Action</div>
<div class="bulk-zone">
  <div class="bulk-card">
    <div class="bulk-icon">👋</div>
    <div class="bulk-card-title">Welcome Arriving Guests</div>
    <div class="bulk-card-sub">Send personalised welcome emails to today's {len(arriving_today)} arriving guests</div>
    <button class="bulk-btn green-btn" onclick="openBulkTemplate('welcome')">Send Welcome Email →</button>
  </div>
  <div class="bulk-card">
    <div class="bulk-icon">🛎</div>
    <div class="bulk-card-title">Departure Reminders</div>
    <div class="bulk-card-sub">Remind tomorrow's departures of checkout time and offer late checkout</div>
    <button class="bulk-btn" onclick="openBulkTemplate('departure')">Send Departure Reminder →</button>
  </div>
  <div class="bulk-card">
    <div class="bulk-icon">⬆️</div>
    <div class="bulk-card-title">Upsell In-House Guests</div>
    <div class="bulk-card-sub">Offer restaurant, parking, or room upgrade to the {len(in_house)} guests currently staying</div>
    <button class="bulk-btn" onclick="openBulkTemplate('upsell')">Send Upsell Offer →</button>
  </div>
</div>

</div><!-- /content -->


<!-- DETAIL MODAL -->
<div class="modal-overlay" id="detailModal">
  <div class="modal">
    <button class="modal-close" onclick="closeDetailModal()">✕</button>
    <div class="modal-title" id="dm-title">Guest Analysis</div>
    <div class="modal-sub" id="dm-sub">AI Cancellation Risk</div>
    <div class="score-display" id="dm-score">0%</div>
    <div class="score-bar-bg"><div class="score-bar-fill" id="dm-bar" style="width:0%"></div></div>
    <div class="score-verdict" id="dm-verdict"></div>
    <div class="modal-section">
      <div class="modal-section-title">Booking Details</div>
      <div id="dm-details"></div>
    </div>
    <div class="modal-section">
      <div class="modal-section-title">AI Risk Factors</div>
      <div id="dm-reasons"></div>
    </div>
    <div style="display:flex;gap:10px;margin-top:20px;">
      <button id="dm-contact-btn" style="flex:1;padding:12px;border:none;border-radius:8px;font-size:13px;font-weight:700;cursor:pointer;font-family:Inter,sans-serif;background:#00d165;color:#080c14;" onclick="openContactFromModal()">Contact Guest →</button>
      <button style="flex:1;padding:12px;background:#f8fafc;color:#64748b;border:1px solid #e4e8f0;border-radius:8px;font-size:13px;font-weight:500;cursor:pointer;" onclick="closeDetailModal()">Close</button>
    </div>
  </div>
</div>

<!-- EMAIL COMPOSER -->
<div class="email-composer" id="emailComposer">
  <div class="email-box">
    <div style="margin-bottom:20px;">
      <div class="email-title" id="ec-title">Contact Guest</div>
      <div style="font-family:'JetBrains Mono',monospace;font-size:11px;color:#94a3b8;margin-top:3px;" id="ec-sub"></div>
    </div>
    <label class="email-label">Guest Email Address</label>
    <input type="email" id="ec-email" class="email-input" placeholder="guest@example.com">
    <label class="email-label">Guest Name</label>
    <input type="text" id="ec-name" class="email-input" placeholder="Guest Name">
    <label class="email-label">Subject</label>
    <input type="text" id="ec-subject" class="email-input" placeholder="Your upcoming stay at Van der Valk Hotel Mechelen">
    <label class="email-label">Message</label>
    <textarea id="ec-body" class="email-textarea" placeholder="Dear Guest..."></textarea>
    <div class="email-actions">
      <button class="email-send" onclick="sendGuestEmail()">📧 Send Email</button>
      <button class="email-cancel" onclick="closeEmailComposer()">Cancel</button>
    </div>
  </div>
</div>

<!-- BULK EMAIL COMPOSER -->
<div class="email-composer" id="bulkComposer">
  <div class="email-box">
    <div style="margin-bottom:20px;">
      <div class="email-title" id="bc-title">Send to Group</div>
      <div style="font-family:'JetBrains Mono',monospace;font-size:11px;color:#94a3b8;margin-top:3px;" id="bc-sub"></div>
    </div>
    <label class="email-label">Subject</label>
    <input type="text" id="bc-subject" class="email-input">
    <label class="email-label">Message (sent to all guests in this group)</label>
    <textarea id="bc-body" class="email-textarea"></textarea>
    <div class="email-actions">
      <button class="email-send" onclick="sendBulkEmail()">📧 Send to All</button>
      <button class="email-cancel" onclick="closeBulkComposer()">Cancel</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
const guests = {guests_js};
const scores = {guest_scores_js};
let currentGuestIdx = -1;

// ── CHARTS ────────────────────────────────────────────────────────────────────
(function initCharts() {{
  // Donut — risk distribution
  new Chart(document.getElementById('riskDonut'), {{
    type: 'doughnut',
    data: {{
      labels: ['Low Risk','Medium Risk','High Risk'],
      datasets: [{{ data: {risk_donut_js}, backgroundColor: ['#00d165','#f59e0b','#dc2626'], borderWidth: 0, hoverOffset: 4 }}]
    }},
    options: {{
      cutout: '72%', plugins: {{ legend: {{ position: 'bottom', labels: {{ font: {{ family: 'JetBrains Mono', size: 10 }}, boxWidth: 10, padding: 12 }} }}, tooltip: {{ callbacks: {{ label: ctx => ` ${{ctx.label}}: ${{ctx.parsed}} bookings` }} }} }},
      animation: {{ animateRotate: true, duration: 900 }}
    }}
  }});

  // Channel cancellations bar
  new Chart(document.getElementById('channelChart'), {{
    type: 'bar',
    data: {{
      labels: {ch_labels},
      datasets: [{{
        label: 'Cancellations',
        data: {ch_values},
        backgroundColor: ['#dc2626','#f59e0b','#3b82f6','#8b5cf6','#94a3b8'],
        borderRadius: 5, borderWidth: 0
      }}]
    }},
    options: {{
      indexAxis: 'y',
      plugins: {{ legend: {{ display: false }}, tooltip: {{ callbacks: {{ label: ctx => ` ${{ctx.parsed.x}} cancellations (${{({ch_pcts})[ctx.dataIndex]}}%)` }} }} }},
      scales: {{ x: {{ grid: {{ color: '#f1f5f9' }}, ticks: {{ font: {{ family: 'JetBrains Mono', size: 10 }} }} }}, y: {{ grid: {{ display: false }}, ticks: {{ font: {{ family: 'JetBrains Mono', size: 10 }} }} }} }},
      animation: {{ duration: 900 }}
    }}
  }});

  // Guest risk scores bar
  new Chart(document.getElementById('scoreChart'), {{
    type: 'bar',
    data: {{
      labels: {guest_names_js},
      datasets: [{{
        label: 'Risk Score %',
        data: scores,
        backgroundColor: {guest_colors_js},
        borderRadius: 5, borderWidth: 0
      }}]
    }},
    options: {{
      plugins: {{ legend: {{ display: false }}, tooltip: {{ callbacks: {{ label: ctx => ` ${{ctx.parsed.y.toFixed(1)}}% cancellation risk` }} }} }},
      scales: {{ x: {{ grid: {{ display: false }}, ticks: {{ font: {{ family: 'JetBrains Mono', size: 9 }}, maxRotation: 45 }} }}, y: {{ min:0, max:100, grid: {{ color:'#f1f5f9' }}, ticks: {{ font: {{ family:'JetBrains Mono',size:10 }}, callback: v => v+'%' }} }} }},
      animation: {{ duration: 900 }}
    }}
  }});
}})();

// ── DETAIL MODAL ──────────────────────────────────────────────────────────────
function showVdvDetail(idx, score) {{
  const g = guests[idx];
  currentGuestIdx = idx;
  document.getElementById('dm-title').textContent = g.name;
  document.getElementById('dm-sub').textContent = g.arrival + ' → ' + g.departure + ' · ' + g.status;
  document.getElementById('dm-score').textContent = score.toFixed(1) + '%';

  const bar   = document.getElementById('dm-bar');
  const verd  = document.getElementById('dm-verdict');
  const scoreEl = document.getElementById('dm-score');
  bar.style.width = score + '%';

  if (score >= 70) {{
    bar.style.background = '#dc2626'; scoreEl.style.color = '#dc2626';
    verd.textContent = 'HIGH RISK'; verd.style.background = '#fef2f2'; verd.style.color = '#dc2626';
  }} else if (score >= 40) {{
    bar.style.background = '#f59e0b'; scoreEl.style.color = '#f59e0b';
    verd.textContent = 'MEDIUM RISK'; verd.style.background = '#fffbeb'; verd.style.color = '#b45309';
  }} else {{
    bar.style.background = '#00d165'; scoreEl.style.color = '#00d165';
    verd.textContent = 'LOW RISK'; verd.style.background = '#f0fdf4'; verd.style.color = '#16a34a';
  }}

  document.getElementById('dm-details').innerHTML = `
    <div class="modal-detail-row"><span class="modal-detail-label">Nights</span><span class="modal-detail-val">${{g.nights}}</span></div>
    <div class="modal-detail-row"><span class="modal-detail-label">Adults</span><span class="modal-detail-val">${{g.adults}}</span></div>
    <div class="modal-detail-row"><span class="modal-detail-label">Membership</span><span class="modal-detail-val">${{g.membership || 'Standard'}}</span></div>
    <div class="modal-detail-row"><span class="modal-detail-label">Avg Room Rate</span><span class="modal-detail-val">€${{g.adr}}/night</span></div>
    ${{g.note ? '<div class="modal-detail-row"><span class="modal-detail-label">Notes</span><span class="modal-detail-val" style="font-size:11px;max-width:220px;text-align:right;">' + g.note + '</span></div>' : ''}}
  `;

  const reasons = [];
  if (score < 15) {{
    reasons.push({{pos:true, text:'Repeat guest — historically reliable, lower no-show probability'}});
    reasons.push({{pos:true, text:'Low lead time — very close to check-in, commitment is high'}});
    if (g.membership) reasons.push({{pos:true, text:'Corporate/loyalty membership — adds accountability'}});
  }} else if (score < 40) {{
    reasons.push({{pos:true, text:'Returning guest with positive booking history'}});
    reasons.push({{pos:false, text:'Extended stay or higher lead time increases marginal risk'}});
  }} else {{
    reasons.push({{pos:false, text:'Risk factors present — consider proactive contact'}});
  }}

  document.getElementById('dm-reasons').innerHTML = reasons.map(r =>
    `<div class="reason-item ${{r.pos?'pos':'neg'}}">${{r.pos?'✓':'⚠'}} ${{r.text}}</div>`
  ).join('');

  document.getElementById('detailModal').classList.add('show');
}}

function closeDetailModal() {{
  document.getElementById('detailModal').classList.remove('show');
  currentGuestIdx = -1;
}}

function openContactFromModal() {{
  closeDetailModal();
  if (currentGuestIdx >= 0) setTimeout(() => openVdvEmail(currentGuestIdx, 'contact'), 100);
}}

// ── EMAIL COMPOSER ────────────────────────────────────────────────────────────
function openVdvEmail(idx, type) {{
  const g = guests[idx];
  currentGuestIdx = idx;
  const firstName = g.name.split(',').length > 1 ? g.name.split(',')[1].split(',')[0].trim().split(' ')[1] || g.name.split(',')[1].trim() : g.name;

  const templates = {{
    contact: {{
      subject: 'Your upcoming stay at Van der Valk Hotel Mechelen',
      body: `Dear ${{firstName}},\n\nWe are looking forward to welcoming you to Van der Valk Hotel Mechelen.\n\nPlease do not hesitate to contact us if you have any special requests or questions regarding your stay from ${{g.arrival}} to ${{g.departure}}.\n\nWarm regards,\nVan der Valk Hotel Mechelen`
    }},
    welcome: {{
      subject: 'Welcome to Van der Valk Hotel Mechelen',
      body: `Dear ${{firstName}},\n\nWelcome! We are delighted to have you with us today.\n\nYour room is being prepared and we look forward to ensuring you have a wonderful stay. Should you need anything during your time with us, please do not hesitate to contact the front desk.\n\nWarm regards,\nVan der Valk Hotel Mechelen`
    }},
    departure: {{
      subject: 'Thank you for staying — departure reminder',
      body: `Dear ${{firstName}},\n\nWe hope you are enjoying your stay at Van der Valk Hotel Mechelen.\n\nThis is a friendly reminder that your check-out is scheduled for ${{g.departure}}. Checkout time is 12:00. If you wish to arrange a late checkout, please contact the front desk.\n\nWe hope to welcome you back soon!\n\nWarm regards,\nVan der Valk Hotel Mechelen`
    }},
    reminder: {{
      subject: 'Reminder: Your upcoming reservation',
      body: `Dear ${{firstName}},\n\nThis is a friendly reminder of your upcoming reservation from ${{g.arrival}} to ${{g.departure}} at Van der Valk Hotel Mechelen.\n\nPlease confirm your booking or contact us if there are any changes to your plans.\n\nWarm regards,\nVan der Valk Hotel Mechelen`
    }},
    deposit: {{
      subject: 'Reservation guarantee — deposit request',
      body: `Dear ${{firstName}},\n\nThank you for your reservation from ${{g.arrival}} to ${{g.departure}} at Van der Valk Hotel Mechelen.\n\nTo secure your booking, we kindly request a deposit. Please contact us at your earliest convenience to complete this.\n\nWarm regards,\nVan der Valk Hotel Mechelen`
    }},
    upsell: {{
      subject: 'Make the most of your stay — exclusive offers',
      body: `Dear ${{firstName}},\n\nWe hope you are enjoying your time at Van der Valk Hotel Mechelen!\n\nAs our valued guest, we would like to offer you:\n• Restaurant dinner reservation (10% loyalty discount)\n• Covered parking upgrade\n• Late checkout until 14:00 (subject to availability)\n\nPlease contact the front desk or reply to this email to arrange any of the above.\n\nWarm regards,\nVan der Valk Hotel Mechelen`
    }}
  }};

  const tpl = templates[type] || templates.contact;
  document.getElementById('ec-title').textContent = 'Email to ' + g.name;
  document.getElementById('ec-sub').textContent   = g.status + ' · ' + g.arrival + ' – ' + g.departure;
  document.getElementById('ec-name').value    = g.name;
  document.getElementById('ec-email').value   = '';
  document.getElementById('ec-subject').value = tpl.subject;
  document.getElementById('ec-body').value    = tpl.body;
  document.getElementById('emailComposer').classList.add('show');
}}

function closeEmailComposer() {{
  document.getElementById('emailComposer').classList.remove('show');
}}

function sendGuestEmail() {{
  const email   = document.getElementById('ec-email').value.trim();
  const subject = document.getElementById('ec-subject').value.trim();
  const body    = document.getElementById('ec-body').value.trim();
  if (!email || !subject || !body) {{ showToast('Please fill in all fields', 'error'); return; }}
  fetch('/send-guest-email', {{
    method: 'POST', headers: {{'Content-Type':'application/json'}},
    body: JSON.stringify({{guest_email: email, subject, body}})
  }}).then(r => r.json()).then(d => {{
    closeEmailComposer();
    showToast(d.status === 'success' ? '✓ Email sent' : 'Error: ' + d.message, d.status === 'success' ? 'success' : 'error');
  }}).catch(() => showToast('Error sending email', 'error'));
}}

// ── BULK COMPOSER ─────────────────────────────────────────────────────────────
function openBulkTemplate(type) {{
  const templates = {{
    welcome: {{
      title: 'Welcome Email — Today\'s Arrivals',
      subject: 'Welcome to Van der Valk Hotel Mechelen',
      body: 'Dear Valued Guest,\n\nWelcome! We are so glad to have you with us today.\n\nYour room is being prepared and our team is ready to ensure a wonderful experience. For any requests, please contact the front desk.\n\nWarm regards,\nVan der Valk Hotel Mechelen'
    }},
    departure: {{
      title: 'Departure Reminder — Tomorrow\'s Checkouts',
      subject: 'Departure reminder — checkout tomorrow',
      body: 'Dear Valued Guest,\n\nThis is a friendly reminder that your checkout is scheduled for tomorrow. Standard checkout is at 12:00.\n\nWe hope you have enjoyed your stay and look forward to welcoming you back!\n\nWarm regards,\nVan der Valk Hotel Mechelen'
    }},
    upsell: {{
      title: 'Upsell Offer — In-House Guests',
      subject: 'Exclusive offers for your stay',
      body: 'Dear Valued Guest,\n\nWe hope you are enjoying your time with us!\n\nAs a valued guest, we are pleased to offer you exclusive in-stay experiences:\n• Restaurant reservation with priority seating\n• Parking upgrade\n• Late checkout (subject to availability)\n\nContact the front desk to arrange any of these.\n\nWarm regards,\nVan der Valk Hotel Mechelen'
    }}
  }};
  const tpl = templates[type] || templates.welcome;
  document.getElementById('bc-title').textContent   = tpl.title;
  document.getElementById('bc-sub').textContent     = 'Template — fill in guest details before sending';
  document.getElementById('bc-subject').value = tpl.subject;
  document.getElementById('bc-body').value    = tpl.body;
  document.getElementById('bulkComposer').classList.add('show');
}}

function closeBulkComposer() {{
  document.getElementById('bulkComposer').classList.remove('show');
}}

function sendBulkEmail() {{
  const subject = document.getElementById('bc-subject').value.trim();
  const body    = document.getElementById('bc-body').value.trim();
  if (!subject || !body) {{ showToast('Please fill in all fields', 'error'); return; }}
  fetch('/send-bulk-email', {{
    method: 'POST', headers: {{'Content-Type':'application/json'}},
    body: JSON.stringify({{count: guests.length, subject, body}})
  }}).then(r => r.json()).then(d => {{
    closeBulkComposer();
    showToast(d.status === 'success' ? '✓ Emails sent' : 'Error', d.status === 'success' ? 'success' : 'error');
  }}).catch(() => showToast('Error', 'error'));
}}

// ── UTILS ─────────────────────────────────────────────────────────────────────
function showToast(msg, type) {{
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.style.background = type === 'error' ? '#dc2626' : '#0d1120';
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 3200);
}}

document.getElementById('detailModal').addEventListener('click', e => {{ if (e.target === document.getElementById('detailModal')) closeDetailModal(); }});
document.getElementById('emailComposer').addEventListener('click', e => {{ if (e.target === document.getElementById('emailComposer')) closeEmailComposer(); }});
document.getElementById('bulkComposer').addEventListener('click', e => {{ if (e.target === document.getElementById('bulkComposer')) closeBulkComposer(); }});
</script>
</body>
</html>"""

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
        if not session.get("is_admin"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated

def is_valid_email(email):
    """Basic email format validation."""
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))

def build_empty_state(hotel_name, lang="en"):
    return f"""<!DOCTYPE html>
<html>
<head>
<title>Occupado — {hotel_name}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{margin:0;padding:0;box-sizing:border-box;}}
body{{background:#ffffff;color:#0d1120;font-family:'Inter',sans-serif;-webkit-font-smoothing:antialiased;}}
a{{text-decoration:none;}}
.topbar{{height:62px;background:#ffffff;border-bottom:1px solid #e4e8f0;display:flex;align-items:center;padding:0 32px;}}
.topbar-name{{font-family:'Syne',sans-serif;font-size:17px;font-weight:800;color:#0d1120;letter-spacing:-0.4px;}}
.topbar-name span{{color:#00d165;}}
.topbar-hotel{{font-family:'JetBrains Mono',monospace;font-size:11px;color:#94a3b8;margin-left:12px;padding-left:12px;border-left:1px solid #e4e8f0;}}
.topbar-right{{margin-left:auto;display:flex;gap:8px;}}
.btn-nav{{padding:7px 16px;background:transparent;border:1px solid #e4e8f0;border-radius:7px;color:#64748b;font-size:12px;font-weight:500;text-decoration:none;}}
.btn-nav:hover{{border-color:#cbd5e1;color:#0d1120;}}
.page{{max-width:600px;margin:0 auto;padding:80px 24px 40px;text-align:center;}}
.welcome-tag{{display:inline-flex;align-items:center;gap:6px;background:#f0fdf4;border:1px solid #bbf7d0;border-radius:99px;padding:5px 14px;font-family:'JetBrains Mono',monospace;font-size:11px;color:#16a34a;margin-bottom:24px;}}
.welcome-dot{{width:6px;height:6px;background:#00d165;border-radius:50%;}}
h1{{font-family:'Syne',sans-serif;font-size:40px;font-weight:800;color:#0d1120;letter-spacing:-1.5px;line-height:1.1;margin-bottom:14px;}}
h1 span{{color:#00d165;}}
.sub{{font-size:16px;color:#64748b;line-height:1.6;margin-bottom:48px;}}
.features{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:48px;text-align:left;}}
.feat{{background:#f8fafc;border:1px solid #e4e8f0;border-radius:12px;padding:20px;}}
.feat-icon{{font-size:22px;margin-bottom:10px;}}
.feat-title{{font-family:'Syne',sans-serif;font-size:13px;font-weight:700;color:#0d1120;margin-bottom:4px;letter-spacing:-0.2px;}}
.feat-sub{{font-size:12px;color:#64748b;line-height:1.5;}}
.upload-card{{background:#f8fafc;border:2px dashed #cbd5e1;border-radius:16px;padding:40px;margin-bottom:20px;cursor:pointer;transition:all .2s;}}
.upload-card:hover{{border-color:#00d165;background:#f0fdf4;}}
.upload-icon{{font-size:36px;margin-bottom:12px;}}
.upload-title{{font-family:'Syne',sans-serif;font-size:18px;font-weight:800;color:#0d1120;margin-bottom:6px;letter-spacing:-0.4px;}}
.upload-sub{{font-size:13px;color:#64748b;margin-bottom:24px;}}
.upload-btn{{display:inline-block;padding:13px 32px;background:#00d165;color:#080c14;border:none;border-radius:9px;font-size:14px;font-weight:700;cursor:pointer;font-family:'Inter',sans-serif;}}
.upload-btn:hover{{background:#04e270;}}
.demo-link{{font-size:13px;color:#94a3b8;}}
.demo-link a{{color:#64748b;text-decoration:underline;text-underline-offset:3px;}}
.demo-link a:hover{{color:#0d1120;}}
</style>
</head>
<body>
<div class="topbar">
  <span class="topbar-name">Occup<span>ado</span></span>
  <span class="topbar-hotel">{hotel_name}</span>
  <div class="topbar-right">
    <a href="/settings" class="btn-nav">Settings</a>
    <a href="/logout" class="btn-nav">Sign out</a>
  </div>
</div>
<div class="page">
  <div class="welcome-tag"><span class="welcome-dot"></span>Account ready</div>
  <h1>Welcome to<br><span>Occupado</span></h1>
  <p class="sub">Upload your booking data and get AI-powered cancellation risk scores, revenue forecasts, and action plans — in seconds.</p>
  <div class="features">
    <div class="feat">
      <div class="feat-icon">🎯</div>
      <div class="feat-title">Risk Scores</div>
      <div class="feat-sub">Every booking scored 0–100% cancellation probability</div>
    </div>
    <div class="feat">
      <div class="feat-icon">💶</div>
      <div class="feat-title">Revenue at Risk</div>
      <div class="feat-sub">See exactly how much revenue is exposed each week</div>
    </div>
    <div class="feat">
      <div class="feat-icon">📧</div>
      <div class="feat-title">Take Action</div>
      <div class="feat-sub">Send deposit requests and reminders in one click</div>
    </div>
  </div>
  <form method="POST" action="/upload" enctype="multipart/form-data">
    <div class="upload-card" onclick="document.getElementById('csv-onboard').click()">
      <div class="upload-icon">📂</div>
      <div class="upload-title">Upload your booking export</div>
      <div class="upload-sub">CSV file from your PMS — Opera, Protel, Mews, or any system</div>
      <input type="file" id="csv-onboard" name="csv_file" accept=".csv" style="display:none" onchange="this.form.submit()">
      <button type="button" class="upload-btn" onclick="event.stopPropagation();document.getElementById('csv-onboard').click()">Choose file</button>
    </div>
  </form>
  <p class="demo-link">Not ready yet? <a href="/dashboard?skip_onboard=1">Preview with demo data</a></p>
</div>
</body>
</html>"""


def build_dashboard(hotel_name, sample, scores, tonight_scores, tonight_sample=None, uploaded=False, lang="en", first_login=False):
    high = sum(1 for s in scores if s >= 70)
    med  = sum(1 for s in scores if 40 <= s < 70)
    low  = sum(1 for s in scores if s < 40)

    avg_rate = sample["adr"].mean() if "adr" in sample.columns else df["adr"].mean()
    predicted_noshows = sum(1 for s in tonight_scores if s >= 70)
    safe_overbook = int(predicted_noshows * 0.80)
    revenue = safe_overbook * avg_rate

    # --- Full-dataset analytics ---
    if tonight_sample is not None and len(tonight_sample) > 0:
        all_scores   = list(tonight_scores)
        total_bookings = len(tonight_sample)
        high_total   = sum(1 for s in all_scores if s >= 70)
        med_total    = sum(1 for s in all_scores if 40 <= s < 70)
        low_total    = sum(1 for s in all_scores if s < 40)
        avg_adr      = float(tonight_sample["adr"].mean()) if "adr" in tonight_sample.columns else float(avg_rate)
        wk = tonight_sample["stays_in_week_nights"] if "stays_in_week_nights" in tonight_sample.columns else pd.Series([1]*total_bookings)
        we = tonight_sample["stays_in_weekend_nights"] if "stays_in_weekend_nights" in tonight_sample.columns else pd.Series([0]*total_bookings)
        avg_nights   = max(1.0, float((wk + we).mean()))
        revenue_at_risk = int(high_total * avg_adr * avg_nights)

        # Lead-time buckets for chart
        lt_buckets = [[] for _ in range(5)]
        for idx, (_, row) in enumerate(tonight_sample.iterrows()):
            lt = float(row.get("lead_time", 0))
            s  = all_scores[idx] if idx < len(all_scores) else 0
            if lt <= 7:    lt_buckets[0].append(s)
            elif lt <= 30: lt_buckets[1].append(s)
            elif lt <= 60: lt_buckets[2].append(s)
            elif lt <= 90: lt_buckets[3].append(s)
            else:          lt_buckets[4].append(s)
        lt_high_js = json.dumps([sum(1 for s in b if s >= 70)      for b in lt_buckets])
        lt_med_js  = json.dumps([sum(1 for s in b if 40 <= s < 70) for b in lt_buckets])
        lt_low_js  = json.dumps([sum(1 for s in b if s < 40)       for b in lt_buckets])

        # Table: top 50 highest-risk bookings
        table_pairs = sorted(zip(tonight_sample.iterrows(), all_scores), key=lambda x: x[1], reverse=True)[:50]
    else:
        total_bookings  = len(sample)
        high_total      = high
        med_total       = med
        low_total       = low
        avg_adr         = float(avg_rate)
        avg_nights      = 2.0
        revenue_at_risk = int(high_total * avg_adr * avg_nights)
        lt_high_js      = json.dumps([0, 0, 0, 0, 0])
        lt_med_js       = json.dumps([0, 0, 0, 0, 0])
        lt_low_js       = json.dumps([0, 0, 0, 0, 0])
        table_pairs     = list(zip(sample.iterrows(), scores))

    savings_default_bk  = int(high_total * 0.20)
    savings_default_rev = int(revenue_at_risk * 0.20)

    bookings_data = []
    for (_, booking), _ in table_pairs:
        bookings_data.append({k: float(booking.get(k, 0)) for k in features})
    bookings_js = json.dumps(bookings_data)

    rows = ""
    for i, ((_, booking), score) in enumerate(table_pairs):
        if score >= 70:
            badge = f'<span class="badge high">{t("high", lang)} {score:.1f}%</span>'
            action = f'<button class="btn dep" onclick="event.stopPropagation(); openEmailComposer({i}, \'deposit\')">{t("req_dep", lang)}</button>'
        elif score >= 40:
            badge = f'<span class="badge med">{t("medium", lang)} {score:.1f}%</span>'
            action = f'<button class="btn rem" onclick="event.stopPropagation(); openEmailComposer({i}, \'reminder\')">{t("send_rem", lang)}</button>'
        else:
            badge = f'<span class="badge low">{t("low", lang)} {score:.1f}%</span>'
            action = f'<button class="btn mon" onclick="event.stopPropagation(); openEmailComposer({i}, \'monitor\')">{t("monitor", lang)}</button>'

        lead = int(booking.get("lead_time", 0))
        adr  = int(booking.get("adr", 0))
        rep  = t("yes", lang) if booking.get("is_repeated_guest", 0) else t("no", lang)
        canc = int(booking.get("previous_cancellations", 0))

        rows += f"""<tr class="clickable-row" onclick="showDetail({i}, {score:.1f})">
            <td><span style="font-family:'JetBrains Mono',monospace;color:#94a3b8;font-size:11px">{i+1}</span></td>
            <td><span style="color:#0d1120;font-weight:600">{t("booking", lang)} {i+1}</span></td>
            <td>{lead} {t("days", lang)}</td><td>EUR {adr}</td><td>{rep}</td><td>{canc}</td>
            <td>{badge}</td><td>{action}</td>
        </tr>"""

    upload_banner = ""
    clear_button = ""
    if uploaded:
        upload_banner = f'<div class="upload-banner">📂 Your uploaded data is loaded</div>'
        clear_button = f'<a href="/clear" class="clear-btn">🗑 Clear File</a>'

    bulk_action_html = f'''<div class="section-title">{t("take_action", lang)}</div>
<div class="bulk-action-zone">
    <div class="bulk-action-card">
        <div class="bulk-action-icon">📧</div>
        <div class="bulk-action-title">{t("send_mass", lang)}</div>
        <div class="bulk-action-sub">{t("send_high", lang, high=high)}</div>
        <button class="bulk-action-btn" onclick="openBulkEmailComposer()">{t("send_btn", lang)}</button>
    </div>
    <div class="bulk-action-card">
        <div class="bulk-action-icon">💰</div>
        <div class="bulk-action-title">{t("request_dep", lang)}</div>
        <div class="bulk-action-sub">{t("dep_template", lang)}</div>
        <button class="bulk-action-btn deposit-btn" onclick="openBulkEmailTemplate('deposit')">{t("dep_btn", lang)}</button>
    </div>
    <div class="bulk-action-card">
        <div class="bulk-action-icon">⏰</div>
        <div class="bulk-action-title">{t("reminders", lang)}</div>
        <div class="bulk-action-sub">{t("rem_template", lang)}</div>
        <button class="bulk-action-btn reminder-btn" onclick="openBulkEmailTemplate('reminder')">{t("rem_btn", lang)}</button>
    </div>
</div>'''

    return f"""<!DOCTYPE html>
<html>
<head>
<title>Occupado — {hotel_name}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*,*::before,*::after{{margin:0;padding:0;box-sizing:border-box;}}
body{{background:#ffffff;color:#0d1120;font-family:'Inter',sans-serif;-webkit-font-smoothing:antialiased;}}
a{{text-decoration:none;}}
/* TOPBAR */
.topbar{{height:62px;background:#ffffff;border-bottom:1px solid #e4e8f0;display:flex;align-items:center;padding:0 32px;position:sticky;top:0;z-index:100;}}
.topbar-brand{{display:flex;align-items:center;gap:6px;}}
.topbar-name{{font-family:'Syne',sans-serif;font-size:17px;font-weight:800;color:#0d1120;letter-spacing:-0.4px;}}
.topbar-name span{{color:#00d165;}}
.topbar-hotel{{font-family:'JetBrains Mono',monospace;font-size:11px;color:#94a3b8;margin-left:8px;padding-left:12px;border-left:1px solid #e4e8f0;}}
.topbar-right{{display:flex;align-items:center;gap:8px;margin-left:auto;}}
.lang-selector{{padding:7px 12px;background:transparent;border:1px solid #e4e8f0;border-radius:7px;color:#64748b;font-size:12px;cursor:pointer;font-family:'Inter',sans-serif;outline:none;}}
.lang-selector:hover{{border-color:#cbd5e1;color:#0d1120;}}
.btn-nav{{padding:7px 16px;background:transparent;border:1px solid #e4e8f0;border-radius:7px;color:#64748b;font-size:12px;font-weight:500;text-decoration:none;transition:all .2s;display:inline-flex;align-items:center;gap:5px;}}
.btn-nav:hover{{border-color:#cbd5e1;color:#0d1120;}}
.clear-btn{{padding:7px 14px;background:#fef2f2;border:1px solid #fecaca;border-radius:7px;color:#dc2626;font-size:12px;font-weight:500;text-decoration:none;transition:all .2s;}}
.clear-btn:hover{{background:#fee2e2;}}
/* WELCOME BANNER */
.welcome-banner{{background:#f0fdf4;border-bottom:1px solid #bbf7d0;padding:11px 32px;display:flex;align-items:center;justify-content:space-between;font-size:13px;color:#166534;}}
.welcome-banner strong{{color:#0d1120;}}
.welcome-close{{background:none;border:none;color:#94a3b8;font-size:18px;cursor:pointer;padding:0 4px;line-height:1;}}
.welcome-close:hover{{color:#0d1120;}}
/* CONTENT */
.content{{padding:36px 32px;}}
.page-sub{{font-family:'JetBrains Mono',monospace;font-size:11px;color:#94a3b8;margin-bottom:28px;letter-spacing:0.5px;}}
.section-title{{font-family:'Syne',sans-serif;font-size:18px;font-weight:700;color:#0d1120;letter-spacing:-0.4px;margin-bottom:14px;margin-top:36px;}}
/* UPLOAD ZONE */
.upload-zone{{border:1px dashed #cbd5e1;border-radius:14px;padding:36px;text-align:center;background:#f8fafc;margin-bottom:28px;cursor:pointer;transition:all .2s;}}
.upload-zone:hover{{border-color:#00d165;background:#f0fdf4;}}
.upload-zone-title{{font-family:'Syne',sans-serif;font-size:16px;font-weight:700;color:#0d1120;margin-bottom:6px;}}
.upload-zone-sub{{font-size:13px;color:#64748b;margin-bottom:18px;}}
.upload-btn{{padding:10px 24px;background:#00d165;color:#080c14;border:none;border-radius:8px;font-size:13px;font-weight:700;cursor:pointer;font-family:'Inter',sans-serif;}}
.upload-banner{{background:#f0fdf4;border:1px solid #bbf7d0;border-radius:9px;padding:12px 18px;font-size:13px;color:#166534;margin-bottom:20px;font-weight:500;}}
/* STATS */
.stats{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:28px;}}
.stat{{background:#f8fafc;border:1px solid #e4e8f0;border-radius:12px;padding:20px 22px;}}
.stat-value{{font-family:'Syne',sans-serif;font-size:44px;font-weight:800;line-height:1;letter-spacing:-2px;}}
.stat-label{{font-family:'JetBrains Mono',monospace;font-size:10px;color:#94a3b8;margin-top:6px;text-transform:uppercase;letter-spacing:1px;}}
/* OPTIMIZER */
.optimizer{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:36px;}}
.opt-main{{background:#f0fdf4;border:1px solid #bbf7d0;border-radius:12px;padding:28px;}}
.opt-value{{font-family:'Syne',sans-serif;font-size:72px;font-weight:800;color:#00d165;line-height:1;letter-spacing:-3px;}}
.opt-label{{font-family:'JetBrains Mono',monospace;font-size:10px;color:#64748b;margin-top:6px;text-transform:uppercase;letter-spacing:1px;}}
.opt-btn{{margin-top:20px;width:100%;padding:11px;background:#00d165;border:none;border-radius:8px;color:#080c14;font-size:13px;font-weight:700;cursor:pointer;font-family:'Inter',sans-serif;transition:all .2s;}}
.opt-btn:hover{{background:#04e270;}}
.opt-stats{{background:#f8fafc;border:1px solid #e4e8f0;border-radius:12px;padding:22px;}}
.opt-row{{display:flex;justify-content:space-between;align-items:center;padding:9px 0;border-bottom:1px solid #f1f5f9;font-size:13px;}}
.opt-row:last-child{{border-bottom:none;}}
.opt-row-label{{color:#64748b;}}
.opt-row-value{{font-family:'JetBrains Mono',monospace;font-weight:500;color:#0d1120;}}
/* BULK ACTIONS */
.bulk-action-zone{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:36px;}}
.bulk-action-card{{background:#f8fafc;border:1px solid #e4e8f0;border-radius:12px;padding:22px;transition:border-color .2s;}}
.bulk-action-card:hover{{border-color:#cbd5e1;}}
.bulk-action-icon{{font-size:26px;margin-bottom:10px;}}
.bulk-action-title{{font-family:'Syne',sans-serif;font-size:14px;font-weight:700;color:#0d1120;margin-bottom:5px;letter-spacing:-0.2px;}}
.bulk-action-sub{{font-size:12px;color:#64748b;margin-bottom:16px;line-height:1.5;}}
.bulk-action-btn{{padding:9px 14px;background:#ffffff;border:1px solid #e4e8f0;border-radius:8px;color:#0d1120;font-size:12px;font-weight:600;cursor:pointer;width:100%;font-family:'Inter',sans-serif;transition:all .2s;}}
.bulk-action-btn:hover{{background:#f1f5f9;}}
.bulk-action-btn.deposit-btn{{background:#fef2f2;border-color:#fecaca;color:#dc2626;}}
.bulk-action-btn.deposit-btn:hover{{background:#fee2e2;}}
.bulk-action-btn.reminder-btn{{background:#fffbeb;border-color:#fde68a;color:#b45309;}}
.bulk-action-btn.reminder-btn:hover{{background:#fef3c7;}}
/* TABLE */
table{{width:100%;border-collapse:collapse;background:#ffffff;border-radius:14px;overflow:hidden;border:1px solid #e4e8f0;}}
th{{background:#f8fafc;color:#94a3b8;font-family:'JetBrains Mono',monospace;font-size:10px;text-transform:uppercase;letter-spacing:1px;padding:13px 16px;text-align:left;border-bottom:1px solid #e4e8f0;}}
td{{padding:13px 16px;font-size:13px;border-bottom:1px solid #f1f5f9;color:#374151;}}
.clickable-row{{cursor:pointer;}}
.clickable-row:hover td{{background:#f8fafc;}}
td:first-child{{color:#0d1120;font-weight:600;}}
.badge{{padding:3px 10px;border-radius:99px;font-family:'JetBrains Mono',monospace;font-size:10.5px;font-weight:500;border:1px solid;}}
.high{{background:#fef2f2;color:#dc2626;border-color:#fecaca;}}
.med{{background:#fffbeb;color:#b45309;border-color:#fde68a;}}
.low{{background:#f0fdf4;color:#16a34a;border-color:#bbf7d0;}}
.btn{{padding:6px 13px;border-radius:7px;font-size:11.5px;font-weight:500;cursor:pointer;border:1px solid;background:transparent;font-family:'Inter',sans-serif;transition:all .2s;}}
.dep{{color:#dc2626;border-color:#fecaca;}}
.dep:hover{{background:#fef2f2;}}
.rem{{color:#b45309;border-color:#fde68a;}}
.rem:hover{{background:#fffbeb;}}
.mon{{color:#16a34a;border-color:#bbf7d0;}}
.mon:hover{{background:#f0fdf4;}}
/* MODAL */
.modal-overlay{{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:1000;align-items:center;justify-content:center;backdrop-filter:blur(4px);}}
.modal-overlay.show{{display:flex;}}
.modal{{background:#ffffff;border:1px solid #e4e8f0;border-radius:20px;padding:40px;width:100%;max-width:520px;max-height:85vh;overflow-y:auto;position:relative;box-shadow:0 16px 48px rgba(0,0,0,0.1);}}
.modal-close{{position:absolute;top:16px;right:18px;font-size:20px;cursor:pointer;color:#94a3b8;background:none;border:none;line-height:1;transition:color .2s;}}
.modal-close:hover{{color:#0d1120;}}
.modal-title{{font-family:'Syne',sans-serif;font-size:20px;font-weight:800;color:#0d1120;margin-bottom:3px;letter-spacing:-0.4px;}}
.modal-sub{{font-family:'JetBrains Mono',monospace;font-size:11px;color:#94a3b8;margin-bottom:22px;}}
.score-display{{font-family:'Syne',sans-serif;font-size:60px;font-weight:800;line-height:1;margin-bottom:8px;letter-spacing:-3px;}}
.score-bar-bg{{height:8px;background:#f1f5f9;border-radius:4px;overflow:hidden;margin-bottom:12px;}}
.score-bar-fill{{height:100%;border-radius:4px;}}
.score-verdict{{font-size:13px;font-weight:600;padding:7px 14px;border-radius:7px;display:inline-block;margin-bottom:8px;}}
/* EMAIL COMPOSER */
.email-composer{{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:1001;align-items:center;justify-content:center;backdrop-filter:blur(4px);}}
.email-composer.show{{display:flex;}}
.email-box{{background:#ffffff;border:1px solid #e4e8f0;border-radius:20px;padding:36px;width:100%;max-width:680px;max-height:90vh;overflow-y:auto;box-shadow:0 16px 48px rgba(0,0,0,0.1);}}
.email-title{{font-family:'Syne',sans-serif;font-size:18px;font-weight:800;color:#0d1120;margin-bottom:3px;letter-spacing:-0.4px;}}
.email-label{{font-family:'JetBrains Mono',monospace;font-size:10px;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;display:block;margin-bottom:7px;font-weight:500;}}
.email-input{{width:100%;padding:11px 14px;background:#f8fafc;border:1px solid #e4e8f0;border-radius:9px;font-size:13.5px;color:#0d1120;outline:none;margin-bottom:14px;font-family:'Inter',sans-serif;transition:border-color .2s;}}
.email-input:focus{{border-color:#00d165;background:#ffffff;}}
.email-input::placeholder{{color:#cbd5e1;}}
.email-textarea{{width:100%;padding:11px 14px;background:#f8fafc;border:1px solid #e4e8f0;border-radius:9px;font-size:13px;color:#0d1120;outline:none;resize:vertical;min-height:180px;margin-bottom:14px;font-family:'Inter',sans-serif;line-height:1.6;transition:border-color .2s;}}
.email-textarea:focus{{border-color:#00d165;background:#ffffff;}}
.email-textarea::placeholder{{color:#cbd5e1;}}
.email-actions{{display:flex;gap:10px;margin-top:20px;}}
.email-send{{flex:1;padding:12px;background:#00d165;color:#080c14;border:none;border-radius:9px;font-size:13.5px;font-weight:700;cursor:pointer;font-family:'Inter',sans-serif;transition:all .2s;}}
.email-send:hover{{background:#04e270;}}
.email-cancel{{flex:1;padding:12px;background:#f8fafc;color:#64748b;border:1px solid #e4e8f0;border-radius:9px;font-size:13.5px;font-weight:500;cursor:pointer;font-family:'Inter',sans-serif;}}
.email-cancel:hover{{background:#f1f5f9;color:#0d1120;}}
.bulk-email-composer{{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:1002;align-items:center;justify-content:center;backdrop-filter:blur(4px);}}
.bulk-email-composer.show{{display:flex;}}
.bulk-email-box{{background:#ffffff;border:1px solid #e4e8f0;border-radius:20px;padding:36px;width:100%;max-width:680px;max-height:90vh;overflow-y:auto;box-shadow:0 16px 48px rgba(0,0,0,0.1);}}
.bulk-email-title{{font-family:'Syne',sans-serif;font-size:18px;font-weight:800;color:#0d1120;margin-bottom:3px;letter-spacing:-0.4px;}}
.bulk-email-subtitle{{font-family:'JetBrains Mono',monospace;font-size:11px;color:#94a3b8;}}
.bulk-email-actions{{display:flex;gap:10px;margin-top:20px;}}
.bulk-email-send{{flex:1;padding:12px;background:#00d165;color:#080c14;border:none;border-radius:9px;font-size:13.5px;font-weight:700;cursor:pointer;font-family:'Inter',sans-serif;transition:all .2s;}}
.bulk-email-send:hover{{background:#04e270;}}
.bulk-email-send.deposit{{background:#fef2f2;color:#dc2626;border:1px solid #fecaca;}}
.bulk-email-send.deposit:hover{{background:#fee2e2;}}
.bulk-email-send.reminder{{background:#fffbeb;color:#b45309;border:1px solid #fde68a;}}
.bulk-email-send.reminder:hover{{background:#fef3c7;}}
.bulk-email-cancel{{flex:1;padding:12px;background:#f8fafc;color:#64748b;border:1px solid #e4e8f0;border-radius:9px;font-size:13.5px;font-weight:500;cursor:pointer;font-family:'Inter',sans-serif;}}
.bulk-booking-row{{padding:8px 10px;margin-bottom:4px;background:#fef2f2;border:1px solid #fecaca;border-radius:7px;font-size:11px;display:flex;justify-content:space-between;align-items:center;transition:all 0.2s;cursor:pointer;user-select:none;color:#374151;}}
.bulk-booking-row:hover{{background:#fee2e2;}}
/* TOAST */
.toast{{position:fixed;bottom:24px;right:24px;background:#0d1120;color:#ffffff;border-radius:10px;padding:14px 18px;font-size:13px;transform:translateY(70px);opacity:0;transition:all 0.3s;z-index:2000;box-shadow:0 8px 24px rgba(0,0,0,0.15);}}
.toast.show{{transform:translateY(0);opacity:1;}}
/* HERO CARDS */
.hero-cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:28px;}}
.hero-card{{background:#f8fafc;border:1px solid #e4e8f0;border-radius:12px;padding:22px;}}
.hero-card-red{{background:#fef2f2;border-color:#fecaca;}}
.hero-val{{font-family:'Syne',sans-serif;font-size:34px;font-weight:800;line-height:1;letter-spacing:-1.5px;color:#0d1120;}}
.hero-lbl{{font-family:'JetBrains Mono',monospace;font-size:10px;color:#94a3b8;margin-top:6px;text-transform:uppercase;letter-spacing:1px;}}
.hero-sub{{font-size:12px;color:#64748b;margin-top:4px;}}
/* CHARTS */
.charts-row{{display:grid;grid-template-columns:260px 1fr;gap:12px;margin-bottom:28px;}}
.chart-card{{background:#f8fafc;border:1px solid #e4e8f0;border-radius:12px;padding:22px;}}
.chart-head{{font-family:'Syne',sans-serif;font-size:14px;font-weight:700;color:#0d1120;margin-bottom:16px;letter-spacing:-0.2px;}}
/* SAVINGS CALC */
.savings-wrap{{background:#f0fdf4;border:1px solid #bbf7d0;border-radius:14px;padding:28px;display:grid;grid-template-columns:1fr 1fr;gap:32px;margin-bottom:36px;align-items:center;}}
.sav-main{{text-align:center;}}
.sav-lbl{{font-family:'JetBrains Mono',monospace;font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:1px;}}
.sav-pct{{font-family:'Syne',sans-serif;font-size:60px;font-weight:800;color:#00d165;line-height:1;letter-spacing:-3px;margin:8px 0;}}
.sav-slider{{width:100%;margin:16px 0 4px;accent-color:#00d165;cursor:pointer;}}
.sav-range{{display:flex;justify-content:space-between;font-family:'JetBrains Mono',monospace;font-size:10px;color:#94a3b8;}}
.sav-results{{}}
.sav-row{{display:flex;justify-content:space-between;align-items:center;padding:14px 0;border-bottom:1px solid #d1fae5;font-size:13px;}}
.sav-row:last-child{{border-bottom:none;}}
.sav-row-lbl{{color:#64748b;}}
.sav-row-val{{font-family:'JetBrains Mono',monospace;font-weight:600;color:#0d1120;font-size:15px;}}
.sav-row-val.green{{color:#16a34a;}}
</style>
</head>
<body>
<div class="topbar">
  <div class="topbar-brand">
    <span class="topbar-name">Occup<span>ado</span></span>
    <span class="topbar-hotel">{hotel_name}</span>
  </div>
  <div class="topbar-right">
    {clear_button}
    <select class="lang-selector" onchange="changeLanguage(this.value)">
      <option value="en" {"selected" if lang == "en" else ""}>EN</option>
      <option value="nl" {"selected" if lang == "nl" else ""}>NL</option>
      <option value="fr" {"selected" if lang == "fr" else ""}>FR</option>
    </select>
    <a href="/settings" class="btn-nav">{t("settings", lang)}</a>
    <a href="/logout" class="btn-nav">{t("sign_out", lang)}</a>
  </div>
</div>
{f'''<div id="welcome-banner" class="welcome-banner">
    <span>Welcome, <strong>{hotel_name}</strong>. Upload your booking data to get your first risk scores.</span>
    <button onclick="document.getElementById('welcome-banner').style.display='none'" class="welcome-close">×</button>
</div>''' if first_login else ''}
<div class="content">
<div class="page-sub">{t("live_dashboard", lang)} · {total_bookings} {t("bookings_analysed", lang)}</div>
{upload_banner}

<div class="section-title">Overview</div>
<div class="hero-cards">
  <div class="hero-card">
    <div class="hero-val">{total_bookings}</div>
    <div class="hero-lbl">Bookings Analysed</div>
  </div>
  <div class="hero-card hero-card-red">
    <div class="hero-val" style="color:#dc2626">{high_total}</div>
    <div class="hero-lbl">High Risk</div>
    <div class="hero-sub">{f"{high_total/total_bookings*100:.0f}%" if total_bookings > 0 else "0%"} of bookings</div>
  </div>
  <div class="hero-card hero-card-red">
    <div class="hero-val" style="color:#dc2626">€{revenue_at_risk:,}</div>
    <div class="hero-lbl">Revenue at Risk</div>
    <div class="hero-sub">from high-risk bookings</div>
  </div>
  <div class="hero-card">
    <div class="hero-val">€{avg_adr:.0f}</div>
    <div class="hero-lbl">Avg Daily Rate</div>
    <div class="hero-sub">{avg_nights:.1f} avg nights/stay</div>
  </div>
</div>

<div class="charts-row">
  <div class="chart-card" style="display:flex;flex-direction:column;align-items:center;">
    <div class="chart-head" style="align-self:flex-start">Risk Distribution</div>
    <canvas id="riskDoughnut" width="200" height="200"></canvas>
  </div>
  <div class="chart-card">
    <div class="chart-head">Risk by Lead Time</div>
    <canvas id="leadTimeChart" height="180"></canvas>
  </div>
</div>

<div class="section-title">Savings Calculator</div>
<div class="savings-wrap">
  <div class="sav-main">
    <div class="sav-lbl">If you convert</div>
    <div class="sav-pct" id="savPct">20%</div>
    <div class="sav-lbl">of high-risk bookings</div>
    <input type="range" min="5" max="60" value="20" step="5" class="sav-slider" id="savSlider" oninput="updateSavings(this.value)">
    <div class="sav-range"><span>5%</span><span>60%</span></div>
  </div>
  <div class="sav-results">
    <div class="sav-row">
      <span class="sav-row-lbl">Bookings saved</span>
      <span class="sav-row-val" id="savBookings">{savings_default_bk}</span>
    </div>
    <div class="sav-row">
      <span class="sav-row-lbl">Revenue recovered</span>
      <span class="sav-row-val green" id="savRevenue">€{savings_default_rev:,}</span>
    </div>
    <div class="sav-row">
      <span class="sav-row-lbl">Annual projection</span>
      <span class="sav-row-val green" id="savAnnual">€{savings_default_rev * 12:,}</span>
    </div>
  </div>
</div>

<div class="section-title">{t("optimizer", lang)}</div>
<div class="optimizer">
    <div class="opt-main">
        <div class="opt-label">{t("safe_rooms", lang)}</div>
        <div class="opt-value">+{safe_overbook}</div>
        <div class="opt-label" style="margin-top:8px">{t("revenue", lang)} {revenue:.0f}</div>
        <button class="opt-btn" onclick="showToast('Recommendation applied! {safe_overbook} rooms released.')">{t("apply", lang)}</button>
    </div>
    <div class="opt-stats">
        <div class="opt-row"><span class="opt-row-label">{t("bookings_analysed_stat", lang)}</span><span class="opt-row-value">{total_bookings}</span></div>
        <div class="opt-row"><span class="opt-row-label">{t("predicted", lang)}</span><span class="opt-row-value" style="color:#cc0000">{predicted_noshows}</span></div>
        <div class="opt-row"><span class="opt-row-label">{t("confidence", lang)}</span><span class="opt-row-value" style="color:#008000">80.7%</span></div>
        <div class="opt-row"><span class="opt-row-label">{t("walk_risk", lang)}</span><span class="opt-row-value" style="color:#008000">2.1%</span></div>
        <div class="opt-row"><span class="opt-row-label">{t("avg_rate", lang)}</span><span class="opt-row-value">EUR {avg_rate:.0f}</span></div>
    </div>
</div>
{bulk_action_html}
<div class="section-title">{t("click_row", lang)}</div>
<table>
<thead><tr><th>#</th><th>{t("booking", lang)}</th><th>{t("lead", lang)}</th><th>{t("rate", lang)}</th><th>{t("returning", lang)}</th><th>{t("cancels", lang)}</th><th>{t("risk", lang)}</th><th>{t("action", lang)}</th></tr></thead>
<tbody>{rows}</tbody>
</table>
<div style="margin-top:48px;">
<div class="section-title">{t("upload_data", lang)}</div>
<form method="POST" action="/upload" enctype="multipart/form-data">
    <div class="upload-zone" onclick="document.getElementById('csv-input').click()">
        <div class="upload-zone-title">{t("drop_csv", lang)}</div>
        <div class="upload-zone-sub">{t("export_pms", lang)}</div>
        <input type="file" id="csv-input" name="csv_file" accept=".csv" style="display:none" onchange="this.form.submit()">
        <button type="button" class="upload-btn" onclick="event.stopPropagation();document.getElementById('csv-input').click()">{t("choose_file", lang)}</button>
    </div>
</form>
</div>
</div>

<div class="modal-overlay" id="modal">
    <div class="modal">
        <button class="modal-close" onclick="closeModal()">✕</button>
        <div class="modal-title" id="modal-title">Booking Detail</div>
        <div class="modal-sub" id="modal-sub">AI Risk Analysis</div>
        <div class="score-display" id="modal-score">0%</div>
        <div class="score-bar-bg"><div class="score-bar-fill" id="modal-bar" style="width:0%"></div></div>
        <div class="score-verdict" id="modal-verdict"></div>
        <div id="modal-reasons"></div>
        <button style="margin-top:24px; width:100%; padding:14px; border:none; border-radius:10px; font-size:15px; font-weight:700; background:#008000; color:#ffffff; cursor:pointer;" onclick="closeModal()">Close</button>
    </div>
</div>

<div class="email-composer" id="emailComposer">
    <div class="email-box">
        <div style="margin-bottom:24px;">
            <div class="email-title" id="emailTitle">{t("email_guest", lang)}</div>
            <div style="font-family:'DM Mono',monospace; font-size:12px; color:#4a6648; margin-top:4px;" id="emailSubtitle">Booking 1</div>
        </div>
        
        <div>
            <label class="email-label">{t("guest_email", lang)}</label>
            <input type="email" id="guestEmail" class="email-input" placeholder="guest@example.com">
        </div>
        
        <div>
            <label class="email-label">{t("guest_name", lang)}</label>
            <input type="text" id="guestName" class="email-input" placeholder="John Doe">
        </div>
        
        <div>
            <label class="email-label">{t("subject", lang)}</label>
            <input type="text" id="emailSubject" class="email-input" placeholder="Confirm Your Booking">
        </div>
        
        <div>
            <label class="email-label">{t("message", lang)}</label>
            <textarea id="emailBody" class="email-textarea" placeholder="Dear Guest..."></textarea>
        </div>
        
        <div class="email-actions">
            <button class="email-send" onclick="sendEmailToGuest()">{t("send_email", lang)}</button>
            <button class="email-cancel" onclick="closeEmailComposer()">{t("cancel", lang)}</button>
        </div>
    </div>
</div>

<div class="bulk-email-composer" id="bulkEmailComposer">
    <div class="bulk-email-box">
        <div style="margin-bottom:24px;">
            <div class="bulk-email-title" id="bulkEmailTitle">{t("bulk_email", lang)}</div>
            <div class="bulk-email-subtitle" id="bulkEmailSubtitle">{t("select_book", lang)}</div>
        </div>
        
        <div style="background:#f5faf5; border:1px solid rgba(0,128,0,0.15); border-radius:10px; padding:12px; margin-bottom:16px;">
            <div style="margin-bottom:10px;">
                <label class="email-label">{t("select_book", lang)}</label>
                <div id="bulkBookingsList" style="max-height:150px; overflow-y:auto; margin-bottom:10px; padding:8px; background:white; border:1px solid rgba(0,128,0,0.1); border-radius:6px;"></div>
                <input type="text" id="bulkBookingsInput" class="email-input" placeholder="Edit or remove booking numbers..." style="margin-bottom:6px;">
                <div style="font-family:'DM Mono',monospace; font-size:10px; color:#999;">{t("auto_pop", lang)}</div>
            </div>
            <div style="background:#f0f0f0; padding:10px; border-radius:6px; text-align:center; display:flex; justify-content:space-between; align-items:center;">
                <div style="display:flex; align-items:center; gap:12px;">
                    <span style="font-family:'Syne',sans-serif; font-size:24px; font-weight:800; color:#008000;" id="bulkCountBig">0</span>
                    <span style="font-family:'DM Mono',monospace; font-size:12px; color:#4a6648; font-weight:600;">{t("selected_count", lang)}</span>
                </div>
                <button type="button" style="padding:8px 20px; background:#008000; color:white; border:none; border-radius:6px; font-size:12px; font-weight:600; cursor:pointer; font-family:'DM Sans',sans-serif;" onclick="saveBookingChanges()">{t("save_changes", lang)}</button>
            </div>
        </div>
        
        <div>
            <label class="email-label">{t("subject", lang)}</label>
            <input type="text" id="bulkEmailSubject" class="email-input" placeholder="Important: Your Booking">
        </div>
        
        <div>
            <label class="email-label">{t("message", lang)}</label>
            <textarea id="bulkEmailBody" class="email-textarea" placeholder="Dear Guest..."></textarea>
        </div>
        
        <div class="bulk-email-actions">
            <button class="bulk-email-send" id="bulkEmailSendBtn" onclick="sendBulkEmailToGuests()">{t("send_selected", lang)}</button>
            <button class="bulk-email-cancel" onclick="closeBulkEmailComposer()">{t("cancel", lang)}</button>
        </div>
    </div>
</div>

<div class="toast" id="toast"></div>
<script>
const bookings = {bookings_js};
const currentLang = "{lang}";
const translations = {json.dumps(TRANSLATIONS)};

function changeLanguage(lang) {{
    window.location.href = '/dashboard?lang=' + lang;
}}

function t(key) {{
    return translations[currentLang][key] || translations['en'][key] || key;
}}

function populateBulkBookingsList() {{
    const list = document.getElementById('bulkBookingsList');
    const input = document.getElementById('bulkBookingsInput');
    list.innerHTML = '';
    
    const rows = document.querySelectorAll('.clickable-row');
    let highRiskNums = [];
    let html = '';
    
    rows.forEach((row, idx) => {{
        const badgeSpan = row.querySelector('.badge.high');
        if (badgeSpan) {{
            const cells = row.querySelectorAll('td');
            const scoreText = badgeSpan.textContent;
            const leadTime = cells[1] ? cells[1].textContent : '-';
            const roomRate = cells[2] ? cells[2].textContent : '-';
            
            highRiskNums.push(idx + 1);
            
            html += `<div class="bulk-booking-row" data-booking="` + (idx + 1) + `" style="padding:8px; margin-bottom:4px; background:rgba(204, 0, 0, 0.08); border:2px solid rgba(204, 0, 0, 0.2); border-radius:6px; font-size:11px; display:flex; justify-content:space-between; align-items:center; transition:all 0.3s; cursor:pointer; user-select:none;" onclick="addBookingToField(` + (idx + 1) + `)">
                <div>
                    <span style="color:#008000; font-weight:600;">Booking ` + (idx + 1) + `</span>
                    <span style="color:#999; margin:0 8px;">·</span>
                    <span style="color:#999; font-size:10px;">` + leadTime + ` lead</span>
                    <span style="color:#999; margin:0 4px;">·</span>
                    <span style="color:#999; font-size:10px;">` + roomRate + `</span>
                </div>
                <span style="color:#cc0000; font-weight:600;">` + scoreText + `</span>
            </div>`;
        }}
    }});
    
    if (html === '') {{
        list.innerHTML = '<div style="padding:10px; color:#999; font-size:11px; text-align:center;">No high-risk bookings found</div>';
    }} else {{
        list.innerHTML = html;
    }}
    
    const bookingsList = highRiskNums.join(', ');
    input.value = bookingsList;
    
    input.addEventListener('input', handleBookingInputChange);
    
    updateSendCount();
}}

function addBookingToField(bookingNum) {{
    const input = document.getElementById('bulkBookingsInput');
    const current = input.value.trim();
    const nums = current.split(',').map(n => parseInt(n.trim())).filter(n => !isNaN(n));
    
    if (!nums.includes(bookingNum)) {{
        if (current === '') {{
            input.value = bookingNum.toString();
        }} else {{
            input.value = current + ', ' + bookingNum;
        }}
        updateBookingVisuals();
    }}
}}

function updateBookingVisuals() {{
    const input = document.getElementById('bulkBookingsInput').value.trim();
    const selectedNums = input.split(',').map(n => parseInt(n.trim())).filter(n => !isNaN(n));
    
    const bookingRows = document.querySelectorAll('.bulk-booking-row');
    
    bookingRows.forEach(row => {{
        const bookingNum = parseInt(row.getAttribute('data-booking'));
        
        if (selectedNums.includes(bookingNum)) {{
            row.style.opacity = '1';
            row.style.background = 'rgba(204, 0, 0, 0.08)';
            row.style.borderColor = 'rgba(204, 0, 0, 0.2)';
        }} else {{
            row.style.opacity = '0.4';
            row.style.background = 'rgba(100, 100, 100, 0.08)';
            row.style.borderColor = 'rgba(100, 100, 100, 0.1)';
        }}
    }});
    
    updateSendCount();
}}

function openBulkEmailComposer() {{
    populateBulkBookingsList();
    document.getElementById('bulkEmailSubject').value = 'Regarding Your Upcoming Reservation';
    document.getElementById('bulkEmailBody').value = 'Dear Valued Guest,\\n\\nWe wanted to reach out regarding your upcoming reservation. Please confirm your booking details.\\n\\nBest regards,\\nThe Hotel Team';
    document.getElementById('bulkEmailComposer').classList.add('show');
}}

function openBulkEmailTemplate(type) {{
    populateBulkBookingsList();
    let subject = '';
    let template = '';
    let btnClass = 'bulk-email-send';
    
    if (type === 'deposit') {{
        subject = 'Please Confirm Your Reservation with Deposit';
        template = 'Dear Valued Guest,\\n\\nWe want to ensure your upcoming stay is confirmed. Please provide a deposit to guarantee your booking.\\n\\nBest regards,\\nThe Hotel Team';
        btnClass = 'bulk-email-send deposit';
    }} else {{
        subject = 'Reminder: Your Upcoming Stay';
        template = 'Dear Valued Guest,\\n\\nThis is a friendly reminder about your upcoming reservation. If you have questions, please contact us.\\n\\nBest regards,\\nThe Hotel Team';
        btnClass = 'bulk-email-send reminder';
    }}
    
    document.getElementById('bulkEmailSubject').value = subject;
    document.getElementById('bulkEmailBody').value = template;
    document.getElementById('bulkEmailSendBtn').className = btnClass;
    document.getElementById('bulkEmailComposer').classList.add('show');
}}

function handleBookingInputChange() {{
    updateBookingVisuals();
}}

function updateSendCount() {{
    const input = document.getElementById('bulkBookingsInput').value.trim();
    let count = 0;
    
    if (input === '') {{
        const rows = document.querySelectorAll('.clickable-row');
        rows.forEach(row => {{
            if (row.querySelector('.badge.high')) count++;
        }});
    }} else {{
        const nums = input.split(',').map(n => n.trim()).filter(n => n !== '');
        count = nums.length;
    }}
    
    document.getElementById('bulkCountBig').textContent = count;
}}

function saveBookingChanges() {{
    const input = document.getElementById('bulkBookingsInput').value.trim();
    const nums = input.split(',').map(n => parseInt(n.trim())).filter(n => !isNaN(n));
    
    if (nums.length === 0) {{
        showToast('Please keep at least one booking', 'error');
        return;
    }}
    
    showToast('✓ ' + nums.length + ' booking(s) selected for email', 'success');
}}

function validateAndGetSelectedBookings() {{
    const input = document.getElementById('bulkBookingsInput').value.trim();
    const rows = document.querySelectorAll('.clickable-row');
    let selected = [];
    
    if (input === '') {{
        rows.forEach((row, idx) => {{
            if (row.querySelector('.badge.high')) {{
                selected.push(idx);
            }}
        }});
    }} else {{
        const nums = input.split(',').map(n => parseInt(n.trim())).filter(n => !isNaN(n));
        
        rows.forEach((row, idx) => {{
            if (row.querySelector('.badge.high') && nums.includes(idx + 1)) {{
                selected.push(idx);
            }}
        }});
    }}
    
    return selected;
}}

function closeBulkEmailComposer() {{
    document.getElementById('bulkEmailComposer').classList.remove('show');
}}

function sendBulkEmailToGuests() {{
    const subject = document.getElementById('bulkEmailSubject').value.trim();
    const body = document.getElementById('bulkEmailBody').value.trim();
    
    if (!subject || !body) {{
        showToast('Please fill in all fields', 'error');
        return;
    }}
    
    const selected = validateAndGetSelectedBookings();
    
    if (selected.length === 0) {{
        showToast('Please select at least one booking', 'error');
        return;
    }}
    
    fetch('/send-bulk-email', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{
            count: selected.length,
            subject: subject,
            body: body
        }})
    }})
    .then(r => r.json())
    .then(data => {{
        if (data.status === 'success') {{
            closeBulkEmailComposer();
            showToast('✓ Emails sent to ' + data.count + ' guest(s)', 'success');
        }} else {{
            showToast('Error: ' + data.message, 'error');
        }}
    }})
    .catch(e => showToast('Error sending emails', 'error'));
}}

function openEmailComposer(idx, actionType) {{
    const booking = bookings[idx];
    const score = Object.values(bookings[idx]).slice(-1)[0] * 100 || 0;
    
    document.getElementById('emailTitle').textContent = 'Send Email to Guest';
    document.getElementById('emailSubtitle').textContent = 'Booking ' + (idx+1) + ' · Risk Score: ' + score.toFixed(1) + '%';
    
    let template = '';
    if (actionType === 'deposit') {{
        template = 'Dear Valued Guest,\\n\\nWe want to ensure your upcoming stay is confirmed and secured. Please provide a deposit to guarantee your booking.\\n\\nBest regards,\\nThe Hotel Team';
        document.getElementById('emailSubject').value = 'Please Confirm Your Reservation with Deposit';
    }} else if (actionType === 'reminder') {{
        template = 'Dear Valued Guest,\\n\\nWe hope you are looking forward to your stay! This is a friendly reminder about your upcoming reservation.\\n\\nBest regards,\\nThe Hotel Team';
        document.getElementById('emailSubject').value = 'Reminder: Your Upcoming Stay';
    }} else {{
        template = 'Dear Valued Guest,\\n\\nWe wanted to confirm your upcoming reservation. Please let us know if you have any questions.\\n\\nBest regards,\\nThe Hotel Team';
        document.getElementById('emailSubject').value = 'Reservation Confirmation';
    }}
    
    document.getElementById('emailBody').value = template;
    document.getElementById('guestEmail').value = '';
    document.getElementById('guestName').value = '';
    document.getElementById('emailComposer').classList.add('show');
}}

function closeEmailComposer() {{
    document.getElementById('emailComposer').classList.remove('show');
}}

function sendEmailToGuest() {{
    const email = document.getElementById('guestEmail').value.trim();
    const subject = document.getElementById('emailSubject').value.trim();
    const body = document.getElementById('emailBody').value.trim();
    
    if (!email || !subject || !body) {{
        showToast('Please fill in all fields', 'error');
        return;
    }}
    
    fetch('/send-guest-email', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{guest_email: email, subject: subject, body: body}})
    }})
    .then(r => r.json())
    .then(data => {{
        if (data.status === 'success') {{
            closeEmailComposer();
            showToast('Email sent successfully', 'success');
        }} else {{
            showToast('Error: ' + data.message, 'error');
        }}
    }})
    .catch(() => showToast('Error sending email', 'error'));
}}

function showDetail(idx, score) {{
    const booking = bookings[idx];
    document.getElementById('modal-title').textContent = 'Booking ' + (idx+1);
    document.getElementById('modal-sub').textContent = 'Lead time: ' + booking.lead_time + ' days · EUR ' + booking.adr + '/night';
    document.getElementById('modal-score').textContent = score.toFixed(1) + '%';
    
    const bar = document.getElementById('modal-bar');
    bar.style.width = score + '%';
    if (score >= 70) {{
        bar.style.background = '#cc0000';
        document.getElementById('modal-score').style.color = '#cc0000';
        document.getElementById('modal-verdict').textContent = 'HIGH RISK';
        document.getElementById('modal-verdict').style.background = 'rgba(255,69,96,0.1)';
        document.getElementById('modal-verdict').style.color = '#cc0000';
    }} else if (score >= 40) {{
        bar.style.background = '#cc6600';
        document.getElementById('modal-score').style.color = '#cc6600';
        document.getElementById('modal-verdict').textContent = 'MEDIUM RISK';
        document.getElementById('modal-verdict').style.background = 'rgba(255,179,64,0.1)';
        document.getElementById('modal-verdict').style.color = '#cc6600';
    }} else {{
        bar.style.background = '#008000';
        document.getElementById('modal-score').style.color = '#008000';
        document.getElementById('modal-verdict').textContent = 'LOW RISK';
        document.getElementById('modal-verdict').style.background = 'rgba(0,128,0,0.1)';
        document.getElementById('modal-verdict').style.color = '#008000';
    }}
    document.getElementById('modal').classList.add('show');
}}

function closeModal() {{
    document.getElementById('modal').classList.remove('show');
}}

function showToast(msg, type) {{
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    t.style.background = type === 'error' ? '#cc0000' : '#008000';
    setTimeout(() => t.classList.remove('show'), 3000);
}}

document.getElementById('modal').addEventListener('click', e => {{ if (e.target === this) closeModal(); }});
document.getElementById('emailComposer').addEventListener('click', e => {{ if (e.target === this) closeEmailComposer(); }});
document.getElementById('bulkEmailComposer').addEventListener('click', e => {{ if (e.target === this) closeBulkEmailComposer(); }});

// Risk distribution doughnut
(function() {{
  const ctx = document.getElementById('riskDoughnut');
  if (!ctx) return;
  new Chart(ctx, {{
    type: 'doughnut',
    data: {{
      labels: ['High Risk', 'Medium', 'Low Risk'],
      datasets: [{{
        data: [{high_total}, {med_total}, {low_total}],
        backgroundColor: ['#fecaca', '#fde68a', '#bbf7d0'],
        borderColor: ['#dc2626', '#d97706', '#16a34a'],
        borderWidth: 1.5
      }}]
    }},
    options: {{
      cutout: '65%',
      plugins: {{
        legend: {{ position: 'bottom', labels: {{ font: {{ family: 'Inter', size: 11 }}, padding: 12 }} }}
      }}
    }}
  }});
}})();

// Lead-time stacked bar
(function() {{
  const ctx = document.getElementById('leadTimeChart');
  if (!ctx) return;
  new Chart(ctx, {{
    type: 'bar',
    data: {{
      labels: ['0–7 days', '8–30 days', '31–60 days', '61–90 days', '90+ days'],
      datasets: [
        {{ label: 'High Risk', data: {lt_high_js}, backgroundColor: '#fecaca', borderColor: '#dc2626', borderWidth: 1 }},
        {{ label: 'Medium',    data: {lt_med_js},  backgroundColor: '#fde68a', borderColor: '#d97706', borderWidth: 1 }},
        {{ label: 'Low Risk',  data: {lt_low_js},  backgroundColor: '#bbf7d0', borderColor: '#16a34a', borderWidth: 1 }}
      ]
    }},
    options: {{
      responsive: true,
      scales: {{
        x: {{ stacked: true, grid: {{ display: false }}, ticks: {{ font: {{ family: 'Inter', size: 11 }} }} }},
        y: {{ stacked: true, beginAtZero: true, ticks: {{ font: {{ family: 'Inter', size: 11 }} }} }}
      }},
      plugins: {{
        legend: {{ position: 'bottom', labels: {{ font: {{ family: 'Inter', size: 11 }}, padding: 12 }} }}
      }}
    }}
  }});
}})();

// Savings calculator
const _savHighTotal = {high_total};
const _savAvgAdr    = {avg_adr:.2f};
const _savAvgNights = {avg_nights:.2f};
function updateSavings(pct) {{
  const p = parseInt(pct) / 100;
  const bk  = Math.round(_savHighTotal * p);
  const rev = Math.round(bk * _savAvgAdr * _savAvgNights);
  document.getElementById('savPct').textContent = pct + '%';
  document.getElementById('savBookings').textContent = bk.toLocaleString();
  document.getElementById('savRevenue').textContent = '€' + rev.toLocaleString();
  document.getElementById('savAnnual').textContent  = '€' + (rev * 12).toLocaleString();
}}
</script>
</body>
</html>"""
    return dashboard_html

@app.route("/robots.txt")
def robots():
    return "User-agent: *\nDisallow: /admin\nDisallow: /admin/\n", 200, {"Content-Type": "text/plain"}


@app.route("/")
def home():
    try:
        return send_file("landing.html")
    except:
        return redirect(url_for("login"))

@app.route("/landing")
def landing():
    try:
        return send_file("landing.html")
    except:
        return redirect(url_for("login"))

@app.route("/magic/<token>")
def magic_link(token):
    print(f"\n[MAGIC] Token received: {token[:30]}...")
    
    token_data = get_token_data(token)
    if not token_data:
        print(f"[MAGIC] Token not found!")
        return redirect(url_for("login"))
    
    hotel_username = token_data.get("hotel")
    csv_data = token_data.get("csv_data")

    # Check both HOTELS and REGISTERED_USERS
    if hotel_username in HOTELS:
        hotel_name = HOTELS[hotel_username]["name"]
    else:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT name FROM registered_users WHERE username=%s", (hotel_username,))
        user = cur.fetchone()
        cur.close()
        conn.close()
        if not user:
            return redirect(url_for("login"))
        hotel_name = user["name"]

    session["hotel"]        = hotel_username
    session["hotel_name"]   = hotel_name
    session["alert_email"]  = ""
    session["uploaded_csv"] = csv_data
    
    delete_token(token)
    print(f"[MAGIC] Auto-logged in: {hotel_username}")
    
    return redirect(url_for("dashboard"))

@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    success = session.pop("verified_success", "")
    if request.method == "POST":
        ip = request.remote_addr
        blocked, remaining = check_rate_limit(ip)
        if blocked:
            error = f"Too many failed attempts. Try again in {remaining // 60 + 1} minute(s)."
        else:
            username = sanitise(request.form.get("username", "")).lower()
            password = request.form.get("password", "").strip()
            # Check admin credentials
            if username == "jpdourado" and password == "livejoao":
                reset_attempts(ip)
                session.permanent = True
                session["is_admin"] = True
                return redirect(url_for("admin_panel"))
            # Check demo/hotel accounts
            if username in HOTELS and HOTELS[username]["password"] == password:
                reset_attempts(ip)
                session.permanent = True
                session["hotel"] = username
                session["hotel_name"] = HOTELS[username]["name"]
                session["alert_email"] = ""
                session["language"] = "en"
                session["first_login"] = True
                return redirect(url_for("dashboard"))
            # Check registered users in SQLite
            conn = get_db()
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT * FROM registered_users WHERE username=%s", (username,))
            user = cur.fetchone()
            cur.close()
            conn.close()
            if user:
                # Support both bcrypt hashed and legacy plain text passwords
                pw_bytes = password.encode("utf-8")
                stored   = user["password"]
                try:
                    match = bcrypt.checkpw(pw_bytes, stored.encode("utf-8"))
                except Exception:
                    match = (stored == password)
                if match:
                    if not user["verified"]:
                        error = "Please verify your email before logging in. Check your inbox."
                    else:
                        reset_attempts(ip)
                        session.permanent = True
                        session["hotel"] = username
                        session["hotel_name"] = user["name"]
                        session["alert_email"] = user["email"]
                        session["language"] = "en"
                        session["first_login"] = True
                        return redirect(url_for("dashboard"))
                else:
                    record_failed_attempt(ip)
                    error = "Invalid credentials"
            else:
                record_failed_attempt(ip)
                error = "Invalid credentials"

    error_html   = f'<div class="err">{error}</div>' if error else ''
    success_html = f'<div class="ok">{success}</div>' if success else ''

    return f"""<!DOCTYPE html>
<html>
<head><title>Occupado — Sign in</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{margin:0;padding:0;box-sizing:border-box;}}
body{{background:#f5f7fb;font-family:'Inter',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;-webkit-font-smoothing:antialiased;}}
.card{{background:#ffffff;border:1px solid #e4e8f0;border-radius:20px;width:100%;max-width:400px;padding:48px;box-shadow:0 4px 32px rgba(0,0,0,0.06);}}
.brand{{font-family:'Syne',sans-serif;font-size:22px;font-weight:800;color:#0d1120;letter-spacing:-0.5px;margin-bottom:28px;}}
.brand span{{color:#00d165;}}
.card-title{{font-family:'Syne',sans-serif;font-size:22px;font-weight:800;color:#0d1120;letter-spacing:-0.6px;margin-bottom:6px;}}
.card-sub{{font-size:13px;color:#64748b;margin-bottom:28px;}}
.err{{background:#fef2f2;border:1px solid #fecaca;color:#dc2626;padding:12px 14px;border-radius:9px;font-size:13px;margin-bottom:20px;line-height:1.5;}}
.ok{{background:#f0fdf4;border:1px solid #bbf7d0;color:#16a34a;padding:12px 14px;border-radius:9px;font-size:13px;margin-bottom:20px;line-height:1.5;}}
label{{font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:500;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;display:block;margin-bottom:7px;}}
input{{width:100%;padding:12px 14px;background:#f8fafc;border:1px solid #e4e8f0;border-radius:9px;font-size:14px;color:#0d1120;margin-bottom:16px;outline:none;font-family:'Inter',sans-serif;transition:border-color .2s,background .2s;}}
input:focus{{border-color:#00d165;background:#ffffff;}}
input::placeholder{{color:#cbd5e1;}}
.btn-submit{{width:100%;padding:13px;background:#00d165;color:#080c14;border:none;border-radius:9px;font-weight:700;cursor:pointer;font-size:14px;font-family:'Inter',sans-serif;transition:all .2s;display:flex;align-items:center;justify-content:center;gap:6px;margin-top:4px;}}
.btn-submit:hover{{background:#04e270;box-shadow:0 4px 16px rgba(0,209,101,0.25);}}
.links{{margin-top:24px;text-align:center;display:flex;flex-direction:column;gap:10px;}}
.links a{{font-size:13px;color:#94a3b8;text-decoration:none;transition:color .2s;}}
.links a span{{color:#00d165;font-weight:600;}}
.links a:hover{{color:#0d1120;}}
.divider{{height:1px;background:#e4e8f0;margin:20px 0;}}
</style>
</head>
<body>
<div class="card">
  <div class="brand">Occup<span>ado</span></div>
  <div class="card-title">Welcome back</div>
  <div class="card-sub">Sign in to your revenue dashboard</div>
  {error_html}{success_html}
  <form method="POST">
    <label>Username</label>
    <input type="text" name="username" required autocomplete="username" placeholder="your username">
    <label>Password</label>
    <input type="password" name="password" required autocomplete="current-password" placeholder="••••••••">
    <button type="submit" class="btn-submit">Sign in &rarr;</button>
  </form>
  <div class="divider"></div>
  <div class="links">
    <a href="/register">No account yet? <span>Start free pilot</span></a>
    <a href="/forgot-password">Forgot password?</a>
  </div>
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
    hotel_username = session.get("hotel", "")
    hotel_name = session.get("hotel_name", "Your Hotel")
    lang = request.args.get("lang", session.get("language", "en"))

    if lang not in TRANSLATIONS:
        lang = "en"
    session["language"] = lang

    # ── Van der Valk Mechelen gets a dedicated enriched dashboard ──
    if hotel_username == VDV_HOTEL_KEY:
        first_login = session.pop("first_login", False)
        return build_vdv_dashboard(hotel_name, lang=lang, first_login=first_login)

    uploaded_data = session.get("uploaded_csv")
    first_login = session.pop("first_login", False)
    skip_onboard = request.args.get("skip_onboard")

    # Show onboarding screen for first-time logins with no data yet
    if first_login and not uploaded_data and not skip_onboard:
        return build_empty_state(hotel_name, lang=lang)

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

    return build_dashboard(hotel_name, sample, scores, tonight_scores, tonight_sample=tonight_sample, uploaded=uploaded, lang=lang, first_login=first_login)

@app.route("/clear")
@login_required
def clear():
    session.pop("uploaded_csv", None)
    return redirect(url_for("dashboard"))

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    hotel_name = session.get("hotel_name", "Your Hotel")
    lang = session.get("language", "en")
    message = None
    
    if request.method == "POST":
        alert_email = request.form.get("alert_email", "").strip()
        if alert_email and not is_valid_email(alert_email):
            message = "Please enter a valid email address."
        else:
            session["alert_email"] = alert_email
            message = t("saved", lang)
    
    current_email = session.get("alert_email", "")
    message_html = f'<div style="background:#c8e6c9;border:1px solid #81c784;padding:14px 20px;margin:0 auto 30px;color:#2e7d32;border-radius:8px;text-align:center;max-width:500px;font-size:13px;font-weight:500;">{message}</div>' if message else ''
    
    return f"""<!DOCTYPE html>
<html>
<head><title>Occupado — {t("settings_title", lang)}</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:wght@400;500&family=DM+Mono&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#ffffff; color:#0a1a0a; font-family:'DM Sans',sans-serif; }}
.topbar {{ background:#008000; padding:16px 40px; display:flex; align-items:center; justify-content:space-between; }}
.topbar-logo {{ font-family:'Syne',sans-serif; font-size:22px; font-weight:800; color:#ffffff; }}
.topbar-hotel {{ font-family:'DM Mono',monospace; font-size:12px; color:rgba(255,255,255,0.8); }}
.topbar-right {{ display:flex; align-items:center; gap:10px; }}
.btn-nav {{ padding:8px 18px; background:rgba(255,255,255,0.15); border:1px solid rgba(255,255,255,0.3); border-radius:8px; color:#ffffff; font-size:13px; font-weight:600; text-decoration:none; }}
.btn-nav:hover {{ background:rgba(255,255,255,0.25); }}
.content {{ padding:60px 40px; display:flex; align-items:center; justify-content:center; min-height:calc(100vh - 80px); }}
.wrapper {{ width:100%; max-width:500px; text-align:center; }}
.page-title {{ font-family:'Syne',sans-serif; font-size:36px; font-weight:800; margin-bottom:8px; }}
.page-sub {{ font-family:'DM Mono',monospace; font-size:12px; color:#4a6648; margin-bottom:40px; }}
.card {{ background:#f5faf5; border:1px solid rgba(0,128,0,0.15); border-radius:16px; padding:40px; }}
.card-title {{ font-family:'Syne',sans-serif; font-size:18px; font-weight:700; margin-bottom:12px; }}
.card-sub {{ font-size:13px; color:#4a6648; margin-bottom:24px; }}
label {{ font-size:12px; color:#4a6648; display:block; margin-bottom:8px; font-family:'DM Mono',monospace; font-weight:600; text-align:left; }}
input {{ width:100%; padding:12px 16px; background:#ffffff; border:1px solid rgba(0,128,0,0.2); border-radius:10px; font-size:14px; margin-bottom:20px; font-family:'DM Sans',sans-serif; }}
input:focus {{ border-color:#008000; outline:none; }}
button {{ padding:12px 32px; background:#008000; color:white; border:none; border-radius:10px; font-weight:600; cursor:pointer; font-size:14px; font-family:'DM Sans',sans-serif; }}
button:hover {{ background:#006600; }}
</style>
</head>
<body>
<div class="topbar">
    <div>
        <div class="topbar-logo">{t("occupado", lang)}</div>
        <div class="topbar-hotel">{hotel_name} · {t("settings_title", lang)}</div>
    </div>
    <div class="topbar-right">
        <a href="/dashboard" class="btn-nav">{t("back", lang)}</a>
        <a href="/logout" class="btn-nav">{t("sign_out", lang)}</a>
    </div>
</div>
<div class="content">
    <div class="wrapper">
        <div class="page-title">{t("settings_title", lang)}</div>
        <div class="page-sub">{t("config_alert", lang)}</div>
        {message_html}
        <div class="card">
            <div class="card-title">{t("alert_email", lang)}</div>
            <div class="card-sub">{t("alert_desc", lang)}</div>
            <form method="POST">
                <label>{t("email_addr", lang)}</label>
                <input type="email" name="alert_email" value="{current_email}" placeholder="your-email@example.com" required>
                <button type="submit">{t("save", lang)}</button>
            </form>
        </div>
    </div>
</div>
</body>
</html>"""

@app.route("/upload", methods=["POST"])
@login_required
def upload():
    if "csv_file" not in request.files:
        return redirect(url_for("dashboard"))
    file = request.files["csv_file"]
    if file.filename == "":
        return redirect(url_for("dashboard"))
    try:
        content = file.read().decode("utf-8")
        df_uploaded = pd.read_csv(io.StringIO(content))
        # Store raw CSV columns and data in session for field mapping
        session["raw_csv_columns"] = list(df_uploaded.columns)
        session["raw_csv_data"] = df_uploaded.head(500).fillna(0).to_dict(orient="records")
        return redirect(url_for("map_fields"))
    except Exception as e:
        print(f"[ERROR] {e}")
        return redirect(url_for("dashboard"))


@app.route("/map-fields", methods=["GET", "POST"])
@login_required
def map_fields():
    hotel_name = session.get("hotel_name", "Hotel")
    hotel_username = session.get("hotel")
    lang = request.args.get("lang", session.get("language", "en"))
    raw_columns = session.get("raw_csv_columns", [])
    raw_data = session.get("raw_csv_data", [])

    if not raw_columns:
        return redirect(url_for("dashboard"))

    FEATURE_LABELS = {
        "lead_time":                      "Lead Time (days before arrival)",
        "arrival_date_week_number":       "Arrival Week Number",
        "stays_in_weekend_nights":        "Weekend Nights",
        "stays_in_week_nights":           "Week Nights",
        "adults":                         "Number of Adults",
        "is_repeated_guest":              "Repeated Guest (0/1)",
        "previous_cancellations":         "Previous Cancellations",
        "previous_bookings_not_canceled": "Previous Bookings (not cancelled)",
        "booking_changes":                "Booking Changes",
        "days_in_waiting_list":           "Days in Waiting List",
        "adr":                            "Average Daily Rate (room price)",
        "total_of_special_requests":      "Total Special Requests",
    }

    # Auto-match: find best column for each feature
    def auto_match(feat, cols):
        feat_lower = feat.lower().replace("_", "")
        for col in cols:
            col_lower = col.lower().replace("_", "").replace(" ", "")
            if feat_lower == col_lower:
                return col
        # Partial match
        for col in cols:
            col_lower = col.lower().replace("_", "").replace(" ", "")
            if feat_lower in col_lower or col_lower in feat_lower:
                return col
        return ""

    if request.method == "POST":
        mapping = {}
        for feat in features:
            mapped_col = request.form.get(f"map_{feat}", "").strip()
            mapping[feat] = mapped_col

        # Build final dataframe using mapping
        df_raw = pd.DataFrame(raw_data)
        df_final = pd.DataFrame()
        for feat in features:
            col = mapping.get(feat, "")
            if col and col in df_raw.columns:
                df_final[feat] = pd.to_numeric(df_raw[col], errors="coerce").fillna(0)
            else:
                df_final[feat] = 0

        csv_data = df_final.to_dict(orient="records")
        session["uploaded_csv"] = csv_data

        # Send alert if configured
        sample = df_final.head(20)
        scores = model.predict_proba(sample)[:, 1] * 100
        alert_email = session.get("alert_email", "")
        high_risk_bookings = [{"id": f"Booking {i+1}", "score": s} for i, s in enumerate(scores) if s >= 70]
        if high_risk_bookings and alert_email:
            send_consolidated_alert(hotel_name, alert_email, high_risk_bookings, hotel_username, csv_data)

        return redirect(url_for("dashboard"))

    # Build auto-matched defaults
    auto_map = {feat: auto_match(feat, raw_columns) for feat in features}

    # Preview: first 3 rows, only mapped or all columns
    preview_rows = raw_data[:3]
    preview_cols = raw_columns[:8]  # show first 8 cols in preview

    # Build options HTML helper
    def col_options(selected):
        opts = '<option value="">(skip / use 0)</option>'
        for col in raw_columns:
            sel = 'selected' if col == selected else ''
            opts += f'<option value="{col}" {sel}>{col}</option>'
        return opts

    # Count auto-matched
    matched = sum(1 for v in auto_map.values() if v)

    rows_html = ""
    for feat in features:
        label = FEATURE_LABELS[feat]
        matched_col = auto_map[feat]
        badge = f'<span style="background:#e8f5e9;color:#2e7d32;border-radius:6px;padding:2px 8px;font-size:11px;font-family:DM Mono,monospace;">✓ auto-matched</span>' if matched_col else f'<span style="background:#fff3e0;color:#e65100;border-radius:6px;padding:2px 8px;font-size:11px;font-family:DM Mono,monospace;">needs mapping</span>'
        rows_html += f"""
        <div style="display:grid;grid-template-columns:1fr 1fr auto;gap:12px;align-items:center;padding:14px 0;border-bottom:1px solid rgba(0,128,0,0.08);">
            <div>
                <div style="font-size:13px;font-weight:600;color:#0a1a0a;font-family:'DM Mono',monospace;">{feat}</div>
                <div style="font-size:12px;color:#4a6648;margin-top:2px;">{label}</div>
            </div>
            <select name="map_{feat}" style="padding:10px 12px;border:1px solid rgba(0,128,0,0.2);border-radius:8px;font-size:13px;font-family:'DM Sans',sans-serif;background:#f5faf5;color:#0a1a0a;width:100%;outline:none;">
                {col_options(matched_col)}
            </select>
            <div>{badge}</div>
        </div>"""

    # Preview table
    preview_header = "".join(f'<th style="padding:8px 12px;font-size:11px;font-family:DM Mono,monospace;color:#4a6648;text-align:left;border-bottom:1px solid rgba(0,128,0,0.1);">{c}</th>' for c in preview_cols)
    preview_body = ""
    for row in preview_rows:
        cells = "".join(f'<td style="padding:8px 12px;font-size:12px;color:#0a1a0a;border-bottom:1px solid rgba(0,128,0,0.06);">{str(row.get(c,""))[:20]}</td>' for c in preview_cols)
        preview_body += f"<tr>{cells}</tr>"

    return f"""<!DOCTYPE html>
<html>
<head><title>Occupado — Map Your Data</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:wght@400;500&family=DM+Mono&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#f5faf5; font-family:'DM Sans',sans-serif; color:#0a1a0a; }}
.topbar {{ background:#008000; padding:16px 40px; display:flex; align-items:center; justify-content:space-between; }}
.topbar-logo {{ font-family:'Syne',sans-serif; font-size:22px; font-weight:800; color:#ffffff; }}
.topbar-hotel {{ font-family:'DM Mono',monospace; font-size:12px; color:rgba(255,255,255,0.8); }}
.btn-nav {{ padding:8px 18px; background:rgba(255,255,255,0.15); border:1px solid rgba(255,255,255,0.3); border-radius:8px; color:#ffffff; font-size:13px; font-weight:600; text-decoration:none; }}
.btn-nav:hover {{ background:rgba(255,255,255,0.25); }}
.content {{ max-width:860px; margin:0 auto; padding:48px 24px; }}
.page-title {{ font-family:'Syne',sans-serif; font-size:32px; font-weight:800; margin-bottom:6px; }}
.page-sub {{ font-size:13px; color:#4a6648; font-family:'DM Mono',monospace; margin-bottom:32px; }}
.card {{ background:#ffffff; border:1px solid rgba(0,128,0,0.15); border-radius:16px; padding:32px; margin-bottom:24px; }}
.card-title {{ font-family:'Syne',sans-serif; font-size:18px; font-weight:700; margin-bottom:6px; }}
.card-sub {{ font-size:13px; color:#4a6648; margin-bottom:24px; }}
.submit-btn {{ width:100%; padding:16px; background:#008000; color:white; border:none; border-radius:12px; font-weight:700; font-size:16px; cursor:pointer; font-family:'DM Sans',sans-serif; margin-top:8px; }}
.submit-btn:hover {{ background:#006600; }}
select:focus {{ border-color:#008000; background:white; }}
</style>
</head>
<body>
<div class="topbar">
    <div>
        <div class="topbar-logo">Occupado</div>
        <div class="topbar-hotel">{hotel_name} · Map Your Data</div>
    </div>
    <div style="display:flex;gap:10px;">
        <a href="/dashboard" class="btn-nav">← Back</a>
        <a href="/logout" class="btn-nav">Sign Out</a>
    </div>
</div>
<div class="content">
    <div class="page-title">Map Your Columns</div>
    <div class="page-sub">Tell Occupado which columns in your CSV match each feature · {matched}/12 auto-matched</div>

    <div class="card">
        <div class="card-title">📂 Your CSV has {len(raw_columns)} columns, {len(raw_data)} rows</div>
        <div class="card-sub">Match your column names to Occupado's required features. Auto-matched columns are pre-filled — review and adjust if needed.</div>
        <form method="POST">
            {rows_html}
            <button type="submit" class="submit-btn">Run Predictions →</button>
        </form>
    </div>

    <div class="card">
        <div class="card-title">👀 Data Preview (first 3 rows)</div>
        <div class="card-sub">Showing first 8 columns of your file</div>
        <div style="overflow-x:auto;">
            <table style="width:100%;border-collapse:collapse;">
                <thead><tr>{preview_header}</tr></thead>
                <tbody>{preview_body}</tbody>
            </table>
        </div>
    </div>
</div>
</body>
</html>"""

@app.route("/send-guest-email", methods=["POST"])
@login_required
def send_guest_email():
    ip = request.remote_addr
    blocked, remaining = check_rate_limit(ip)
    if blocked:
        return {"status": "error", "message": f"Too many attempts. Try again in {remaining} minutes."}, 429
    data = request.get_json()
    guest_email = sanitise(data.get("guest_email", "")).strip()
    guest_name  = sanitise(data.get("guest_name", "Guest"))
    subject     = sanitise(data.get("subject", ""), max_length=200)
    body        = data.get("body", "").strip()

    if not is_valid_email(guest_email):
        return {"status": "error", "message": "Invalid email address"}, 400
    if not subject or not body:
        return {"status": "error", "message": "Subject and message are required"}, 400

    hotel_name = session.get("hotel_name", "Hotel")
    success = send_email_to_guest(guest_email, guest_name, hotel_name, subject, body)

    if success:
        return {"status": "success", "message": f"Email sent to {guest_email}"}
    else:
        return {"status": "error", "message": "Failed to send email"}, 500

@app.route("/send-bulk-email", methods=["POST"])
@login_required
def send_bulk_email():
    data    = request.get_json()
    count   = data.get("count", 0)
    subject = sanitise(data.get("subject", ""), max_length=200)
    body    = data.get("body", "").strip()

    if not subject or not body:
        return {"status": "error", "message": "Subject and message are required"}, 400
    if count == 0:
        return {"status": "error", "message": "No bookings selected"}, 400
    if len(body) > 5000:
        return {"status": "error", "message": "Message is too long (max 5000 characters)"}, 400

    return {"status": "success", "count": count}


# ─────────────────────────────────────────────
#  SHIJI TRANSFORMER
# ─────────────────────────────────────────────

def parse_shiji_date(val):
    if pd.isnull(val) or str(val).strip() == "":
        return None
    for fmt in ["%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d %b %Y", "%b %d %Y"]:
        try:
            return pd.to_datetime(str(val).strip(), format=fmt)
        except:
            continue
    try:
        return pd.to_datetime(str(val).strip(), infer_datetime_format=True)
    except:
        return None


def transform_shiji(df_res, df_cxl=None, df_ns=None):
    df = df_res.copy()

    def find_col(dataframe, keywords):
        for kw in keywords:
            for col in dataframe.columns:
                if kw.lower() in col.lower():
                    return col
        return None

    arr_col     = find_col(df, ["arr. date", "arrival date", "arr date", "checkin", "check-in"])
    created_col = find_col(df, ["created on", "created", "booking date", "booked on"])
    if arr_col and created_col:
        arr_dates     = df[arr_col].apply(parse_shiji_date)
        created_dates = df[created_col].apply(parse_shiji_date)
        df["lead_time"] = (arr_dates - created_dates).dt.days.clip(lower=0).fillna(0)
    else:
        df["lead_time"] = 0

    if arr_col:
        df["arrival_date_week_number"] = df[arr_col].apply(
            lambda x: parse_shiji_date(x).isocalendar()[1] if parse_shiji_date(x) else 0
        )
    else:
        df["arrival_date_week_number"] = 0

    nights_col = find_col(df, ["# nights", "nights", "num nights", "length of stay", "los"])
    dep_col    = find_col(df, ["dep. date", "departure date", "checkout", "check-out"])
    if nights_col:
        total = pd.to_numeric(df[nights_col], errors="coerce").fillna(0).clip(lower=0)
        df["stays_in_week_nights"]    = total
        df["stays_in_weekend_nights"] = (total * 0.28).round().astype(int)
    elif arr_col and dep_col:
        arr_d = df[arr_col].apply(parse_shiji_date)
        dep_d = df[dep_col].apply(parse_shiji_date)
        total = (dep_d - arr_d).dt.days.clip(lower=0).fillna(0)
        df["stays_in_week_nights"]    = total
        df["stays_in_weekend_nights"] = (total * 0.28).round().astype(int)
    else:
        df["stays_in_week_nights"]    = 0
        df["stays_in_weekend_nights"] = 0

    adults_col = find_col(df, ["ad/ch", "adults", "adult", "pax", "guests", "no. of guests"])
    if adults_col:
        def parse_adults(v):
            try:
                return int(str(v).split("/")[0].strip())
            except:
                return 1
        df["adults"] = df[adults_col].apply(parse_adults)
    else:
        df["adults"] = 2

    memb_col = find_col(df, ["memb. level", "membership", "loyalty", "vip", "member"])
    if memb_col:
        df["is_repeated_guest"] = df[memb_col].apply(
            lambda x: 0 if (pd.isnull(x) or str(x).strip() in ["", "None", "0", "No"]) else 1
        )
    else:
        df["is_repeated_guest"] = 0

    if df_cxl is not None and not df_cxl.empty:
        guest_col_res = find_col(df,     ["guest name", "guest", "name"])
        guest_col_cxl = find_col(df_cxl, ["guest name", "guest", "name"])
        if guest_col_res and guest_col_cxl:
            cxl_counts = df_cxl[guest_col_cxl].value_counts().to_dict()
            df["previous_cancellations"] = df[guest_col_res].map(cxl_counts).fillna(0).astype(int)
        else:
            df["previous_cancellations"] = 0
    else:
        cxl_no_col = find_col(df, ["cxl no", "cxl number", "cancellation no"])
        df["previous_cancellations"] = pd.to_numeric(df[cxl_no_col], errors="coerce").fillna(0).clip(lower=0) if cxl_no_col else 0

    df["previous_bookings_not_canceled"] = 0

    changes_col = find_col(df, ["booking changes", "modifications", "amended", "changes"])
    df["booking_changes"] = pd.to_numeric(df[changes_col], errors="coerce").fillna(0).clip(lower=0) if changes_col else 0

    wait_col = find_col(df, ["waiting list", "waitlist", "days waiting"])
    df["days_in_waiting_list"] = pd.to_numeric(df[wait_col], errors="coerce").fillna(0).clip(lower=0) if wait_col else 0

    rate_col = find_col(df, ["rate amount", "room rate total", "room rate", "nightly rate", "price", "adr"])
    if rate_col:
        df["adr"] = pd.to_numeric(
            df[rate_col].astype(str).str.replace("[€$£,]", "", regex=True),
            errors="coerce"
        ).fillna(0).clip(lower=0)
    else:
        df["adr"] = 0

    req_col = find_col(df, ["special request", "requests", "extras"])
    df["total_of_special_requests"] = pd.to_numeric(df[req_col], errors="coerce").fillna(0).clip(lower=0) if req_col else 0

    feat_cols = [
        "lead_time", "arrival_date_week_number", "stays_in_weekend_nights",
        "stays_in_week_nights", "adults", "is_repeated_guest",
        "previous_cancellations", "previous_bookings_not_canceled",
        "booking_changes", "days_in_waiting_list", "adr", "total_of_special_requests"
    ]
    return df[feat_cols].fillna(0)


@app.route("/shiji-upload", methods=["GET", "POST"])
@login_required
def shiji_upload():
    hotel_name     = session.get("hotel_name", "Hotel")
    hotel_username = session.get("hotel")
    error          = ""

    if request.method == "POST":
        try:
            if "res_file" not in request.files or request.files["res_file"].filename == "":
                error = "Please upload at least the Reservations file."
            else:
                def read_upload(key):
                    f = request.files.get(key)
                    if f and f.filename:
                        content = f.read().decode("utf-8", errors="replace")
                        return pd.read_csv(io.StringIO(content))
                    return None

                df_res = read_upload("res_file")
                df_cxl = read_upload("cxl_file")
                df_ns  = read_upload("ns_file")

                df_transformed = transform_shiji(df_res, df_cxl, df_ns)
                csv_data = df_transformed.to_dict(orient="records")
                session["uploaded_csv"] = csv_data

                sample = df_transformed.head(20)
                scores = model.predict_proba(sample)[:, 1] * 100
                alert_email = session.get("alert_email", "")
                high_risk   = [{"id": f"Booking {i+1}", "score": s} for i, s in enumerate(scores) if s >= 70]
                if high_risk and alert_email:
                    send_consolidated_alert(hotel_name, alert_email, high_risk, hotel_username, csv_data)

                return redirect(url_for("dashboard"))

        except Exception as e:
            print(f"[SHIJI ERROR] {e}")
            error = f"Error processing files: {str(e)}"

    error_html = f'''<div style="background:#ffcdd2;padding:12px 16px;border-radius:8px;color:#c62828;font-size:14px;margin-bottom:24px;">{error}</div>''' if error else ""

    return f"""<!DOCTYPE html>
<html>
<head><title>Occupado — Shiji Import</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:wght@400;500&family=DM+Mono&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#f5faf5; font-family:'DM Sans',sans-serif; color:#0a1a0a; }}
.topbar {{ background:#008000; padding:16px 40px; display:flex; align-items:center; justify-content:space-between; }}
.topbar-logo {{ font-family:'Syne',sans-serif; font-size:22px; font-weight:800; color:#ffffff; }}
.topbar-hotel {{ font-family:'DM Mono',monospace; font-size:12px; color:rgba(255,255,255,0.8); }}
.btn-nav {{ padding:8px 18px; background:rgba(255,255,255,0.15); border:1px solid rgba(255,255,255,0.3); border-radius:8px; color:#ffffff; font-size:13px; font-weight:600; text-decoration:none; }}
.btn-nav:hover {{ background:rgba(255,255,255,0.25); }}
.content {{ max-width:700px; margin:0 auto; padding:48px 24px; }}
.page-title {{ font-family:'Syne',sans-serif; font-size:32px; font-weight:800; margin-bottom:6px; }}
.page-sub {{ font-size:13px; color:#4a6648; font-family:'DM Mono',monospace; margin-bottom:32px; }}
.card {{ background:#ffffff; border:1px solid rgba(0,128,0,0.15); border-radius:16px; padding:32px; margin-bottom:20px; }}
.card-title {{ font-family:'Syne',sans-serif; font-size:18px; font-weight:700; margin-bottom:12px; }}
.card-sub {{ font-size:13px; color:#4a6648; margin-bottom:24px; line-height:1.6; }}
.file-row {{ margin-bottom:20px; }}
.file-label {{ font-size:12px; font-family:'DM Mono',monospace; color:#4a6648; font-weight:600; text-transform:uppercase; letter-spacing:0.5px; display:block; margin-bottom:8px; }}
.req-badge {{ background:rgba(0,128,0,0.1);color:#008000;border-radius:4px;padding:2px 6px;font-size:10px;margin-left:6px; }}
.opt-badge {{ background:rgba(0,0,0,0.06);color:#4a6648;border-radius:4px;padding:2px 6px;font-size:10px;margin-left:6px; }}
input[type=file] {{ width:100%; padding:12px; background:#f5faf5; border:1px solid rgba(0,128,0,0.2); border-radius:10px; font-size:13px; font-family:'DM Sans',sans-serif; cursor:pointer; }}
input[type=file]:hover {{ border-color:#008000; }}
.submit-btn {{ width:100%; padding:16px; background:#008000; color:white; border:none; border-radius:12px; font-weight:700; font-size:16px; cursor:pointer; font-family:'DM Sans',sans-serif; }}
.submit-btn:hover {{ background:#006600; }}
.info-row {{ display:flex; gap:8px; margin-bottom:10px; font-size:13px; color:#4a6648; line-height:1.5; }}
.info-icon {{ color:#008000; }}
</style>
</head>
<body>
<div class="topbar">
    <div>
        <div class="topbar-logo">Occupado</div>
        <div class="topbar-hotel">{hotel_name} · Shiji Import</div>
    </div>
    <div style="display:flex;gap:10px;">
        <a href="/dashboard" class="btn-nav">← Back</a>
        <a href="/logout" class="btn-nav">Sign Out</a>
    </div>
</div>
<div class="content">
    <div class="page-title">Import from Shiji PMS</div>
    <div class="page-sub">Upload your Shiji exports · Occupado calculates all features automatically</div>
    {error_html}
    <div class="card">
        <div class="card-title">How it works</div>
        <div class="info-row"><span class="info-icon">✦</span><span>Occupado reads your Shiji columns and calculates all 12 AI features automatically</span></div>
        <div class="info-row"><span class="info-icon">✦</span><span><strong>Lead time</strong> calculated from Arr. Date minus Created On</span></div>
        <div class="info-row"><span class="info-icon">✦</span><span><strong>Previous cancellations</strong> counted from your CXL file per guest name</span></div>
        <div class="info-row"><span class="info-icon">✦</span><span><strong>Room rate</strong> from Rate Amount · Membership from Memb. Level</span></div>
    </div>
    <div class="card">
        <div class="card-title">Upload your Shiji files</div>
        <div class="card-sub">Export these reports from Shiji PMS and upload them here. Only Reservations is required.</div>
        <form method="POST" enctype="multipart/form-data">
            <div class="file-row">
                <label class="file-label">Reservations <span class="req-badge">REQUIRED</span></label>
                <input type="file" name="res_file" accept=".csv" required>
            </div>
            <div class="file-row">
                <label class="file-label">Cancelled Reservations <span class="opt-badge">OPTIONAL</span></label>
                <input type="file" name="cxl_file" accept=".csv">
            </div>
            <div class="file-row" style="margin-bottom:28px;">
                <label class="file-label">No-Shows <span class="opt-badge">OPTIONAL</span></label>
                <input type="file" name="ns_file" accept=".csv">
            </div>
            <button type="submit" class="submit-btn">🚀 Run Predictions →</button>
        </form>
    </div>
</div>
</body>
</html>"""


def send_verification_email(to_email, hotel_name, token):
    """Send email verification link via SendGrid"""
    base_url = os.environ.get("BASE_URL", "https://occupado.co")
    verify_url = f"{base_url}/verify/{token}"
    api_key = os.environ.get("SENDGRID_API_KEY")
    from_email = os.environ.get("ALERT_FROM_EMAIL", "team@occupado.co")
    if not api_key:
        return False
    try:
        html = f"""
        <div style="font-family:'DM Sans',sans-serif;max-width:480px;margin:0 auto;">
          <div style="background:#008000;padding:24px 32px;border-radius:12px 12px 0 0;">
            <span style="font-family:'Syne',sans-serif;font-size:24px;font-weight:800;color:#fff;">Occupado</span>
          </div>
          <div style="background:#ffffff;padding:32px;border:1px solid rgba(0,128,0,0.15);border-radius:0 0 12px 12px;">
            <h2 style="font-family:'Syne',sans-serif;color:#0a1a0a;margin-bottom:12px;">Verify your email</h2>
            <p style="color:#4a6648;margin-bottom:24px;line-height:1.6;">Hi <strong>{hotel_name}</strong>, thanks for registering with Occupado. Click the button below to activate your account.</p>
            <a href="{verify_url}" style="display:inline-block;background:#008000;color:#fff;padding:14px 28px;border-radius:10px;font-weight:700;text-decoration:none;font-size:15px;">Verify Email →</a>
            <p style="color:#4a6648;font-size:12px;margin-top:24px;">Or copy this link: {verify_url}</p>
          </div>
        </div>"""
        message = Mail(from_email=from_email, to_emails=to_email,
                       subject="Verify your Occupado account", html_content=html)
        sg = SendGridAPIClient(api_key)
        sg.send(message)
        return True
    except Exception as e:
        print(f"Verification email error: {e}")
        return False


def send_reset_email(to_email, hotel_name, token):
    """Send password reset link via SendGrid"""
    base_url  = os.environ.get("BASE_URL", "https://occupado.co")
    reset_url = f"{base_url}/reset-password/{token}"
    api_key   = os.environ.get("SENDGRID_API_KEY")
    from_email = os.environ.get("ALERT_FROM_EMAIL", "team@occupado.co")
    if not api_key:
        return False
    try:
        html = f"""
        <div style="font-family:'DM Sans',sans-serif;max-width:480px;margin:0 auto;">
          <div style="background:#008000;padding:24px 32px;border-radius:12px 12px 0 0;">
            <span style="font-family:'Syne',sans-serif;font-size:24px;font-weight:800;color:#fff;">Occupado</span>
          </div>
          <div style="background:#ffffff;padding:32px;border:1px solid rgba(0,128,0,0.15);border-radius:0 0 12px 12px;">
            <h2 style="font-family:'Syne',sans-serif;color:#0a1a0a;margin-bottom:12px;">Reset your password</h2>
            <p style="color:#4a6648;margin-bottom:24px;line-height:1.6;">Hi <strong>{hotel_name}</strong>, click the button below to reset your password. This link expires in <strong>1 hour</strong>.</p>
            <a href="{reset_url}" style="display:inline-block;background:#008000;color:#fff;padding:14px 28px;border-radius:10px;font-weight:700;text-decoration:none;font-size:15px;">Reset Password →</a>
            <p style="color:#4a6648;font-size:12px;margin-top:24px;">If you didn't request this, ignore this email. Your password won't change.</p>
            <p style="color:#4a6648;font-size:12px;margin-top:8px;">Or copy this link: {reset_url}</p>
          </div>
        </div>"""
        message = Mail(from_email=from_email, to_emails=to_email,
                       subject="Reset your Occupado password", html_content=html)
        sg = SendGridAPIClient(api_key)
        sg.send(message)
        return True
    except Exception as e:
        print(f"Reset email error: {e}")
        return False


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    ip = request.remote_addr
    message = ""
    if request.method == "POST":
        blocked, remaining = check_rate_limit(ip)
        if blocked:
            message = f"Too many attempts. Try again in {remaining} minutes."
        else:
            email = sanitise(request.form.get("email", ""), max_length=150).lower().strip()
            if not is_valid_email(email):
                message = "Please enter a valid email address."
            else:
                # Always show success message (don't reveal if email exists)
                conn = get_db()
                cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute("SELECT username, name FROM registered_users WHERE email=%s AND verified=1", (email,))
                user = cur.fetchone()
                if user:
                    token = secrets.token_urlsafe(32)
                    cur.execute("INSERT INTO password_reset_tokens (token, username, expires_at) VALUES (%s,%s, NOW() + INTERVAL '1 hour')", (token, user["username"]))
                    conn.commit()
                    send_reset_email(email, user["name"], token)
                cur.close()
                conn.close()
                message = "success"

    if message == "success":
        success_html = '<div style="background:#e8f5e9;padding:12px;margin-bottom:20px;color:#2e7d32;border-radius:8px;font-size:14px;">If that email is registered, a reset link has been sent. Check your inbox.</div>'
        error_html   = ""
    else:
        error_html   = f'<div style="background:#ffcdd2;padding:12px;margin-bottom:20px;color:#c62828;border-radius:8px;font-size:14px;">{message}</div>' if message else ""
        success_html = ""

    return f"""<!DOCTYPE html>
<html>
<head><title>Occupado — Forgot Password</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:wght@400;500&family=DM+Mono&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#f5faf5; font-family:'DM Sans',sans-serif; min-height:100vh; display:flex; align-items:center; justify-content:center; }}
.box {{ background:#ffffff; padding:48px; border-radius:20px; width:100%; max-width:400px; border:1px solid rgba(0,128,0,0.15); }}
.logo {{ font-family:'Syne',sans-serif; font-size:28px; font-weight:800; color:#008000; margin-bottom:8px; }}
.subtitle {{ font-size:13px; color:#4a6648; margin-bottom:28px; font-family:'DM Mono',monospace; }}
label {{ font-size:12px; color:#4a6648; display:block; margin-bottom:6px; font-family:'DM Mono',monospace; font-weight:600; }}
input {{ width:100%; padding:12px; background:#f5faf5; border:1px solid rgba(0,128,0,0.2); border-radius:10px; font-size:14px; margin-bottom:16px; outline:none; }}
input:focus {{ border-color:#008000; background:white; }}
button {{ width:100%; padding:14px; background:#008000; color:white; border:none; border-radius:10px; font-weight:700; cursor:pointer; font-size:15px; font-family:'DM Sans',sans-serif; }}
button:hover {{ background:#006600; }}
.switch-link {{ text-align:center; margin-top:20px; font-size:13px; color:#4a6648; }}
.switch-link a {{ color:#008000; font-weight:700; text-decoration:none; }}
</style>
</head>
<body>
<div class="box">
    <div class="logo">Occupado</div>
    <div class="subtitle">Password Reset</div>
    {error_html}{success_html}
    <form method="POST">
        <label>Email address</label>
        <input type="email" name="email" required placeholder="your@email.com">
        <button type="submit">Send Reset Link →</button>
    </form>
    <div class="switch-link"><a href="/login">← Back to login</a></div>
</div>
</body>
</html>"""


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    from datetime import timezone
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT username, expires_at FROM password_reset_tokens WHERE token=%s", (token,))
    row = cur.fetchone()

    def invalid_page(msg):
        cur.close()
        conn.close()
        return f"""<!DOCTYPE html>
<html>
<head><title>Occupado — Reset Failed</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:wght@400;500&display=swap" rel="stylesheet">
<style>* {{margin:0;padding:0;box-sizing:border-box;}} body {{background:#f5faf5;font-family:'DM Sans',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;}} .box {{background:#fff;padding:48px;border-radius:20px;max-width:400px;text-align:center;border:1px solid rgba(0,128,0,0.15);}}</style>
</head>
<body><div class="box">
<div style="font-family:'Syne',sans-serif;font-size:28px;font-weight:800;color:#008000;margin-bottom:16px;">Occupado</div>
<div style="font-size:36px;margin-bottom:16px;">❌</div>
<h2 style="margin-bottom:12px;color:#0a1a0a;">{msg}</h2>
<a href="/forgot-password" style="color:#008000;font-weight:700;text-decoration:none;">Request a new link →</a>
</div></body></html>"""

    if not row:
        return invalid_page("Invalid or expired link")

    expires_at = row["expires_at"]
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires_at:
        cur.execute("DELETE FROM password_reset_tokens WHERE token=%s", (token,))
        conn.commit()
        return invalid_page("Reset link has expired")

    username = row["username"]
    error = ""

    if request.method == "POST":
        password = request.form.get("password", "").strip()
        confirm  = request.form.get("confirm", "").strip()
        if not password or not confirm:
            error = "Both fields are required."
        elif len(password) < 8:
            error = "Password must be at least 8 characters."
        elif password != confirm:
            error = "Passwords do not match."
        else:
            hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
            cur.execute("UPDATE registered_users SET password=%s WHERE username=%s", (hashed, username))
            cur.execute("DELETE FROM password_reset_tokens WHERE token=%s", (token,))
            conn.commit()
            cur.close()
            conn.close()
            session["verified_success"] = "Password reset successfully. Please sign in."
            return redirect(url_for("login"))

    cur.close()
    conn.close()
    error_html = f'<div style="background:#ffcdd2;padding:12px;margin-bottom:20px;color:#c62828;border-radius:8px;font-size:14px;">{error}</div>' if error else ""

    return f"""<!DOCTYPE html>
<html>
<head><title>Occupado — Reset Password</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:wght@400;500&family=DM+Mono&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#f5faf5; font-family:'DM Sans',sans-serif; min-height:100vh; display:flex; align-items:center; justify-content:center; }}
.box {{ background:#ffffff; padding:48px; border-radius:20px; width:100%; max-width:400px; border:1px solid rgba(0,128,0,0.15); }}
.logo {{ font-family:'Syne',sans-serif; font-size:28px; font-weight:800; color:#008000; margin-bottom:8px; }}
.subtitle {{ font-size:13px; color:#4a6648; margin-bottom:28px; font-family:'DM Mono',monospace; }}
label {{ font-size:12px; color:#4a6648; display:block; margin-bottom:6px; font-family:'DM Mono',monospace; font-weight:600; }}
input {{ width:100%; padding:12px; background:#f5faf5; border:1px solid rgba(0,128,0,0.2); border-radius:10px; font-size:14px; margin-bottom:16px; outline:none; }}
input:focus {{ border-color:#008000; background:white; }}
button {{ width:100%; padding:14px; background:#008000; color:white; border:none; border-radius:10px; font-weight:700; cursor:pointer; font-size:15px; font-family:'DM Sans',sans-serif; }}
button:hover {{ background:#006600; }}
.switch-link {{ text-align:center; margin-top:20px; font-size:13px; color:#4a6648; }}
.switch-link a {{ color:#008000; font-weight:700; text-decoration:none; }}
</style>
</head>
<body>
<div class="box">
    <div class="logo">Occupado</div>
    <div class="subtitle">Set New Password</div>
    {error_html}
    <form method="POST">
        <label>New Password</label>
        <input type="password" name="password" required minlength="8" placeholder="Min. 8 characters">
        <label>Confirm Password</label>
        <input type="password" name="confirm" required placeholder="Repeat password">
        <button type="submit">Reset Password →</button>
    </form>
    <div class="switch-link"><a href="/login">← Back to login</a></div>
</div>
</body>
</html>"""


@app.route("/register", methods=["GET", "POST"])
def register():
    error = ""
    success = ""
    ip = request.remote_addr
    if request.method == "POST":
        blocked, remaining = check_rate_limit(ip)
        if blocked:
            error = f"Too many attempts. Try again in {remaining} minutes."
        else:
            hotel_name = sanitise(request.form.get("hotel_name", ""), max_length=100)
            email      = sanitise(request.form.get("email", ""), max_length=150).lower()
            username   = sanitise(request.form.get("username", ""), max_length=50).lower()
            password   = request.form.get("password", "").strip()
            confirm    = request.form.get("confirm", "").strip()

        RESERVED_USERNAMES = set(HOTELS.keys()) | {"jpdourado", "admin", "occupado"}

        if not all([hotel_name, email, username, password, confirm]):
            error = "All fields are required."
        elif not is_valid_email(email):
            error = "Please enter a valid email address."
        elif not re.match(r"^[a-z0-9_]{3,50}$", username):
            error = "Username must be 3–50 characters, letters, numbers and underscores only."
        elif password != confirm:
            error = "Passwords do not match."
        elif len(password) < 8:
            error = "Password must be at least 8 characters."
        elif username in RESERVED_USERNAMES:
            error = "That username is already taken. Please choose another."
        else:
            conn = get_db()
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT username FROM registered_users WHERE username=%s", (username,))
            existing = cur.fetchone()
            if existing:
                error = "That username is already taken. Please choose another."
                cur.close()
                conn.close()
            else:
                hashed_pw = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
                token = secrets.token_urlsafe(32)
                cur.execute("INSERT INTO registered_users (username, password, name, email, verified, signed_up) VALUES (%s,%s,%s,%s,0,%s)",
                             (username, hashed_pw, hotel_name, email, datetime.now().strftime("%d %b %Y")))
                cur.execute("INSERT INTO verification_tokens (token, username, expires_at) VALUES (%s,%s, NOW() + INTERVAL '24 hours')", (token, username))
                conn.commit()
                cur.close()
                conn.close()
                sent = send_verification_email(email, hotel_name, token)
                if sent:
                    success = f"Account created! A verification email has been sent to {email}. Please check your inbox."
                else:
                    conn2 = get_db()
                    cur2 = conn2.cursor()
                    cur2.execute("UPDATE registered_users SET verified=1 WHERE username=%s", (username,))
                    cur2.execute("DELETE FROM verification_tokens WHERE token=%s", (token,))
                    conn2.commit()
                    cur2.close()
                    conn2.close()
                    success = "Account created! (Email verification skipped — no SendGrid key detected.) You can now sign in."

    error_html   = f'<div class="err">{error}</div>' if error else ''
    success_html = f'<div class="ok">{success}</div>' if success else ''

    return f"""<!DOCTYPE html>
<html>
<head><title>Occupado — Start free pilot</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{margin:0;padding:0;box-sizing:border-box;}}
body{{background:#f5f7fb;font-family:'Inter',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px;-webkit-font-smoothing:antialiased;}}
.card{{background:#ffffff;border:1px solid #e4e8f0;border-radius:20px;width:100%;max-width:460px;padding:48px;box-shadow:0 4px 32px rgba(0,0,0,0.06);}}
.brand{{font-family:'Syne',sans-serif;font-size:22px;font-weight:800;color:#0d1120;letter-spacing:-0.5px;margin-bottom:28px;}}
.brand span{{color:#00d165;}}
.pilot-badge{{display:inline-flex;align-items:center;background:#f0fdf4;border:1px solid #bbf7d0;border-radius:99px;padding:5px 12px;font-family:'JetBrains Mono',monospace;font-size:10px;color:#16a34a;letter-spacing:1px;margin-bottom:20px;}}
.card-title{{font-family:'Syne',sans-serif;font-size:22px;font-weight:800;color:#0d1120;letter-spacing:-0.6px;margin-bottom:6px;}}
.card-sub{{font-size:13px;color:#64748b;margin-bottom:28px;}}
.err{{background:#fef2f2;border:1px solid #fecaca;color:#dc2626;padding:12px 14px;border-radius:9px;font-size:13px;margin-bottom:20px;line-height:1.5;}}
.ok{{background:#f0fdf4;border:1px solid #bbf7d0;color:#16a34a;padding:12px 14px;border-radius:9px;font-size:13px;margin-bottom:20px;line-height:1.5;}}
.ok a{{color:#00d165;font-weight:600;text-decoration:none;}}
label{{font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:500;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;display:block;margin-bottom:7px;}}
input{{width:100%;padding:12px 14px;background:#f8fafc;border:1px solid #e4e8f0;border-radius:9px;font-size:14px;color:#0d1120;margin-bottom:16px;outline:none;font-family:'Inter',sans-serif;transition:border-color .2s,background .2s;}}
input:focus{{border-color:#00d165;background:#ffffff;}}
input::placeholder{{color:#cbd5e1;}}
.btn-submit{{width:100%;padding:13px;background:#00d165;color:#080c14;border:none;border-radius:9px;font-weight:700;cursor:pointer;font-size:14px;font-family:'Inter',sans-serif;transition:all .2s;margin-top:4px;}}
.btn-submit:hover{{background:#04e270;box-shadow:0 4px 16px rgba(0,209,101,0.25);}}
.divider{{height:1px;background:#e4e8f0;margin:20px 0;}}
.back-link{{text-align:center;font-size:13px;}}
.back-link a{{color:#94a3b8;text-decoration:none;transition:color .2s;}}
.back-link a span{{color:#00d165;font-weight:600;}}
.back-link a:hover{{color:#0d1120;}}
</style>
</head>
<body>
<div class="card">
  <div class="brand">Occup<span>ado</span></div>
  <div class="pilot-badge">FREE 40-DAY PILOT · NO CREDIT CARD</div>
  <div class="card-title">Create your account</div>
  <div class="card-sub">Start predicting cancellations in minutes</div>
  {error_html}{success_html}
  {'<div class="divider"></div><div class="back-link"><a href="/login"><span>Back to Sign in</span></a></div>' if success else f"""
  <form method="POST">
    <label>Hotel Name</label>
    <input type="text" name="hotel_name" placeholder="e.g. Van der Valk Mechelen" required>
    <label>Email Address</label>
    <input type="email" name="email" placeholder="revenue@yourhotel.com" required>
    <label>Username</label>
    <input type="text" name="username" placeholder="Choose a username" required>
    <label>Password</label>
    <input type="password" name="password" placeholder="Min. 8 characters" required>
    <label>Confirm Password</label>
    <input type="password" name="confirm" placeholder="Repeat password" required>
    <button type="submit" class="btn-submit">Create account &rarr;</button>
  </form>
  <div class="divider"></div>
  <div class="back-link"><a href="/login">Already have an account? <span>Sign in</span></a></div>
  """}
</div>
</body>
</html>"""


@app.route("/verify/<token>")
def verify_email(token):
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT username, expires_at FROM verification_tokens WHERE token=%s", (token,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return f"""<!DOCTYPE html>
<html>
<head><title>Occupado — Verification Failed</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:wght@400;500&display=swap" rel="stylesheet">
<style>* {{margin:0;padding:0;box-sizing:border-box;}} body {{background:#f5faf5;font-family:'DM Sans',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;}} .box {{background:#fff;padding:48px;border-radius:20px;max-width:400px;text-align:center;border:1px solid rgba(0,128,0,0.15);}}</style>
</head>
<body><div class="box">
<div style="font-family:'Syne',sans-serif;font-size:28px;font-weight:800;color:#008000;margin-bottom:16px;">Occupado</div>
<div style="font-size:36px;margin-bottom:16px;">❌</div>
<h2 style="margin-bottom:12px;color:#0a1a0a;">Invalid or expired link</h2>
<p style="color:#4a6648;margin-bottom:24px;">This verification link is not valid. Please register again.</p>
<a href="/register" style="color:#008000;font-weight:700;text-decoration:none;">Register →</a>
</div></body></html>"""

    # Check token expiry
    from datetime import timezone
    expires_at = row["expires_at"]
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires_at:
        cur.execute("DELETE FROM verification_tokens WHERE token=%s", (token,))
        conn.commit()
        cur.close()
        conn.close()
        return f"""<!DOCTYPE html>
<html>
<head><title>Occupado — Link Expired</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:wght@400;500&display=swap" rel="stylesheet">
<style>* {{margin:0;padding:0;box-sizing:border-box;}} body {{background:#f5faf5;font-family:'DM Sans',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;}} .box {{background:#fff;padding:48px;border-radius:20px;max-width:400px;text-align:center;border:1px solid rgba(0,128,0,0.15);}}</style>
</head>
<body><div class="box">
<div style="font-family:'Syne',sans-serif;font-size:28px;font-weight:800;color:#008000;margin-bottom:16px;">Occupado</div>
<div style="font-size:36px;margin-bottom:16px;">⏰</div>
<h2 style="margin-bottom:12px;color:#0a1a0a;">Verification link expired</h2>
<p style="color:#4a6648;margin-bottom:24px;">This link expired after 24 hours. Please register again to get a new link.</p>
<a href="/register" style="color:#008000;font-weight:700;text-decoration:none;">Register again →</a>
</div></body></html>"""

    username = row["username"]
    cur.execute("UPDATE registered_users SET verified=1 WHERE username=%s", (username,))
    cur.execute("DELETE FROM verification_tokens WHERE token=%s", (token,))
    conn.commit()
    cur.close()
    conn.close()

    session["verified_success"] = "✅ Email verified! You can now sign in."
    return redirect(url_for("login"))


# ─────────────────────────────────────────────
#  ADMIN PANEL
# ─────────────────────────────────────────────

ADMIN_PASSWORD = "occupado-admin-2024"

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = ""
    if request.method == "POST":
        ip = request.remote_addr
        blocked, remaining = check_rate_limit(ip)
        if blocked:
            error = f"Too many failed attempts. Try again in {remaining // 60 + 1} minute(s)."
        else:
            pw = request.form.get("password", "").strip()
            if pw == ADMIN_PASSWORD:
                reset_attempts(ip)
                session.permanent = True
                session["is_admin"] = True
                return redirect(url_for("admin_panel"))
            record_failed_attempt(ip)
            error = "Wrong password."

    error_html = f'<div style="background:#ffcdd2;padding:12px;border-radius:8px;color:#c62828;font-size:14px;margin-bottom:20px;">{error}</div>' if error else ""

    return f"""<!DOCTYPE html>
<html>
<head><title>Occupado — Admin</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:wght@400;500&family=DM+Mono&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#f5faf5; font-family:'DM Sans',sans-serif; min-height:100vh; display:flex; align-items:center; justify-content:center; }}
.box {{ background:#fff; padding:48px; border-radius:20px; width:100%; max-width:380px; border:1px solid rgba(0,128,0,0.15); }}
.logo {{ font-family:'Syne',sans-serif; font-size:26px; font-weight:800; color:#008000; margin-bottom:4px; }}
.subtitle {{ font-size:12px; color:#4a6648; font-family:'DM Mono',monospace; margin-bottom:28px; }}
label {{ font-size:12px; color:#4a6648; display:block; margin-bottom:6px; font-family:'DM Mono',monospace; font-weight:600; text-transform:uppercase; }}
input {{ width:100%; padding:12px; background:#f5faf5; border:1px solid rgba(0,128,0,0.2); border-radius:10px; font-size:14px; margin-bottom:16px; outline:none; }}
input:focus {{ border-color:#008000; background:#fff; }}
button {{ width:100%; padding:14px; background:#008000; color:#fff; border:none; border-radius:10px; font-weight:700; font-size:15px; cursor:pointer; font-family:'DM Sans',sans-serif; }}
button:hover {{ background:#006600; }}
</style>
</head>
<body>
<div class="box">
    <div class="logo">Occupado</div>
    <div class="subtitle">Admin Panel</div>
    {error_html}
    <form method="POST">
        <label>Admin Password</label>
        <input type="password" name="password" required autofocus>
        <button type="submit">Enter Admin →</button>
    </form>
</div>
</body>
</html>"""


@app.route("/admin")
@admin_required
def admin_panel():
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT username, name, email, verified, signed_up FROM registered_users ORDER BY username")
    users = cur.fetchall()
    cur.close()
    conn.close()

    total      = len(users)
    verified   = sum(1 for u in users if u["verified"])
    unverified = total - verified

    rows_html = ""
    for u in users:
        verified_badge = '<span style="background:#e8f5e9;color:#2e7d32;border-radius:6px;padding:3px 10px;font-size:11px;font-family:DM Mono,monospace;font-weight:600;">✓ Verified</span>' \
                       if u["verified"] else \
                       '<span style="background:#fff3e0;color:#e65100;border-radius:6px;padding:3px 10px;font-size:11px;font-family:DM Mono,monospace;font-weight:600;">Pending</span>'
        uname = u["username"]
        confirm_verify = "Manually verify " + uname + "?"
        confirm_delete = "Delete " + uname + "? This cannot be undone."
        verify_btn = "" if u["verified"] else (
            '<form method="POST" action="/admin/verify-user/' + uname + '" style="display:inline;" onsubmit="return confirm('' + confirm_verify + '')">'
            '<button type="submit" style="background:none;border:none;font-size:12px;color:#008000;font-weight:600;cursor:pointer;margin-right:12px;padding:0;">✓ Verify</button></form>'
        )
        delete_btn = (
            '<form method="POST" action="/admin/delete-user/' + uname + '" style="display:inline;" onsubmit="return confirm('' + confirm_delete + '')">'
            '<button type="submit" style="background:none;border:none;font-size:12px;color:#c62828;font-weight:600;cursor:pointer;padding:0;">✕ Delete</button></form>'
        )
        signed_up  = u["signed_up"] or "—"

        rows_html += f"""<tr>
            <td style="padding:14px 16px;font-size:14px;font-family:'DM Mono',monospace;color:#0a1a0a;border-bottom:1px solid rgba(0,128,0,0.08);">{u['username']}</td>
            <td style="padding:14px 16px;font-size:14px;color:#0a1a0a;border-bottom:1px solid rgba(0,128,0,0.08);">{u['name']}</td>
            <td style="padding:14px 16px;font-size:14px;color:#4a6648;border-bottom:1px solid rgba(0,128,0,0.08);">{u['email']}</td>
            <td style="padding:14px 16px;font-size:13px;color:#4a6648;border-bottom:1px solid rgba(0,128,0,0.08);font-family:'DM Mono',monospace;">{signed_up}</td>
            <td style="padding:14px 16px;border-bottom:1px solid rgba(0,128,0,0.08);">{verified_badge}</td>
            <td style="padding:14px 16px;border-bottom:1px solid rgba(0,128,0,0.08);">{verify_btn}{delete_btn}</td>
        </tr>"""

    if not rows_html:
        rows_html = '<tr><td colspan="6" style="padding:32px;text-align:center;color:#4a6648;font-size:14px;">No registered users yet.</td></tr>'

    return f"""<!DOCTYPE html>
<html>
<head><title>Occupado — Admin Panel</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:wght@400;500&family=DM+Mono&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#f5faf5; font-family:'DM Sans',sans-serif; color:#0a1a0a; }}
.topbar {{ background:#008000; padding:16px 40px; display:flex; align-items:center; justify-content:space-between; }}
.topbar-logo {{ font-family:'Syne',sans-serif; font-size:22px; font-weight:800; color:#ffffff; }}
.topbar-sub {{ font-family:'DM Mono',monospace; font-size:12px; color:rgba(255,255,255,0.8); }}
.btn-nav {{ padding:8px 18px; background:rgba(255,255,255,0.15); border:1px solid rgba(255,255,255,0.3); border-radius:8px; color:#ffffff; font-size:13px; font-weight:600; text-decoration:none; }}
.btn-nav:hover {{ background:rgba(255,255,255,0.25); }}
.content {{ max-width:1000px; margin:0 auto; padding:48px 24px; }}
.page-title {{ font-family:'Syne',sans-serif; font-size:32px; font-weight:800; margin-bottom:6px; }}
.page-sub {{ font-size:13px; color:#4a6648; font-family:'DM Mono',monospace; margin-bottom:32px; }}
.stats {{ display:flex; gap:16px; margin-bottom:28px; flex-wrap:wrap; }}
.stat-card {{ background:#fff; border:1px solid rgba(0,128,0,0.15); border-radius:12px; padding:20px 28px; flex:1; min-width:140px; }}
.stat-num {{ font-family:'Syne',sans-serif; font-size:32px; font-weight:800; color:#008000; line-height:1; }}
.stat-label {{ font-size:12px; color:#4a6648; font-family:'DM Mono',monospace; margin-top:6px; }}
.card {{ background:#fff; border:1px solid rgba(0,128,0,0.15); border-radius:16px; overflow:hidden; }}
.card-header {{ padding:20px 24px; border-bottom:1px solid rgba(0,128,0,0.08); }}
.card-title {{ font-family:'Syne',sans-serif; font-size:18px; font-weight:700; }}
table {{ width:100%; border-collapse:collapse; }}
th {{ padding:12px 16px; text-align:left; font-size:11px; font-family:'DM Mono',monospace; color:#4a6648; text-transform:uppercase; letter-spacing:0.5px; border-bottom:2px solid rgba(0,128,0,0.1); background:#f5faf5; }}
tr:hover td {{ background:rgba(0,128,0,0.02); }}
</style>
</head>
<body>
<div class="topbar">
    <div>
        <div class="topbar-logo">Occupado</div>
        <div class="topbar-sub">Admin Panel</div>
    </div>
    <a href="/admin/logout" class="btn-nav">Sign Out</a>
</div>
<div class="content">
    <div class="page-title">Registered Users</div>
    <div class="page-sub">All hotels that have signed up for Occupado</div>

    <div class="stats">
        <div class="stat-card">
            <div class="stat-num">{total}</div>
            <div class="stat-label">Total signups</div>
        </div>
        <div class="stat-card">
            <div class="stat-num" style="color:#2e7d32;">{verified}</div>
            <div class="stat-label">Verified</div>
        </div>
        <div class="stat-card">
            <div class="stat-num" style="color:#e65100;">{unverified}</div>
            <div class="stat-label">Pending verification</div>
        </div>
    </div>

    <div class="card">
        <div class="card-header">
            <div class="card-title">All Users</div>
        </div>
        <table>
            <thead>
                <tr>
                    <th>Username</th>
                    <th>Hotel Name</th>
                    <th>Email</th>
                    <th>Signed Up</th>
                    <th>Status</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>{rows_html}</tbody>
        </table>
    </div>
</div>
</body>
</html>"""


@app.route("/admin/delete-user/<username>", methods=["POST"])
@admin_required
def admin_delete_user(username):
    username = sanitise(username)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM registered_users WHERE username=%s", (username,))
    cur.execute("DELETE FROM verification_tokens WHERE username=%s", (username,))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for("admin_panel"))


@app.route("/admin/verify-user/<username>", methods=["POST"])
@admin_required
def admin_verify_user(username):
    username = sanitise(username)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE registered_users SET verified=1 WHERE username=%s", (username,))
    cur.execute("DELETE FROM verification_tokens WHERE username=%s", (username,))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for("admin_panel"))


@app.route("/admin/clear-test-data", methods=["POST"])
@admin_required
def admin_clear_test_data():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM registered_users WHERE username IN ('jpdourado', 'admin')")
    cur.execute("DELETE FROM verification_tokens")
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for("admin_panel"))


@app.route("/admin/logout")
@admin_required
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("admin_login"))


if __name__ == "__main__":
    print("\n" + "="*50)
    print("Occupado running on http://localhost:8080")
    print("="*50 + "\n")
    app.run(host="0.0.0.0", port=8080, debug=False)