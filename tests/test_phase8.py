"""Tests Phase 8: Termine mit Wiederholung, Überschneidungen, Aufgaben mit Vorlagen und Wiederholung, Erinnerungen, fremder Kalender.
Aufruf im Projektordner:  python -m unittest discover -s tests -v
"""
import threading
import unittest
from datetime import date, datetime, timedelta
from unittest import mock

from test_phase1 import Client, server

D = server.date


class Wiederholung(unittest.TestCase):
    def vk(self, t, von, bis):
        return [(b.isoformat(timespec="minutes"), e.isoformat(timespec="minutes")) for b, e in server.termin_vorkommen(t, D.fromisoformat(von), D.fromisoformat(bis))]

    def test_einmalig(self):
        t = {"beginn": "2027-03-10T18:00", "ende": "2027-03-10T19:30"}
        self.assertEqual(self.vk(t, "2027-03-01", "2027-03-31"), [("2027-03-10T18:00", "2027-03-10T19:30")])
        self.assertEqual(self.vk(t, "2027-04-01", "2027-04-30"), [])

    def test_woechentlich_bis(self):
        t = {"beginn": "2027-03-01T18:00", "wiederholung": "wöchentlich", "wiederholung_bis": "2027-03-22"}
        self.assertEqual([b for b, _ in self.vk(t, "2027-03-01", "2027-04-30")],
                         ["2027-03-01T18:00", "2027-03-08T18:00", "2027-03-15T18:00", "2027-03-22T18:00"])
        self.assertEqual([b for b, _ in self.vk(t, "2027-03-14", "2027-03-16")], ["2027-03-15T18:00"])

    def test_monatlich_am_31(self):
        t = {"beginn": "2027-01-31", "ganztaegig": 1, "wiederholung": "monatlich"}
        self.assertEqual([b[:10] for b, _ in self.vk(t, "2027-01-01", "2027-04-30")], ["2027-01-31", "2027-02-28", "2027-03-31", "2027-04-30"])

    def test_ganztaegig_ende(self):
        self.assertEqual(server.termin_zeit({"beginn": "2027-05-01", "ende": "2027-05-03", "ganztaegig": 1}),
                         (datetime(2027, 5, 1), datetime(2027, 5, 4)))


class IcsLesen(unittest.TestCase):
    ICS = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nSUMMARY:Frühdienst\\, Station 2\r\nDTSTART;TZID=Europe/Berlin:20261116T060000\r\n"
           "DTEND;TZID=Europe/Berlin:20261116T140000\r\nRRULE:FREQ=WEEKLY;COUNT=3\r\nLOCATION:Kli\r\n nikum\r\nEND:VEVENT\r\n"
           "BEGIN:VEVENT\r\nSUMMARY:Urlaub\r\nDTSTART;VALUE=DATE:20261201\r\nDTEND;VALUE=DATE:20261202\r\nEND:VEVENT\r\n"
           "BEGIN:VEVENT\r\nSUMMARY:UTC\r\nDTSTART:20260701T100000Z\r\nEND:VEVENT\r\n"
           "BEGIN:VEVENT\r\nSUMMARY:Abgesagt\r\nSTATUS:CANCELLED\r\nDTSTART:20261117T100000Z\r\nEND:VEVENT\r\n"
           "BEGIN:VEVENT\r\nSUMMARY:Kaputt\r\nDTSTART:gestern\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")

    def test_lesen(self):
        t = server.ics_lesen(self.ICS, D(2026, 11, 14))
        self.assertEqual([(x["datum"], x["uhrzeit"], x["bis"]) for x in t if x["titel"] == "Frühdienst, Station 2"],
                         [("2026-11-16", "06:00", "14:00"), ("2026-11-23", "06:00", "14:00"), ("2026-11-30", "06:00", "14:00")])
        self.assertEqual(t[0]["ort"], "Klinikum")
        self.assertIn(("2026-12-01", ""), [(x["datum"], x["uhrzeit"]) for x in t if x["titel"] == "Urlaub"])
        self.assertNotIn("Abgesagt", [x["titel"] for x in t])
        self.assertNotIn("UTC", [x["titel"] for x in t])   # länger als 30 Tage her
        self.assertEqual(server.ics_lesen(self.ICS.replace("20260701", "20261120"), D(2026, 11, 14))[-1]["uhrzeit"], "11:00")   # UTC nach Berlin

    def test_nur_oeffentliche_https_server(self):
        for url in ("http://example.org/a.ics", "https://127.0.0.1/a.ics", "https://localhost/a.ics", "https://10.0.0.5/a.ics", "ftp://x/y", ""):
            self.assertFalse(server.fremd_url_ok(url), url)


