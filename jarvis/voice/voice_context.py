"""Keep full persistence, select bounded relevant context for one voice turn."""
import re


def relevant_context(text, query, budget=1100):
    words=set(re.findall(r'\w{3,}',query.casefold()))
    lines=[line for line in text.splitlines() if line.strip()]
    if re.search(r'(?i)\b(?:what do you remember about me|what do you know about me|show (?:me )?(?:all )?(?:my )?memories|list (?:all )?(?:my )?memories|was wei(?:ss|ß)t du alles über mich|zeige (?:mir )?(?:alle )?erinnerungen|was hast du dir über mich gemerkt)\b',query):
        return text[:min(max(budget,3000),3800)]
    if re.search(r'(?i)\b(?:yesterday|gestern|earlier|vorhin|zuletzt|recent conversation|last conversation|meeting|besprechung|termin|heute|today|routine|alltag)\b',query):
        budget=max(budget,1700)
    ranked=[(len(words & set(re.findall(r'\w{3,}',line.casefold()))),i,line) for i,line in enumerate(lines)]
    picked=sorted([row for row in ranked if row[0]], key=lambda row:(-row[0],row[1]))[:5]
    return '\n'.join(row[2] for row in sorted(picked,key=lambda row:row[1]))[:budget]


def recent_turns(history, text, budget=3800):
    previous = history[:-1] if history and history[-1].get('role') == 'user' and history[-1].get('content') == text else history
    selected = []
    remaining = max(0, budget - len(text))
    for row in reversed(previous[-4:]):
        content = row.get('content')
        if not isinstance(content, str):
            break
        content = content[-800:]
        if len(content) > remaining:
            break
        selected.append(dict(row, content=content))
        remaining -= len(content)
    return list(reversed(selected)) + [{'role': 'user', 'content': text}]
