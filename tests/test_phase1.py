"""Tests Phase 1: Schema, Seed, Anmeldung, Sperre, Schutz-Header, Formatierung.
Aufruf im Projektordner:  python -m unittest discover -s tests -v
"""
import http.client
import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="studio-test-")
os.environ["STUDIO_DATA"] = TMP
os.environ["STUDIO_ADMIN_USER"] = "silas"
os.environ["STUDIO_ADMIN_PASSWORD"] = "testpasswort-123"
os.environ.pop("STUDIO_SECURE_COOKIES", None)
os.environ.pop("STUDIO_TRUST_PROXY", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402

server.time.sleep = lambda s: None   # Bremse bei Fehlversuchen im Test überspringen


class Client:
    def __init__(self, port):
        self.port = port
        self.cookie = ""

    def req(self, method, path, body=None, csrf=True):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {}
        if csrf:
            headers["X-Studio"] = "1"
        if self.cookie:
            headers["Cookie"] = self.cookie
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        c.request(method, path, body=data, headers=headers)
        r = c.getresponse()
        raw = r.read()
        sc = r.getheader("Set-Cookie")
        if sc:
            self.cookie = sc.split(";")[0]
        try:
            payload = json.loads(raw) if raw else None
        except ValueError:
            payload = raw.decode("utf-8", "replace")
        c.close()
        return r.status, payload, r

    def login(self, user="silas", pw="testpasswort-123"):
        return self.req("POST", "/auth/login", {"username": user, "password": pw})


class Phase1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.make_server("127.0.0.1", 0)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        with server.FAILED_LOCK:
            server.FAILED_IPS.clear()
            server.GHOST_FAILS.clear()
        with server.db() as conn:
            conn.execute("UPDATE users SET fail_count=0, fail_first=NULL, locked_until=NULL")

    # ---- Schema und Seed ----
    def test_alle_tabellen_da(self):
        conn = sqlite3.connect(Path(TMP) / "studio.db")
        have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        for t in list(server.TABLES) + ["users", "sessions", "secrets", "settings", "audit_log"]:
            self.assertIn(t, have)

    def test_seed_pakete_in_cent(self):
        with server.db() as conn:
            p = {r["name"]: dict(r) for r in conn.execute("SELECT * FROM pakete")}
        self.assertEqual(p["Basic"]["grundpreis_cent"], 3000)
        self.assertEqual(p["Pro"]["grundpreis_cent"], 4500)
        self.assertEqual(p["Spielershooting"]["grundpreis_cent"], 6000)
        self.assertEqual(p["Spielershooting"]["inkl_spieler"], 25)
        self.assertEqual(p["Spielershooting"]["zusatzspieler_cent"], 90)
        self.assertEqual(p["Saisonspiel HSG Emden"]["grundpreis_cent"], 3500)

    def test_seed_aendert_nichts_beim_neustart(self):
        with server.db() as conn:
            conn.execute("UPDATE pakete SET grundpreis_cent=3300 WHERE name='Basic'")
            server.set_setting(conn, "anfahrt_frei_km", "12")
        server.init_db()
        with server.db() as conn:
            self.assertEqual(conn.execute("SELECT grundpreis_cent FROM pakete WHERE name='Basic'").fetchone()[0], 3300)
            self.assertEqual(server.get_setting(conn, "anfahrt_frei_km"), "12")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM pakete").fetchone()[0], 4)
            conn.execute("UPDATE pakete SET grundpreis_cent=3000 WHERE name='Basic'")
            server.set_setting(conn, "anfahrt_frei_km", "10")

    def test_seed_einstellungen(self):
        with server.db() as conn:
            self.assertEqual(server.get_setting(conn, "anfahrt_cent_je_km"), "30")
            self.assertEqual(server.get_setting(conn, "lieferfrist_tage"), "5")
            self.assertEqual(server.get_setting(conn, "picdrop_tage"), "30")
            self.assertEqual(server.get_setting(conn, "umsatzgrenze_cent"), "")

    # ---- öffentlich ----
    def test_healthz(self):
        st, body, _ = Client(self.port).req("GET", "/healthz", csrf=False)
        self.assertEqual(st, 200)
        self.assertTrue(body["ok"])

    def test_ohne_login_gesperrt(self):
        c = Client(self.port)
        self.assertEqual(c.req("GET", "/api/me")[0], 401)
        self.assertEqual(c.req("GET", "/api/pakete")[0], 401)
        st, _, r = c.req("GET", "/", csrf=False)
        self.assertEqual(st, 302)
        self.assertEqual(r.getheader("Location"), "/login")
        self.assertEqual(c.req("GET", "/static/app.js", csrf=False)[0], 302)
        self.assertEqual(c.req("GET", "/login", csrf=False)[0], 200)
        self.assertEqual(c.req("GET", "/static/style.css", csrf=False)[0], 200)

    def test_head_anfrage(self):
        st, body, r = Client(self.port).req("HEAD", "/", csrf=False)
        self.assertEqual(st, 302)
        st, body, r = Client(self.port).req("HEAD", "/healthz", csrf=False)
        self.assertEqual(st, 200)
        self.assertFalse(body)

    def test_sicherheits_header(self):
        _, _, r = Client(self.port).req("GET", "/login", csrf=False)
        self.assertIn("frame-ancestors 'none'", r.getheader("Content-Security-Policy"))
        self.assertEqual(r.getheader("X-Robots-Tag"), "noindex, nofollow")
        self.assertEqual(r.getheader("X-Frame-Options"), "DENY")

    def test_pfad_ausbruch(self):
        c = Client(self.port)
        c.login()
        self.assertIn(c.req("GET", "/static/../server.py", csrf=False)[0], (403, 404))
        self.assertIn(c.req("GET", "/static/%2e%2e/server.py", csrf=False)[0], (403, 404))

    # ---- Anmeldung ----
    def test_login_und_logout(self):
        c = Client(self.port)
        st, body, r = c.login()
        self.assertEqual(st, 200)
        sc = r.getheader("Set-Cookie")
        self.assertIn("HttpOnly", sc)
        self.assertIn("SameSite=Lax", sc)
        st, me, _ = c.req("GET", "/api/me")
        self.assertEqual(st, 200)
        self.assertEqual(me["user"]["username"], "silas")
        self.assertEqual(c.req("GET", "/", csrf=False)[0], 200)
        self.assertEqual(c.req("POST", "/auth/logout")[0], 200)
        self.assertEqual(c.req("GET", "/api/me")[0], 401)

    def test_token_nur_als_hash_gespeichert(self):
        c = Client(self.port)
        c.login()
        tok = c.cookie.split("=", 1)[1]
        with server.db() as conn:
            rows = [r[0] for r in conn.execute("SELECT token_hash FROM sessions")]
        self.assertNotIn(tok, rows)
        self.assertIn(server.token_hash(tok), rows)

    def test_falsches_passwort(self):
        st, body, _ = Client(self.port).login(pw="falsch-falsch")
        self.assertEqual(st, 401)
        self.assertIn("falsch", body["error"])

    def test_sperre_nach_5_fehlversuchen(self):
        c = Client(self.port)
        for _ in range(4):
            self.assertEqual(c.login(pw="falsch-falsch")[0], 401)
        self.assertEqual(c.login(pw="falsch-falsch")[0], 429)
        # auch mit richtigem Passwort gesperrt
        self.assertEqual(c.login()[0], 429)
        with server.db() as conn:
            self.assertTrue(conn.execute("SELECT 1 FROM audit_log WHERE action='Konto gesperrt'").fetchone())

    def test_unbekannter_name_verhaelt_sich_gleich(self):
        c = Client(self.port)
        for _ in range(4):
            self.assertEqual(c.login(user="gibtsnicht", pw="x" * 12)[0], 401)
        self.assertEqual(c.login(user="gibtsnicht", pw="x" * 12)[0], 429)

    def test_login_ohne_schutz_header(self):
        st, _, _ = Client(self.port).req("POST", "/auth/login", {"username": "silas", "password": "testpasswort-123"}, csrf=False)
        self.assertEqual(st, 403)

    def test_schreiben_ohne_schutz_header(self):
        c = Client(self.port)
        c.login()
        self.assertEqual(c.req("POST", "/api/me", {}, csrf=False)[0], 403)

    def test_api_gibt_keine_geheimnisse_aus(self):
        c = Client(self.port)
        c.login()
        with server.db() as conn:
            server.secret_set(conn, "test", "geheim-xyz")
        for path in ("/api/me", "/api/pakete", "/api/einstellungen", "/api/secrets", "/api/users"):
            _, body, _ = c.req("GET", path)
            self.assertNotIn("geheim-xyz", json.dumps(body))
            self.assertNotIn("scrypt$", json.dumps(body))

    # ---- Formatierung ----
    def test_euro_und_datum(self):
        self.assertEqual(server.eur_text(6720), "67,20 €")
        self.assertEqual(server.eur_text(2), "0,02 €")
        self.assertEqual(server.eur_text(123456789), "1.234.567,89 €")
        self.assertEqual(server.eur_text(-90), "-0,90 €")
        self.assertEqual(server.datum_text("2026-11-01"), "01.11.2026")
        self.assertEqual(server.datum_text("kaputt"), "")

    def test_passwort_mindestlaenge(self):
        with self.assertRaises(ValueError):
            server.create_user("kurz", "123")


if __name__ == "__main__":
    unittest.main()
