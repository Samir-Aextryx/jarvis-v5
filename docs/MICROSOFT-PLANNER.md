# Microsoft Planner: ausschließlich lesen

`jarvis/integrations/microsoft_planner.py` stellt `PlannerConfig` und
`PlannerClient` bereit. `microsoft_graph_auth.py` übernimmt den Client-Credentials-
Flow, Fehlerklassen und den threadsicheren Token-Cache. Benötigte Pakete `httpx`
und `python-dotenv` sind bereits in `requirements.txt` enthalten.

## Einrichtung

1. In Microsoft Entra eine Anwendung im angegebenen Tenant registrieren.
2. Microsoft Graph → **Application permissions → Tasks.Read.All** hinzufügen
   und vom zuständigen Administrator freigeben lassen. Keine Schreibberechtigung
   für diese Anbindung hinzufügen. Diese Berechtigung ist tenantweit; die
   `PLAN_ID` beschränkt die normalen Modulabfragen, nicht die Entra-Berechtigung.
3. Client-ID und den **Wert** des Client-Secrets (nicht dessen Secret-ID) in eine
   lokale `.env` eintragen. Bestehende Jarvis-Einstellungen beibehalten:

```dotenv
TENANT_ID=74fa0cbc-cc38-4b2b-88f1-f0ae09ff9697
PLAN_ID=oInDxGoKskmRXtehkXpj4ZYAEqvn
CLIENT_ID=<UUID der Entra-Anwendung>
CLIENT_SECRET=<Secret-Wert>
```

Die Vorlage liegt in `.env.example`. Echte Secrets sind dort niemals einzutragen;
lokale `.env`-Dateien werden von Git ignoriert. Konfiguration wird nur geladen,
wenn sie ausdrücklich angefordert wird. Bestehende Umgebungsvariablen haben
Vorrang vor der gewählten `.env`.

Das Client-Secret gehört in den Windows Credential Manager. Beim nächsten
Serverstart verschiebt Jarvis `CLIENT_SECRET` aus `.env` dorthin und ersetzt die
Zeile durch einen Kommentar; `PlannerConfig.from_env()` liest das Secret dann aus
dem Vault, sofern weder Umgebung noch `.env` eines liefern. Für den einmaligen
CLI-Lauf vor dem ersten Serverstart funktioniert `.env` weiterhin unverändert.

## Ausführen und verwenden

Vom Projektverzeichnis mit der virtuellen Umgebung ausführen:

```powershell
.\.venv\Scripts\python.exe -m jarvis.integrations.microsoft_planner --env-file .env
```

Eine JSON-Zusammenfassung wird ausgegeben. Fehler liefern eine sichere
JSON-Fehlermeldung und Exit-Code 1, ohne Token oder Secret. Die Ausgabe enthält
Aufgabenbeschreibungen; deshalb nicht unkontrolliert in öffentliche Logs schreiben.

```python
from jarvis.integrations.microsoft_planner import PlannerClient, PlannerConfig

with PlannerClient(PlannerConfig.from_env('.env')) as planner:
    buckets = planner.get_buckets()
    tasks = planner.get_tasks()
    if tasks:
        details = planner.get_task_details(tasks[0]['id'])
    context = planner.get_board_summary()
```

In Jarvis-Async-Handlern den synchronen Netzwerkzugriff auslagern und einen
Client für mehrere Abfragen wiederverwenden:

```python
import asyncio

with PlannerClient(PlannerConfig.from_env('.env')) as planner:
    summary = await asyncio.to_thread(planner.get_board_summary)
```

Eine automatische Registrierung als Sprachbefehl oder ein neuer REST-Endpunkt
ist nicht Bestandteil dieses eigenständigen Moduls. Es verändert keine
bestehenden Mail-, Kalender- oder Aufgabenfunktionen.

## Struktur des Kontexts

