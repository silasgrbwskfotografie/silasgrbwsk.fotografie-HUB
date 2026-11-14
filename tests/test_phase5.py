"""Tests Phase 5: Vertragsfristen, PDF-Upload, geschützter Download.
Aufruf im Projektordner:  python -m unittest discover -s tests -v
"""
import base64
import threading
import unittest

from test_phase1 import Client, server

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def data_url(raw, mime="application/pdf"):
    return f"data:{mime};base64," + base64.b64encode(raw).decode()


class Fristen(unittest.TestCase):
    V = {"beginn": "2026-08-01", "mindestlaufzeit_monate": 12, "kuendigungsfrist_wert": 3, "kuendigungsfrist_einheit": "Monate"}

    def f(self, tag, **v):
        return server.vertragsfristen({**self.V, **v}, tag)

    def test_zwoelf_monate_drei_monate_frist(self):
        self.assertEqual(self.f("2026-11-14"), {"laufzeit_ende": "2027-07-31", "kuendigen_bis": "2027-04-30", "vertrag_status": "endet"})

    def test_wochen_und_tage(self):
        self.assertEqual(self.f("2026-11-14", kuendigungsfrist_wert=6, kuendigungsfrist_einheit="Wochen")["kuendigen_bis"], "2027-06-19")
        self.assertEqual(self.f("2026-11-14", kuendigungsfrist_wert=30, kuendigungsfrist_einheit="Tage")["kuendigen_bis"], "2027-07-01")

    def test_festes_ende_geht_vor(self):
        self.assertEqual(self.f("2026-11-14", ende="2026-12-31")["kuendigen_bis"], "2026-09-30")

    def test_verlaengerung_springt_in_die_naechste_periode(self):
        r = self.f("2027-05-01", verlaengerung_monate=12)
        self.assertEqual((r["laufzeit_ende"], r["kuendigen_bis"], r["vertrag_status"]), ("2028-07-31", "2028-04-30", "verlängert sich"))
        self.assertEqual(self.f("2027-04-30", verlaengerung_monate=12)["kuendigen_bis"], "2027-04-30")

    def test_beendet_und_unbefristet(self):
        self.assertEqual(self.f("2027-08-01")["vertrag_status"], "beendet")
        self.assertEqual(self.f("2026-11-14", mindestlaufzeit_monate=None)["vertrag_status"], "unbefristet")

    def test_monatsende(self):
        self.assertEqual(server.plus_monate(server.date(2027, 3, 31), -1), server.date(2027, 2, 28))
        self.assertEqual(server.plus_monate(server.date(2028, 1, 31), 1), server.date(2028, 2, 29))


