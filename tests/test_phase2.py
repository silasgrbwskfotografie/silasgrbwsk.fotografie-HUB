"""Tests Phase 2: Preislogik, Kunden, Kontakte, Aufträge, Einstellungen.
Aufruf im Projektordner:  python -m unittest discover -s tests -v
"""
import sqlite3
import threading
import unittest

from test_phase1 import Client, server


class Preislogik(unittest.TestCase):
    """preis(grund, inkl, je_spieler, spieler, km, frei_km, cent_je_km) -> (Zusatzspieler, Anfahrt, Summe) in Cent"""

    def test_beispiel_aus_der_planung(self):
        # Spielershooting, 28 Spieler, 25 km: 60 € + 3 × 0,90 € + 15 × 0,30 € = 67,20 €
        self.assertEqual(server.preis(6000, 25, 90, 28, 25, 10, 30), (270, 450, 6720))

    def test_hsg_spiel_ohne_zuschlaege(self):
        self.assertEqual(server.preis(3500, 0, 0, 0, 5, 10, 30), (0, 0, 3500))

    def test_genau_an_den_grenzen(self):
        self.assertEqual(server.preis(6000, 25, 90, 25, 10, 10, 30), (0, 0, 6000))
        self.assertEqual(server.preis(6000, 25, 90, 26, 11, 10, 30), (90, 30, 6120))

    def test_unter_den_grenzen_wird_nichts_abgezogen(self):
        self.assertEqual(server.preis(6000, 25, 90, 10, 3, 10, 30), (0, 0, 6000))

    def test_paket_ohne_spielerstaffel(self):
        # inkl = 0 heißt: Spielerzahl spielt keine Rolle
        self.assertEqual(server.preis(3000, 0, 90, 40, 0, 10, 30), (0, 0, 3000))


