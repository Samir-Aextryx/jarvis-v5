# Jarvis v5: Voice-Pipeline, 16. September 2026

## Ergebnis und Installation

Die optimierte Windows-App ist unter `%USERPROFILE%\Documents\Jarvis v5` installiert und gestartet. Die Desktop-Verknuepfung wurde auf diesen vorhandenen Speicherort korrigiert. Der zuvor verwendete Desktop-Unterordner existiert nicht mehr. Der vorhandene Ordner `%USERPROFILE%\Documents\jarvis v5 backup` bleibt unangetastet; vor dem Update wurde das installierte Backend zusaetzlich in `backup-updates` gesichert. Konfiguration und gespeicherte Daten bleiben erhalten.

Das Ziel von 0,5 bis 1,2 Sekunden ist in den Cloud-Messungen **nicht erreicht**. Erste PCM-Audiodaten kamen im korrigierten Vergleich nach 2,082 bis 5,822 Sekunden, Median 2,702 Sekunden. Ein separater Test des installierten Servers ergab 2,271 Sekunden. Diese Werte messen die Ankunft von Audio, nicht den akustischen Beginn am Lautsprecher.

## Gefundene Engpaesse und Aenderungen

| Bisheriger Engpass | Umsetzung |
|---|---|
| Zusaetzliche Antwortpause, standardmaessig 2000 ms | Neue Einstellung standardmaessig 0 ms; 0/100/200/300/500/1000 ms sowie laengere Denkpausen bleiben waehlbar. Lokale Sprachende-Erkennung benoetigt zusaetzlich etwa 160 ms Stille. |
| STT startet erst nach Abschluss einer Audioaufnahme | AudioWorklet liefert 20-ms-PCM-Frames mit 24 kHz an einen authentifizierten persistenten WebSocket. Teiltranskripte entstehen schon waehrend des Sprechens. |
| Warten auf vollstaendige LLM-Antwort | OpenAI Responses SSE liefert Textdeltas direkt an einen Phrase-Buffer. |
| TTS und Textgenerierung nacheinander | Ausgabe bei Satzzeichen oder etwa 12 Woertern; zwei Fish-Anfragen koennen gleichzeitig laufen, Wiedergabe bleibt in Textreihenfolge. Begrenzte Warteschlangen verhindern unkontrolliertes Vorladen. |
| Mikrofon/Late Replies unterbrechen neue Eingaben | Mikrofon bleibt aktiv. Lokale Spracherkennung unterbricht nach ca. 80 ms ausreichend lauter Sprache; Turn-IDs, Generationen und Cancellation verwerfen alte Antworten. Escape/Stop und Hard-Mute bleiben erhalten. |
| Wiederholte Kontexte und Verbindungskosten | Relevante, begrenzte Memory-Auswahl, letzte sechs Nachrichten, paralleles Laden der Erinnerungen, HTTP-Keep-Alive und persistentes STT. Vollstaendig gespeichertes Gedaechtnis wird nicht geloescht. |
| Unnoetige Modellaufrufe fuer einfache Aktionen | Bestehende direkte App-/Website-/Karten-Aktionen bleiben erhalten. Direkter Screenshot, lokales Mute und englischer Codex-Status umgehen ebenfalls den Antwort-LLM. |
| Keine durchgehenden Messpunkte | speech_end, stt_final, llm_first_token, first_tts_chunk, first_audio und response_complete; Abbrueche getrennt markiert, keine Gespraechsinhalte im Latenzlog. |

Das STT-Modell `gpt-live-transcribe` wurde mit der tatsaechlichen API geprueft. Server-VAD wird fuer dieses Modell abgelehnt; deshalb verwendet Jarvis lokale VAD und explizite Audio-Commits. Der bisherige Upload-STT bleibt als Fehlerfallback erhalten. Nach einem Verbindungsfehler wird um Wiederholung gebeten, damit ein unsicher erkannter Befehl nicht doppelt ausgefuehrt wird. Stumm-/Wiedereinschalten versucht die Live-Verbindung erneut.

Fish-Stimme und Qualitaets-/Latenzeinstellung bleiben erhalten. Die Verbindung zum LLM und Fish ist gepooltes HTTP; STT verwendet WebSocket. Fish erhaelt parallele Streaming-HTTP-Anfragen pro Phrase, keinen behaupteten kontinuierlichen Text-WebSocket.

## Messungen

