# Jarvis v5 – Verbesserungsplan

Dieser Plan priorisiert die Arbeit so, dass Jarvis im Alltag schneller und verlässlicher wird, ohne dabei persönliche Daten unnötig zu sammeln oder externe Aktionen unbemerkt auszuführen. „Erledigt“ bedeutet hier, dass der Code geändert und durch automatisierte Tests bzw. einen lokalen Lauf geprüft wurde. Es bedeutet nicht, dass jede Mikrofon-, Konto- oder Gerätevariante bereits auf diesem PC praktisch vermessen wurde.

## Bereits umgesetzt und geprüft

### Spracheingabe und Erkennung

- Die Browser- und Desktop-App verwenden denselben Live-Transkriptionspfad. Fällt der Echtzeitpfad aus, bleibt der bisherige Datei-Transkriptions-Fallback verfügbar.
- Die Live-Erkennung erhält Deutsch und Englisch als erwartete Sprachen sowie einen auf Jarvis, Alltag, Besprechungen und häufige App-Namen ausgerichteten Hinweistext.
- In den Einstellungen lassen sich Namen und Fachbegriffe hinterlegen. Jarvis begrenzt und prüft diese Liste, bevor sie an den Transkriptionsdienst geht.
- Die Live-Erkennung bietet die Stufen „Fastest“, „Low latency“, „Balanced“ und „More accurate“. „Fastest“ ist Standard; die richtige Wahl hängt vom Mikrofon, Akzent, Hintergrundgeräusch und Code-Switching ab.
- Doppelte finale Transkripte werden anhand der Sitzungsereignisse abgefangen; Tests prüfen Reihenfolge, Teiltranskripte, finale Texte und ungültige Einstellungen.

### Gedächtnis und sparsamer Kontext

- Jarvis sucht für eine Frage passende Erinnerungen heraus, statt bei jeder Anfrage die gesamte gespeicherte Historie an das Sprachmodell zu senden.
- Dauerhafte Vorlieben, Routinen und ausdrücklich zu merkende Informationen werden bevorzugt. Kurzlebige Aufgaben wie „Ich öffne Outlook“ sollen nicht als dauerhafte persönliche Fakten gespeichert werden.
- Kontext und Historie sind begrenzt. Eine ausdrückliche Frage wie „Was weißt du noch über mich?“ darf mehr gespeicherte Fakten abrufen als eine normale Frage.
- Wiederkehrende Nutzungsbeobachtungen und passende lokale Notizen können in die Antwort einfließen, wenn sie für die konkrete Frage relevant sind.
- Im persönlichen Fenster lassen sich Erinnerungen ansehen, suchen, ergänzen, ändern und löschen. Manuelle Änderungen werden gegen automatische Überschreibungen geschützt; Konflikte nach einem parallelen Update verlangen ein erneutes Laden.

### Besprechungen und Kalender

- Bei Besprechungs- und Kalenderfragen lädt Jarvis den lokalen Kalender aktuell ab und ergänzt passende Einträge mit Zeit, Ort und Beschreibung.
- Zusätzlich sucht Jarvis in lokalen Notizen nach wenigen passenden Treffern. Unvertrauenswürdige Notiztexte werden als Daten behandelt, nicht als Anweisungen.
- Bei gewöhnlichen Fragen wird der Kalender nicht unnötig abgefragt.

### ChatGPT und Claude ansprechen

- Häufige direkte Formulierungen wie „Open ChatGPT and prompt it to …“ sowie entsprechende Claude-Formulierungen werden als eigener PC-Auftrag erkannt, statt fälschlich als App-Name behandelt zu werden.
- Jarvis öffnet den gewünschten Dienst und übergibt den gesprochenen Auftrag über die App-Automatisierung.
- Die Erkennung und Planung sind durch Tests abgedeckt. Der vollständige Ablauf mit einem angemeldeten echten Browserkonto wurde in diesem Durchlauf nicht gegen alle möglichen Änderungen der Webseitenoberflächen geprüft.

