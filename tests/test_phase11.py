"""Tests Phase 11: Fahrtenbuch mit Kilometerfolge, Änderungsverlauf, Sperre, Import, GPS-Strecke und Auswertung.
Aufruf im Projektordner:  python -m unittest discover -s tests -v
"""
import base64
import threading
import unittest

from test_phase1 import Client, server


class Strecke(unittest.TestCase):
    def test_haversine(self):
        # Emden Rathaus nach Leer Rathaus: rund 22,6 km Luftlinie
        self.assertAlmostEqual(server.entfernung_m((53.3669, 7.2061), (53.2307, 7.4600)) / 1000, 22.6, delta=0.3)
        self.assertEqual(server.entfernung_m((53.0, 7.0), (53.0, 7.0)), 0)

    def test_strecke_und_luecken(self):
        punkte = [("2026-11-14T10:00:00", 53.0, 7.0), ("2026-11-14T10:00:30", 53.001, 7.0), ("2026-11-14T10:03:00", 53.002, 7.0)]
        meter, luecken = server.gps_strecke(punkte)
        self.assertAlmostEqual(meter, 222, delta=2)   # 2 x 0,001 Grad Breite = 2 x 111 m
        self.assertEqual(luecken, [{"von": "2026-11-14T10:00:30", "bis": "2026-11-14T10:03:00", "sekunden": 150}])
        self.assertEqual(server.gps_strecke([]), (0, []))

    def test_zahlen_aus_dem_import(self):
        for txt, soll in (("12.345", 12.345), ("12345", 12345), ("12.345,6", 12345.6), ("12,345.6", 12345.6), ("23,4", 23.4), ("", None)):
            self.assertEqual(server.zahl(txt), soll, txt)


