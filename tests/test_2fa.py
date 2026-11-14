"""Tests Zwei-Faktor-Anmeldung (TOTP): Norm-Prüfwert, Pflicht, Einrichtung, Login in zwei Schritten,
Wiederherstellungscodes, Schutz gegen doppelt benutzte Codes, Notfall-Reset.
Nutzt ein eigenes Konto "zweit", damit die anderen Tests unberührt bleiben.
"""
import time
import unittest

import test_phase1
from test_phase1 import Client, server

PW = "zweitpasswort-123"


def code_now(secret, offset=0):
    return server.totp_code(secret, int(time.time() // 30) + offset)


class ZweiFaktor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.make_server("127.0.0.1", 0)
        cls.port = cls.httpd.server_address[1]
        test_phase1.threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        try:
            server.create_user("zweit", PW)
        except ValueError:
            pass

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        server.twofa_reset("zweit")
        with server.FAILED_LOCK:
            server.FAILED_IPS.clear()
            server.GHOST_FAILS.clear()
            server.TWOFA_TICKETS.clear()
        with server.db() as conn:
            conn.execute("UPDATE users SET fail_count=0, fail_first=NULL, locked_until=NULL")

    def einrichten(self):
        c = Client(self.port)
        self.assertEqual(c.login("zweit", PW)[0], 200)
        st, s, _ = c.req("POST", "/api/me/2fa/setup", {"password": PW})
        self.assertEqual(st, 200)
        st, r, _ = c.req("POST", "/api/me/2fa/enable", {"code": code_now(s["secret"])})
        self.assertEqual(st, 200)
        return c, s["secret"], r["codes"]

    # ---- Rechnung ----
    def test_rfc6238_pruefwert(self):
        # RFC 6238 Anhang B: Schlüssel "12345678901234567890", Zeit 59 s, SHA1, 8 Ziffern -> 94287082
        secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
        self.assertEqual(server.totp_code(secret, 59 // 30, digits=8), "94287082")
        self.assertEqual(server.totp_code(secret, 1111111109 // 30, digits=8), "07081804")
        self.assertEqual(server.totp_code(secret, 59 // 30), "287082")

    def test_zeitfenster_und_wiederholung(self):
        secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
        now = 1_000_000_000
        t = now // 30
        self.assertEqual(server.totp_match(secret, server.totp_code(secret, t), 0, now), t)
        self.assertEqual(server.totp_match(secret, server.totp_code(secret, t - 1), 0, now), t - 1)
        self.assertEqual(server.totp_match(secret, server.totp_code(secret, t - 2), 0, now), 0)
        self.assertEqual(server.totp_match(secret, server.totp_code(secret, t), t, now), 0)   # schon benutzt
        self.assertEqual(server.totp_match(secret, "abc", 0, now), 0)

    # ---- Pflicht ----
    def test_pflicht_sperrt_alles_ausser_sicherheit(self):
        c = Client(self.port)
        c.login("zweit", PW)
        st, me, _ = c.req("GET", "/api/me")
        self.assertEqual(st, 200)
        self.assertTrue(me["user"]["must_2fa"])
        st, body, _ = c.req("GET", "/api/pakete")
        self.assertEqual(st, 403)
        self.assertTrue(body["need_2fa"])
        self.assertEqual(c.req("GET", "/api/me/2fa")[0], 200)

    def test_einrichten_braucht_passwort(self):
        c = Client(self.port)
        c.login("zweit", PW)
        self.assertEqual(c.req("POST", "/api/me/2fa/setup", {"password": "falsch-falsch"})[0], 400)

    def test_einrichten_falscher_code(self):
        c = Client(self.port)
        c.login("zweit", PW)
        st, s, _ = c.req("POST", "/api/me/2fa/setup", {"password": PW})
        self.assertTrue(s["uri"].startswith("otpauth://totp/Studio-Tool"))
        bad = "000000" if code_now(s["secret"]) != "000000" else "111111"
        self.assertEqual(c.req("POST", "/api/me/2fa/enable", {"code": bad})[0], 400)

    def test_einrichten_und_freigabe(self):
        c, secret, codes = self.einrichten()
        self.assertEqual(len(codes), 10)
        self.assertEqual(c.req("GET", "/api/pakete")[0], 200)
        with server.db() as conn:
            row = server.twofa_row(conn, conn.execute("SELECT id FROM users WHERE username='zweit'").fetchone()[0])
        for code in codes:   # nur Hashes gespeichert
            self.assertNotIn(code.replace("-", ""), row["recovery"])

    # ---- Login in zwei Schritten ----
    def test_login_mit_code(self):
        _, secret, _ = self.einrichten()
        c = Client(self.port)
        st, body, r = c.login("zweit", PW)
        self.assertEqual(st, 200)
        self.assertTrue(body["need_2fa"])
        self.assertIsNone(r.getheader("Set-Cookie"))           # noch keine Sitzung
        self.assertEqual(c.req("GET", "/api/me")[0], 401)
        st, _, _ = c.req("POST", "/auth/login2", {"ticket": body["ticket"], "code": code_now(secret, 1)})
        self.assertEqual(st, 200)
        self.assertEqual(c.req("GET", "/api/pakete")[0], 200)

    def test_code_nur_einmal(self):
        _, secret, _ = self.einrichten()
        code = code_now(secret, 1)
        c = Client(self.port)
        _, body, _ = c.login("zweit", PW)
        self.assertEqual(c.req("POST", "/auth/login2", {"ticket": body["ticket"], "code": code})[0], 200)
        c2 = Client(self.port)
        _, body2, _ = c2.login("zweit", PW)
        self.assertEqual(c2.req("POST", "/auth/login2", {"ticket": body2["ticket"], "code": code})[0], 401)

    def test_falscher_code_und_ticket_verfaellt(self):
        _, secret, _ = self.einrichten()
        c = Client(self.port)
        _, body, _ = c.login("zweit", PW)
        good = {code_now(secret, k) for k in (-1, 0, 1)}
        bad = next(x for x in ("000000", "111111", "222222", "333333") if x not in good)
        self.assertEqual(c.req("POST", "/auth/login2", {"ticket": body["ticket"], "code": bad})[0], 401)
        self.assertEqual(c.req("POST", "/auth/login2", {"ticket": "erfunden", "code": bad})[0], 400)

    def test_fuenf_falsche_codes_sperren(self):
        _, secret, _ = self.einrichten()
        c = Client(self.port)
        _, body, _ = c.login("zweit", PW)
        good = {code_now(secret, k) for k in (-1, 0, 1)}
        bad = next(x for x in ("000000", "111111", "222222", "333333") if x not in good)
        res = [c.req("POST", "/auth/login2", {"ticket": body["ticket"], "code": bad})[0] for _ in range(5)]
        self.assertEqual(res[-1], 429)
        self.assertEqual(c.login("zweit", PW)[0], 429)          # Konto gesperrt

    def test_wiederherstellungscode_einmal(self):
        _, _, codes = self.einrichten()
        c = Client(self.port)
        _, body, _ = c.login("zweit", PW)
        st, res, _ = c.req("POST", "/auth/login2", {"ticket": body["ticket"], "code": codes[0].upper()})
        self.assertEqual(st, 200)
        self.assertEqual(res["recovery_left"], 9)
        c2 = Client(self.port)
        _, body2, _ = c2.login("zweit", PW)
        self.assertEqual(c2.req("POST", "/auth/login2", {"ticket": body2["ticket"], "code": codes[0]})[0], 401)

    def test_ausschalten_bei_pflicht_verboten(self):
        c, _, _ = self.einrichten()
        self.assertEqual(c.req("POST", "/api/me/2fa/disable", {"password": PW})[0], 400)

    def test_notfall_reset(self):
        c, _, _ = self.einrichten()
        server.twofa_reset("zweit")
        self.assertEqual(c.req("GET", "/api/me")[0], 401)       # alle Sitzungen beendet
        c2 = Client(self.port)
        st, body, _ = c2.login("zweit", PW)
        self.assertEqual(st, 200)
        self.assertNotIn("need_2fa", body)


if __name__ == "__main__":
    unittest.main()
