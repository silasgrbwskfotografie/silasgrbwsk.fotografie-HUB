# Studio-Tool silasgrbwsk.fotografie: Planung

Nov 13, 2026 · @Silas

## Ziel und Rahmen

Das Tool ist die zentrale Arbeitsoberfläche für silasgrbwsk.fotografie: Jeder Auftrag ist von der Anfrage bis zur Bezahlung an einer Stelle sichtbar, inklusive Liefer-Links und Vertrag.

- **Nutzer:** nur du, ein Admin-Login. Kein Kundenbereich, kein öffentliches Formular.
- **Betrieb:** ein Docker-Container auf dem V-Server, über Caddy unter einer eigenen Subdomain erreichbar.
- **Bedienung:** als installierbare Web-App auf dem iPhone (Symbol auf dem Home-Bildschirm, Vollbild, Push-Mitteilungen) und im Browser am PC.
- **Sprache:** Oberfläche auf Deutsch, Beträge in Euro, Datum im Format TT.MM.JJJJ.

Grundlage ist deine Vorlage `APP2-CLAUDE.md`: Das Studio-Tool ist die dort beschriebene app2. Es läuft auf dem netcup-VPS neben dem Emden Tigers Hub, hinter dem zentralen Caddy, und das Postfach wird aus dem Hub übernommen statt neu erfunden. Die Vorlage bleibt die `CLAUDE.md` des neuen Repositorys, dieses Dokument wird die `PLANUNG.md` daneben. Bei Widerspruch gilt die `CLAUDE.md`.

Bewusst nicht Teil des Tools:

- **Rechnungen schreiben.** Das bleibt in Finom. Das Tool zeigt nur, was noch abzurechnen ist, und merkt sich die Finom-Rechnungsnummer.
- **Bilder speichern oder ausliefern.** Das bleibt bei Picdrop und pCloud. Das Tool verwaltet nur die Links und Fristen.
- **Amtliche Buchhaltung und Steuererklärung.** Keine Abgabe ans Finanzamt (kein ELSTER), keine GoBD-Buchhaltung. Ab Phase 10 bereitet das Tool aber Einnahmen, Ausgaben, Belege und Fahrten so vor, dass Finom oder die Steuerberatung damit arbeiten können.

## Funktionsumfang

Neun Module plus eine Startseite. Die ersten vier drehen sich um den Auftrag, dazu kommen E-Mail, Kalender, Aufgaben, die Steuer-Vorbereitung und das Fahrtenbuch.

### Startseite (Dashboard)

- Nächste Termine der kommenden 14 Tage
- Überfällige Lieferungen (Galerie nicht innerhalb von 5 Tagen nach dem Spiel bereitgestellt)
- Offene Zahlungen mit Summe
- Picdrop-Links, die in den nächsten 7 Tagen ablaufen
- Verträge, deren Kündigungsfrist oder Laufzeitende näher rückt
- Umsatz im laufenden Jahr

### Aufträge und Spiele

- Kunden anlegen: Verein, Sparte oder Einzelperson, jeweils mit Ansprechperson
- Auftrag anlegen mit Datum, Uhrzeit, Ort, Sportart, Begegnung und Paket
- Pakete als Vorlagen mit Preis: Basic 30 €, Pro 45 €, Spielershooting 60 € (bis 25 Spieler, jeder weitere 0,90 €), Saisonspiel HSG Emden 35 €. Preise sind in den Einstellungen änderbar.
- Anfahrt automatisch berechnen: Kilometer eingeben, die ersten 10 km ab Emden frei, danach 0,30 € pro km
- Status je Auftrag: Angefragt, Bestätigt, Fotografiert, Geliefert, Abgeschlossen, Abgesagt
- Kalenderansicht und Listenansicht mit Filter nach Kunde, Status und Zeitraum
- Kalender-Abo als ICS-Link, damit die Termine im Handykalender erscheinen
- Serien anlegen: mehrere Spieltage eines Vereins in einem Schritt

### Zahlungen und Rechnungen

- Betrag je Auftrag aus Paket, Zusatzspielern und Anfahrt, manuell überschreibbar
- Zahler getrennt vom Kunden erfassbar, weil bei der HSG Emden der buchende Spieler oder Spartenverantwortliche zahlt
- Zahlstatus: Offen, Bezahlt, Erlassen, dazu Zahlart (Bar, Überweisung, PayPal) und Zahldatum
- Häkchen "in Finom abgerechnet" mit Feld für die Rechnungsnummer
- Liste "Noch in Finom abzurechnen" mit kopierfertigem Leistungstext pro Auftrag
- Umsatz pro Monat, Jahr und Kunde, mit CSV-Export
- Anzeige des Jahresumsatzes gegen eine einstellbare Kleinunternehmergrenze

### Bildauslieferung

- Pro Auftrag beliebig viele Links mit Typ (Picdrop, pCloud, Sonstiges), Empfänger und Ablaufdatum
- Lieferfrist automatisch: Spieldatum plus 5 Tage, Ampel im Auftrag
- Picdrop-Ablauf automatisch vorbelegt mit 30 Tagen ab Erstellung
- Hinweisfeld pro Link, zum Beispiel "mit Wasserzeichen, für Spieler" oder "ohne Wasserzeichen, nur Verein"
- Nachrichtenvorlagen mit Platzhaltern (Name, Spiel, Link, Ablaufdatum) zum Kopieren für WhatsApp oder Instagram

### Verträge und Dokumente