Die identische synthetische englische Testaufnahme fragt nach einer kurzen API-Erklaerung. Neue STT-Eingabe wird mit Echtzeitgeschwindigkeit in 20-ms-Frames zugespielt. Die alten Messungen stammen aus dem Zustand vor dem Umbau; es gibt nur einen alten Vergleichslauf, deshalb keine belastbare alte Verteilung. API-Key-, Modell-, Stimme- und Fish-Einstellungen von Quellprojekt und jetziger Installation wurden auf Uebereinstimmung geprueft, ohne Geheimnisse auszugeben.

| Messung ab Sprachende | Alt: einzelner Referenzlauf | Neu Lauf 1 | Neu Lauf 2 | Neu Lauf 3 |
|---|---:|---:|---:|---:|
| STT final | 1660 ms Verarbeitung nach Upload, plus alte Pause | 3026 ms | 1104 ms | 859 ms |
| Erstes LLM-Token | nicht gemessen; volle Antwort brauchte 1790 ms | 5157 ms | 2254 ms | 1664 ms |
| Erste Server-PCM-Daten | **5759 ms geschaetzt**, inkl. 2000 ms Pause | **5822 ms** | **2702 ms** | **2082 ms** |
| Generierung/PCM-Uebertragung fertig | 4798 ms ohne alte Pause | 7027 ms | 3792 ms | 2696 ms |

Der neue Median bis zu ersten PCM-Daten ist etwa 53 % niedriger als die alte Einzellauf-Schaetzung. Das ist keine Garantie fuer jede Anfrage: Lauf 1 war sogar etwas langsamer. Kalte Verbindungen, Anbieterlast, Netzwerk und Antwortlaenge beeinflussen das Ergebnis. Alle drei neuen Laeufe lieferten Teiltranskripte vor Sprachende.

Ein Fehler im urspruenglichen neuen Benchmark schloss die STT-Verbindung vor Beginn des LLM-Aufrufs. Der Close-Handshake wurde damit faelschlich der Antwortlatenz zugerechnet. Der korrigierte Benchmark haelt die Verbindung wie die App offen. `benchmarks/after.json` enthaelt ausschliesslich die korrigierten Werte.

Separater Integrationstest nach Installation (`benchmarks/installed-round1.json`): STT final 914 ms, erstes LLM-Token 1955 ms, erste PCM-Daten 2271 ms, 156 Audio-Pakete; Live-Teiltranskript, finales Transkript, Authentifizierung und Auslieferung des AudioWorklets erfolgreich.

`first_audio` wird in der echten Oberflaeche zum geplanten Start der AudioContext-Wiedergabe erfasst; PCM hat einen kleinen Vorlauf von 15 ms. Die Benchmark-Spalte `estimated_browser_first_audio` ist nur Server-PCM plus 15 ms und **keine** echte Browser-/Lautsprechermessung. `response_complete` im Browser meint Ende der Wiedergabe; im synthetischen Backend-Benchmark meint es Ende der Generierung/Uebertragung. Diese unterschiedlichen Endpunkte duerfen nicht gleichgesetzt werden.

## Validierung

- 81 Python-Regressionstests bestanden: Streaming, STT-Relay, Authentifizierung, finale Deduplication, Fehler/Abbruch, gepoolte Verbindungen, Memory, Google, Mail-Workflows, autonome Aufgaben, PC-Steuerung, Websites und Karten.
- Sechs Node-Testprogramme bestanden: Live-Mikrofonmodell, Datei-Fallback, PCM-Wiedergabe, AudioWorklet bei 24/44,1/48 kHz, natives Kartenfenster und Animationsgeometrie.
- TypeScript-Pruefung, Vite-Produktionsbuild und PyInstaller-Windows-Build erfolgreich.
- Live OpenAI/Fish-Benchmarks und anschliessender Integrationstest gegen den installierten Server erfolgreich. Keine Test-E-Mails versendet, keine Desktop-Befehle aus Testtranskripten ausgefuehrt.

## Geaenderte Dateien dieser Voice-Arbeit

