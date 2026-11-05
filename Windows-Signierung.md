# Jarvis v5: Windows-Startblockade und Signierung

## Befund vom 7. Oktober 2026

Smart App Control blockiert die installierte `Jarvis v5.exe` wegen des nicht
verifizierbaren Herausgebers. Die App und `resources/backend/jarvis-server.exe`
sind unsigniert. In den persönlichen Windows-Zertifikatsspeichern wurde kein
Code-Signing-Zertifikat gefunden; SignTool ist nicht eingerichtet.
Ein weiterer unsignierter Build behebt die Blockade nicht.
Die vollständige Prüfung der installierten Version erfasste **129 Binärdateien**:
74 mit gültiger Signatur und 55 ohne gültige Signatur.

## Was vorbereitet ist

- `scripts/check-windows-signatures.ps1`: Prüfung beider Einstiegspunkte;
  mit `-IncludeDependencies` auch EXE, DLL, PYD und native Node-Module.
  Ungültige/fehlende Signaturen ergeben Exit-Code 1.
- `scripts/sign-windows-release.ps1`: Standardmäßig ausschließlich ein
  lesender Paketplan. Nur mit `-Execute` entsteht eine **neue Kopie**. Der
  Quellordner und die installierte App werden nicht verändert.
- Der Ablauf prüft Zertifikat, privaten Schlüssel, Code-Signing-Verwendungszweck,
  Gültigkeit, Zertifikatskette und Microsoft-Signatur von SignTool. Er signiert
  unsignierte Binärdateien mit SHA256 und RFC3161-Zeitstempel und prüft danach
  jede Signatur. Gültige Herstellersignaturen bleiben erhalten. Beschädigte
  oder nicht vertrauenswürdige bestehende Signaturen führen zum Abbruch.
- Ein Manifest enthält die ursprünglichen und signierten Datei-Hashes. Bei
  Abbruch bleibt die Kopie zur Diagnose erhalten. Nur vollständig geprüfte
  Kopien erhalten `Verified: true`; das ist kein Beweis für SAC-Zulassung.
- Private Zertifikatsdateien sind in `.gitignore` ausgeschlossen.

## Was noch fehlt

Ein Zertifikat eines vertrauenswürdigen Code-Signing-Anbieters oder ein
eingerichteter Microsoft-Artifact-Signing-Zugang mit geprüfter Identität.
Der lokale Zertifikatsablauf unten unterstützt Zertifikate im Windows-My-Speicher
mit zugänglichem privaten Schlüssel. Artifact Signing benötigt seinen eigenen
Dienst- und Signierungsclient; er ist durch dieses Skript noch nicht integriert.
Ein lokales Zertifikat oder eine selbst importierte Vertrauenswurzel ersetzt
keinen anerkannten Herausgeber für Smart App Control.

Zusätzlich benötigt der lokale Ablauf die SignTool-Komponente des Windows SDK.
Das SDK wurde ohne vorhandenes Zertifikat nicht vorsorglich installiert.
Das Skript verlangt explizit den Zertifikat-Fingerabdruck; PFX-Passwörter
werden nicht als Befehlszeilenparameter verarbeitet.

## Anwendung nach Einrichtung des Zertifikats

Aus dem Projektordner, zuerst nur den Plan prüfen. Als Quelle möglichst ein
sauberes Build-Paket verwenden, **keinen App-Ordner mit persönlichen Daten**:

```powershell
.\scripts\sign-windows-release.ps1 -ApplicationRoot '.\release-v5\win-unpacked'
```

Erst nachdem Zertifikat und SDK bereitstehen (Platzhalter ersetzen):

```powershell
.\scripts\sign-windows-release.ps1 `
  -ApplicationRoot '.\release-v5\win-unpacked' `
  -OutputRoot '.\signed-releases\jarvis-v5-20261007' `
  -CertificateThumbprint '<40-stelliger Fingerabdruck>' `
  -SignToolPath '<Windows-SDK-Pfad>\x64\signtool.exe' `
  -Execute

.\scripts\check-windows-signatures.ps1 `
  -ApplicationRoot '.\signed-releases\jarvis-v5-20261007' `
  -IncludeDependencies
```

Danach das **komplette Paket unter aktivem Smart App Control testen**, inklusive
Backend-Start und Laden nativer Abhängigkeiten. Keine automatische Installation
oder Änderung an SAC, Defender oder Zertifikats-Vertrauensankern wird vorgenommen.
Die Zertifikatskettenprüfung nutzt den Windows-Vertrauensspeicher; auch eine
gültige lokale Kette garantiert noch keine Zulassung durch Smart App Control.

## Prüfung in dieser Sitzung

Die acht Regressionstests für lesenden Standardbetrieb, fehlendes/unbekanntes
Zertifikat, bestehende/überlappende Ausgabepfade, fehlenden Backend-Einstiegspunkt,
Signaturprüfung und unveränderte Quelldateien sind bestanden.
Der lesende Plan wurde auch am installierten Paket erfolgreich ausgeführt;
die vollständige Signaturprüfung meldet erwartungsgemäß Exit-Code 1.
Ein Konflikt bei der PowerShell-Modulsuche wurde durch das explizite Laden
des zum jeweiligen PowerShell-Host gehörenden Sicherheitsmoduls behoben.
Eine echte Signierung und ein erfolgreicher
SAC-App-Start sind ohne Zertifikat **nicht verifiziert**.

## Offizielle Quellen

- [Microsoft: Signieren für Smart App Control](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/code-signing-for-smart-app-control)
- [Microsoft: SignTool und SHA256-/Zeitstempeloptionen](https://learn.microsoft.com/en-us/windows/win32/seccrypto/signtool)