### Windows-App und automatisierte Prüfung

- Unabhängige Datei- und Ordnerleseschritte, die der Planer bereits aus dem Auftrag bestimmen kann, bleiben gemeinsam in derselben Phase und laufen parallel. Jarvis verwirft keine vorgemerkten Leseschritte mehr und wartet weiterhin auf gelesene Ergebnisse, bevor er davon abhängige Aktionen plant.
- Eindeutige autonome Aufträge zum Öffnen einer installierten App oder einer unterstützten Website werden lokal ausgeführt. Mehrere ausdrücklich genannte Apps werden als ein lokaler Startschritt abgearbeitet und parallel geöffnet, statt pro App auf den vorherigen Start zu warten. Unabhängige `open_app`-Schritte, die ein mehrstufiger Planer gemeinsam zurückgibt, starten ebenfalls parallel und behalten getrennte Erfolgsstatus. Diese Aufträge benötigen keinen entfernten Planungsaufruf; Websites und Sonderansichten von Jarvis behalten ihren eigenen Öffnungspfad.
- Eindeutige Leseaufträge für lokale Textdateien und Ordnerlisten gehen ebenfalls direkt an die geprüfte Windows-Dateifunktion, ohne eine Modellplanung aufzurufen. Zusammengesetzte Befehle werden dabei nicht als einzelner Dateipfad fehlinterpretiert.
- Bis zu vier ausdrücklich angegebene lokale Text-/Quellcodedateien lassen sich jetzt parallel und ohne Planungsaufruf lesen. Der Abschluss wird aus den tatsächlichen Einzelergebnissen gebildet; bei fehlgeschlagenem Lesen bleibt ein einzelner gezielter Wiederholungsversuch möglich. Wörter wie „meeting“ innerhalb eines zitierten Dateipfads lösen nicht mehr versehentlich den Kalenderplaner aus.
- Wenn ein E-Mail- oder Datei-Lesezugriff scheitert, führt Jarvis trotzdem die im selben unabhängigen Plan ausdrücklich angeforderten App-/Website-Starts aus. Abhängige Schreib- und Versandaktionen bleiben blockiert; der Gesamtauftrag wird als teilweise fehlgeschlagen gemeldet. So geht ein sicherer Teilschritt nicht verloren und Jarvis braucht keine weitere Planungsrunde nur zum Öffnen der App.
- Die Mail-Schnellplanung nimmt einen eindeutig angehängten App-/Website-Start bereits in ihre erste Phase auf. Vollständig angegebene E-Mail-Entwürfe mit einem solchen Folgeschritt bleiben modellfrei planbar; Betreff und wörtlicher E-Mail-Text werden vor dem Öffnungsbefehl getrennt.
- Vollständig angegebene einzelne E-Mail-Aufträge mit exakt erkanntem Empfänger, Anbieter, Betreff und Text werden lokal strukturiert geplant. Nach einem bestätigten Mail-Schritt endet Jarvis ohne zusätzlichen Modellaufruf nur zur Abschlussbewertung; klar sequenzierte Folgeaktionen bleiben Teil des autonomen Auftrags und werden nicht in den E-Mail-Text übernommen.
- Wenn ein Thema wie „Schreibe eine E-Mail in Outlook über unser Meeting morgen“ vorgegeben ist, aber kein Nachrichtentext diktiert wurde, erstellt der Mailplaner einen kurzen deutschen Entwurf aus genau diesem Thema. Diktierter Wortlaut bleibt modellfrei und unverändert. Ein bestätigter Entwurf braucht keine weitere Planungsrunde; er wird weiterhin nie automatisch versendet.
- Neue Aufträge während einer laufenden Aufgabe gehen nicht mehr verloren: Jarvis bestätigt sie und reiht bis zu vier für danach ein. „Stop“ beendet den aktiven Auftrag und leert diese Warteschlange.
- Die Windows-UI-Automatisierung verwendet jetzt pro Auftrag denselben Modell-Client und schickt eine kompakte Auswahl der sichtbaren Bedienelemente an den Planer. Lange Nachrichten-/Dokumenttexte und flüchtige Windows-Runtime-IDs werden nicht unnötig erneut übertragen; lokale Prüfungen behalten den vollständigen UI-Zustand. Das spart Kontext und Client-Initialisierungen; echte Antwortzeiten hängen weiterhin von Modell, Netzwerk und jeweiliger App-Oberfläche ab.
- Normale App-Klicks und Texteingaben prüfen nach der Modellantwort nur das ausgewählte UI-Steuerelement nochmals. Für Mail-Aktionen, Empfänger und Senden wird weiterhin der vollständige App-Kontext frisch gelesen; so entfällt ein teurer doppelter UIA-Baumdurchlauf pro normalem Schritt, ohne die Empfänger- und Sendeprüfung abzukürzen.
- Autonome Aufgaben speichern jetzt nur die verstrichene Gesamtzeit, summierte Planungs-/Aktionszeit und Dauer pro Schritt. Die Aufgabenhistorie zeigt diese Werte an; Zieltext, Nachrichteninhalt und Dateipfade bleiben weiterhin aus dem dauerhaften Verlauf ausgeschlossen.
- Die überarbeiteten Frontend- und Backend-Dateien wurden für das Windows-Paket gebaut.
- Die Testsuite lief beim letzten vollständigen Lauf mit **389 bestandenen Tests, 1 übersprungenem Test und 84 bestandenen Untertests** durch; Frontend-TypeScript/Vite-Build, PyInstaller-Build und der isolierte Paket-Smoke-Test für Authentifizierung, Einstellungen, Gedächtnis, Kalender und App-Dateien waren erfolgreich. Regressionstests prüfen parallele Datei-/App-Schritte, Mail-/App-Phasen ohne unnötigen Umweg und dass unabhängige App-Starts auch nach fehlgeschlagenen Mailaktionen ausgeführt werden.
- Das installierte Jarvis v5 wurde aktualisiert. Der SHA-256-Abgleich des installierten Backends mit dem geprüften Build stimmt; `/api/health` meldet Jarvis 5.0.0 als online.
- Die vorherige Installation wurde unter `backup-updates/20260924-234850` gesichert; frühere Sicherungen bleiben bestehen.

