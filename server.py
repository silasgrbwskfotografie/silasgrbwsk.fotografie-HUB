"""
Studio-Tool silasgrbwsk.fotografie
Interne Arbeitsoberfläche: Aufträge, Zahlungen, Bildauslieferung, Verträge, später Postfach, Kalender und Aufgaben.
Aufbau wie beim Emden Tigers Hub: ein Python-Prozess, nur Standardbibliothek, SQLite unter /data.

Lokal:            python server.py          (http://127.0.0.1:3000)
Benutzer anlegen: python server.py adduser <name>
Passwort setzen:  python server.py passwd <name>
2FA zurücksetzen: python server.py 2fa-reset <name>   (Notfall: Handy weg und keine Wiederherstellungscodes mehr)

Konfiguration über Umgebungsvariablen (auf dem Server aus der .env):
  STUDIO_HOST            Adresse, an die der Server bindet (Standard 127.0.0.1, im Container 0.0.0.0)
  STUDIO_PORT            Port (Standard 3000)
  STUDIO_DATA            Datenordner (Standard: Ordner "data" neben dieser Datei)
  STUDIO_SECURE_COOKIES  1 = Login-Cookie nur über HTTPS (hinter Caddy immer 1)
  STUDIO_TRUST_PROXY     1 = Client-IP aus X-Forwarded-For übernehmen (nur hinter Caddy)
  DOMAIN                 öffentliche Adresse ohne https://, Links werden nur daraus gebaut
  STUDIO_ADMIN_USER      Benutzername des ersten Admins
  STUDIO_ADMIN_PASSWORD  Passwort des ersten Admins (nur genutzt, solange es keinen Benutzer gibt)
  STUDIO_RESET_PASSWORD  1 = Passwort von STUDIO_ADMIN_USER beim Start auf STUDIO_ADMIN_PASSWORD zurücksetzen
"""

import base64
import calendar
import contextlib
import csv
import io
import getpass
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse
from zoneinfo import ZoneInfo

VERSION = "0.6"
APP_NAME = "Studio-Tool"
ENV = os.environ.get
HOST = ENV("STUDIO_HOST", "127.0.0.1")
PORT = int(ENV("STUDIO_PORT", "3000"))
SECURE_COOKIES = ENV("STUDIO_SECURE_COOKIES") == "1"
TRUST_PROXY = ENV("STUDIO_TRUST_PROXY") == "1"
DOMAIN = (ENV("DOMAIN") or "").strip().strip("/")
SITE_URL = f"https://{DOMAIN}" if DOMAIN else f"http://127.0.0.1:{PORT}"
TZ = ZoneInfo("Europe/Berlin")
MAX_JSON = 2 * 1024 * 1024
SESSION_DAYS = 30
COOKIE = "studio_session"
CSRF_HEADER = "X-Studio"          # jede schreibende Anfrage braucht "X-Studio: 1" (fremde Seiten können ihn nicht setzen)

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"
DATA = Path(ENV("STUDIO_DATA") or (BASE / "data")).resolve()
UPLOADS = DATA / "uploads"
BACKUPS = DATA / "backups"
DB_PATH = DATA / "studio.db"

# ---------------------------------------------------------------------------
# Datenbank-Schema
# Jede Tabelle: Spaltenname -> SQL-Typ. "id" wird automatisch angelegt.
# Neue Spalten hier ergänzen, sie werden beim Start zur bestehenden Datenbank hinzugefügt.
# Geldbeträge immer als ganze Cent (Spalten *_cent), Datum als JJJJ-MM-TT, Zeitpunkte als ISO mit Zeitzone.
# ---------------------------------------------------------------------------
STATUS_AUFTRAG = ("Angefragt", "Bestätigt", "Fotografiert", "Geliefert", "Abgeschlossen", "Abgesagt")
STATUS_ZAHLUNG = ("Offen", "Bezahlt", "Erlassen")
ZAHLARTEN = ("Bar", "Überweisung", "PayPal")
KUNDEN_TYPEN = ("Verein", "Sparte", "Einzelperson")
LINK_TYPEN = ("Picdrop", "pCloud", "Sonstiges")
VERTRAG_ARTEN = ("Saisonvertrag", "Einwilligungs- und Nutzungsvereinbarung", "Sponsoring")

TABLES = {
    # ---- Kern: der Auftrag ist der Mittelpunkt ----
    "kunden": {
        "name": "TEXT NOT NULL",
        "typ": "TEXT DEFAULT 'Verein'",                  # KUNDEN_TYPEN
        "parent_id": "INTEGER REFERENCES kunden(id)",    # Sparte gehört zu Verein
        "notizen": "TEXT",
        "archiviert": "INTEGER DEFAULT 0",
        "erstellt_am": "TEXT",
        "geaendert_am": "TEXT",
    },
    "kontakte": {                                        # Ansprechperson oder Zahler
        "kunde_id": "INTEGER REFERENCES kunden(id)",
        "name": "TEXT",
        "rolle": "TEXT",
        "telefon": "TEXT",
        "email": "TEXT",
        "instagram": "TEXT",
        "notizen": "TEXT",
        "anonymisiert": "INTEGER DEFAULT 0",             # Löschwunsch: Daten leeren, Umsätze bleiben
        "erstellt_am": "TEXT",
        "geaendert_am": "TEXT",
    },
    "pakete": {                                          # Preisvorlage
        "name": "TEXT NOT NULL",
        "grundpreis_cent": "INTEGER NOT NULL DEFAULT 0",
        "inkl_spieler": "INTEGER DEFAULT 0",             # 0 = keine Spielerstaffel
        "zusatzspieler_cent": "INTEGER DEFAULT 0",
        "finom_text": "TEXT",                            # Leistungstext für die Rechnung in Finom
        "aktiv": "INTEGER DEFAULT 1",
        "sort": "INTEGER DEFAULT 0",
    },
    "auftraege": {                                       # ein Spiel oder Shooting
        "kunde_id": "INTEGER REFERENCES kunden(id)",
        "paket_id": "INTEGER REFERENCES pakete(id)",
        "serie": "TEXT",                                 # gemeinsame Kennung bei Serien-Anlage
        "datum": "TEXT",
        "uhrzeit": "TEXT",
        "ort": "TEXT",
        "sportart": "TEXT",
        "begegnung": "TEXT",
        "status": "TEXT DEFAULT 'Angefragt'",            # STATUS_AUFTRAG
        "km": "INTEGER DEFAULT 0",                       # einfache Strecke ab Emden
        "spieler": "INTEGER DEFAULT 0",
        # beim Anlegen festgeschrieben, spätere Paketpreise ändern alte Aufträge nicht
        "grundpreis_cent": "INTEGER DEFAULT 0",
        "inkl_spieler": "INTEGER DEFAULT 0",
        "zusatz_je_spieler_cent": "INTEGER DEFAULT 0",
        "anfahrt_frei_km": "INTEGER DEFAULT 0",
        "anfahrt_cent_je_km": "INTEGER DEFAULT 0",
        "zusatzspieler_cent": "INTEGER DEFAULT 0",       # Summe für alle Zusatzspieler
        "anfahrt_cent": "INTEGER DEFAULT 0",             # Summe Anfahrt
        "betrag_cent": "INTEGER DEFAULT 0",
        "betrag_manuell": "INTEGER DEFAULT 0",           # 1 = Betrag von Hand überschrieben
        "lieferfrist": "TEXT",
        "notizen": "TEXT",
        "archiviert": "INTEGER DEFAULT 0",
        "erstellt_am": "TEXT",
        "geaendert_am": "TEXT",
    },
    "zahlungen": {                                       # je Auftrag genau eine "Zahlung", dazu höchstens eine "Anzahlung"
        "auftrag_id": "INTEGER REFERENCES auftraege(id)",
        "art": "TEXT DEFAULT 'Zahlung'",                 # Zahlung / Anzahlung
        "zahler_id": "INTEGER REFERENCES kontakte(id)",
        "betrag_cent": "INTEGER DEFAULT 0",
        "status": "TEXT DEFAULT 'Offen'",                # STATUS_ZAHLUNG
        "zahlart": "TEXT",                               # ZAHLARTEN
        "zahldatum": "TEXT",
        "finom_abgerechnet": "INTEGER DEFAULT 0",
        "finom_rechnungsnr": "TEXT",
        "notizen": "TEXT",
        "erstellt_am": "TEXT",
        "geaendert_am": "TEXT",
    },
    "lieferlinks": {                                     # Galerie-Link zum Auftrag (Bilder selbst liegen bei Picdrop/pCloud)
        "auftrag_id": "INTEGER REFERENCES auftraege(id)",
        "typ": "TEXT DEFAULT 'Picdrop'",                 # LINK_TYPEN
        "url": "TEXT",
        "empfaenger": "TEXT",
        "erstellt_am": "TEXT",
        "laeuft_ab_am": "TEXT",
        "hinweis": "TEXT",
    },
    "vertraege": {
        "kunde_id": "INTEGER REFERENCES kunden(id)",
        "art": "TEXT",                                   # VERTRAG_ARTEN
        "beginn": "TEXT",
        "mindestlaufzeit_monate": "INTEGER",
        "kuendigungsfrist_wert": "INTEGER",
        "kuendigungsfrist_einheit": "TEXT DEFAULT 'Monate'",   # Tage / Wochen / Monate
        "verlaengerung_monate": "INTEGER",               # leer oder 0: endet; sonst verlängert sich um so viele Monate
        "ende": "TEXT",
        "datei": "TEXT",                                 # zufälliger Dateiname unter uploads/
        "datei_name": "TEXT",                            # ursprünglicher Name für den Download
        "notizen": "TEXT",
        "archiviert": "INTEGER DEFAULT 0",
        "erstellt_am": "TEXT",
        "geaendert_am": "TEXT",
    },
    "dokumente": {                                       # freie Ablage je Kunde (z. B. Akkreditierungen)
        "kunde_id": "INTEGER REFERENCES kunden(id)",
        "titel": "TEXT",
        "datei": "TEXT",
        "datei_name": "TEXT",
        "groesse": "INTEGER",
        "notizen": "TEXT",
        "hochgeladen_am": "TEXT",
    },
    "vorlagen": {                                        # Nachrichtenvorlagen mit Platzhaltern {name} {spiel} {datum} {link} {ablauf}
        "name": "TEXT NOT NULL",
        "text": "TEXT",
        "sort": "INTEGER DEFAULT 0",
    },
    # ---- Erweiterung: Postfach, Kalender, Aufgaben, Push ----
    "mailkonten": {                                      # wie user_mail im Hub, Passwort liegt in secrets ("mailkonto:<id>")
        "name": "TEXT",
        "adresse": "TEXT",
        "smtp_host": "TEXT",
        "smtp_port": "INTEGER DEFAULT 465",
        "imap_host": "TEXT",
        "imap_port": "INTEGER DEFAULT 993",
        "benutzer": "TEXT",
        "signatur": "TEXT",
        "aktiv": "INTEGER DEFAULT 1",
        "sort": "INTEGER DEFAULT 0",
    },
    "mail_eingang": {                                    # Stand des Hintergrund-Abrufs, wie pf_inbox im Hub
        "konto_id": "INTEGER REFERENCES mailkonten(id)",
        "uidvalidity": "INTEGER",
        "uid": "INTEGER",
        "message_id": "TEXT",
        "betreff": "TEXT",
        "absender": "TEXT",
        "status": "TEXT DEFAULT 'neu'",                  # neu / erledigt
        "erkannt_am": "TEXT",
        "erledigt_am": "TEXT",
    },
    "mail_verweise": {                                   # nur der Verweis, nie die Mail selbst
        "konto_id": "INTEGER REFERENCES mailkonten(id)",
        "ordner": "TEXT",
        "message_id": "TEXT",
        "betreff": "TEXT",
        "absender": "TEXT",
        "kunde_id": "INTEGER REFERENCES kunden(id)",
        "auftrag_id": "INTEGER REFERENCES auftraege(id)",
        "erstellt_am": "TEXT",
    },
    "termine": {
        "titel": "TEXT",
        "beginn": "TEXT",
        "ende": "TEXT",
        "ganztaegig": "INTEGER DEFAULT 0",
        "ort": "TEXT",
        "art": "TEXT",                                   # Besprechung, Vorbereitung, privat geblockt ...
        "wiederholung": "TEXT",
        "erinnerung_min": "INTEGER",
        "kunde_id": "INTEGER REFERENCES kunden(id)",
        "auftrag_id": "INTEGER REFERENCES auftraege(id)",
        "notizen": "TEXT",
        "erstellt_am": "TEXT",
        "geaendert_am": "TEXT",
    },
    "aufgaben": {
        "titel": "TEXT",
        "faellig": "TEXT",
        "prioritaet": "TEXT DEFAULT 'Mittel'",           # Hoch / Mittel / Niedrig
        "status": "TEXT DEFAULT 'Offen'",                # Offen / In Arbeit / Erledigt
        "wiederholung": "TEXT",
        "kunde_id": "INTEGER REFERENCES kunden(id)",
        "auftrag_id": "INTEGER REFERENCES auftraege(id)",
        "mail_verweis_id": "INTEGER REFERENCES mail_verweise(id)",
        "notizen": "TEXT",
        "sort": "INTEGER DEFAULT 0",
        "erledigt_am": "TEXT",
        "erstellt_am": "TEXT",
        "geaendert_am": "TEXT",
    },
    "push_abos": {                                       # angemeldetes Gerät
        "endpoint": "TEXT",                              # eindeutig über ux_push_endpoint
        "p256dh": "TEXT",
        "auth": "TEXT",
        "geraet": "TEXT",
        "angelegt_am": "TEXT",
    },
}

INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_auftraege_datum ON auftraege(datum)",
    "CREATE INDEX IF NOT EXISTS ix_auftraege_kunde ON auftraege(kunde_id)",
    "CREATE INDEX IF NOT EXISTS ix_zahlungen_auftrag ON zahlungen(auftrag_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_zahlungen_art ON zahlungen(auftrag_id, art)",
    "CREATE INDEX IF NOT EXISTS ix_lieferlinks_auftrag ON lieferlinks(auftrag_id)",
    "CREATE INDEX IF NOT EXISTS ix_kontakte_kunde ON kontakte(kunde_id)",
    "CREATE INDEX IF NOT EXISTS ix_vertraege_kunde ON vertraege(kunde_id)",
    "CREATE INDEX IF NOT EXISTS ix_mail_eingang_konto ON mail_eingang(konto_id, uid)",
    "CREATE INDEX IF NOT EXISTS ix_termine_beginn ON termine(beginn)",
    "CREATE INDEX IF NOT EXISTS ix_aufgaben_faellig ON aufgaben(faellig)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_push_endpoint ON push_abos(endpoint)",
)

# Startwerte der Einstellungen (Seed). Geldwerte in Cent. Leer heißt: noch nicht festgelegt.
DEFAULT_SETTINGS = {
    "anfahrt_frei_km": "10",          # die ersten 10 km ab Emden frei
    "anfahrt_cent_je_km": "30",       # danach 0,30 € je km
    "lieferfrist_tage": "5",          # Galerie spätestens 5 Tage nach dem Spiel
    "picdrop_tage": "30",             # Picdrop-Link läuft nach 30 Tagen ab
    "umsatzgrenze_cent": "",          # OFFEN: Kleinunternehmergrenze, Wert von Silas (mit Steuerberatung abgleichen)
    "twofa_pflicht": "1",             # Zwei-Faktor-Anmeldung ist Pflicht (Entscheidung von Silas)
}

# Startpakete (Seed), Preise in Cent. Finom-Leistungstext bleibt leer, bis Silas ihn einträgt.
SEED_PAKETE = (
    {"name": "Basic", "grundpreis_cent": 3000, "inkl_spieler": 0, "zusatzspieler_cent": 0, "sort": 1},
    {"name": "Pro", "grundpreis_cent": 4500, "inkl_spieler": 0, "zusatzspieler_cent": 0, "sort": 2},
    {"name": "Spielershooting", "grundpreis_cent": 6000, "inkl_spieler": 25, "zusatzspieler_cent": 90, "sort": 3},
    {"name": "Saisonspiel HSG Emden", "grundpreis_cent": 3500, "inkl_spieler": 0, "zusatzspieler_cent": 0, "sort": 4},
)

DB_LOCK = threading.RLock()


def now_iso():
    return datetime.now(TZ).isoformat(timespec="seconds")


@contextlib.contextmanager
def db():
    """Verbindung öffnen, am Ende committen (bzw. bei Fehler zurückrollen) und schließen."""
    with DB_LOCK:
        conn = sqlite3.connect(DB_PATH, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 15000")
        try:
            with conn:
                yield conn
        finally:
            conn.close()


def init_db():
    DATA.mkdir(parents=True, exist_ok=True)
    UPLOADS.mkdir(exist_ok=True)
    BACKUPS.mkdir(exist_ok=True)
    with db() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        # Interne Tabellen: bewusst NICHT in TABLES, damit sie nie über eine allgemeine API erreichbar sind
        conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE COLLATE NOCASE, "
                     "pw_hash TEXT, display_name TEXT, active INTEGER DEFAULT 1, fail_count INTEGER DEFAULT 0, fail_first REAL, "
                     "locked_until REAL, created_at TEXT, last_login TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id INTEGER REFERENCES users(id), "
                     "expires REAL, created_at TEXT, ip TEXT, user_agent TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS user_2fa (user_id INTEGER PRIMARY KEY REFERENCES users(id), secret TEXT, "
                     "enabled INTEGER DEFAULT 0, pending_secret TEXT, pending_expires REAL, last_step INTEGER DEFAULT 0, "
                     "recovery TEXT, enabled_at TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS secrets (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT, user_id INTEGER, "
                     "user_name TEXT, action TEXT, table_name TEXT, record_id INTEGER, label TEXT, details TEXT)")
        for table, cols in TABLES.items():
            conn.execute(f"CREATE TABLE IF NOT EXISTS {table} (id INTEGER PRIMARY KEY AUTOINCREMENT)")
            have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            for col, typ in cols.items():
                if col not in have:
                    # NOT NULL ohne Default lässt sich nicht nachträglich anfügen
                    add = typ.replace("NOT NULL", "") if "DEFAULT" not in typ else typ
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {add}")
        for sql in INDEXES:
            conn.execute(sql)
        seed(conn)
        # Aufträge ohne Zahlung (angelegt vor Phase 3) bekommen ihre offene Zahlung
        for r in conn.execute("SELECT id FROM auftraege WHERE id NOT IN "
                              "(SELECT auftrag_id FROM zahlungen WHERE art='Zahlung' AND auftrag_id IS NOT NULL)").fetchall():
            zahlung_sync(conn, r["id"])


def seed(conn):
    """Startdaten: Einstellungen und Pakete. Läuft bei jedem Start, ändert aber nie vorhandene Werte."""
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
    if not conn.execute("SELECT 1 FROM settings WHERE key='seed_pakete'").fetchone():
        if not conn.execute("SELECT COUNT(*) FROM pakete").fetchone()[0]:
            for p in SEED_PAKETE:
                conn.execute("INSERT INTO pakete (name, grundpreis_cent, inkl_spieler, zusatzspieler_cent, finom_text, aktiv, sort) "
                             "VALUES (?, ?, ?, ?, '', 1, ?)",
                             (p["name"], p["grundpreis_cent"], p["inkl_spieler"], p["zusatzspieler_cent"], p["sort"]))
        conn.execute("INSERT INTO settings (key, value) VALUES ('seed_pakete', ?)", (now_iso(),))
    if not conn.execute("SELECT 1 FROM settings WHERE key='seed_vorlagen'").fetchone():
        if not conn.execute("SELECT COUNT(*) FROM vorlagen").fetchone()[0]:
            conn.execute("INSERT INTO vorlagen (name, text, sort) VALUES (?, ?, 1)", ("Galerie ist online (Beispiel, bitte anpassen)",
                         "Hallo {name},\n\ndie Bilder vom Spiel {spiel} am {datum} sind online:\n{link}\n\n"
                         "Der Link ist bis {ablauf} gültig.\n\nViele Grüße"))
        conn.execute("INSERT INTO settings (key, value) VALUES ('seed_vorlagen', ?)", (now_iso(),))


def row_dict(r):
    return {k: r[k] for k in r.keys()}


def get_setting(conn, key):
    r = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r["value"] if r else DEFAULT_SETTINGS.get(key, "")


def set_setting(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))


def secret_get(conn, key):
    r = conn.execute("SELECT value FROM secrets WHERE key=?", (key,)).fetchone()
    return r["value"] if r and r["value"] is not None else ""


def secret_set(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO secrets (key, value) VALUES (?, ?)", (key, value))


def audit(conn, user, action, table="", rid=None, label="", details=None):
    """user: angemeldeter Benutzer (dict) oder ein Name wie „System“ für Aktionen ohne Login."""
    if isinstance(user, dict):
        uid, name = user.get("id"), user.get("display_name") or user.get("username") or "?"
    else:
        uid, name = None, user or "System"
    conn.execute("INSERT INTO audit_log (time, user_id, user_name, action, table_name, record_id, label, details) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (now_iso(), uid, name, action, table, rid, (label or "")[:120],
                  json.dumps(details, ensure_ascii=False)[:6000] if details else ""))


# ---------------------------------------------------------------------------
# Anzeige-Hilfen (Euro, Datum TT.MM.JJJJ)
# ---------------------------------------------------------------------------
def eur_text(cent):
    """2 -> '0,02 €', 672000 -> '6.720,00 €'"""
    cent = int(cent or 0)
    sign = "-" if cent < 0 else ""
    euro, rest = divmod(abs(cent), 100)
    return f"{sign}{euro:,}".replace(",", ".") + f",{rest:02d} €"


def datum_text(iso):
    """'2026-11-01' -> '01.11.2026', ungültig -> ''"""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", iso or "")
    return f"{m.group(3)}.{m.group(2)}.{m.group(1)}" if m else ""


# ---------------------------------------------------------------------------
# Benutzer, Passwörter, Sitzungen (wie im Hub)
# ---------------------------------------------------------------------------
def hash_pw(pw):
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${h.hex()}"