class Phase5(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.make_server("127.0.0.1", 0)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        with server.db() as conn:
            server.set_setting(conn, "twofa_pflicht", "0")
        cls.c = Client(cls.port)
        assert cls.c.login()[0] == 200
        st, cls.kunde, _ = cls.c.req("POST", "/api/kunden", {"name": "Vertrag e. V."})

    @classmethod
    def tearDownClass(cls):
        with server.db() as conn:
            server.set_setting(conn, "twofa_pflicht", "1")
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def vertrag(self, **v):
        st, body, _ = self.c.req("POST", "/api/vertraege", {"kunde_id": self.kunde["id"], "art": "Saisonvertrag", "beginn": "2026-08-01",
                                                             "mindestlaufzeit_monate": 12, "kuendigungsfrist_wert": 3, **v})
        self.assertEqual(st, 201, body)
        return body

    def test_vertrag_zeigt_fristen(self):
        v = self.vertrag()
        self.assertEqual((v["laufzeit_ende"], v["kuendigen_bis"]), ("2027-07-31", "2027-04-30"))
        self.assertEqual([x for x in self.c.req("GET", "/api/vertraege")[1] if x["id"] == v["id"]][0]["kuendigen_bis"], "2027-04-30")

    def test_ungueltige_vertraege(self):
        for v in ({"art": "Mietvertrag"}, {"beginn": ""}, {"beginn": "2026-02-30"}, {"ende": "2026-01-01"},
                  {"kuendigungsfrist_einheit": "Jahre"}, {"kunde_id": None}):
            self.assertEqual(self.c.req("POST", "/api/vertraege", {"kunde_id": self.kunde["id"], "art": "Sponsoring", "beginn": "2026-08-01", **v})[0], 400, v)

    def test_pdf_hochladen_und_nur_mit_login_abrufbar(self):
        v = self.vertrag()
        st, r, _ = self.c.req("POST", f"/api/datei/vertraege/{v['id']}", {"name": "../Vertrag HSG.pdf", "data": data_url(PDF)})
        self.assertEqual(st, 200, r)
        self.assertEqual(r["datei_name"], "Vertrag HSG.pdf")
        self.assertRegex(r["datei"], r"^[0-9a-f]{32}\.pdf$")
        self.assertNotIn("datei", self.c.req("PUT", f"/api/vertraege/{v['id']}", {"datei": "x.pdf"})[1]["datei"] or "x")
        st, body, resp = self.c.req("GET", f"/api/datei/vertraege/{v['id']}")
        self.assertEqual((st, resp.getheader("Content-Type")), (200, "application/pdf"))
        self.assertIn("inline", resp.getheader("Content-Disposition"))
        self.assertIn("attachment", self.c.req("GET", f"/api/datei/vertraege/{v['id']}?download=1")[2].getheader("Content-Disposition"))
        fremd = Client(self.port)
        self.assertEqual(fremd.req("GET", f"/api/datei/vertraege/{v['id']}")[0], 401)
        self.assertEqual(fremd.req("GET", f"/static/../data/uploads/{r['datei']}", csrf=False)[0], 302)
        self.assertEqual(fremd.req("GET", f"/uploads/{r['datei']}", csrf=False)[0], 302)
        # neue Datei ersetzt die alte, Löschen nimmt die Datei mit
        st, r2, _ = self.c.req("POST", f"/api/datei/vertraege/{v['id']}", {"name": "neu.pdf", "data": data_url(PDF)})
        self.assertFalse((server.UPLOADS / r["datei"]).exists())
        self.assertTrue((server.UPLOADS / r2["datei"]).exists())
        self.assertEqual(self.c.req("DELETE", f"/api/vertraege/{v['id']}")[0], 200)
        self.assertFalse((server.UPLOADS / r2["datei"]).exists())

    def test_nur_echte_pdfs(self):
        v = self.vertrag()
        for raw, mime in ((b"<html><script>alert(1)</script>", "application/pdf"), (b"\xff\xd8\xff\xe0jpeg", "image/jpeg"), (b"", "application/pdf")):
            self.assertEqual(self.c.req("POST", f"/api/datei/vertraege/{v['id']}", {"name": "x.pdf", "data": data_url(raw, mime)})[0], 400)
        self.assertEqual(self.c.req("POST", f"/api/datei/vertraege/{v['id']}", {"name": "x.pdf", "data": "kein data-url"})[0], 400)
        self.assertEqual(self.c.req("POST", "/api/datei/vertraege/999999", {"name": "x.pdf", "data": data_url(PDF)})[0], 404)
        self.assertEqual(self.c.req("POST", f"/api/datei/kunden/{self.kunde['id']}", {"name": "x.pdf", "data": data_url(PDF)})[0], 404)

    def test_zu_gross(self):
        v = self.vertrag()
        alt = server.DATEI_MAX
        server.DATEI_MAX = 100
        self.addCleanup(setattr, server, "DATEI_MAX", alt)
        self.assertEqual(self.c.req("POST", f"/api/datei/vertraege/{v['id']}", {"name": "x.pdf", "data": data_url(PDF * 10)})[0], 400)

    def test_dokument(self):
        st, d, _ = self.c.req("POST", "/api/dokumente", {"kunde_id": self.kunde["id"], "titel": "Akkreditierung"})
        self.assertEqual(st, 201)
        st, r, _ = self.c.req("POST", f"/api/datei/dokumente/{d['id']}", {"name": "akk.pdf", "data": data_url(PDF)})
        self.assertEqual((st, r["groesse"]), (200, len(PDF)))
        self.assertTrue(r["hochgeladen_am"])
        self.assertEqual(self.c.req("POST", "/api/dokumente", {"kunde_id": self.kunde["id"]})[0], 400)
        # Kunde mit Vertrag oder Dokument lässt sich nicht löschen
        self.assertEqual(self.c.req("DELETE", f"/api/kunden/{self.kunde['id']}")[0], 400)


if __name__ == "__main__":
    unittest.main()
