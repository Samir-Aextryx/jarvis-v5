# JARVIS für Windows mit OpenAI

Einrichten: einmalig `powershell -ExecutionPolicy Bypass -File scripts\install.ps1`
(Python-venv, Frontend-Build, Electron, Desktop-Verknüpfung; siehe README).
Start: Desktop-Verknüpfung **Jarvis v5** (Electron + `.venv`) oder
`scripts\Start-JARVIS.cmd` für den Browser-Modus. Der Server lauscht nur auf `127.0.0.1`.
Die Desktop-Shell verwendet Port **8345**, der eigenständige Start **8340**;
der Port lässt sich über `JARVIS_PORT` ändern.

In Settings folgende Werte eintragen, Save Keys anklicken und mit Test prüfen:

- OpenAI API Key: https://platform.openai.com/api-keys
- Fish Audio API Key: https://fish.audio/app/api-keys/
- Fish Voice ID: eigene Stimme aus dem Fish-Audio-Konto (siehe unten)

API-Schlüssel und Stimmen-ID sind verschiedene Werte. Schlüssel werden im
**Windows Credential Manager** gespeichert und nach Save Keys sofort aktiv.
Die `.env` enthält nur nicht-geheime Einstellungen. Schlüssel niemals im Chat
posten oder in Git einchecken. Test erzeugt eine kleine API-Anfrage.

OpenAI-Modell: `OPENAI_MODEL=gpt-6-luna` (Standard), Reasoning-Aufwand `low`.
Andere für dein API-Projekt freigeschaltete Responses-Modelle kannst du in der
`.env` eintragen. Ein ChatGPT-Login ersetzt den API-Schlüssel nicht.
Preisangaben in der App sind Schätzungen; bei Modellwechsel
`OPENAI_INPUT_PRICE` und `OPENAI_OUTPUT_PRICE` (USD pro Million Tokens) anpassen.
Fish-Kosten sind darin nicht enthalten.

Fish-Modell: `FISH_MODEL=s2.1-pro-free`; die Stimme wird über `FISH_VOICE_ID`
in den Einstellungen gewählt. Die Verfügbarkeit einer Community-Stimme hängt
von Fish Audio ab.

Unterstützt: Weboberfläche, Gespräche und Bildanalyse mit OpenAI, Fish-Sprachausgabe,
Windows-Fensterliste und Screenshots, Browser öffnen, PowerShell öffnen, lokale
Aufgaben und Erinnerungen. Die Spracheingabe erkennt Deutsch und Englisch.
Google Chrome verwenden und Mikrofonzugriff erlauben.

Jarvis verwendet sein eigenes lokales Notizbuch, Gedächtnis und seinen Kalender.
Outlook und Google lassen sich separat in den Einstellungen verbinden.
Programmieraufträge laufen über Codex; Gespräche und Bildanalyse verwenden den
konfigurierten OpenAI-Zugang.

Beenden: Fenster schließen oder `scripts\Stop-JARVIS.ps1` ausführen. Startprobleme:
`server.log` im Datenordner lesen (`Documents\Jarvis v5\config` im Desktop-Modus).

## Entwicklung und Validierung

Voraussetzungen: Windows 10/11, Python 3.12, Node.js 22.12+, Google Chrome.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
.venv\Scripts\python.exe -m pytest -q
```

`scripts\check-and-build.ps1` führt Tests, TypeScript-Prüfung, Vite-Build
und den isolierten Smoke-Test `scripts\verify-source.py` aus. Die Anleitung
für die Desktop-App steht in `docs\Jarvis-v5-Hilfe.md`.

Jarvis wird nicht als EXE verpackt: Smart App Control blockiert unsignierte
Programme. Die Desktop-Verknüpfung startet deshalb Stock-Electron mit
`desktop/` und dem venv-Python. Smart App Control nicht ändern.
