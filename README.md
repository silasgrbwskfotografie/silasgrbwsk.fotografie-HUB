# Studio-Tool silasgrbwsk.fotografie

Interne Arbeitsoberfläche für Aufträge, Zahlungen, Bildauslieferung und Verträge.
Regeln und Server: `CLAUDE.md`. Funktionsumfang und Bauphasen: `PLANUNG.md`.

Stand: **Phase 5** (Verträge mit berechneter Kündigungsfrist und automatischer Verlängerung, PDF-Upload, geschützter Download, Dokumente je Kunde).
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

Deployment hinter dem zentralen Caddy: siehe `CLAUDE.md` und `PLANUNG.md`, Abschnitt "Docker und Caddy".
Die vollständige Anleitung mit Backup und Wiederherstellung folgt in Phase 6.
