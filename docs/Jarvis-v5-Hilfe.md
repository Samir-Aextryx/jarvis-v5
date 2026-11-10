# Jarvis v5

## WhatsApp Beta und dringende E-Mails

Unter Settings → AI Settings kann die eigene WhatsApp-Kontaktnummer für „Boss“
im Windows-Anmeldeinformationsspeicher hinterlegt werden. Die Nummer wird nicht
im Quellcode, in der `.env` oder im Gedächtnis abgelegt. Der Sprachbefehl
„Call Boss on WhatsApp Beta“ beziehungsweise „Ruf mich an“ öffnet gezielt
WhatsApp Beta und sagt ausdrücklich, wenn kein Anruf aufgebaut wurde.
Bei diesem Sprachbefehl prüft Jarvis den ausgewählten Boss-Chat anhand der
exakten im WhatsApp-Kontaktfenster angezeigten Nummer. Dabei wird die Nummer
kurz lokal kopiert und die bisherige Zwischenablage anschließend wiederhergestellt.
Schlägt der Abgleich fehl, wird kein Anruf vorbereitet oder gewählt. Auch ein
erfolgreicher Abgleich löst derzeit noch keinen Anruf aus.

Während das Backend läuft, prüft Jarvis alle 30 Sekunden nur die Kopfzeilen
ungelesener Outlook-Nachrichten. Verbundenes Gmail wird alle 90 Sekunden
geprüft. Falls Outlook vorübergehend nicht erreichbar ist, zeigt Jarvis einen
deutlichen Hinweis und versucht die Verbindung mit Abstand erneut. Für die
Überwachung öffnet Jarvis bei Bedarf das klassische Outlook als sichtbare App;
eine unsichtbare COM-Instanz wird nicht gestartet. Der erste Scan
setzt den Ausgangsstand. Danach erscheint für neu eingetroffene Nachrichten
mit hoher Priorität oder eindeutig dringendem Betreff ein Hinweis in Jarvis.
Nachrichteninhalte lösen niemals Befehle aus. Der Hinweis ersetzt keinen
zuverlässigen Notfalldienst.
Der Erkennungsstand und die Hinweise werden für den aktuellen Windows-Benutzer
verschlüsselt gespeichert, damit nach einem Backend-Neustart keine alten Mails
erneut gemeldet werden und neue Mails seit dem letzten Lauf erkennbar bleiben.
Neue dringende Hinweise erhalten zusätzlich einen verschlüsselten Anrufauftrag.
Solange der Anruf technisch nicht möglich ist, bleibt er als „blocked“ sichtbar
und wird höchstens alle fünf Minuten erneut auf Bereitschaft geprüft. Nach
30 Minuten verfällt er. Ein Anruf mit unbekanntem Ergebnis wird aus Schutz vor
doppelten Anrufen nicht automatisch wiederholt. Ein erfolgreicher Anruf wird
erst gespeichert, wenn Verbindung und gesprochene Nachricht bestätigt sind.

Ein automatischer WhatsApp-Anruf mit Gespräch ist derzeit **nicht verfügbar**:
Auf diesem PC fehlt ein virtuelles Mikrofon. Die vorbereitete WASAPI-Brücke
kann Fish-Audio-PCM in einen virtuellen Kabel-Eingang ausgeben, dessen
Aufnahmeseite WhatsApp als Mikrofon wählen müsste. Sie kann den eingehenden
Anrufton über den Lautsprecher-Loopback für Spracherkennung erfassen und die
Kabelverbindung mit einem lokalen Ton testen. Die Erkennung des tatsächlich
verbundenen WhatsApp-Anrufs und die Wahl des verifizierten Kontakts sind noch
nicht zuverlässig automatisiert. Ein Anruf ohne diese Prüfungen würde entweder
die falsche Person erreichen oder Jarvis' Stimme nicht übertragen. Der
Verbindungsstatus steht in den Einstellungen.

Die App über die Desktop-Verknüpfung **Jarvis v5** starten. Jarvis läuft direkt
aus dem Quellcode: Die Verknüpfung startet Electron mit dem Ordner `desktop/`, der
Python-Server startet automatisch im Hintergrund. Eine eigene EXE gibt es nicht,
daher funktioniert der Start auch mit aktivem Smart App Control. Eingerichtet wird
alles einmalig mit `scripts\install.ps1` (siehe README).

API-Schlüssel und Einstellungen über das Menü oben rechts → Settings eintragen.
Die lokale Konfiguration liegt in `Documents\Jarvis v5\config\.env`.

Oben rechts schaltet der Button „Mikro an“ / „Mikro aus“ das Zuhören um.
Grün bedeutet eingeschaltet, Rot bedeutet stummgeschaltet. Beim Stummschalten
endet die Aufnahme; die Auswahl bleibt auch nach einem Neustart erhalten.
Jarvis spricht ausschließlich Englisch, auch bei deutschen Befehlen und lokalen
Aktionsmeldungen. Die Desktop-App erkennt
Sprechpausen und sendet die Aufnahme zur OpenAI-Spracherkennung. Antworten werden
von OpenAI erzeugt und mit der Fish-Audio-JARVIS-Stimme gesprochen.
Für Gespräche ist eine Internetverbindung erforderlich.

## Schnellere Sprachausgabe

