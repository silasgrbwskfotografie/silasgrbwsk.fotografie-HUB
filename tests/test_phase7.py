"""Tests Phase 7: Web Push (Verschlüsselung nach RFC 8291, VAPID), Push-Abos, App-Manifest.
Aufruf im Projektordner:  python -m unittest discover -s tests -v
"""
import json
import threading
import unittest
from unittest import mock

import webpush
from test_phase1 import Client, server


class Krypto(unittest.TestCase):
    def test_rfc8291_anhang_a(self):
        """Beispiel aus RFC 8291, Anhang A: gleicher Schlüssel und Salt ergeben genau den Nachrichtenkörper aus dem RFC."""
        ua_public = webpush.b64u_dec("BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4")
        auth = webpush.b64u_dec("BTBZMqHH6r4Tts7J_aSIgg")
        as_priv = int.from_bytes(webpush.b64u_dec("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"), "big")
        salt = webpush.b64u_dec("DGv6ra1nlYgDCS1FRnbzlw")
        body = webpush.webpush_encrypt(ua_public, auth, b"When I grow up, I want to be a watermelon", as_priv, salt)
        self.assertEqual(webpush.b64u(body),
                         "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_y"
                         "l95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN")

    def test_signatur(self):
        d, pub = webpush.ec_keypair()
        sig = webpush.ec_sign(d, b"nachricht")
        self.assertTrue(webpush.ec_verify(pub, b"nachricht", sig))
        self.assertFalse(webpush.ec_verify(pub, b"andere", sig))

    def test_nur_bekannte_push_dienste(self):
        for ok in ("https://fcm.googleapis.com/fcm/send/abc", "https://web.push.apple.com/QGx", "https://updates.push.services.mozilla.com/wpush/v2/x"):
            self.assertTrue(webpush.push_endpoint_ok(ok), ok)
        for bad in ("http://fcm.googleapis.com/x", "https://evil.example/x", "https://googleapis.com.evil.example/x", "https://127.0.0.1/x", ""):
            self.assertFalse(webpush.push_endpoint_ok(bad), bad)


class Phase7(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.make_server("127.0.0.1", 0)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        with server.db() as conn:
            server.set_setting(conn, "twofa_pflicht", "0")
        cls.c = Client(cls.port)
        assert cls.c.login()[0] == 200

    @classmethod
    def tearDownClass(cls):
        with server.db() as conn:
            server.set_setting(conn, "twofa_pflicht", "1")
            conn.execute("DELETE FROM push_abos")
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def abo(self, endpoint="https://web.push.apple.com/geraet-1"):
        _, pub = webpush.ec_keypair()
        return {"endpoint": endpoint, "keys": {"p256dh": webpush.b64u(webpush.ec_pub_bytes(pub)), "auth": webpush.b64u(b"0123456789abcdef")}}

    def test_app_dateien_ohne_anmeldung(self):
        fremd = Client(self.port)
        st, m, r = fremd.req("GET", "/manifest.webmanifest", csrf=False)
        self.assertEqual((st, r.getheader("Content-Type")), (200, "application/manifest+json"))
        m = json.loads(m) if isinstance(m, str) else m
        self.assertEqual((m["start_url"], m["display"]), ("/", "standalone"))
        self.assertEqual(fremd.req("GET", "/sw.js", csrf=False)[0], 200)
        for icon in m["icons"]:
            self.assertEqual(fremd.req("GET", icon["src"], csrf=False)[0], 200, icon["src"])

    def test_abo_anlegen_und_entfernen(self):
        st, k, _ = self.c.req("GET", "/api/push/key")
        self.assertEqual(len(webpush.b64u_dec(k["key"])), 65)
        self.assertEqual(self.c.req("GET", "/api/push/key")[1]["key"], k["key"])   # Schlüssel bleibt gleich
        a = self.abo()
        self.assertEqual(self.c.req("POST", "/api/push/subscribe", a)[0], 200)
        self.assertEqual(self.c.req("POST", "/api/push/subscribe", a)[0], 200)   # zweimal: kein doppeltes Abo
        with server.db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM push_abos WHERE endpoint=?", (a["endpoint"],)).fetchone()[0], 1)
        self.c.req("POST", "/api/push/unsubscribe", {"endpoint": a["endpoint"]})
        with server.db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM push_abos WHERE endpoint=?", (a["endpoint"],)).fetchone()[0], 0)

    def test_ungueltige_abos(self):
        for a in ({**self.abo(), "endpoint": "https://evil.example/x"}, {**self.abo(), "keys": {"p256dh": "kaputt", "auth": "x"}},
                  {**self.abo(), "keys": {"p256dh": self.abo()["keys"]["p256dh"], "auth": webpush.b64u(b"kurz")}}, {"endpoint": "https://web.push.apple.com/x"}):
            self.assertEqual(self.c.req("POST", "/api/push/subscribe", a)[0], 400)
        self.assertEqual(Client(self.port).req("GET", "/api/push/key")[0], 401)

    def test_senden_mit_vapid_und_aufraeumen(self):
        """Ohne echtes Netz: urlopen wird ersetzt. Geprüft wird der VAPID-Kopf (Signatur mit dem Server-Schlüssel) und dass 410 das Abo löscht."""
        with server.db() as conn:
            conn.execute("DELETE FROM push_abos")
        self.c.req("POST", "/api/push/subscribe", self.abo("https://web.push.apple.com/gut"))
        self.c.req("POST", "/api/push/subscribe", self.abo("https://fcm.googleapis.com/fcm/send/weg"))
        gesehen = []

        class Antwort:
            status = 201
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def urlopen(req, timeout=0):
            gesehen.append(req)
            if "weg" in req.full_url:
                raise server.urllib.error.HTTPError(req.full_url, 410, "Gone", {}, None)
            return Antwort()

        with mock.patch.object(server.urllib.request, "urlopen", urlopen):
            self.assertEqual(server.send_push("Titel", "Text", "/#/aufgaben"), 1)
        self.assertEqual(len(gesehen), 2)
        req = [r for r in gesehen if "gut" in r.full_url][0]
        self.assertEqual(req.get_header("Content-encoding"), "aes128gcm")
        auth = req.get_header("Authorization")
        jwt, k = auth[len("vapid t="):].split(", k=")
        head, claims, sig = jwt.split(".")
        with server.db() as conn:
            _, pub = server.vapid_keys(conn)
        self.assertEqual(k, webpush.b64u(pub))
        self.assertTrue(webpush.ec_verify(webpush.ec_pub_point(pub), f"{head}.{claims}".encode(), webpush.b64u_dec(sig)))
        self.assertEqual(json.loads(webpush.b64u_dec(claims))["aud"], "https://web.push.apple.com")
        with server.db() as conn:
            self.assertEqual([r[0] for r in conn.execute("SELECT endpoint FROM push_abos")], ["https://web.push.apple.com/gut"])

    def test_badge(self):
        st, b, _ = self.c.req("GET", "/api/badge")
        self.assertEqual(st, 200)
        self.assertIsInstance(b["badge"], int)

    def test_vapid_schluessel_nie_ueber_die_api(self):
        with server.db() as conn:
            d = server.secret_get(conn, "vapid_d") or format(server.vapid_keys(conn)[0], "064x")
        for pfad in ("/api/push/key", "/api/einstellungen", "/api/me", "/api/protokoll"):
            self.assertNotIn(d, json.dumps(self.c.req("GET", pfad)[1]))


if __name__ == "__main__":
    unittest.main()
