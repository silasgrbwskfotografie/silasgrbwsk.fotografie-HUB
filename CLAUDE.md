# Studio-Tool (Arbeitstitel)

**Zweck:** Internes Verwaltungstool für silasgrbwsk.fotografie: Aufträge, Zahlungen, Bildauslieferung, Verträge, Postfach, Kalender, Aufgaben. Einziger Nutzer: Silas.
**Domain:** OFFEN (noch nicht festgelegt, dazu `www.`?)
**Technik:** Python (nur Standardbibliothek) und SQLite im Aufbau des Emden Tigers Hubs, eigener Code. Oberfläche HTML, CSS und JavaScript ohne Build-Schritt.
**Repository:** OFFEN (Empfehlung: privat. Bei öffentlich: keine Zugangsdaten, keine privaten Links im Code)
**Suchmaschinen:** `noindex`, weil rein intern.

Funktionsumfang, Datenmodell und Bauphasen stehen in `PLANUNG.md`. Bei Widerspruch gilt diese Datei.
In dieser Datei heißt die Software an manchen Stellen noch app2: Gemeint ist das Studio-Tool (Container `studio-tool`, interner Port 3000).

## Arbeitsweise mit Silas

- Betreiber und Hauptnutzer: Silas. Sprache der Oberfläche, Texte und Antworten: **Deutsch**.
- Texte ohne Gedankenstriche (– und —), das wirkt nach KI.
- Rechner: Windows 11, Shell PowerShell 5.1 (kein `&&`). Git über GitHub Desktop:
  `C:\Users\silas\AppData\Local\GitHubDesktop\app-3.6.10\resources\app\git\cmd\git.exe`.
- **Commit nur nach Rückfrage.** Pushen macht Silas selbst in GitHub Desktop.
- **Vor dem Löschen, Überschreiben oder Stoppen bestehender Dienste fragen.** Fehlt eine Information: nachfragen, nicht raten.
- Passwörter, Tokens und sudo-Passwörter tippt Silas selbst. Nie in Dateien, Befehle oder Chat schreiben.
- Keine Fakten, Rechtstexte oder Daten erfinden. Fehlendes deutlich als Platzhalter markieren.
- Sicherheits- und Systemeinstellungen auf Silas' Geräten nicht ändern.
- Ordner `.claude/` nie committen.

## Server (gemeinsam mit dem Emden Tigers Hub)

- netcup-VPS, Debian 13, IP `62.83.124.184`. Dort läuft produktiv der Hub unter **emden-tigers.de** mit echten Vereinsdaten.
- Anmeldung nur per SSH-Schlüssel als `tigershub` (sudo, Gruppe docker):
  `ssh -i C:\Users\silas\.ssh\tigers_vps tigershub@62.83.124.184`
  root- und Passwort-Anmeldung sind aus. `sudo` fragt nach dem Passwort von `tigershub`: solche Befehle im Terminal laufen lassen, Silas tippt.
- Firewall ufw: nur 22, 80, 443. fail2ban und automatische Sicherheitsupdates sind aktiv. **Keine neuen Ports öffnen.**
- Vom Anbieter, nicht anfassen: Dienst `scp-server-satellite`, Docker Swarm.
- Skripte auf den Server bringen: per `scp` nach `/tmp` kopieren und mit `bash` ausführen (PowerShell-Quoting über SSH ist fehleranfällig).
- Betriebsanleitung auf dem Server: `/opt/docker/DEPLOY.md` (Abschnitt „app2 hinzufügen“).

### Aufbau

```
/opt/docker/
├── DEPLOY.md
├── proxy/                     zentraler Caddy, EINZIGER Container mit 80/443
│   ├── docker-compose.yml     Container proxy-caddy, Netzwerk "proxy"
│   ├── Caddyfile              alle Domains
│   └── .env                   ACME_EMAIL, HUB_DOMAIN, HUB_REDIRECTS, APP2_DOMAIN
└── apps/
    ├── emden-tigers-hub/      Hub (nicht anfassen)
    └── app2/                  hierhin kommt die neue Software
```

```
Internet ──> 80/443 ──> proxy-caddy ──(Docker-Netzwerk "proxy")──> emden-tigers-hub:8765
                                    └──────────────────────────> app2:<interner Port>
```

### Regeln für app2

