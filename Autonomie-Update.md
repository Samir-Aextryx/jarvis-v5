# Jarvis v5: mehrstufige Aufgaben, 17. September 2026

## Änderungen

- `local_pc.py`: Nach einer Mail- oder Kalender-Aktion wird der gesamte Auftrag anhand der Ergebnisse erneut bewertet. Keine automatische Fertigmeldung nach dem ersten Entwurf. Explizite Versandaufträge werden von Entwürfen und reinen Zusammenfassungen unterschieden. Der Planer erhält zusätzlich das aus dem Nutzerauftrag berechnete Versandmerkmal; die tatsächliche Ausführung prüft Empfänger und Auftrag weiterhin unabhängig. Ein formal widersprüchlicher Plan wird einmal korrigiert, bevor eine weitere Aktion läuft.
- `autonomous_tasks.py`: Ein fehlgeschlagener Datei-, Ordner- oder Mail-Lesezugriff kann vom Planer einmal erneut angefordert werden. Nur eine erfolgreiche Wiederholung derselben Aktion löst ihren vorherigen Fehler auf. Der ursprüngliche Fehler bleibt im Verlauf sichtbar. Erfolgreiche Aktionen und unklare Schreib-/Sendeaktionen werden nicht wiederholt. Die Fortschrittsanzeige zählt gelöste Fehlversuche nicht als offene Aufgaben.
- `email_planner.py`: Bei „lesen und danach schreiben“ verhindert ein noch fehlender Empfänger nicht mehr den vorausgehenden Lesezugriff.
- `google_access.py`: Neue Gmail-Entwürfe können per API gespeichert werden; Erfolg setzt eine Entwurfs- und Nachrichten-ID voraus. Keine Wiederholung bei unklarer Antwort. Eigene Einstellung `gmail_drafts`, OAuth-Recht `gmail.compose`. Der generische Lesepfad lehnt Schreibberechtigungen ab.
- `frontend/src/settings.ts`, `server.py`: Neue Auswahl „Gmail drafts“, aktualisierte Hilfe und Beschreibung der Fähigkeiten.
- `tests/test_autonomy_mail.py`: Integrationstest von Mail-Lesen über Entwurfsspeicherung bis App-Start sowie Fehler-, Berechtigungs-, Wiederholungs- und Planreparaturtests.
- `Jarvis-v5-Hilfe.md`: Bedienung, Beispiele, Voraussetzungen und Grenzen aktualisiert; veraltete Aussagen „kein Mail-Versand“ berichtigt.

## Prüfung

109 automatisierte Tests bestanden: 76 für Aufgaben, E-Mails, Google, PC-Steuerung und Kalender; 33 für Desktop-Steuerung, gelernte App-Namen, Gedächtnis und Sprachverarbeitung. Konto- und App-Antworten in diesen Tests sind simuliert. Keine echte Mail versandt oder als Testentwurf im Benutzerkonto gespeichert.

Zusätzlich echte OpenAI-Planung mit ausschließlich erfundenen Nachrichten getestet: Entwurf mit anschließendem App-Start; englischer und deutscher Versand einer Zusammenfassung; ausdrücklich nicht gesendeter Entwurf; restlicher App-Start nach einem bereits bestätigten Versand; Zusammenfassung ohne ausgehende Mail. Dabei wurden keine geplanten Aktionen ausgeführt. Die ersten Durchläufe deckten eine unnötige Entwurfsplanung statt Versand und eine widersprüchliche Fertigmeldung mit offenen Schritten auf. Beispiele im Planer und eine begrenzte Formatkorrektur behoben diese beobachteten Fälle. Das ist eine Stichprobe, keine Garantie für jeden möglichen Auftrag.

TypeScript-Prüfung und Produktions-Build bestanden. Vite meldet weiterhin die bekannte große JavaScript-Datei (>500 kB); die App baut erfolgreich. Es wurden keine neuen Messungen der Sprachlatenz durchgeführt.

## Voraussetzungen und Grenzen

Settings > Google: Gmail reading, Gmail drafts und bei gewünschtem Versand Gmail sending auswählen und Connect Google erneut ausführen. Die Google-Anmeldung muss der Nutzer selbst abschließen. `gmail.compose` umfasst bei Google mehr als reines Lesen; Jarvis verlangt für API-Versand weiterhin die separate Sendeeinstellung und einen ausdrücklichen Auftrag. Die Implementierung folgt der offiziellen [Gmail-Drafts-API](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.drafts/create).

Gmail-API-Bestätigung belegt die Annahme, nicht die Zustellung. Explizite Chrome-Aufträge verwenden weiterhin die sichtbare Browser-Oberfläche; Outlook und allgemeine Apps benötigen zugängliche Windows-Bedienelemente. Keine allgemeine Unterstützung für Anhänge, Antworten in bestehenden Mail-Threads oder jede beliebige Windows-App. Aufgaben bleiben auf 12 Aktionsversuche, 8 Planungsrunden und fünf Minuten begrenzt; keine dauerhafte Postfachüberwachung. Stop/Escape und Rückfragen im selben Auftrag bleiben erhalten.

Die bestehende Sicherung `Documents/jarvis v5 backup` bleibt unverändert. Zusätzlich liegen die Ausgangsquelldateien unter `backup-updates/autonomy-source-20260917-091028`; das Installationsupdate sichert den vorherigen Backend-Stand separat.

## Installationsprüfung

Die App unter `C:/Users/Samir/Documents/Jarvis v5` wurde aktualisiert und gestartet. `/api/health` liefert HTTP 200; die ausgelieferte Oberfläche enthält „Gmail drafts“. Der SHA-256-Abgleich des installierten Backends mit dem neuen Paket stimmt überein. Die unmittelbar vorherige Backend-Version liegt unter `backup-updates/20260917-093011`; die ältere vollständige Sicherung ist weiterhin vorhanden.

Kontostatus nach dem Update: OAuth eingerichtet, Google derzeit **nicht verbunden**, bisher ausgewählt: calendar, drive, gmail. Der Nutzer muss die gewünschten Gmail-Funktionen auswählen und die Google-Anmeldung abschließen. Eine echte Kontoaktion wurde deshalb nicht als erfolgreich getestet dargestellt.
