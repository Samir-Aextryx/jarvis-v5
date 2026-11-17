# OpenAI, Gemini, Grok, Ollama Cloud und lokale KI in Jarvis

## Bedienung

Beim ersten Start führt der Einrichtungsassistent durch Name, KI-Wahl (Cloud oder
lokal) und die API-Schlüssel. Er lässt sich unter **Settings → General → Run setup
again** erneut öffnen. Später:

1. **Settings → API keys**: Schlüssel eintragen und mit **Save** speichern. Jede Karte
   zeigt, ob ein Schlüssel gespeichert ist; **Test** prüft ihn, **Remove** löscht ihn.
2. **Settings → AI → Cloud AI**: OpenAI, Google Gemini, xAI Grok oder Ollama Cloud
   wählen. Modell-IDs stehen unter „Model IDs and reasoning“. Änderungen werden sofort
   gespeichert.
3. Der „Test“-Button ist eine echte kleine, kostenpflichtige API-Abfrage mit dem
   eingestellten Modell. „Saved“ bestätigt nur das Speichern, „Working“ den API-Test.

## Lokale KI (Ollama + Hugging Face)

**Settings → AI → Local AI** (oder im Einrichtungsassistenten):

1. **Install local AI** installiert die offizielle, signierte Ollama-App per
   `winget` für den aktuellen Benutzer (ohne Adminrechte). Ohne winget führt der
   Button zur Ollama-Downloadseite.
2. Ein empfohlenes Modell mit **Download** laden oder Hugging Face durchsuchen und
   unter **Versions** eine Quantisierung wählen (Q4_K_M ist ein guter Kompromiss).
   Ollama lädt GGUF-Dateien direkt als `hf.co/<repo>:<quant>`.
3. **Use** macht ein heruntergeladenes Modell zur KI von Jarvis; **Remove** löscht es.

Lokale Anfragen gehen an `http://127.0.0.1:11434/v1/chat/completions`, ohne
API-Schlüssel. Jarvis startet Ollama bei Bedarf selbst. Modelle mit Denkmodus
(z. B. Qwen3 8B) bekommen die gewählte Reasoning-Stufe, alle anderen `none`.
Spracherkennung (OpenAI) und Stimme (Fish Audio) brauchen weiterhin ihre Schlüssel.

OpenAI bleibt die bestehende Standardauswahl. Neue Standardmodelle sind
`gemini-3.8-flash` und `grok-4.7`, gemäß den bei Umsetzung abgerufenen offiziellen
Dokumentationen. Verfügbarkeit hängt vom API-Konto ab; Modell-IDs sind editierbar.
ChatGPT-, Gemini- oder Grok-Chat-Abos stellen keine API-Verbindung in Jarvis her.

**Ollama Cloud** nutzt standardmäßig `deepseek-v4.1-flash` (DeepSeek V4.1 Flash) über
`https://ollama.com/v1/chat/completions`; Schlüssel unter <https://ollama.com/settings/keys>.
Ein Tag wie `deepseek-v4.1-flash:1017` pinnt eine Version. DeepSeek denkt ohne
Vorgabe auf „high“; Jarvis sendet die gewählte Reasoning-Stufe (`none`, `low`,
`high`, `max`; `medium` → `high`, `xhigh` → `max`). `none` antwortet am schnellsten.

## Was die Auswahl steuert

Gesprächsantworten, Intent-Klassifikation, E-Mail-/Kalenderplanung, Desktop-
Planung und die LLM-Antworten des vorbereiteten Telefonmodus verwenden den
ausgewählten Anbieter. Ein laufender Request behält seinen Anbieter. Neue
Requests übernehmen die gespeicherte Auswahl; kein Neustart ist erforderlich.

Fish Audio und die ausgewählte Jarvis-Stimme bleiben erhalten. Mikrofon-STT
verwendet weiterhin OpenAI; dessen API-Schlüssel ist dafür auch bei Auswahl
von Gemini oder Grok erforderlich. Google-Konto-OAuth für Gmail/Kalender ist
von einem Gemini-API-Schlüssel unabhängig. Codex-/ChatGPT-/Claude-App-Prompts bleiben Desktopfunktionen.