class Phase2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.make_server("127.0.0.1", 0)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        with server.db() as conn:   # ohne eingerichteten zweiten Faktor wäre sonst nur /api/me erreichbar
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

    def kunde(self, name="HSG Emden", **vals):
        return self.neu("kunden", name=name, **vals)

    def auftrag(self, paket="Spielershooting", **vals):
        k = vals.pop("kunde_id", None) or self.kunde()["id"]
        return self.neu("auftraege", kunde_id=k, paket_id=self.pakete[paket], datum="2026-11-01", **vals)

    # ---- Preis im Auftrag ----
    def test_spielershooting_28_spieler_25_km(self):
        a = self.auftrag(spieler=28, km=25)
        self.assertEqual((a["grundpreis_cent"], a["zusatzspieler_cent"], a["anfahrt_cent"], a["betrag_cent"]), (6000, 270, 450, 6720))
        self.assertEqual(a["status"], "Angefragt")
        self.assertEqual(a["lieferfrist"], "2026-11-06")

    def test_hsg_spiel(self):
        a = self.auftrag("Saisonspiel HSG Emden", km=3, begegnung="HSG Emden gegen TuS")
        self.assertEqual(a["betrag_cent"], 3500)

    def test_vorschau_rechnet_ohne_zu_speichern(self):
        with server.db() as conn:
            vorher = conn.execute("SELECT COUNT(*) FROM auftraege").fetchone()[0]
        st, v, _ = self.c.req("POST", "/api/auftraege/vorschau", {"paket_id": self.pakete["Spielershooting"], "spieler": 28, "km": 25})
        self.assertEqual(st, 200)
        self.assertEqual(v["betrag_cent"], 6720)
        with server.db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM auftraege").fetchone()[0], vorher)

    def test_alte_preise_bleiben(self):
        a = self.auftrag(spieler=28, km=25)
        pid = self.pakete["Spielershooting"]
        self.addCleanup(self.c.req, "PUT", f"/api/pakete/{pid}", {"grundpreis_cent": 6000, "zusatzspieler_cent": 90})
        self.addCleanup(self.c.req, "PUT", "/api/einstellungen", {"anfahrt_cent_je_km": "30", "anfahrt_frei_km": "10"})
        self.assertEqual(self.c.req("PUT", f"/api/pakete/{pid}", {"grundpreis_cent": 9000, "zusatzspieler_cent": 200})[0], 200)
        self.assertEqual(self.c.req("PUT", "/api/einstellungen", {"anfahrt_cent_je_km": "50", "anfahrt_frei_km": "0"})[0], 200)
        # mehr Kilometer: gerechnet wird mit den Preisen vom Anlegen (60 € + 2,70 € + 20 × 0,30 €)
        st, b, _ = self.c.req("PUT", f"/api/auftraege/{a['id']}", {"km": 30})
        self.assertEqual((st, b["betrag_cent"]), (200, 6870))
        # ein neuer Auftrag bekommt die neuen Preise (90 € + 3 × 2 € + 25 × 0,50 €)
        self.assertEqual(self.auftrag(spieler=28, km=25)["betrag_cent"], 9000 + 600 + 1250)
        # Paketwechsel holt den aktuellen Paketpreis, die Anfahrt bleibt bei den alten Sätzen (30 € + 20 × 0,30 €)
        st, b, _ = self.c.req("PUT", f"/api/auftraege/{a['id']}", {"paket_id": self.pakete["Basic"]})
        self.assertEqual((b["grundpreis_cent"], b["zusatzspieler_cent"], b["anfahrt_cent"], b["betrag_cent"]), (3000, 0, 600, 3600))

    def test_betrag_von_hand(self):
        a = self.auftrag(spieler=28, km=25)
        url = f"/api/auftraege/{a['id']}"
        self.assertEqual(self.c.req("PUT", url, {"betrag_manuell": 1, "betrag_cent": 5000})[1]["betrag_cent"], 5000)
        b = self.c.req("PUT", url, {"km": 100})[1]   # bleibt überschrieben, die Anfahrt wird trotzdem mitgeführt
        self.assertEqual((b["betrag_cent"], b["anfahrt_cent"]), (5000, 2700))
        self.assertEqual(self.c.req("PUT", url, {"betrag_manuell": 0})[1]["betrag_cent"], 6000 + 270 + 2700)

    def test_preisfelder_setzt_nur_der_server(self):
        a = self.auftrag(spieler=28, km=25, grundpreis_cent=1, anfahrt_cent=1, betrag_cent=1, lieferfrist="2030-01-01")
        self.assertEqual((a["betrag_cent"], a["lieferfrist"]), (6720, "2026-11-06"))

    def test_lieferfrist_wandert_mit_dem_datum(self):
        a = self.auftrag()
        b = self.c.req("PUT", f"/api/auftraege/{a['id']}", {"datum": "2026-12-30", "status": "Bestätigt"})[1]
        self.assertEqual((b["lieferfrist"], b["status"]), ("2027-01-04", "Bestätigt"))

    # ---- Prüfungen ----
    def test_ungueltige_eingaben(self):
        k = self.kunde()["id"]
        p = self.pakete["Basic"]
        ok = {"kunde_id": k, "paket_id": p, "datum": "2026-11-01"}
        for table, vals in (
            ("kunden", {"name": ""}),
            ("kunden", {"name": "X", "typ": "Firma"}),
            ("kontakte", {"name": "Ohne Kunde"}),
            ("kontakte", {"name": "Falscher Kunde", "kunde_id": 999999}),
            ("auftraege", {**ok, "datum": "01.11.2026"}),
            ("auftraege", {**ok, "datum": "2026-02-30"}),
            ("auftraege", {**ok, "status": "Erfunden"}),
            ("auftraege", {**ok, "uhrzeit": "25:00"}),
            ("auftraege", {**ok, "km": -5}),
            ("auftraege", {**ok, "km": "viele"}),
            ("auftraege", {**ok, "spieler": 2.5}),
            ("auftraege", {**ok, "kunde_id": 999999}),
            ("auftraege", {**ok, "paket_id": 999999}),
            ("auftraege", {"paket_id": p, "datum": "2026-11-01"}),
        ):
            st, body, _ = self.c.req("POST", f"/api/{table}", vals)
            self.assertEqual(st, 400, (table, vals, body))
            self.assertTrue(body["error"])

    def test_sparte_nur_unter_verein(self):
        verein = self.kunde("Verein A")
        sparte = self.kunde("Handball", typ="Sparte", parent_id=verein["id"])
        self.assertEqual(sparte["parent_id"], verein["id"])
        self.assertEqual(self.c.req("POST", "/api/kunden", {"name": "Jugend", "parent_id": sparte["id"]})[0], 400)
        self.assertEqual(self.c.req("PUT", f"/api/kunden/{verein['id']}", {"parent_id": sparte["id"]})[0], 400)
        self.assertEqual(self.c.req("PUT", f"/api/kunden/{verein['id']}", {"parent_id": verein["id"]})[0], 400)

    # ---- Löschen und Archivieren ----
    def test_kunde_mit_auftrag_nur_archivieren(self):
        k = self.kunde("Mit Auftrag")
        kontakt = self.neu("kontakte", name="Anna", kunde_id=k["id"], email="anna@example.org")
        a = self.auftrag(kunde_id=k["id"])
        st, body, _ = self.c.req("DELETE", f"/api/kunden/{k['id']}")
        self.assertEqual(st, 400)
        self.assertIn("archivieren", body["error"])
        # nichts halb gelöscht: der Kontakt ist noch da
        self.assertEqual(self.c.req("GET", f"/api/kontakte/{kontakt['id']}")[0], 200)
        self.assertEqual(self.c.req("PUT", f"/api/kunden/{k['id']}", {"archiviert": 1})[1]["archiviert"], 1)
        # ohne Auftrag ist der Kunde löschbar, seine Kontakte gehen mit
        self.assertEqual(self.c.req("DELETE", f"/api/auftraege/{a['id']}")[0], 200)
        self.assertEqual(self.c.req("DELETE", f"/api/kunden/{k['id']}")[0], 200)
        self.assertEqual(self.c.req("GET", f"/api/kontakte/{kontakt['id']}")[0], 404)

    def test_benutztes_paket_nicht_loeschbar(self):
        p = self.neu("pakete", name="Testpaket", grundpreis_cent=1000)
        a = self.neu("auftraege", kunde_id=self.kunde()["id"], paket_id=p["id"], datum="2026-11-01")
        self.assertEqual(self.c.req("DELETE", f"/api/pakete/{p['id']}")[0], 400)
        self.c.req("DELETE", f"/api/auftraege/{a['id']}")
        self.assertEqual(self.c.req("DELETE", f"/api/pakete/{p['id']}")[0], 200)

    # ---- Einstellungen ----
    def test_einstellungen_aendern(self):
        self.addCleanup(self.c.req, "PUT", "/api/einstellungen", {"picdrop_tage": "30", "umsatzgrenze_cent": ""})
        st, s, _ = self.c.req("PUT", "/api/einstellungen", {"picdrop_tage": "45", "umsatzgrenze_cent": "2500000", "twofa_pflicht": "1"})
        self.assertEqual((st, s["picdrop_tage"], s["umsatzgrenze_cent"]), (200, "45", "2500000"))
        self.assertEqual(s["twofa_pflicht"], "0")   # nicht über die Oberfläche änderbar
        for bad in ("abc", "-1", "1.5", ""):
            self.assertEqual(self.c.req("PUT", "/api/einstellungen", {"picdrop_tage": bad})[0], 400, bad)

    # ---- Schutz und Protokoll ----
    def test_ohne_anmeldung_und_ohne_schutz_header(self):
        fremd = Client(self.port)
        for path in ("/api/kunden", "/api/kontakte", "/api/auftraege"):
            self.assertEqual(fremd.req("GET", path)[0], 401)
        self.assertEqual(fremd.req("POST", "/api/kunden", {"name": "X"})[0], 401)
        self.assertEqual(self.c.req("POST", "/api/kunden", {"name": "X"}, csrf=False)[0], 403)
        self.assertEqual(self.c.req("GET", "/api/users")[0], 404)
        self.assertEqual(self.c.req("GET", "/api/secrets")[0], 404)

    def test_aenderungen_stehen_im_protokoll(self):
        k = self.kunde("Protokoll e. V.")
        self.c.req("PUT", f"/api/kunden/{k['id']}", {"notizen": "neu"})
        self.c.req("DELETE", f"/api/kunden/{k['id']}")
        with server.db() as conn:
            rows = [r["action"] for r in conn.execute(
                "SELECT action FROM audit_log WHERE table_name='kunden' AND record_id=? ORDER BY id", (k["id"],))]
        self.assertEqual(rows, ["neu", "geändert", "gelöscht"])

    def test_protokoll_lesbar_ohne_geheimnisse(self):
        self.kunde("Fürs Protokoll")
        with server.db() as conn:
            server.secret_set(conn, "test", "geheim-xyz")
        st, rows, _ = self.c.req("GET", "/api/protokoll")
        self.assertEqual(st, 200)
        self.assertEqual((rows[0]["action"], rows[0]["label"]), ("neu", "Fürs Protokoll"))
        self.assertNotIn("geheim-xyz", str(rows))
        self.assertNotIn("scrypt$", str(rows))
        self.assertEqual(Client(self.port).req("GET", "/api/protokoll")[0], 401)

    # ---- Passwort ändern ----
    def test_passwort_aendern(self):
        server.create_user("pwtest", "altes-passwort-1")
        a, b = Client(self.port), Client(self.port)
        self.assertEqual(a.login("pwtest", "altes-passwort-1")[0], 200)
        self.assertEqual(b.login("pwtest", "altes-passwort-1")[0], 200)
        self.assertEqual(a.req("POST", "/api/me/passwort", {"alt": "falsch-falsch", "neu": "neues-passwort-2"})[0], 400)
        self.assertEqual(a.req("POST", "/api/me/passwort", {"alt": "altes-passwort-1", "neu": "kurz"})[0], 400)
        self.assertEqual(a.req("POST", "/api/me/passwort", {"alt": "altes-passwort-1", "neu": "neues-passwort-2"})[0], 200)
        self.assertEqual(a.req("GET", "/api/me")[0], 200)     # diese Sitzung bleibt
        self.assertEqual(b.req("GET", "/api/me")[0], 401)     # andere Geräte sind abgemeldet
        self.assertEqual(Client(self.port).login("pwtest", "altes-passwort-1")[0], 401)
        self.assertEqual(Client(self.port).login("pwtest", "neues-passwort-2")[0], 200)

    # ---- Sicherung ----
    def test_sicherung_ist_eine_lesbare_datenbank(self):
        k = self.kunde("In der Sicherung")
        st, liste, _ = self.c.req("POST", "/api/sicherungen", {})
        self.assertEqual(st, 200)
        self.assertRegex(liste[0]["name"], r"^studio-\d{4}-\d{2}-\d{2}\.db$")
        conn = sqlite3.connect(server.BACKUPS / liste[0]["name"])
        try:
            self.assertEqual(conn.execute("SELECT name FROM kunden WHERE id=?", (k["id"],)).fetchone()[0], "In der Sicherung")
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        finally:
            conn.close()

    def test_alte_sicherungen_werden_aufgeraeumt(self):
        alt = [server.BACKUPS / f"studio-2020-{m:02d}-{t:02d}.db" for m in (1, 2, 3) for t in range(1, 21)]
        for f in alt:
            f.write_bytes(b"")
        self.addCleanup(lambda: [f.unlink(missing_ok=True) for f in alt])
        server.daily_backup()
        da = sorted(f.name for f in server.BACKUPS.glob("studio-2020-*.db"))
        # die Tagesstände sind neuer (heute und die letzten aus März 2020), von den Monaten bleibt jeweils der erste
        self.assertEqual(da[:2], ["studio-2020-01-01.db", "studio-2020-02-01.db"])
        self.assertEqual(len(da), 2 + 1 + 13)


class Aufraeumen(unittest.TestCase):
    def test_14_tage_und_6_monatsstaende(self):
        namen = [f"studio-2026-{m:02d}-{t:02d}.db" for m in range(1, 11) for t in range(1, 29)]
        keep = server.backup_behalten(namen)
        # die 14 letzten Tage (15. bis 28. Oktober), dazu der 1. von Mai bis Oktober
        self.assertEqual(len(keep), 14 + 6)
        self.assertIn("studio-2026-10-15.db", keep)
        self.assertNotIn("studio-2026-10-14.db", keep)
        self.assertIn("studio-2026-05-01.db", keep)
        self.assertNotIn("studio-2026-04-01.db", keep)


if __name__ == "__main__":
    unittest.main()