- Verträge je Kunde mit Art (Saisonvertrag, Einwilligungs- und Nutzungsvereinbarung, Sponsoring), Beginn, Mindestlaufzeit, Kündigungsfrist und Ende
- PDF-Upload des unterschriebenen Vertrags, Download und Vorschau
- Automatisch berechnetes Datum "spätestens kündigen bis"
- Freie Dokumentenablage pro Kunde, zum Beispiel Akkreditierungen

### E-Mail

Das Postfach verhält sich wie im Emden Tigers Hub (Version 4.35) und wird aus dessen Code portiert.

- **Mehrere Konten:** je Konto Adresse, SMTP, IMAP, Benutzer und Passwort, mit Knopf "Verbindung prüfen". Umschalter zwischen den Postfächern oben in der Ordnerliste.
- **Live per IMAP:** Mails werden nicht dauerhaft in der eigenen Datenbank gespeichert. Ordnerliste mit deutschen Namen, Ungelesen-Zahl je Ordner, Seiten zu 40 Mails.
- **Lesen nur als Text:** HTML-Mails werden in Text umgewandelt, keine fremden Bilder, keine Skripte. Anhänge nur als Download.
- **Schreiben:** Antworten, Allen antworten, Weiterleiten, Neue Mail, mit Signatur und Zitat. Kopie landet im Ordner Gesendet des Postfachs, über das verschickt wurde. Absender wählbar.
- **Erledigt:** Knopf bei jeder Mail, verschiebt sie in den Ordner Erledigt und legt ihn bei Bedarf an.
- **Löschen** in den Papierkorb, **Gelesen, Ungelesen, Markieren** über IMAP-Flags.
- **Neue Mails melden:** Abruf im Hintergrund alle 120 Sekunden, Push aufs iPhone, Zahl im Menü und am App-Symbol.

Was aus dem Hub entfällt, weil nur du das Tool nutzt: Zuweisen an Personen, Rechte je Bereich, Gruppen und das Kontaktformular. Bitte bestätigen, siehe offene Punkte.

Was für das Studio-Tool dazukommt:

- Passt die Absenderadresse zu einem Kontakt, zeigt die Mail den Kunden an und lässt sich mit einem Auftrag verknüpfen (gespeichert wird nur der Verweis, nicht die Mail).
- Aus einer Mail mit einem Klick einen Auftrag, einen Termin oder eine Aufgabe machen.
- Textvorlagen mit Platzhaltern, zum Beispiel für die Galerie-Auslieferung.

Hinweis zu Gmail: Google akzeptiert für IMAP kein normales Passwort mehr. Du brauchst ein App-Passwort (setzt die Bestätigung in zwei Schritten voraus) oder eine Anmeldung per OAuth. Für Version 1 ist das App-Passwort der einfache Weg. Bitte vor dem Bau kurz in deinem Google-Konto prüfen, ob App-Passwörter dort verfügbar sind.

### Kalender

- Monats-, Wochen- und Tagesansicht sowie eine Agenda-Liste fürs Handy
- Aufträge erscheinen automatisch, dazu eigene Termine (Besprechung, Shooting-Vorbereitung, privat geblockt)
- Auch Lieferfristen, Vertragsfristen und fällige Aufgaben lassen sich einblenden
- Warnung bei Überschneidungen, zum Beispiel zwei Spiele zur selben Zeit
- Wiederkehrende Termine und Erinnerungen per Push
- ICS-Abo, damit alles auch im iPhone-Kalender steht. Optional umgekehrt: einen bestehenden Kalender per ICS-Link einlesen, um Dienstzeiten oder private Termine zu sehen.

### Aufgabenplaner

- Aufgaben mit Fälligkeit, Priorität und Status (Offen, In Arbeit, Erledigt)
- Verknüpfung mit Kunde, Auftrag oder Mail
- Ansichten: Heute, Diese Woche, Überfällig, Alle
- Aufgaben-Vorlagen je Paket: Beim Anlegen eines Auftrags entstehen automatisch die üblichen Schritte, zum Beispiel Akkus laden, Bilder sichern, Auswahl bearbeiten, Galerie hochladen, Link verschicken, Zahlung prüfen
- Wiederkehrende Aufgaben, zum Beispiel monatlich Belege in Finom prüfen
- Erinnerung per Push am Fälligkeitstag

### iPhone-App

- Umsetzung als Progressive Web App: in Safari öffnen, über "Teilen" zum Home-Bildschirm hinzufügen, danach startet sie wie eine App ohne Browserleiste
- Push-Mitteilungen für neue Mails, Termine und fällige Aufgaben. Auf dem iPhone funktionieren sie nur, wenn die App auf dem Home-Bildschirm installiert ist.
- Untere Navigationsleiste mit Start, Aufträge, Mail, Kalender, Aufgaben
- Die App braucht eine Verbindung. Der Service Worker zeigt wie im Hub nur Push an und speichert nichts auf dem Gerät.
- Kein App Store nötig. Eine echte native App wäre deutlich mehr Aufwand (Apple-Entwicklerkonto, eigener Build) und bringt für diesen Zweck kaum Vorteile.

### Ausgaben und Steuer-Vorbereitung (Phase 10)

Vorbereitung für Steuerberatung und Finom, ausdrücklich keine amtliche Buchhaltung und keine Abgabe ans Finanzamt.