Die Desktop-App spielt die Fish-Stimme jetzt als fortlaufenden Audiostream ab.
Bereits unter der englischen Systemanweisung erzeugte Antworten brauchen keine
zweite Übersetzungsanfrage. Häufige Antworten werden nur im Arbeitsspeicher
zwischengespeichert (höchstens 8 MB), getrennt nach Stimme, Modell und API-Schlüssel.
API-Verbindungen werden wiederverwendet. Stille Aufnahmeabschnitte werden verworfen;
das Ende eines Sprachbefehls wird nach ungefähr 160 ms Pause erkannt, zuzüglich der
in den Einstellungen gewählten Zusatzpause.
Während einer Antwort bleibt das eingeschaltete Mikrofon für Unterbrechungen aktiv.
Der Stumm-Button beendet die Aufnahme und gibt das Gerät vollständig frei.
Die Projektliste wird im Hintergrund geladen; die Animation pausiert in ausgeblendeten
Fenstern. Internet- und Anbieterantwortzeiten bestimmen weiterhin einen Teil der Wartezeit.

## Google verbinden

Ein Google-API-Key kann unter Settings → Google → **Google API key** gespeichert,
geprüft und entfernt werden. Er liegt geschützt in der Windows-Anmeldeinformationsverwaltung.
Der Test prüft konkret YouTube Data API v3; diese API muss im Google-Projekt aktiviert
und für den Key erlaubt sein. „Show popular YouTube videos“ liest damit öffentliche
Videotitel. Ein erfolgreicher Test gewährt keinen Zugriff auf private Kontodaten.

Websites öffnen: „Öffne youtube.com“, „Open github.com“ oder „Öffne example punkt com“.
Die Adresse wird direkt im Standardbrowser geöffnet, ohne eine KI-Antwort abzuwarten.

Oben rechts: Menü → Settings → Google.

1. In Google Cloud ein Projekt wählen und die gewünschten APIs aktivieren:
   Gmail API, Google Calendar API, Google Drive API, optional Tasks API und People API.
2. Unter Google Auth Platform die Einwilligungsseite einrichten. Bei einer App im
   Testmodus dein eigenes Google-Konto als Testnutzer eintragen.
3. Einen OAuth-Client vom Typ **Desktop-App** erstellen und dessen JSON herunterladen.
4. In Jarvis die gewünschten Dienste auswählen und die JSON-Datei importieren.
5. **Connect Google** anklicken, bei Google anmelden und die angezeigten Zugriffe
   freigeben. Danach **Refresh status** anklicken.

Ein gewöhnlicher Google-API-Key genügt nicht für private Gmail-Nachrichten und
Kalender. OAuth-Client und Zugriffstoken liegen in der Windows-Anmeldeinformationsverwaltung.
Google-Anleitung: https://developers.google.com/identity/protocols/oauth2/native-app

Sprachbefehle nach der Anmeldung:
- „Read my Gmail“ / „Lies meine Gmail Nachrichten“: bis zu fünf ungelesene Nachrichten,
  mit Absender, Betreff und Vorschautext.
- „Show my Google Calendar“: die nächsten zehn Termine im Hauptkalender.
- „Show my Google Drive“: die zwanzig zuletzt geänderten Dateien.
- „Show my Google Tasks“: bis zu zwanzig offene Aufgaben der Standardliste.
- „Show my Google Contacts“: bis zu zwanzig Kontakte.

Gmail kann zusätzlich Entwürfe speichern und auf ausdrücklichen Auftrag senden;
Google-Kalender kann einzelne persönliche Termine erstellen und ändern. Dafür
die entsprechenden Dienste auswählen und erneut verbinden. Löschen ist nicht
eingebaut. Docs, Sheets und Slides erscheinen als Dateien in Drive.
„Open Gmail“, „Open Google Keep“, „Open Google Docs“, „Open Google Maps“ usw.
öffnen die jeweiligen Webseiten. Es gibt keinen pauschalen Datenzugriff auf alle
Google-Produkte; weitere APIs benötigen eigene Anbindungen und Freigaben.
„Disconnect“ entfernt die lokale Kontoverbindung und versucht, die Google-Freigabe
zu widerrufen. Der OAuth-Client bleibt für eine spätere Anmeldung gespeichert.

Schlüssel verwalten: https://platform.openai.com/api-keys und
https://fish.audio/app/api-keys/.
Stimme: https://fish.audio/m/612b878b113047d9a770c069c8b4fdfe/
Voice ID: `612b878b113047d9a770c069c8b4fdfe`.

Lokale Aufgaben, Erinnerungen, Browser, Fensterliste und Screenshots sind verfügbar.
Installierte Apps kannst du direkt öffnen: „Öffne Outlook“, „Starte WhatsApp“,
„Öffne Snapchat“, „Öffne Chrome“ oder „Öffne Proton VPN“. Auch andere Apps aus
dem Windows-Startmenü werden erkannt. Bei „Öffne VPN“ kannst du mit „Proton“,
„Mullvad“ oder „FortiClient“ auswählen. Es wird nur die VPN-App geöffnet.
App-Namen werden beim Start vorgeladen; der Startbefehl wartet nicht auf eine
KI-Antwort. Die Spracherkennung benötigt weiterhin eine Internetverbindung.

