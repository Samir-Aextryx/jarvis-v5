"""
JARVIS Atlassian Access — Confluence & Jira Tickets.

STRICTLY READ-ONLY ACCESS:
By design and security requirement, this module ONLY reads tickets and Confluence pages.
No reply, comment, create, update, or delete operations exist or are permitted.
"""

import asyncio
import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

log = logging.getLogger("jarvis.atlassian")


def _find_twg_binary() -> Optional[str]:
    """Find the twg executable on the system."""
    # 1. PATH lookup
    found = shutil.which("twg")
    if found and Path(found).exists():
        return found

    # 2. Standard Windows install path
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        default_path = Path(local_app_data) / "Programs" / "twg" / "bin" / "twg.exe"
        if default_path.exists():
            return str(default_path)

    # 3. Unix standard paths
    home = Path.home()
    unix_path = home / ".local" / "bin" / "twg"
    if unix_path.exists():
        return str(unix_path)

    return None


def is_twg_available() -> bool:
    """Check if the twg CLI binary exists."""
    return _find_twg_binary() is not None


def is_authenticated() -> bool:
    """Check if twg credentials exist."""
    app_data = os.environ.get("APPDATA")
    if app_data:
        auth_conf = Path(app_data) / "twg" / "auth.conf"
        if auth_conf.exists() and auth_conf.stat().st_size > 0:
            return True
    unix_conf = Path.home() / ".config" / "twg" / "auth.conf"
    if unix_conf.exists() and unix_conf.stat().st_size > 0:
        return True
    return False


def can_reply_to_tickets() -> bool:
    """Strict read-only safety guard. Always False."""
    return False


def reply_to_ticket(*args, **kwargs):
    """Enforce strict read-only safety policy."""
    raise PermissionError("Replying to or modifying tickets is strictly prohibited by security policy.")


def comment_on_ticket(*args, **kwargs):
    """Enforce strict read-only safety policy."""
    raise PermissionError("Commenting on or modifying tickets is strictly prohibited by security policy.")


def update_ticket(*args, **kwargs):
    """Enforce strict read-only safety policy."""
    raise PermissionError("Updating tickets is strictly prohibited by security policy.")


async def _run_twg_command(args: list[str], timeout: float = 15) -> tuple[int, str, str]:
    """Run a twg CLI command asynchronously."""
    binary = _find_twg_binary()
    if not binary:
        return -1, "", "twg CLI is not installed"

    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            binary, *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        out_str = stdout.decode("utf-8", errors="replace").strip()
        err_str = stderr.decode("utf-8", errors="replace").strip()
        return proc.returncode, out_str, err_str
    except asyncio.TimeoutError:
        log.warning(f"twg command timed out: twg {' '.join(args)}")
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass
        return -2, "", "Command timed out"
    except Exception as e:
        log.warning(f"twg execution failed: {e}")
        return -3, "", str(e)


def is_atlassian_ready() -> bool:
    """Check whether twg is installed and ready."""
    return is_twg_available()


async def get_recent_tickets(limit: int = 5) -> list[dict]:
    """Fetch recent/active Jira tickets in read-only mode."""
    if not is_twg_available():
        log.debug("twg CLI not found for get_recent_tickets")
        return []

    # Attempt 1: context jira workitem or jira query
    code, stdout, stderr = await _run_twg_command(["context", "jira", "workitem"])
    if code != 0 or not stdout:
        code, stdout, stderr = await _run_twg_command(["jira", "query", "--limit", str(limit)])

    if code != 0 or not stdout:
        log.debug(f"twg tickets query returned code {code}: {stderr}")
        return []

    tickets = []
    # Parse JSON envelope if available
    try:
        data = json.loads(stdout)
        items = data if isinstance(data, list) else data.get("items", data.get("issues", data.get("workitems", [])))
        for item in items[:limit]:
            if isinstance(item, dict):
                tickets.append({
                    "id": item.get("key", item.get("id", "Ticket")),
                    "title": item.get("summary", item.get("title", "Untitled Ticket")),
                    "status": item.get("status", item.get("state", "Open")),
                    "priority": item.get("priority", "Normal"),
                    "assignee": item.get("assignee", "Unassigned"),
                    "updated": item.get("updated", ""),
                })
    except json.JSONDecodeError:
        # Parse plain text lines
        for line in stdout.splitlines()[:limit]:
            line = line.strip()
            if line and not line.startswith(("#", "---", "===")):
                tickets.append({
                    "id": line.split()[0] if " " in line else "Ticket",
                    "title": line,
                    "status": "Active",
                    "priority": "Normal",
                    "assignee": "User",
                    "updated": "",
                })

    return tickets