- Ausgaben erfassen: Datum, Betrag, Kategorie, Lieferant, Zahlart, Notiz, Beleg als PDF oder Foto vom iPhone. Optional einem Auftrag zuordnen.
- Kategorien als Vorlage, zum Beispiel Ausrüstung, Software und Abos, Fahrtkosten, Telefon und Internet, Fortbildung, Bürobedarf, Sonstiges. Änderbar in den Einstellungen.
- Anlagegüter markieren (zum Beispiel Kamera, Objektiv) mit Kaufdatum, damit die Steuerberatung die Abschreibung festlegen kann. Das Tool rechnet keine Abschreibung aus.
- Einnahmen kommen automatisch aus den bezahlten Zahlungen, nichts doppelt eintippen.
- Übersicht im Aufbau einer EÜR: Einnahmen, Ausgaben je Kategorie und Ergebnis je Monat und Jahr. Klar beschriftet als Vorbereitung, nicht als amtliche Erklärung.
- Fahrten kommen aus dem Fahrtenbuch (Phase 11). Bis dahin eine einfache Liste aus den Kilometern der Aufträge.
- Belege, deren Datum oder Betrag fehlt, erscheinen als "unvollständig".
- Export je Zeitraum: CSV für Einnahmen, Ausgaben und Fahrten, dazu alle Belege als ZIP mit verständlichen Dateinamen. DATEV-Format nur, wenn die Steuerberatung es verlangt.
- Abgeschlossene Monate lassen sich sperren, danach sind Änderungen nur mit Vermerk im Protokoll möglich.
- Umsatzsteuer: nur Felder für Steuersatz und Steuerbetrag je Beleg. Welche Regeln gelten (Kleinunternehmer oder nicht), klärt Silas mit der Steuerberatung.

Vor dem Bau mit der Steuerberatung klären: welche Kategorien, welches Exportformat, ob Kleinunternehmerregelung gilt und wie Belege aufbewahrt werden müssen.

### Fahrtenbuch (Phase 11)

Ersetzt Driversnote. Ziel ist ein Fahrtenbuch, das den Anforderungen des Finanzamts an ein elektronisches Fahrtenbuch möglichst entspricht.
Ob es anerkannt wird, entscheidet am Ende das Finanzamt. Vor dem Umstieg mit der Steuerberatung abstimmen.

- Fahrten mit Datum, Uhrzeit Beginn und Ende, Kilometerstand Beginn und Ende, Start- und Zieladresse, Zweck, Geschäftspartner (Kunde oder Auftrag) und Art: betrieblich, privat, Wohnung und Arbeitsstätte. Bei Umwegen eine Begründung.
- Kilometerstände lückenlos: Der Anfangsstand jeder Fahrt muss zum Endstand der vorherigen passen, sonst Warnung. Abgleich mit Kilometerständen auf Werkstatt- und Tankbelegen.
- Mehrere Fahrzeuge möglich, je Fahrzeug eigene Kilometerfolge.
- Nachträgliche Änderungen: Der Zeitpunkt jeder Erfassung wird gespeichert. Jede Änderung wird mit altem und neuem Wert protokolliert und bleibt sichtbar. Abgeschlossene Monate sind gesperrt.
- Aufträge verknüpfen: Aus einem Auftrag mit Ort entsteht ein Fahrtvorschlag, der nur noch bestätigt werden muss.
- **Import aus Driversnote:** Export-Datei hochladen, Vorschau mit Zuordnung der Spalten, Dubletten erkennen. Importierte Fahrten sind als "aus Driversnote" markiert, die Original-Datei wird aufbewahrt. Das genaue Format wird erst mit einer echten Export-Datei festgelegt.
- **GPS-Aufzeichnung** in der Web-App: Start und Stopp per Knopf, Punkte mit schlechter Genauigkeit werden verworfen, Strecke aus den Punkten berechnet.
  Maßgeblich für das Fahrtenbuch bleibt der Kilometerstand vom Tacho, die GPS-Strecke dient als Vorschlag und Kontrolle.
  Grenze des iPhones: Eine Web-App zeichnet nur auf, solange sie im Vordergrund ist und der Bildschirm an ist. Bei gesperrtem Bildschirm oder wenn eine Navigations-App vorne ist, stoppt die Aufzeichnung. Das Tool erkennt solche Lücken und zeigt sie an.
- **Karte:** Jede Fahrt mit aufgezeichneter Strecke auf einer Karte, Kartenbibliothek lokal eingebunden. Woher die Kartenbilder kommen, ist eine offene Entscheidung (siehe offene Punkte).
- Auswertung je Jahr und Fahrzeug: betriebliche, private und Arbeitsweg-Kilometer, Anteil in Prozent. Export als PDF und CSV.

### Später möglich, nicht in Version 1

- Erinnerungen per E-Mail oder Telegram
- Kundenbereich oder öffentliches Anfrageformular
- Vertrags-PDF direkt aus einer Vorlage erzeugen
- Zahlungseingänge automatisch über die Bankschnittstelle (XS2A) abgleichen
- Eigene iPhone-App für das Fahrtenbuch, falls GPS im Hintergrund nötig wird (braucht Apple-Entwicklerkonto)

## Datenmodell

Sieben Tabellen bilden den Kern, acht weitere kommen für Postfach, Kalender, Aufgaben, Push und Betrieb dazu, drei für die Steuer-Vorbereitung. Der Auftrag ist der Mittelpunkt, alles andere hängt daran oder am Kunden.