Persönliches Gedächtnis: `config/MEMORY.md`. Jarvis merkt sich genannte Infos,
Vorlieben, Ziele, Routinen und deine Fragen dauerhaft über Neustarts hinweg.
Die Datei kannst du über Settings oder „Öffne dein Gedächtnis“ ansehen.
Sie wird automatisch aus der lokalen Datenbank erstellt; manuelle Änderungen
an der Datei werden beim nächsten Gespräch überschrieben. Korrekturen teilst du
Jarvis im Gespräch mit. Fragen sind keine Fakten über dich, und App-Muster werden
erst nach mindestens drei verschiedenen Tagen als unbestätigte Beobachtung notiert.
Die letzten 20 Gesprächsbeiträge und die 20 häufigsten Fragen stehen in der MD-Datei;
die lokale Datenbank behält auch ältere Beiträge.
Jarvis nutzt sein eigenes lokales Gedächtnis, Notizbuch und seinen Kalender. Outlook und Google sind separate, optionale Verbindungen.
PC-Befehle (mit den Zugriffsrechten deines Windows-Benutzers):
- „Zeige Laufwerke“
- „Öffne Ordner C:\\Users\\Name“ oder „Öffne Downloads“
- „Zeige Dateien in Desktop“
- „Suche Datei rechnung.pdf“ (Suche begrenzt auf 8 Sekunden / 20 Treffer)
- „Lies Datei C:\\Pfad\\notiz.txt“ (maximal 4000 Zeichen)
- „Lies die Dateien \"C:\\Pfad\\eins.txt\" und \"C:\\Pfad\\zwei.md\"“ liest beide Text-/Quellcodedateien parallel; jede Datei bleibt auf maximal 4000 Zeichen begrenzt.
Dokumente werden gezielt gelesen; ausführbare Dateien startet dieser Dateibefehl nicht.
Windows-Zugriffsschutz und Administratorabfragen bleiben wirksam.

Windows Defender:
- „Starte Schnellscan“ oder „Scanne meinen ganzen PC“ (Vollscan)
- „Scanstatus“ / „Sicherheitsstatus“
- „Entferne erkannte Viren“ nennt die aktuellen aktiven Defender-Funde.
- „Defender Bereinigung bestätigen“ bestätigt diese Funde innerhalb von 90 Sekunden.
Defender führt die Bereinigung aus. Jarvis löscht keine Dateien auf KI-Verdacht.
Defender kann während eines Scans entsprechend deinen Windows-Einstellungen
Bedrohungen automatisch behandeln. Null aktive Funde sind keine Garantie für Virenfreiheit.
Falls Windows einen Befehl verweigert, meldet Jarvis den Fehler; es wird kein Schutz umgangen.

Codex: „Programmiere mir eine Taschenrechner-App“ oder „Erstelle eine Website …“.
Jarvis startet Codex über die installierte CLI mit deiner vorhandenen ChatGPT-Anmeldung.
Neue Aufträge arbeiten unter `Desktop/Jarvis Projekte/Auftrag-…` mit Schreibzugriff
auf ihren Projektordner. Sobald eine Aufgaben-ID vorliegt, öffnet Jarvis die Aufgabe
über den offiziellen Codex-Link. Der Auftrag wird automatisch per CLI übermittelt.
„Codex Status“ meldet laufende Aufträge, Abschluss oder Fehler. Ergebnisse liegen
im Projektordner. Jobprotokolle stehen in `config/data/pc-jobs`.
Ein laufender Auftrag darf fertigarbeiten; Jarvis währenddessen nicht beenden.
Auch die Windows-Projektübergabe verwendet Codex. Jeder übergebene Auftrag erhält
eine eigene Aufgabe; Folgeaufträge in Jarvis übernehmen den Projektordner, aber
nicht automatisch den Gesprächsverlauf früherer Codex-Aufgaben.

Bei Startproblemen: `config/server.log`. Der lokale App-Server verwendet Port 8345.

Geprüft: Start der gebündelten Windows-App, Konfiguration beider Schlüssel,
OpenAI-Antworten, Fish-Sprachausgabe und Transkription einer Test-Audiodatei.
Die Aufnahme über dein physisches Mikrofon kannst du direkt in der App testen.

Dashboard: Sage Open dashboard oder Öffne das Dashboard. Jarvis öffnet seine Einstellungen und Systemübersicht in Chrome. Das Mikrofon des zusätzlichen Browserfensters startet stumm. Die Desktop-App bleibt separat bedienbar.

## Lokale PC-Aufträge und Unterbrechen