def check_pw(pw, stored):
    try:
        algo, salt, h = (stored or "").split("$")
        if algo != "scrypt":
            return False
        calc = hashlib.scrypt(pw.encode("utf-8"), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(calc.hex(), h)
    except Exception:  # noqa
        return False


def pw_problem(pw):
    if len(pw or "") < 10:
        return "Das Passwort muss mindestens 10 Zeichen lang sein."
    return ""


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def check_username(username):
    username = (username or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._@-]{2,40}", username):
        raise ValueError("Benutzername: 2 bis 40 Zeichen, nur Buchstaben, Zahlen und . _ - @")
    return username


def user_count():
    with db() as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def create_user(username, password, display_name=""):
    username = check_username(username)
    prob = pw_problem(password)
    if prob:
        raise ValueError(prob)
    with db() as conn:
        if conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            raise ValueError("Diesen Benutzernamen gibt es schon.")
        uid = conn.execute("INSERT INTO users (username, pw_hash, display_name, active, created_at) VALUES (?, ?, ?, 1, ?)",
                           (username, hash_pw(password), display_name or username, now_iso())).lastrowid
        audit(conn, "System", "Konto angelegt", "users", uid, username)
    return uid


def set_password(username, password):
    prob = pw_problem(password)
    if prob:
        raise ValueError(prob)
    with db() as conn:
        row = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        if not row:
            raise ValueError("Diesen Benutzer gibt es nicht.")
        conn.execute("UPDATE users SET pw_hash=?, active=1, fail_count=0, locked_until=NULL WHERE id=?", (hash_pw(password), row["id"]))
        conn.execute("DELETE FROM sessions WHERE user_id=?", (row["id"],))
        audit(conn, "System", "Passwort gesetzt", "users", row["id"], username)


def bootstrap_admin():
    user = (ENV("STUDIO_ADMIN_USER") or "").strip()
    pw = ENV("STUDIO_ADMIN_PASSWORD") or ""
    if not user or not pw:
        return
    try:
        with db() as conn:
            exists = conn.execute("SELECT 1 FROM users WHERE username=?", (user,)).fetchone()
            count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if exists and ENV("STUDIO_RESET_PASSWORD") == "1":
            set_password(user, pw)
            print(f"Passwort für {user} wurde zurückgesetzt. STUDIO_RESET_PASSWORD wieder auf 0 stellen.")
        elif not count:
            create_user(user, pw)
            print(f"Admin-Benutzer {user} wurde angelegt.")
    except ValueError as e:
        print("Admin-Benutzer konnte nicht angelegt werden:", e)


# Sperren: 5 Fehlversuche je Konto -> 15 Minuten gesperrt. Zusätzlich je IP höchstens 20 Fehlversuche in 15 Minuten.
# Unbekannte Benutzernamen werden genauso gezählt, damit die Antwort nichts über vorhandene Konten verrät.
ACCOUNT_FAIL_MAX = 5
ACCOUNT_LOCK_MINUTES = 15
IP_FAIL_MAX = 20
FAILED_LOCK = threading.Lock()
FAILED_IPS = {}           # IP -> [Zeitpunkte]
GHOST_FAILS = {}          # unbekannter Benutzername (klein) -> [Anzahl, erster Fehlversuch, gesperrt bis]
DUMMY_PW_HASH = None


def dummy_check_pw(pw):
    """Gleiche Rechenzeit für unbekannte Benutzernamen."""
    global DUMMY_PW_HASH
    if DUMMY_PW_HASH is None:
        DUMMY_PW_HASH = hash_pw(secrets.token_hex(8))
    check_pw(pw, DUMMY_PW_HASH)


def ip_blocked(ip):
    with FAILED_LOCK:
        now = time.time()
        hits = [t for t in FAILED_IPS.get(ip, []) if now - t < ACCOUNT_LOCK_MINUTES * 60]
        FAILED_IPS[ip] = hits
        return len(hits) >= IP_FAIL_MAX


def ip_failed(ip):
    with FAILED_LOCK:
        FAILED_IPS.setdefault(ip, []).append(time.time())


def account_locked(u, username):
    now = time.time()
    if u is None:
        with FAILED_LOCK:
            g = GHOST_FAILS.get((username or "").lower())
            return bool(g and g[2] > now)
    return bool(u["locked_until"] and u["locked_until"] > now)


def account_failed(conn, u, username):
    """Fehlversuch zählen, beim Erreichen der Grenze sperren. Gibt True zurück, wenn jetzt gesperrt."""
    now = time.time()
    window = ACCOUNT_LOCK_MINUTES * 60
    if u is None:
        with FAILED_LOCK:
            if len(GHOST_FAILS) > 5000:
                GHOST_FAILS.clear()
            key = (username or "").lower()
            g = GHOST_FAILS.get(key)
            if not g or now - g[1] > window:
                g = [0, now, 0]
            g[0] += 1
            if g[0] >= ACCOUNT_FAIL_MAX:
                g[2] = now + window
            GHOST_FAILS[key] = g
            return g[2] > now
    first = u["fail_first"] or 0
    count = (u["fail_count"] or 0) if now - first <= window else 0
    if not count:
        first = now
    count += 1
    locked = now + window if count >= ACCOUNT_FAIL_MAX else None
    conn.execute("UPDATE users SET fail_count=?, fail_first=?, locked_until=? WHERE id=?",
                 (0 if locked else count, first, locked, u["id"]))
    if locked:
        audit(conn, "Anmeldung", "Konto gesperrt", "users", u["id"], u["username"], {"Minuten": ACCOUNT_LOCK_MINUTES})
    return bool(locked)


def account_ok(conn, uid):
    conn.execute("UPDATE users SET fail_count=0, fail_first=NULL, locked_until=NULL WHERE id=?", (uid,))


# ---------------------------------------------------------------------------
# Zwei-Faktor-Anmeldung (TOTP nach RFC 6238, wie im Hub): Code aus einer Authenticator-App,
# dazu 10 Wiederherstellungscodes, die nur als Hash gespeichert werden.
# ---------------------------------------------------------------------------
TOTP_ISSUER = "Studio-Tool"
RECOVERY_COUNT = 10
RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
TWOFA_TICKET_MINUTES = 5
TWOFA_TICKETS = {}        # Hash des Zwischen-Tickets -> {"uid", "expires", "tries"} (Passwort stimmt, Code fehlt noch)


def totp_code(secret_b32, step, digits=6):
    key = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8), casefold=True)
    mac = hmac.new(key, step.to_bytes(8, "big"), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    return f"{(int.from_bytes(mac[off:off + 4], 'big') & 0x7FFFFFFF) % (10 ** digits):0{digits}d}"


def totp_match(secret_b32, code, last_step=0, now=None):
    """Passenden Zeitschritt zurückgeben (30 Sekunden Abweichung erlaubt), sonst 0. Schon benutzte Codes zählen nicht."""
    code = re.sub(r"\s", "", str(code or ""))
    if not re.fullmatch(r"\d{6}", code) or not secret_b32:
        return 0
    t = int((now if now is not None else time.time()) // 30)
    for step in (t - 1, t, t + 1):
        if step > (last_step or 0) and hmac.compare_digest(totp_code(secret_b32, step), code):
            return step
    return 0


def totp_uri(secret_b32, username):
    from urllib.parse import quote
    label = quote(f"{TOTP_ISSUER}:{username}")
    return f"otpauth://totp/{label}?secret={secret_b32}&issuer={quote(TOTP_ISSUER)}&algorithm=SHA1&digits=6&period=30"


def recovery_norm(code):
    return re.sub(r"[^a-z0-9]", "", str(code or "").lower())


def recovery_new():
    """Neue Codes (Klartext für die einmalige Anzeige) und ihre Hashes (zum Speichern)."""
    codes = []
    for _ in range(RECOVERY_COUNT):
        c = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(10))
        codes.append(f"{c[:5]}-{c[5:]}")
    return codes, [token_hash(recovery_norm(c)) for c in codes]


def twofa_row(conn, uid):
    return conn.execute("SELECT * FROM user_2fa WHERE user_id=?", (uid,)).fetchone()


def twofa_enabled(conn, uid):
    r = twofa_row(conn, uid)
    return bool(r and r["enabled"] and r["secret"])


def twofa_required(conn):
    return get_setting(conn, "twofa_pflicht") == "1"


def twofa_check(conn, uid, code):
    """Code aus der App oder Wiederherstellungscode prüfen. Rückgabe: "totp", "recovery" oder ""."""
    r = twofa_row(conn, uid)
    if not r or not r["enabled"]:
        return ""
    step = totp_match(r["secret"], code, r["last_step"] or 0)
    if step:
        conn.execute("UPDATE user_2fa SET last_step=? WHERE user_id=?", (step, uid))
        return "totp"
    norm = recovery_norm(code)
    if len(norm) == 10:
        hashes = json.loads(r["recovery"] or "[]")
        h = token_hash(norm)
        for x in hashes:
            if hmac.compare_digest(x, h):
                hashes.remove(x)
                conn.execute("UPDATE user_2fa SET recovery=? WHERE user_id=?", (json.dumps(hashes), uid))
                return "recovery"
    return ""


def twofa_ticket_new(uid):
    tok = secrets.token_urlsafe(32)
    with FAILED_LOCK:
        now = time.time()
        for k in [k for k, v in TWOFA_TICKETS.items() if v["expires"] < now]:
            TWOFA_TICKETS.pop(k, None)
        TWOFA_TICKETS[token_hash(tok)] = {"uid": uid, "expires": now + TWOFA_TICKET_MINUTES * 60, "tries": 0}
    return tok


def twofa_reset(username):
    with db() as conn:
        row = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        if not row:
            raise ValueError("Diesen Benutzer gibt es nicht.")
        conn.execute("DELETE FROM user_2fa WHERE user_id=?", (row["id"],))
        conn.execute("DELETE FROM sessions WHERE user_id=?", (row["id"],))
        audit(conn, "System", "Zwei-Faktor-Anmeldung zurückgesetzt", "users", row["id"], username)


# ---------------------------------------------------------------------------
# Phase 2: Kunden, Kontakte, Pakete, Aufträge (allgemeine Tabellen-Schnittstelle wie api_table im Hub)
# ---------------------------------------------------------------------------
API_TABLES = ("kunden", "kontakte", "pakete", "auftraege", "zahlungen", "lieferlinks", "vorlagen", "vertraege", "dokumente")
ORDER = {"kunden": "name COLLATE NOCASE, id", "kontakte": "name COLLATE NOCASE, id", "pakete": "sort, id",
         "auftraege": "datum, uhrzeit, id", "zahlungen": "auftrag_id, art = 'Zahlung', id",
         "lieferlinks": "auftrag_id, erstellt_am, id", "vorlagen": "sort, id", "vertraege": "beginn, id",
         "dokumente": "hochgeladen_am DESC, id"}
# Diese Felder setzt nur der Server (Preise, Fristen, Zeitstempel)
SERVER_FIELDS = {
    "kunden": ("erstellt_am", "geaendert_am"),
    "kontakte": ("erstellt_am", "geaendert_am", "anonymisiert"),
    "zahlungen": ("erstellt_am", "geaendert_am"),
    "lieferlinks": ("erstellt_am",),
    "vertraege": ("erstellt_am", "geaendert_am", "datei", "datei_name"),
    "dokumente": ("hochgeladen_am", "datei", "datei_name", "groesse"),
    "auftraege": ("erstellt_am", "geaendert_am", "serie", "grundpreis_cent", "inkl_spieler", "zusatz_je_spieler_cent",
                  "anfahrt_frei_km", "anfahrt_cent_je_km", "zusatzspieler_cent", "anfahrt_cent", "lieferfrist"),
}
AUDIT_SKIP = ("erstellt_am", "geaendert_am")
EDITABLE_SETTINGS = ("anfahrt_frei_km", "anfahrt_cent_je_km", "lieferfrist_tage", "picdrop_tage", "umsatzgrenze_cent")


class BadRequest(Exception):
    pass


def preis(grund, inkl, je_spieler, spieler, km, frei_km, cent_je_km):
    """Preis in Cent: (Zusatzspieler, Anfahrt, Summe). inkl = 0 heißt: Paket ohne Spielerstaffel.
    km ist die einfache Strecke ab Emden, berechnet wird nur, was über frei_km liegt."""
    zusatz = max(0, spieler - inkl) * je_spieler if inkl else 0
    anfahrt = max(0, km - frei_km) * cent_je_km
    return zusatz, anfahrt, grund + zusatz + anfahrt


def clean_values(table, data):
    """Nur bekannte Spalten, Zahlen als ganze Zahl ab 0, Texte gekürzt."""
    cols = TABLES[table]
    out = {}
    for k, v in data.items():
        if k not in cols:
            continue
        if "INTEGER" in cols[k]:
            if v in ("", None):
                v = None
            else:
                try:
                    v = int(v) if not isinstance(v, float) or v.is_integer() else None
                except (TypeError, ValueError):
                    v = None
                if v is None or not 0 <= v < 10 ** 9:
                    raise BadRequest(f"{k}: bitte eine ganze Zahl ab 0 eingeben.")
        else:
            v = None if v is None else str(v).strip()[:10000 if k == "notizen" else 500]
        out[k] = v
    return out


def check_row(conn, table, row):
    """Pflichtfelder und erlaubte Werte. Ungültige Verweise fängt die Datenbank ab (foreign_keys)."""
    if table in ("kunden", "kontakte", "pakete") and not row.get("name"):
        raise BadRequest("Bitte einen Namen eingeben.")
    if table == "kunden":
        if row.get("typ") not in KUNDEN_TYPEN:
            raise BadRequest("Unbekannter Kundentyp.")
        if row.get("parent_id"):
            parent = conn.execute("SELECT parent_id FROM kunden WHERE id=?", (row["parent_id"],)).fetchone()
            # nur eine Ebene (Sparte gehört zu Verein), damit kein Kreis entstehen kann
            if not parent or parent["parent_id"] or row["parent_id"] == row.get("id"):
                raise BadRequest("Der übergeordnete Kunde passt nicht (er darf selbst keinem Kunden untergeordnet sein).")
            if row.get("id") and conn.execute("SELECT 1 FROM kunden WHERE parent_id=?", (row["id"],)).fetchone():
                raise BadRequest("Diesem Kunden sind schon andere untergeordnet, er kann selbst nicht untergeordnet werden.")
    if table == "kontakte" and not row.get("kunde_id"):
        raise BadRequest("Der Kontakt braucht einen Kunden.")
    if table == "auftraege":
        if not row.get("kunde_id") or not row.get("paket_id"):
            raise BadRequest("Bitte Kunde und Paket wählen.")
        try:
            date.fromisoformat(row.get("datum") or "")
        except ValueError:
            raise BadRequest("Bitte ein gültiges Datum eingeben.")
        if row.get("uhrzeit") and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", row["uhrzeit"]):
            raise BadRequest("Uhrzeit bitte als HH:MM.")
        if row.get("status") not in STATUS_AUFTRAG:
            raise BadRequest("Unbekannter Status.")
    if table == "zahlungen":
        if row.get("status") not in STATUS_ZAHLUNG:
            raise BadRequest("Unbekannter Zahlstatus.")
        if row.get("zahlart") and row["zahlart"] not in ZAHLARTEN:
            raise BadRequest("Unbekannte Zahlart.")
        if row.get("zahldatum"):
            try:
                date.fromisoformat(row["zahldatum"])
            except ValueError:
                raise BadRequest("Bitte ein gültiges Zahldatum eingeben.")
        if row.get("art") == "Anzahlung":
            a = conn.execute("SELECT betrag_cent FROM auftraege WHERE id=?", (row.get("auftrag_id"),)).fetchone()
            if not row.get("betrag_cent"):
                raise BadRequest("Bitte den Betrag der Anzahlung eingeben.")
            if a and row["betrag_cent"] > (a["betrag_cent"] or 0):
                raise BadRequest("Die Anzahlung ist höher als der Betrag des Auftrags.")
    if table == "lieferlinks":
        if not row.get("auftrag_id"):
            raise BadRequest("Der Link braucht einen Auftrag.")
        # nur https: verhindert javascript:-Links und unverschlüsselte Galerien
        if not re.fullmatch(r"https://[^\s<>\"']{3,490}", row.get("url") or ""):
            raise BadRequest("Bitte den vollständigen Link eingeben, er muss mit https:// beginnen.")
        if row.get("typ") not in LINK_TYPEN:
            raise BadRequest("Unbekannter Link-Typ.")
        if row.get("laeuft_ab_am"):
            try:
                date.fromisoformat(row["laeuft_ab_am"])
            except ValueError:
                raise BadRequest("Bitte ein gültiges Ablaufdatum eingeben.")
    if table == "vorlagen" and (not row.get("name") or not row.get("text")):
        raise BadRequest("Bitte Name und Text der Vorlage eingeben.")
    if table == "vertraege":
        if not row.get("kunde_id"):
            raise BadRequest("Der Vertrag braucht einen Kunden.")
        if row.get("art") not in VERTRAG_ARTEN:
            raise BadRequest("Bitte die Art des Vertrags wählen.")
        for k, name in (("beginn", "Beginn"), ("ende", "Ende")):
            if row.get(k) or k == "beginn":
                try:
                    date.fromisoformat(row.get(k) or "")
                except ValueError:
                    raise BadRequest(f"Bitte ein gültiges Datum für {name} eingeben.")
        if row.get("ende") and row["ende"] < row["beginn"]:
            raise BadRequest("Das Ende liegt vor dem Beginn.")
        if (row.get("kuendigungsfrist_einheit") or "Monate") not in FRIST_EINHEITEN:
            raise BadRequest("Unbekannte Einheit der Kündigungsfrist.")
    if table == "dokumente" and (not row.get("kunde_id") or not row.get("titel")):
        raise BadRequest("Bitte Kunde und Titel eingeben.")


FRIST_EINHEITEN = ("Tage", "Wochen", "Monate")


def plus_monate(d, n):
    """Monate addieren, am Monatsende abgeschnitten: 31.07. minus 3 Monate = 30.04."""
    y, m = divmod(d.month - 1 + n, 12)
    y += d.year
    return date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1]))