| Tabelle | Zweck | Wichtige Felder |
| --- | --- | --- |
| Kunde | Verein, Sparte oder Einzelperson | Name, Typ, übergeordneter Kunde (Sparte gehört zu Verein), Notizen |
| Kontakt | Ansprechperson oder Zahler | Name, Rolle, Telefon, E-Mail, Instagram, Kunde |
| Paket | Preisvorlage | Name, Grundpreis, inklusive Spieler, Preis je Zusatzspieler, Finom-Leistungstext, aktiv |
| Auftrag | Ein Spiel oder Shooting | Kunde, Paket, Datum, Uhrzeit, Ort, Sportart, Begegnung, Status, Kilometer, Anzahl Spieler, Betrag, Lieferfrist, Notizen |
| Zahlung | Geld zum Auftrag | Auftrag, Zahler (Kontakt), Betrag, Status, Zahlart, Zahldatum, in Finom abgerechnet, Rechnungsnummer |
| Lieferlink | Galerie-Link zum Auftrag | Auftrag, Typ, URL, Empfänger, erstellt am, läuft ab am, Hinweis |
| Vertrag | Vereinbarung mit Kunde | Kunde, Art, Beginn, Mindestlaufzeit, Kündigungsfrist, Ende, Datei, Notizen |

| Tabelle (Erweiterung) | Zweck | Wichtige Felder |
| --- | --- | --- |
| Mailkonto | Hinterlegtes Postfach, wie `user_mail` im Hub | Name, Adresse, SMTP, IMAP, Benutzer, Signatur. Das Passwort liegt in `secrets`. |
| Mail-Eingang | Stand des Hintergrund-Abrufs, wie `pf_inbox` im Hub | Konto, UIDVALIDITY, letzte UID, Message-ID, Betreff, Absender, Status (neu, erledigt) |
| Mail-Verweis | Verknüpfung einer Mail mit Kunde oder Auftrag | Konto, Ordner, Message-ID, Kunde, Auftrag |
| Termin | Eigener Kalendereintrag | Titel, Beginn, Ende, ganztägig, Ort, Wiederholung, Erinnerung, Kunde, Auftrag |
| Aufgabe | To-do | Titel, Fälligkeit, Priorität, Status, Wiederholung, Kunde, Auftrag, Mail-Verweis |
| Push-Abo | Angemeldetes Gerät | Endpunkt, Schlüssel, Gerätename, angelegt am |
| secrets | Geschützte Ablage für Zugangsdaten, wie im Hub | Schlüssel, Wert. Nie über die API lesbar, nicht im Backup-Download. |
| audit | Änderungsprotokoll, wie im Hub | Zeitpunkt, Aktion (gesendet, gelöscht, geändert), Bezug |

| Tabelle (Phase 10) | Zweck | Wichtige Felder |
| --- | --- | --- |
| Ausgabe | Beleg einer Ausgabe | Datum, Betrag in Cent, Steuersatz, Steuerbetrag in Cent, Kategorie, Lieferant, Zahlart, Anlagegut, Auftrag, Datei, Notiz |
| Ausgaben-Kategorie | Vorlage für Kategorien | Name, Sortierung, aktiv |
| Fahrzeug | Auto für das Fahrtenbuch | Name, Kennzeichen, Anfangs-Kilometerstand, aktiv |
| Fahrt | Eintrag im Fahrtenbuch (Phase 11) | Fahrzeug, Datum, Beginn, Ende, km-Stand Beginn und Ende, Start, Ziel, Zweck, Geschäftspartner, Art, Umweg-Begründung, Kunde, Auftrag, Quelle (Hand, GPS, Driversnote), erfasst am, gesperrt |
| Fahrt-Punkt | GPS-Punkt einer aufgezeichneten Fahrt | Fahrt, Zeit, Breite, Länge, Genauigkeit |
| Fahrt-Änderung | Protokoll jeder Änderung an einer Fahrt | Fahrt, Zeitpunkt, Feld, alter Wert, neuer Wert, Grund |

Dazu kommen zwei technische Tabellen: Einstellungen (Anfahrt frei bis km, Preis je km, Lieferfrist in Tagen, Picdrop-Laufzeit, Umsatzgrenze) und Dokument (freie Dateiablage je Kunde).

Regeln für die Umsetzung:

- Geldbeträge als ganze Cent speichern, nie als Kommazahl.
- Der Betrag wird beim Anlegen aus Paket, Zusatzspielern und Anfahrt berechnet und dann im Auftrag festgeschrieben. Spätere Preisänderungen am Paket ändern alte Aufträge nicht.
- Nichts wird hart gelöscht, was eine Zahlung hat. Stattdessen Status Abgesagt oder Archiviert.
- Die Startdaten (deine Pakete und Einstellungen) kommen über ein Seed-Skript.
- Entschieden am 14.11.2026 (Phase 2): Ändern sich bei einem bestehenden Auftrag Kilometer oder Spielerzahl, wird mit den Preisen vom Anlegen gerechnet. Nur ein Paketwechsel holt die aktuellen Preise des neuen Pakets. Von Hand gesetzte Beträge bleiben stehen.
- Entschieden am 14.11.2026 (Phase 2): Kunden und Aufträge werden archiviert. Endgültig löschen geht nur, wenn nichts daran hängt (Kunde ohne Aufträge, Auftrag ohne Zahlung, Kontakt nicht als Zahler, Paket ohne Aufträge).
- Entschieden am 14.11.2026 (Phase 2): Sportart ist ein freies Textfeld, bereits benutzte Sportarten werden vorgeschlagen.
- Entschieden am 14.11.2026 (Phase 3): Jeder Auftrag hat genau eine Zahlung, dazu optional eine Anzahlung. Die Zahlung entsteht mit dem Auftrag, ihr Betrag ist Auftragsbetrag minus Anzahlung und zieht nach, solange sie offen ist.
- Entschieden am 14.11.2026 (Phase 3): Umsatz zählt nach Zahldatum, nur bezahlte Zahlungen. Bezahlt ohne Datum bekommt das heutige Datum.
- Entschieden am 14.11.2026 (Phase 3): "Noch in Finom abzurechnen" zeigt nur bezahlte Zahlungen ohne Finom-Häkchen, Zahlung und Anzahlung getrennt.
- Phase 3: Ein Auftrag lässt sich nur löschen, solange seine Zahlungen offen und nicht abgerechnet sind. Sonst archivieren.
- Entschieden am 14.11.2026 (Phase 4): Ein Auftrag gilt als geliefert, sobald ein Galerie-Link eingetragen ist. Steht der Status noch auf Angefragt, Bestätigt oder Fotografiert, wechselt er auf Geliefert.
- Phase 4: Lieferfrist-Ampel rot = Frist vorbei, gelb = Spiel war und Frist läuft, grün = geliefert. Galerie-Links nur mit https://.
- Phase 5: Vertragsende = festes Ende oder Beginn plus Mindestlaufzeit minus 1 Tag. "Spätestens kündigen bis" = Ende minus Frist (Monate zum Monatsende abgeschnitten). Verlängert sich der Vertrag und ist die Frist vorbei, zählt die nächste Periode. Uploads nur PDF bis 15 MB, am Inhalt geprüft.
- Entschieden am 14.11.2026: Alle weiteren Phasen am Stück, Commit nach jeder Phase. Kalender liest zusätzlich einen fremden ICS-Link ein. Fahrtenbuch-Karte mit OpenStreetMap-Kacheln. Aufgaben-Vorlagen je Paket aus der Liste dieser Planung.

