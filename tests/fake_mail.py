"""Nachbau eines IMAP- und eines SMTP-Servers für die Postfach-Tests (kein Netz).
FakeIMAP ersetzt imaplib.IMAP4_SSL und kann LIST, NAMESPACE, CREATE, SUBSCRIBE, SELECT, STATUS, EXPUNGE, APPEND und
UID SEARCH/FETCH/STORE/COPY/MOVE mit COPYUID, so wie postfach.py sie benutzt. Ordner mit Trenner "." und Namensraum "INBOX." wie bei Strato.
FakeSMTP ersetzt smtplib.SMTP_SSL und smtplib.SMTP und merkt sich die verschickten Mails.
"""
import imaplib
import re
import smtplib
from email.parser import BytesParser
from email import policy


class Server:
    passwort = "richtig"
    move = True              # Fähigkeit MOVE (sonst COPY, \Deleted, EXPUNGE)
    gesendet = []            # von FakeSMTP verschickte Mails (EmailMessage)
    ordner = {}

    @classmethod
    def neu(cls):
        cls.passwort, cls.move, cls.gesendet = "richtig", True, []
        cls.ordner = {}
        for name, rolle in (("INBOX", ""), ("INBOX.Sent", "\\Sent"), ("INBOX.Trash", "\\Trash"), ("INBOX.Drafts", "\\Drafts"),
                            ("INBOX.Spam", "\\Junk"), ("INBOX.Kunden", "")):
            cls.ordner[name] = {"uv": 4711, "next": 1, "rolle": rolle, "msgs": {}}

    @classmethod
    def ablegen(cls, ordner, raw, flags=()):
        f = cls.ordner[ordner]
        uid = f["next"]
        f["next"] += 1
        f["msgs"][uid] = {"raw": raw, "flags": set(flags)}
        return uid


