# Gedächtnis und Kalender – 21. September 2026

## Umsetzung

- Eigene Ansichten für Erinnerungen und Kalender, erreichbar über Menü, Einstellungen und `Open my memory` / `Open my calendar`.
- Erinnerungen suchen, erstellen, bearbeiten und löschen; manuelle Einträge haben Vorrang vor automatischem Lernen. Routinen lassen sich erstellen und aktualisieren.
- Lokaler Kalender mit Monatsansicht, Tagesliste, ganztägigen Ereignissen, Ort und Notizen. Sprachaktionen verwenden standardmäßig diesen Kalender; ausdrücklich genannte Google-Aufträge bleiben getrennt.
- Persistente SQLite-Daten, Markdown-Export des Gedächtnisses und Versionsprüfung gegen veraltete Bearbeitungen. Schreibtransaktionen reservieren die Datenbank vor der Versionsprüfung.
- Fehler in Menüverknüpfungen und Sprachverarbeitung behoben; Dateioperationen der neuen API-Endpunkte laufen außerhalb der Ereignisschleife.

## Dateien

`personal_memory.py`, `local_calendar.py`, `local_calendar_workflows.py`, `local_pc.py`, `server.py`, `frontend/src/personal-panel.ts`, `frontend/src/main.ts`, `frontend/src/settings.ts`, `frontend/src/style.css`, `frontend/index.html`, `tests/test_custom_personal.py` und `Jarvis-v5-Hilfe.md`.

## Prüfung

54 Tests bestanden: custom_personal, personal_memory, calendar_workflows, app_learning, local_pc, streaming_voice und realtime_stt. TypeScript-Prüfung, Frontend-Build und Backend-Paketierung erfolgreich. Oberfläche mit isolierten Testdaten geprüft: Erinnerung speichern und erneut öffnen, ganztägigen Termin speichern und aktualisierte Ansicht laden. Google-Antworten simuliert; keine echten Google-Termine verändert.

## Installation und verbleibende Grenze

Aktualisierte Dateien nach `%USERPROFILE%\Documents\Jarvis v5` kopiert. Installiertes Backend stimmt per SHA-256 mit dem neuen Build überein. Gedächtnis und Kalenderdatenbanken vorab zusätzlich gesichert; frühere vollständige Sicherung `jarvis v5 backup` erhalten.

Der Neustart der vorhandenen Desktop-EXE wurde von Windows mit „Eine Anwendungssteuerungsrichtlinie hat diese Datei blockiert“ abgelehnt. Die Desktop-EXE wurde bei diesem Update nicht ausgetauscht. Deshalb konnte die installierte App nach dem Update nicht laufend geprüft werden; die Oberfläche wurde im isolierten Entwicklungsserver erfolgreich geprüft. Windows-Schutzfunktionen wurden nicht verändert. Die Freigabe der App muss über die zuständige Windows-Anwendungssteuerung geklärt werden.

Der lokale Kalender hat noch keine Erinnerungsbenachrichtigungen, Serientermine oder automatische Google-Synchronisierung.