### Schnell hören und Outlook bedienen

- Der latenzärmste `minimal`-Modus ist jetzt der Standard; „Low latency“, „Balanced“ und „More accurate“ bleiben einstellbar. Niedrigere Latenz liefert frühere Teiltexte, während höhere Stufen mehr Kontext für die Genauigkeit abwarten. [Realtime-Transkription](https://developers.openai.com/api/docs/guides/realtime-transcription).
- Während die authentifizierte STT-Verbindung startet, puffert Jarvis bis zu drei Sekunden Mikrofon-Audio. So gehen die ersten gesprochenen Worte nicht verloren, wenn du direkt nach dem Einschalten sprichst.
- Der Erkennungskontext deckt jetzt deutsche und englische Outlook-/E-Mail-Diktate ab und soll Empfängernamen, Betreff und diktierten Nachrichtentext erhalten.
- „Open Outlook“ wird direkt lokal geplant, ohne erst das Sprachmodell um einen App-Start zu bitten. Vollständig diktierte englische und deutsche E-Mails werden als Outlook-Entwurf angelegt. Ein Entwurf wird nicht automatisch versendet.
- „Open Outlook and read my latest emails“ sowie der deutsche Gegenpart wählen den Outlook-Lesepfad direkt, statt zunächst einen allgemeinen Mailplaner aufzurufen. Die vorhandene Suche, Kontoprüfung und sichtbare Mail-Leseprüfung bleiben dafür zuständig.
- Gezielt geprüft: Outlook-Start, vollständige englische und deutsche Entwürfe ohne Modell-Planungsaufruf sowie STT-Konfiguration.
- Die reale Zeit vom letzten gesprochenen Wort bis zum ersten Ton wurde nicht mit einem Mikrofon gemessen; Netzwerk, Mikrofon und Akzent beeinflussen sie. Die neue Einstellung priorisiert schnelle Teilerkennung, ist aber kein belegter Millisekundenwert.
- Die lokale Endpunkterkennung wurde auf 160 ms Stille verkürzt. Vollständig diktierte Outlook-Entwürfe umgehen auch im älteren PC-Planer die zusätzliche Modellplanung; die Providerwahl „Outlook“ bleibt erhalten.

## Priorität 0 – Sprachqualität und Antwortlatenz mit echten Aufnahmen belegen

- Mail-Folgeplanung verwendet nun die allgemeine kompakte Autonomie-Anweisung plus einen gezielten Mail-Zusatz statt zwei sich stark überschneidender Vollprompts. Der Systemprompt sank von etwa 1.845 auf 777 Tokens; im synthetischen Live-Aufruf gingen Gesamteingabetokens von 2.076 auf 1.060 zurück. Bei zwei Folgeaufrufen wurden 1.057 Tokens wiederverwendet. Drei Planungen behielten den expliziten Sendeauftrag korrekt bei und meldeten ihn nicht vorzeitig als erledigt; es wurde keine E-Mail versendet. Gemessene API-Zeiten schwankten zwischen 1,2 und 2,9 Sekunden und beweisen bislang keine verlässliche Ende-zu-Ende-Beschleunigung.
- Reine Mail-Leseaufträge mit ausdrücklich gewünschtem App-/Webseitenstart enden nach bestätigtem Lesen und Öffnen ohne zusätzliche Abschluss-Planungsrunde. Bei nachgelagertem Entwurf, Antwort oder Zusammenfassung bleibt der App-Start bis nach der inhaltsabhängigen Aktion zurückgestellt. Regressionstests prüfen beide Reihenfolgen und den entfallenen Abschlussaufruf.
- Bestätigte lokale und Google-Kalenderaktionen beenden einfache Kalenderaufträge jetzt ebenfalls ohne zusätzliche allgemeine Abschluss-Planung. Ein ausdrücklich anschließender App-/Webseitenstart bleibt in derselben geordneten Phase; eine gewünschte Auswertung der Termine wird weiter anhand der tatsächlichen Leseergebnisse geplant.
- Ein gespeicherter Lauf vom 24.09.2026 vor der aktuellen Schnellpfadkorrektur benötigte 10.310 ms Planung und 2.981 ms Aktionszeit über vier Planungsrunden. Höfliche Mailbefehle wie „Could you…“ und „Bitte…“ werden jetzt vor der direkten Mailplanung normalisiert, damit vollständig angegebene Aufträge denselben modellfreien Schnellpfad wie knappe Befehle verwenden. Der Live-Lauf nach dieser Korrektur muss noch gemessen werden.

Automatisierte Tests beweisen, dass der Audiopfad und seine Einstellungen funktionieren. Sie beweisen nicht, dass Jarvis Sams Stimme in einem lauten Zimmer zuverlässig erkennt. Der nächste Schritt ist deshalb ein kleines, lokales Testset mit echten, freiwillig aufgenommenen Beispielen.

1. Je 20–30 kurze deutsche und englische Befehle aufnehmen, darunter Namen, Zahlen, Datumsangaben, E-Mail-Adressen, App-Namen und häufige Meeting-Begriffe.
2. Schwierige Beispiele ergänzen: Schweizerdeutscher Einschlag, Wechsel zwischen Deutsch und Englisch, leise Sprache, Abstand zum Mikrofon und typische Hintergrundgeräusche.
3. Für jede Erkennungsstufe Wortfehlerrate, ausgelassene/verdoppelte Befehle und Zeit bis zum ersten brauchbaren Teiltranskript messen.
4. `speech_end`, `stt_final`, `llm_first_token`, `first_tts_chunk`, `first_audio` und `response_complete` pro Anfrage erfassen. Latenz als Median und 95. Perzentil ausweisen, nicht aus Einzelmessungen ableiten.
5. VAD-Ende, Stop/Escape, Echo aus Jarvis’ Lautsprecherausgabe und Barge-in separat testen. Beim erneuten Sprechen müssen alte Audio-Chunks verworfen und keine alte Antwort weitergespielt werden.
6. Den schnellen Modus als Standard beibehalten und „Balanced“/„More accurate“ für schwierige Namen oder laute Räume anbieten. Mit echten Aufnahmen messen, ob der schnellere Modus für Samirs Stimme zuverlässig genug ist; keine reale Latenz oder Erkennungsrate ohne Messung behaupten.

**Abnahme:** Keine doppelten Aktionen in 100 wiederholten Befehlen; deutsche Namen und Zahlen in der vereinbarten Testliste korrekt; Latenzbericht für alle drei Stufen; Stop/Barge-in beendet die Ausgabe reproduzierbar.

## Priorität 1 – Persönliches Gedächtnis kontrollierbar machen

1. Einen klaren Speicherbefehl anbieten, etwa „Remember that …“, und nach erfolgreichem Speichern knapp bestätigen.
2. Auf Wunsch anzeigen, welche Fakten, Routinen und Vorlieben gespeichert sind; einzelne Einträge korrigieren oder löschen können.
3. Persönliche Fakten, Gesprächszusammenfassungen und kurzfristige Aufgaben getrennt halten und jeweils ein Ablaufdatum bzw. eine Aufbewahrungsregel anwenden.
4. Geheimnisse wie API-Schlüssel, Passwörter, Zugangscodes und vollständige Zahlungsdaten grundsätzlich vom automatischen Gedächtnis ausschließen.
5. Retrieval mit Fragen aus Alltag und Meetings testen. Ein Treffer muss zur Frage passen; ein irrelevanter Fakt soll lieber fehlen.
6. Für wiederkehrende Routinen sparsame, zusammengefasste Einträge statt eines Protokolls jedes einzelnen Gesprächs nutzen.

**Abnahme:** Nutzer kann gespeicherte Information sehen, korrigieren und löschen; sensible Testwerte werden nicht gespeichert; normale Fragen senden nur passende, begrenzte Erinnerungen.

## Priorität 1 – Besprechungswissen verlässlich zusammenführen

1. Den lokalen Kalender als schnelle Quelle beibehalten und Google-/Outlook-Kalender nur abfragen, wenn der Nutzer sie verbunden und die Berechtigung erteilt hat.
2. Zeitangaben in der lokalen Zeitzone darstellen und „nächste Woche“, ganztägige Termine sowie Sommer-/Winterzeit testen.
3. Meeting-Kontext aus Terminbeschreibung und freigegebenen lokalen Notizen beziehen. E-Mails nur dann durchsuchen, wenn eine verbundene Mail-Integration aktiv und die Frage passend ist.
4. Antworten klar unterscheiden lassen zwischen Kalenderfakt, gespeicherter Notiz und Schlussfolgerung. Unbekannte Punkte nicht erfinden.
5. Eine kompakte Meeting-Zusammenfassung mit Teilnehmenden, Ziel, offenen Punkten und letzten Entscheidungen auf Nachfrage erzeugen.

**Abnahme:** Tests für Zeitzonen, leeren Kalender, doppelte Termine, unvollständige Beschreibungen und widersprüchliche Notizen; jede Antwort kann ihre lokale Quelle benennen.

## Priorität 1 – App- und Browseraktionen robuster machen

1. App-Namen vor der allgemeinen Sprachmodellplanung normalisieren, inklusive gängiger deutscher/englischer Aussprachevarianten.
2. Zwischen „App öffnen“, „Text vorbereiten“ und „Nachricht/E-Mail absenden“ unterscheiden. Vor dem tatsächlichen Senden den Empfänger und Inhalt sichtbar bzw. hörbar kontrollieren lassen, sofern keine eindeutige Freigabe vorliegt.
3. ChatGPT- und Claude-Oberflächen mit angemeldetem Browser praktisch prüfen. Selektoren, Fokuswechsel, Ladezustände, Fehlermeldungen und Änderungen der Webseiten regelmäßig testen.
4. Bei unklarer Person oder Empfänger nicht raten. Jarvis soll die fehlende Information kurz erfragen.
5. Nach einer Aktion das Ergebnis kontrollieren, statt nur zu melden, dass sie ausgeführt wurde.
6. Für Aufgaben, die nicht zuverlässig über eine Weboberfläche bedient werden können, eine stabile offizielle API-Integration anbieten, sofern Zugangsdaten sicher und ausdrücklich eingerichtet wurden.

**Abnahme:** Für jede unterstützte Aktion existiert ein Erfolgssignal, ein Timeout und eine verständliche Fehlermeldung. Keine unbestätigte Nachricht an einen unklaren Empfänger.

## Priorität 2 – Zuverlässigkeit, Sicherheit und Wartbarkeit

1. Verbindungsabbrüche bei OpenAI, Fish Audio, Google und Microsoft mit begrenzten Wiederholungen und verständlichem Status behandeln.
2. API-Schlüssel ausschließlich in Windows Credential Manager oder einem gleichwertigen Secretspeicher halten; nie in Logs, URLs, Testausgaben oder Erinnerungen schreiben.
3. Latenz- und Fehlertelemetrie lokal und datensparsam halten. Eine Einstellung soll erlauben, Diagnosedaten zu löschen.
4. Gemeinsame asynchrone Aufgaben bei Stop, App-Neustart und Netzwerkverlust sauber beenden.
5. Kritische Integrationen mit Mocktests und wenige gezielte manuelle Smoke-Tests abdecken, ohne echte Nachrichten oder E-Mails an Testpersonen zu schicken.
6. Vor Releases Backup, Paketversion, installierte Prüfsumme, Health-Check und Rollback-Anleitung automatisch dokumentieren.

**Abnahme:** Keine Schlüssel in Repository oder Logs; wiederholter Start/Stop ohne hängende Audioaufgaben; Release kann anhand der Sicherung zurückgesetzt werden.

## Autonomie-Schnellweg – 25. September 2026

Wenn ein Auftrag einen konkreten lokalen Datei-Lesezugriff und einen ausdrücklich gewünschten App- oder Website-Start enthält, zerlegt Jarvis ihn jetzt lokal ohne Planungsmodell. Der Datei-Lesezugriff und genau ein unabhängiger Start laufen parallel. App- und Website-Starts untereinander bleiben seriell, wenn Windows-Fokus betroffen sein kann. Tests prüfen die deutsche und englische Aktionsroute, einen Planungsdurchlauf, gleichzeitige Ausführung und dass abhängige Mail-/Schreibschritte weiter auf ihre gelesenen Ergebnisse warten. Die künstliche Überlappung ist durch einen Barriere-Test belegt; eine reale Zeitersparnis für ein bestimmtes Laufwerk oder eine geschlossene App wurde nicht behauptet.

Ein unabhängiger Kalenderauftrag kann nun ebenfalls parallel zu einem ausdrücklich gewünschten App- oder Website-Start laufen. Das gilt nur für genau einen Kalenderauftrag; Datei-Lesevorgänge werden nicht mit Kalenderänderungen vermischt. Ein Synchronisationstest belegt die gleichzeitige Ausführung und dass ein einfacher Kalenderauftrag ohne zusätzliche allgemeine Planungsrunde endet. Die Kalenderintegration darf weiterhin selbst eine fachliche Datumsplanung durchführen.

Eindeutige Leseanfragen an den lokalen Jarvis-Kalender für heute, morgen, diese/nächste Woche und die nächsten sieben Tage werden jetzt ohne Planungsmodell direkt aus der lokalen Datenbank beantwortet. Datumsgrenzen folgen der Zeitzone Europe/Zurich; Google-Anfragen und unklare Zeiträume bleiben beim bisherigen Planer. Deutsche Formen wie „Liste meinen Kalender nächste Woche“ werden ebenfalls als Kalenderanfragen erkannt.

Für die ausdrückliche Anfrage nach den neuesten Outlook-Mails liest Jarvis jetzt bis zu fünf Nachrichten direkt und nur lesend aus dem klassischen Outlook-Posteingang. Bei einem ausdrücklichen „Outlook öffnen“ startet Jarvis Outlook zuerst und liest dann per COM. Das umgeht die mehrstufige UI-Planung; neue Outlook-Versionen ohne COM nutzen weiterhin den bisherigen geprüften UI-Pfad. Andere Filter, etwa nach Absender oder Datum, wurden nicht auf diese Abkürzung umgestellt.

Terminale Leseaufträge laufen nach einem endgültigen Fehler nicht mehr in eine zusätzliche Planungsrunde, die nur denselben fehlgeschlagenen Zugriff erneut auswählt. Klar vorübergehende Netzwerk-/Timeout-Fehler erhalten höchstens einen direkten Wiederholungsversuch; dauerhafte Berechtigungs- oder Verfügbarkeitsfehler enden unmittelbar mit `needs_attention`. Parallele Datei-Leseaufträge verwenden dieselbe begrenzte Wiederholung und behalten ausdrücklich angeforderte App-Starts bei. Schreib-, Sende-, Kalender- und UI-Aktionen werden dabei nicht wiederholt.

Ein Mail-Lesezugriff kann jetzt gleichzeitig mit einem ausdrücklich gewünschten, davon unabhängigen App- oder Webseitenstart laufen. Outlook lesen und Outlook selbst starten sowie Gmail lesen und die Gmail-Webseite öffnen bleiben absichtlich geordnet, um konkurrierende Starts desselben Mailclients zu vermeiden. Die Mailauswahl wird nach dem parallelen Lesen in den laufenden Assistentenkontext zurückgegeben, damit ein Folgeschritt sie weiterverwenden kann. Synchronisationstests prüfen Parallelität, Kontextübergabe und die geordnete Outlook-Ausnahme.

## Salt Fiber Box und Telefonie

Die von Salt dokumentierte Verbindung eines Festnetztelefons erfolgt über einen der RJ11-Telefonanschlüsse oder über DECT. Die USB-A-Anschlüsse der Fiber Box werden als USB-3.0-Anschlüsse für Speicher/Peripherie aufgeführt, nicht als PC-Telefon- oder Audioverbindung. Ein USB-A-zu-USB-A-Kabel vom Router zum Laptop macht Jarvis daher nicht zum Telefon.

Vor einer Telefonie-Implementierung zuerst das genaue Fiber-Box-Modell und die Salt-Festnetzoptionen prüfen. Salt müsste bestätigen, ob SIP-Zugangsdaten oder ein unterstützter Telefonieadapter für ein Drittgerät verfügbar sind. Erst dann lässt sich beurteilen, ob eine Software-Telefonanlage oder ein kompatibler Adapter realistisch ist.

## Reihenfolge der nächsten Arbeiten

1. Echte Mikrofon-Testaufnahmen und Latenzmessung ergänzen.
2. Kalender- und Meeting-Antworten mit Zeitzonen und verbundenen Anbietern erweitern.
3. Browseraktionen für ChatGPT und Claude an einem angemeldeten Konto praktisch absichern.
4. Credential-Speicherung, Abbruchverhalten und Release-Rollback härten.
5. Erst nach diesen Messungen weitere Modelle, lokale KI oder Telefonie-Hardware integrieren.