def vertragsfristen(v, tag):
    """Aktuelles Laufzeitende und "spätestens kündigen bis" am Tag tag (JJJJ-MM-TT).
    Ende: eingetragenes Ende, sonst Beginn plus Mindestlaufzeit minus 1 Tag. Verlängert sich der Vertrag und ist die
    Kündigungsfrist der laufenden Periode schon vorbei, zählt die nächste Periode. Ohne Gewähr, maßgeblich ist der Vertrag."""
    try:
        beginn = date.fromisoformat(v.get("beginn") or "")
    except ValueError:
        return {"laufzeit_ende": None, "kuendigen_bis": None, "vertrag_status": "unvollständig"}
    t = date.fromisoformat(tag)
    if v.get("ende"):
        ende = date.fromisoformat(v["ende"])
    elif v.get("mindestlaufzeit_monate"):
        ende = plus_monate(beginn, v["mindestlaufzeit_monate"]) - timedelta(days=1)
    else:
        return {"laufzeit_ende": None, "kuendigen_bis": None, "vertrag_status": "unbefristet"}
    verl = v.get("verlaengerung_monate") or 0
    n, einheit = v.get("kuendigungsfrist_wert") or 0, v.get("kuendigungsfrist_einheit") or "Monate"

    def frist(e):
        if not n:
            return None
        if einheit == "Monate":
            return plus_monate(e, -n)
        return e - timedelta(days=n * (7 if einheit == "Wochen" else 1))

    for _ in range(600):   # höchstens 600 Verlängerungen, schützt vor Endlosschleifen bei kaputten Daten
        kb = frist(ende)
        if not verl or (kb or ende) >= t:
            break
        ende = plus_monate(ende + timedelta(days=1), verl) - timedelta(days=1)
    status = "beendet" if not verl and ende < t else ("verlängert sich" if verl else "endet")
    return {"laufzeit_ende": ende.isoformat(), "kuendigen_bis": kb.isoformat() if kb else None, "vertrag_status": status}


def mit_fristen(rows):
    tag = heute()
    for d in rows:
        d.update(vertragsfristen(d, tag))
    return rows


# Uploads: nur erlaubte Dateitypen, am Inhalt geprüft, unter zufälligem Namen in data/uploads, nie öffentlich
DATEI_TABELLEN = {"vertraege": ("pdf",), "dokumente": ("pdf",)}
DATEI_ARTEN = {"pdf": (b"%PDF-", ".pdf", "application/pdf"), "jpg": (b"\xff\xd8\xff", ".jpg", "image/jpeg"),
               "png": (b"\x89PNG\r\n\x1a\n", ".png", "image/png")}
DATEI_MAX = 15 * 1024 * 1024


def datei_speichern(raw_b64, name, erlaubt):
    """Data-URL prüfen und speichern. Rückgabe: (Dateiname auf der Platte, Anzeigename, Größe)."""
    m = re.match(r"^data:[\w/+.-]*;base64,(.*)$", raw_b64 or "", re.S)
    if not m:
        raise BadRequest("Ungültige Datei.")
    try:
        data = base64.b64decode(m.group(1), validate=True)
    except ValueError:
        raise BadRequest("Ungültige Datei.")
    if len(data) > DATEI_MAX:
        raise BadRequest(f"Die Datei ist größer als {DATEI_MAX // 1024 // 1024} MB.")
    art = next((k for k in erlaubt if data.startswith(DATEI_ARTEN[k][0])), None)
    if not art:
        raise BadRequest("Erlaubt sind nur " + ", ".join(k.upper() for k in erlaubt) + " Dateien.")
    fname = secrets.token_hex(16) + DATEI_ARTEN[art][1]
    (UPLOADS / fname).write_bytes(data)
    anzeige = re.sub(r"[\x00-\x1f/\\]", "", Path(str(name or "")).name).strip()[:120] or "datei" + DATEI_ARTEN[art][1]
    return fname, anzeige, len(data)


def datei_loeschen(fname):
    if fname and re.fullmatch(r"[0-9a-f]{32}\.[a-z]{3}", fname):
        (UPLOADS / fname).unlink(missing_ok=True)


def lieferlink_vorbereiten(conn, vals, old):
    """Der Auftrag eines Links steht fest. Picdrop-Links bekommen ohne Datum den Ablauf nach der Picdrop-Laufzeit."""
    if old:
        vals.pop("auftrag_id", None)
        return
    vals["typ"] = vals.get("typ") or "Picdrop"
    if vals["typ"] == "Picdrop" and not vals.get("laeuft_ab_am"):
        tage = int(get_setting(conn, "picdrop_tage") or 0)
        vals["laeuft_ab_am"] = (date.fromisoformat(heute()) + timedelta(days=tage)).isoformat()


def lieferampel(a, hat_link, tag):
    """Lieferfrist-Ampel eines Auftrags am Tag tag (JJJJ-MM-TT):
    gruen = geliefert (Link da oder Status Geliefert/Abgeschlossen), rot = Frist vorbei, gelb = Spiel war, Frist läuft,
    keine = abgesagt, Spiel noch nicht gewesen oder keine Frist."""
    if a["status"] == "Abgesagt":
        return "keine"
    if hat_link or a["status"] in ("Geliefert", "Abgeschlossen"):
        return "gruen"
    if not a.get("lieferfrist") or not a.get("datum") or tag < a["datum"]:
        return "keine"
    return "rot" if tag > a["lieferfrist"] else "gelb"


