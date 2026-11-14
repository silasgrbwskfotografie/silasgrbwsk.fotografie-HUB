"""Postfach per IMAP und Versand per SMTP, nur Standardbibliothek.
Übernommen aus dem Emden Tigers Hub (server.py, Version 4.35): IMAP-Hilfen, Ordner, Erledigt, Lesen nur als Text, Anhänge, Kontoprüfung, Versand.
Angepasst: jedes Mailkonto bringt seine eigene Konfiguration mit (cfg), es gibt kein Vereinspostfach, keine Zuweisungen und keine Rechte.
cfg-Schlüssel: imap, imap_port, smtp_host, smtp_port, smtp_security (ssl, starttls, none), smtp_user, smtp_password, smtp_from.
Nichts wird in der Datenbank gespeichert, jede Anfrage holt live vom Mailserver.
"""
import base64
import contextlib
import re
from html.parser import HTMLParser

PF_PAGE = 40
PF_DONE_FOLDER = "Erledigt"   # „Erledigt“ verschiebt Mails hierher (wird bei Bedarf angelegt)
PF_FOLDER_LABELS = {"inbox": "Posteingang", "done": "Erledigt", "sent": "Gesendet", "drafts": "Entwürfe", "trash": "Papierkorb", "junk": "Spam", "archive": "Archiv"}
PF_ROLE_NAMES = {"sent": ("sent", "gesendet", "gesendete objekte", "sent items", "sent messages"), "trash": ("trash", "papierkorb", "deleted items", "gelöschte objekte"),
                 "drafts": ("drafts", "entwürfe"), "junk": ("junk", "spam", "unerwünscht"), "archive": ("archive", "archiv"), "done": ("erledigt",)}


class PostfachError(Exception):
    pass


def imap_utf7_decode(name):
    out = []
    for part in re.split(r"(&[^-]*-)", name):
        if part.startswith("&") and part.endswith("-"):
            if part == "&-":
                out.append("&")
            else:
                b = part[1:-1].replace(",", "/")
                try:
                    out.append(base64.b64decode(b + "=" * (-len(b) % 4)).decode("utf-16-be"))
                except (ValueError, UnicodeDecodeError):
                    out.append(part)
        else:
            out.append(part)
    return "".join(out)


def imap_quote(name):
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def postfach_open(cfg):
    import imaplib
    import ssl
    if not (cfg.get("imap") and cfg.get("smtp_user") and cfg.get("smtp_password")):
        raise PostfachError("Dieses Mailkonto ist noch nicht vollständig eingerichtet (Einstellungen, Mailkonten: Server, Benutzer und Passwort).")
    try:
        m = imaplib.IMAP4_SSL(cfg["imap"], int(cfg.get("imap_port") or 993), ssl_context=ssl.create_default_context(), timeout=20)
    except OSError as e:
        raise PostfachError(f"Der Mailserver {cfg['imap']} ist nicht erreichbar ({type(e).__name__}).")
    try:
        m.login(cfg["smtp_user"], cfg["smtp_password"])
    except imaplib.IMAP4.error:
        raise PostfachError("Anmeldung am Postfach fehlgeschlagen. Benutzername oder Passwort stimmen nicht.")
    return m, cfg


def postfach_folders(m):
    typ, data = m.list()
    out = []
    for line in data or []:
        if not isinstance(line, bytes):
            continue
        mm = re.match(rb'\((?P<flags>[^)]*)\) (?:"[^"]*"|NIL) (?P<name>.+)$', line)
        if not mm:
            continue
        raw = mm.group("name").decode("utf-8", "replace").strip()
        if raw.startswith('"') and raw.endswith('"'):
            raw = raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        flags = mm.group("flags").decode().lower()
        if "\\noselect" in flags:
            continue
        label = imap_utf7_decode(raw)
        short = label.split("/")[-1].split(".")[-1].strip().lower()
        role = "inbox" if raw.upper() == "INBOX" else next((r for r in ("sent", "trash", "drafts", "junk", "archive") if f"\\{r}" in flags), "")
        if not role:
            role = next((r for r, names in PF_ROLE_NAMES.items() if short in names), "")
        out.append({"name": raw, "label": PF_FOLDER_LABELS.get(role, label), "role": role})
    order = ["inbox", "done", "sent", "drafts", "archive", "junk", "trash", ""]
    out.sort(key=lambda f: (order.index(f["role"]), f["label"].lower()))
    return out


