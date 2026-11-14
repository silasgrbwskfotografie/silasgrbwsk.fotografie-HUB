# Studio-Tool silasgrbwsk.fotografie

Interne Arbeitsoberfläche für Aufträge, Zahlungen, Bildauslieferung und Verträge.
Regeln und Server: `CLAUDE.md`. Funktionsumfang und Bauphasen: `PLANUNG.md`.

Stand: **Phase 2** (Kunden, Kontakte, Aufträge mit Preisberechnung, Statuswechsel, Liste mit Filtern, Pakete und Einstellungen bearbeiten).
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

## Tests

```
python -m unittest discover -s tests -v
```

## Server

Deployment hinter dem zentralen Caddy: siehe `CLAUDE.md` und `PLANUNG.md`, Abschnitt "Docker und Caddy".
Die vollständige Anleitung mit Backup und Wiederherstellung folgt in Phase 6.