## Technik und Architektur

Der Stack wechselt von Next.js auf Python mit SQLite, im selben Aufbau wie der Emden Tigers Hub. Grund: Deine Vorlage verlangt, das Postfach aus dem Hub-Code zu übernehmen. Das geht nur dann fast eins zu eins, wenn das Studio-Tool dieselbe Sprache und denselben Aufbau hat.

| Baustein | Wahl | Grund |
| --- | --- | --- |
| Sprache und Server | Python, Aufbau wie `server.py` im Hub | Postfach, Anmeldung, Push und Protokoll lassen sich übernehmen |
| Datenbank | SQLite als Datei unter `/data` | Kein zweiter Container, Backup ist eine Datei |
| Oberfläche | HTML, CSS und JavaScript ohne Build-Schritt, wie `static/pages.js` und `static/style.css` im Hub | Gleiche Bausteine, Postfach-Oberfläche (`.pf-*`) wiederverwendbar |
| Postfach | Nur Python-Standardbibliothek: `imaplib` (SSL, Port 993, Zeitlimit 20 s), `smtplib`, `email` | Wie im Hub, keine Zusatzpakete |
| Hintergrund-Abruf | Schleife im selben Prozess, alle 120 Sekunden (`pf_poll_loop`) | Ein Container reicht, kein zweiter Dienst |
| Push | Web Push mit VAPID, ohne Zusatzpakete (`send_push`, `webpush_encrypt`) | Wie im Hub |
| App auf dem iPhone | Web-App-Manifest und Service Worker nach `static/sw.js` (zeigt Push nur an, speichert nichts) | Installierbar ohne App Store |
| Kalender-Oberfläche | FullCalendar, lokal eingebunden, kein CDN | Monat, Woche, Tag, Agenda fertig. Alternativ eigene einfache Ansicht. |
| Zugangsdaten | Tabelle `secrets`, nie über die API lesbar | Wie im Hub |
| Schutz | Anmeldung, CSRF-Header bei schreibenden Anfragen, Änderungsprotokoll `audit` | Voraussetzungen des Postfachs laut Vorlage |
| Tests | Preis- und Fristenlogik, dazu ein nachgebauter IMAP-Server (FakeIMAP) fürs Postfach | Dort dürfen keine Fehler passieren |

Welches Web-Framework der Hub genau nutzt, steht nicht in der Vorlage. Claude Code liest das im Hub-Repository nach und übernimmt denselben Aufbau.

Der Weg einer Anfrage: Internet, dann Port 80/443, dann `proxy-caddy`, dann über das Docker-Netzwerk `proxy` zum Container des Studio-Tools.

Vor dem Bauen liest Claude Code diese Stellen im Hub (lokal unter `C:\Users\silas\Documents\GitHub\emden-tigers-hub`, nur lesen):

| Was | Wo im Hub |
| --- | --- |
| IMAP-Hilfen, Ordner, Erledigt | `server.py`: `postfach_config`, `postfach_open`, `postfach_folders`, `pf_done_folder`, `pf_move_to_done`, `pf_message`, `pf_text`, `html_to_text`, `pf_attachments`, `pf_unseen` |
| Schnittstelle | `server.py`: `api_postfach` |
| Neue Mails, Push | `server.py`: `pf_poll`, `pf_poll_loop`, `pf_inbox`, `pf_mark_handled`, `badge_for`, `send_push`, `webpush_encrypt` |
| Eigenes Postfach, Absender | `server.py`: `user_mail_cfg`, `pf_senders`, `own_mail_address` |
| Signatur | `server.py`: `signature_parts`, Paket `web/assets/signatur/` |
| Oberfläche | `static/pages.js`: `App.pages.postfach`, `pfShow`, `pfCompose`, `refreshMailBadge`; `static/style.css`: `.pf-*` |
| Service Worker | `static/sw.js` |

## Docker und Caddy

Das Studio-Tool kommt nach `/opt/docker/apps/app2` auf dem netcup-VPS (Debian 13) und hängt am vorhandenen zentralen Caddy. Der Proxy ist der einzige Container mit Port 80 und 443.