class Phase8(unittest.TestCase):
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
        cls.kunde = cls.c.req("POST", "/api/kunden", {"name": "Aufgaben e. V."})[1]

    @classmethod
    def tearDownClass(cls):
        with server.db() as conn:
            server.set_setting(conn, "twofa_pflicht", "1")
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def neu(self, table, **v):
        st, r, _ = self.c.req("POST", f"/api/{table}", v)
        self.assertEqual(st, 201, r)
        return r

    # ---- Aufgaben aus Vorlagen ----
    def test_neuer_auftrag_bekommt_aufgabenliste(self):
        vorlagen = [v for v in self.c.req("GET", "/api/aufgaben_vorlagen")[1] if v["paket_id"] == self.pakete["Pro"]]
        self.assertEqual([v["titel"] for v in vorlagen], [t for t, _ in server.SEED_AUFGABEN])
        a = self.neu("auftraege", kunde_id=self.kunde["id"], paket_id=self.pakete["Pro"], datum="2027-06-10")
        auf = [x for x in self.c.req("GET", "/api/aufgaben")[1] if x["auftrag_id"] == a["id"]]
        self.assertEqual({x["titel"]: x["faellig"] for x in auf}["Akkus laden"], "2027-06-09")
        self.assertEqual({x["titel"]: x["faellig"] for x in auf}["Zahlung prüfen"], "2027-06-17")
        self.assertTrue(all(x["kunde_id"] == self.kunde["id"] and x["status"] == "Offen" for x in auf))
        # Auftrag löschen nimmt seine Aufgaben mit
        self.assertEqual(self.c.req("DELETE", f"/api/auftraege/{a['id']}")[0], 200)
        self.assertEqual([x for x in self.c.req("GET", "/api/aufgaben")[1] if x["auftrag_id"] == a["id"]], [])

    def test_vorlage_mit_negativen_tagen(self):
        v = self.neu("aufgaben_vorlagen", paket_id=self.pakete["Basic"], titel="Akkreditierung anfragen", tage_offset=-14)
        self.assertEqual(v["tage_offset"], -14)
        self.assertEqual(self.c.req("POST", "/api/aufgaben_vorlagen", {"paket_id": self.pakete["Basic"], "titel": "x", "tage_offset": -5000})[0], 400)
        self.c.req("DELETE", f"/api/aufgaben_vorlagen/{v['id']}")

    # ---- Aufgaben ----
    def test_wiederkehrende_aufgabe(self):
        a = self.neu("aufgaben", titel="Belege in Finom prüfen", faellig="2027-01-31", wiederholung="monatlich")
        r = self.c.req("PUT", f"/api/aufgaben/{a['id']}", {"status": "Erledigt"})[1]
        self.assertTrue(r["erledigt_am"])
        neu = [x for x in self.c.req("GET", "/api/aufgaben")[1] if x["titel"] == "Belege in Finom prüfen" and x["status"] == "Offen"]
        self.assertEqual([x["faellig"] for x in neu], ["2027-02-28"])
        # zweimal erledigt melden erzeugt keine zweite Folgeaufgabe
        self.c.req("PUT", f"/api/aufgaben/{a['id']}", {"status": "Erledigt"})
        self.assertEqual(len([x for x in self.c.req("GET", "/api/aufgaben")[1] if x["titel"] == "Belege in Finom prüfen" and x["status"] == "Offen"]), 1)
        self.assertIsNone(self.c.req("PUT", f"/api/aufgaben/{a['id']}", {"status": "Offen"})[1]["erledigt_am"])

    def test_ungueltige_aufgaben_und_termine(self):
        for t, v in (("aufgaben", {"titel": ""}), ("aufgaben", {"titel": "x", "faellig": "morgen"}), ("aufgaben", {"titel": "x", "prioritaet": "Sofort"}),
                     ("aufgaben", {"titel": "x", "status": "Vielleicht"}), ("aufgaben", {"titel": "x", "wiederholung": "stündlich"}),
                     ("termine", {"titel": "x"}), ("termine", {"titel": "x", "beginn": "2027-03-01"}),
                     ("termine", {"titel": "x", "beginn": "2027-03-01T18:00", "ende": "2027-03-01T17:00"}),
                     ("termine", {"titel": "", "beginn": "2027-03-01T18:00"}), ("termine", {"titel": "x", "beginn": "2027-03-01T18:00", "wiederholung_bis": "bald"})):
            self.assertEqual(self.c.req("POST", f"/api/{t}", v)[0], 400, (t, v))

    # ---- Überschneidungen ----
    def test_ueberschneidung(self):
        a = self.neu("auftraege", kunde_id=self.kunde["id"], paket_id=self.pakete["Basic"], datum="2027-09-04", uhrzeit="15:00", begegnung="Spiel A")
        b = self.neu("auftraege", kunde_id=self.kunde["id"], paket_id=self.pakete["Basic"], datum="2027-09-04", uhrzeit="16:00", begegnung="Spiel B")
        self.assertEqual([x["id"] for x in b["ueberschneidungen"]], [a["id"]])
        t = self.neu("termine", titel="Besprechung", beginn="2027-09-04T16:30", ende="2027-09-04T17:30")
        self.assertEqual(sorted(x["titel"] for x in t["ueberschneidungen"]), ["Spiel A", "Spiel B"])
        frei = self.neu("termine", titel="Abends", beginn="2027-09-04T20:00")
        self.assertEqual(frei["ueberschneidungen"], [])
        self.neu("termine", titel="Training", beginn="2027-08-28T15:30", wiederholung="wöchentlich")
        # ein späteres Vorkommen des wöchentlichen Trainings fällt auf ein neues Spiel
        c =self.neu("auftraege", kunde_id=self.kunde["id"], paket_id=self.pakete["Basic"], datum="2027-09-11", uhrzeit="16:00")
        self.assertIn("Training", [x["titel"] for x in c["ueberschneidungen"]])

    # ---- Kalender ----
    def test_kalender_mit_terminen_und_aufgaben(self):
        t = self.neu("termine", titel="Vorbereitung", beginn="2035-02-05T10:00", ende="2035-02-05T11:00", wiederholung="wöchentlich")
        self.neu("aufgaben", titel="Kamera reinigen", faellig="2035-02-07")
        e = self.c.req("GET", "/api/kalender?von=2035-02-01&bis=2035-02-28")[1]
        self.assertEqual([x["datum"] for x in e if x["art"] == "termin" and x["id"] == t["id"]], ["2035-02-05", "2035-02-12", "2035-02-19", "2035-02-26"])
        self.assertIn(("aufgabe", "Kamera reinigen"), [(x["art"], x["titel"]) for x in e])

    # ---- Erinnerungen ----
    def test_erinnerungen_einmal(self):
        t = self.neu("termine", titel="Shooting Vorgespräch", beginn="2036-03-03T18:00", erinnerung_min=30, ort="Studio")
        a = self.neu("aufgaben", titel="Rechnung schreiben", faellig="2036-03-03")
        gesendet = []
        with mock.patch.object(server, "send_push", lambda *a, **k: gesendet.append(a) or 1):
            self.assertEqual(server.erinnern(datetime(2036, 3, 3, 7, 0)), 0)            # vor 8 Uhr, Termin noch weit
            self.assertEqual(server.erinnern(datetime(2036, 3, 3, 8, 5)), 1)            # Aufgabe am Fälligkeitstag
            self.assertEqual(server.erinnern(datetime(2036, 3, 3, 17, 31)), 1)          # 30 Minuten vor dem Termin
            self.assertEqual(server.erinnern(datetime(2036, 3, 3, 17, 45)), 0)          # nicht doppelt
        self.assertEqual(gesendet[0][1], "Rechnung schreiben")
        self.assertEqual((gesendet[1][0], gesendet[1][1]), ("Termin um 18:00", "Shooting Vorgespräch, Studio"))
        self.c.req("PUT", f"/api/aufgaben/{a['id']}", {"status": "Erledigt"})
        self.c.req("DELETE", f"/api/termine/{t['id']}")

    # ---- Fremder Kalender ----
    def test_fremder_kalender_link_wird_nie_ausgegeben(self):
        self.assertEqual(self.c.req("PUT", "/api/kalender/fremd", {"url": "http://example.org/a.ics"})[0], 400)
        with mock.patch.object(server, "fremd_url_ok", lambda u: True), \
                mock.patch.object(server, "fremd_abrufen", lambda: server.FREMD.update(termine=server.ics_lesen(IcsLesen.ICS, date.fromisoformat(server.heute()) + timedelta(days=-3)), zeit="x", fehler="")):
            st, r, _ = self.c.req("PUT", "/api/kalender/fremd", {"url": "webcal://kalender.example.org/geheim-123.ics"})
        self.assertEqual((st, r["aktiv"], r["host"]), (200, True, "kalender.example.org"))
        self.assertNotIn("geheim-123", str(r))
        with server.db() as conn:
            self.assertEqual(server.secret_get(conn, "ics_import_url"), "https://kalender.example.org/geheim-123.ics")
        self.assertNotIn("geheim-123", str(self.c.req("GET", "/api/einstellungen")[1]) + str(self.c.req("GET", "/api/protokoll")[1]))
        # fremde Termine stehen im Kalender, aber nie im eigenen Abo
        e = self.c.req("GET", "/api/kalender?von=2026-11-01&bis=2026-12-31")[1]
        self.assertIn("Urlaub", [x["titel"] for x in e if x["art"] == "extern"])
        with server.db() as conn:
            self.assertNotIn("Urlaub", server.ics_kalender(conn))
        with mock.patch.object(server, "fremd_abrufen", lambda: server.FREMD.update(termine=[], zeit="", fehler="")):
            self.assertFalse(self.c.req("DELETE", "/api/kalender/fremd")[1]["aktiv"])

    def test_startseite(self):
        a = self.neu("aufgaben", titel="Heute erledigen", faellig=server.heute())
        d = self.c.req("GET", "/api/dashboard")[1]
        self.assertIn(a["id"], [x["id"] for x in d["aufgaben"]])
        self.assertIn("eigene_termine", d)


if __name__ == "__main__":
    unittest.main()
