"""Tests Phase 9: Postfach mit mehreren Mailkonten gegen einen nachgebauten IMAP- und SMTP-Server (tests/fake_mail.py).
Aufruf im Projektordner:  python -m unittest discover -s tests -v
"""
import json
import threading
import unittest
from email.message import EmailMessage
from email import policy
from unittest import mock

import fake_mail
from fake_mail import FakeIMAP, FakeSMTP, Server, mail
from test_phase1 import Client, server


class Phase9(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patches = [mock.patch("imaplib.IMAP4_SSL", FakeIMAP), mock.patch("smtplib.SMTP_SSL", FakeSMTP), mock.patch("smtplib.SMTP", FakeSMTP)]
        for p in cls.patches:
            p.start()
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
        for p in cls.patches:
            p.stop()

    def setUp(self):
        Server.neu()
        server.PF_STATUS["daten"] = None
        st, self.konto, _ = self.c.req("POST", "/api/mailkonten", {"name": "Studio", "adresse": "info@studio.example", "smtp_host": "smtp.studio.example",
                                                                   "smtp_port": 465, "absender_name": "silasgrbwsk.fotografie", "signatur": "Viele Grüße\nSilas"})
        self.assertEqual(st, 201, self.konto)
        self.k = self.konto["id"]
        self.assertEqual(self.c.req("PUT", f"/api/mailkonten/{self.k}/passwort", {"passwort": "richtig"})[0], 200)

    def tearDown(self):
        self.c.req("DELETE", f"/api/mailkonten/{self.k}")

    def api(self, method, sub, **kw):
        q = "&".join(f"{k}={v}" for k, v in kw.items() if method == "GET")
        st, body, r = self.c.req(method, f"/api/postfach/{sub}?konto={self.k}" + ("&" + q if q else ""), None if method == "GET" else {"konto": self.k, **kw})
        return st, body, r

    # ---- Konto ----
    def test_passwort_nie_lesbar_und_verbindung_pruefen(self):
        k = self.c.req("GET", f"/api/mailkonten/{self.k}")[1]
        self.assertTrue(k["passwort_gesetzt"])
        for pfad in ("/api/mailkonten", f"/api/mailkonten/{self.k}", "/api/postfach/konten", "/api/protokoll", "/api/einstellungen"):
            self.assertNotIn("richtig", json.dumps(self.c.req("GET", pfad)[1]), pfad)
        self.assertEqual(self.c.req("POST", f"/api/mailkonten/{self.k}/pruefen", {})[1], {"smtp": "ok", "imap": "ok", "ok": True})
        Server.passwort = "anders"
        r = self.c.req("POST", f"/api/mailkonten/{self.k}/pruefen", {})[1]
        self.assertFalse(r["ok"])
        self.assertIn("Anmeldung", r["imap"])
        self.assertEqual(Server.gesendet, [])   # Prüfen verschickt nichts

    def test_ungueltige_konten(self):
        for v in ({"adresse": "keine-adresse", "smtp_host": "smtp.x.de"}, {"adresse": "a@b.de", "smtp_host": "smtp x"},
                  {"adresse": "a@b.de", "smtp_host": "smtp.x.de", "imap_host": "imap/x"}, {"adresse": "a@b.de", "smtp_host": "smtp.x.de", "smtp_port": 70000},
                  {"adresse": "a@b.de", "smtp_host": "smtp.x.de", "smtp_security": "tls1"}):
            self.assertEqual(self.c.req("POST", "/api/mailkonten", v)[0], 400, v)

    def test_konto_loeschen_entfernt_zugangsdaten(self):
        st, k2, _ = self.c.req("POST", "/api/mailkonten", {"adresse": "zwei@studio.example", "smtp_host": "smtp.studio.example"})
        self.c.req("PUT", f"/api/mailkonten/{k2['id']}/passwort", {"passwort": "geheim-2"})
        self.c.req("DELETE", f"/api/mailkonten/{k2['id']}")
        with server.db() as conn:
            self.assertFalse(conn.execute("SELECT 1 FROM secrets WHERE value='geheim-2'").fetchone())

    # ---- Ordner und Liste ----
    def test_ordner_deutsch_und_erledigt_wird_angelegt(self):
        Server.ablegen("INBOX", mail())
        st, f, _ = self.api("GET", "folders")
        self.assertEqual(st, 200, f)
        self.assertEqual([x["label"] for x in f["folders"]][:4], ["Posteingang", "Erledigt", "Gesendet", "Entwürfe"])
        self.assertIn("INBOX.Erledigt", Server.ordner)   # mit Namensraum-Präfix angelegt
        self.assertEqual(f["folders"][0]["unseen"], 1)
        self.assertEqual(f["adresse"], "info@studio.example")

    def test_liste_mit_kunde_und_suche(self):
        st, kunde, _ = self.c.req("POST", "/api/kunden", {"name": "Verein Muster"})
        self.c.req("POST", "/api/kontakte", {"kunde_id": kunde["id"], "name": "Anna Muster", "email": "Anna@Verein.example"})
        Server.ablegen("INBOX", mail())
        Server.ablegen("INBOX", mail("Rechnung Mai", von="buchhaltung@firma.example", text="Bitte zahlen"), ["\\Seen"])
        st, r, _ = self.api("GET", "messages", folder="INBOX")
        self.assertEqual((st, r["total"]), (200, 2))
        self.assertEqual([(x["subject"], x["seen"], x["kunde"]) for x in r["items"]],
                         [("Rechnung Mai", True, ""), ("Anfrage Spielershooting", False, "Verein Muster")])
        self.assertEqual([x["subject"] for x in self.api("GET", "messages", folder="INBOX", q="zahlen")[1]["items"]], ["Rechnung Mai"])

    # ---- Lesen ----
    def test_lesen_nur_als_text(self):
        m = EmailMessage()
        m["From"], m["Subject"], m["Message-ID"] = "x@y.example", "HTML", "<h1@y.example>"
        m.set_content('<p>Hallo <b>Welt</b><script>alert(1)</script><img src="https://tracker.example/p.gif"></p><a href="https://picdrop.com/g">Galerie</a>', subtype="html")
        uid = Server.ablegen("INBOX", m.as_bytes(policy=policy.SMTP))
        st, msg, _ = self.api("GET", "message", folder="INBOX", uid=uid, peek=1)
        self.assertEqual(st, 200)
        self.assertIn("Hallo Welt", msg["text"])
        self.assertIn("[https://picdrop.com/g]", msg["text"])
        self.assertNotIn("<", msg["text"])
        self.assertNotIn("alert", msg["text"])
        self.assertNotIn("\\Seen", Server.ordner["INBOX"]["msgs"][uid]["flags"])   # peek: bleibt ungelesen
        self.api("GET", "message", folder="INBOX", uid=uid)
        self.assertIn("\\Seen", Server.ordner["INBOX"]["msgs"][uid]["flags"])

    def test_anhang_nur_als_download(self):
        uid = Server.ablegen("INBOX", mail(anhang=("Vertrag <x>.pdf", b"%PDF-1.4 inhalt")))
        st, msg, _ = self.api("GET", "message", folder="INBOX", uid=uid)
        self.assertEqual(msg["attachments"][0]["name"], "Vertrag <x>.pdf")
        st, raw, r = self.api("GET", "attachment", folder="INBOX", uid=uid, i=0)
        self.assertEqual((st, r.getheader("Content-Type")), (200, "application/octet-stream"))
        self.assertIn("attachment;", r.getheader("Content-Disposition"))
        self.assertNotIn("<", r.getheader("Content-Disposition"))
        self.assertEqual(self.api("GET", "attachment", folder="INBOX", uid=uid, i=5)[0], 404)

    def test_ungueltige_eingaben(self):
        self.assertEqual(self.api("GET", "message", folder="INBOX", uid="1%20OR%202")[0], 400)
        self.assertEqual(self.c.req("GET", "/api/postfach/folders")[0], 400)   # ohne Konto
        self.assertEqual(self.c.req("GET", "/api/postfach/folders?konto=999999")[0], 400)
        self.assertEqual(Client(self.port).req("GET", f"/api/postfach/folders?konto={self.k}")[0], 401)
        self.assertEqual(self.api("GET", "messages", folder="Gibts.Nicht")[0], 400)

    # ---- Schreiben ----
    def test_antworten(self):
        uid = Server.ablegen("INBOX", mail(mid="<frage-1@verein.example>"))
        st, r, _ = self.api("POST", "send", to="Anna Muster <anna@verein.example>", subject="Re: Anfrage Spielershooting", body="Gern, Termin passt.",
                            reply={"folder": "INBOX", "uid": uid}, quote={"head": "Am 14.11. schrieb Anna:", "text": "Hallo, wir hätten gern Fotos."})
        self.assertEqual(st, 200, r)
        gesendet = Server.gesendet[-1]
        self.assertEqual(gesendet["To"], "anna@verein.example")
        self.assertEqual(gesendet["In-Reply-To"], "<frage-1@verein.example>")
        self.assertEqual(gesendet["From"].addresses[0].display_name, "silasgrbwsk.fotografie")
        self.assertEqual(gesendet["From"].addresses[0].addr_spec, "info@studio.example")
        text = gesendet.get_body(("plain",)).get_content()
        self.assertIn("Gern, Termin passt.\n\nViele Grüße\nSilas", text)
        self.assertIn("> Hallo, wir hätten gern Fotos.", text)
        self.assertIn("<blockquote", gesendet.get_body(("html",)).get_content())
        self.assertIn("\\Answered", Server.ordner["INBOX"]["msgs"][uid]["flags"])
        self.assertEqual(len(Server.ordner["INBOX.Sent"]["msgs"]), 1)   # Kopie unter Gesendet

    def test_versand_pruefungen(self):
        for v in ({"to": "kaputt", "subject": "x", "body": "y"}, {"to": ",".join(f"a{i}@b.example" for i in range(21)), "subject": "x", "body": "y"},
                  {"to": "a@b.example", "subject": "", "body": "y"}, {"to": "a@b.example", "subject": "x", "body": " "},
                  {"to": "a@b.example", "cc": "nicht gültig", "subject": "x", "body": "y"}):
            self.assertEqual(self.api("POST", "send", **v)[0], 400, v)
        self.assertEqual(Server.gesendet, [])
        Server.passwort = "anders"
        st, r, _ = self.api("POST", "send", to="a@b.example", subject="x", body="y")
        self.assertEqual(st, 400)
        self.assertIn("Anmeldung", r["error"])

    def test_absender_waehlen(self):
        st, k2, _ = self.c.req("POST", "/api/mailkonten", {"adresse": "privat@studio.example", "smtp_host": "smtp.studio.example"})
        self.c.req("PUT", f"/api/mailkonten/{k2['id']}/passwort", {"passwort": "richtig"})
        self.addCleanup(self.c.req, "DELETE", f"/api/mailkonten/{k2['id']}")
        st, r, _ = self.api("POST", "send", to="a@b.example", subject="Test", body="Hallo", von=k2["id"], signature=False)
        self.assertEqual((st, r["von"]), (200, "privat@studio.example"))
        self.assertEqual(Server.gesendet[-1]["From"], "privat@studio.example")
        self.assertNotIn("Viele Grüße", Server.gesendet[-1].get_body(("plain",)).get_content())

    # ---- Erledigt und Löschen ----
    def test_erledigt_mit_move_und_ohne(self):
        for move in (True, False):
            Server.move = move
            uid = Server.ablegen("INBOX", mail(f"Erledigt {move}"))
            st, r, _ = self.api("POST", "handled", folder="INBOX", uid=uid)
            self.assertEqual((st, r["moved"], r["folder"]), (200, True, "INBOX.Erledigt"), r)
            self.assertNotIn(uid, Server.ordner["INBOX"]["msgs"])
            self.assertIn(r["uid"], Server.ordner["INBOX.Erledigt"]["msgs"])

    def test_loeschen_erst_papierkorb_dann_endgueltig(self):
        uid = Server.ablegen("INBOX", mail("Weg damit"))
        st, r, _ = self.api("POST", "delete", folder="INBOX", uid=uid)
        self.assertEqual(r["action"], "in den Papierkorb")
        tuid = max(Server.ordner["INBOX.Trash"]["msgs"])
        self.assertEqual(self.api("POST", "delete", folder="INBOX.Trash", uid=tuid)[1]["action"], "endgültig gelöscht")
        self.assertEqual(Server.ordner["INBOX.Trash"]["msgs"], {})
        with server.db() as conn:
            self.assertTrue(conn.execute("SELECT 1 FROM audit_log WHERE action='Mail gelöscht' AND label='Weg damit'").fetchone())

    # ---- Neue Mails melden ----
    def test_abruf_meldet_nur_neues(self):
        Server.ablegen("INBOX", mail("Alt"))
        pushes = []
        with mock.patch.object(server, "send_push", lambda *a, **k: pushes.append(a) or 1), \
                mock.patch.object(server, "send_push_async", lambda *a, **k: pushes.append(("done",) + a)):
            cfg = self.cfg()
            self.assertEqual(server.pf_poll(cfg), 0)                       # erster Lauf: nur Stand merken
            neu = Server.ablegen("INBOX", mail("Neu 1"))
            Server.ablegen("INBOX", mail("Schon gelesen"), ["\\Seen"])
            self.assertEqual(server.pf_poll(cfg), 1)
            self.assertEqual(pushes[-1][0], "Neue Mail: Neu 1")
            self.assertEqual(pushes[-1][2], f"/#/mail/{self.k}/m/INBOX/{neu}")
            self.assertEqual(server.pf_poll(cfg), 0)                       # nicht doppelt
            with server.db() as conn:
                self.assertEqual(server.badge_zahl(conn) >= 1, True)
            # außerhalb beantwortet: zählt als erledigt
            Server.ordner["INBOX"]["msgs"][neu]["flags"].add("\\Answered")
            server.pf_poll(cfg)
        with server.db() as conn:
            r = conn.execute("SELECT status, aktion FROM mail_eingang WHERE konto_id=? AND uid=?", (self.k, neu)).fetchone()
        self.assertEqual((r["status"], r["aktion"]), ("erledigt", "beantwortet"))
        self.assertEqual(pushes[-1][0], "done")

    def test_status_zahl_im_menue(self):
        Server.ablegen("INBOX", mail("A"))
        Server.ablegen("INBOX", mail("B"))
        st, r, _ = self.c.req("GET", "/api/postfach/status")
        self.assertEqual(r["unseen"], 2)
        self.assertEqual([k["adresse"] for k in r["konten"]], ["info@studio.example"])

    # ---- Verknüpfen ----
    def test_verweis_und_wiederfinden(self):
        st, kunde, _ = self.c.req("POST", "/api/kunden", {"name": "Verweis e. V."})
        uid = Server.ablegen("INBOX", mail("Termin 3. Spieltag", mid="<spieltag-3@verein.example>"))
        st, v, _ = self.api("POST", "verweis", folder="INBOX", message_id="<spieltag-3@verein.example>", betreff="Termin 3. Spieltag", kunde_id=kunde["id"])
        self.assertEqual(st, 201, v)
        self.assertEqual(self.api("GET", "message", folder="INBOX", uid=uid)[1]["verweise"][0]["kunde"], "Verweis e. V.")
        self.api("POST", "handled", folder="INBOX", uid=uid)   # liegt jetzt in Erledigt
        st, f, _ = self.api("GET", "finde", verweis=v["id"])
        self.assertEqual((st, f["folder"]), (200, "INBOX.Erledigt"))
        # Aufgabe mit Verweis auf die Mail
        st, a, _ = self.c.req("POST", "/api/aufgaben", {"titel": "Antworten", "mail_verweis_id": v["id"]})
        self.assertEqual(st, 201)

    def cfg(self):
        with server.db() as conn:
            return server.konto_cfg(conn, self.k)


if __name__ == "__main__":
    unittest.main()