def unquote(name):
    name = name.decode() if isinstance(name, bytes) else str(name)
    if name.startswith('"') and name.endswith('"'):
        name = name[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return name


class FakeIMAP:
    def __init__(self, host, port=993, ssl_context=None, timeout=None):
        if host.startswith("fehler"):
            raise OSError("nicht erreichbar")
        self.capabilities = ("IMAP4REV1", "UIDPLUS", "SPECIAL-USE", "NAMESPACE") + (("MOVE",) if Server.move else ())
        self.untagged_responses = {}
        self.sel = None
        self.literal = None

    def login(self, user, pw):
        if pw != Server.passwort:
            raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials")
        return "OK", [b"Logged in"]

    def logout(self):
        return "BYE", [b""]

    def list(self):
        out = []
        for name, f in Server.ordner.items():
            out.append(f'(\\HasNoChildren{" " + f["rolle"] if f["rolle"] else ""}) "." "{name}"'.encode())
        return "OK", out

    def namespace(self):
        return "OK", [b'(("INBOX." ".")) NIL NIL']

    def create(self, name):
        name = unquote(name)
        if not name.startswith("INBOX."):   # wie Strato: eigene Ordner nur unterhalb von INBOX.
            return "NO", [b"[CANNOT] not allowed"]
        Server.ordner.setdefault(name, {"uv": 4711, "next": 1, "rolle": "", "msgs": {}})
        return "OK", [b"Created"]

    def subscribe(self, name):
        return "OK", [b""]

    def select(self, name="INBOX", readonly=False):
        name = unquote(name)
        if name not in Server.ordner:
            return "NO", [b"Mailbox does not exist"]
        self.sel = name
        self.untagged_responses["UIDVALIDITY"] = [str(Server.ordner[name]["uv"]).encode()]
        return "OK", [str(len(Server.ordner[name]["msgs"])).encode()]

    def status(self, name, what):
        name = unquote(name)
        n = sum(1 for m in Server.ordner[name]["msgs"].values() if "\\Seen" not in m["flags"])
        return "OK", [f'"{name}" (UNSEEN {n})'.encode()]

    def expunge(self):
        msgs = Server.ordner[self.sel]["msgs"]
        for uid in [u for u, m in msgs.items() if "\\Deleted" in m["flags"]]:
            del msgs[uid]
        return "OK", [b""]

    def append(self, name, flags, date, raw):
        Server.ablegen(unquote(name), raw, re.findall(r"\\\w+", flags or ""))
        return "OK", [b"APPEND completed"]

    def uid(self, cmd, *args):
        msgs = Server.ordner[self.sel]["msgs"]
        cmd = cmd.upper()
        if cmd == "SEARCH":
            if args[:2] == ("CHARSET", "UTF-8"):
                term = (self.literal or b"").decode().lower()
                treffer = [u for u, m in msgs.items() if term in m["raw"].decode("utf-8", "replace").lower()]
            elif len(args) >= 4 and args[1] == "HEADER":
                treffer = [u for u, m in msgs.items() if re.search(rb"^Message-ID:\s*" + re.escape(args[3].encode()), m["raw"], re.M | re.I)]
            else:
                treffer = sorted(msgs)
            return "OK", [" ".join(map(str, sorted(treffer))).encode()]
        if cmd == "FETCH":
            uidset = args[0].decode() if isinstance(args[0], bytes) else str(args[0])
            items = args[1]
            out = []
            for u in [int(x) for x in uidset.split(",") if x]:
                m = msgs.get(u)
                if not m:
                    continue
                fl = " ".join(sorted(m["flags"]))
                if items == "(UID FLAGS)":
                    out.append(f"{u} (UID {u} FLAGS ({fl}))".encode())
                    continue
                kopf, _, _ = m["raw"].partition(b"\r\n\r\n")
                daten = m["raw"] if "BODY.PEEK[]" in items else kopf + b"\r\n\r\n"
                struktur = ' BODYSTRUCTURE (("text" "plain") ("application" "pdf" ("name" "x.pdf") NIL NIL "base64" 3 NIL ("attachment" ("filename" "x.pdf"))))' \
                    if b"Content-Disposition: attachment" in m["raw"] else ' BODYSTRUCTURE ("text" "plain")'
                out.append((f"{u} (UID {u} FLAGS ({fl}) RFC822.SIZE {len(m['raw'])}{struktur} BODY[] {{{len(daten)}}}".encode(), daten))
                out.append(b")")
            return "OK", out
        if cmd == "STORE":
            u, art, flags = int(args[0]), args[1], re.findall(r"\\\w+", args[2])
            if u in msgs:
                msgs[u]["flags"] = (msgs[u]["flags"] | set(flags)) if art.startswith("+") else (msgs[u]["flags"] - set(flags))
            return "OK", [b""]
        if cmd in ("COPY", "MOVE"):
            if cmd == "MOVE" and not Server.move:
                raise imaplib.IMAP4.error("BAD unknown command")
            u, ziel = int(args[0]), unquote(args[1])
            if u not in msgs or ziel not in Server.ordner:
                return "NO", [b"nope"]
            neu = Server.ablegen(ziel, msgs[u]["raw"], msgs[u]["flags"] - {"\\Deleted"})
            if cmd == "MOVE":
                del msgs[u]
            return "OK", [f"[COPYUID {Server.ordner[ziel]['uv']} {u} {neu}] Done".encode()]
        raise imaplib.IMAP4.error(f"BAD {cmd}")


class FakeSMTP:
    def __init__(self, host, port=0, timeout=None, context=None):
        self.host, self.esmtp_features = host, {"auth": "PLAIN LOGIN"}
        self.user = self.password = ""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def ehlo_or_helo_if_needed(self):
        pass

    def starttls(self, context=None):
        pass

    def auth(self, mech, fn):
        if self.password != Server.passwort:
            raise smtplib.SMTPAuthenticationError(535, b"5.7.8 Authentication failed")

    def auth_plain(self, challenge=None):
        return ""

    auth_login = auth_plain

    def login(self, user, pw):
        if pw != Server.passwort:
            raise smtplib.SMTPAuthenticationError(535, b"5.7.8 Authentication failed")

    def send_message(self, msg, from_addr=None):
        Server.gesendet.append(BytesParser(policy=policy.default).parsebytes(msg.as_bytes()))
        return {}


def mail(betreff="Anfrage Spielershooting", von="Anna Muster <anna@verein.example>", text="Hallo, wir hätten gern Fotos.", html=None,
         anhang=None, mid=None, an="info@studio.example"):
    from email.message import EmailMessage
    from email.utils import make_msgid
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = von, an, betreff
    m["Date"] = "Sat, 14 Nov 2026 10:00:00 +0100"
    m["Message-ID"] = mid or make_msgid(domain="verein.example")
    m.set_content(text)
    if html:
        m.add_alternative(html, subtype="html")
    if anhang:
        m.add_attachment(anhang[1], maintype="application", subtype="pdf", filename=anhang[0])
    return m.as_bytes(policy=policy.SMTP)