```json
{
  "plan_id": "oInDxGoKskmRXtehkXpj4ZYAEqvn",
  "fetched_at": "2026-10-07T12:00:00+00:00",
  "read_only": true,
  "content_is_untrusted": true,
  "task_count": 1,
  "buckets": [{"id": "bucket-1", "name": "Meetings"}],
  "tasks": [{
    "id": "task-1",
    "title": "Meeting vorbereiten",
    "status": "in_progress",
    "percent_complete": 50,
    "due_date_time": "2026-10-08T09:00:00Z",
    "start_date_time": null,
    "bucket_id": "bucket-1",
    "bucket_name": "Meetings",
    "assignments": [{"user_id": "user-1", "assigned_date_time": null}],
    "description": "Agenda mitnehmen",
    "checklist": {
      "total": 1, "completed": 1,
      "items": [{"id": "item-1", "title": "Agenda", "is_checked": true}]
    }
  }]
}
```

Zuweisungen enthalten Nutzer-IDs. Es erfolgt kein zusätzlicher Benutzerabruf,
sodass keine `User.Read.All`-Berechtigung benötigt wird. Aufgabeninhalte bleiben
Daten und dürfen niemals als Systemanweisungen an Jarvis übergeben werden.

## Fehler und Grenzen

- Graph-Aufrufe verwenden ausschließlich GET für Buckets, Tasks und Details.
  Der separate OAuth-Token-Abruf verwendet zwingend POST am Identity-Endpunkt;
  er erstellt oder verändert keine Planner-Daten.
- Der Token bleibt im Arbeitsspeicher und wird mit Ablaufreserve wiederverwendet.
  Gleichzeitige Aufrufe teilen einen Refresh. Nach einem 401 erfolgt höchstens
  ein Token-Refresh; ein erneuter 401 ergibt `PlannerAuthenticationError`.
- 403 ergibt `PlannerPermissionError` mit Hinweis auf Berechtigung und Consent;
  404 ergibt `PlannerNotFoundError`. Ein ungültiges/abgelaufenes Secret ergibt
  `PlannerAuthenticationError`. Secret-Rotation erfolgt über den Credential
  Manager (oder `.env` vor dem ersten Start) und einen neuen Client; es werden
  keine Tokens auf Platte gespeichert.
- 429 respektiert `Retry-After` (Sekunden oder HTTP-Datum). Netzwerkfehler und
  502/503/504 erhalten begrenzte Wiederholungen. Standard: zwei Wiederholungen,
  maximal 30 Sekunden Wartezeit je Wiederholung, 30 Sekunden Netzwerk-Timeout.
  Ein längeres `Retry-After` wird als Fehler mit `retry_after` zurückgegeben,
  statt verfrüht erneut anzufragen oder unbegrenzt zu blockieren.
- Pagination erlaubt ausschließlich HTTPS, den exakten Graph-Host und den
  ursprünglichen Ressourcenpfad. Weiterleitungen werden nicht verfolgt. Zyklen,
  ungültige Antworten und überschrittene Seitengrenzen ergeben explizite Fehler.
- Details werden pro Aufgabe gelesen. Große Boards benötigen entsprechend
  viele GETs. Bei einem Detailfehler gibt es keine scheinbar vollständige
  Zusammenfassung. Separate GETs bilden keinen atomaren Snapshot: Änderungen
  am Board während des Abrufs können zu einem gemischten Stand führen.
- Graph Planner unterstützt nur die durch diese API bereitgestellten Pläne;
  Premium-/Dataverse-Pläne müssen gesondert geprüft werden.

## Prüfung

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_microsoft_planner.py -q
```

Die Tests verwenden `httpx.MockTransport`. Sie prüfen echte Client-Aufrufe,
GET-only-Verhalten, Token-Wiederverwendung/-Ablauf/-Parallelität, 401/403/404,
Rate-Limits, Netzwerkfehler, Pagination, Secret-Schutz und den Board-Kontext.
Ein Live-Test benötigt die echten Entra-Anwendungsdaten und Admin-Consent.

## Offizielle Referenzen

- [Plan-Aufgaben und Application-Permission Tasks.Read.All](https://learn.microsoft.com/en-us/graph/api/plannerplan-list-tasks?view=graph-rest-1.0)
- [Buckets eines Plans](https://learn.microsoft.com/en-us/graph/api/plannerplan-list-buckets?view=graph-rest-1.0)
- [Aufgabendetails](https://learn.microsoft.com/en-us/graph/api/plannertaskdetails-get?view=graph-rest-1.0)
- [Client Credentials und .default](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-client-creds-grant-flow)
- [Microsoft Graph Throttling](https://learn.microsoft.com/en-us/graph/throttling)