Es erfolgt kein automatischer Wechsel zu einem anderen Anbieter bei Fehlern.
Das vermeidet überraschende Kosten und das Senden des Kontexts an einen
nicht ausgewählten Dienst. Bestehende lokale Befehle umgehen die KI weiterhin.

## Umsetzung und Zugangsdaten

- `rust/src/settings.rs`: feste offizielle HTTPS-Endpunkte, eigene Key-/Modellnamen.
- `rust/src/llm.rs`: bestehende OpenAI Responses API; Gemini und Grok über
  Chat Completions. Einheitliches Text-/Nutzungsformat, Bild- und JSON-Schema-
  Unterstützung, sofortiges SSE-Streaming und Abbruch beim Stoppen.
- API-Schlüssel: `OPENAI_API_KEY`, `GEMINI_API_KEY`, `XAI_API_KEY`, `OLLAMA_API_KEY`.
  Gemini-/Grok-/Ollama-Schlüssel werden nur bei bestätigter Speicherung im Windows
  Credential Manager als gespeichert gemeldet. Schlüssel werden niemals vom
  Status-Endpunkt zurückgegeben oder in Browser-LocalStorage gespeichert.
- Auswahl und Modelle: `agent-settings.json`, mit kompatiblen Defaults für
  alte Einstellungen. `.env.example` dokumentiert die Startkonfiguration.
- Verbindungstest: `/api/settings/test-llm`, authentifiziert wie bestehende
  Einstellungen. Der alte OpenAI-Test bleibt ausdrücklich an OpenAI gebunden.
- Der frühere OpenAI-Schlüsselparameter der Sprachübersetzung wird niemals
  als Gemini-/Grok-Schlüssel wiederverwendet.
- Die bisherigen Kostenschätzungen in Jarvis beruhen weiterhin auf den
  bisherigen konfigurierten OpenAI-Preisen. Sie sind keine verlässliche
  Rechnung für gemischte Anbieter. Tatsächliche Kosten im jeweiligen
  Anbieter-Dashboard prüfen; Tokenzählung wird normalisiert.

## Prüfstand

29 gezielte Provider-Tests prüfen Schlüsseltrennung, Endpunkte, Text, Bilder,
JSON-Schemas, Nutzung, Streaming vor Abschluss, Abbruch, sichere Fehler,
Authentifizierung und persistente Auswahl. Planner besitzt 38 eigene Tests.
Gesamtsuite: 532 bestanden, 1 übersprungen, 106 Subtests bestanden.
TypeScript und Vite-Build erfolgreich.

Ein Live-Test von Gemini/Grok benötigt deren echte Schlüssel und API-Guthaben;
die Tests verwenden ausschließlich Fake-Schlüssel und MockTransport. Die
Browser-Smoke-Prüfung ist in `tests/check_provider_ui.py` vorbereitet, konnte
in dieser Sitzung jedoch wegen einer hängenden Browserinitialisierung nicht
abgeschlossen werden. Sie darf nicht als bestanden gewertet werden.

## Windows-Start

Jarvis läuft direkt aus dem Quellcode (Electron mit dem Rust-Backend als WebAssembly). Es gibt
keine eigene, unsignierte EXE mehr, die Smart App Control blockieren könnte.

## Offizielle Quellen

- [OpenAI Streaming](https://developers.openai.com/api/docs/guides/streaming-responses)
- [Gemini: OpenAI-Kompatibilität, Streaming, Bilder und strukturierte Ausgaben](https://ai.google.dev/gemini-api/docs/openai)
- [Grok: strukturierte Ausgaben](https://docs.x.ai/developers/model-capabilities/text/structured-outputs)
- [Grok-Modelle](https://docs.x.ai/developers/models)
- [Ollama Cloud API](https://docs.ollama.com/cloud) und [OpenAI-Kompatibilität](https://docs.ollama.com/api/openai-compatibility)