Regeln aus deiner Vorlage, die für das Tool gelten:

- Kein `ports:` im Compose, nur `expose:`. Erreichbar ausschließlich über Caddy.
- Netzwerk `proxy` als `external: true`. Eindeutiger `container_name`, nicht `emden-tigers-hub` und nicht `proxy-caddy`.
- Interner Port frei wählbar, aber nicht 8765 (Hub).
- Log-Begrenzung wie beim Hub.
- Zugangsdaten nur in `/opt/docker/apps/app2/.env` mit `chmod 600`, nie im Repository.
- Daten im eigenen Ordner `/opt/docker/apps/app2/data`, mit eigener Sicherung. Der Hub sichert nur seine eigenen Daten.
- Das Tool spricht intern nur HTTP. Cookies mit `Secure`, Proxy-Header nur von Caddy vertrauen.
- Öffentliche Adresse fest aus der `.env` (`DOMAIN`), nie aus dem Host-Header ableiten.
- Keine neuen Ports in der Firewall. `scp-server-satellite` und Docker Swarm nicht anfassen. Den Hub nicht anfassen.
- Arbeitsspeicher teilen sich Hub und Studio-Tool: vorher mit `free -h` prüfen.

`docker-compose.yml`:

```yaml
x-logging: &logging
  driver: json-file
  options:
    max-size: "10m"
    max-file: "5"

services:
  studio-tool:
    build: .
    container_name: studio-tool
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./data:/data
    expose:
      - "3000"
    networks: [proxy]
    logging: *logging

networks:
  proxy:
    external: true
```

Ergänzung im Caddyfile unter `/opt/docker/proxy` (und in der Vorlage `deploy/proxy/Caddyfile` im Hub-Repository nachziehen):

```
{$APP2_DOMAIN} {
	import sicherheit
	reverse_proxy studio-tool:3000
}
```

Ablauf beim ersten Deployment:

1. A-Eintrag der Domain auf die Server-IP setzen. MX- und TXT-Einträge (SPF, DKIM, DMARC) nie ändern, wenn unter der Domain schon E-Mail läuft.
2. Warten, bis `getent hosts <domain>` auf dem Server die IP zeigt.
3. `APP2_DOMAIN=...` in `/opt/docker/proxy/.env` eintragen.
4. Caddyfile prüfen: `docker compose exec caddy caddy validate --config /etc/caddy/Caddyfile`. Ein Fehler legt beide Seiten lahm.
5. Proxy neu erstellen mit `docker compose up -d`. Das unterbricht emden-tigers.de für ein paar Sekunden, also vorher einen ruhigen Zeitpunkt wählen.
6. Testen: `curl -I https://<domain>` liefert 200 oder 302, Caddy-Logs ohne Fehler, und der Hub antwortet noch unter `https://emden-tigers.de/healthz`.

Die Betriebsanleitung auf dem Server steht in `/opt/docker/DEPLOY.md`, Abschnitt "app2 hinzufügen". Skripte kommen per `scp` nach `/tmp` und werden dort mit `bash` ausgeführt.

## Sicherheit, Datenschutz, Backup

Das Tool enthält Namen, Kontaktdaten und Verträge und hängt am offenen Internet. Diese Punkte gehören deshalb in Version 1 und nicht in "später".

**Zugriff**

- Jede Seite und jede API-Route außer Login und Health verlangt eine gültige Session.
- Session-Cookie mit HttpOnly, Secure und SameSite=Lax.
- Login-Versuche begrenzen, zum Beispiel 5 Fehlversuche, dann 15 Minuten Sperre.
- Der ICS-Kalenderlink nutzt ein eigenes, langes Zufallstoken und zeigt nur Termin, Ort und Begegnung, keine Beträge oder Kontaktdaten.
- Datei-Downloads laufen über eine geschützte Route, nie über einen öffentlichen Ordner.
- Uploads nur als PDF, mit Größenlimit und zufälligem Dateinamen auf der Platte.

**E-Mail**

- SMTP- und IMAP-Passwörter nur in `secrets`, nie über die API ausgeben, nicht im Backup-Download, beim Serverumzug dabei.
- Mails nur als Text anzeigen, nie als HTML. Anhänge nur als Download mit `application/octet-stream`.
- IMAP-Hostname nur aus `[A-Za-z0-9.-]`, Ordnernamen immer gequotet, UIDs nur als Ziffern, Lesen mit `BODY.PEEK`.
- Höchstens 20 Empfänger je Mail, Adressen geprüft.
- Push nur zu bekannten Push-Diensten, Inhalt nur Betreff und Absendername. Der Service Worker speichert nichts.
- Für Gmail ein eigenes App-Passwort nur für dieses Tool anlegen, damit es sich einzeln widerrufen lässt.
- Zweiter Faktor beim Login (TOTP) ist Pflicht, weil das Tool Zugriff auf deine Postfächer hat. Notfall ohne Handy und ohne Codes: `python server.py 2fa-reset <name>` im Container.
- Push und Mail-Abruf in der Datenschutzerklärung erwähnen, falls das Tool eine bekommt. netcup als Hosting-Anbieter nennen.

**Datenschutz**

- Das Tool verarbeitet personenbezogene Daten deiner Kunden. Trage es in dein Verzeichnis der Verarbeitungstätigkeiten ein.
- Prüfe, ob mit dem Server-Anbieter ein Vertrag zur Auftragsverarbeitung besteht.
- Kontakte lassen sich auf Wunsch löschen oder anonymisieren, ohne dass Umsätze verloren gehen.
- Keine externen Tracker, Schriften oder CDNs einbinden.

