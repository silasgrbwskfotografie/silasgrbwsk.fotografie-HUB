"""Tests Phase 6: Startseite, Kalender, Kalender-Abo (ICS), Serien.
Aufruf im Projektordner:  python -m unittest discover -s tests -v
"""
import threading
import unittest
from datetime import date, timedelta

from test_phase1 import Client, server


def tage(n):
    return (date.fromisoformat(server.heute()) + timedelta(days=n)).isoformat()


class Ics(unittest.TestCase):
    def test_text_und_falten(self):
        self.assertEqual(server.ics_text("a,b;c\\d\ne"), r"a\,b\;c\\d\ne")
        lang = "SUMMARY:" + "Ä" * 60
        teile = server.ics_falten(lang).split("\r\n")
        self.assertTrue(all(len(t.encode()) <= 75 for t in teile))
        self.assertTrue(all(t.startswith(" ") for t in teile[1:]))
        self.assertEqual("".join(t[1:] if i else t for i, t in enumerate(teile)), lang)


class Phase6(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.make_server("127.0.0.1", 0)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        with server.db() as conn:
            server.set_setting(conn, "twofa_pflicht", "0")
            cls.paket = conn.execute("SELECT id FROM pakete WHERE name='Pro'").fetchone()[0]
        cls.c = Client(cls.port)
        assert cls.c.login()[0] == 200
        cls.kunde = cls.c.req("POST", "/api/kunden", {"name": "Kalender e. V."})[1]

    @classmethod
    def tearDownClass(cls):
        with server.db() as conn:
            server.set_setting(conn, "twofa_pflicht", "1")
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def auftrag(self, datum, **v):
        st, a, _ = self.c.req("POST", "/api/auftraege", {"kunde_id": self.kunde["id"], "paket_id": self.paket, "datum": datum, **v})
        self.assertEqual(st, 201, a)
        return a

    # ---- Startseite ----
    def test_dashboard(self):
        bald = self.auftrag(tage(3), begegnung="Bald, mit Komma; und Semikolon", uhrzeit="18:30", ort="Emden")
        spaeter = self.auftrag(tage(20))
        ueber = self.auftrag(tage(-10), status="Fotografiert")
        st, d, _ = self.c.req("POST", "/api/vertraege", {"kunde_id": self.kunde["id"], "art": "Sponsoring", "beginn": tage(-300),
                                                          "ende": tage(40), "kuendigungsfrist_wert": 2, "kuendigungsfrist_einheit": "Wochen"})
        db = self.c.req("GET", "/api/dashboard")[1]
        ids = [a["id"] for a in db["termine"]]
        self.assertIn(bald["id"], ids)
        self.assertNotIn(spaeter["id"], ids)
        self.assertIn(ueber["id"], [a["id"] for a in db["ueberfaellig"]])
        self.assertIn(d["id"], [v["id"] for v in db["vertraege"]])
        self.assertEqual(db["offen_summe"], sum(z["betrag_cent"] for z in db["offen"]))
        self.assertGreaterEqual(db["offen_summe"], 3 * 4500)
        self.assertIn("umsatz_jahr", db)

    # ---- Kalender ----
    def test_kalender_zeitraum(self):
        a = self.auftrag("2033-03-10", begegnung="März")
        self.auftrag("2033-04-10", begegnung="April")
        e = self.c.req("GET", "/api/kalender?von=2033-03-01&bis=2033-03-31")[1]
        self.assertIn(("auftrag", a["id"]), [(x["art"], x["id"]) for x in e])
        self.assertNotIn("April", [x["titel"] for x in e])
        for q in ("von=2033-03-01", "von=2033-03-31&bis=2033-03-01", "von=2033-01-01&bis=2035-01-01", "von=x&bis=y"):
            self.assertEqual(self.c.req("GET", "/api/kalender?" + q)[0], 400, q)

    # ---- Kalender-Abo ----
    def test_ics_abo(self):
        a = self.auftrag(tage(5), begegnung="HSG gegen TuS, Heimspiel", uhrzeit="19:00", ort="Emden")
        self.c.req("PUT", f"/api/zahlungen/{[z for z in self.c.req('GET', '/api/zahlungen')[1] if z['auftrag_id'] == a['id']][0]['id']}", {})
        self.assertFalse(self.c.req("GET", "/api/kalender/abo")[1]["aktiv"])
        st, r, _ = self.c.req("POST", "/api/kalender/abo", {})
        self.assertTrue(r["aktiv"])
        pfad = r["link"].split("127.0.0.1:" + str(server.PORT))[-1] if "127.0.0.1" in r["link"] else "/" + r["link"].split("/", 3)[3]
        fremd = Client(self.port)
        st, text, resp = fremd.req("GET", pfad, csrf=False)
        self.assertEqual(st, 200)
        self.assertIn("text/calendar", resp.getheader("Content-Type"))
        self.assertIn(r"SUMMARY:HSG gegen TuS\, Heimspiel", text)
        self.assertIn(f"UID:auftrag-{a['id']}@", text)
        self.assertIn("LOCATION:Emden", text)
        self.assertNotIn("€", text)
        self.assertNotIn("45,00", text)
        self.assertNotIn("4500", text)
        self.assertTrue(text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n"))
        with server.db() as conn:   # nur der Hash ist gespeichert
            self.assertNotIn(pfad.split("/")[-1][:-4], str([tuple(x) for x in conn.execute("SELECT * FROM settings")]))
        # falscher Link, neuer Link macht den alten ungültig, Abschalten
        self.assertEqual(fremd.req("GET", "/kalender/" + "x" * 43 + ".ics", csrf=False)[0], 404)
        neu = self.c.req("POST", "/api/kalender/abo", {})[1]["link"]
        self.assertEqual(fremd.req("GET", pfad, csrf=False)[0], 404)
        self.assertEqual(fremd.req("GET", "/" + neu.split("/", 3)[3], csrf=False)[0], 200)
        self.c.req("DELETE", "/api/kalender/abo")
        self.assertEqual(fremd.req("GET", "/" + neu.split("/", 3)[3], csrf=False)[0], 404)

    # ---- Serien ----
    def test_serie(self):
        st, r, _ = self.c.req("POST", "/api/auftraege/serie", {"kunde_id": self.kunde["id"], "paket_id": self.paket, "ort": "Halle", "km": 30,
                                                                "termine": [{"datum": "2034-01-10", "begegnung": "Spieltag 1"},
                                                                            {"datum": "2034-01-17", "uhrzeit": "15:00", "begegnung": "Spieltag 2"}]})
        self.assertEqual(st, 201, r)
        self.assertEqual(len(r), 2)
        self.assertEqual(r[0]["serie"], r[1]["serie"])
        self.assertEqual((r[1]["ort"], r[1]["uhrzeit"], r[1]["betrag_cent"]), ("Halle", "15:00", 4500 + 20 * 30))
        self.assertEqual(len([z for z in self.c.req("GET", "/api/zahlungen")[1] if z["auftrag_id"] in (r[0]["id"], r[1]["id"])]), 2)

    def test_serie_alles_oder_nichts(self):
        vorher = len(self.c.req("GET", "/api/auftraege")[1])
        st, r, _ = self.c.req("POST", "/api/auftraege/serie", {"kunde_id": self.kunde["id"], "paket_id": self.paket,
                                                                "termine": [{"datum": "2034-02-01"}, {"datum": "kaputt"}]})
        self.assertEqual(st, 400)
        self.assertIn("Termin 2", r["error"])
        self.assertEqual(len(self.c.req("GET", "/api/auftraege")[1]), vorher)
        for t in ([], "x", [{"datum": "2034-01-01"}] * 101, ["x"]):
            self.assertEqual(self.c.req("POST", "/api/auftraege/serie", {"kunde_id": self.kunde["id"], "paket_id": self.paket, "termine": t})[0], 400)

    def test_ohne_anmeldung(self):
        fremd = Client(self.port)
        for pfad in ("/api/dashboard", "/api/kalender?von=2030-01-01&bis=2030-01-31", "/api/kalender/abo"):
            self.assertEqual(fremd.req("GET", pfad)[0], 401)


if __name__ == "__main__":
    unittest.main()
