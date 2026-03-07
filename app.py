from flask import Flask, send_file, request, redirect, url_for, session
import pandas as pd
import pickle
import io
import json
from functools import wraps
from datetime import datetime
import os
import secrets
import sqlite3
from dotenv import load_dotenv
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

load_dotenv()

app = Flask(__name__)
app.secret_key = "occupado-secret-2024"

TOKEN_DIR = "/tmp/occupado_tokens"
os.makedirs(TOKEN_DIR, exist_ok=True)

DB_PATH = "/tmp/occupado_users.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS registered_users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            verified INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS verification_tokens (
            token TEXT PRIMARY KEY,
            username TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

init_db()

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
    "grandmeridian": {"password": "hotel123", "name": "Grand Meridian Hotel", "rooms": 200, "city": "Lisbon"},
    "scandic":       {"password": "hotel456", "name": "Scandic Stockholm",    "rooms": 350, "city": "Stockholm"},
    "demo":          {"password": "demo",      "name": "Demo Hotel",           "rooms": 100, "city": "Porto"},
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

def build_dashboard(hotel_name, sample, scores, tonight_scores, uploaded=False, lang="en", first_login=False):
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
            badge = f'<span class="badge high">{t("high", lang)} {score:.1f}%</span>'
            action = f'<button class="btn dep" onclick="event.stopPropagation(); openEmailComposer({i}, \'deposit\')">{t("req_dep", lang)}</button>'
        elif score >= 40:
            badge = f'<span class="badge med">{t("medium", lang)} {score:.1f}%</span>'
            action = f'<button class="btn rem" onclick="event.stopPropagation(); openEmailComposer({i}, \'reminder\')">{t("send_rem", lang)}</button>'
        else:
            badge = f'<span class="badge low">{t("low", lang)} {score:.1f}%</span>'
            action = f'<button class="btn mon" onclick="event.stopPropagation(); openEmailComposer({i}, \'monitor\')">{t("monitor", lang)}</button>'

        lead = int(booking.get("lead_time", 0))
        adr = int(booking.get("adr", 0))
        rep = t("yes", lang) if booking.get("is_repeated_guest", 0) else t("no", lang)
        canc = int(booking.get("previous_cancellations", 0))

        rows += f"""<tr class="clickable-row" onclick="showDetail({i}, {score:.1f})">
            <td><span style="color:#008000;font-weight:600">{t("booking", lang)} {i+1}</span></td>
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
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:wght@400;500&family=DM+Mono&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#ffffff; color:#0a1a0a; font-family:'DM Sans',sans-serif; }}
.topbar {{ background:#008000; padding:16px 40px; display:flex; align-items:center; justify-content:space-between; }}
.topbar-logo {{ font-family:'Syne',sans-serif; font-size:22px; font-weight:800; color:#ffffff; }}
.topbar-hotel {{ font-family:'DM Mono',monospace; font-size:12px; color:rgba(255,255,255,0.8); }}
.topbar-right {{ display:flex; align-items:center; gap:10px; }}
.lang-selector {{ padding:8px 16px; background:#008000; border:1px solid rgba(0,128,0,0.3); border-radius:8px; color:#ffffff; font-size:13px; font-weight:600; cursor:pointer; font-family:'DM Sans',sans-serif; }}
.lang-selector:hover {{ background:#006600; }}
.logout {{ padding:8px 18px; background:rgba(255,255,255,0.15); border:1px solid rgba(255,255,255,0.3); border-radius:8px; color:#ffffff; font-size:13px; font-weight:600; text-decoration:none; }}
.logout:hover {{ background:rgba(255,255,255,0.25); }}
.settings-btn {{ padding:8px 18px; background:rgba(255,255,255,0.15); border:1px solid rgba(255,255,255,0.3); border-radius:8px; color:#ffffff; font-size:13px; font-weight:600; text-decoration:none; }}
.settings-btn:hover {{ background:rgba(255,255,255,0.25); }}
.clear-btn {{ padding:8px 18px; background:rgba(255,69,96,0.3); border:1px solid rgba(255,69,96,0.5); border-radius:8px; color:#ffffff; font-size:13px; font-weight:600; text-decoration:none; }}
.clear-btn:hover {{ background:rgba(255,69,96,0.5); }}
.content {{ padding:40px; }}
.sub {{ color:#4a6648; font-family:'DM Mono',monospace; font-size:13px; margin-bottom:32px; }}
.section-title {{ font-family:'Syne',sans-serif; font-size:20px; font-weight:700; margin-bottom:16px; margin-top:40px; color:#0a1a0a; }}
.stats {{ display:grid; grid-template-columns:repeat(3,1fr); gap:16px; margin-bottom:32px; }}
.stat {{ background:#f5faf5; border:1px solid rgba(0,128,0,0.15); border-radius:12px; padding:20px; }}
.stat-value {{ font-family:'Syne',sans-serif; font-size:42px; font-weight:800; line-height:1; }}
.stat-label {{ font-family:'DM Mono',monospace; font-size:11px; color:#4a6648; margin-top:6px; }}
.optimizer {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:40px; }}
.opt-main {{ background:rgba(0,128,0,0.04); border:1px solid rgba(0,128,0,0.2); border-radius:12px; padding:28px; }}
.opt-value {{ font-family:'Syne',sans-serif; font-size:72px; font-weight:800; color:#008000; line-height:1; }}
.opt-label {{ font-family:'DM Mono',monospace; font-size:12px; color:#4a6648; margin-top:6px; }}
.opt-btn {{ margin-top:20px; width:100%; padding:12px; background:#008000; border:none; border-radius:8px; color:#ffffff; font-size:14px; font-weight:600; cursor:pointer; }}
.opt-btn:hover {{ background:#006600; }}
.opt-stats {{ background:#f5faf5; border:1px solid rgba(0,128,0,0.15); border-radius:12px; padding:24px; }}
.opt-row {{ display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid rgba(0,128,0,0.08); font-size:13px; }}
.opt-row:last-child {{ border-bottom:none; }}
.opt-row-label {{ color:#4a6648; }}
.opt-row-value {{ font-family:'DM Mono',monospace; font-weight:500; }}
.bulk-action-zone {{ display:grid; grid-template-columns:repeat(3,1fr); gap:16px; margin-bottom:40px; }}
.bulk-action-card {{ background:#f5faf5; border:1px solid rgba(0,128,0,0.15); border-radius:12px; padding:20px; text-align:center; }}
.bulk-action-icon {{ font-size:32px; margin-bottom:10px; }}
.bulk-action-title {{ font-family:'Syne',sans-serif; font-size:14px; font-weight:700; margin-bottom:6px; }}
.bulk-action-sub {{ font-size:12px; color:#4a6648; margin-bottom:14px; }}
.bulk-action-btn {{ padding:10px 16px; background:#008000; color:#ffffff; border:none; border-radius:8px; font-size:12px; font-weight:600; cursor:pointer; width:100%; font-family:'DM Sans',sans-serif; }}
.bulk-action-btn:hover {{ background:#006600; }}
.bulk-action-btn.deposit-btn {{ background:#cc0000; }}
.bulk-action-btn.deposit-btn:hover {{ background:#990000; }}
.bulk-action-btn.reminder-btn {{ background:#cc6600; }}
.bulk-action-btn.reminder-btn:hover {{ background:#994400; }}
table {{ width:100%; border-collapse:collapse; background:#f5faf5; border-radius:16px; overflow:hidden; border:1px solid rgba(0,128,0,0.15); }}
th {{ background:#008000; color:#ffffff; font-family:'DM Mono',monospace; font-size:11px; text-transform:uppercase; padding:14px 16px; text-align:left; }}
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
.upload-btn {{ padding:12px 28px; background:#008000; color:#ffffff; border:none; border-radius:10px; font-size:14px; font-weight:600; cursor:pointer; }}
.upload-banner {{ background:rgba(0,128,0,0.08); border:1px solid rgba(0,128,0,0.2); border-radius:10px; padding:14px 20px; font-size:13px; color:#008000; margin-bottom:24px; font-weight:500; }}
.modal-overlay {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,0.5); z-index:1000; align-items:center; justify-content:center; }}
.modal-overlay.show {{ display:flex; }}
.modal {{ background:#ffffff; border-radius:20px; padding:40px; width:100%; max-width:560px; max-height:85vh; overflow-y:auto; position:relative; box-shadow:0 20px 60px rgba(0,0,0,0.2); }}
.modal-close {{ position:absolute; top:16px; right:20px; font-size:22px; cursor:pointer; color:#4a6648; background:none; border:none; }}
.modal-title {{ font-family:'Syne',sans-serif; font-size:22px; font-weight:800; margin-bottom:4px; }}
.modal-sub {{ font-family:'DM Mono',monospace; font-size:12px; color:#4a6648; margin-bottom:24px; }}
.score-display {{ font-family:'Syne',sans-serif; font-size:64px; font-weight:800; line-height:1; margin-bottom:8px; }}
.score-bar-bg {{ height:10px; background:#f0f0f0; border-radius:5px; overflow:hidden; margin-bottom:12px; }}
.score-bar-fill {{ height:100%; border-radius:5px; }}
.score-verdict {{ font-size:14px; font-weight:600; padding:8px 16px; border-radius:8px; display:inline-block; margin-bottom:8px; }}
.email-composer {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,0.5); z-index:1001; align-items:center; justify-content:center; }}
.email-composer.show {{ display:flex; }}
.email-box {{ background:#ffffff; border-radius:20px; padding:32px; width:100%; max-width:700px; max-height:90vh; overflow-y:auto; box-shadow:0 20px 60px rgba(0,0,0,0.2); }}
.email-title {{ font-family:'Syne',sans-serif; font-size:20px; font-weight:800; margin-bottom:4px; }}
.email-label {{ font-family:'DM Mono',monospace; font-size:11px; color:#4a6648; text-transform:uppercase; display:block; margin-bottom:6px; font-weight:600; }}
.email-input {{ width:100%; padding:12px 16px; background:#f5faf5; border:1px solid rgba(0,128,0,0.2); border-radius:10px; font-size:14px; color:#0a1a0a; outline:none; margin-bottom:16px; }}
.email-input:focus {{ border-color:#008000; background:#ffffff; }}
.email-textarea {{ width:100%; padding:12px 16px; background:#f5faf5; border:1px solid rgba(0,128,0,0.2); border-radius:10px; font-size:13px; color:#0a1a0a; outline:none; resize:vertical; min-height:200px; margin-bottom:16px; }}
.email-textarea:focus {{ border-color:#008000; background:#ffffff; }}
.email-actions {{ display:flex; gap:12px; margin-top:24px; }}
.email-send {{ flex:1; padding:14px; background:#008000; color:#ffffff; border:none; border-radius:10px; font-size:14px; font-weight:600; cursor:pointer; }}
.email-send:hover {{ background:#006600; }}
.email-cancel {{ flex:1; padding:14px; background:#f5faf5; color:#0a1a0a; border:1px solid rgba(0,128,0,0.2); border-radius:10px; font-size:14px; font-weight:600; cursor:pointer; }}
.bulk-email-composer {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,0.5); z-index:1002; align-items:center; justify-content:center; }}
.bulk-email-composer.show {{ display:flex; }}
.bulk-email-box {{ background:#ffffff; border-radius:20px; padding:32px; width:100%; max-width:700px; max-height:90vh; overflow-y:auto; box-shadow:0 20px 60px rgba(0,0,0,0.2); }}
.bulk-email-title {{ font-family:'Syne',sans-serif; font-size:20px; font-weight:800; margin-bottom:4px; }}
.bulk-email-subtitle {{ font-family:'DM Mono',monospace; font-size:12px; color:#4a6648; }}
.bulk-email-actions {{ display:flex; gap:12px; margin-top:24px; }}
.bulk-email-send {{ flex:1; padding:14px; background:#008000; color:#ffffff; border:none; border-radius:10px; font-size:14px; font-weight:600; cursor:pointer; }}
.bulk-email-send:hover {{ background:#006600; }}
.bulk-email-send.deposit {{ background:#cc0000; }}
.bulk-email-send.deposit:hover {{ background:#990000; }}
.bulk-email-send.reminder {{ background:#cc6600; }}
.bulk-email-send.reminder:hover {{ background:#994400; }}
.bulk-email-cancel {{ flex:1; padding:14px; background:#f5faf5; color:#0a1a0a; border:1px solid rgba(0,128,0,0.2); border-radius:10px; font-size:14px; font-weight:600; cursor:pointer; }}
.bulk-booking-row {{ padding:8px; margin-bottom:4px; background:rgba(204, 0, 0, 0.08); border:2px solid rgba(204, 0, 0, 0.2); border-radius:6px; font-size:11px; display:flex; justify-content:space-between; align-items:center; transition:all 0.3s; cursor:pointer; user-select:none; }}
.bulk-booking-row:hover {{ transform:translateX(4px); box-shadow:0 2px 8px rgba(204, 0, 0, 0.15); }}
.toast {{ position:fixed; bottom:24px; right:24px; background:#008000; color:#ffffff; border-radius:12px; padding:16px 20px; font-size:13px; transform:translateY(80px); opacity:0; transition:all 0.35s; z-index:2000; }}
.toast.show {{ transform:translateY(0); opacity:1; }}
</style>
</head>
<body>
<div class="topbar">
    <div>
        <div class="topbar-logo">{t("occupado", lang)}</div>
        <div class="topbar-hotel">{hotel_name} · {t("ai_booking", lang)}</div>
    </div>
    <div class="topbar-right">
        {clear_button}
        <select class="lang-selector" onchange="changeLanguage(this.value)">
            <option value="en" {"selected" if lang == "en" else ""}>🇬🇧 English</option>
            <option value="nl" {"selected" if lang == "nl" else ""}>🇳🇱 Nederlands</option>
            <option value="fr" {"selected" if lang == "fr" else ""}>🇫🇷 Français</option>
        </select>
        <a href="/settings" class="settings-btn">⚙️ {t("settings", lang)}</a>
        <a href="/logout" class="logout">{t("sign_out", lang)}</a>
    </div>
</div>
{f'''<div id="welcome-banner" style="background:rgba(0,128,0,0.07);border-bottom:1px solid rgba(0,128,0,0.15);padding:12px 40px;display:flex;align-items:center;justify-content:space-between;">
    <span style="font-size:14px;color:#2e5f2e;">👋 Welcome to Occupado, <strong>{hotel_name}</strong>. Upload your booking data to get your first AI risk scores.</span>
    <button onclick="document.getElementById('welcome-banner').style.display='none'" style="background:none;border:none;color:#4a6648;font-size:18px;cursor:pointer;padding:0 4px;line-height:1;">×</button>
</div>''' if first_login else ''}
<div class="content">
<div class="sub">{t("live_dashboard", lang)} · {len(sample)} {t("bookings_analysed", lang)}</div>
{upload_banner}
<div class="section-title">{t("upload_data", lang)}</div>
<form method="POST" action="/upload" enctype="multipart/form-data">
    <div class="upload-zone" onclick="document.getElementById('csv-input').click()">
        <div class="upload-zone-title">{t("drop_csv", lang)}</div>
        <div class="upload-zone-sub">{t("export_pms", lang)}</div>
        <input type="file" id="csv-input" name="csv_file" accept=".csv" style="display:none" onchange="this.form.submit()">
        <button type="button" class="upload-btn" onclick="event.stopPropagation();document.getElementById('csv-input').click()">{t("choose_file", lang)}</button>
    </div>
</form>
<div class="stats">
    <div class="stat"><div class="stat-value" style="color:#cc0000">{high}</div><div class="stat-label">{t("high_risk", lang)}</div></div>
    <div class="stat"><div class="stat-value" style="color:#cc6600">{med}</div><div class="stat-label">{t("medium_risk", lang)}</div></div>
    <div class="stat"><div class="stat-value" style="color:#008000">{low}</div><div class="stat-label">{t("low_risk", lang)}</div></div>
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
        <div class="opt-row"><span class="opt-row-label">{t("bookings_analysed_stat", lang)}</span><span class="opt-row-value">{len(sample)}</span></div>
        <div class="opt-row"><span class="opt-row-label">{t("predicted", lang)}</span><span class="opt-row-value" style="color:#cc0000">{predicted_noshows}</span></div>
        <div class="opt-row"><span class="opt-row-label">{t("confidence", lang)}</span><span class="opt-row-value" style="color:#008000">80.7%</span></div>
        <div class="opt-row"><span class="opt-row-label">{t("walk_risk", lang)}</span><span class="opt-row-value" style="color:#008000">2.1%</span></div>
        <div class="opt-row"><span class="opt-row-label">{t("avg_rate", lang)}</span><span class="opt-row-value">EUR {avg_rate:.0f}</span></div>
    </div>
</div>
{bulk_action_html}
<div class="section-title">{t("click_row", lang)}</div>
<table>
<thead><tr><th>{t("booking", lang)}</th><th>{t("lead", lang)}</th><th>{t("rate", lang)}</th><th>{t("returning", lang)}</th><th>{t("cancels", lang)}</th><th>{t("risk", lang)}</th><th>{t("action", lang)}</th></tr></thead>
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
</script>
</body>
</html>"""
    return dashboard_html

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
    
    if hotel_username not in HOTELS:
        return redirect(url_for("login"))
    
    session["hotel"] = hotel_username
    session["hotel_name"] = HOTELS[hotel_username]["name"]
    session["alert_email"] = ""
    session["uploaded_csv"] = csv_data
    
    delete_token(token)
    print(f"[MAGIC] Auto-logged in: {hotel_username}")
    
    return redirect(url_for("dashboard"))