- **Kein `ports:`** im docker-compose von app2, nur `expose:`. Erreichbar ist app2 ausschließlich über Caddy.
- Netzwerk `proxy` als `external: true` einbinden. Eindeutiger `container_name` (nicht `emden-tigers-hub`, nicht `proxy-caddy`).
- Interner Port frei wählbar, aber nicht 8765 (Hub).
- Log-Begrenzung wie beim Hub (`json-file`, `max-size: 10m`, `max-file: 5`).
- Zugangsdaten nur in `/opt/docker/apps/app2/.env` (`chmod 600`), nie im Repository.
- Daten in einem eigenen Ordner, z. B. `/opt/docker/apps/app2/data` als Volume. Sicherung dafür einplanen (der Hub sichert nur seine eigenen Daten).
- HTTPS macht Caddy (Let's Encrypt, automatisch). app2 selbst spricht nur HTTP im internen Netz.
  Wenn app2 Cookies setzt: `Secure` einschalten. Proxy-Header (`X-Forwarded-For`, `X-Forwarded-Proto`) nur von Caddy vertrauen.
- Öffentliche Adresse der Software fest aus der `.env` (z. B. `DOMAIN`), nie aus `X-Forwarded-Host` oder einem ungeprüften Host-Header ableiten.
- Arbeitsspeicher des VPS teilen sich Hub und app2: Ressourcenbedarf von app2 vorher prüfen (`free -h` auf dem Server).

### Grundgerüst docker-compose.yml (in /opt/docker/apps/app2)

```yaml
x-logging: &logging
  driver: json-file
  options:
    max-size: "10m"
    max-file: "5"

services:
  app2:
    build: .                     # oder image: hersteller/programm:<feste Version>
    container_name: app2
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./data:/data
    expose:
      - "3000"                   # interner Port, NICHT unter ports
    networks: [proxy]
    logging: *logging

networks:
  proxy:
    external: true
```

### Caddy (Proxy) erweitern

Vorlage liegt im Hub-Repository unter `deploy/proxy/Caddyfile` (dort auch nachziehen, damit Vorlage und Server gleich bleiben).

```
{$APP2_DOMAIN} {
	import sicherheit            # HSTS, nosniff, Referrer-Policy, Permissions-Policy, ohne Server-Header
	reverse_proxy app2:3000
}

# optional, z. B. www auf die Hauptadresse
# www.{$APP2_DOMAIN} {
# 	redir https://{$APP2_DOMAIN}{uri} permanent
# }
```

In `/opt/docker/proxy/.env`: `APP2_DOMAIN=...`. Danach:

```
cd /opt/docker/proxy && docker compose up -d && docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile
```

Neue `.env`-Werte übernimmt Caddy nur über `docker compose up -d` (Container neu erstellt), `reload` allein reicht nicht.
**Achtung:** Das Neuerstellen des Proxys unterbricht auch emden-tigers.de für ein paar Sekunden. Vorher mit Silas absprechen.
Ein Fehler im Caddyfile legt beide Seiten lahm: vorher prüfen mit
`docker compose exec caddy caddy validate --config /etc/caddy/Caddyfile`.

### DNS

- A-Eintrag der Domain (und ggf. `www`) auf `62.83.124.184`. Bei welchem Anbieter die Domain liegt: OFFEN.
- Läuft unter der Domain schon E-Mail: **MX- und TXT-Einträge (SPF, DKIM, DMARC) nie ändern**, nur A/AAAA.
- Erst wenn `getent hosts <domain>` auf dem Server die IP zeigt, kann Caddy ein Zertifikat holen.

### Testen nach dem Start

- `curl -I https://<domain>` liefert 200 oder 302.
- `cd /opt/docker/proxy && docker compose logs --tail 100 caddy`: Zertifikat geholt, keine Fehler.
- **Hub danach noch erreichbar:** `curl -s https://emden-tigers.de/healthz`.

## Rechtliches (falls app2 öffentlich erreichbar ist)

- Impressum und Datenschutzerklärung für die neue Domain: Inhalte von Silas, nichts erfinden.
- Keine externen Schriften, Skripte, Tracker oder Einbettungen ohne Rücksprache (beim Hub gilt das ausnahmslos).
- Hosting-Anbieter (netcup) in der Datenschutzerklärung von app2 nennen, Vertrag zur Auftragsverarbeitung beim Anbieter vorhanden?

## Postfach (genau wie im Emden Tigers Hub)

app2 bekommt ein Postfach, das sich so verhält wie das im Hub (Version 4.35). **Vorlage ist der Code des Hubs**, lokal unter
`C:\Users\silas\Documents\GitHub\emden-tigers-hub`: vor dem Bauen dort lesen, nicht neu erfinden. Wichtige Stellen:

| Was | Wo im Hub |
|---|---|
| IMAP-Hilfen, Ordner, Erledigt, Weiterleiten | `server.py`: `postfach_config`, `postfach_open`, `postfach_folders`, `pf_done_folder`, `pf_move_to_done`, `pf_forward_to_person`, `pf_role_folder`, `pf_message`, `pf_text`, `html_to_text`, `pf_attachments`, `pf_unseen` |
| Schnittstelle | `server.py`: `api_postfach` (`/api/postfach/<sub>`), `api_mailtasks` (`/api/mailtasks`) |
| Neue Mails erkennen, Push | `server.py`: `pf_poll`, `pf_poll_loop`, `pf_inbox`, `pf_recipients`, `pf_mark_handled`, `badge_for`, `send_push`, `webpush_encrypt` |
| Eigenes Postfach, Absender | `server.py`: `user_mail_cfg`, `pf_senders`, `own_mail_address`, Admin-Route `/api/admin/users/<id>/mail` |
| Signatur | `server.py`: `signature_parts`, Paket `web/assets/signatur/` (`signatur.html`, `signatur.txt`, Bilder) |
| Oberfläche | `static/pages.js`: `App.pages.postfach`, `pfShow`, `pfCompose`, `refreshMailBadge`, Zuweisen-Dialog; `static/style.css`: `.pf-*` |
| Service Worker | `static/sw.js` (zeigt Push nur an, speichert nichts) |
| Tests (Nachbau eines IMAP-Servers) | beim Hub nur lokal vorhanden, bei Bedarf neu schreiben: FakeIMAP mit LIST, SELECT, UID FETCH/STORE/COPY/MOVE, APPEND, CREATE, COPYUID |

### Voraussetzungen in app2

Das Postfach im Hub hängt an Dingen, die app2 ebenfalls braucht: Konten mit Anmeldung, Rechte pro Bereich
(0 = kein Zugriff, 1 = Lesen, 2 = Bearbeiten, Ausnahme pro Person vor Gruppenrecht), Gruppen, Änderungsprotokoll (`audit`),
geschützte Ablage für Zugangsdaten (Tabelle `secrets`, nie über die API lesbar), Mailversand (`send_mail`), CSRF-Header bei schreibenden Anfragen.
Gibt es das in app2 noch nicht, zuerst bauen oder mit Silas klären, wie viel davon nötig ist.

### Was es kann

- **Vereinspostfach (z. B. info@):** live per IMAP, nichts wird dauerhaft in der eigenen Datenbank gespeichert. Ordnerliste mit deutschen Namen
  (Posteingang, Erledigt, Gesendet, Entwürfe, Archiv, Spam, Papierkorb, dann weitere), Ungelesen-Zahl je Ordner, Seiten zu 40 Mails.
- **Lesen nur als Text:** HTML-Mails werden in Text umgewandelt (`html_to_text`), nie als HTML angezeigt. Keine fremden Bilder, keine Skripte.
  Anhänge nur als Download mit `application/octet-stream` (nie im Browser öffnen lassen).
- **Antworten, Allen antworten, Weiterleiten, Neue Mail:** Antwort geht an `Reply-To`, sonst an `From`. `In-Reply-To`/`References` werden gesetzt,
  die Originalmail bekommt `\Answered`, eine Kopie landet im Ordner „Gesendet“ des Postfachs, über das verschickt wurde.
  Text- und HTML-Fassung mit Signatur (Platzhalter `{{NAME}}`, `{{ROLLE}}`, Bilder öffentlich erreichbar), Zitat der Ursprungsmail.
  Höchstens 20 Empfänger, Adressen geprüft.
- **Erledigt:** Knopf bei jeder Mail (nicht in Gesendet, Entwürfe, Papierkorb, Spam, Erledigt). Verschiebt per IMAP `MOVE` in den Ordner „Erledigt“
  (fehlt MOVE: `COPY`, `\Deleted`, `EXPUNGE`), legt den Ordner bei Bedarf an (mit Namespace-Präfix, z. B. `INBOX.`) und abonniert ihn.
  Die neue UID kommt aus `COPYUID`, sonst Suche nach der Message-ID.
- **Löschen:** in den Papierkorb, nur im Papierkorb selbst endgültig.
- **Gelesen/Ungelesen, Markieren** über IMAP-Flags.
- **Zuweisen (Mail-Aufgaben):** Mail einer Person zuweisen, mit Hinweis. Tabelle `mail_tasks`. Die Person darf genau diese Mail lesen und beantworten,
  auch ohne Postfach-Recht. Push und Info-Mail an die Person. Antwort oder „Erledigt“ schließt die Aufgabe.
  Hat die Person **kein Recht** auf das Vereinspostfach: Die Mail wird mit Anhängen (bis 20 MB) an ihr eigenes Postfach oder ihre Konto-Adresse
  **weitergeleitet**, `Reply-To` = ursprünglicher Absender. Ohne Adresse: Fehlermeldung, keine Aufgabe.
- **Neue Mails melden:** Hintergrund-Abruf alle 120 Sekunden (`pf_poll`). Der erste Lauf merkt sich nur den Stand (UIDVALIDITY, letzte UID),
  meldet nichts Altes. Neue ungelesene Mails landen in `pf_inbox` (Status „neu“) und gehen per Web Push an die Gruppen aus der Einstellung
  `pf_notify_groups`. Wer sie beantwortet, weiterleitet, löscht oder erledigt, schließt sie für alle (Push „Erledigt“ schließt die Meldung auf den anderen Geräten).
  Außerhalb beantwortet (`\Answered`) oder verschwunden zählt auch als erledigt.
- **Zahl im Menü:** ungelesene Mails aus Vereinspostfach und eigenem Postfach zusammen, jede Minute und beim Zurückkehren in den Tab neu. Zahl am App-Symbol (`setAppBadge`) aus offenen Aufgaben und neuen Mails.
- **Eigenes Postfach je Konto:** Admin hinterlegt pro Konto Adresse, SMTP, IMAP, Benutzer, Passwort (Tabelle `user_mail`, Passwort nie lesbar,
  eigener Knopf „Verbindung prüfen“ meldet sich an SMTP und IMAP an, ohne etwas zu verschicken). Die Person sieht es im Postfach **zusätzlich** (Umschalter oben in der Ordnerliste, `box=own`)
  und kann dort alles außer Zuweisen. Schalter „kein Zugriff auf info@“ setzt die Ausnahme Postfach = 0.
- **Absender wählen:** Wer auf mehrere Postfächer Zugriff hat, wählt beim Schreiben, worüber die Mail rausgeht (`from`: `info`/`own`).
- **Kontaktformular:** Anfragen gehen mit `Reply-To` der anfragenden Person an info@, „Antworten“ geht direkt an sie.
  Anfragende mit E-Mail bekommen eine Eingangsbestätigung **ohne** Formularinhalt (sonst Spam-Schleuder).

### Rechte

| Recht | Darf |
|---|---|
| Postfach 0 | nichts, außer zugewiesene Mails (über die Aufgabe) und das eigene Postfach |
| Postfach 1 | Vereinspostfach lesen, Erledigt, Gelesen/Markieren |
| Postfach 2 | zusätzlich antworten, schreiben, weiterleiten, löschen, zuweisen |
| eigenes Postfach | volle Rechte darin, unabhängig vom Bereich |

Der Server prüft jede Anfrage, die Oberfläche blendet nur aus. Jede Aktion (gesendet, gelöscht, zugewiesen, weitergeleitet) steht im Änderungsprotokoll.
Der Bereich Postfach zählt nicht als „irgendein Leserecht“ für andere Tabellen.

### Technik und Sicherheit

- Nur Python-Standardbibliothek: `imaplib` (SSL, Port 993, Zeitlimit 20 s), `smtplib`, `email` mit `policy.default`. Web Push (VAPID, RFC 8291) ebenfalls ohne Zusatzpakete.
- IMAP-Server aus Einstellung `imap_host`, sonst aus dem SMTP-Server (`smtp.` wird `imap.`). Hostname nur `[A-Za-z0-9.-]`.
- Ordnernamen IMAP-UTF-7 dekodieren, immer gequotet senden. UIDs nur als Ziffern annehmen. Lesen mit `BODY.PEEK` (setzt nicht automatisch gelesen).
- Ordner-Rollen über SPECIAL-USE-Flags, sonst über bekannte Namen (`PF_ROLE_NAMES`).
- SMTP-/IMAP-Passwörter nur in `secrets` bzw. `user_mail`, nie über die API ausgeben, nicht im Backup-Download, beim Serverumzug dabei.
- Push-Abos nur zu bekannten Push-Diensten (`push_endpoint_ok`), Push-Inhalt nur Betreff und Absendername, Service Worker speichert nichts.
- Mailserver im Hub: Strato (Fähigkeiten MOVE, UIDPLUS, SPECIAL-USE, Namespace `""` mit Trenner `.`). Für app2: Anbieter OFFEN, Fähigkeiten dort prüfen.
- Neue Datenverarbeitung (Weiterleiten, Bestätigungsmail, Push) in der Datenschutzerklärung von app2 erwähnen.

## Offene Fragen vor dem Start

1. Was ist app2, und für wen?
2. Welche Domain, bei welchem DNS-Anbieter, mit oder ohne `www`?
3. Eigener Code oder fertiges Programm? Welche Sprache, welche Datenbank?
4. Braucht app2 E-Mail-Versand? (SMTP-Zugang wie beim Hub über Strato?)
5. Sollen Suchmaschinen app2 finden, oder `noindex`?
6. Wie wird gesichert (Datenbank, Uploads), und wer aktualisiert?
7. Erst auf der Test-VM ausprobieren (wie beim Hub) oder direkt auf den VPS?
8. Postfach: Welche Adresse ist das gemeinsame Postfach, bei welchem Mailanbieter? Gibt es in app2 schon Konten, Gruppen und Rechte?
   Welche Gruppen bekommen die Push-Meldung bei neuen Mails? Eigene Signatur (Logo, Farben) für app2?
