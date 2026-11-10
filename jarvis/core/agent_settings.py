"""Small, local, non-secret agent preferences and content-free activity history."""
import json
import copy
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from jarvis.core.runtime_paths import DATA_ROOT
from jarvis.integrations.llm_providers import PROVIDERS, PROVIDER_CHOICE_ERROR, provider_config, validate_model

DEFAULTS = {'work_apps': ['Outlook', 'Microsoft Teams', 'Google Chrome', 'ChatGPT'],
            'fallback': True, 'automation': True, 'activity_log': True,
            'large_model': os.getenv('OPENAI_MODEL', 'gpt-6-luna'),
            'llm_provider': os.getenv('LLM_PROVIDER', 'openai'),
            'gemini_model': os.getenv('GEMINI_MODEL', PROVIDERS['gemini'].default_model),
            'grok_model': os.getenv('GROK_MODEL', PROVIDERS['grok'].default_model),
            'ollama_model': os.getenv('OLLAMA_MODEL', PROVIDERS['ollama'].default_model),
            'reasoning_effort': os.getenv('OPENAI_REASONING_EFFORT', 'low'),
            'default_email': 'Gmail'}


class AgentSettings:
    def __init__(self, root=DATA_ROOT):
        self.path = Path(root) / 'agent-settings.json'
        self.log_path = Path(root) / 'data/agent-activity.json'
        self.lock = threading.RLock()

    def get(self):
        with self.lock:
            try:
                data = json.loads(self.path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                data = {}
            values = copy.deepcopy(DEFAULTS)
            if isinstance(data, dict):
                for key, value in data.items():
                    try:
                        values.update(self._validated({key: value}))
                    except ValueError:
                        continue
            return values

    @staticmethod
    def _validated(data):
        if not isinstance(data, dict) or set(data) - set(DEFAULTS):
            raise ValueError('Unknown agent setting.')
        if 'work_apps' in data:
            apps = data['work_apps']
            if not isinstance(apps, list) or len(apps) > 20 or any(not isinstance(a, str) or not re.fullmatch(r'[\w .()+-]{1,80}', a.strip()) for a in apps):
                raise ValueError('Enter up to 20 installed app names, one per line.')
            data = dict(data, work_apps=list(dict.fromkeys(a.strip() for a in apps)))
        for name in ('fallback', 'automation', 'activity_log'):
            if name in data and type(data[name]) is not bool:
                raise ValueError('Use a checkbox for this setting.')
        if 'large_model' in data and (not isinstance(data['large_model'], str) or not re.fullmatch(r'[a-zA-Z0-9._-]{1,80}', data['large_model'])):
            raise ValueError('Enter a valid model identifier.')
        if 'llm_provider' in data:
            if not isinstance(data['llm_provider'], str) or data['llm_provider'] not in PROVIDERS:
                raise ValueError(PROVIDER_CHOICE_ERROR)
        for name in ('gemini_model', 'grok_model', 'ollama_model'):
            if name in data:
                validate_model(data[name])
        if 'reasoning_effort' in data and data['reasoning_effort'] not in {'none', 'low', 'medium', 'high', 'xhigh', 'max'}:
            raise ValueError('Choose a supported reasoning effort.')
        if data.get('default_email', 'Gmail') not in ('Gmail', 'Outlook'):
            raise ValueError('Choose Gmail or Outlook.')
        return data

    def save(self, data):
        with self.lock:
            values = self.get()
            data = self._validated(data)
            values.update(data)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix('.tmp')
            temp.write_text(json.dumps(values, indent=2), encoding='utf-8')
            os.replace(temp, self.path)
            return values

    def activity(self, tool, success, count=0):
        # Deliberately accept fixed tool names and counts, never requests or results.
        if tool not in {'apps.open', 'personal.update', 'jev.route', 'workflow'} or not self.get()['activity_log']:
            return
        with self.lock:
            rows = self.logs()
            rows.append({'time': datetime.now(timezone.utc).isoformat(), 'tool': tool,
                         'success': bool(success), 'count': int(count)})
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._write_logs(rows[-200:])

    def logs(self):
        with self.lock:
            try:
                rows = json.loads(self.log_path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                return []
            if not isinstance(rows, list):
                return []
            return [row for row in rows[-200:] if isinstance(row, dict)
                    and set(row) == {'time', 'tool', 'success', 'count'}
                    and isinstance(row['time'], str)
                    and row['tool'] in ('apps.open', 'personal.update', 'jev.route', 'workflow')
                    and type(row['success']) is bool and type(row['count']) is int]

    def _write_logs(self, rows):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.log_path.with_suffix('.tmp')
        temp.write_text(json.dumps(rows), encoding='utf-8')
        os.replace(temp, self.log_path)

    def clear_logs(self):
        with self.lock:
            self._write_logs([])


agent_settings = AgentSettings()