- OpenAI plant komplexe PC-Aufträge und autonome Aufgaben über den eingerichteten API-Schlüssel. Dabei entstehen API-Nutzungskosten. Normale Unterhaltung, Spracherkennung und Fish Audio bleiben bei ihren bisherigen Diensten.
- Beispiele: "Open ChatGPT and prompt it to improve Jarvis v5", "Open Chrome and open Notepad", "Save a file called test.txt to Desktop with the content Hello Samir".
- Ohne Dateiname oder Inhalt fragt Jarvis nach. Neue Desktop-Dateien werden exklusiv angelegt und geprüft. Vorhandene Dateien werden nicht überschrieben. Unterstützte Schreibformate: txt, md, csv, json.
- ChatGPT wird in Chrome geöffnet. Jarvis versucht das eindeutig erkannte Nachrichtenfeld zu füllen und Senden zu betätigen. Anmeldung, vorhandene Entwürfe oder nicht zugängliche Steuerelemente können das verhindern. In diesem Fall wird kein Versand behauptet; der Prompt wird gegebenenfalls als Textdatei auf dem Desktop gesichert. ChatGPT im Browser bekommt dadurch keinen automatischen Dateizugriff.
- Für Programmieraufträge mit direktem Projektzugriff kann ausdrücklich Codex angesprochen werden. Der Projektpfad muss angegeben werden; ohne Projekt erstellt die bisherige Codex-Funktion einen neuen Projektordner. ChatGPT und Codex bleiben getrennte Ziele.
- Sprich während einer Antwort, um die Sprachausgabe zu unterbrechen. "Stop" beendet die Antwort und lässt das Mikrofon aktiv. Bereits abgeschlossene Dateiaktionen werden dadurch nicht rückgängig gemacht; separat gestartete Codex-/Defender-Aufträge laufen weiter.
- Settings > User Preferences > Pause before replying: 0, 100, 200, 300, 500, 1000, 2000, 3500 oder 5000 ms. Standard sind 0 ms; zusätzlich prüft Jarvis 160 ms Stille. Die Desktop-Aufnahme erlaubt bis zu 120 Sekunden pro Abschnitt. Echo-Unterdrückung ist aktiv; bei Rückkopplungen sind Kopfhörer hilfreich.
- Settings zeigt, ob ein OpenAI-API-Schlüssel hinterlegt ist. Dies ist kein Verbindungstest.
- Es handelt sich um gezielte PC-Funktionen, nicht um uneingeschränkte Kontrolle jeder beliebigen App oder das Ausführen beliebiger Shell-Befehle.

Nachrichten: Open Snapchat and write a message to Branko fragt zuerst nach dem Nachrichtentext. Mit Text wird ein separater lokaler Entwurf geöffnet sowie Snapchat Web in Chrome. Dieser Entwurf wird nicht automatisch in Snapchat eingefügt oder gesendet. Auch WhatsApp-Entwürfe sind getrennt vom tatsächlichen Versand.

Zuverlässigkeit: Eindeutige ChatGPT-Prompts und vollständig angegebene Desktop-Textdateien werden direkt verarbeitet, ohne lokale Modellwartezeit. Für komplexe Aufträge nutzt Jarvis die OpenAI-API. Neue PC-Aufträge ersetzen alte offene Rückfragen. Bei unklarem ChatGPT-Sendeergebnis wird nicht automatisch erneut gesendet. Kurze Spracheingaben unterbrechen die Ausgabe; Escape dient zusätzlich als Stopp-Taste.

## Autonome Aufgaben

Sage "Autonomous task: ..." oder "Deine Aufgabe ist ...". Beispiel: "Autonomous task: Save a file called plan.txt to Desktop with the content Work on Jarvis today."
Jarvis plant unterstützte Schritte über OpenAI, führt sie nacheinander aus und nutzt die Ergebnisse für die weitere Planung. Bis zu zwölf Aktionen und acht Planungsrunden sind möglich; eindeutige Befehle werden direkt verarbeitet. Aufgaben laufen getrennt von der Sprachausgabe, maximal fünf Minuten. "Task status" meldet den Stand. "Stop" oder Escape bricht ab; bereits erledigte Aktionen werden nicht rückgängig gemacht.
Settings > Autonomous PC assistant > Refresh task history zeigt den Verlauf. Fehlende Angaben führen zu einer Rückfrage. Lesezugriffe können einmal wiederholt werden; Schreib- und Sendeaktionen werden nicht automatisch wiederholt. Bei autonomen Codex-Aufträgen wartet Jarvis auf den Abschlussbericht und wertet ihn vor weiteren Schritten aus.
Unterstützt werden die bereits vorhandenen lokalen PC-Funktionen; eine beliebige Aufgabe außerhalb dieser Werkzeuge kann Jarvis nicht selbstständig lösen. Es gibt keine ungefragte Hintergrundüberwachung oder automatischen Snapchat-Nachrichtenversand.
Der fehlerhafte Windows-App-Namen-Hinweis wurde aus der Spracherkennung entfernt; die bekannte Fehltranskription wird zusätzlich verworfen.


## Adaptive autonome Aufgaben

Sage „Your task is: …“ oder „Autonomous task: …“. Jarvis führt unterstützte Aktionen aus, wertet echte Ergebnisse aus und plant anschließend weiter. Nach Lesezugriffen nutzt er das Ergebnis für den nächsten Schritt. Fehler bei Lese- oder Startaktionen fließen in die weitere Planung ein. Unklare Schreib- und Sendeaktionen werden nicht wiederholt.

Fortschritt und Rückfragen erscheinen direkt im Status der App. Eine Antwort auf eine Rückfrage setzt denselben Auftrag mit seinen bisherigen Ergebnissen fort. „Task status“ nennt den Stand; „Stop“ bricht ab. Höchstens 12 Aktionen, 8 Planungsrunden und fünf Minuten pro Ausführung. Die OpenAI-Planung kostet API-Nutzung. Ein beendeter Codex-Lauf allein beweist keine bestandenen Tests; Jarvis wertet den Bericht aus. Unterstützte Werkzeuge begrenzen die Autonomie; beliebige Bedienung jeder App ist damit nicht zugesichert.


## App-Steuerung (9. September 2026)

Jarvis verwendet jetzt eine gemeinsame Windows-Steuerung für zugängliche App-Oberflächen. Beispiele: „Use Word to open the Layout tab“ oder „Open ChatGPT and prompt it to explain this idea“. Die Steuerung erkennt Bedienelemente, führt jeweils einen Schritt aus und liest danach den neuen Zustand. Ein eindeutiges Fenster und eine bereits angemeldete Sitzung sind erforderlich. Nicht jede App stellt ihre Oberfläche auf diese Weise bereit; bei unklaren Elementen stoppt Jarvis mit einer Erklärung.

