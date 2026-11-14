# Studio-Tool silasgrbwsk.fotografie

Interne Arbeitsoberfläche für Aufträge, Zahlungen, Bildauslieferung und Verträge.
Regeln und Server: `CLAUDE.md`. Funktionsumfang und Bauphasen: `PLANUNG.md`.

Stand: **Phase 9** (Postfach aus dem Hub übernommen: mehrere Mailkonten, live per IMAP, Lesen nur als Text, Antworten, Weiterleiten, Erledigt, Löschen, Push bei neuen Mails, Kundenerkennung, Auftrag, Termin oder Aufgabe aus einer Mail, Textvorlagen).
Davor Phase 8: Eigene Termine mit Wiederholung und Erinnerung, Kalender mit Woche und Tag, Warnung bei Überschneidungen, Aufgaben mit Ansichten und Vorlagen je Paket, wiederkehrende Aufgaben, Push-Erinnerungen, fremder Kalender per ICS-Link.
Davor Phase 7: iPhone-App: Manifest, App-Symbole, Service Worker ohne Zwischenspeicher, Push-Mitteilungen mit VAPID wie im Hub, Zahl am App-Symbol, Installationshinweis.
Davor Phase 6: Startseite mit Kennzahlen, Kalender (Monat und Liste) mit Aufträgen und Fristen, Kalender-Abo fürs iPhone, Serien-Anlage, Sicherung außerhalb des Servers, Anleitung für Deployment und Wiederherstellung.
Davor Phase 5: Verträge mit berechneter Kündigungsfrist und automatischer Verlängerung, PDF-Upload, geschützter Download, Dokumente je Kunde.
Davor Phase 4: Bildauslieferung: Galerie-Links mit Ablaufdatum, Lieferfrist-Ampel, Nachrichtenvorlagen.
Davor Phase 3: Zahlung und Anzahlung je Auftrag, Finom-Häkchen mit Rechnungsnummer, Liste "Noch in Finom abzurechnen", Umsatz je Monat und Kunde, CSV-Export.
Davor Phase 2: Kunden, Kontakte, Aufträge mit Preisberechnung, Auftragsseite mit Duplizieren, Protokoll, Passwort ändern, nächtliche Sicherung.
Davor Phase 1: Grundgerüst, Anmeldung mit Zwei-Faktor, Datenbank, Navigation.

## Lokal starten (Windows, PowerShell)

Voraussetzung: Python 3.10 oder neuer. Zusatzpakete braucht es keine.

Ersten Benutzer anlegen (fragt das Passwort verdeckt ab, mindestens 10 Zeichen):

```
python server.py adduser silas
```

Server starten: `Start.bat` doppelklicken, oder in PowerShell:

```
python server.py
```

Dann im Browser `http://127.0.0.1:3000` öffnen. Die Daten liegen im Ordner `data` (nicht im Repository).

Passwort ändern: `python server.py passwd silas`. Konten anzeigen: `python server.py users`.

Beim ersten Login muss die Zwei-Faktor-Anmeldung eingerichtet werden (Seite "Sicherheit", QR-Code mit einer Authenticator-App
scannen, zum Beispiel die Passwörter-App am iPhone). Die 10 Wiederherstellungscodes sicher ablegen.

Notfall (Handy weg und keine Wiederherstellungscodes mehr), auf dem Server:

```
docker compose exec studio-tool python server.py 2fa-reset silas
```

## Lokal mit Docker

```
copy .env.example .env
```

In der `.env` `STUDIO_ADMIN_PASSWORD` selbst eintragen, dann:

```
docker compose -f docker-compose.lokal.yml up --build
```

## Sicherung

Solange der Server läuft, entsteht jede Nacht eine Kopie der Datenbank unter `data/backups/studio-JJJJ-MM-TT.db`.
Behalten werden 14 Tagesstände und 6 Monatsstände. In den Einstellungen steht die letzte Sicherung, dort gibt es auch "Jetzt sichern".

Wiederherstellen: Server stoppen, die gewünschte Datei aus `data/backups` als `data/studio.db` kopieren
(vorhandene Dateien `studio.db-wal` und `studio.db-shm` löschen), Server starten.

Die Kopien liegen auf demselben Rechner wie das Tool. Die Ablage außerhalb des Servers und die Sicherung der Uploads folgen in Phase 6.