def mit_ampel(conn, rows):
    mit_link = {r[0] for r in conn.execute("SELECT DISTINCT auftrag_id FROM lieferlinks")}
    tag = heute()
    for d in rows:
        d["ampel"] = lieferampel(d, d["id"] in mit_link, tag)
    return rows


def lieferung_uebersicht(conn, tag):
    """Für die Seite Bildauslieferung: fällige und überfällige Aufträge, bald ablaufende und abgelaufene Links."""
    kunden = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM kunden")}
    auftraege = mit_ampel(conn, [row_dict(r) for r in conn.execute(
        "SELECT * FROM auftraege WHERE IFNULL(archiviert, 0)=0 ORDER BY lieferfrist, id")])
    for a in auftraege:
        a["kunde"] = kunden.get(a["kunde_id"], "")
    t = date.fromisoformat(tag)
    bald, vorbei = (t + timedelta(days=7)).isoformat(), (t - timedelta(days=30)).isoformat()
    links = [row_dict(r) for r in conn.execute(
        "SELECT l.*, a.begegnung, a.datum, a.kunde_id FROM lieferlinks l JOIN auftraege a ON a.id = l.auftrag_id "
        "WHERE l.laeuft_ab_am != '' AND l.laeuft_ab_am >= ? AND l.laeuft_ab_am <= ? ORDER BY l.laeuft_ab_am", (vorbei, bald))]
    for l in links:
        l["kunde"] = kunden.get(l["kunde_id"], "")
    return {"heute": tag,
            "ueberfaellig": [a for a in auftraege if a["ampel"] == "rot"],
            "faellig": [a for a in auftraege if a["ampel"] == "gelb"],
            "laeuft_ab": [l for l in links if l["laeuft_ab_am"] >= tag],
            "abgelaufen": [l for l in links if l["laeuft_ab_am"] < tag]}


def heute():
    return datetime.now(TZ).date().isoformat()


def zahlung_vorbereiten(conn, vals, old):
    """Regeln für Zahlungen: Art und Auftrag stehen fest, der Betrag der Zahlung kommt aus dem Auftrag (abzüglich Anzahlung).
    Neu angelegt werden kann nur die Anzahlung, die Zahlung selbst entsteht mit dem Auftrag."""
    if old:
        vals.pop("auftrag_id", None)
        vals.pop("art", None)
        if old["art"] == "Zahlung":
            vals.pop("betrag_cent", None)
    else:
        if vals.get("art") != "Anzahlung":
            raise BadRequest("Neu anlegen lässt sich nur eine Anzahlung. Die Zahlung entsteht mit dem Auftrag.")
        if conn.execute("SELECT 1 FROM zahlungen WHERE auftrag_id=? AND art='Anzahlung'", (vals.get("auftrag_id"),)).fetchone():
            raise BadRequest("Dieser Auftrag hat schon eine Anzahlung.")
        vals.setdefault("status", "Offen")
        vals["status"] = vals["status"] or "Offen"
    status = vals.get("status", old["status"] if old else "Offen")
    if status == "Bezahlt" and not vals.get("zahldatum", old["zahldatum"] if old else None):
        vals["zahldatum"] = heute()   # Umsatz zählt nach Zahldatum, deshalb nie bezahlt ohne Datum


def zahlung_sync(conn, auftrag_id):
    """Die Zahlung eines Auftrags anlegen oder ihren Betrag nachziehen (Auftragsbetrag minus Anzahlung).
    Nur solange sie offen ist: Bezahlte oder erlassene Beträge bleiben, wie sie sind."""
    a = conn.execute("SELECT betrag_cent FROM auftraege WHERE id=?", (auftrag_id,)).fetchone()
    if not a:
        return
    anz = conn.execute("SELECT betrag_cent FROM zahlungen WHERE auftrag_id=? AND art='Anzahlung'", (auftrag_id,)).fetchone()
    soll = max(0, (a["betrag_cent"] or 0) - ((anz["betrag_cent"] or 0) if anz else 0))
    z = conn.execute("SELECT id, status, betrag_cent FROM zahlungen WHERE auftrag_id=? AND art='Zahlung'", (auftrag_id,)).fetchone()
    if not z:
        conn.execute("INSERT INTO zahlungen (auftrag_id, art, betrag_cent, status, finom_abgerechnet, erstellt_am, geaendert_am) "
                     "VALUES (?, 'Zahlung', ?, 'Offen', 0, ?, ?)", (auftrag_id, soll, now_iso(), now_iso()))
    elif z["status"] == "Offen" and z["betrag_cent"] != soll:
        conn.execute("UPDATE zahlungen SET betrag_cent=?, geaendert_am=? WHERE id=?", (soll, now_iso(), z["id"]))


def umsatz(conn, jahr):
    """Umsatz eines Jahres in Cent nach Zahldatum: je Monat und je Kunde. Zählt nur bezahlte Zahlungen."""
    monate = [0] * 12
    kunden = {}
    for r in conn.execute("SELECT z.betrag_cent, z.zahldatum, k.name FROM zahlungen z JOIN auftraege a ON a.id = z.auftrag_id "
                          "LEFT JOIN kunden k ON k.id = a.kunde_id WHERE z.status='Bezahlt' AND substr(z.zahldatum, 1, 4)=?",
                          (str(jahr),)):
        monate[int(r["zahldatum"][5:7]) - 1] += r["betrag_cent"] or 0
        kunden[r["name"] or "ohne Kunde"] = kunden.get(r["name"] or "ohne Kunde", 0) + (r["betrag_cent"] or 0)
    offen = conn.execute("SELECT COALESCE(SUM(z.betrag_cent), 0) FROM zahlungen z JOIN auftraege a ON a.id = z.auftrag_id "
                         "WHERE z.status='Offen' AND a.status != 'Abgesagt'").fetchone()[0]
    jahre = sorted({r[0] for r in conn.execute("SELECT DISTINCT substr(zahldatum, 1, 4) FROM zahlungen "
                                                "WHERE status='Bezahlt' AND zahldatum != ''")} | {str(jahr), heute()[:4]}, reverse=True)
    grenze = get_setting(conn, "umsatzgrenze_cent")
    return {"jahr": int(jahr), "monate": monate, "summe": sum(monate), "offen": offen, "jahre": [int(j) for j in jahre],
            "kunden": sorted(([k, v] for k, v in kunden.items()), key=lambda x: -x[1]),
            "grenze": int(grenze) if grenze else None}


def leistungstext(a, paket, z, anzahlung_cent):
    """Kopierfertiger Text für die Rechnung in Finom. Mit von Hand festgelegtem Betrag ohne Aufschlüsselung,
    weil die Einzelposten dann nicht zur Summe passen."""
    titel = (paket["finom_text"] if paket else "") or (paket["name"] if paket else "") or "Fotografie"
    kopf = ", ".join(x for x in (a["begegnung"], datum_text(a["datum"])) if x)
    zeile = f"{titel}: {kopf}" if kopf else titel
    if z["art"] == "Anzahlung":
        return f"Anzahlung für {zeile}\nBetrag: {eur_text(z['betrag_cent'])}"
    zeilen = [zeile]
    if not a["betrag_manuell"]:
        if a["zusatzspieler_cent"]:
            n = max(0, (a["spieler"] or 0) - (a["inkl_spieler"] or 0))
            zeilen.append(f"Zusatzspieler: {n} × {eur_text(a['zusatz_je_spieler_cent'])} = {eur_text(a['zusatzspieler_cent'])}")
        if a["anfahrt_cent"]:
            km = max(0, (a["km"] or 0) - (a["anfahrt_frei_km"] or 0))
            zeilen.append(f"Anfahrt: {km} km × {eur_text(a['anfahrt_cent_je_km'])} = {eur_text(a['anfahrt_cent'])}")
    if anzahlung_cent:
        zeilen.append(f"abzüglich Anzahlung: {eur_text(anzahlung_cent)}")
    zeilen.append(f"Betrag: {eur_text(z['betrag_cent'])}")
    return "\n".join(zeilen)


def abrechnen(conn):
    """Bezahlte Zahlungen ohne Finom-Häkchen, mit Leistungstext."""
    out = []
    for z in conn.execute("SELECT * FROM zahlungen WHERE status='Bezahlt' AND IFNULL(finom_abgerechnet, 0)=0 "
                          "ORDER BY zahldatum, id").fetchall():
        a = conn.execute("SELECT * FROM auftraege WHERE id=?", (z["auftrag_id"],)).fetchone()
        paket = conn.execute("SELECT * FROM pakete WHERE id=?", (a["paket_id"],)).fetchone()
        kunde = conn.execute("SELECT name FROM kunden WHERE id=?", (a["kunde_id"],)).fetchone()
        zahler = conn.execute("SELECT name FROM kontakte WHERE id=?", (z["zahler_id"],)).fetchone() if z["zahler_id"] else None
        anz = conn.execute("SELECT betrag_cent FROM zahlungen WHERE auftrag_id=? AND art='Anzahlung'", (a["id"],)).fetchone()
        out.append({**row_dict(z), "kunde": kunde["name"] if kunde else "", "zahler": zahler["name"] if zahler else "",
                    "auftrag_datum": a["datum"], "begegnung": a["begegnung"] or "",
                    "text": leistungstext(a, paket, z, (anz["betrag_cent"] or 0) if anz and z["art"] == "Zahlung" else 0)})
    return out


def csv_zelle(v):
    """Schutz für Excel: Zellen, die mit = + - @ beginnen, würden sonst als Formel ausgeführt."""
    v = "" if v is None else str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


def umsatz_csv(conn, jahr):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(["Zahldatum", "Kunde", "Auftrag", "Datum Auftrag", "Art", "Zahler", "Zahlart", "Betrag", "Finom-Rechnung"])
    for r in conn.execute("SELECT z.*, a.begegnung, a.datum, k.name AS kunde, c.name AS zahler FROM zahlungen z "
                          "JOIN auftraege a ON a.id = z.auftrag_id LEFT JOIN kunden k ON k.id = a.kunde_id "
                          "LEFT JOIN kontakte c ON c.id = z.zahler_id WHERE z.status='Bezahlt' AND substr(z.zahldatum, 1, 4)=? "
                          "ORDER BY z.zahldatum, z.id", (str(jahr),)):
        w.writerow([csv_zelle(x) for x in (datum_text(r["zahldatum"]), r["kunde"], r["begegnung"], datum_text(r["datum"]), r["art"],
                                           r["zahler"], r["zahlart"], eur_text(r["betrag_cent"]).replace(" €", "").replace(".", ""),
                                           r["finom_rechnungsnr"])])
    return "\ufeff" + buf.getvalue()   # BOM, damit Excel die Umlaute erkennt


def auftrag_preise(conn, row, old):
    """Preisfelder eines Auftrags. Die Preise werden beim Anlegen festgeschrieben: spätere Änderungen an Kilometern
    oder Spielern rechnen mit den alten Preisen, nur ein Paketwechsel holt die aktuellen Preise des neuen Pakets."""
    out = {}
    if not old or old["paket_id"] != row["paket_id"]:
        p = conn.execute("SELECT * FROM pakete WHERE id=?", (row["paket_id"],)).fetchone()
        if not p:
            raise BadRequest("Dieses Paket gibt es nicht.")
        out.update(grundpreis_cent=p["grundpreis_cent"] or 0, inkl_spieler=p["inkl_spieler"] or 0,
                   zusatz_je_spieler_cent=p["zusatzspieler_cent"] or 0)
    if not old:
        out.update(anfahrt_frei_km=int(get_setting(conn, "anfahrt_frei_km") or 0),
                   anfahrt_cent_je_km=int(get_setting(conn, "anfahrt_cent_je_km") or 0))
    f = {**row, **out}
    zusatz, anfahrt, summe = preis(f["grundpreis_cent"] or 0, f["inkl_spieler"] or 0, f["zusatz_je_spieler_cent"] or 0,
                                   f.get("spieler") or 0, f.get("km") or 0, f["anfahrt_frei_km"] or 0, f["anfahrt_cent_je_km"] or 0)
    out.update(zusatzspieler_cent=zusatz, anfahrt_cent=anfahrt, berechnet_cent=summe,
               betrag_cent=(row.get("betrag_cent") or 0) if row.get("betrag_manuell") else summe)
    return out