Nachrichten werden nicht mehr nur in einer separaten Textdatei vorbereitet. Jarvis versucht den genauen Kontakt in der App zu öffnen und den wörtlichen Text im Nachrichtenfeld einzugeben. Ohne eindeutige Gesprächsüberschrift oder bei vorhandenem Entwurf stoppt er. „Write“ erstellt einen Entwurf; nur ein ausdrückliches „send/sende“ erlaubt das Absenden. Eingabe, Absenden und tatsächliche Zustellung werden getrennt behandelt. Bestehende Entwürfe, Passwörter, Sicherheitsdialoge, Löschaktionen und Käufe werden nicht automatisch verändert.

ChatGPT-Prompts nutzen dieselbe Steuerung und werden nur als abgesendet gemeldet, wenn der genaue Text eingegeben und das anschließend leere Eingabefeld beobachtet wurde. Das bestätigt keine fertige ChatGPT-Antwort.


## God's Eye View / Schweiz

„Open Switzerland“ oder „Öffne die Schweiz“ startet die lokale Karte im eigenen Jarvis-Kartenfenster mit Schweiz-Ansicht sowie zivilen und militärischen Flugzeugdaten. „Open God's Eye View“ öffnet die allgemeine Karte. Falls nötig, startet Jarvis den installierten Kartenserver automatisch. Die Anzeige hängt von der Abdeckung und Verfügbarkeit der öffentlichen Datenquellen ab.

Die Karte nutzt standardmäßig 30 FPS, reduzierte Renderauflösung und einfache Kantenglättung; die Schweiz-Ansicht zeigt Flugzeugsymbole statt aufwendiger 3D-Modelle. Für volle Qualität kann ?performance=quality in der Karten-URL verwendet werden. Jarvis selbst rendert seine Animation mit maximal 30 FPS im Leerlauf bzw. 60 FPS bei Aktivität und reduziert die Pixeldichte. Spracheingabe und -ausgabe werden davon nicht gedrosselt.


## Sprach- und Kartenupdate (15. September 2026)

Das Mikrofon zeichnet auch während der Transkription weiter auf. Zusammenhängende Abschnitte werden in Reihenfolge zusammengeführt; neue Sprache verhindert die vorzeitige Ausgabe einer vorherigen Transkription. Maximal zwei Erkennungsanfragen sind gleichzeitig aktiv. Bei langsamer Verbindung erscheint eine Fehlermeldung statt einer unbegrenzten Warteschlange. Stummschalten verwirft offene Aufnahmen und Ergebnisse. Mono-Opus mit 32 kbit/s reduziert die Uploadmenge. Die einstellbare Sprechpause bleibt erhalten.

Fish-Audio-Daten werden direkt beim Eintreffen weitergegeben. Die tatsächliche Antwortzeit hängt weiterhin von Netzwerk und API ab. Es wurde keine feste End-to-End-Latenz garantiert.

Autonome Aufgaben können auch mit „Take care of …“, „Handle this task …“ oder „Kümmere dich um …“ beginnen. Die bestehenden Grenzen und Ergebnisprüfungen gelten weiter.

„Open USA“ und „Open Switzerland“ öffnen Satellitenbilder mit schräger Kamera im wiederverwendeten Jarvis-Kartenfenster. Gelände hängt vom verfügbaren Terrain-Dienst ab; Satellitenbilder sind keine Live-Aufnahmen. Google-3D-Gebäude benötigen die separat eingerichtete Kartenquelle. Während die Karte im Vordergrund ist, pausiert die Jarvis-Partikelanimation.


## Mail-Aufgaben

Beispiele: "Open Outlook and draft an email to alex@example.com about arranging a meeting tomorrow" oder "Open Gmail in Chrome and draft an email to alex@example.com with subject Meeting and text Hello Alex". Jarvis bereitet neue Entwürfe vor und prüft Empfänger, Betreff und Text. Ein Entwurfsauftrag sendet keine E-Mail; ausdrückliche Versandaufträge werden separat ausgeführt. Fehlende Angaben werden im selben Auftrag nachgefragt. Vorhandene Entwürfe und Signaturen bleiben unverändert; nicht eindeutig lesbare Felder führen zu einer konkreten Fehlermeldung.

Per Sprache kannst du auch sagen: "Öffne Outlook" oder "Schreibe eine Mail in Outlook über unser Meeting morgen". Ein Thema ohne diktierten Wortlaut wird als kurzer deutscher Entwurf formuliert; Jarvis erfindet dabei keine Termine, Zusagen oder sonstigen Fakten. Diktierten Text übernimmt Jarvis wörtlich. „Schreib“ und „öffne Outlook“ sind lokale Kurzbefehle; der Entwurf wird nie automatisch versendet.

"Read Gmail emails from alex@example.com before September 1, 2026" nutzt bei verbundener Google-Anbindung die vorhandene Leseberechtigung. Pro Suchauftrag werden höchstens fünf Nachrichten geladen, mit bis zu 10.000 Zeichen Text pro Nachricht. Anhänge, externe Bilder und Links werden nicht geöffnet. Die Google-Anmeldung muss in Settings eingerichtet sein. Explizite Chrome-Aufträge bleiben in der sichtbaren Gmail-Webseite; Outlook verwendet zugängliche Windows-Bedienelemente. Ohne zugängliche Oberfläche kann die App-Steuerung nicht zugesichert werden. Leseergebnisse sind Daten, keine Befehle an Jarvis.


