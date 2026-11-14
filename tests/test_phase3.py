"""Tests Phase 3: Zahlung und Anzahlung, Umsatz nach Zahldatum, Finom-Liste, CSV-Export.
Aufruf im Projektordner:  python -m unittest discover -s tests -v
"""
import threading
import unittest

from test_phase1 import Client, server


class Phase3(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.make_server("127.0.0.1", 0)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        with server.db() as conn:
            server.set_setting(conn, "twofa_pflicht", "0")
            cls.pakete = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM pakete")}
        cls.c = Client(cls.port)
        assert cls.c.login()[0] == 200

    @classmethod
    def tearDownClass(cls):
        with server.db() as conn:
            server.set_setting(conn, "twofa_pflicht", "1")
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def neu(self, table, **vals):
        st, body, _ = self.c.req("POST", f"/api/{table}", vals)
        self.assertEqual(st, 201, body)
        return body

    def auftrag(self, kunde="Zahlungen e. V.", paket="Spielershooting", **vals):
        k = self.neu("kunden", name=kunde)["id"]
        vals.setdefault("datum", "2026-11-01")
        return self.neu("auftraege", kunde_id=k, paket_id=self.pakete[paket], **vals)

    def zahlungen(self, auftrag_id):
        rows = [z for z in self.c.req("GET", "/api/zahlungen")[1] if z["auftrag_id"] == auftrag_id]
        return {z["art"]: z for z in rows}

    def setze(self, z, **vals):
        st, body, _ = self.c.req("PUT", f"/api/zahlungen/{z['id']}", vals)
        self.assertEqual(st, 200, body)
        return body

    # ---- Zahlung entsteht mit dem Auftrag ----
    def test_auftrag_bekommt_offene_zahlung(self):
        a = self.auftrag(spieler=28, km=25)
        z = self.zahlungen(a["id"])
        self.assertEqual(list(z), ["Zahlung"])
        self.assertEqual((z["Zahlung"]["betrag_cent"], z["Zahlung"]["status"]), (6720, "Offen"))
        # offene Zahlung zieht mit, wenn sich der Auftrag ändert
        self.c.req("PUT", f"/api/auftraege/{a['id']}", {"km": 30})
        self.assertEqual(self.zahlungen(a["id"])["Zahlung"]["betrag_cent"], 6870)

    def test_bezahlte_zahlung_bleibt_wie_sie_ist(self):
        a = self.auftrag(spieler=28, km=25)
        self.setze(self.zahlungen(a["id"])["Zahlung"], status="Bezahlt", zahldatum="2026-11-03", zahlart="Bar")
        self.c.req("PUT", f"/api/auftraege/{a['id']}", {"km": 100})
        self.assertEqual(self.zahlungen(a["id"])["Zahlung"]["betrag_cent"], 6720)

    def test_bezahlt_ohne_datum_bekommt_heute(self):
        a = self.auftrag()
        z = self.setze(self.zahlungen(a["id"])["Zahlung"], status="Bezahlt")
        self.assertEqual(z["zahldatum"], server.heute())

    # ---- Anzahlung ----
    def test_anzahlung_verringert_die_zahlung(self):
        a = self.auftrag(spieler=28, km=25)
        anz = self.neu("zahlungen", auftrag_id=a["id"], art="Anzahlung", betrag_cent=2000)
        self.assertEqual(anz["status"], "Offen")
        self.assertEqual(self.zahlungen(a["id"])["Zahlung"]["betrag_cent"], 4720)
        self.setze(anz, betrag_cent=3000)
        self.assertEqual(self.zahlungen(a["id"])["Zahlung"]["betrag_cent"], 3720)
        # wieder löschen: die Zahlung geht zurück auf den vollen Betrag
        self.assertEqual(self.c.req("DELETE", f"/api/zahlungen/{anz['id']}")[0], 200)
        self.assertEqual(self.zahlungen(a["id"])["Zahlung"]["betrag_cent"], 6720)

    def test_regeln_fuer_anzahlung_und_zahlung(self):
        a = self.auftrag(spieler=28, km=25)
        z = self.zahlungen(a["id"])["Zahlung"]
        for vals in ({"auftrag_id": a["id"], "art": "Zahlung", "betrag_cent": 100},
                     {"auftrag_id": a["id"], "betrag_cent": 100},
                     {"auftrag_id": a["id"], "art": "Anzahlung"},
                     {"auftrag_id": a["id"], "art": "Anzahlung", "betrag_cent": 6721},
                     {"auftrag_id": 999999, "art": "Anzahlung", "betrag_cent": 100}):
            self.assertEqual(self.c.req("POST", "/api/zahlungen", vals)[0], 400, vals)
        anz = self.neu("zahlungen", auftrag_id=a["id"], art="Anzahlung", betrag_cent=1000)
        self.assertEqual(self.c.req("POST", "/api/zahlungen", {"auftrag_id": a["id"], "art": "Anzahlung", "betrag_cent": 500})[0], 400)
        # die Zahlung selbst lässt sich weder löschen noch im Betrag ändern
        self.assertEqual(self.c.req("DELETE", f"/api/zahlungen/{z['id']}")[0], 400)
        self.assertEqual(self.setze(z, betrag_cent=1)["betrag_cent"], 5720)
        # Art und Auftrag stehen fest
        self.assertEqual(self.setze(anz, art="Zahlung", auftrag_id=1)["art"], "Anzahlung")
        # bezahlte Anzahlung ist nicht löschbar
        self.setze(anz, status="Bezahlt")
        self.assertEqual(self.c.req("DELETE", f"/api/zahlungen/{anz['id']}")[0], 400)

    def test_ungueltige_angaben(self):
        z = self.zahlungen(self.auftrag()["id"])["Zahlung"]
        for vals in ({"status": "Teilweise"}, {"zahlart": "Bitcoin"}, {"zahldatum": "03.11.2026"}, {"zahler_id": 999999}):
            self.assertEqual(self.c.req("PUT", f"/api/zahlungen/{z['id']}", vals)[0], 400, vals)

    # ---- Löschen ----
    def test_auftrag_mit_erfasster_zahlung_nicht_loeschbar(self):
        a = self.auftrag()
        self.setze(self.zahlungen(a["id"])["Zahlung"], status="Erlassen")
        st, body, _ = self.c.req("DELETE", f"/api/auftraege/{a['id']}")
        self.assertEqual(st, 400)
        self.assertIn("archivieren", body["error"])
        b = self.auftrag()
        self.neu("zahlungen", auftrag_id=b["id"], art="Anzahlung", betrag_cent=500)
        self.assertEqual(self.c.req("DELETE", f"/api/auftraege/{b['id']}")[0], 200)
        self.assertEqual(self.zahlungen(b["id"]), {})

    def test_zahler_nicht_loeschbar(self):
        a = self.auftrag()
        kontakt = self.neu("kontakte", name="Zahlt", kunde_id=a["kunde_id"])
        self.setze(self.zahlungen(a["id"])["Zahlung"], zahler_id=kontakt["id"])
        self.assertEqual(self.c.req("DELETE", f"/api/kontakte/{kontakt['id']}")[0], 400)

    # ---- Umsatz, gerechnet von Hand ----
    def test_umsatz_nach_zahldatum(self):
        # eigenes Jahr, damit andere Tests nicht mitzählen
        a = self.auftrag("Umsatz A", spieler=28, km=25)          # 67,20 €
        b = self.auftrag("Umsatz B", "Saisonspiel HSG Emden")    # 35,00 €
        c = self.auftrag("Umsatz C", "Basic")                    # 30,00 €
        self.setze(self.zahlungen(a["id"])["Zahlung"], status="Bezahlt", zahldatum="2031-01-15")
        anz = self.neu("zahlungen", auftrag_id=b["id"], art="Anzahlung", betrag_cent=1000)
        self.setze(anz, status="Bezahlt", zahldatum="2031-02-01")
        self.setze(self.zahlungen(b["id"])["Zahlung"], status="Bezahlt", zahldatum="2031-03-31")
        self.setze(self.zahlungen(c["id"])["Zahlung"], status="Erlassen", zahldatum="2031-03-01")
        st, u, _ = self.c.req("GET", "/api/umsatz?jahr=2031")
        self.assertEqual(st, 200)
        self.assertEqual(u["monate"][:4], [6720, 1000, 2500, 0])
        self.assertEqual(u["summe"], 6720 + 1000 + 2500)
        self.assertEqual(dict(map(tuple, u["kunden"])), {"Umsatz A": 6720, "Umsatz B": 3500})
        self.assertIn(2031, u["jahre"])
        self.assertEqual(self.c.req("GET", "/api/umsatz?jahr=2030")[1]["summe"], 0)

    def test_offene_summe_ohne_abgesagte(self):
        vorher = self.c.req("GET", "/api/umsatz")[1]["offen"]
        self.auftrag("Offen A", "Basic")
        abgesagt = self.auftrag("Offen B", "Pro")
        self.c.req("PUT", f"/api/auftraege/{abgesagt['id']}", {"status": "Abgesagt"})
        self.assertEqual(self.c.req("GET", "/api/umsatz")[1]["offen"], vorher + 3000)

    # ---- Finom ----
    def test_noch_abzurechnen_erst_wenn_bezahlt(self):
        a = self.auftrag("Finom e. V.", spieler=28, km=25, begegnung="Mannschaftsfotos")
        z = self.zahlungen(a["id"])["Zahlung"]
        ids = lambda: [x["id"] for x in self.c.req("GET", "/api/abrechnen")[1]]   # noqa: E731
        self.assertNotIn(z["id"], ids())
        self.setze(z, status="Bezahlt", zahldatum="2026-11-05")
        eintrag = [x for x in self.c.req("GET", "/api/abrechnen")[1] if x["id"] == z["id"]][0]
        self.assertEqual(eintrag["kunde"], "Finom e. V.")
        self.assertEqual(eintrag["text"], "Spielershooting: Mannschaftsfotos, 01.11.2026\n"
                                          "Zusatzspieler: 3 × 0,90 € = 2,70 €\n"
                                          "Anfahrt: 15 km × 0,30 € = 4,50 €\n"
                                          "Betrag: 67,20 €")
        self.setze(z, finom_abgerechnet=1, finom_rechnungsnr="RE-2026-001")
        self.assertNotIn(z["id"], ids())

    def test_leistungstext_mit_anzahlung_und_finom_text(self):
        a = self.auftrag("Text e. V.", "Pro", begegnung="Heimspiel")
        pid = self.pakete["Pro"]
        self.c.req("PUT", f"/api/pakete/{pid}", {"finom_text": "Sportfotografie Paket Pro"})
        self.addCleanup(self.c.req, "PUT", f"/api/pakete/{pid}", {"finom_text": ""})
        anz = self.neu("zahlungen", auftrag_id=a["id"], art="Anzahlung", betrag_cent=1500)
        self.setze(anz, status="Bezahlt")
        self.setze(self.zahlungen(a["id"])["Zahlung"], status="Bezahlt")
        texte = {x["art"]: x["text"] for x in self.c.req("GET", "/api/abrechnen")[1] if x["auftrag_id"] == a["id"]}
        self.assertEqual(texte["Anzahlung"], "Anzahlung für Sportfotografie Paket Pro: Heimspiel, 01.11.2026\nBetrag: 15,00 €")
        self.assertEqual(texte["Zahlung"], "Sportfotografie Paket Pro: Heimspiel, 01.11.2026\n"
                                           "abzüglich Anzahlung: 15,00 €\nBetrag: 30,00 €")

    # ---- CSV ----
    def test_csv_export(self):
        a = self.auftrag("=HYPERLINK(\"x\")", spieler=28, km=25, begegnung="Export")
        self.setze(self.zahlungen(a["id"])["Zahlung"], status="Bezahlt", zahldatum="2032-06-01", zahlart="PayPal")
        st, text, r = self.c.req("GET", "/api/umsatz/csv?jahr=2032")
        self.assertEqual(st, 200)
        self.assertIn("text/csv", r.getheader("Content-Type"))
        self.assertIn('filename="umsatz-2032.csv"', r.getheader("Content-Disposition"))
        zeilen = text.lstrip("﻿").splitlines()
        self.assertTrue(text.startswith("﻿"))
        self.assertEqual(zeilen[0], "Zahldatum;Kunde;Auftrag;Datum Auftrag;Art;Zahler;Zahlart;Betrag;Finom-Rechnung")
        self.assertEqual(zeilen[1], "01.06.2032;\"'=HYPERLINK(\"\"x\"\")\";Export;01.11.2026;Zahlung;;PayPal;67,20;")
        self.assertEqual(len(zeilen), 2)
        self.assertEqual(Client(self.port).req("GET", "/api/umsatz/csv?jahr=2032")[0], 401)

    # ---- Bestand vor Phase 3 ----
    def test_alte_auftraege_bekommen_zahlung_beim_start(self):
        a = self.auftrag(spieler=28, km=25)
        with server.db() as conn:
            conn.execute("DELETE FROM zahlungen WHERE auftrag_id=?", (a["id"],))
        server.init_db()
        self.assertEqual(self.zahlungen(a["id"])["Zahlung"]["betrag_cent"], 6720)


if __name__ == "__main__":
    unittest.main()