**Backup**

- Jede Nacht ein konsistentes SQLite-Backup (`sqlite3 .backup`) plus der Upload-Ordner als ein Archiv.
- Ablage außerhalb des Servers, zum Beispiel per rclone verschlüsselt in deine pCloud.
- 14 Tagesstände und 6 Monatsstände behalten.
- Die Wiederherstellung einmal wirklich durchspielen und im README dokumentieren.

Rechtlicher Hinweis: Die Datenschutzpunkte sind eine Orientierung und keine Rechtsberatung.

## Bauphasen

Elf Phasen, jede endet mit etwas, das du im Browser prüfen kannst. Phase 1 bis 6 ergeben das Auftragstool, Phase 7 bis 9 die Erweiterung um App, Kalender, Aufgaben und E-Mail, Phase 10 die Steuer-Vorbereitung, Phase 11 das Fahrtenbuch. Gib Claude Code immer nur eine Phase und teste, bevor die nächste beginnt.

1. **Grundgerüst.** Projekt anlegen, Aufbau nach dem Hub, Datenbankschema mit allen Tabellen samt secrets und audit, Seed mit deinen Paketen, Login, Layout mit Navigation, Health-Route, Dockerfile und Compose. Fertig, wenn der Container lokal startet und der Login funktioniert.
2. **Kunden und Aufträge.** Kunden mit Kontakten, Auftrag anlegen und bearbeiten, Preisberechnung mit Anfahrt, Statuswechsel, Liste mit Filtern. Dazu die Tests für `die Preislogik`. Fertig, wenn ein HSG-Spiel und ein Spielershooting mit 28 Spielern und 25 km Anfahrt den richtigen Betrag zeigen (60 € + 3 × 0,90 € + 15 × 0,30 € = 67,20 €).
3. **Zahlungen.** Zahlstatus, Zahler, Finom-Häkchen mit Rechnungsnummer, Liste "Noch abzurechnen", Umsatzübersicht, CSV-Export. Fertig, wenn die Summen mit einer Handrechnung übereinstimmen.
4. **Bildauslieferung.** Lieferlinks, Fristenampel, Ablaufdaten, Nachrichtenvorlagen. Dazu die Tests für `die Fristenlogik`. Fertig, wenn ein Spiel vom 01.11. am 07.11. als überfällig erscheint.
5. **Verträge und Dokumente.** Verträge mit Fristen, PDF-Upload und geschützter Download. Fertig, wenn das Datum "spätestens kündigen bis" stimmt und die PDF ohne Login nicht abrufbar ist.
6. **Dashboard, Kalender, Betrieb.** Startseite mit allen Kennzahlen, Kalenderansicht, ICS-Abo, Serien-Anlage, Backup-Skript, README mit Deployment und Wiederherstellung. Danach Deployment auf dem V-Server hinter Caddy.

Erweiterung:

- **Phase 7: iPhone-App und Push.** Manifest, App-Symbole, Service Worker und Web Push aus dem Hub übernehmen, untere Navigationsleiste. Fertig, wenn die App vom Home-Bildschirm im Vollbild startet und eine Test-Mitteilung auf dem iPhone ankommt.
- **Phase 8: Kalender und Aufgaben.** Eigene Termine, Kalenderansichten, Wiederholungen, Überschneidungswarnung, Aufgaben mit Ansichten und Vorlagen je Paket, Erinnerungen über die Hintergrund-Schleife. Fertig, wenn ein neuer Pro-Auftrag automatisch seine Aufgabenliste bekommt und die Erinnerung als Push kommt.
- **Phase 9: Postfach.** Zuerst die genannten Stellen im Hub lesen. Dann ein Konto mit "Verbindung prüfen", Ordner und Lesen, danach Schreiben, Erledigt und Löschen, danach mehrere Konten, Hintergrund-Abruf mit Push und die Verknüpfung mit Kunden und Aufträgen. Die Fähigkeiten jedes Mailanbieters vorher prüfen (MOVE, UIDPLUS, SPECIAL-USE, Namespace). Fertig, wenn eine Antwort aus dem Tool im Gesendet-Ordner des echten Postfachs liegt und "Erledigt" die Mail dort verschiebt.

- **Phase 10: Ausgaben und Steuer-Vorbereitung.** Ausgaben mit Beleg-Upload (auch Foto vom iPhone), Kategorien, Anlagegüter markieren, Übersicht im Aufbau einer EÜR, Fahrtenliste, Monatssperre, Export als CSV und Belege als ZIP. Dazu Tests für Summen und Export. Fertig, wenn die Jahresübersicht mit einer Handrechnung übereinstimmt und der Export vollständig in Finom oder bei der Steuerberatung ankommt.

- **Phase 11: Fahrtenbuch.** Fahrzeuge, Fahrten mit Kilometerständen und Prüfung der Lücken, Änderungsprotokoll und Monatssperre, Vorschläge aus Aufträgen, Import aus Driversnote, GPS-Aufzeichnung mit Lückenanzeige, Karte, Jahresauswertung mit PDF- und CSV-Export. Dazu Tests für Kilometerfolge, Streckenberechnung und Import. Fertig, wenn der Driversnote-Export vollständig übernommen ist, eine echte Fahrt per GPS höchstens wenige Prozent vom Tacho abweicht und die Strecke auf der Karte erscheint.

Das Postfach ist durch die Vorlage aus dem Hub deutlich weniger Arbeit als ein Neubau. Es bleibt trotzdem am Ende, weil es Anmeldung, secrets, audit und Push voraussetzt.

