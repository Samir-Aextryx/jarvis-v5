# Tokenverbrauch reduzieren

- Der an das Sprachmodell gesendete Verlauf umfasst höchstens vier vorherige Nachrichten mit je maximal 800 Zeichen und insgesamt höchstens 3.800 Zeichen inklusive der aktuellen Anfrage (`jarvis/voice/voice_context.py`). Die aktuelle Anfrage bleibt immer vollständig, auch wenn sie allein das Budget überschreitet. Die gespeicherten Originalnachrichten werden nicht gekürzt.
- Der laufende Verlauf im WebSocket bleibt auf 100 Einträge begrenzt. Die rollende Zusammenfassung übernimmt ältere Nachrichten in Blöcken von höchstens 20, sobald mindestens fünf neue Beiträge vorliegen; die letzten 20 Nachrichten bleiben unzusammengefasst. Nach einem Fehler bleibt der bisherige Stand erhalten und der Abschnitt wird später erneut versucht.
- Die automatische Extraktion persoenlicher Erinnerungen ueberspringt Nachrichten ohne deutsche oder englische Hinweise auf einen persoenlichen Bezug oder einen ausdruecklichen Speicherwunsch. Alle Gespraechsbeitraege werden weiterhin lokal gespeichert. Implizite persoenliche Aussagen ohne diese Hinweise koennen bei der automatischen Extraktion uebersehen werden; mit „Merke dir …“ laesst sie sich ausdruecklich anfordern.

Das Kontextbudget zaehlt Zeichen, keine exakten Tokens. Modell, Systemanweisungen und Antwortlimit bleiben unveraendert. Die tatsaechliche Tokenersparnis haengt vom Gespraech ab und wurde nicht mit kostenpflichtigen API-Aufrufen gemessen.

Lokale Regressionstests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_token_efficiency.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_personal_memory.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_streaming_voice.py
```