class Phase11(unittest.TestCase):
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
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        st, self.fz, _ = self.c.req("POST", "/api/fahrzeuge", {"name": "Golf", "kennzeichen": "EMD-XY 1", "km_start": 50000})
        self.assertEqual(st, 201)

    def fahrt(self, **v):
        st, f, _ = self.c.req("POST", "/api/fahrten", {"fahrzeug_id": self.fz["id"], **v})
        self.assertEqual(st, 201, f)
        return f

    def test_kilometerfolge(self):
        a = self.fahrt(datum="2045-03-01", beginn="08:00", km_start=50000, km_ende=50040, ziel_ort="Leer", zweck="Spiel")
        b = self.fahrt(datum="2045-03-02", km_start=50040, km_ende=50100)
        c = self.fahrt(datum="2045-03-03", km_start=50120, km_ende=50150)     # 20 km fehlen
        d = self.fahrt(datum="2045-03-04", km_start=50140, km_ende=50160)     # überschneidet sich
        p = self.c.req("GET", "/api/fahrtenbuch/pruefung")[1][str(self.fz["id"])]
        self.assertEqual([(x["fahrt_id"], x["erwartet"], x["ist"], x["art"]) for x in p],
                         [(c["id"], 50100, 50120, "Lücke"), (d["id"], 50150, 50140, "Überschneidung")])
        self.assertTrue(a["erfasst_am"])

    def test_pruefungen(self):
        for v in ({"datum": "2045-13-01"}, {"datum": "2045-03-01", "km_start": 100, "km_ende": 90}, {"datum": "2045-03-01", "art": "dienstlich"},
                  {"datum": "2045-03-01", "beginn": "25:00"}, {"datum": "2045-03-01", "quelle": "Handy"}):
            self.assertEqual(self.c.req("POST", "/api/fahrten", {"fahrzeug_id": self.fz["id"], **v})[0], 400, v)
        self.assertEqual(self.c.req("POST", "/api/fahrten", {"datum": "2045-03-01"})[0], 400)

    def test_aenderungen_bleiben_sichtbar_und_nichts_wird_geloescht(self):
        f = self.fahrt(datum="2045-04-01", km_start=50000, km_ende=50030, zweck="Spiel")
        erfasst = f["erfasst_am"]
        r = self.c.req("PUT", f"/api/fahrten/{f['id']}", {"km_ende": 50035, "zweck": "Spiel HSG", "erfasst_am": "2000-01-01T00:00:00", "grund": "Tacho abgelesen"})[1]
        self.assertEqual(r["erfasst_am"], erfasst)   # Erfassungszeit bleibt
        v = self.c.req("GET", f"/api/fahrtenbuch/fahrt/{f['id']}/aenderungen")[1]
        self.assertEqual(sorted((x["feld"], x["alt"], x["neu"], x["grund"]) for x in v),
                         [("km_ende", "50030", "50035", "Tacho abgelesen"), ("zweck", "Spiel", "Spiel HSG", "Tacho abgelesen")])
        self.assertEqual(self.c.req("DELETE", f"/api/fahrten/{f['id']}")[0], 400)
        self.assertEqual(self.c.req("PUT", f"/api/fahrten/{f['id']}", {"art": "storniert"})[0], 400)          # nur mit Grund
        self.assertEqual(self.c.req("PUT", f"/api/fahrten/{f['id']}", {"art": "storniert", "grund": "doppelt erfasst"})[0], 200)
        self.assertEqual(self.c.req("DELETE", f"/api/fahrzeuge/{self.fz['id']}")[0], 400)

    def test_gesperrter_monat(self):
        f = self.fahrt(datum="2046-05-03", km_start=50000, km_ende=50010)
        self.c.req("POST", "/api/sperren", {"monat": "2046-05"})
        self.assertEqual(self.c.req("PUT", f"/api/fahrten/{f['id']}", {"zweck": "x"})[0], 400)
        self.assertEqual(self.c.req("PUT", f"/api/fahrten/{f['id']}", {"zweck": "x", "sperr_grund": "Nachtrag"})[0], 200)
        self.assertEqual(self.c.req("GET", f"/api/fahrtenbuch/fahrt/{f['id']}/aenderungen")[1][-1]["grund"], "Nachtrag")

    def test_gps_aufzeichnung(self):
        f = self.fahrt(datum="2045-06-01", quelle="GPS", km_start=50000)
        pts = [{"t": "2045-06-01T08:00:00Z", "lat": 53.0, "lon": 7.0, "acc": 8}, {"t": "2045-06-01T08:00:20Z", "lat": 53.001, "lon": 7.0, "acc": 10},
               {"t": "2045-06-01T08:00:25Z", "lat": 54.0, "lon": 7.0, "acc": 300},      # ungenau: verworfen
               {"t": "2045-06-01T08:05:00Z", "lat": 53.002, "lon": 7.0, "acc": 12}, {"t": "kaputt", "lat": 1, "lon": 1}]
        st, r, _ = self.c.req("POST", f"/api/fahrtenbuch/fahrt/{f['id']}/punkte", {"punkte": pts})
        self.assertEqual((st, r["gespeichert"], r["luecken"]), (200, 3, 1))
        self.assertAlmostEqual(r["strecke_m"], 222, delta=2)
        g = self.c.req("GET", f"/api/fahrtenbuch/fahrt/{f['id']}/punkte")[1]
        self.assertEqual(len(g["punkte"]), 3)
        self.assertEqual(g["punkte"][0][2], "2045-06-01T10:00:00")   # UTC nach Ortszeit (Sommerzeit: plus 2 Stunden)
        # abgebrochene Aufzeichnung ohne Kilometer am Ende darf weg, eine Fahrt von Hand bekommt keine Punkte
        self.assertEqual(self.c.req("DELETE", f"/api/fahrten/{f['id']}")[0], 200)
        h = self.fahrt(datum="2045-06-02", km_start=1, km_ende=2)
        self.assertEqual(self.c.req("POST", f"/api/fahrtenbuch/fahrt/{h['id']}/punkte", {"punkte": pts})[0], 400)

    def test_vorschlag_aus_auftrag(self):
        k = self.c.req("POST", "/api/kunden", {"name": "Fahrt e. V."})[1]
        with server.db() as conn:
            paket = conn.execute("SELECT id FROM pakete LIMIT 1").fetchone()[0]
        a = self.c.req("POST", "/api/auftraege", {"kunde_id": k["id"], "paket_id": paket, "datum": server.heute(), "ort": "Leer", "km": 25})[1]
        v = [x for x in self.c.req("GET", "/api/fahrtenbuch/vorschlaege")[1] if x["auftrag_id"] == a["id"]]
        self.assertEqual((v[0]["ort"], v[0]["km"], v[0]["kunde"]), ("Leer", 25, "Fahrt e. V."))
        self.fahrt(datum=server.heute(), auftrag_id=a["id"], km_start=1, km_ende=51)
        self.assertNotIn(a["id"], [x["auftrag_id"] for x in self.c.req("GET", "/api/fahrtenbuch/vorschlaege")[1]])

    def test_import_mit_dubletten(self):
        csv_ = ("Datum;Start;Ende;Von;Nach;Zweck;Kunde;Kategorie;Strecke (km);Tacho Start;Tacho Ende\r\n"
                "03.03.2047;08:15;09:00;Emden;Leer;Spielershooting;HSG;Business;25,4;60000;60025\r\n"
                "04.03.2047;10:00;10:20;Emden;Aurich;;;Personal;12,0;60025;60037\r\n"
                "kaputt;;;;;;;;;;\r\n").encode("cp1252")
        d = "data:text/csv;base64," + base64.b64encode(csv_).decode()
        st, v, _ = self.c.req("POST", "/api/fahrtenbuch/import", {"data": d, "nur_vorschau": True})
        self.assertEqual((st, v["anzahl"], v["spalten"][4]), (200, 3, "Nach"))
        zu = {"datum": 0, "beginn": 1, "ende": 2, "start_ort": 3, "ziel_ort": 4, "zweck": 5, "partner": 6, "art": 7, "strecke_km": 8, "km_start": 9, "km_ende": 10}
        st, r, _ = self.c.req("POST", "/api/fahrtenbuch/import", {"data": d, "name": "driversnote.csv", "fahrzeug_id": self.fz["id"], "zuordnung": zu, "datumsformat": "TT.MM.JJJJ"})
        self.assertEqual((st, r["angelegt"], r["dubletten"], len(r["fehler"])), (200, 2, 0, 1), r)
        f = [x for x in self.c.req("GET", "/api/fahrten")[1] if x["datum"] == "2047-03-03" and x["fahrzeug_id"] == self.fz["id"]][0]
        self.assertEqual((f["quelle"], f["art"], f["km_start"], f["km_ende"], f["strecke_m"], f["ziel_ort"]), ("Driversnote", "betrieblich", 60000, 60025, 25400, "Leer"))
        self.assertTrue(f["import_datei"].endswith("|driversnote.csv"))
        self.assertTrue((server.UPLOADS / f["import_datei"].split("|")[0]).is_file())   # Original aufbewahrt
        st, r, _ = self.c.req("POST", "/api/fahrtenbuch/import", {"data": d, "name": "nochmal.csv", "fahrzeug_id": self.fz["id"], "zuordnung": zu, "datumsformat": "TT.MM.JJJJ"})
        self.assertEqual((r["angelegt"], r["dubletten"]), (0, 2))
        self.assertEqual(self.c.req("POST", "/api/fahrtenbuch/import", {"data": d, "fahrzeug_id": self.fz["id"], "zuordnung": {}, "datumsformat": "TT.MM.JJJJ"})[0], 400)

    def test_auswertung_und_export(self):
        self.fahrt(datum="2048-01-02", km_start=50000, km_ende=50300, art="betrieblich", ziel_ort="Hamburg")
        self.fahrt(datum="2048-01-03", km_start=50300, km_ende=50400, art="privat")
        self.fahrt(datum="2048-01-04", km_start=50400, km_ende=50500, art="storniert", grund="Test")
        self.fahrt(datum="2048-01-05")                                                   # ohne Kilometer
        a = self.c.req("GET", f"/api/fahrtenbuch/auswertung?jahr=2048&fahrzeug={self.fz['id']}")[1]
        self.assertEqual((a["km"]["betrieblich"], a["km"]["privat"], a["gesamt"], a["anteil"]["betrieblich"], a["unvollstaendig"]), (300, 100, 400, 75.0, 1))
        st, text, _ = self.c.req("GET", "/api/export/fahrten.csv?von=2048-01-01&bis=2048-01-31")
        zeilen = text.lstrip("﻿").splitlines()
        self.assertEqual(len(zeilen), 5)
        self.assertIn(";02.01.2048;;;50000;50300;300;;Hamburg;", zeilen[1])


if __name__ == "__main__":
    unittest.main()
