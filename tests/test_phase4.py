"""Tests Phase 4: Lieferfrist-Ampel, Galerie-Links mit Ablaufdatum, Nachrichtenvorlagen.
Aufruf im Projektordner:  python -m unittest discover -s tests -v
"""
import threading
import unittest
from datetime import date, timedelta

from test_phase1 import Client, server


def tage(n):
    return (date.fromisoformat(server.heute()) + timedelta(days=n)).isoformat()


class Fristenlogik(unittest.TestCase):
    """lieferampel(auftrag, hat_link, tag): Spiel am 01.11., Lieferfrist 5 Tage, also bis 06.11."""
    A = {"status": "Fotografiert", "datum": "2026-11-01", "lieferfrist": "2026-11-06"}

    def test_beispiel_aus_der_planung(self):
        self.assertEqual(server.lieferampel(self.A, False, "2026-11-07"), "rot")

    def test_am_letzten_tag_noch_gelb(self):
        self.assertEqual(server.lieferampel(self.A, False, "2026-11-06"), "gelb")
        self.assertEqual(server.lieferampel(self.A, False, "2026-11-01"), "gelb")

    def test_vor_dem_spiel_keine_ampel(self):
        self.assertEqual(server.lieferampel(self.A, False, "2026-10-31"), "keine")

    def test_geliefert(self):
        self.assertEqual(server.lieferampel(self.A, True, "2026-12-24"), "gruen")
        for st in ("Geliefert", "Abgeschlossen"):
            self.assertEqual(server.lieferampel({**self.A, "status": st}, False, "2026-12-24"), "gruen")

    def test_abgesagt(self):
        self.assertEqual(server.lieferampel({**self.A, "status": "Abgesagt"}, False, "2026-11-07"), "keine")