## Voice-Pipeline (16. September 2026)

Die zusätzliche Antwortpause ist standardmäßig 0 ms. Unter Einstellungen sind 0, 100, 200, 300, 500 und 1000 ms sowie längere Denkpausen wählbar. Zusätzlich erkennt Jarvis das Sprachende nach ungefähr 160 ms Stille. Die Live-Erkennung verwendet standardmäßig den latenzärmsten Modus; „Low latency“, „Balanced“ und „More accurate“ helfen bei schwierigen Namen. Für langsames Sprechen eine längere Pause einstellen.

Die Desktop-App sendet während des Sprechens kleine Audioframes an die Live-Spracherkennung. Das Mikrofon bleibt beim Antworten aktiv: erneutes Sprechen stoppt die Ausgabe, Stop/Escape bricht sie ebenfalls ab. Stummschalten gibt das Mikrofon frei. Bei Ausfall der Live-Erkennung schaltet Jarvis auf die bisherige Datei-Erkennung um und bittet um Wiederholung; einmal stumm und wieder einschalten startet einen neuen Live-Verbindungsversuch.

Antworten werden abschnittsweise mit Fish Audio gesprochen, während weiterer Text entsteht. Memory, Google, Codex und PC-Aufgaben bleiben verfügbar. Die zusätzliche Wartezeit ist entfernt, Cloud-Dienste benötigen aber weiterhin variable Zeit. 0,5–1,2 Sekunden sind bisher nicht zuverlässig erreicht.

Technische Messwerte liegen ohne Gesprächsinhalte in config/data/voice-latency.jsonl. first_audio bezeichnet den geplanten Wiedergabestart im Browser, keine akustische Messung am Lautsprecher. Details im VOICE-PIPELINE-REPORT.md des Projekts.


## E-Mails senden und Apps bedienen

Unter Einstellungen > Google kann neben Gmail reading jetzt Gmail sending aktiviert werden. Danach Connect Google erneut auswaehlen und den Zugriff bei Google bestaetigen. Bestehende reine Leseberechtigung erlaubt keinen Versand. Die API sendet aus dem verbundenen Gmail-Konto; eine ausdrueckliche Chrome-Anweisung verwendet dagegen das sichtbare Browser-Konto.

Beispiele fuer Sprachauftraege:
- Read Gmail emails from alex@example.com before September 2026.
- Send an email in Gmail to alex@example.com, subject Meeting, saying: Can we meet tomorrow at ten?
- Open Outlook and send an email to alex@example.com, subject Meeting, saying: Can we meet tomorrow at ten?
- Open Spotify.
- Use Notepad to write Hello Samir.
- Open WhatsApp and send a message to Alex saying I will be ten minutes late.

Write/compose bereitet einen Entwurf vor; Send erlaubt den Versand. Jarvis fragt nach der exakten E-Mail-Adresse und fehlendem Inhalt. Vor UI-Versand werden Empfaenger, Betreff und Text erneut geprueft. Nach einem Timeout oder unklarem Ergebnis bitte zuerst den Gesendet-Ordner kontrollieren; Jarvis wiederholt Versand nicht automatisch.

Outlook und allgemeine App-Aktionen benoetigen eine angemeldete App mit lesbaren Windows-Bedienelementen. Nicht jede App stellt diese bereit. Gmail API-Versand meldet Annahme durch Gmail, UI-Versand verlangt eine sichtbare Versandmeldung; beides ist keine Zustellbestaetigung. Antworten im bestehenden Mail-Thread und Anhaenge sind weiterhin nicht implementiert.

Validierung: Versand mit simulierten API-/UI-Antworten getestet; beim Einbau wurde keine echte E-Mail verschickt. Vorhandene App- und Lesefunktionen bleiben erhalten.


## Dauerhaftes Gedaechtnis und Google-Kalender bearbeiten

Direkte Erinnerungen werden sofort lokal gespeichert und nach Neustarts wieder geladen, z. B. "Remember that I prefer meetings in the morning" oder "Merke dir, dass ich morgens arbeite". Die Datei config/MEMORY.md ist eine lesbare Ansicht des Gedaechtnisses; ihre Datenbank liegt in config/data/personal_memory.db. Einstellungen > Persoenliches Gedaechtnis oeffnet die Datei. API-Schluessel und Passwoerter gehoeren nicht hinein.

Google-Kalender: Einstellungen > Google > Calendar reading und Calendar editing auswaehlen, dann Connect Google und die neuen Rechte bei Google bestaetigen. Bereits erteilte reine Leserechte reichen zum Schreiben nicht. Die Verbindung und Zustimmung erfolgen fuer das Google-Konto des Nutzers.

Beispiele:
- Show my calendar appointments for tomorrow.
- Create a calendar event called Dentist tomorrow from 10 AM to 11 AM.
- Move the calendar appointment Dentist on September 20, 2026 to September 21 from 10 AM to 11 AM.

Es wird der primaere Google-Kalender verwendet. Zeiten verwenden Europe/Zurich einschliesslich Sommer-/Winterzeit; die Datumsbibliothek wird im Windows-Paket mitgeliefert. Ein abweichender Standort kann ueber JARVIS_TIMEZONE eingestellt werden. Fehlende Titel, Daten, Anfangs-/Endzeiten werden nachgefragt. Bei Aenderungen muss genau ein bestehender Termin zu Titel und urspruenglichem Datum passen. Zwischenzeitliche Aenderungen werden ueber ETag/If-Match erkannt.