| Dateien | Zweck |
|---|---|
| `server.py`, `llm_client.py` | SSE-Anbindung, Streaming-TTS, direkte Aktionen, Turn-IDs, Messpunkte, Kontextauswahl |
| `streaming_voice.py` | Phrase-Buffer, begrenzte parallele Fish-Generierung, geordnete PCM-Ausgabe, Abbruch |
| `realtime_stt.py` | Authentifizierter PCM-Relay, Sitzung, Partials/Finals, Fehlerbehandlung und Deduplication |
| `frontend/public/pcm-capture.js`, `frontend/src/voice-stream.ts` | AudioWorklet, Resampling, lokale VAD, Live-Frames, Fallback, kontinuierliches Mikrofon |
| `frontend/src/voice.ts`, `frontend/src/voice-desktop.ts`, `frontend/src/main.ts` | Wiedergabestart-Messung, Abbruch, alte Aufnahme als Fallback, Metadaten und verworfene alte Antworten |
| `frontend/src/settings.ts` | Antwortpause 0 ms und neue Auswahlwerte |
| `voice_turn.py`, `voice_context.py`, `voice_metrics.py`, `pc_control.py` | Turn-Schutz, begrenzter Kontext, Latenzlog, direkter Codex-Status |
| `tests/test_streaming_voice.py`, `tests/test_realtime_stt.py`, `tests/voice-stream.cjs`, `tests/pcm-capture.cjs`, `tests/voice-latency.cjs`, `tests/pcm-playback.cjs` | Streaming-/Audio-/Abbruchregressionen |
| `benchmarks/baseline.py`, `benchmarks/streaming.py`, `benchmarks/installed_smoke.py`, zugehoerige JSON-Dateien | Referenzmessungen und installierter Integrationstest |
| `update-desktop.ps1`, `Jarvis-v5-Hilfe.md`, dieser Bericht | Update am vorhandenen Speicherort, Verknuepfung, Sicherung und Dokumentation |

Bereits vorbereitete Mail-Aenderungen in `email_planner.py`, `email_workflows.py`, `google_access.py`, `local_pc.py`, `autonomous_tasks.py` und `desktop_agent.py` wurden mit verpackt und regressionsgeprueft. Sie trennen Lesen, Entwurf, Rueckfrage und Abschlusspruefung. Sie wurden nicht zugunsten der Voice-Aenderungen verworfen.

## Verbleibende Grenzen

- 0,5 bis 1,2 Sekunden sind mit dieser gemessenen Kombination noch nicht erreicht. Netz-/Anbieterzeiten lassen sich durch lokale Queues nicht entfernen. Es wurde kein weniger leistungsfaehiges Modell eingesetzt, nur um bessere Zahlen zu erhalten.
- Reales Mikrofon, Lautsprecherecho, Erkennung bei Hintergrundlaerm und subjektive Prosodie wurden nicht akustisch Ende-zu-Ende vermessen. Barge-in ist durch simulierte Audioframes und Cancellation-Tests abgesichert; die Echo-Unterdrueckung bleibt geraeteabhaengig.
- 160 ms Stille priorisiert Schnelligkeit. Fuer Denkpausen die zusaetzliche Pause erhoehen; das erhoeht bewusst die Antwortlatenz.
- Arbeitsmodus, komplexe Aktionsplanung und Ergebnisse externer Apps haben eigene Laufzeiten; nicht jede Aktion liefert sofort streambaren Antworttext. Kurze direkte Befehle umgehen den LLM, benoetigen aber weiterhin STT und gegebenenfalls Fish.
- UI-Automation von Outlook/Gmail wurde mit Regressionstests geprueft, nicht durch Versand echter Nachrichten. Outlook stellte beim vorherigen UI-Test keine nutzbaren Accessibility-Elemente bereit; dort bleibt die erfolgreiche Bedienung der konkreten Oberflaeche unbestaetigt.
- Der Vite-Build meldet weiterhin einen JavaScript-Chunk ueber 500 kB. Das ist eine Start-/Ladegroesse, keine neu eingefuehrte Antwortpause.
- Benchmark-Resampling verwendet `audioop` in Python 3.12; bei einem spaeteren Wechsel auf Python 3.13 muss nur dieses Testhilfsmittel ersetzt werden. Die produktive Mikrofon-Resampling-Pipeline verwendet JavaScript.

Die App schreibt in `config/data/voice-latency.jsonl` einen begrenzten, inhaltsfreien Verlauf. Der authentifizierte Endpunkt `/api/voice/metrics` liefert die letzten 100 Eintraege. Nicht verwendete Stufen fehlen, etwa `llm_first_token` bei einem direkten lokalen Befehl.

## Schnellere Spracheingabe und Outlook-Mail (24. September 2026)

Neue Einstellungen verwenden `minimal` als Standard fuer die OpenAI-Live-Transkription. Die fruehere Endpunkterkennung nach 180 ms Stille wurde auf 160 ms gesenkt. VAD erkennt den Sprechbeginn weiterhin nach vier aufeinanderfolgenden 20-ms-Frames. Das ist eine Latenzoptimierung; erkennbare Namen koennen mit „Low latency“, „Balanced“, „More accurate“ und den optionalen Namen-Hinweisen verlaesslicher werden. Die wirkliche Zeit bis zum ersten Ton wurde mit dem Mikrofon dieses Computers nicht neu gemessen.