def pf_done_folder(m, create=True):
    """Name des Ordners „Erledigt“ im Postfach; legt ihn an, wenn er fehlt (create=True)."""
    names = [f["name"] for f in postfach_folders(m)]
    target = next((n for n in names if n.split(".")[-1].split("/")[-1].strip().lower() == PF_DONE_FOLDER.lower()), "")
    if not target and create:
        names = [PF_DONE_FOLDER]
        with contextlib.suppress(Exception):   # manche Anbieter erlauben Ordner nur unterhalb von „INBOX.“ (persönlicher Namensraum)
            typ, ns = m.namespace()
            mm = re.match(rb'\(\("([^"]*)" "([^"]*)"\)', (ns or [b""])[0] or b"")
            if mm and mm.group(1):
                names.append(mm.group(1).decode() + PF_DONE_FOLDER)
        for name in names:
            with contextlib.suppress(Exception):
                typ, _d = m.create(imap_quote(name))
                if typ == "OK":
                    target = name
                    with contextlib.suppress(Exception):
                        m.subscribe(imap_quote(name))
                    break
    return target


def pf_move_to_done(folder, uid, cfg):
    """Mail in den Ordner „Erledigt“ verschieben (anlegen, falls nötig). Gibt (Ordner, neue UID) zurück oder None."""
    m, _ = postfach_open(cfg)
    try:
        target = pf_done_folder(m)
        if not target:
            raise PostfachError("Ordner „Erledigt“ konnte nicht angelegt werden.")
        if folder == target:
            return None
        pf_select(m, folder, readonly=False)
        typ, data = m.uid("FETCH", str(uid), "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
        hdr = next((x[1] for x in data or [] if isinstance(x, tuple)), b"")
        if not hdr:
            return None
        mid = re.search(rb"Message-ID:\s*(<[^>]+>)", hdr, re.I)
        m.untagged_responses.pop("COPYUID", None)
        if "MOVE" in m.capabilities:
            typ, data = m.uid("MOVE", str(uid), imap_quote(target))
        else:
            typ, data = m.uid("COPY", str(uid), imap_quote(target))
            if typ == "OK":
                m.uid("STORE", str(uid), "+FLAGS", "(\\Deleted)")
                m.expunge()
        if typ != "OK":
            raise PostfachError("Verschieben nach „Erledigt“ fehlgeschlagen.")
        new_uid = None
        texts = [x for x in (m.untagged_responses.pop("COPYUID", None) or []) + list(data or []) if isinstance(x, (bytes, str))]
        for t in texts:
            mm = re.search(r"(?:COPYUID )?\d+ (\d+) (\d+)", t.decode() if isinstance(t, bytes) else t)
            if mm and mm.group(1) == str(uid):
                new_uid = int(mm.group(2))
        if new_uid is None and mid:   # ohne Rückmeldung: über die Message-ID im Zielordner suchen
            pf_select(m, target)
            typ, d2 = m.uid("SEARCH", None, "HEADER", "Message-ID", mid.group(1).decode())
            found = (d2[0] or b"").split()
            new_uid = int(found[-1]) if found else None
    finally:
        with contextlib.suppress(Exception):
            m.logout()
    return target, new_uid


def pf_role_folder(m, role):
    return next((f["name"] for f in postfach_folders(m) if f["role"] == role), "")


def pf_select(m, folder, readonly=True):
    typ, data = m.select(imap_quote(folder or "INBOX"), readonly=readonly)
    if typ != "OK":
        raise PostfachError("Diesen Ordner gibt es nicht.")


def pf_name(f):
    from email.utils import parseaddr
    n, a = parseaddr(f or "")
    return n or a or (f or "")


def pf_head(text):
    from email.header import decode_header, make_header
    try:
        return str(make_header(decode_header(text or "")))
    except Exception:  # noqa
        return text or ""


class _HtmlText(HTMLParser):
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "blockquote", "hr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.href = [], 0, ""

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head", "title"):
            self.skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n")
        if tag == "li":
            self.out.append("- ")
        if tag == "a":
            self.href = dict(attrs).get("href") or ""

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head", "title"):
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.out.append("\n")
        if tag == "a" and self.href.startswith(("http://", "https://")):
            self.out.append(f" [{self.href}]")
            self.href = ""

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(html):
    p = _HtmlText()
    try:
        p.feed(html or "")
        p.close()
    except Exception:  # noqa
        return re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"[ \t\r\f\v]+", " ", "".join(p.out))
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", text).strip()


