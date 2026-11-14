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
import ipaddress
import getpass
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import socket
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse
from zoneinfo import ZoneInfo

import webpush
from webpush import b64u, b64u_dec, ec_pub_point, push_endpoint_ok

VERSION = "0.9"
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
        "wiederholung": "TEXT",                          # leer, täglich, wöchentlich, monatlich, jährlich
        "wiederholung_bis": "TEXT",
        "erinnerung_min": "INTEGER",                     # Push so viele Minuten vor Beginn, leer: keine
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
    "aufgaben_vorlagen": {                               # Aufgaben, die beim Anlegen eines Auftrags entstehen
        "paket_id": "INTEGER REFERENCES pakete(id)",
        "titel": "TEXT NOT NULL",
        "tage_offset": "INTEGER DEFAULT 0",              # fällig: Datum des Auftrags plus so viele Tage (auch negativ)
        "prioritaet": "TEXT DEFAULT 'Mittel'",
        "sort": "INTEGER DEFAULT 0",
    },
    "push_abos": {                                       # angemeldetes Gerät
        "endpoint": "TEXT",                              # eindeutig über ux_push_endpoint
        "p256dh": "TEXT",
        "auth": "TEXT",
        "geraet": "TEXT",
        "angelegt_am": "TEXT",
        "zuletzt_ok": "TEXT",
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

# Standard-Aufgaben je Paket (Liste aus der Planung), mit Tagen relativ zum Auftrag
SEED_AUFGABEN = (("Akkus laden", -1), ("Bilder sichern", 0), ("Auswahl bearbeiten", 1), ("Galerie hochladen", 3),
                 ("Link verschicken", 3), ("Zahlung prüfen", 7))
WIEDERHOLUNGEN = ("", "täglich", "wöchentlich", "monatlich", "jährlich")
PRIORITAETEN = ("Hoch", "Mittel", "Niedrig")
STATUS_AUFGABE = ("Offen", "In Arbeit", "Erledigt")

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
        conn.execute("CREATE TABLE IF NOT EXISTS erinnerungen (schluessel TEXT PRIMARY KEY, zeit TEXT)")   # schon gesendete Push-Erinnerungen
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
    if not conn.execute("SELECT 1 FROM settings WHERE key='seed_aufgaben'").fetchone():
        # Liste aus der Planung, je Paket. Die Tage relativ zum Auftrag sind ein Vorschlag, in den Einstellungen änderbar.
        if not conn.execute("SELECT COUNT(*) FROM aufgaben_vorlagen").fetchone()[0]:
            for (pid,) in conn.execute("SELECT id FROM pakete ORDER BY sort, id").fetchall():
                for i, (titel, tage) in enumerate(SEED_AUFGABEN, 1):
                    conn.execute("INSERT INTO aufgaben_vorlagen (paket_id, titel, tage_offset, prioritaet, sort) VALUES (?, ?, ?, 'Mittel', ?)",
                                 (pid, titel, tage, i))
        conn.execute("INSERT INTO settings (key, value) VALUES ('seed_aufgaben', ?)", (now_iso(),))
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
API_TABLES = ("kunden", "kontakte", "pakete", "auftraege", "zahlungen", "lieferlinks", "vorlagen", "vertraege", "dokumente",
              "termine", "aufgaben", "aufgaben_vorlagen")
ORDER = {"kunden": "name COLLATE NOCASE, id", "kontakte": "name COLLATE NOCASE, id", "pakete": "sort, id",
         "auftraege": "datum, uhrzeit, id", "zahlungen": "auftrag_id, art = 'Zahlung', id",
         "lieferlinks": "auftrag_id, erstellt_am, id", "vorlagen": "sort, id", "vertraege": "beginn, id",
         "dokumente": "hochgeladen_am DESC, id", "termine": "beginn, id",
         "aufgaben": "status = 'Erledigt', faellig = '', faellig IS NULL, faellig, prioritaet = 'Niedrig', prioritaet = 'Mittel', sort, id",
         "aufgaben_vorlagen": "paket_id, sort, id"}
# Diese Felder setzt nur der Server (Preise, Fristen, Zeitstempel)
SERVER_FIELDS = {
    "kunden": ("erstellt_am", "geaendert_am"),
    "kontakte": ("erstellt_am", "geaendert_am", "anonymisiert"),
    "zahlungen": ("erstellt_am", "geaendert_am"),
    "lieferlinks": ("erstellt_am",),
    "vertraege": ("erstellt_am", "geaendert_am", "datei", "datei_name"),
    "dokumente": ("hochgeladen_am", "datei", "datei_name", "groesse"),
    "aufgaben": ("erstellt_am", "geaendert_am", "erledigt_am"),
    "termine": ("erstellt_am", "geaendert_am"),
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


NEGATIV_OK = {"tage_offset"}


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
                if v is None or not (-3650 if k in NEGATIV_OK else 0) <= v < 10 ** 9:
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
    if table in ("aufgaben", "aufgaben_vorlagen") and not row.get("titel"):
        raise BadRequest("Bitte einen Titel eingeben.")
    if table in ("aufgaben", "aufgaben_vorlagen") and (row.get("prioritaet") or "Mittel") not in PRIORITAETEN:
        raise BadRequest("Unbekannte Priorität.")
    if table == "aufgaben":
        if (row.get("status") or "Offen") not in STATUS_AUFGABE:
            raise BadRequest("Unbekannter Status.")
        if row.get("faellig"):
            try:
                date.fromisoformat(row["faellig"])
            except ValueError:
                raise BadRequest("Bitte ein gültiges Fälligkeitsdatum eingeben.")
    if table in ("aufgaben", "termine") and (row.get("wiederholung") or "") not in WIEDERHOLUNGEN:
        raise BadRequest("Unbekannte Wiederholung.")
    if table == "termine":
        if not row.get("titel"):
            raise BadRequest("Bitte einen Titel eingeben.")
        b, e = termin_zeit(row)
        if not b:
            raise BadRequest("Bitte Beginn angeben (Datum, bei Uhrzeit als Datum und Zeit).")
        if row.get("ende") and not e:
            raise BadRequest("Ende ungültig.")
        if e and e < b:
            raise BadRequest("Das Ende liegt vor dem Beginn.")
        if row.get("wiederholung_bis"):
            try:
                date.fromisoformat(row["wiederholung_bis"])
            except ValueError:
                raise BadRequest("Wiederholung bis: bitte ein gültiges Datum.")


def termin_zeit(t):
    """Beginn und Ende als datetime (lokal). Ganztägig: JJJJ-MM-TT, sonst JJJJ-MM-TTTHH:MM. Ungültig: (None, None)."""
    def lesen(v, ende=False):
        v = (v or "").strip()
        try:
            if t.get("ganztaegig"):
                d = date.fromisoformat(v[:10])
                return datetime(d.year, d.month, d.day) + (timedelta(days=1) if ende else timedelta())
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", v):
                return None
            return datetime.fromisoformat(v)
        except ValueError:
            return None
    b = lesen(t.get("beginn"))
    e = lesen(t.get("ende"), True) if t.get("ende") else None
    if b and not e:
        e = b + (timedelta(days=1) if t.get("ganztaegig") else timedelta(hours=1))
    return b, e


def naechstes(d, wiederholung):
    if wiederholung == "täglich":
        return d + timedelta(days=1)
    if wiederholung == "wöchentlich":
        return d + timedelta(days=7)
    if wiederholung == "monatlich":
        return plus_monate(d, 1)
    if wiederholung == "jährlich":
        return plus_monate(d, 12)
    return None


def termin_vorkommen(t, von, bis):
    """Alle Vorkommen eines Termins, die den Zeitraum [von, bis] (date) berühren: Liste von (beginn, ende) als datetime.
    Monatlich am 31. landet in kürzeren Monaten am Monatsende (gerechnet vom ersten Termin aus, nicht fortgeschrieben)."""
    b, e = termin_zeit(t)
    if not b:
        return []
    dauer = e - b
    w = t.get("wiederholung") or ""
    grenze = date.fromisoformat(t["wiederholung_bis"]) if t.get("wiederholung_bis") else None
    out = []
    for n in range(5000):   # Schutz vor Endlosschleifen
        if n == 0:
            x = b
        elif w in ("monatlich", "jährlich"):
            x = datetime.combine(plus_monate(b.date(), n * (1 if w == "monatlich" else 12)), b.time())
        elif w:
            x = b + n * (timedelta(days=1) if w == "täglich" else timedelta(days=7))
        else:
            break
        if x.date() > bis or (grenze and x.date() > grenze):
            break
        if (x + dauer).date() >= von or x.date() >= von:
            if (x + dauer) > datetime.combine(von, datetime.min.time()) or x.date() >= von:
                out.append((x, x + dauer))
    return out


def ueberschneidungen(conn, beginn, ende, ausser=None):
    """Termine und Aufträge mit Uhrzeit, die sich mit [beginn, ende) überschneiden. ausser: ("termin"|"auftrag", id)."""
    tag = beginn.date()
    treffer = []
    for a in conn.execute("SELECT id, datum, uhrzeit, begegnung FROM auftraege WHERE datum >= ? AND datum <= ? AND IFNULL(uhrzeit, '') != '' "
                          "AND status != 'Abgesagt' AND IFNULL(archiviert, 0)=0", ((tag - timedelta(days=1)).isoformat(), ende.date().isoformat())):
        if ausser == ("auftrag", a["id"]):
            continue
        ab = datetime.fromisoformat(f"{a['datum']}T{a['uhrzeit']}")
        if ab < ende and beginn < ab + timedelta(minutes=ICS_DAUER_MIN):
            treffer.append({"art": "auftrag", "id": a["id"], "titel": a["begegnung"] or "Auftrag", "beginn": ab.isoformat(timespec="minutes")})
    for t in conn.execute("SELECT * FROM termine").fetchall():
        if ausser == ("termin", t["id"]) or t["ganztaegig"]:
            continue
        for tb, te in termin_vorkommen(row_dict(t), tag - timedelta(days=1), ende.date()):
            if tb < ende and beginn < te:
                treffer.append({"art": "termin", "id": t["id"], "titel": t["titel"], "beginn": tb.isoformat(timespec="minutes")})
    return treffer


def aufgaben_aus_vorlagen(conn, a):
    """Beim Anlegen eines Auftrags: die Aufgaben-Vorlagen seines Pakets als Aufgaben anlegen."""
    d = date.fromisoformat(a["datum"])
    for v in conn.execute("SELECT * FROM aufgaben_vorlagen WHERE paket_id=? ORDER BY sort, id", (a["paket_id"],)).fetchall():
        conn.execute("INSERT INTO aufgaben (titel, faellig, prioritaet, status, kunde_id, auftrag_id, sort, erstellt_am, geaendert_am) "
                     "VALUES (?, ?, ?, 'Offen', ?, ?, ?, ?, ?)",
                     (v["titel"], (d + timedelta(days=v["tage_offset"] or 0)).isoformat(), v["prioritaet"] or "Mittel",
                      a["kunde_id"], a["id"], v["sort"] or 0, now_iso(), now_iso()))


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


def speichern(conn, table, data, old, user, fest=None):
    """Eintrag anlegen (old=None) oder ändern, mit allen Regeln der Tabelle. fest: Werte, die nur der Server setzt
    (zum Beispiel die Serien-Kennung). Rückgabe: der gespeicherte Eintrag als dict."""
    cols = TABLES[table]
    now = now_iso()
    rid = old["id"] if old else None
    vals = clean_values(table, data)
    for f in SERVER_FIELDS.get(table, ()):
        vals.pop(f, None)
    vals.update(fest or {})
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
    if table == "aufgaben":
        if row.get("status") == "Erledigt" and (not old or old["status"] != "Erledigt"):
            conn.execute("UPDATE aufgaben SET erledigt_am=? WHERE id=?", (now, rid))
            # wiederkehrend: die nächste Aufgabe entsteht beim Erledigen, die erledigte bleibt als Verlauf
            nxt = naechstes(date.fromisoformat(row["faellig"]), row.get("wiederholung") or "") if row.get("faellig") else None
            if nxt:
                conn.execute("INSERT INTO aufgaben (titel, faellig, prioritaet, status, wiederholung, kunde_id, auftrag_id, notizen, sort, "
                             "erstellt_am, geaendert_am) VALUES (?, ?, ?, 'Offen', ?, ?, ?, ?, ?, ?, ?)",
                             (row["titel"], nxt.isoformat(), row.get("prioritaet") or "Mittel", row["wiederholung"], row.get("kunde_id"),
                              row.get("auftrag_id"), row.get("notizen"), row.get("sort") or 0, now, now))
        elif row.get("status") != "Erledigt" and old and old["status"] == "Erledigt":
            conn.execute("UPDATE aufgaben SET erledigt_am=NULL WHERE id=?", (rid,))
    if table == "auftraege" and not old:
        aufgaben_aus_vorlagen(conn, {**row, "id": rid})
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
    # Warnung bei Überschneidungen (gespeichert wird trotzdem)
    if table == "termine" and not out.get("ganztaegig"):
        b, e = termin_zeit(out)
        out["ueberschneidungen"] = ueberschneidungen(conn, b, e, ("termin", rid))
    if table == "auftraege" and out.get("uhrzeit") and out.get("status") != "Abgesagt":
        b = datetime.fromisoformat(f"{out['datum']}T{out['uhrzeit']}")
        out["ueberschneidungen"] = ueberschneidungen(conn, b, b + timedelta(minutes=ICS_DAUER_MIN), ("auftrag", rid))
    return out


def auftraege_im_zeitraum(conn, von, bis):
    rows = [row_dict(r) for r in conn.execute(
        "SELECT a.*, k.name AS kunde FROM auftraege a LEFT JOIN kunden k ON k.id = a.kunde_id "
        "WHERE IFNULL(a.archiviert, 0)=0 AND a.datum >= ? AND a.datum <= ? ORDER BY a.datum, a.uhrzeit, a.id", (von, bis))]
    return mit_ampel(conn, rows)


def dashboard(conn, tag):
    t = date.fromisoformat(tag)
    lief = lieferung_uebersicht(conn, tag)
    u = umsatz(conn, t.year)
    offen = [row_dict(r) for r in conn.execute(
        "SELECT z.id, z.betrag_cent, z.art, a.id AS auftrag_id, a.datum, a.begegnung, k.name AS kunde FROM zahlungen z "
        "JOIN auftraege a ON a.id = z.auftrag_id LEFT JOIN kunden k ON k.id = a.kunde_id "
        "WHERE z.status='Offen' AND a.status != 'Abgesagt' ORDER BY a.datum, z.id")]
    vertraege = mit_fristen([row_dict(r) for r in conn.execute(
        "SELECT v.*, k.name AS kunde FROM vertraege v LEFT JOIN kunden k ON k.id = v.kunde_id WHERE IFNULL(v.archiviert, 0)=0")])
    grenze = (t + timedelta(days=60)).isoformat()
    return {
        "heute": tag,
        "termine": [a for a in auftraege_im_zeitraum(conn, tag, (t + timedelta(days=14)).isoformat()) if a["status"] != "Abgesagt"],
        "ueberfaellig": lief["ueberfaellig"],
        "offen": offen, "offen_summe": sum(z["betrag_cent"] or 0 for z in offen),
        "links_ablauf": lief["laeuft_ab"],
        "vertraege": sorted((v for v in vertraege if v["kuendigen_bis"] and tag <= v["kuendigen_bis"] <= grenze),
                            key=lambda v: v["kuendigen_bis"]),
        "umsatz_jahr": u["summe"], "umsatz_grenze": u["grenze"], "jahr": t.year,
        "aufgaben": [row_dict(r) for r in conn.execute(
            "SELECT * FROM aufgaben WHERE status != 'Erledigt' AND faellig != '' AND faellig <= ? ORDER BY faellig, prioritaet='Niedrig', "
            "prioritaet='Mittel', id", (tag,))],
        "eigene_termine": [e for e in kalender_eintraege(conn, tag, (t + timedelta(days=14)).isoformat()) if e["art"] == "termin"],
    }


def kalender_eintraege(conn, von, bis):
    """Alles, was der Kalender zeigt, im Zeitraum von bis bis (JJJJ-MM-TT). art: auftrag, lieferfrist, vertrag, ablauf."""
    out = []
    for a in auftraege_im_zeitraum(conn, von, bis):
        out.append({"art": "auftrag", "id": a["id"], "datum": a["datum"], "uhrzeit": a["uhrzeit"] or "", "titel": a["begegnung"] or "Auftrag",
                    "ort": a["ort"] or "", "kunde": a["kunde"] or "", "status": a["status"], "ampel": a["ampel"]})
    for a in mit_ampel(conn, [row_dict(r) for r in conn.execute(
            "SELECT * FROM auftraege WHERE IFNULL(archiviert, 0)=0 AND lieferfrist >= ? AND lieferfrist <= ?", (von, bis))]):
        if a["ampel"] in ("rot", "gelb"):
            out.append({"art": "lieferfrist", "id": a["id"], "datum": a["lieferfrist"], "uhrzeit": "", "titel": "Lieferfrist: " + (a["begegnung"] or "Auftrag")})
    for v in mit_fristen([row_dict(r) for r in conn.execute(
            "SELECT v.*, k.name AS kunde FROM vertraege v LEFT JOIN kunden k ON k.id = v.kunde_id WHERE IFNULL(v.archiviert, 0)=0")]):
        if v["kuendigen_bis"] and von <= v["kuendigen_bis"] <= bis:
            out.append({"art": "vertrag", "id": v["id"], "datum": v["kuendigen_bis"], "uhrzeit": "", "titel": f"Kündigen bis: {v['kunde'] or ''} ({v['art']})"})
    for l in conn.execute("SELECT l.id, l.auftrag_id, l.typ, l.laeuft_ab_am, a.begegnung FROM lieferlinks l JOIN auftraege a ON a.id = l.auftrag_id "
                          "WHERE l.laeuft_ab_am >= ? AND l.laeuft_ab_am <= ?", (von, bis)):
        out.append({"art": "ablauf", "id": l["auftrag_id"], "datum": l["laeuft_ab_am"], "uhrzeit": "", "titel": f"{l['typ']}-Link läuft ab: {l['begegnung'] or ''}"})
    v_, b_ = date.fromisoformat(von), date.fromisoformat(bis)
    for t in conn.execute("SELECT * FROM termine").fetchall():
        for tb, te in termin_vorkommen(row_dict(t), v_, b_):
            if tb.date() < v_:
                continue
            out.append({"art": "termin", "id": t["id"], "datum": tb.date().isoformat(), "uhrzeit": "" if t["ganztaegig"] else tb.strftime("%H:%M"),
                        "bis": "" if t["ganztaegig"] else te.strftime("%H:%M"), "titel": t["titel"], "ort": t["ort"] or "", "termin_art": t["art"] or ""})
    for a in conn.execute("SELECT id, titel, faellig, prioritaet FROM aufgaben WHERE status != 'Erledigt' AND faellig >= ? AND faellig <= ?", (von, bis)):
        out.append({"art": "aufgabe", "id": a["id"], "datum": a["faellig"], "uhrzeit": "", "titel": a["titel"], "prioritaet": a["prioritaet"]})
    with FREMD_LOCK:
        fremd = list(FREMD["termine"])
    for f in fremd:
        if von <= f["datum"] <= bis:
            out.append({"art": "extern", "id": 0, **f})
    return sorted(out, key=lambda e: (e["datum"], e["uhrzeit"] or "99"))


# ---------------------------------------------------------------------------
# Fremder Kalender (ICS-Link, zum Beispiel Dienstplan): nur anzeigen, nie ins eigene Kalender-Abo übernehmen.
# Der Link liegt in secrets ("ics_import_url"), abgerufen wird alle 30 Minuten im Hintergrund.
# ---------------------------------------------------------------------------
FREMD_LOCK = threading.Lock()
FREMD = {"termine": [], "zeit": "", "fehler": ""}
FREMD_MAX = 5 * 1024 * 1024
FREMD_TAGE = 400   # Vorkommen von heute minus 30 bis plus 400 Tage


def fremd_url_ok(url):
    """Nur https, kein Server im eigenen Netz (sonst könnte der Link den Server auf interne Adressen schicken)."""
    u = urlparse(str(url or ""))
    if u.scheme != "https" or not u.hostname or len(url) > 2000:
        return False
    try:
        for info in socket.getaddrinfo(u.hostname, u.port or 443, proto=socket.IPPROTO_TCP):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
                return False
    except (OSError, ValueError):
        return False
    return True


def ics_lesen(text, heute_d=None):
    """Einfacher ICS-Leser für VEVENTs: SUMMARY, LOCATION, DTSTART/DTEND (mit TZID, UTC oder ganztägig), RRULE mit FREQ,
    INTERVAL, COUNT, UNTIL. shortcut: BYDAY, EXDATE und geänderte Einzeltermine (RECURRENCE-ID) werden nicht ausgewertet;
    reicht für einfache Dienstpläne, bei Bedarf erweitern."""
    heute_d = heute_d or date.fromisoformat(heute())
    von, bis = heute_d - timedelta(days=30), heute_d + timedelta(days=FREMD_TAGE)
    zeilen = []
    for z in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if z[:1] in (" ", "\t") and zeilen:
            zeilen[-1] += z[1:]
        else:
            zeilen.append(z)

    def zeit(name, params, wert):
        tz = next((p.split("=", 1)[1] for p in params if p.upper().startswith("TZID=")), None)
        if "VALUE=DATE" in [p.upper() for p in params] or re.fullmatch(r"\d{8}", wert):
            return datetime.strptime(wert[:8], "%Y%m%d"), True
        dt = datetime.strptime(wert[:15], "%Y%m%dT%H%M%S")
        if wert.endswith("Z"):
            return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ).replace(tzinfo=None), False
        if tz:
            try:
                return dt.replace(tzinfo=ZoneInfo(tz.strip('"'))).astimezone(TZ).replace(tzinfo=None), False
            except Exception:  # noqa: unbekannte Zeitzone: als Ortszeit nehmen
                pass
        return dt, False

    def text_(v):
        return v.replace("\\n", " ").replace("\\N", " ").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")

    out, ev = [], None
    for z in zeilen:
        if z == "BEGIN:VEVENT":
            ev = {}
        elif z == "END:VEVENT" and ev is not None:
            try:
                if "DTSTART" in ev and ev.get("STATUS", ("", [], ""))[2].upper() != "CANCELLED":
                    b, ganz = zeit(*ev["DTSTART"])
                    e = zeit(*ev["DTEND"])[0] if "DTEND" in ev else b + (timedelta(days=1) if ganz else timedelta(hours=1))
                    regel = dict(x.split("=", 1) for x in ev.get("RRULE", ("", [], ""))[2].split(";") if "=" in x)
                    freq = {"DAILY": "täglich", "WEEKLY": "wöchentlich", "MONTHLY": "monatlich", "YEARLY": "jährlich"}.get(regel.get("FREQ", ""), "")
                    schritt = max(1, int(regel.get("INTERVAL", "1") or 1))
                    anzahl = int(regel["COUNT"]) if regel.get("COUNT", "").isdigit() else None
                    ende_r = datetime.strptime(regel["UNTIL"][:8], "%Y%m%d").date() if regel.get("UNTIL") else None
                    x, n = b, 0
                    while n < 3000:
                        if x.date() > bis or (ende_r and x.date() > ende_r) or (anzahl is not None and n >= anzahl):
                            break
                        if x.date() >= von:
                            out.append({"datum": x.date().isoformat(), "uhrzeit": "" if ganz else x.strftime("%H:%M"),
                                        "bis": "" if ganz else (x + (e - b)).strftime("%H:%M"),
                                        "titel": text_(ev.get("SUMMARY", ("", [], "Termin"))[2])[:200], "ort": text_(ev.get("LOCATION", ("", [], ""))[2])[:200]})
                        if not freq:
                            break
                        n += 1
                        if freq in ("monatlich", "jährlich"):
                            x = datetime.combine(plus_monate(b.date(), n * schritt * (1 if freq == "monatlich" else 12)), b.time())
                        else:
                            x = b + n * schritt * timedelta(days=1 if freq == "täglich" else 7)
            except (ValueError, KeyError):
                pass   # einzelner kaputter Termin: überspringen, der Rest zählt
            ev = None
        elif ev is not None and ":" in z:
            kopf, wert = z.split(":", 1)
            name, *params = kopf.split(";")
            ev[name.upper()] = (name.upper(), params, wert)
    return out


def fremd_abrufen():
    with db() as conn:
        url = secret_get(conn, "ics_import_url")
    if not url:
        with FREMD_LOCK:
            FREMD.update(termine=[], zeit="", fehler="")
        return
    try:
        if not fremd_url_ok(url):
            raise ValueError("Der Link muss mit https:// beginnen und auf einen Server im Internet zeigen.")
        req = urllib.request.Request(url, headers={"User-Agent": "Studio-Tool/" + VERSION, "Accept": "text/calendar"})
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read(FREMD_MAX + 1)
        if len(raw) > FREMD_MAX:
            raise ValueError("Der Kalender ist größer als 5 MB.")
        termine = ics_lesen(raw.decode("utf-8", "replace"))
        with FREMD_LOCK:
            FREMD.update(termine=termine, zeit=now_iso(), fehler="")
    except Exception as e:  # noqa: Netz, Format, Zertifikat
        with FREMD_LOCK:
            FREMD.update(zeit=now_iso(), fehler=str(e)[:200] or e.__class__.__name__)


# ---------------------------------------------------------------------------
# Hintergrund: Erinnerungen per Push (Termine mit Vorlauf, Aufgaben am Fälligkeitstag um 8 Uhr) und fremder Kalender
# ---------------------------------------------------------------------------
AUFGABEN_UHRZEIT = 8


def erinnerungen_faellig(conn, jetzt):
    """Was jetzt erinnert werden soll und noch nicht erinnert wurde: Liste (schluessel, titel, text, url)."""
    out = []
    tag = jetzt.date()
    for t in conn.execute("SELECT * FROM termine WHERE erinnerung_min IS NOT NULL").fetchall():
        for tb, _ in termin_vorkommen(row_dict(t), tag - timedelta(days=1), tag + timedelta(days=8)):
            wann = tb - timedelta(minutes=t["erinnerung_min"] or 0)
            if wann <= jetzt <= tb + timedelta(minutes=10):   # verpasste Erinnerung höchstens bis 10 Minuten nach Beginn nachholen
                out.append((f"termin:{t['id']}:{tb.isoformat()}", "Termin" + ("" if t["ganztaegig"] else f" um {tb:%H:%M}"),
                            t["titel"] + (f", {t['ort']}" if t["ort"] else ""), "/#/kalender"))
    if jetzt.hour >= AUFGABEN_UHRZEIT:
        for a in conn.execute("SELECT id, titel FROM aufgaben WHERE status != 'Erledigt' AND faellig=?", (tag.isoformat(),)):
            out.append((f"aufgabe:{a['id']}:{tag.isoformat()}", "Aufgabe fällig", a["titel"], "/#/aufgaben"))
    return [x for x in out if not conn.execute("SELECT 1 FROM erinnerungen WHERE schluessel=?", (x[0],)).fetchone()]


def erinnern(jetzt=None):
    jetzt = jetzt or datetime.now(TZ).replace(tzinfo=None)
    with db() as conn:
        faellig = erinnerungen_faellig(conn, jetzt)
        for schluessel, *_ in faellig:   # vor dem Senden merken: lieber einmal verpasst als doppelt
            conn.execute("INSERT OR IGNORE INTO erinnerungen (schluessel, zeit) VALUES (?, ?)", (schluessel, jetzt.isoformat()))
        conn.execute("DELETE FROM erinnerungen WHERE zeit < ?", ((jetzt - timedelta(days=60)).isoformat(),))
    for schluessel, titel, text, url in faellig:
        send_push(titel, text, url, schluessel.rsplit(":", 1)[0])
    return len(faellig)


def hintergrund_loop():
    letzter_abruf = 0
    while True:
        try:
            erinnern()
        except Exception as e:  # noqa
            print("Erinnerungen fehlgeschlagen:", e)
        if time.time() - letzter_abruf > 1800:
            letzter_abruf = time.time()
            fremd_abrufen()
        if HINTERGRUND_EXTRA:
            for f in HINTERGRUND_EXTRA:
                try:
                    f()
                except Exception as e:  # noqa
                    print("Hintergrund fehlgeschlagen:", e)
        threading.Event().wait(60)


HINTERGRUND_EXTRA = []   # weitere Aufgaben je Minute (Postfach-Abruf, Phase 9)


def ics_text(v):
    return str(v or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")


def ics_falten(zeile):
    """RFC 5545: Zeilen höchstens 75 Bytes, Fortsetzung beginnt mit einem Leerzeichen."""
    b = zeile.encode("utf-8")
    teile = []
    while len(b) > 75:
        cut = 75 if not teile else 74
        while cut > 0 and (b[cut] & 0xC0) == 0x80:   # nicht mitten in einem UTF-8-Zeichen trennen
            cut -= 1
        teile.append(b[:cut].decode("utf-8"))
        b = b[cut:]
    teile.append(b.decode("utf-8"))
    return "\r\n ".join(teile)


ICS_DAUER_MIN = 120   # shortcut: Aufträge haben keine Endzeit, im Kalender-Abo stehen sie mit 2 Stunden; bei Bedarf Feld "Ende" ergänzen


def ics_kalender(conn):
    """Kalender-Abo: nur Termin, Ort und Begegnung. Keine Beträge, keine Kontaktdaten."""
    stamp = datetime.now(TZ).astimezone(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")
    host = DOMAIN or "studio-tool.local"
    z = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//silasgrbwsk.fotografie//Studio-Tool//DE", "CALSCALE:GREGORIAN",
         "X-WR-CALNAME:Studio-Tool", "X-WR-TIMEZONE:Europe/Berlin"]
    seit = (date.fromisoformat(heute()) - timedelta(days=90)).isoformat()
    for a in conn.execute("SELECT * FROM auftraege WHERE IFNULL(archiviert, 0)=0 AND status != 'Abgesagt' AND datum >= ? ORDER BY datum",
                          (seit,)):
        z += ["BEGIN:VEVENT", f"UID:auftrag-{a['id']}@{host}", f"DTSTAMP:{stamp}"]
        if a["uhrzeit"]:
            beginn = datetime.fromisoformat(f"{a['datum']}T{a['uhrzeit']}").replace(tzinfo=TZ).astimezone(ZoneInfo("UTC"))
            z += [f"DTSTART:{beginn:%Y%m%dT%H%M%SZ}", f"DTEND:{beginn + timedelta(minutes=ICS_DAUER_MIN):%Y%m%dT%H%M%SZ}"]
        else:
            d = date.fromisoformat(a["datum"])
            z += [f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{d + timedelta(days=1):%Y%m%d}"]
        z.append("SUMMARY:" + ics_text(a["begegnung"] or "Auftrag"))
        if a["ort"]:
            z.append("LOCATION:" + ics_text(a["ort"]))
        z.append("END:VEVENT")
    # eigene Termine, Wiederholungen als einzelne Vorkommen im nächsten Jahr
    h = date.fromisoformat(heute())
    for t in conn.execute("SELECT * FROM termine").fetchall():
        for tb, te in termin_vorkommen(row_dict(t), h - timedelta(days=90), h + timedelta(days=365)):
            z += ["BEGIN:VEVENT", f"UID:termin-{t['id']}-{tb:%Y%m%dT%H%M}@{host}", f"DTSTAMP:{stamp}"]
            if t["ganztaegig"]:
                z += [f"DTSTART;VALUE=DATE:{tb:%Y%m%d}", f"DTEND;VALUE=DATE:{te:%Y%m%d}"]
            else:
                u = ZoneInfo("UTC")
                z += [f"DTSTART:{tb.replace(tzinfo=TZ).astimezone(u):%Y%m%dT%H%M%SZ}", f"DTEND:{te.replace(tzinfo=TZ).astimezone(u):%Y%m%dT%H%M%SZ}"]
            z.append("SUMMARY:" + ics_text(t["titel"]))
            if t["ort"]:
                z.append("LOCATION:" + ics_text(t["ort"]))
            z.append("END:VEVENT")
    z.append("END:VCALENDAR")
    return "\r\n".join(ics_falten(x) for x in z) + "\r\n"


def serie_anlegen(conn, data, user):
    """Mehrere Aufträge eines Kunden in einem Schritt. Alles oder nichts: ein Fehler rollt die ganze Serie zurück."""
    termine = data.get("termine")
    if not isinstance(termine, list) or not 1 <= len(termine) <= 100:
        raise BadRequest("Bitte 1 bis 100 Termine angeben.")
    gemeinsam = {k: data.get(k) for k in ("kunde_id", "paket_id", "ort", "sportart", "km", "spieler", "status", "notizen") if k in data}
    serie = secrets.token_hex(6)
    out = []
    for i, t in enumerate(termine, 1):
        if not isinstance(t, dict):
            raise BadRequest(f"Termin {i}: ungültige Angaben.")
        try:
            out.append(speichern(conn, "auftraege", {**gemeinsam, **{k: t.get(k) for k in ("datum", "uhrzeit", "begegnung") if t.get(k)}},
                                 None, user, fest={"serie": serie}))
        except BadRequest as e:
            raise BadRequest(f"Termin {i}: {e}")
    return out


# ---------------------------------------------------------------------------
# Push-Mitteilungen (wie send_push im Hub). Ein Nutzer, also gehen sie an alle angemeldeten Geräte.
# Inhalt nur Titel und kurzer Text, der Service Worker speichert nichts.
# ---------------------------------------------------------------------------
def vapid_keys(conn):
    raw = secret_get(conn, "vapid_d")
    if not raw:
        d, _ = webpush.ec_keypair()
        raw = format(d, "064x")
        secret_set(conn, "vapid_d", raw)
    d = int(raw, 16)
    return d, webpush.ec_pub_bytes(webpush._ec_mul(d, webpush._EC_G))


def badge_zahl(conn):
    """Zahl am App-Symbol: überfällige und heute fällige Aufgaben plus neue Mails."""
    aufgaben = conn.execute("SELECT COUNT(*) FROM aufgaben WHERE status != 'Erledigt' AND faellig != '' AND faellig <= ?",
                            (heute(),)).fetchone()[0]
    mails = conn.execute("SELECT COUNT(*) FROM mail_eingang WHERE status='neu'").fetchone()[0]
    return aufgaben + mails


def push_send_one(sub, payload, d, pub, contact):
    u = urlparse(sub["endpoint"])
    claims = {"aud": f"{u.scheme}://{u.netloc}", "exp": int(time.time()) + 12 * 3600, "sub": contact}
    head = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode()) + "." + \
        b64u(json.dumps(claims, separators=(",", ":")).encode())
    jwt = head + "." + b64u(webpush.ec_sign(d, head.encode()))
    body = webpush.webpush_encrypt(b64u_dec(sub["p256dh"]), b64u_dec(sub["auth"]), json.dumps(payload, ensure_ascii=False).encode())
    req = urllib.request.Request(sub["endpoint"], data=body, method="POST", headers={
        "Authorization": f"vapid t={jwt}, k={b64u(pub)}", "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream",
        "TTL": "86400", "Urgency": "high"})
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:  # noqa
        return 0


def send_push(title, body, url="/", tag="studio", kind="show"):
    """Push an alle Geräte. Abgelaufene Abos (404/410) werden entfernt. Rückgabe: Zahl erfolgreicher Zustellungen."""
    with db() as conn:
        subs = conn.execute("SELECT * FROM push_abos").fetchall()
        if not subs:
            return 0
        d, pub = vapid_keys(conn)
        badge = badge_zahl(conn)
    contact = SITE_URL if SITE_URL.startswith("https://") else "mailto:studio-tool@example.invalid"
    payload = {"title": str(title)[:120], "body": str(body)[:300], "url": url if str(url).startswith("/") else "/",
               "tag": str(tag)[:60], "type": kind, "badge": badge}
    ok = 0
    for row in subs:
        st = push_send_one(row, payload, d, pub, contact)
        with db() as conn:
            if st in (404, 410):
                conn.execute("DELETE FROM push_abos WHERE id=?", (row["id"],))
            elif 200 <= st < 300:
                ok += 1
                conn.execute("UPDATE push_abos SET zuletzt_ok=? WHERE id=?", (now_iso(), row["id"]))
    return ok


def send_push_async(*a, **kw):
    threading.Thread(target=lambda: send_push(*a, **kw), daemon=True).start()


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
PUBLIC_STATIC = {"style.css", "login.js", "icon.svg", "logo.png", "icon-192.png", "icon-512.png", "icon-maskable-512.png", "apple-touch-icon.png"}


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
        if path.suffix == ".webmanifest":
            ctype = "application/manifest+json"
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
        if method == "GET" and head == "kalender" and len(p) == 2 and re.fullmatch(r"[A-Za-z0-9_-]{20,80}\.ics", p[1]):
            return self.ics_abo(p[1][:-4])
        if method == "GET" and p == ["robots.txt"]:
            body = b"User-agent: *\nDisallow: /\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        if method == "GET" and head == "static" and len(p) == 2 and p[1] in PUBLIC_STATIC:
            return self.serve_under(STATIC, p[1:])
        if method == "GET" and p in (["manifest.webmanifest"], ["sw.js"]):   # App auf dem Home-Bildschirm, ohne Anmeldung abrufbar
            return self.send_file(STATIC / p[0])
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
        if head == "push":
            return self.api_push(method, p[1:])
        if method == "GET" and p == ["badge"]:
            with db() as conn:
                return self.send_json({"badge": badge_zahl(conn)})
        if method == "GET" and p == ["dashboard"]:
            with db() as conn:
                return self.send_json(dashboard(conn, heute()))
        if method == "GET" and p == ["kalender"]:
            q = parse_qs(urlparse(self.path).query)
            von, bis = (q.get("von") or [""])[0], (q.get("bis") or [""])[0]
            try:
                if date.fromisoformat(bis) - date.fromisoformat(von) > timedelta(days=400) or bis < von:
                    raise ValueError
            except ValueError:
                raise BadRequest("Zeitraum bitte als von und bis (JJJJ-MM-TT), höchstens 400 Tage.")
            with db() as conn:
                return self.send_json(kalender_eintraege(conn, von, bis))
        if p == ["kalender", "abo"] and method in ("GET", "POST", "DELETE"):
            with db() as conn:
                if method == "POST":   # neuer Link: der alte gilt danach nicht mehr. Gespeichert wird nur der Hash.
                    tok = secrets.token_urlsafe(32)
                    set_setting(conn, "ics_token_hash", token_hash(tok))
                    audit(conn, user, "Kalender-Abo neu erstellt", "settings", None, "Kalender-Abo")
                    return self.send_json({"aktiv": True, "link": f"{SITE_URL}/kalender/{tok}.ics"})
                if method == "DELETE":
                    set_setting(conn, "ics_token_hash", "")
                    audit(conn, user, "Kalender-Abo abgeschaltet", "settings", None, "Kalender-Abo")
                return self.send_json({"aktiv": bool(get_setting(conn, "ics_token_hash"))})
        if p[:2] == ["kalender", "fremd"]:
            return self.api_fremd(method, p[2:], user)
        if method == "POST" and p == ["auftraege", "serie"]:
            with db() as conn:
                return self.send_json(serie_anlegen(conn, self.read_json(), user), 201)
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
                out = speichern(conn, table, self.read_json(), old, user)
                return self.send_json(out, 200 if old else 201)

            if method == "DELETE" and old:
                # Endgültig löschen geht nur, wenn nichts daran hängt: sonst meldet die Datenbank einen Fehler
                # (IntegrityError, siehe handle_request) und alles wird zurückgerollt.
                if table == "kunden":
                    conn.execute("DELETE FROM kontakte WHERE kunde_id=?", (rid,))
                    conn.execute("UPDATE aufgaben SET kunde_id=NULL WHERE kunde_id=?", (rid,))
                    conn.execute("UPDATE termine SET kunde_id=NULL WHERE kunde_id=?", (rid,))
                if table == "pakete":
                    conn.execute("DELETE FROM aufgaben_vorlagen WHERE paket_id=?", (rid,))
                if table == "auftraege":   # nur, solange keine Zahlung erfasst ist: die offenen Zahlungen gehen mit
                    if conn.execute("SELECT 1 FROM zahlungen WHERE auftrag_id=? AND (status != 'Offen' OR IFNULL(finom_abgerechnet, 0))",
                                    (rid,)).fetchone():
                        raise BadRequest("Zu diesem Auftrag ist schon eine Zahlung erfasst. Bitte archivieren statt löschen.")
                    conn.execute("DELETE FROM zahlungen WHERE auftrag_id=?", (rid,))
                    conn.execute("DELETE FROM aufgaben WHERE auftrag_id=?", (rid,))   # die Aufgaben gehören zum Auftrag
                    conn.execute("UPDATE termine SET auftrag_id=NULL WHERE auftrag_id=?", (rid,))
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

    # -- Fremder Kalender (/api/kalender/fremd) -----------------------------
    def api_fremd(self, method, p, user):
        if method == "POST" and p == ["abrufen"]:
            fremd_abrufen()
        elif method == "PUT" and not p:
            url = str(self.read_json().get("url") or "").strip()
            if url.startswith("webcal://"):
                url = "https://" + url[len("webcal://"):]
            if not fremd_url_ok(url):
                raise BadRequest("Der Link muss mit https:// (oder webcal://) beginnen und auf einen Server im Internet zeigen.")
            with db() as conn:
                secret_set(conn, "ics_import_url", url)
                audit(conn, user, "Fremden Kalender eingetragen", "settings", None, urlparse(url).hostname or "")
            fremd_abrufen()
        elif method == "DELETE" and not p:
            with db() as conn:
                secret_set(conn, "ics_import_url", "")
                audit(conn, user, "Fremden Kalender entfernt", "settings", None, "")
            fremd_abrufen()
        elif method != "GET" or p:
            return self.send_json({"error": "Unbekannte Schnittstelle"}, 404)
        with db() as conn:
            url = secret_get(conn, "ics_import_url")
        with FREMD_LOCK:   # der Link selbst wird nie ausgegeben, nur der Servername
            return self.send_json({"aktiv": bool(url), "host": urlparse(url).hostname if url else "", "zeit": FREMD["zeit"],
                                   "fehler": FREMD["fehler"], "anzahl": len(FREMD["termine"])})

    # -- Push-Abos dieses Geräts (/api/push/...) ---------------------------
    def api_push(self, method, p):
        sub = p[0] if p else ""
        with db() as conn:
            if method == "GET" and sub == "key":
                _, pub = vapid_keys(conn)
                return self.send_json({"key": b64u(pub), "geraete": conn.execute("SELECT COUNT(*) FROM push_abos").fetchone()[0]})
            if method == "POST" and sub == "subscribe":
                data = self.read_json()
                ep, keys = str(data.get("endpoint") or ""), data.get("keys") or {}
                if not push_endpoint_ok(ep):
                    raise BadRequest("Dieser Push-Dienst wird nicht unterstützt.")
                try:
                    ec_pub_point(b64u_dec(keys.get("p256dh")))
                    if len(b64u_dec(keys.get("auth"))) != 16:
                        raise ValueError
                except (ValueError, TypeError, AttributeError):
                    raise BadRequest("Ungültiges Push-Abo.")
                conn.execute("DELETE FROM push_abos WHERE endpoint=?", (ep,))
                conn.execute("INSERT INTO push_abos (endpoint, p256dh, auth, geraet, angelegt_am) VALUES (?, ?, ?, ?, ?)",
                             (ep, keys["p256dh"], keys["auth"], (self.headers.get("User-Agent") or "")[:200], now_iso()))
                return self.send_json({"ok": True})
            if method == "POST" and sub == "unsubscribe":
                conn.execute("DELETE FROM push_abos WHERE endpoint=?", (str(self.read_json().get("endpoint") or ""),))
                return self.send_json({"ok": True})
        if method == "POST" and sub == "test":
            n = send_push("Studio-Tool", "Push-Mitteilungen funktionieren.", "/#/einstellungen", "test")
            return self.send_json({"ok": n > 0, "zugestellt": n})
        return self.send_json({"error": "Unbekannte Schnittstelle"}, 404)

    # -- Kalender-Abo (öffentlich, nur mit dem geheimen Link) -------------
    def ics_abo(self, tok):
        with db() as conn:
            soll = get_setting(conn, "ics_token_hash")
            if not soll or not hmac.compare_digest(soll, token_hash(tok)):
                time.sleep(0.3)
                return self.send_error(404)
            body = ics_kalender(conn).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/calendar; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "private, max-age=300")
        self.end_headers()
        return self.wfile.write(body)

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
    threading.Thread(target=hintergrund_loop, daemon=True).start()
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