Vollstaendig angegebene E-Mail-Entwuerfe werden nun auch im aelteren LocalPC-Aufruf direkt und ohne LLM-Planung erstellt. Der explizit genannte Provider bleibt erhalten: „in Outlook“ erzeugt einen Outlook-Entwurf, nicht Gmail. „Open Outlook“ wird weiter lokal und ohne Planungsaufruf geoeffnet. Diese Aenderungen wurden mit den Python-Tests und simulierten Live-Mikrofonpruefungen validiert; es wurden keine echten Nachrichten versendet.


## Zweite Optimierungsrunde: frueherer Sprechbeginn

Auf erneuten Wunsch nach maximaler Geschwindigkeit wurde der erste Sprachabschnitt von 12 auf 8 vollstaendige Woerter reduziert. Folgeabschnitte nutzen bis zu 16 Woerter; Satzzeichen koennen weiterhin frueher ausloesen. Ein einzelnes grosses LLM-Delta mit spaetem Satzzeichen wird jetzt ebenfalls am frueheren Wortlimit geteilt. Steuer-Tags bleiben ausgeschlossen. Dies ist mit neuen Tests auf Verlustfreiheit und Chunk-Grenzen geprueft.

Die variable Uhrzeit und Wetterdaten wurden hinter alle festen Aktionsanweisungen verschoben. Damit kann der lange unveraenderte Prompt-Praefix auch ueber Minutenwechsel hinweg wiederverwendet werden. Kein Aktionsvertrag und keine Persoenlichkeitsregel wurde entfernt. Grundlage: [OpenAI Prompt Caching](https://developers.openai.com/api/docs/guides/prompt-caching). Cache-Treffer oder deren individuelle Zeitersparnis wurden nicht separat gemessen.

Fish bleibt im bisherigen balanced-Modus mit derselben Stimme. Laut [Fish-TTS-Referenz](https://docs.fish.audio/api-reference/endpoint/openapi-v1/text-to-speech) ist low ein Latenz-/Qualitaetskompromiss; es wurde deshalb kein ungepruefter Qualitaetswechsel vorgenommen.

Drei neue Messungen mit identischer Aufnahme (`benchmarks/faster.json`):

| Lauf | STT final | Erstes LLM-Token | Erste Server-PCM-Daten |
|---|---:|---:|---:|
| 1 | 893 ms | 1974 ms | 2371 ms |
| 2 | 914 ms | 1928 ms | 2292 ms |
| 3 | 972 ms | 1797 ms | 2244 ms |

Median 2292 ms gegen zuvor 2702 ms. Wegen kleiner Stichprobe und Cloud-Schwankungen ist die Differenz kein belastbarer Kausalnachweis. Der bisherige installierte Einzellauf von 2271 ms liegt auf aehnlichem Niveau. 0,5-1,2 Sekunden werden weiterhin nicht erreicht. Keine dieser Zahlen ist eine akustische Messung. Die Antwortgenerierung benoetigt weiterhin rund 0,8-1,1 Sekunden nach finalem Transkript, STT rund 0,9 Sekunden nach Sprachende.

83 Python-Regressionstests bestanden; Backend erneut gebaut. Geaenderte Produktdateien dieser Runde: `server.py` und `streaming_voice.py`; Tests in `tests/test_streaming_voice.py`; korrigierter Installationspfad und getrennte Ausgabedatei fuer Wiederholungsmessungen in `benchmarks/streaming.py`.

Integrationstest nach dem zweiten Update: Live-STT und PCM-Streaming bestanden; STT final 1004 ms, erstes LLM-Token 2074 ms, erste Server-PCM-Daten 2409 ms (`benchmarks/installed.json`). Die Installation wurde gestartet und das vorherige Backend erneut gesichert.

## 25. September 2026: Mikrofon sofort starten

Die Windows-Oberflaeche wartete nach dem Laden kuenstlich eine Sekunde, bevor sie das Mikrofon anforderte und den persistenten Live-STT-Stream aufwaermte. Diese Wartezeit entfaellt: Jarvis startet die Spracheingabe jetzt im ersten gerenderten App-Frame. Das kann das Mikrofon und die Transkriptionsverbindung bis zu einer Sekunde frueher bereitstellen; es aendert nicht die gemessene Zeit vom gesprochenen Satzende bis zur ersten Antwort. Outlook wird weiterhin lokal ohne Planungsaufruf geoeffnet. Deutsche und englische E-Mail-Entwuerfe bleiben auf den getrennten, geprueften Entwurfsweg geleitet und werden nicht automatisch gesendet.

Gezielte Regressionstests fuer Stimme, Outlook-Start und E-Mail-Entwuerfe bestanden; die echten Mikrofon-/Lautsprecherlatenzen wurden fuer diese kleine Aenderung nicht erneut gemessen.