Diese Version erstellt und aendert einzelne persoenliche Termine ohne Gaeste. Einladungen, Serientermine, andere Kalender und Loeschen werden nicht automatisch ausgefuehrt. Ein Netzfehler beim Schreiben fuehrt zu keinem automatischen Wiederholungsversuch: erst im Kalender nachsehen.

Geprueft: 73 Regressionstests inkl. persistenter Memory-Neuladung, vertraulicher Inhalte, Kalender-Routing, Zeitumstellung, Schreibrechte, mehrdeutiger Treffer und Aenderungskonflikte. Keine echten Testtermine erstellt oder veraendert; Kalenderzugriffe wurden in Tests simuliert.


## App-Namen lernen und Mikrofon anpassen

Bei mehreren passenden Apps fragt Jarvis nach dem Namen. Nach einer erfolgreichen Auswahl merkt er sich die Zuordnung dauerhaft. Beispiel: "Open VPN" → "Proton". Beim naechsten "Open VPN" verwendet er Proton VPN. Die Zuordnungen stehen in MEMORY.md unter Confirmed app names und bleiben nach einem Neustart erhalten. Entfernte Apps werden nicht anhand eines alten gespeicherten Pfades gestartet; die Zuordnung wird gegen den installierten Windows-Katalog geprueft.

Eine Zuordnung kann auch ohne App-Start explizit gespeichert oder ersetzt werden:
- Remember that browser means Google Chrome.
- When I say VPN, open Mullvad VPN.
- Merke dir: Mit VPN meine ich Proton VPN.

Aehnliche Namen wie Snapshat liefern Vorschlaege und starten erst nach einer eindeutigen Auswahl. Reine Nutzungshaeufigkeit veraendert die bevorzugte App nicht automatisch.

Einstellungen > Microphone sensitivity: Automatic passt die Erkennung an den gemessenen Hintergrundpegel an; Quiet voice reagiert auf leisere Sprache; Noisy room verlangt ein deutlicheres Signal. Die Live-Erkennung misst schon waehrend des Verbindungsaufbaus den Hintergrund. Wortenden haben eine weichere Schwelle als der Sprachbeginn. Die Extra-Antwortpause bleibt unveraendert bei 0 ms. Bei laengeren Denkpausen die vorhandene Pauseneinstellung erhoehen. Kopfhoerer helfen, wenn Lautsprecher-Echo erneut als Sprache erkannt wird.

Korrekturen wie cloud → Claude erfolgen nicht mehr pauschal in Gespraechen, Empfaengern oder Nachrichtentexten. Nur die direkte Anrede und passende Startbefehle werden korrigiert.

Validiert mit automatisierten Tests fuer leise Sprache, kalibriertes Hintergrundrauschen, Wortenden, Stop/Mute, App-Auswahl, Wiederladen und unveraenderte diktierte Texte. Eine Verbesserung der realen Transkriptionsgenauigkeit wurde noch nicht mit deinem Mikrofon vermessen; dies ist keine Garantie gegen Erkennungsfehler.


## Mehrstufige Aufgaben und Gmail-Entwürfe (17. September 2026)

Jarvis bewertet nach Mail- und Kalender-Aktionen den gesamten Auftrag erneut. Ein erster gespeicherter Entwurf beendet einen Auftrag mit weiteren Schritten nicht mehr. Gelesene Nachrichten liefern die Fakten für den nächsten Schritt. Eine Frage nach dem Empfänger wird erst gestellt, wenn er für einen Entwurf oder Versand benötigt wird. Fehlende Angaben werden im selben laufenden Auftrag ergänzt.

Beispiele (Adresse durch den tatsächlichen Empfänger ersetzen):
- "Read Gmail emails about delivery and summarize them for me."
- "Read Gmail emails about delivery, draft a summary to alex@example.com, then open Notepad."
- "Send a Gmail email to alex@example.com with subject Meeting and body Can we meet on Friday? Then open Chrome."
- "Show my calendar for tomorrow and save a summary as tomorrow.txt on Desktop."

Gmail reading, Gmail drafts und bei Bedarf Gmail sending unter Settings > Google auswählen. Danach Connect Google anklicken und die ausgewählten Rechte bei Google erteilen. Gmail drafts speichert neue Entwürfe direkt im verbundenen Konto und erhält eine Entwurfs-ID als Bestätigung. Die Google-Berechtigung gmail.compose ist umfangreicher als reines Lesen; Jarvis verlangt für API-Versand weiterhin die separate Einstellung Gmail sending und einen ausdrücklichen Versandauftrag. Ohne Entwurfs-Anbindung bleibt der vorhandene Weg über die App-Oberfläche verfügbar. Explizite Chrome-Aufträge bleiben im sichtbaren Browser-Konto.

Fehlgeschlagenes Datei-/Ordner-/Mail-Lesen kann der Planer einmal erneut versuchen. Ein erfolgreicher Wiederholungsversuch löst genau diesen Fehler; andere Fehler bleiben sichtbar. Schreiben und Versenden werden nach einem unklaren Ergebnis nicht automatisch wiederholt. Task status nennt den Fortschritt; Stop/Escape beendet den laufenden Auftrag. Der Verlauf bleibt in Settings sichtbar.

