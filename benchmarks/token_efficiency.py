"""Offline before/after input-text token counts; no API requests or private data."""
import ast
import asyncio
import copy
import json
import logging
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import tiktoken

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jarvis.core.personal_memory import PersonalMemory
from jarvis.voice.voice_context import recent_turns

TOKENIZER = tiktoken.get_encoding('o200k_base')


def tokens(text):
    return len(TOKENIZER.encode(text))


def before_turns(history, text):
    messages = [dict(row, content=row['content'][-2400:]) for row in history[-6:]]
    if not messages or messages[-1].get('content') != text:
        messages.append({'role': 'user', 'content': text})
    return messages


class Capture:
    def __init__(self):
        self.messages = self
        self.calls = 0
        self.input_tokens = 0

    async def create(self, *, messages, system='', **kwargs):
        self.calls += 1
        self.input_tokens += tokens(system) + sum(tokens(row['content']) for row in messages)
        return SimpleNamespace(content=[SimpleNamespace(text='[]')])


def result(before, after):
    return {'before': before, 'after': after,
            'saved_percent': round(100 * (before - after) / before, 1) if before else 0}


def summary_function():
    tree = ast.parse((ROOT / 'jarvis/server.py').read_text(encoding='utf-8'))
    function = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                    and node.name == '_update_session_summary')
    namespace = {'LLMClient': object, 'log': logging.getLogger('benchmark')}
    exec(compile(ast.Module(body=[function], type_ignores=[]), 'summary', 'exec'), namespace)
    return namespace[function.name]


async def run():
    report = {'method': 'o200k_base input-text tokens only; synthetic fixtures; no API calls, output tokens, protocol overhead or cache pricing',
              'conversation': {}, 'summaries': {}, 'memory': {}}
    for label, repetitions in [('short', 1), ('long', 28)]:
        history = []
        totals = [0, 0]
        for turn in range(100):
            question = (f'Frage {turn}: Erkläre bitte, wie ein Elektromotor funktioniert. ' * repetitions).strip()
            for index, selector in enumerate((before_turns, recent_turns)):
                totals[index] += sum(tokens(row['content']) for row in selector(history, question))
            history.extend([{'role': 'user', 'content': question},
                            {'role': 'assistant', 'content': 'Ein Elektromotor wandelt elektrische Energie durch Magnetfelder in Bewegung um. ' * repetitions}])
        report['conversation'][label + '_100_turns_history_and_current_request'] = result(*totals)

    summarize = summary_function()
    for length in [20, 50, 100]:
        clients = [Capture(), Capture()]
        history = []
        cursor = 0
        since_summary = 0
        old_summary = ''
        for turn in range(length):
            history.extend([{'role': 'user', 'content': f'Frage {turn}: Wie funktioniert ein Elektromotor und welche Bauteile braucht er?'},
                            {'role': 'assistant', 'content': 'Ein Elektromotor benötigt einen Stator und einen Rotor. Magnetfelder erzeugen eine Drehbewegung.'}])
            since_summary += 1
            if since_summary >= 5 and len(history) > 20:
                since_summary = 0
                end = min(len(history) - 20, cursor + 20)
                await summarize(old_summary, history[:-20], clients[0])
                await summarize(old_summary, history[cursor:end], clients[1])
                cursor = end
                old_summary = 'Wir besprechen Elektromotoren, ihre Bauteile und die Wirkung von Magnetfeldern.'
        report['summaries'][str(length) + '_turns'] = {
            'input_tokens': result(*(client.input_tokens for client in clients)),
            'calls': result(*(client.calls for client in clients))}

    tree = ast.parse((ROOT / 'jarvis.core.personal_memory.py').read_text(encoding='utf-8'))
    memory_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'PersonalMemory')
    learn = copy.deepcopy(next(node for node in memory_class.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'learn'))
    assert isinstance(learn.body[1], ast.If) and 're.search' in ast.unparse(learn.body[1].test)
    del learn.body[1]
    namespace = dict(sys.modules['personal_memory'].__dict__)
    exec(compile(ast.Module(body=[learn], type_ignores=[]), 'before_memory', 'exec'), namespace)
    general = ['Wie funktioniert ein Elektromotor?', 'What is the capital of France?',
               'Explain Python generators.', 'Wie entsteht ein Regenbogen?', 'Was bedeutet Wechselstrom?',
               'Explain how solar panels work.', 'Wie funktioniert ein Computer?', 'What causes the tides?']
    personal = ['Ich wohne jetzt in Bern.', 'My favourite drink is tea.']
    clients = [Capture(), Capture()]
    with tempfile.TemporaryDirectory() as root:
        memory = PersonalMemory(root)
        for text in (general + personal) * 10:
            await namespace['learn'](memory, text, clients[0], 0)
            await memory.learn(text, clients[1], 0)
    report['memory']['100_messages_80_general_20_personal_empty_existing_memory'] = {
        'input_tokens': result(*(client.input_tokens for client in clients)),
        'calls': result(*(client.calls for client in clients))}
    output = ROOT / 'benchmarks/token_efficiency_results.json'
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    asyncio.run(run())