@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    success = session.pop("verified_success", "")
    if request.method == "POST":
        username = request.form.get("username", "").lower().strip()
        password = request.form.get("password", "").strip()
        # Check admin credentials
        if username == "jpdourado" and password == "livejoao":
            session["is_admin"] = True
            return redirect(url_for("admin_panel"))
        # Check demo/hotel accounts first
        if username in HOTELS and HOTELS[username]["password"] == password:
            session["hotel"] = username
            session["hotel_name"] = HOTELS[username]["name"]
            session["alert_email"] = ""
            session["language"] = "en"
            session["first_login"] = True
            return redirect(url_for("dashboard"))
        # Check registered users in SQLite
        if not error:
            conn = get_db()
            user = conn.execute("SELECT * FROM registered_users WHERE username=?", (username,)).fetchone()
            conn.close()
            if user and user["password"] == password:
                if not user["verified"]:
                    error = "Please verify your email before logging in. Check your inbox."
                else:
                    session["hotel"] = username
                    session["hotel_name"] = user["name"]
                    session["alert_email"] = user["email"]
                    session["language"] = "en"
                    session["first_login"] = True
                    return redirect(url_for("dashboard"))
            else:
                error = "Invalid credentials"

    error_html   = f'<div style="background:#ffcdd2;padding:12px;margin-bottom:20px;color:#c62828;border-radius:8px;font-size:14px;">{error}</div>' if error else ''
    success_html = f'<div style="background:#e8f5e9;padding:12px;margin-bottom:20px;color:#2e7d32;border-radius:8px;font-size:14px;">{success}</div>' if success else ''

    return f"""<!DOCTYPE html>
<html>
<head><title>Occupado — Login</title>
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
.switch-link a:hover {{ text-decoration:underline; }}
</style>
</head>
<body>
<div class="box">
    <div class="logo">Occupado</div>
    <div class="subtitle">AI Booking Intelligence</div>
    {error_html}{success_html}
    <form method="POST">
        <label>Username</label>
        <input type="text" name="username" required autocomplete="username">
        <label>Password</label>
        <input type="password" name="password" required autocomplete="current-password">
        <button type="submit">Sign In →</button>
    </form>
    <div class="switch-link">Don't have an account? <a href="/register">Register free →</a></div>
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
    lang = request.args.get("lang", session.get("language", "en"))
    
    if lang not in TRANSLATIONS:
        lang = "en"
    
    session["language"] = lang
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

    first_login = session.pop("first_login", False)
    return build_dashboard(hotel_name, sample, scores, tonight_scores, uploaded=uploaded, lang=lang, first_login=first_login)

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
    data = request.get_json()
    guest_email = data.get("guest_email", "").strip()
    guest_name = data.get("guest_name", "Guest")
    subject = data.get("subject", "")
    body = data.get("body", "")
    
    hotel_name = session.get("hotel_name", "Hotel")
    success = send_email_to_guest(guest_email, guest_name, hotel_name, subject, body)
    
    if success:
        return {"status": "success", "message": f"Email sent to {guest_email}"}
    else:
        return {"status": "error", "message": "Failed to send email"}, 500

@app.route("/send-bulk-email", methods=["POST"])
@login_required
def send_bulk_email():
    data = request.get_json()
    count = data.get("count", 0)
    subject = data.get("subject", "")
    body = data.get("body", "")
    
    if not subject or not body or count == 0:
        return {"status": "error", "message": "Missing required fields"}, 400
    
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


@app.route("/register", methods=["GET", "POST"])
def register():
    error = ""
    success = ""
    if request.method == "POST":
        hotel_name = request.form.get("hotel_name", "").strip()
        email      = request.form.get("email", "").strip().lower()
        username   = request.form.get("username", "").strip().lower()
        password   = request.form.get("password", "").strip()
        confirm    = request.form.get("confirm", "").strip()

        RESERVED_USERNAMES = set(HOTELS.keys()) | {"jpdourado", "admin", "occupado"}

        if not all([hotel_name, email, username, password, confirm]):
            error = "All fields are required."
        elif password != confirm:
            error = "Passwords do not match."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        elif username in RESERVED_USERNAMES:
            error = "That username is already taken. Please choose another."
        else:
            conn = get_db()
            existing = conn.execute("SELECT username FROM registered_users WHERE username=?", (username,)).fetchone()
            if existing:
                error = "That username is already taken. Please choose another."
                conn.close()
            else:
                token = secrets.token_urlsafe(32)
                conn.execute("INSERT INTO registered_users (username, password, name, email, verified) VALUES (?,?,?,?,0)",
                             (username, password, hotel_name, email))
                conn.execute("INSERT INTO verification_tokens (token, username) VALUES (?,?)", (token, username))
                conn.commit()
                conn.close()
                sent = send_verification_email(email, hotel_name, token)
                if sent:
                    success = f"Account created! A verification email has been sent to {email}. Please check your inbox."
                else:
                    conn2 = get_db()
                    conn2.execute("UPDATE registered_users SET verified=1 WHERE username=?", (username,))
                    conn2.execute("DELETE FROM verification_tokens WHERE token=?", (token,))
                    conn2.commit()
                    conn2.close()
                    success = "Account created! (Email verification skipped — no SendGrid key detected.) You can now sign in."

    error_html   = f'<div style="background:#ffcdd2;padding:12px;margin-bottom:20px;color:#c62828;border-radius:8px;font-size:14px;">{error}</div>' if error else ''
    success_html = f'<div style="background:#e8f5e9;padding:12px;margin-bottom:20px;color:#2e7d32;border-radius:8px;font-size:14px;">{success}</div>' if success else ''

    return f"""<!DOCTYPE html>