def pf_message(m, folder, uid, mark_seen=True):
    from email import policy
    from email.parser import BytesParser
    pf_select(m, folder, readonly=not mark_seen)
    typ, data = m.uid("FETCH", uid, "(FLAGS BODY.PEEK[])")
    raw = next((x[1] for x in data or [] if isinstance(x, tuple)), None)
    if not raw:
        raise PostfachError("Diese Mail gibt es nicht mehr.")
    flags = next((x[0] for x in data if isinstance(x, tuple)), b"")
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    if mark_seen and b"\\Seen" not in flags:
        m.uid("STORE", uid, "+FLAGS", "(\\Seen)")
    return msg, flags


def pf_text(msg):
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        content = part.get_content()
    except (LookupError, ValueError):
        content = part.get_payload(decode=True).decode("utf-8", "replace")
    if part.get_content_subtype() == "html":
        content = html_to_text(content)
    return str(content)[:200000]


def pf_attachments(msg):
    out = []
    for i, part in enumerate(msg.iter_attachments()):
        name = pf_head(part.get_filename() or "") or f"anhang-{i + 1}"
        payload = part.get_payload(decode=True) or b""
        out.append({"i": i, "name": name[:150], "type": part.get_content_type(), "size": len(payload)})
    return out


def pf_unseen(cfg):
    m, _ = postfach_open(cfg)
    try:
        typ, data = m.status("INBOX", "(UNSEEN)")
        mm = re.search(rb"UNSEEN (\d+)", data[0] if data else b"")
        return int(mm.group(1)) if mm else 0
    finally:
        with contextlib.suppress(Exception):
            m.logout()


def mail_account_check(cfg):
    """Prüft Anmeldung an SMTP und IMAP eines Zugangs, ohne etwas zu verschicken."""
    import smtplib
    import ssl
    res = {}
    try:
        port = int(cfg["smtp_port"] or (465 if cfg["smtp_security"] == "ssl" else 587))
        sec = {465: "ssl", 587: "starttls"}.get(port, cfg["smtp_security"])
        ctx = ssl.create_default_context()
        s_ = smtplib.SMTP_SSL(cfg["smtp_host"], port, timeout=20, context=ctx) if sec == "ssl" else smtplib.SMTP(cfg["smtp_host"], port, timeout=20)
        with s_:
            if sec == "starttls":
                s_.starttls(context=ctx)
            s_.login(cfg["smtp_user"], cfg["smtp_password"])
        res["smtp"] = "ok"
    except Exception as e:  # noqa
        res["smtp"] = f"{type(e).__name__}: {e}"[:200]
    try:
        m, _ = postfach_open(cfg)
        with contextlib.suppress(Exception):
            m.logout()
        res["imap"] = "ok"
    except Exception as e:  # noqa
        res["imap"] = str(e)[:200]
    res["ok"] = res["smtp"] == "ok"
    return res