Ob zuerst auf der Test-VM oder direkt auf dem VPS ausprobiert wird, ist eine deiner offenen Fragen. Weil auf dem VPS der Hub mit echten Vereinsdaten läuft, spricht viel für die Test-VM.

Nach Phase 2 lohnt sich schon ein erstes Deployment auf dem Server. So fällt früh auf, ob Netzwerk, Domain und Volume passen.

## Startprompt für Claude Code und offene Punkte

Ins neue Repository kommen zwei Dateien: deine Vorlage als `CLAUDE.md` (mit ausgefüllten OFFEN-Stellen) und dieses Dokument als `PLANUNG.md`.

Vorschlag für die OFFEN-Stellen im Kopf der `CLAUDE.md`:

| Stelle | Eintrag |
| --- | --- |
| Name | Studio-Tool (Arbeitstitel) |
| Zweck | Internes Verwaltungstool für silasgrbwsk.fotografie: Aufträge, Zahlungen, Bildauslieferung, Verträge, Postfach, Kalender, Aufgaben. Einziger Nutzer: Silas. |
| Domain | `hub.silasgrbwskfotografie.de` |
| Technik | Python und SQLite im Aufbau des Hubs, eigener Code |
| Repository | Empfehlung: privat |
| Suchmaschinen | `noindex`, weil rein intern |

Startprompt für Claude Code:

```
Lies CLAUDE.md und PLANUNG.md vollständig, bevor du etwas anlegst.
CLAUDE.md regelt Server, Arbeitsweise und Postfach. PLANUNG.md regelt
Funktionsumfang, Datenmodell und Bauphasen. Bei Widerspruch gilt
CLAUDE.md, und du fragst nach.

Lies außerdem den Emden Tigers Hub unter
C:\Users\silas\Documents\GitHub\emden-tigers-hub (nur lesen, nichts
ändern). Übernimm von dort Aufbau, Anmeldung, secrets, audit, CSRF,
Push und später das Postfach. Sag mir zuerst kurz, welchen Aufbau du
dort gefunden hast und was du übernehmen willst.

Regeln:
- Arbeite phasenweise. Setze nur Phase 1 um und stoppe danach.
- Oberfläche auf Deutsch, mobil zuerst, Texte ohne Gedankenstriche.
- Geldbeträge in Cent, Zeitzone Europe/Berlin.
- Preis- und Fristenlogik bekommt Tests.
- Commit nur nach Rückfrage. Nichts am Hub oder am Proxy ohne Absprache.
- Am Ende jeder Phase: was fertig ist, wie ich es teste, was offen bleibt.
```

Für jede weitere Phase reicht: "Phase 1 ist getestet. Setze jetzt Phase 2 aus PLANUNG.md um und stoppe danach."

Offene Punkte, die du vor dem Start klären solltest:

- [x] Domain: `hub.silasgrbwskfotografie.de` (Subdomain, ohne `www`)
- [x] DNS bei netcup, E-Mail läuft dort schon (MX und TXT bleiben unverändert). A-Eintrag `hub` auf `62.83.124.184` ist gesetzt.
- [ ] Repository öffentlich oder privat?
- [ ] Erst auf der Test-VM ausprobieren oder direkt auf den VPS?
- [ ] Reicht der Arbeitsspeicher des VPS für Hub und Studio-Tool (`free -h`)?
- [ ] Welche Postfächer sollen rein, bei welchen Mailanbietern? Deren Fähigkeiten prüfen (im Hub ist es Strato).
- [ ] Gmail: Sind App-Passwörter in deinem Google-Konto verfügbar? Gmail arbeitet mit Labels statt Ordnern, "Erledigt" dort eigens testen.
- [ ] Stimmt es, dass Zuweisen, Rechte, Gruppen und Kontaktformular aus dem Hub entfallen, weil nur du das Tool nutzt?
- [ ] Eigene Signatur für die Fotografie (Logo, Farben)?
- [x] Zweiter Faktor beim Login: ja, als Pflicht (TOTP mit Authenticator-App, 10 Wiederherstellungscodes). Eingebaut in Phase 1.
- [ ] Stimmen die Pakete und Preise noch, und fehlen welche (zum Beispiel Livestream oder Portraitshooting)?
- [ ] Welche Umsatzgrenze soll das Dashboard anzeigen? Den aktuellen Wert für Kleinunternehmer bitte mit Steuerberatung oder Finanzamt abgleichen.
- [ ] Wie wird gesichert (Datenbank, Uploads), wohin, und wer aktualisiert?
- [ ] Soll der Kalender nur exportieren (ICS-Abo) oder auch einen bestehenden Kalender einlesen?
- [ ] Welche Standard-Aufgaben gehören zu welchem Paket?
- [ ] Phase 10: Kategorien, Exportformat und Kleinunternehmerregelung mit der Steuerberatung klären.
- [ ] Phase 11: Beispiel-Export aus Driversnote (CSV oder Excel) bereitstellen.
- [ ] Phase 11: Kartenbilder von OpenStreetMap laden (dann sieht der Kartendienst die angezeigten Gegenden) oder Karte ohne Hintergrund, nur die Strecke?
- [ ] Phase 11: Reicht GPS nur bei eingeschaltetem Bildschirm (Handy in der Halterung), oder wird eine eigene iPhone-App gebraucht?
- [ ] Phase 11: Firmenwagen oder privates Auto mit betrieblicher Nutzung? Wofür das Fahrtenbuch steuerlich gebraucht wird, mit der Steuerberatung klären.