class Phase4(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.make_server("127.0.0.1", 0)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        with server.db() as conn:
            server.set_setting(conn, "twofa_pflicht", "0")
            cls.paket = conn.execute("SELECT id FROM pakete WHERE name='Basic'").fetchone()[0]
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

    def auftrag(self, datum, **vals):
        k = self.neu("kunden", name="Lieferung e. V.")["id"]
        return self.neu("auftraege", kunde_id=k, paket_id=self.paket, datum=datum, **vals)

    def link(self, auftrag_id, **vals):
        vals.setdefault("url", "https://example.picdrop.com/galerie")
        return self.neu("lieferlinks", auftrag_id=auftrag_id, **vals)

    # ---- Ablaufdatum ----
    def test_picdrop_laeuft_nach_30_tagen_ab(self):
        a = self.auftrag(tage(-2))
        self.assertEqual(self.link(a["id"])["laeuft_ab_am"], tage(30))
        self.assertEqual(self.link(a["id"], laeuft_ab_am="2030-01-01")["laeuft_ab_am"], "2030-01-01")
        self.assertIn(self.link(a["id"], typ="pCloud")["laeuft_ab_am"], (None, ""))
        self.c.req("PUT", "/api/einstellungen", {"picdrop_tage": "45"})
        self.addCleanup(self.c.req, "PUT", "/api/einstellungen", {"picdrop_tage": "30"})
        self.assertEqual(self.link(a["id"])["laeuft_ab_am"], tage(45))

    def test_ungueltige_links(self):
        a = self.auftrag(tage(-2))
        for vals in ({"url": "http://example.org/x"}, {"url": "javascript:alert(1)"}, {"url": ""},
                     {"url": "https://a b.de/x"}, {"url": "https://x.de/\"onmouseover"}, {"typ": "Dropbox"},
                     {"laeuft_ab_am": "01.12.2026"}):
            self.assertEqual(self.c.req("POST", "/api/lieferlinks", {"auftrag_id": a["id"], "url": "https://x.de/a", **vals})[0], 400, vals)
        self.assertEqual(self.c.req("POST", "/api/lieferlinks", {"url": "https://x.de/a"})[0], 400)
        self.assertEqual(self.c.req("POST", "/api/lieferlinks", {"auftrag_id": 999999, "url": "https://x.de/a"})[0], 400)

    def test_auftrag_des_links_steht_fest(self):
        a, b = self.auftrag(tage(-2)), self.auftrag(tage(-2))
        l = self.link(a["id"])
        self.assertEqual(self.c.req("PUT", f"/api/lieferlinks/{l['id']}", {"auftrag_id": b["id"], "hinweis": "mit Wasserzeichen"})[1]["auftrag_id"], a["id"])

    # ---- Ampel und Status ----
    def test_ueberfaellig_bis_ein_link_kommt(self):
        a = self.auftrag(tage(-6), status="Fotografiert")          # Frist war gestern
        self.assertEqual(self.c.req("GET", f"/api/auftraege/{a['id']}")[1]["ampel"], "rot")
        uebersicht = self.c.req("GET", "/api/lieferung")[1]
        self.assertIn(a["id"], [x["id"] for x in uebersicht["ueberfaellig"]])
        self.link(a["id"])
        b = self.c.req("GET", f"/api/auftraege/{a['id']}")[1]
        self.assertEqual((b["ampel"], b["status"]), ("gruen", "Geliefert"))
        self.assertNotIn(a["id"], [x["id"] for x in self.c.req("GET", "/api/lieferung")[1]["ueberfaellig"]])
        with server.db() as conn:
            r = conn.execute("SELECT details FROM audit_log WHERE table_name='auftraege' AND record_id=? ORDER BY id DESC", (a["id"],)).fetchone()
        self.assertIn("Galerie-Link", r["details"])

    def test_faellig_und_liste_mit_ampel(self):
        a, spaeter = self.auftrag(tage(-1)), self.auftrag(tage(10))
        self.assertIn(a["id"], [x["id"] for x in self.c.req("GET", "/api/lieferung")[1]["faellig"]])
        liste = {x["id"]: x["ampel"] for x in self.c.req("GET", "/api/auftraege")[1]}
        self.assertEqual((liste[a["id"]], liste[spaeter["id"]]), ("gelb", "keine"))

    def test_status_wird_nur_vorwaerts_gesetzt(self):
        a = self.auftrag(tage(-2), status="Abgeschlossen")
        self.link(a["id"])
        self.assertEqual(self.c.req("GET", f"/api/auftraege/{a['id']}")[1]["status"], "Abgeschlossen")
        b = self.auftrag(tage(-2), status="Abgesagt")
        self.link(b["id"])
        self.assertEqual(self.c.req("GET", f"/api/auftraege/{b['id']}")[1]["status"], "Abgesagt")

    def test_links_laufen_ab(self):
        a = self.auftrag(tage(-20))
        bald = self.link(a["id"], laeuft_ab_am=tage(3))
        weg = self.link(a["id"], laeuft_ab_am=tage(-5))
        spaeter = self.link(a["id"], laeuft_ab_am=tage(8))
        lange_weg = self.link(a["id"], laeuft_ab_am=tage(-31))
        u = self.c.req("GET", "/api/lieferung")[1]
        ab = [x["id"] for x in u["laeuft_ab"]]
        vorbei = [x["id"] for x in u["abgelaufen"]]
        self.assertIn(bald["id"], ab)
        self.assertIn(weg["id"], vorbei)
        for x in (spaeter, lange_weg):
            self.assertNotIn(x["id"], ab + vorbei)
        self.assertEqual([x for x in u["laeuft_ab"] if x["id"] == bald["id"]][0]["kunde"], "Lieferung e. V.")

    def test_link_loeschen(self):
        l = self.link(self.auftrag(tage(-2))["id"])
        self.assertEqual(self.c.req("DELETE", f"/api/lieferlinks/{l['id']}")[0], 200)

    # ---- Vorlagen ----
    def test_vorlagen(self):
        vorlagen = self.c.req("GET", "/api/vorlagen")[1]
        self.assertTrue(any("{link}" in v["text"] for v in vorlagen))
        self.assertEqual(self.c.req("POST", "/api/vorlagen", {"name": "Leer"})[0], 400)
        v = self.neu("vorlagen", name="Kurz", text="Hier sind die Bilder: {link}")
        self.assertEqual(self.c.req("DELETE", f"/api/vorlagen/{v['id']}")[0], 200)

    def test_ohne_anmeldung(self):
        fremd = Client(self.port)
        for path in ("/api/lieferung", "/api/lieferlinks", "/api/vorlagen"):
            self.assertEqual(fremd.req("GET", path)[0], 401)


if __name__ == "__main__":
    unittest.main()
