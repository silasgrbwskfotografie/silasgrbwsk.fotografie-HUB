"""Tests Phase 10: Ausgaben, Übersicht im Aufbau einer EÜR (von Hand nachgerechnet), Monatssperre, Export.
Aufruf im Projektordner:  python -m unittest discover -s tests -v
"""
import base64
import io
import threading
import unittest
import zipfile

from test_phase1 import Client, server

PDF = b"%PDF-1.4\n%%EOF\n"
JPG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"x" * 20


def data_url(raw, mime):
    return f"data:{mime};base64," + base64.b64encode(raw).decode()


class Phase10(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.make_server("127.0.0.1", 0)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        with server.db() as conn:
            server.set_setting(conn, "twofa_pflicht", "0")
            cls.kat = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM ausgaben_kategorien")}
            cls.paket = conn.execute("SELECT id FROM pakete WHERE name='Basic'").fetchone()[0]
        cls.c = Client(cls.port)
        assert cls.c.login()[0] == 200

    @classmethod
    def tearDownClass(cls):
        with server.db() as conn:
            server.set_setting(conn, "twofa_pflicht", "1")
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def ausgabe(self, **v):
        st, a, _ = self.c.req("POST", "/api/ausgaben", v)
        self.assertEqual(st, 201, a)
        return a

    def einnahme(self, cent, zahldatum):
        k = self.c.req("POST", "/api/kunden", {"name": "EÜR e. V."})[1]
        a = self.c.req("POST", "/api/auftraege", {"kunde_id": k["id"], "paket_id": self.paket, "datum": zahldatum, "betrag_manuell": 1, "betrag_cent": cent})[1]
        z = [x for x in self.c.req("GET", "/api/zahlungen")[1] if x["auftrag_id"] == a["id"]][0]
        st, r, _ = self.c.req("PUT", f"/api/zahlungen/{z['id']}", {"status": "Bezahlt", "zahldatum": zahldatum})
        self.assertEqual(st, 200, r)
        return r

    def test_kategorien_aus_der_planung(self):
        self.assertEqual(list(self.kat)[:3], ["Ausrüstung", "Software und Abos", "Fahrtkosten"])

    def test_euer_von_hand_nachgerechnet(self):
        # eigenes Jahr 2041, damit andere Tests nicht mitzählen
        self.einnahme(6720, "2041-01-15")
        self.einnahme(3000, "2041-01-20")
        self.einnahme(4500, "2041-03-02")
        self.ausgabe(datum="2041-01-05", betrag_cent=1999, kategorie_id=self.kat["Software und Abos"], lieferant="Adobe")
        self.ausgabe(datum="2041-01-31", betrag_cent=4590, kategorie_id=self.kat["Fahrtkosten"])
        self.ausgabe(datum="2041-03-10", betrag_cent=129900, kategorie_id=self.kat["Ausrüstung"], anlagegut=1, lieferant="Kamera")
        self.ausgabe(datum="2041-03-11", betrag_cent=2500)                               # ohne Kategorie
        self.ausgabe(lieferant="Foto vom Beleg, Rest folgt")                             # unvollständig, zählt nicht
        e = self.c.req("GET", "/api/euer?jahr=2041")[1]
        self.assertEqual(e["einnahmen"][:3], [9720, 0, 4500])
        self.assertEqual(e["ausgaben"][:3], [6589, 0, 2500])
        self.assertEqual(e["anlagegueter"][2], 129900)
        self.assertEqual(e["ergebnis"][:3], [3131, 0, 2000])
        self.assertEqual(e["summe"], {"einnahmen": 14220, "ausgaben": 9089, "anlagegueter": 129900, "ergebnis": 5131})
        self.assertEqual({k: s_ for k, _, s_ in e["kategorien"]}, {"Fahrtkosten": 4590, "ohne Kategorie": 2500, "Software und Abos": 1999})
        self.assertGreaterEqual(e["unvollstaendig"], 1)

    def test_ungueltige_ausgaben(self):
        for v in ({"datum": "05.01.2041"}, {"betrag_cent": -5}, {"steuersatz": 190}, {"zahlart": "Bitcoin"}, {"kategorie_id": 999999}):
            self.assertEqual(self.c.req("POST", "/api/ausgaben", v)[0], 400, v)

    def test_beleg_als_foto_oder_pdf(self):
        a = self.ausgabe(datum="2044-05-01", betrag_cent=1000, lieferant="Media Markt")
        for raw, mime in ((JPG, "image/jpeg"), (PDF, "application/pdf")):
            st, r, _ = self.c.req("POST", f"/api/datei/ausgaben/{a['id']}", {"name": "beleg", "data": data_url(raw, mime)})
            self.assertEqual(st, 200, r)
        self.assertEqual(self.c.req("POST", f"/api/datei/ausgaben/{a['id']}", {"name": "x", "data": data_url(b"<svg/>", "image/svg+xml")})[0], 400)
        self.assertEqual(self.c.req("GET", f"/api/datei/ausgaben/{a['id']}")[2].getheader("Content-Type"), "application/pdf")

    # ---- Monatssperre ----
    def test_gesperrter_monat_nur_mit_grund(self):
        a = self.ausgabe(datum="2042-02-10", betrag_cent=5000, lieferant="Sperre GmbH")
        z = self.einnahme(3000, "2042-02-12")
        self.assertEqual(self.c.req("POST", "/api/sperren", {"monat": "2042-02"})[0], 200)
        st, r, _ = self.c.req("PUT", f"/api/ausgaben/{a['id']}", {"betrag_cent": 5100})
        self.assertEqual(st, 400)
        self.assertIn("02.2042 ist gesperrt", r["error"])
        self.assertEqual(self.c.req("POST", "/api/ausgaben", {"datum": "2042-02-28", "betrag_cent": 1})[0], 400)    # neu in gesperrten Monat
        self.assertEqual(self.c.req("PUT", f"/api/ausgaben/{a['id']}", {"datum": "2042-03-01"})[0], 400)          # heraus verschieben
        self.assertEqual(self.c.req("DELETE", f"/api/ausgaben/{a['id']}")[0], 400)
        self.assertEqual(self.c.req("PUT", f"/api/zahlungen/{z['id']}", {"status": "Offen"})[0], 400)
        self.assertEqual(self.c.req("PUT", f"/api/zahlungen/{z['id']}", {"finom_abgerechnet": 1, "finom_rechnungsnr": "RE-1"})[0], 200)   # nur Häkchen: erlaubt
        self.assertEqual(self.c.req("POST", f"/api/datei/ausgaben/{a['id']}", {"name": "x.pdf", "data": data_url(PDF, "application/pdf")})[0], 400)
        st, r, _ = self.c.req("PUT", f"/api/ausgaben/{a['id']}", {"betrag_cent": 5100, "sperr_grund": "Tippfehler im Betrag"})
        self.assertEqual((st, r["betrag_cent"]), (200, 5100))
        with server.db() as conn:
            d = conn.execute("SELECT details FROM audit_log WHERE table_name='ausgaben' AND record_id=? ORDER BY id DESC", (a["id"],)).fetchone()["details"]
        self.assertIn("Tippfehler im Betrag", d)
        # Entsperren nur mit Grund
        self.assertEqual(self.c.req("DELETE", "/api/sperren/2042-02")[0], 400)
        self.assertEqual(self.c.req("DELETE", "/api/sperren/2042-02?grund=Nachbuchung")[0], 200)
        self.assertEqual(self.c.req("PUT", f"/api/ausgaben/{a['id']}", {"betrag_cent": 5000})[0], 200)
        self.assertEqual(self.c.req("POST", "/api/sperren", {"monat": "2042-13"})[0], 400)

    # ---- Export ----
    def test_export(self):
        self.einnahme(6720, "2043-06-01")
        a = self.ausgabe(datum="2043-06-03", betrag_cent=1234, steuersatz=19, steuer_cent=197, kategorie_id=self.kat["Bürobedarf"], lieferant="=Büro & Co")
        self.c.req("POST", f"/api/datei/ausgaben/{a['id']}", {"name": "beleg.jpg", "data": data_url(JPG, "image/jpeg")})
        self.ausgabe(datum="2043-07-01", betrag_cent=1, lieferant="außerhalb")
        st, text, r = self.c.req("GET", "/api/export/ausgaben.csv?von=2043-06-01&bis=2043-06-30")
        self.assertEqual(st, 200)
        zeilen = text.lstrip("﻿").splitlines()
        self.assertEqual(len(zeilen), 2)
        self.assertIn("03.06.2043;'=Büro & Co;Bürobedarf;12,34;19;1,97;", zeilen[1])
        self.assertTrue(zeilen[1].endswith(f";2043-06-03_Büro-Co_12,34_{a['id']}.jpg"))
        st, text, _ = self.c.req("GET", "/api/export/einnahmen.csv?von=2043-06-01&bis=2043-06-30")
        self.assertIn(";67,20;", text)
        c = Client(self.port)
        c.cookie = self.c.cookie
        conn_ = __import__("http.client").client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn_.request("GET", "/api/export/belege.zip?von=2043-06-01&bis=2043-06-30", headers={"Cookie": self.c.cookie})
        resp = conn_.getresponse()
        z = zipfile.ZipFile(io.BytesIO(resp.read()))
        self.assertEqual(z.namelist(), [f"2043-06-03_Büro-Co_12,34_{a['id']}.jpg"])
        self.assertEqual(z.read(z.namelist()[0]), JPG)
        for q in ("", "von=2043-06-30&bis=2043-06-01", "von=x&bis=y"):
            self.assertEqual(self.c.req("GET", "/api/export/ausgaben.csv?" + q)[0], 400, q)
        self.assertEqual(Client(self.port).req("GET", "/api/export/ausgaben.csv?von=2043-06-01&bis=2043-06-30")[0], 401)


if __name__ == "__main__":
    unittest.main()