<html>
<head><title>Occupado — Register</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:wght@400;500&family=DM+Mono&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#f5faf5; font-family:'DM Sans',sans-serif; min-height:100vh; display:flex; align-items:center; justify-content:center; padding:24px; }}
.box {{ background:#ffffff; padding:48px; border-radius:20px; width:100%; max-width:440px; border:1px solid rgba(0,128,0,0.15); }}
.logo {{ font-family:'Syne',sans-serif; font-size:28px; font-weight:800; color:#008000; margin-bottom:4px; }}
.subtitle {{ font-size:13px; color:#4a6648; margin-bottom:28px; font-family:'DM Mono',monospace; }}
label {{ font-size:12px; color:#4a6648; display:block; margin-bottom:6px; font-family:'DM Mono',monospace; font-weight:600; text-transform:uppercase; letter-spacing:0.5px; }}
input {{ width:100%; padding:12px; background:#f5faf5; border:1px solid rgba(0,128,0,0.2); border-radius:10px; font-size:14px; margin-bottom:16px; outline:none; font-family:'DM Sans',sans-serif; }}
input:focus {{ border-color:#008000; background:white; }}
button {{ width:100%; padding:14px; background:#008000; color:white; border:none; border-radius:10px; font-weight:700; cursor:pointer; font-size:15px; font-family:'DM Sans',sans-serif; }}
button:hover {{ background:#006600; }}
.switch-link {{ text-align:center; margin-top:20px; font-size:13px; color:#4a6648; }}
.switch-link a {{ color:#008000; font-weight:700; text-decoration:none; }}
.switch-link a:hover {{ text-decoration:underline; }}
.badge {{ display:inline-block; background:rgba(0,128,0,0.08); border:1px solid rgba(0,128,0,0.2); border-radius:20px; padding:6px 14px; font-family:'DM Mono',monospace; font-size:11px; color:#008000; margin-bottom:24px; letter-spacing:0.5px; }}
</style>
</head>
<body>
<div class="box">
    <div class="logo">Occupado</div>
    <div class="subtitle">AI Booking Intelligence</div>
    <div class="badge">✦ Free 40-day pilot · No credit card</div>
    {error_html}{success_html}
    {'<div style="text-align:center;margin-top:12px;"><a href="/login" style="color:#008000;font-weight:700;text-decoration:none;">← Back to Sign In</a></div>' if success else f"""
    <form method="POST">
        <label>Hotel Name</label>
        <input type="text" name="hotel_name" placeholder="e.g. Grand Hotel Lisbon" required>
        <label>Email Address</label>
        <input type="email" name="email" placeholder="you@hotel.com" required>
        <label>Username</label>
        <input type="text" name="username" placeholder="Choose a username" required>
        <label>Password</label>
        <input type="password" name="password" placeholder="Min. 6 characters" required>
        <label>Confirm Password</label>
        <input type="password" name="confirm" placeholder="Repeat password" required>
        <button type="submit">Create Account →</button>
    </form>
    <div class="switch-link">Already have an account? <a href="/login">Sign in →</a></div>
    """}
</div>
</body>
</html>"""


@app.route("/verify/<token>")
def verify_email(token):
    conn = get_db()
    row = conn.execute("SELECT username FROM verification_tokens WHERE token=?", (token,)).fetchone()
    if not row:
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

    username = row["username"]
    conn.execute("UPDATE registered_users SET verified=1 WHERE username=?", (username,))
    conn.execute("DELETE FROM verification_tokens WHERE token=?", (token,))
    conn.commit()
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
        pw = request.form.get("password", "").strip()
        if pw == ADMIN_PASSWORD:
            session["is_admin"] = True
            return redirect(url_for("admin_panel"))
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
def admin_panel():
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))

    conn = get_db()
    users = conn.execute(
        "SELECT username, name, email, verified FROM registered_users ORDER BY rowid DESC"
    ).fetchall()
    conn.close()

    total      = len(users)
    verified   = sum(1 for u in users if u["verified"])
    unverified = total - verified

    rows_html = ""
    for u in users:
        verified_badge = '<span style="background:#e8f5e9;color:#2e7d32;border-radius:6px;padding:3px 10px;font-size:11px;font-family:DM Mono,monospace;font-weight:600;">✓ Verified</span>' \
                       if u["verified"] else \
                       '<span style="background:#fff3e0;color:#e65100;border-radius:6px;padding:3px 10px;font-size:11px;font-family:DM Mono,monospace;font-weight:600;">Pending</span>'
        rows_html += f"""<tr>
            <td style="padding:14px 16px;font-size:14px;font-family:'DM Mono',monospace;color:#0a1a0a;border-bottom:1px solid rgba(0,128,0,0.08);">{u['username']}</td>
            <td style="padding:14px 16px;font-size:14px;color:#0a1a0a;border-bottom:1px solid rgba(0,128,0,0.08);">{u['name']}</td>
            <td style="padding:14px 16px;font-size:14px;color:#4a6648;border-bottom:1px solid rgba(0,128,0,0.08);">{u['email']}</td>
            <td style="padding:14px 16px;border-bottom:1px solid rgba(0,128,0,0.08);">{verified_badge}</td>
        </tr>"""

    if not rows_html:
        rows_html = '<tr><td colspan="4" style="padding:32px;text-align:center;color:#4a6648;font-size:14px;">No registered users yet.</td></tr>'

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
.content {{ max-width:900px; margin:0 auto; padding:48px 24px; }}
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
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>{rows_html}</tbody>
        </table>
    </div>
</div>
</body>
</html>"""


@app.route("/admin/clear-test-data")
def admin_clear_test_data():
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))
    conn = get_db()
    conn.execute("DELETE FROM registered_users WHERE username IN ('jpdourado', 'admin')")
    conn.execute("DELETE FROM verification_tokens")
    conn.commit()
    conn.close()
    return redirect(url_for("admin_panel"))


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("admin_login"))


if __name__ == "__main__":
    print("\n" + "="*50)
    print("Occupado running on http://localhost:8080")
    print("="*50 + "\n")
    app.run(host="0.0.0.0", port=8080, debug=False)