"""Explicit local PC commands; no speech text is ever evaluated by a shell."""
import asyncio
import json
import os
from pathlib import Path
import re
import shutil
import string
import subprocess
import time
import threading
import uuid
import winreg

from jarvis.core.runtime_paths import DATA_ROOT


def desktop():
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
        return Path(os.path.expandvars(winreg.QueryValueEx(key, "Desktop")[0]))


def local_path(value):
    aliases = {"desktop": desktop(), "downloads": Path.home() / "Downloads",
               "dokumente": Path.home() / "Documents", "benutzerordner": Path.home()}
    value = value.strip().strip('"')
    path = aliases.get(value.lower(), Path(os.path.expandvars(value)))
    if not path.is_absolute() or str(path).startswith("\\\\") or ":" in str(path)[2:]:
        raise ValueError("Bitte einen lokalen absoluten Pfad wie C:\\Users\\Samir oder Desktop angeben.")
    path = path.resolve(strict=True)
    if str(path).startswith("\\\\"):
        raise ValueError("Netzwerk- und Gerätepfade werden nicht geöffnet.")
    return path


def powershell(script, timeout=30):
    from jarvis.integrations.credentials_vault import child_process_env
    exe = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe")
    result = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-Command",
        "[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); $ErrorActionPreference='Stop'; " + script],
        capture_output=True, encoding="utf-8", errors="replace", timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW, env=child_process_env())
    if result.returncode:
        raise RuntimeError("Windows konnte den Defender-Befehl nicht ausführen. Eventuell fehlen Administratorrechte oder Defender ist nicht verfügbar.")
    return result.stdout.strip()


def defender_status():
    return json.loads(powershell("$s=Get-MpComputerStatus; $t=@(Get-MpThreat | Where-Object IsActive | Select-Object ThreatID,ThreatName); @{enabled=$s.AntivirusEnabled; realtime=$s.RealTimeProtectionEnabled; quickEnd=[string]$s.QuickScanEndTime; fullEnd=[string]$s.FullScanEndTime; threats=$t} | ConvertTo-Json -Depth 5"))


def codex_executable():
    found = shutil.which("codex.exe")
    if found:
        return found
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "OpenAI/Codex/bin"
    candidates = list(base.glob("*/codex.exe"))
    if not candidates:
        raise RuntimeError("Codex ist nicht installiert. Bitte Codex installieren und anmelden.")
    return str(max(candidates, key=lambda p: p.stat().st_mtime))