def mail_sender(cfg):
    """Absender-Kopfzeile und Absender-Adresse für den Mailserver. Steht unter „Absender“ nur ein Name (z. B. „Emden Tigers“),
    wird die Adresse des Postfachs (Benutzername) dazugenommen: „Emden Tigers <info@emden-tigers.de>“.
    Viele Anbieter (z. B. Strato) verlangen, dass die Absenderadresse zum angemeldeten Postfach passt."""
    from email.utils import formataddr, parseaddr
    user = (cfg.get("smtp_user") or "").strip()
    raw = (cfg.get("smtp_from") or "").strip()
    name, addr = parseaddr(raw)
    if "@" not in addr:   # nur ein Name eingetragen
        name, addr = raw, user
    if "@" not in addr:
        addr = user
    envelope = user if "@" in user else addr
    return (formataddr((name, addr)) if name and name != addr else addr), envelope


def send_mail(cfg, to, subject, body, footer=False, attachments=(), headers=None, cc=(), out=None, html=None, related=()):
    """Schickt eine Klartext-Mail (optional mit Anhängen: (Dateiname, Bytes, Haupttyp, Untertyp)). Liefert None oder eine Fehlermeldung."""
    import smtplib
    import ssl
    from email.message import EmailMessage
    from email.utils import formatdate, make_msgid
    msg = EmailMessage()
    msg["From"], envelope = mail_sender(cfg)
    msg["To"] = to
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    for k, v in (headers or {}).items():
        if v:
            msg[k] = v
    msg["Date"] = formatdate(localtime=True)   # ohne Datum und Message-ID sortieren Yahoo, Gmail und Co. Mails gern aus
    msg["Message-ID"] = make_msgid(domain=envelope.rsplit("@", 1)[-1] if "@" in envelope else None)
    msg.set_content(body)
    if html:   # HTML-Fassung (z. B. mit Signatur), Bilder eingebettet über cid
        msg.add_alternative(html, subtype="html")
        hpart = msg.get_payload()[-1]
        for cid, data in related:
            hpart.add_related(data, maintype="image", subtype="png", cid=f"<{cid}>", disposition="inline")
    for fname, data, maintype, subtype in attachments:
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=fname)
    try:
        port = int(cfg["smtp_port"] or (465 if cfg["smtp_security"] == "ssl" else 587))
        security = cfg["smtp_security"]
        if security != "none":   # Standardports haben feste Verschlüsselung: 465 = SSL, 587 = STARTTLS (häufige Verwechslung)
            security = {465: "ssl", 587: "starttls"}.get(port, security)
        ctx = ssl.create_default_context()
        if security == "ssl":
            s = smtplib.SMTP_SSL(cfg["smtp_host"], port, timeout=30, context=ctx)
        else:
            s = smtplib.SMTP(cfg["smtp_host"], port, timeout=30)
            if security != "none":
                s.starttls(context=ctx)
        with s:
            if cfg["smtp_user"]:
                # Nur der erste Anmeldeweg, sonst verdeckt Gmail die Ablehnung mit "Connection unexpectedly closed"
                s.ehlo_or_helo_if_needed()
                s.user, s.password = cfg["smtp_user"], cfg["smtp_password"] or ""
                if cfg["smtp_host"].lower().endswith(("gmail.com", "googlemail.com")):
                    s.password = "".join(s.password.split())   # App-Passwort wird mit Leerzeichen angezeigt: "abcd efgh ijkl mnop"
                mech = next((m for m in ("PLAIN", "LOGIN") if m in s.esmtp_features.get("auth", "").upper().split()), None)
                if mech:
                    s.auth(mech, s.auth_plain if mech == "PLAIN" else s.auth_login)
                else:
                    s.login(cfg["smtp_user"], cfg["smtp_password"])
            refused = s.send_message(msg, from_addr=envelope)
        if out is not None:
            out["raw"] = msg.as_bytes()
        if refused:
            return "Empfänger abgelehnt: " + ", ".join(f"{k} ({v[0]})" for k, v in refused.items())
        return None
    except smtplib.SMTPAuthenticationError as e:
        return (f"Anmeldung abgelehnt ({e.smtp_code}). Benutzername oder Passwort stimmen nicht. "
                "Bei Gmail die komplette Adresse und ein App-Passwort verwenden (Bestätigung in zwei Schritten muss an sein).")
    except Exception as e:  # noqa
        return f"{type(e).__name__}: {e}"
