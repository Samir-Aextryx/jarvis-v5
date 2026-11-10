"""Voice tasks for the local calendar; explicit Google requests keep their route."""
import asyncio
import copy
from datetime import datetime, timedelta
import json
import re
from zoneinfo import ZoneInfo
from jarvis.integrations.calendar_workflows import SCHEMA, SYSTEM, ZONE, operation_allowed
from jarvis.integrations.llm_client import LLMClient
from jarvis.core.local_calendar import local_calendar
from jarvis.automation.pc_fastpath import normalize_request

DELETE = r'delete|remove|cancel|l[oö]sche|entferne'


def personal_panel_request(text):
    text = normalize_request(text).strip(' .!?')
    if re.fullmatch(r'(?i)(?:open|show|[oö]ffne|zeige)\s+(?:(?:my|your|the|mein(?:en)?|dein(?:en)?|den|das)\s+)?(?:(?:jarvis|custom|local|lokalen?|eigenen?)\s+)?(?:calendar|kalender)', text):
        return 'calendar'
    if re.fullmatch(r'(?i)(?:open|show|[oö]ffne|zeige)\s+(?:(?:my|your|the|mein(?:en)?|dein(?:en)?|den|das)\s+)?(?:(?:jarvis|custom|local|lokales?|eigenes?)\s+)?(?:memory|memories|ged[aä]chtnis|erinnerungen)', text):
        return 'memory'
    return None


def is_local_delete(text):
    if re.search(r"(?i)do not (?:delete|remove|cancel)|don.t (?:delete|remove|cancel)|never (?:delete|remove|cancel)|nicht (?:l[oö]schen|entfernen|absagen)|(?:l[oö]sche|entferne).*\bnicht\b", text):
        return False
    return bool(re.match(r'(?i)^(?:'+DELETE+r')\b', normalize_request(text)) and
                re.search(r'(?i)\b(calendar|kalender|event|appointment|meeting|termin)\b', text) and
                not re.search(r'(?i)\bgoogle\b', text))


def _direct_calendar_read_plan(request, now=None):
    """Build a no-model plan for an unambiguous local calendar date-range read."""
    text = normalize_request(request).strip(' .!?')
    if re.search(r'(?i)\bgoogle\b', text):
        return None
    period = re.compile(
        r'(?i)^(?:'
        r'(?:show|list|check|read)\s+(?:(?:me|my|the|mein(?:e|en|em|er)?|den|dem|der)\s+){0,2}'
        r'|what(?:\'s| is)\s+on\s+(?:(?:my|the)\s+)?'
        r'|(?:zeige?|liste|lese?|pr[uü]fe)\s+(?:(?:mir|meinen|meine|meinem|den|dem|der)\s+){0,2}'
        r'|was\s+(?:steht|ist)\s+(?:in|auf)\s+(?:(?:meinem|meine|dem|der)\s+)?'
        r')(?:jarvis\s+|local\s+|custom\s+)?(?:calendar|kalender)\s+'
        r'(?:(?:for|on|during|am|f[uü]r)\s+)?'
        r'(?:(?:the|die)\s+)?'
        r'(?P<range>today|tomorrow|this\s+week|next\s+week|next\s+(?:7|seven)\s+days|'
        r'heute|morgen|diese\s+woche|n[aä]chste\s+woche)$'
    ).fullmatch(text)
    if not period:
        return None

    current = now or datetime.now(ZoneInfo(ZONE))
    today = current.astimezone(ZoneInfo(ZONE)).date()
    selected = re.sub(r'\s+', ' ', period['range'].casefold())
    if selected in {'today', 'heute'}:
        start = today
        end = start + timedelta(days=1)
    elif selected in {'tomorrow', 'morgen'}:
        start = today + timedelta(days=1)
        end = start + timedelta(days=1)
    elif selected in {'this week', 'diese woche'}:
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=7)
    elif selected == 'next week' or selected == 'nächste woche':
        start = today - timedelta(days=today.weekday()) + timedelta(days=7)
        end = start + timedelta(days=7)
    else:
        start = today
        end = today + timedelta(days=7)

    return {
        'operation': 'read', 'all_day': False, 'title': '', 'description': '',
        'location': '', 'start': '', 'end': '', 'query': '',
        'window_start': start.isoformat(), 'window_end': end.isoformat(),
    }


async def run_local_calendar(request, store=None, plan=None):
    store = store or local_calendar
    try:
        if plan is None:
            plan = _direct_calendar_read_plan(request)
        if plan is None:
            schema = copy.deepcopy(SCHEMA)
            schema['properties']['operation']['enum'].append('delete')
            system = SYSTEM.replace('Google Calendar', 'local Jarvis Calendar').replace('primary calendar only', 'local Jarvis calendar only')
            system = system.replace(' or deletion', '') + '''
Deletion of an individual LOCAL event is supported when explicitly requested. For delete use query=EXACT event title and window_start/window_end bounding its existing date; ask if missing. Do not invent an ID. No Google account is needed. For update preserve unchanged description/location; only include requested changes. For read return the requested date range. Default to today for a request for today's schedule; do not create events from vague times.'''
            response = await LLMClient().create(system=system, max_tokens=1200, json_schema=schema,
                messages=[{'role':'user','content':json.dumps({'request':request,'now':datetime.now(ZoneInfo(ZONE)).isoformat(),'timezone':ZONE})}])
            plan = json.loads(response.content[0].text)
        operation = plan.get('operation')
        if operation == 'ask':
            return {'ok':False,'needs_input':True,'message':plan.get('question') or 'Which event and date do you mean?'}
        if operation not in {'read','create','update','delete'}:
            raise ValueError('Unsupported local calendar action.')
        if operation in {'create','update'} and not operation_allowed(request, operation):
            raise ValueError('Please explicitly ask me to create or change the event.')
        if operation == 'delete' and not is_local_delete(request):
            raise ValueError('Please explicitly ask me to delete the event.')
        if operation == 'create':
            event = await asyncio.to_thread(store.save, plan)
        else:
            rows = await asyncio.to_thread(store.list_events, plan.get('window_start',''), plan.get('window_end',''))
            query = plan.get('query','').strip()
            if operation == 'read':
                if re.search(r'(?i)\b(free|available|availability|frei)\b',request):
                    return {'ok':True,'message':('No events overlap the requested time in your Jarvis calendar.' if not rows else 'You have overlapping events: '+json.dumps(rows,ensure_ascii=False))+' Other calendars were not checked.'}
                if query:
                    rows = [row for row in rows if query.casefold() in (row['title']+' '+row['description']).casefold()]
                return {'ok':True,'message':'Your Jarvis calendar: '+json.dumps(rows,ensure_ascii=False)}
            matches = [row for row in rows if row['title'].casefold() == query.casefold()]
            if not query or len(matches) != 1:
                raise ValueError('Please give the exact event title and date so I can identify one event.')
            old = matches[0]
            if operation == 'delete':
                await asyncio.to_thread(store.delete, old['id'], old['version'])
                return {'ok':True,'message':f"Deleted {old['title']} from your Jarvis calendar."}
            data = dict(plan)
            for key in ('title','description','location'):
                data[key] = data.get(key) or old[key]
            event = await asyncio.to_thread(store.save, data, old['id'], old['version'])
        return {'ok':True,'message':f"{'Created' if operation == 'create' else 'Updated'} {event['title']} in your Jarvis calendar, {event['start']} to {event['end']}."}
    except (ValueError, TypeError, KeyError) as exc:
        return {'ok':False,'needs_input':True,'message':str(exc) if isinstance(exc,ValueError) else 'Please give a valid event title, date and time.'}