Grenzen: höchstens 12 Aktionsversuche, 8 Planungsrunden und 5 Minuten je Ausführung. Keine dauerhafte unbeaufsichtigte Postfachüberwachung. Bestehende Mail-Threads, Anhänge, Serientermine und beliebige Bedienelemente jeder Windows-App sind nicht allgemein unterstützt. E-Mail-Adressen werden nicht aus einem Kontaktnamen geraten. Google muss verbunden und die jeweilige Berechtigung erteilt sein. Gmail bestätigt die Annahme eines Versands, nicht die Zustellung beim Empfänger.

Die automatisierten Tests verwenden simulierte Konto- und App-Antworten; dabei wurde keine echte E-Mail gesendet. Der Planer wurde zusätzlich mit erfundenen Daten geprüft. Die Sicherung der vorherigen Installation bleibt erhalten.


## Sicherheits-, Transkriptions- und Verbindungsupdate (18. September 2026)

- **API-Schlüssel geschützt**: OpenAI- und Fish-Audio-Schlüssel werden jetzt in der Windows-Anmeldeinformationsverwaltung (Windows Vault) gespeichert. Vorhandene Klartextschlüssel in der lokalen `config/.env`-Datei werden beim Serverstart automatisch in den Windows Vault überführt und aus der `.env`-Datei bereinigt.
- **Transkriptionssprache & Halluzinationsfilter**: Sprachanfragen an die Transkriptions-API (`/api/transcribe`) fordern jetzt explizit Englisch an (`language: "en"`). Zudem verwirft der Transkriptionsschutz (`clean_transcript`) automatisch Whisper-Halluzinationen fremder Alphabete (Koreanisch, Chinesisch, Kyrillisch, Arabisch usw.) und typische Untertitel-Artefakte ("Thanks for watching", "Subtitles by") auf Hintergrundgeräuschen.
- **WebSocket-Authentifizierung & Reconnect**: Die Electron-Desktop-App stellt den Zugangstoken zuverlässig über die Desktop-Bridge bereit. HTTP-APIs akzeptieren den Token ausschließlich im `Authorization: Bearer`-Header; WebSockets authentifizieren sich im Protokoll-Handshake. Bei abgelehnter Authentifizierung schließt der Server mit Code `4001`, und das Frontend beendet die Reconnect-Schleife statt endlos neu zu verbinden. Der Browser-Dashboard-Link enthält nur einen einmaligen, 60 Sekunden gültigen Code, nie den dauerhaften Token.



## Eigenes Gedächtnis und eigener Kalender (21. September 2026)

Im Menü und unter Settings > Your Jarvis öffnen My memory und My calendar die persönlichen Ansichten direkt in Jarvis. Sprachbefehle: "Open my memory" und "Open my calendar".

My memory: Erinnerungen suchen, hinzufügen, bearbeiten und löschen. Kategorien: Fakten, Vorlieben, Routinen, Ziele und Projekte. Manuelle Änderungen haben Vorrang vor automatischem Lernen. Gespeicherte Fakten bleiben nach einem Neustart erhalten und werden nach MEMORY.md exportiert. Routinen können gespeichert und aktualisiert werden; das Speichern allein startet keine zeitgesteuerte Ausführung. Relevante Erinnerungen werden in Gesprächen berücksichtigt.

My calendar: Monatsansicht mit Tagesliste, Terminen, ganztägigen Ereignissen, Ort und Notizen. Termine lassen sich erstellen, bearbeiten und löschen. Zeiten gelten für Europe/Zurich. Sprachbeispiel: "Create a calendar event Dentist tomorrow from 10 AM to 11 AM." Bei fehlenden oder mehrdeutigen Angaben fragt Jarvis nach. Ohne ausdrücklich genanntes Google verwendet Jarvis seinen lokalen Kalender. "Show my Google calendar tomorrow" verwendet weiterhin die bestehende Google-Anbindung.

Beide Ansichten speichern lokal im config/data-Verzeichnis der installierten App. Der lokale Kalender benötigt kein Google-Konto und synchronisiert nicht automatisch mit Google. Kalender- und Gedächtnisformulare funktionieren ohne Cloud-Verbindung; freie Sprachinterpretation verwendet die vorhandene KI-Anbindung. Refresh lädt zwischenzeitliche Änderungen. Veraltete Bearbeitungen werden abgewiesen, damit sie neuere Änderungen nicht unbemerkt überschreiben.

Noch nicht enthalten: Kalender-Erinnerungsbenachrichtigungen und Serientermine.

Geprüft: 54 automatisierte Tests für Gedächtnis, Kalender, API-Zugriff, Sprachöffnung, App-Lernen und bestehende Sprachfunktionen; zusätzlich Speichern und erneutes Laden in der Oberfläche mit isolierten Testdaten. Google-Antworten wurden simuliert, es wurden keine echten Google-Termine angelegt.


## Jev API key and error codes (23 September 2026)

Open the top-right menu, then Settings > AI Settings · Jev. Enter your TypeSafe Jev API key, select Save Jev key, then Test Connection. The key is stored in Windows Credential Manager and is never shown again after saving. Remove Jev key deletes it from the vault.

Without a stored key the settings show `[JEV_KEY_MISSING]`. The Jev connection test returns the same code. If the “Use existing routing and OpenAI when Jev is unavailable” checkbox is on, Jarvis also shows the code for a routed command and can continue with that fallback. If it is off, Jarvis reports the error instead of routing the command. This does not indicate a missing OpenAI or Fish Audio key; those services have separate settings.