class PCControl:
    MAX_FINISHED_JOBS = 50

    def __init__(self, root=DATA_ROOT):
        self.root = Path(root)
        self.jobs = {}
        self.tasks = set()
        self._cancels = {}
        self.pending_removal = None

    @staticmethod
    def parse(text):
        text = re.sub(r"(?i)^(?:hey\s+)?jarvis[,\s]+", "", text).strip().rstrip("!?.")
        text = re.sub(r"(?i)^(?:kannst du\s+)?bitte\s+", "", text)
        if re.fullmatch(r"(?i)(?:zeige |prüfe |wie ist (?:der )?)?(?:defender.status|sicherheitsstatus|virenstatus|scanstatus|scan.status)", text):
            return ("security_status", "")
        if re.fullmatch(r"(?i)(?:starte (?:einen |den )?)?(?:virenscan|schnellscan|vollscan|vollständigen virenscan|vollständiger virenscan)", text) or re.fullmatch(r"(?i)(?:scanne|prüfe|untersuche) (?:meinen |den )?(?:ganzen |gesamten )?(?:pc|computer)(?: auf (?:viren|viruse|malware))?", text):
            return ("scan", "FullScan" if re.search(r"(?i)voll|ganz|gesamt", text) else "QuickScan")
        if re.fullmatch(r"(?i)(?:lösche|entferne|bereinige) (?:alle |die )?(?:erkannten |gefundenen )?(?:viren|viruse|bedrohungen|malware)", text):
            return ("remove_prepare", "")
        if text.lower() == "defender bereinigung bestätigen":
            return ("remove_confirm", "")
        if text.lower() in {"codex status", "programmierstatus"}:
            return ("coding_status", "")
        if re.match(r"(?i)^(?:programmiere|entwickle|code)\b|^(?:erstelle|baue|schreibe)\b.*\b(?:app|website|webseite|programm|skript|script|spiel|code)\b|^(?:sende|gib|schicke)\b.*\bcodex\b", text):
            return ("code", text)
        if text.lower() in {"zeige laufwerke", "zeige meine laufwerke", "öffne diesen pc"}:
            return ("drives", "")
        for pattern, action in [(r"(?:öffne|zeige) (?:den |die |das )?(?:ordner|datei) (.+)", "open_path"),
                                (r"(?:zeige|liste) (?:den )?(?:inhalt von|dateien in) (.+)", "list_path"),
                                (r"(?:lies|lese) (?:die )?datei (.+)", "read_path"),
                                (r"(?:suche|finde) (?:die )?datei (.+)", "find_path")]:
            match = re.fullmatch(pattern, text, re.I)
            if match:
                return action, match[1]
        if text.lower() in {"öffne desktop", "öffne downloads", "öffne dokumente"}:
            return "open_path", text.split(" ", 1)[1]
        return None

    def _persist(self, job):
        folder = self.root / "data/pc-jobs"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / (job["id"] + ".json")).write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")

    def _prune_jobs(self):
        """Keep the in-memory list and its JSON files bounded over long runs."""
        finished = sorted(
            (job for job in self.jobs.values()
             if job.get("state") not in {"running", "stopping"}),
            key=lambda job: job.get("started", 0),
        )
        excess = len(finished) - self.MAX_FINISHED_JOBS
        for job in finished[:max(0, excess)]:
            self.jobs.pop(job["id"], None)
            try:
                (self.root / "data/pc-jobs" / (job["id"] + ".json")).unlink(missing_ok=True)
            except OSError:
                pass

    def _start(self, kind, worker, *args):
        if any(j["kind"] == kind and j["state"] in {"running", "stopping"} for j in self.jobs.values()):
            return "Ein solcher Auftrag läuft bereits. Frage nach dem Scanstatus oder Codex Status."
        job = {"id": uuid.uuid4().hex, "kind": kind, "state": "running", "started": time.time()}
        self.jobs[job["id"]] = job
        self._persist(job)
        cancel = threading.Event()
        self._cancels[job["id"]] = cancel
        async def run():
            try:
                if kind == "code":
                    await asyncio.to_thread(worker, job, *args, cancel=cancel)
                else:
                    await asyncio.to_thread(worker, job, *args)
                if cancel.is_set():
                    job.update(state="cancelled", message="Coding task stopped; existing file changes were preserved.")
                else:
                    job["state"] = "done"
            except Exception as exc:
                if cancel.is_set():
                    job.update(state="cancelled", message="Coding task stopped; existing file changes were preserved.")
                else:
                    job.update(state="error", message=str(exc)[:400])
            finally:
                self._cancels.pop(job["id"], None)
                self._persist(job)
                self._prune_jobs()
        task = asyncio.create_task(run())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return "Defender-Prüfung beauftragt. Frage nach dem Scanstatus." if kind == "scan" else "Ich übergebe deinen Auftrag an Codex und öffne die Aufgabe, sobald Codex sie angelegt hat. Frage nach Codex Status."

    def cancel_code(self) -> bool:
        """Signal running Codex jobs to stop their process tree."""
        stopped = False
        for job in self.jobs.values():
            if job.get("kind") == "code" and job.get("state") == "running":
                event = self._cancels.get(job["id"])
                if event is not None:
                    event.set()
                    job["state"] = "stopping"
                    stopped = True
        return stopped

    def _scan(self, job, scan_type):
        powershell("Start-MpScan -ScanType " + scan_type, timeout=86400)
        status = defender_status()
        job["message"] = f"Defender-Prüfung abgeschlossen. Aktive erkannte Bedrohungen: {len(status['threats'])}."

    async def run_code(self, prompt, project=None):
        """Wait for the owned Codex job and propagate Stop to its process tree."""
        if any(j['kind']=='code' and j['state'] in {'running','stopping'} for j in self.jobs.values()):
            raise RuntimeError('Another coding task is still running.')
        job = {'id':uuid.uuid4().hex,'kind':'code','state':'running','started':time.time()}
        self.jobs[job['id']] = job
        self._persist(job)
        cancel = threading.Event()
        worker = asyncio.create_task(asyncio.to_thread(self._code, job, prompt, project, cancel))
        try:
            await asyncio.shield(worker)
            job['state']='done'
            return job['message'] + '\nCodex report (not independent verification): ' + job.get('report','No final report was supplied.')
        except asyncio.CancelledError:
            cancel.set()
            try:
                await asyncio.wait_for(asyncio.shield(worker),8)
            except (Exception,asyncio.CancelledError):
                pass
            job.update(state='cancelled' if worker.done() else 'stopping',message='Coding task stopped; existing file changes were preserved.' if worker.done() else 'Cancellation requested; process shutdown is still pending.')
            # Retrieve any eventual exception if OS shutdown takes longer than expected.
            if not worker.done():
                worker.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
            raise
        except Exception as exc:
            job.update(state='error',message=str(exc)[:400])
            raise
        finally:
            self._persist(job)
            self._prune_jobs()

    def _code(self, job, prompt, project=None, cancel=None):
        if cancel is not None and cancel.is_set():
            raise RuntimeError('Coding task cancelled before launch.')
        exe = codex_executable()
        folder = local_path(project) if project else desktop() / "Jarvis Projekte" / ("Auftrag-" + time.strftime("%Y%m%d-%H%M%S") + "-" + job["id"][:6])
        folder.mkdir(parents=True, exist_ok=True)
        job["folder"] = str(folder)
        (folder / ("JARVIS-AUFTRAG-" + job["id"][:12] + ".md")).write_text(prompt, encoding="utf-8")
        # Prompt travels over stdin, never as executable code or shell arguments.
        from jarvis.integrations.credentials_vault import child_process_env
        env = child_process_env()
        if cancel is not None and cancel.is_set():
            raise RuntimeError("Coding task cancelled before launch.")
        with subprocess.Popen([exe, "exec", "--json", "--sandbox", "workspace-write", "--skip-git-repo-check", "-C", str(folder), "-"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                encoding="utf-8", errors="replace", env=env, creationflags=subprocess.CREATE_NO_WINDOW) as process:
            finished = threading.Event()
            def watch_stop():
                while not finished.wait(0.1):
                    if cancel is not None and cancel.is_set():
                        if process.poll() is None:
                            try:
                                killer = str(Path(os.environ.get('SystemRoot',r'C:\Windows')) / 'System32/taskkill.exe')
                                subprocess.run([killer,'/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5,creationflags=subprocess.CREATE_NO_WINDOW)
                            except (OSError,subprocess.TimeoutExpired):
                                pass
                            if process.poll() is None:
                                process.kill()
                        return
            watcher = threading.Thread(target=watch_stop,daemon=True)
            watcher.start()
            try:
                process.stdin.write(prompt)
                process.stdin.close()
                for line in process.stdout:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if event.get("type") == "thread.started" and re.fullmatch(r"[a-zA-Z0-9-]+", event.get("thread_id", "")):
                        job["thread_id"] = event["thread_id"]
                        try:
                            os.startfile("codex://threads/" + job["thread_id"])
                            job["app_open_requested"] = True
                        except OSError:
                            job["app_open_requested"] = False
                        self._persist(job)
                    if event.get("type") in {"error", "turn.failed"}:
                        job["failure"] = True
                    if event.get("type") == "turn.completed":
                        job['turn_completed'] = True
                    item = event.get('item') or {}
                    if event.get('type') == 'item.completed' and item.get('type') == 'agent_message':
                        job['report'] = re.sub(r'sk-[A-Za-z0-9_-]+','[redacted]',str(item.get('text',''))[:8000])
                if process.wait() != 0 or job.get("failure") or not job.get('turn_completed'):
                    raise RuntimeError("Codex konnte den Auftrag nicht abschließen. Prüfe die geöffnete Codex-Aufgabe und deine Anmeldung.")
            finally:
                finished.set()
                watcher.join(timeout=6)
        report = str(job.get("report", "")).strip()
        job["message"] = ("Codex finished its run. " + report if report
                           else "Codex finished its run; no summary was returned.")
        job["message"] += " Project folder: " + str(folder)

    async def execute(self, command):
        action, value = command
        try:
            if action == "security_status":
                status = await asyncio.to_thread(defender_status)
                running = any(j["kind"] == "scan" and j["state"] == "running" for j in self.jobs.values())
                last = next((j for j in reversed(list(self.jobs.values())) if j["kind"] == "scan"), {})
                return f"Defender: {'aktiv' if status['enabled'] else 'inaktiv'}. Echtzeitschutz: {'aktiv' if status['realtime'] else 'inaktiv'}. Aktive erkannte Bedrohungen: {len(status['threats'])}. " + ("Scan läuft. " if running else last.get("message", "")) + " Letzter Schnellscan: " + (status.get("quickEnd") or "unbekannt")
            if action == "scan":
                return self._start("scan", self._scan, value)
            if action == "remove_prepare":
                status = await asyncio.to_thread(defender_status)
                threats = status["threats"]
                if not threats:
                    self.pending_removal = None
                    return "Defender meldet keine aktiven erkannten Bedrohungen. Es wird nichts gelöscht."
                self.pending_removal = (time.monotonic(), {t["ThreatID"] for t in threats})
                return "Defender meldet: " + ", ".join(t["ThreatName"] for t in threats) + ". Sage: Defender Bereinigung bestätigen. Defender übernimmt dann die Bereinigung dieser aktiven Funde."
            if action == "remove_confirm":
                pending, self.pending_removal = self.pending_removal, None
                if not pending or time.monotonic() - pending[0] > 90:
                    return "Keine aktuelle Bereinigung zur Bestätigung. Sage zuerst: Entferne erkannte Viren."
                status = await asyncio.to_thread(defender_status)
                if {t["ThreatID"] for t in status["threats"]} != pending[1]:
                    return "Die Funde haben sich geändert. Sage erneut: Entferne erkannte Viren."
                await asyncio.to_thread(powershell, "Remove-MpThreat", 120)
                status = await asyncio.to_thread(defender_status)
                return f"Defender-Bereinigung ausgeführt. Noch aktive erkannte Bedrohungen: {len(status['threats'])}."
            if action == "code":
                codex_executable()
                return self._start("code", self._code, value)
            if action == "coding_status":
                from jarvis.voice.speech_language import remember_english
                jobs = [j for j in self.jobs.values() if j["kind"] == "code"]
                if not jobs:
                    return remember_english('No Codex task has been started in this Jarvis session.')
                job = jobs[-1]
                return remember_english(job.get('message','Codex is still working.') + (' The Codex task has been created.' if job.get('thread_id') else ''))
            return await asyncio.to_thread(self._files, action, value)
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            return "Aktion nicht abgeschlossen: " + str(exc)[:400]

    def _files(self, action, value):
        if action == "drives":
            return "Verfügbare Laufwerke: " + ", ".join(c + ":\\" for c in string.ascii_uppercase if Path(c + ":\\").exists())
        if action == "find_path":
            if not value or any(c in value for c in "\\/:"):
                return "Nenne einen Dateinamen ohne Pfad."
            deadline, found, count = time.monotonic() + 8, [], 0
            for drive in string.ascii_uppercase:
                root = Path(drive + ":\\")
                if not root.exists():
                    continue
                for folder, dirs, files in os.walk(root, followlinks=False):
                    dirs[:] = [d for d in dirs if not Path(folder, d).is_junction() and not Path(folder, d).is_symlink()]
                    count += 1
                    found.extend(str(Path(folder, f)) for f in files if value.casefold() in f.casefold())
                    if time.monotonic() >= deadline or count > 100000 or len(found) >= 20:
                        return "Begrenzte Suche, erste Treffer: " + ("; ".join(found[:20]) or "bisher keine. Versuche einen genaueren Ordner.")
            return "Gefunden: " + ("; ".join(found) or "keine zugängliche Datei dieses Namens.")
        path = local_path(value)
        if action == "open_path":
            if not path.is_dir() and path.suffix.lower() not in {".txt", ".md", ".pdf", ".png", ".jpg", ".jpeg", ".docx", ".xlsx", ".pptx", ".csv"}:
                return "Diese Datei ist kein unterstütztes Dokument. Programme bitte über ihren App-Namen öffnen."
            os.startfile(str(path))
            return "Ich öffne " + str(path)
        if action == "list_path":
            if not path.is_dir():
                return "Das ist kein Ordner."
            from itertools import islice
            return "Erste bis zu 50 Einträge: " + "; ".join(p.name + (" (Ordner)" if p.is_dir() else "") for p in islice(path.iterdir(), 50))
        if action == "read_path":
            if path.suffix.lower() not in {".txt", ".md", ".csv", ".py", ".js", ".ts", ".html", ".css"}:
                return "Ich kann hier Textdateien und Quellcode vorlesen."
            with path.open(encoding="utf-8", errors="replace") as stream:
                content = stream.read(4001)
            # Never read common API credentials aloud or pass them to speech synthesis.
            content = re.sub(r"sk-[A-Za-z0-9_-]+", "[API-Schlüssel ausgeblendet]", content)
            return content[:4000] + (" … Datei gekürzt." if len(content) > 4000 else "")
        raise ValueError("Unbekannter PC-Befehl.")


controller = PCControl()