async def get_confluence_updates(limit: int = 5) -> list[dict]:
    """Fetch recently updated Confluence pages in read-only mode."""
    if not is_twg_available():
        return []

    code, stdout, stderr = await _run_twg_command(["context", "confluence", "page"])
    if code != 0 or not stdout:
        code, stdout, stderr = await _run_twg_command(["confluence", "query", "--limit", str(limit)])

    if code != 0 or not stdout:
        return []

    pages = []
    try:
        data = json.loads(stdout)
        items = data if isinstance(data, list) else data.get("items", data.get("pages", []))
        for item in items[:limit]:
            if isinstance(item, dict):
                pages.append({
                    "id": item.get("id", ""),
                    "title": item.get("title", "Untitled Page"),
                    "space": item.get("space", item.get("spaceKey", "General")),
                    "updated": item.get("updated", ""),
                    "url": item.get("url", ""),
                })
    except json.JSONDecodeError:
        for line in stdout.splitlines()[:limit]:
            line = line.strip()
            if line and not line.startswith(("#", "---", "===")):
                pages.append({
                    "id": "",
                    "title": line,
                    "space": "Confluence",
                    "updated": "",
                    "url": "",
                })

    return pages


def format_tickets_for_voice(tickets: list[dict], confluence_pages: list[dict] = None) -> str:
    """Format a speech-friendly summary of recent tickets and Confluence pages."""
    parts = []

    if not is_twg_available():
        return "The Atlassian Teamwork Graph tool is not installed on this system, sir."

    if not is_authenticated() and not tickets:
        return "Atlassian is installed, sir, but you are not logged in yet. Please run 'twg login' to connect your Confluence and Jira account."

    if not tickets:
        parts.append("There are no active or new tickets on record at the moment, sir.")
    else:
        count = len(tickets)
        if count == 1:
            t = tickets[0]
            parts.append(f"You have one active ticket, sir: {t['id']}, '{t['title']}' in {t['status']}.")
        else:
            summaries = [f"{t['id']}, '{t['title']}' in {t['status']}" for t in tickets[:3]]
            joined = "; ".join(summaries)
            parts.append(f"You have {count} active tickets, sir: {joined}.")
            if count > 3:
                parts.append(f"Plus {count - 3} additional tickets.")

    if confluence_pages:
        c_count = len(confluence_pages)
        c_titles = [f"'{p['title']}'" for p in confluence_pages[:2]]
        c_joined = " and ".join(c_titles)
        parts.append(f"In Confluence, {c_count} page{'s' if c_count != 1 else ''} were recently updated, including {c_joined}.")

    # Remind user of read-only policy if asked
    return " ".join(parts)


def format_tickets_for_context(tickets: list[dict], confluence_pages: list[dict] = None) -> str:
    """Format tickets and Confluence pages for LLM context injection."""
    lines = []
    if tickets:
        lines.append("ACTIVE JIRA TICKETS:")
        for t in tickets:
            lines.append(f"  - [{t.get('id', 'Ticket')}] {t.get('title', '')} (Status: {t.get('status', 'Open')}, Priority: {t.get('priority', 'Normal')})")
    else:
        lines.append("ACTIVE JIRA TICKETS:\n  No active tickets found.")

    if confluence_pages:
        lines.append("\nRECENT CONFLUENCE PAGES:")
        for p in confluence_pages:
            lines.append(f"  - [{p.get('space', 'Space')}] {p.get('title', '')}")

    lines.append("\nNOTE: Ticket interaction is STRICTLY READ-ONLY. You cannot reply to, comment on, edit, or close tickets.")
    return "\n".join(lines)