## Tests

```
python -m unittest discover -s tests -v
```

## Server

Betrieb auf dem netcup-VPS hinter dem zentralen Caddy, neben dem Emden Tigers Hub. Regeln: `CLAUDE.md`.
Befehle mit `sudo` tippt Silas selbst, ebenso alle Passwörter.

### Erstes Deployment

1. Speicher prüfen: `free -h` (Hub und Studio-Tool teilen sich den Arbeitsspeicher, das Tool braucht im Leerlauf etwa 30 bis 60 MB).
2. Dateien nach `/opt/docker/apps/app2` bringen (per `git clone` oder `scp`), dann dort:
   ```
   cp .env.example .env && chmod 600 .env
   nano .env                       # STUDIO_ADMIN_PASSWORD selbst eintragen
   mkdir -p data && sudo chown -R 1000:1000 data
   docker compose up -d --build
   docker compose logs --tail 50 studio-tool
   ```
3. DNS: A-Eintrag `hub` zeigt auf `62.83.124.184`. Prüfen: `getent hosts hub.silasgrbwskfotografie.de`.
4. Caddy (nur nach Absprache, das Neuerstellen unterbricht emden-tigers.de für ein paar Sekunden):
   - in `/opt/docker/proxy/.env`: `APP2_DOMAIN=hub.silasgrbwskfotografie.de`
   - im Caddyfile (und in der Vorlage `deploy/proxy/Caddyfile` im Hub-Repository):
     ```
     {$APP2_DOMAIN} {
     	import sicherheit
     	reverse_proxy studio-tool:3000
     }
     ```
   - prüfen und übernehmen:
     ```
     cd /opt/docker/proxy
     docker compose exec caddy caddy validate --config /etc/caddy/Caddyfile
     docker compose up -d && docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile
     ```
5. Testen: `curl -I https://hub.silasgrbwskfotografie.de` liefert 200 oder 302, `docker compose logs --tail 100 caddy` ohne Fehler,
   und der Hub antwortet noch: `curl -s https://emden-tigers.de/healthz`.
6. Im Browser anmelden, Zwei-Faktor einrichten, danach `STUDIO_ADMIN_PASSWORD` in der `.env` wieder leeren.

### Aktualisieren

```
cd /opt/docker/apps/app2 && git pull && docker compose up -d --build
```

Die Datenbank wird beim Start automatisch um neue Spalten ergänzt, vorhandene Daten bleiben.

### Sicherung außerhalb des Servers

Im Container entsteht jede Nacht eine Datenbank-Kopie unter `data/backups`. Dazu packt `deploy/backup.sh` (auf dem Server, per cron)
die frische Datenbank und den Upload-Ordner in ein Archiv unter `offsite/`, behält 14 Tages- und 6 Monatsstände und kopiert es per rclone weg.

1. `rclone config`: Ziel einrichten, empfohlen ein verschlüsseltes Remote (crypt) auf pCloud. Zugangsdaten tippt Silas selbst.
2. `chmod +x deploy/backup.sh`, einmal von Hand laufen lassen: `RCLONE_REMOTE=pcloud-crypt:studio-tool ./deploy/backup.sh`
3. `crontab -e`:
   ```
   30 3 * * * RCLONE_REMOTE=pcloud-crypt:studio-tool /opt/docker/apps/app2/deploy/backup.sh >> /opt/docker/apps/app2/offsite/backup.log 2>&1
   ```

### Wiederherstellen

```
cd /opt/docker/apps/app2
docker compose stop studio-tool
mkdir -p /tmp/wiederherstellung && tar -xzf offsite/studio-JJJJ-MM-TT.tar.gz -C /tmp/wiederherstellung
cp data/studio.db data/studio.db.vorher                       # alten Stand aufheben
cp /tmp/wiederherstellung/backups/studio-JJJJ-MM-TT.db data/studio.db
rm -f data/studio.db-wal data/studio.db-shm
cp -r /tmp/wiederherstellung/uploads/. data/uploads/
sudo chown -R 1000:1000 data
docker compose start studio-tool
```

Danach anmelden und Stichproben prüfen (letzte Aufträge, eine Vertrags-PDF öffnen). Die Wiederherstellung einmal wirklich durchspielen,
bevor echte Daten im Tool liegen.