def vals_id(data):
    v = data.get("id")
    return v if isinstance(v, int) and not isinstance(v, bool) else 0


# ---------------------------------------------------------------------------
# Sicherung (wie db_snapshot und daily_backup im Hub): jede Nacht eine konsistente Kopie der Datenbank nach data/backups
# shortcut: nur die Datenbank und nur auf derselben Platte. Uploads (ab Phase 5) und die Ablage außerhalb des Servers
# (rclone, Phase 6) kommen dazu, bevor echte Verträge hochgeladen werden.
# ---------------------------------------------------------------------------
BACKUP_KEEP_TAGE = 14
BACKUP_KEEP_MONATE = 6


def db_snapshot(target: Path):
    """Konsistente Kopie der Datenbank (auch während des Betriebs)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    with db() as src:
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
    os.replace(tmp, target)
    return target


def backup_behalten(namen):
    """Welche Sicherungen bleiben: die letzten 14 Tagesstände, dazu der erste Stand jedes der letzten 6 Monate."""
    namen = sorted(namen)
    monate = {}
    for n in namen:
        monate.setdefault(n[7:14], n)   # studio-JJJJ-MM-TT.db -> JJJJ-MM
    return set(namen[-BACKUP_KEEP_TAGE:]) | set(sorted(monate.values())[-BACKUP_KEEP_MONATE:])


def daily_backup(neu=False):
    """Sicherung von heute anlegen, falls es sie noch nicht gibt (neu=True: überschreiben), danach alte aufräumen."""
    name = BACKUPS / f"studio-{datetime.now(TZ):%Y-%m-%d}.db"
    if neu or not name.exists():
        db_snapshot(name)
    files = list(BACKUPS.glob("studio-????-??-??.db"))
    keep = backup_behalten(f.name for f in files)
    for f in files:
        if f.name not in keep:
            f.unlink(missing_ok=True)
    return name


def backup_loop():
    while True:
        try:
            daily_backup()
        except Exception as e:  # noqa
            print("Sicherung fehlgeschlagen:", e)
        threading.Event().wait(3600)


def backup_liste():
    files = sorted(BACKUPS.glob("studio-????-??-??.db"), reverse=True)
    return [{"name": f.name, "groesse": f.stat().st_size,
             "zeit": datetime.fromtimestamp(f.stat().st_mtime, TZ).isoformat(timespec="seconds")} for f in files]


def audit_label(table, r):
    if table == "auftraege":
        return f"{datum_text(r['datum'])} {r['begegnung'] or ''}".strip()
    if table == "zahlungen":
        return f"{r['art']} zu Auftrag {r['auftrag_id']}"
    if table == "lieferlinks":
        return f"{r['typ']}-Link zu Auftrag {r['auftrag_id']}"
    if table == "vertraege":
        return f"{r['art']} ab {datum_text(r['beginn'])}"
    keys = r.keys()
    return next((r[k] for k in ("name", "titel") if k in keys and r[k]), "")


class _Discard:
    """Bei HEAD-Anfragen: Inhalt verwerfen, Leeren und Schließen an die echte Verbindung weitergeben."""
    def __init__(self, real):
        self.real = real

    def write(self, data):
        return len(data)

    def __getattr__(self, name):
        return getattr(self.real, name)


class PayloadTooLarge(Exception):
    pass


# Öffentlich erreichbare Dateien (Anmeldeseite). Alles andere unter /static nur mit Sitzung.
PUBLIC_STATIC = {"style.css", "login.js", "icon.svg", "logo.png"}


class Handler(BaseHTTPRequestHandler):
    server_version = "StudioTool/" + VERSION
    sys_version = ""
    timeout = 60

    def log_message(self, fmt, *args):  # ruhige Konsole
        if "--verbose" in sys.argv:
            super().log_message(fmt, *args)

    # -- Antworten --------------------------------------------------------
    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        # Nur eigene Skripte, Stile und Bilder. Keine Inline-Skripte, keine fremden Quellen.
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                                                    "connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; "
                                                    "frame-ancestors 'none'")
        super().end_headers()
        if getattr(self, "head_only", False):   # HEAD: Kopfzeilen wie bei GET, aber ohne Inhalt
            self.wfile = _Discard(self.wfile)

    def send_json(self, obj, status=200, headers=None):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path):
        if not path.is_file():
            return self.send_error(404)
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if path.suffix == ".js":
            ctype = "text/javascript"
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def serve_under(self, root: Path, rest):
        target = (root / "/".join(rest)).resolve()
        if root.resolve() not in target.parents:
            return self.send_error(403)
        return self.send_file(target)

    def redirect(self, to, cookie=None):
        self.send_response(302)
        self.send_header("Location", to)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def read_json(self, limit=MAX_JSON):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise PayloadTooLarge()
        if length > limit or length < 0:
            raise PayloadTooLarge()
        raw = self.rfile.read(length) if length else b""
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            raise BadRequest("Ungültige Daten")
        if not isinstance(data, dict):
            raise BadRequest("Ungültige Daten")
        return data

    def parts(self):
        return [unquote(p) for p in urlparse(self.path).path.strip("/").split("/") if p]

    # -- Anfragende Person ------------------------------------------------
    def client_ip(self):
        if TRUST_PROXY:   # nur hinter Caddy: Caddy setzt X-Forwarded-For selbst
            fwd = self.headers.get("X-Forwarded-For", "")
            if fwd:
                return fwd.split(",")[0].strip()[:64]
        return self.client_address[0]

    def session_token(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                return v
        return ""

    def current_user(self):
        if hasattr(self, "_user"):
            return self._user
        self._user = None
        tok = self.session_token()
        if tok:
            with db() as conn:
                r = conn.execute("SELECT u.id, u.username, u.display_name, u.active, s.expires FROM sessions s "
                                 "JOIN users u ON u.id = s.user_id WHERE s.token_hash=?", (token_hash(tok),)).fetchone()
                if r and r["expires"] > time.time() and r["active"]:
                    on = twofa_enabled(conn, r["id"])
                    self._user = {"id": r["id"], "username": r["username"], "display_name": r["display_name"] or r["username"],
                                  "twofa": on, "must_2fa": not on and twofa_required(conn)}
                elif r:
                    conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(tok),))
        return self._user

    def cookie_header(self, value, max_age):
        parts = [f"{COOKIE}={value}", "Path=/", "HttpOnly", "SameSite=Lax", f"Max-Age={max_age}"]
        if SECURE_COOKIES:
            parts.append("Secure")
        return "; ".join(parts)

    def start_session(self, user_id):
        tok = secrets.token_urlsafe(32)
        with db() as conn:
            conn.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
            conn.execute("INSERT INTO sessions (token_hash, user_id, expires, created_at, ip, user_agent) VALUES (?, ?, ?, ?, ?, ?)",
                         (token_hash(tok), user_id, time.time() + SESSION_DAYS * 86400, now_iso(), self.client_ip(),
                          (self.headers.get("User-Agent") or "")[:200]))
            conn.execute("UPDATE users SET last_login=? WHERE id=?", (now_iso(), user_id))
        return tok

    # -- Routing ----------------------------------------------------------
    def do_GET(self):
        self.handle_request("GET")

    def do_HEAD(self):   # z. B. curl -I nach dem Deployment
        self.head_only = True
        self.handle_request("GET")

    def do_POST(self):
        self.handle_request("POST")

    def do_PUT(self):
        self.handle_request("PUT")

    def do_DELETE(self):
        self.handle_request("DELETE")

    def handle_request(self, method):
        try:
            self.route(method)
        except PayloadTooLarge:
            self.send_json({"error": "Anfrage zu groß"}, 413)
        except BadRequest as e:
            self.send_json({"error": str(e)}, 400)
        except sqlite3.IntegrityError:   # foreign_keys: Verweis ungültig oder es hängt noch etwas an dem Eintrag
            self.send_json({"error": "Das geht nicht: Der Eintrag wird noch verwendet oder verweist auf etwas, das es nicht gibt. "
                                     "Benutzte Einträge bitte archivieren statt löschen."}, 400)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def route(self, method):
        p = self.parts()
        head = p[0] if p else ""

        # ---- öffentlich ----
        if method == "GET" and p == ["healthz"]:
            return self.send_json({"ok": True, "version": VERSION})
        if method == "GET" and p == ["robots.txt"]:
            body = b"User-agent: *\nDisallow: /\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        if method == "GET" and head == "static" and len(p) == 2 and p[1] in PUBLIC_STATIC:
            return self.serve_under(STATIC, p[1:])
        if method == "GET" and p == ["favicon.ico"]:
            return self.serve_under(STATIC, ["icon.svg"])
        if method == "GET" and p == ["login"]:
            if self.current_user():
                return self.redirect("/")
            return self.send_file(STATIC / "login.html")
        if head == "auth":
            return self.api_auth(method, p[1:])

        # ---- ab hier nur mit Anmeldung ----
        user = self.current_user()
        if not user:
            if head == "api":
                return self.send_json({"error": "Nicht angemeldet"}, 401)
            return self.redirect("/login")
        if method != "GET" and self.headers.get(CSRF_HEADER) != "1":
            return self.send_json({"error": "Ungültige Anfrage"}, 403)

        if method == "GET" and not p:
            return self.send_file(STATIC / "index.html")
        if method == "GET" and head == "static" and len(p) >= 2:
            return self.serve_under(STATIC, p[1:])
        if head == "api":
            return self.api(method, p[1:], user)
        return self.send_error(404)

    # -- Anmeldung --------------------------------------------------------
    def api_auth(self, method, p):
        name = p[0] if p else ""
        if method != "POST" or self.headers.get(CSRF_HEADER) != "1":
            return self.send_json({"error": "Ungültige Anfrage"}, 403)
        if name == "login":
            ip = self.client_ip()
            locked_msg = f"Zu viele Fehlversuche. Bitte in {ACCOUNT_LOCK_MINUTES} Minuten erneut versuchen."
            if ip_blocked(ip):
                return self.send_json({"error": locked_msg}, 429)
            data = self.read_json()
            username = str(data.get("username") or "").strip()[:80]
            password = str(data.get("password") or "")[:200]
            with db() as conn:
                u = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
                if u and not u["active"]:
                    u = None
                if account_locked(u, username):
                    ip_failed(ip)
                    time.sleep(0.6)
                    return self.send_json({"error": locked_msg}, 429)
                if u:
                    ok = check_pw(password, u["pw_hash"])
                else:
                    dummy_check_pw(password)
                    ok = False
                need = False
                if ok:
                    need = twofa_enabled(conn, u["id"])
                    if not need:
                        account_ok(conn, u["id"])
                        audit(conn, {"id": u["id"], "display_name": u["display_name"]}, "Angemeldet", "users", u["id"],
                              u["username"], {"ip": ip})
                else:
                    ip_failed(ip)
                    locked = account_failed(conn, u, username)
            if not ok:
                time.sleep(0.6)
                return self.send_json({"error": locked_msg if locked else "Benutzername oder Passwort falsch."}, 429 if locked else 401)
            if need:   # Passwort stimmt, jetzt noch der Code aus der App (Sitzung erst danach)
                return self.send_json({"need_2fa": True, "ticket": twofa_ticket_new(u["id"])})
            tok = self.start_session(u["id"])
            return self.send_json({"ok": True}, headers={"Set-Cookie": self.cookie_header(tok, SESSION_DAYS * 86400)})
        if name == "login2":
            ip = self.client_ip()
            locked_msg = f"Zu viele Fehlversuche. Bitte in {ACCOUNT_LOCK_MINUTES} Minuten erneut versuchen."
            if ip_blocked(ip):
                return self.send_json({"error": locked_msg}, 429)
            data = self.read_json()
            th = token_hash(str(data.get("ticket") or ""))
            with FAILED_LOCK:
                t = TWOFA_TICKETS.get(th)
                if t and (t["expires"] < time.time() or t["tries"] >= ACCOUNT_FAIL_MAX):
                    TWOFA_TICKETS.pop(th, None)
                    t = None
            if not t:
                return self.send_json({"error": "Die Anmeldung ist abgelaufen. Bitte noch einmal mit Benutzername und Passwort anmelden.",
                                       "restart": True}, 400)
            with db() as conn:
                u = conn.execute("SELECT * FROM users WHERE id=? AND active=1", (t["uid"],)).fetchone()
                if not u or account_locked(u, ""):
                    with FAILED_LOCK:
                        TWOFA_TICKETS.pop(th, None)
                    return self.send_json({"error": locked_msg, "restart": True}, 429)
                kind = twofa_check(conn, u["id"], str(data.get("code") or "")[:40])
                if kind:
                    account_ok(conn, u["id"])
                    with FAILED_LOCK:
                        TWOFA_TICKETS.pop(th, None)
                    left = len(json.loads(twofa_row(conn, u["id"])["recovery"] or "[]"))
                    audit(conn, {"id": u["id"], "display_name": u["display_name"]}, "Angemeldet", "users", u["id"], u["username"],
                          {"ip": ip, "zweiter Faktor": "Wiederherstellungscode" if kind == "recovery" else "App"})
                else:
                    ip_failed(ip)
                    locked = account_failed(conn, u, u["username"])
                    with FAILED_LOCK:
                        t["tries"] += 1
            if not kind:
                time.sleep(0.6)
                if locked:
                    return self.send_json({"error": locked_msg, "restart": True}, 429)
                return self.send_json({"error": "Der Code stimmt nicht. Bitte den aktuellen Code aus der App eingeben."}, 401)
            tok = self.start_session(u["id"])
            extra = {"recovery_left": left, "next": "/#/sicherheit"} if kind == "recovery" else {}
            return self.send_json({"ok": True, **extra}, headers={"Set-Cookie": self.cookie_header(tok, SESSION_DAYS * 86400)})
        if name == "logout":
            tok = self.session_token()
            user = self.current_user()
            with db() as conn:
                if tok:
                    conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(tok),))
                if user:
                    audit(conn, user, "Abgemeldet", "users", user["id"], user["username"])
            return self.send_json({"ok": True}, headers={"Set-Cookie": self.cookie_header("", 0)})
        return self.send_json({"error": "Unbekannt"}, 404)

    # -- API --------------------------------------------------------------
    def api(self, method, p, user):
        head = p[0] if p else ""
        if head == "me" and p[1:2] == ["2fa"]:
            return self.api_twofa(method, p[2:], user)
        # Zwei-Faktor ist Pflicht, aber noch nicht eingerichtet: nur Profil und Einrichtung erreichbar
        if user["must_2fa"] and head != "me":
            return self.send_json({"error": "Bitte zuerst die Zwei-Faktor-Anmeldung einrichten.", "need_2fa": True}, 403)
        if method == "GET" and head == "me":
            return self.send_json({"user": user, "version": VERSION, "domain": DOMAIN})
        if method == "POST" and p == ["me", "passwort"]:
            return self.api_passwort(user)
        if method == "GET" and p == ["protokoll"]:
            with db() as conn:
                return self.send_json([row_dict(r) for r in conn.execute(
                    "SELECT time, user_name, action, table_name, record_id, label, details FROM audit_log ORDER BY id DESC LIMIT 300")])
        if p == ["sicherungen"] and method in ("GET", "POST"):
            if method == "POST":
                name = daily_backup(neu=True)
                with db() as conn:
                    audit(conn, user, "Sicherung erstellt", "", None, name.name)
            return self.send_json(backup_liste())
        if method == "GET" and head == "umsatz" and p[1:] in ([], ["csv"]):
            jahr = (parse_qs(urlparse(self.path).query).get("jahr") or [""])[0]
            jahr = int(jahr) if re.fullmatch(r"20[0-9]{2}", jahr) else int(heute()[:4])
            with db() as conn:
                if not p[1:]:
                    return self.send_json(umsatz(conn, jahr))
                body = umsatz_csv(conn, jahr).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="umsatz-{jahr}.csv"')
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return self.wfile.write(body)
        if head == "datei" and len(p) == 3 and p[1] in DATEI_TABELLEN and re.fullmatch(r"[0-9]{1,9}", p[2]):
            return self.api_datei(method, p[1], int(p[2]), user)
        if method == "GET" and p == ["lieferung"]:
            with db() as conn:
                return self.send_json(lieferung_uebersicht(conn, heute()))
        if method == "GET" and p == ["abrechnen"]:
            with db() as conn:
                return self.send_json(abrechnen(conn))
        if method == "POST" and p == ["auftraege", "vorschau"]:   # Preis für das Formular, speichert nichts
            data = self.read_json()
            vals = clean_values("auftraege", data)
            if not vals.get("paket_id"):
                raise BadRequest("Bitte ein Paket wählen.")
            with db() as conn:
                old = conn.execute("SELECT * FROM auftraege WHERE id=?", (vals_id(data),)).fetchone()
                row = {**(row_dict(old) if old else {}), **vals}
                fest = ("grundpreis_cent", "inkl_spieler", "zusatz_je_spieler_cent", "anfahrt_frei_km", "anfahrt_cent_je_km")
                return self.send_json({**{k: row.get(k) for k in fest}, **auftrag_preise(conn, row, old)})
        if head in API_TABLES and (len(p) == 1 or (len(p) == 2 and re.fullmatch(r"[0-9]{1,9}", p[1]))):
            return self.api_table(method, head, int(p[1]) if len(p) == 2 else None, user)
        if head == "einstellungen" and not p[1:]:
            with db() as conn:
                if method == "PUT":
                    data = self.read_json()
                    changes = {}
                    for k in EDITABLE_SETTINGS:
                        if k not in data:
                            continue
                        v = str(data[k]).strip()
                        if not (re.fullmatch(r"[0-9]{1,9}", v) or (v == "" and k == "umsatzgrenze_cent")):
                            raise BadRequest(f"{k}: bitte eine ganze Zahl ab 0 eingeben.")
                        alt = get_setting(conn, k)
                        if alt != v:
                            set_setting(conn, k, v)
                            changes[k] = [alt, v]
                    if changes:
                        audit(conn, user, "geändert", "settings", None, "Einstellungen", changes)
                elif method != "GET":
                    return self.send_json({"error": "Methode nicht erlaubt"}, 405)
                return self.send_json({k: get_setting(conn, k) for k in DEFAULT_SETTINGS})
        return self.send_json({"error": "Unbekannte Schnittstelle"}, 404)

    # -- Tabellen (/api/<tabelle>[/<id>]) ----------------------------------
    def api_table(self, method, table, rid, user):
        cols = TABLES[table]
        now = now_iso()
        with db() as conn:
            old = conn.execute(f"SELECT * FROM {table} WHERE id=?", (rid,)).fetchone() if rid is not None else None
            if rid is not None and not old:
                return self.send_json({"error": "Diesen Eintrag gibt es nicht."}, 404)
            if method == "GET":
                rows = [row_dict(r) for r in ([old] if old else conn.execute(f"SELECT * FROM {table} ORDER BY {ORDER[table]}"))]
                if table == "auftraege":
                    mit_ampel(conn, rows)
                if table == "vertraege":
                    mit_fristen(rows)
                return self.send_json(rows[0] if old else rows)

            if (method == "POST" and rid is None) or (method == "PUT" and old):
                vals = clean_values(table, self.read_json())
                for f in SERVER_FIELDS.get(table, ()):
                    vals.pop(f, None)
                if table == "zahlungen":
                    zahlung_vorbereiten(conn, vals, old)
                if table == "lieferlinks":
                    lieferlink_vorbereiten(conn, vals, old)
                if not old:   # Vorgaben, damit die Prüfung auch beim Anlegen greift
                    for k, d in (("typ", "Verein"), ("status", "Angefragt")):
                        if k in cols and table in ("kunden", "auftraege") and not vals.get(k):
                            vals[k] = d
                row = {**(row_dict(old) if old else {}), **vals}
                check_row(conn, table, row)
                if table == "auftraege":
                    pr = auftrag_preise(conn, row, old)
                    pr.pop("berechnet_cent")
                    vals.update(pr)
                    if not old or old["datum"] != row["datum"]:
                        tage = int(get_setting(conn, "lieferfrist_tage") or 0)
                        vals["lieferfrist"] = (date.fromisoformat(row["datum"]) + timedelta(days=tage)).isoformat()
                if "geaendert_am" in cols:
                    vals["geaendert_am"] = now
                if old:
                    if vals:
                        conn.execute(f"UPDATE {table} SET {', '.join(k + '=?' for k in vals)} WHERE id=?", list(vals.values()) + [rid])
                    changes = {k: [old[k], v] for k, v in vals.items()
                               if k not in AUDIT_SKIP and str(old[k] if old[k] is not None else "") != str(v if v is not None else "")}
                else:
                    if "erstellt_am" in cols:
                        vals["erstellt_am"] = now
                    rid = conn.execute(f"INSERT INTO {table} ({', '.join(vals)}) VALUES ({', '.join('?' for _ in vals)})",
                                       list(vals.values())).lastrowid
                    changes = {k: v for k, v in vals.items() if k not in AUDIT_SKIP and v not in (None, "")}
                if table in ("auftraege", "zahlungen"):
                    zahlung_sync(conn, rid if table == "auftraege" else row["auftrag_id"])
                if table == "lieferlinks" and not old:   # erster Link: der Auftrag gilt als geliefert
                    a = conn.execute("SELECT * FROM auftraege WHERE id=?", (row["auftrag_id"],)).fetchone()
                    if a and a["status"] in ("Angefragt", "Bestätigt", "Fotografiert"):
                        conn.execute("UPDATE auftraege SET status='Geliefert', geaendert_am=? WHERE id=?", (now, a["id"]))
                        audit(conn, user, "geändert", "auftraege", a["id"], audit_label("auftraege", a),
                              {"status": [a["status"], "Geliefert"], "Grund": "Galerie-Link eingetragen"})
                r = conn.execute(f"SELECT * FROM {table} WHERE id=?", (rid,)).fetchone()
                if changes:
                    audit(conn, user, "geändert" if old else "neu", table, rid, audit_label(table, r), changes)
                out = row_dict(r)
                if table == "auftraege":
                    mit_ampel(conn, [out])
                if table == "vertraege":
                    mit_fristen([out])
                return self.send_json(out, 200 if old else 201)

            if method == "DELETE" and old:
                # Endgültig löschen geht nur, wenn nichts daran hängt: sonst meldet die Datenbank einen Fehler
                # (IntegrityError, siehe handle_request) und alles wird zurückgerollt.
                if table == "kunden":
                    conn.execute("DELETE FROM kontakte WHERE kunde_id=?", (rid,))
                if table == "auftraege":   # nur, solange keine Zahlung erfasst ist: die offenen Zahlungen gehen mit
                    if conn.execute("SELECT 1 FROM zahlungen WHERE auftrag_id=? AND (status != 'Offen' OR IFNULL(finom_abgerechnet, 0))",
                                    (rid,)).fetchone():
                        raise BadRequest("Zu diesem Auftrag ist schon eine Zahlung erfasst. Bitte archivieren statt löschen.")
                    conn.execute("DELETE FROM zahlungen WHERE auftrag_id=?", (rid,))
                if table == "zahlungen":
                    if old["art"] != "Anzahlung":
                        raise BadRequest("Die Zahlung gehört zum Auftrag und lässt sich nicht einzeln löschen.")
                    if old["status"] != "Offen" or old["finom_abgerechnet"]:
                        raise BadRequest("Nur eine offene Anzahlung lässt sich löschen. Sonst bitte den Status ändern.")
                conn.execute(f"DELETE FROM {table} WHERE id=?", (rid,))
                if table == "zahlungen":
                    zahlung_sync(conn, old["auftrag_id"])
                if table in DATEI_TABELLEN:
                    datei_loeschen(old["datei"])
                audit(conn, user, "gelöscht", table, rid, audit_label(table, old),
                      {k: v for k, v in row_dict(old).items() if k not in AUDIT_SKIP and v not in (None, "")})
                return self.send_json({"ok": True})
        return self.send_json({"error": "Methode nicht erlaubt"}, 405)

    # -- Dateien zu Verträgen und Dokumenten (/api/datei/<tabelle>/<id>) ----
    def api_datei(self, method, table, rid, user):
        with db() as conn:
            r = conn.execute(f"SELECT * FROM {table} WHERE id=?", (rid,)).fetchone()
            if not r:
                return self.send_json({"error": "Diesen Eintrag gibt es nicht."}, 404)
            if method == "POST":
                data = self.read_json(limit=DATEI_MAX * 4 // 3 + 4096)
                fname, anzeige, groesse = datei_speichern(data.get("data"), data.get("name"), DATEI_TABELLEN[table])
                vals = {"datei": fname, "datei_name": anzeige}
                if table == "dokumente":
                    vals.update(groesse=groesse, hochgeladen_am=now_iso())
                conn.execute(f"UPDATE {table} SET {', '.join(k + '=?' for k in vals)} WHERE id=?", [*vals.values(), rid])
                audit(conn, user, "Datei hochgeladen", table, rid, anzeige, {"Größe": groesse})
                alt = r["datei"]
                out = row_dict(conn.execute(f"SELECT * FROM {table} WHERE id=?", (rid,)).fetchone())
            elif method == "GET":
                if not r["datei"] or not (UPLOADS / r["datei"]).is_file():
                    return self.send_json({"error": "Keine Datei vorhanden."}, 404)
                body = (UPLOADS / r["datei"]).read_bytes()
                ctype = next(v[2] for v in DATEI_ARTEN.values() if r["datei"].endswith(v[1]))
                art = "attachment" if "download=1" in urlparse(self.path).query else "inline"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Disposition", f"{art}; filename*=UTF-8''{quote(r['datei_name'] or r['datei'])}")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "private, no-store")
                self.end_headers()
                return self.wfile.write(body)
            else:
                return self.send_json({"error": "Methode nicht erlaubt"}, 405)
        if alt and alt != fname:   # erst nach dem Speichern: die alte Datei wird nicht mehr gebraucht
            datei_loeschen(alt)
        return self.send_json(out)

    # -- Eigenes Passwort ändern (/api/me/passwort) -------------------------
    def api_passwort(self, user):
        data = self.read_json()
        neu = str(data.get("neu") or "")[:200]
        with db() as conn:
            pw_hash = conn.execute("SELECT pw_hash FROM users WHERE id=?", (user["id"],)).fetchone()["pw_hash"]
        if not check_pw(str(data.get("alt") or "")[:200], pw_hash):
            ip_failed(self.client_ip())
            time.sleep(0.6)
            return self.send_json({"error": "Das aktuelle Passwort stimmt nicht."}, 400)
        prob = pw_problem(neu)
        if prob:
            raise BadRequest(prob)
        with db() as conn:
            conn.execute("UPDATE users SET pw_hash=? WHERE id=?", (hash_pw(neu), user["id"]))
            # andere Geräte müssen sich neu anmelden, diese Sitzung bleibt
            conn.execute("DELETE FROM sessions WHERE user_id=? AND token_hash != ?", (user["id"], token_hash(self.session_token())))
            audit(conn, user, "Passwort geändert", "users", user["id"], user["username"])
        return self.send_json({"ok": True})

    # -- Zwei-Faktor des eigenen Kontos (/api/me/2fa) ----------------------
    def api_twofa(self, method, p, user):
        what = p[0] if p else ""
        uid = user["id"]
        if method == "GET" and not what:
            with db() as conn:
                r = twofa_row(conn, uid)
                on = bool(r and r["enabled"])
                return self.send_json({"enabled": on, "required": twofa_required(conn),
                                       "recovery_left": len(json.loads(r["recovery"] or "[]")) if on else 0,
                                       "enabled_at": r["enabled_at"] if on else None})
        if method != "POST" or what not in ("setup", "enable", "recovery", "disable"):
            return self.send_json({"error": "Unbekannte Schnittstelle"}, 404)
        data = self.read_json()
        if what in ("setup", "recovery", "disable"):   # nur mit dem Passwort (schützt vor fremder Nutzung einer offenen Sitzung)
            with db() as conn:
                pw_hash = conn.execute("SELECT pw_hash FROM users WHERE id=?", (uid,)).fetchone()["pw_hash"]
            if not check_pw(str(data.get("password") or "")[:200], pw_hash):
                ip_failed(self.client_ip())
                time.sleep(0.6)
                return self.send_json({"error": "Das Passwort stimmt nicht."}, 400)
        with db() as conn:
            r = twofa_row(conn, uid)
            on = bool(r and r["enabled"])
            if what == "setup":
                if on:
                    return self.send_json({"error": "Die Zwei-Faktor-Anmeldung ist schon eingerichtet."}, 400)
                secret = base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")
                conn.execute("INSERT INTO user_2fa (user_id, enabled, pending_secret, pending_expires) VALUES (?, 0, ?, ?) "
                             "ON CONFLICT(user_id) DO UPDATE SET pending_secret=excluded.pending_secret, "
                             "pending_expires=excluded.pending_expires", (uid, secret, time.time() + 900))
                return self.send_json({"secret": secret, "uri": totp_uri(secret, user["username"]), "issuer": TOTP_ISSUER,
                                       "account": user["username"]})
            if what == "enable":
                if on:
                    return self.send_json({"error": "Die Zwei-Faktor-Anmeldung ist schon eingerichtet."}, 400)
                if not r or not r["pending_secret"] or (r["pending_expires"] or 0) < time.time():
                    return self.send_json({"error": "Die Einrichtung ist abgelaufen. Bitte noch einmal starten."}, 400)
                step = totp_match(r["pending_secret"], data.get("code"))
                if not step:
                    time.sleep(0.4)
                    return self.send_json({"error": "Der Code stimmt nicht. Prüfe, ob die Uhrzeit am Handy stimmt, "
                                                    "und gib den aktuellen Code ein."}, 400)
                codes, hashes = recovery_new()
                conn.execute("UPDATE user_2fa SET secret=pending_secret, pending_secret=NULL, pending_expires=NULL, enabled=1, "
                             "last_step=?, recovery=?, enabled_at=? WHERE user_id=?", (step, json.dumps(hashes), now_iso(), uid))
                # andere Geräte müssen sich neu anmelden, diese Sitzung bleibt
                conn.execute("DELETE FROM sessions WHERE user_id=? AND token_hash != ?", (uid, token_hash(self.session_token())))
                audit(conn, user, "Zwei-Faktor-Anmeldung eingerichtet", "users", uid, user["username"])
                return self.send_json({"ok": True, "codes": codes})
            if what == "recovery":
                if not on:
                    return self.send_json({"error": "Die Zwei-Faktor-Anmeldung ist nicht eingerichtet."}, 400)
                codes, hashes = recovery_new()
                conn.execute("UPDATE user_2fa SET recovery=? WHERE user_id=?", (json.dumps(hashes), uid))
                audit(conn, user, "Neue Wiederherstellungscodes", "users", uid, user["username"])
                return self.send_json({"ok": True, "codes": codes})
            # disable
            if not on:
                return self.send_json({"error": "Die Zwei-Faktor-Anmeldung ist nicht eingerichtet."}, 400)
            if twofa_required(conn):
                return self.send_json({"error": "Die Zwei-Faktor-Anmeldung ist Pflicht und lässt sich hier nicht ausschalten. "
                                                "Notfall: auf dem Server python server.py 2fa-reset <name>."}, 400)
            conn.execute("DELETE FROM user_2fa WHERE user_id=?", (uid,))
            audit(conn, user, "Zwei-Faktor-Anmeldung ausgeschaltet", "users", uid, user["username"])
            return self.send_json({"ok": True})


def cli():
    cmd = sys.argv[1]
    init_db()
    if cmd == "users":
        with db() as conn:
            for r in conn.execute("SELECT username, active, last_login FROM users ORDER BY id"):
                print(f"{r['username']:20} {'aktiv' if r['active'] else 'inaktiv':8} zuletzt: {r['last_login'] or '-'}")
        return
    if len(sys.argv) < 3:
        print(f"Aufruf: python server.py {cmd} <benutzername>")
        sys.exit(2)
    name = sys.argv[2]
    if cmd == "2fa-reset":
        try:
            twofa_reset(name)
        except ValueError as e:
            print(e)
            sys.exit(1)
        print(f"Zwei-Faktor-Anmeldung für {name} zurückgesetzt. Beim nächsten Login muss sie neu eingerichtet werden.")
        return
    pw = getpass.getpass("Neues Passwort (mindestens 10 Zeichen): ")
    if pw != getpass.getpass("Passwort wiederholen: "):
        print("Die Passwörter stimmen nicht überein.")
        sys.exit(1)
    try:
        if cmd == "adduser":
            create_user(name, pw)
            print(f"Benutzer {name} wurde angelegt.")
        else:
            set_password(name, pw)
            print(f"Passwort für {name} wurde gesetzt, alte Sitzungen sind abgemeldet.")
    except ValueError as e:
        print(e)
        sys.exit(1)


def make_server(host=HOST, port=PORT):
    init_db()
    bootstrap_admin()
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    return httpd


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("adduser", "passwd", "users", "2fa-reset"):
        return cli()
    httpd = make_server()
    threading.Thread(target=backup_loop, daemon=True).start()
    print("=" * 56)
    print(f"  {APP_NAME} {VERSION}")
    print(f"  Läuft unter http://{'127.0.0.1' if HOST in ('0.0.0.0', '::') else HOST}:{PORT}/")
    print(f"  Daten: {DATA}")
    if user_count() == 0:
        print("  Noch kein Benutzer. Anlegen mit: python server.py adduser <name>")
        print("  oder STUDIO_ADMIN_USER und STUDIO_ADMIN_PASSWORD in der .env setzen.")
    print("=" * 56, flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
