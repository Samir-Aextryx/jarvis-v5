"""Unified OpenAI, Gemini, Grok and Ollama Cloud adapter for Jarvis message consumers."""
import os
import json
from types import SimpleNamespace
import httpx
from jarvis.integrations.http_clients import http_client
from jarvis.integrations.credentials_vault import get_secure_key
from jarvis.integrations.llm_providers import provider_config, provider_model, validate_model


class LLMClient:
    def __init__(self, api_key=None, transport=None, *, provider=None):
        self.config = provider_config(provider)
        self.provider = self.config.id
        self.api_key = api_key if api_key is not None else get_secure_key(self.config.key_name)
        self.transport = transport
        self.messages = self

    def _require_key(self):
        if not self.api_key:
            raise RuntimeError(f'{self.config.label} API key is missing. Add it in Settings.')

    @staticmethod
    def _inputs(messages, *, chat=False):
        inputs = []
        for message in messages:
            content = message['content']
            if isinstance(content, list):
                parts = []
                for block in content:
                    if block['type'] == 'text':
                        parts.append({'type': 'text' if chat else 'input_text', 'text': block['text']})
                    elif block['type'] == 'image':
                        source = block['source']
                        url = f"data:{source['media_type']};base64,{source['data']}"
                        parts.append({'type': 'image_url', 'image_url': {'url': url}} if chat
                                     else {'type': 'input_image', 'image_url': url})
                    else:
                        raise ValueError('Unsupported message content')
                content = parts
            inputs.append({'role': message['role'], 'content': content})
        return inputs

    def _chat_payload(self, messages, system, max_tokens, model=None, json_schema=None):
        inputs = self._inputs(messages, chat=True)
        if system:
            inputs.insert(0, {'role': 'system', 'content': system})
        payload = {'model': validate_model(model) if model else provider_model(self.provider),
                   'messages': inputs, 'max_tokens': max(16, max_tokens)}
        if self.provider == 'gemini':
            effort = os.getenv('OPENAI_REASONING_EFFORT', 'low')
            payload['reasoning_effort'] = effort if effort in {'minimal', 'low', 'medium', 'high'} else 'low'
        elif self.provider == 'ollama':
            # DeepSeek on Ollama thinks at "high" unless told otherwise; "none" answers directly.
            effort = os.getenv('OPENAI_REASONING_EFFORT', 'low')
            payload['reasoning_effort'] = {'medium': 'high', 'xhigh': 'max'}.get(
                effort, effort if effort in {'none', 'low', 'high', 'max'} else 'low')
        if json_schema is not None:
            payload['response_format'] = {'type': 'json_schema', 'json_schema': {
                'name': 'pc_plan', 'strict': True, 'schema': json_schema}}
        return payload

    @staticmethod
    def _usage(data, *, chat=False):
        usage = data.get('usage') or {}
        return SimpleNamespace(input_tokens=usage.get('prompt_tokens' if chat else 'input_tokens', 0),
                               output_tokens=usage.get('completion_tokens' if chat else 'output_tokens', 0))

    async def _chat_stream(self, *, messages, system, max_tokens, on_usage):
        payload = self._chat_payload(messages, system, max_tokens)
        payload.update(stream=True, stream_options={'include_usage': True})
        finished = False
        done = False
        async with http_client(timeout=90, transport=self.transport) as client:
            async with client.stream('POST', self.config.endpoint,
                    headers={'Authorization': f'Bearer {self.api_key}'}, json=payload) as response:
                if response.status_code != 200:
                    raise RuntimeError(f'{self.config.label} API HTTP {response.status_code}; check key, model and API credit.')
                async for line in response.aiter_lines():
                    if not line.startswith('data:'):
                        continue
                    raw = line[5:].strip()
                    if raw == '[DONE]':
                        done = True
                        break
                    event = json.loads(raw)
                    if event.get('error'):
                        raise RuntimeError(f'{self.config.label} stream failed.')
                    if event.get('usage') and on_usage:
                        on_usage(SimpleNamespace(usage=self._usage(event, chat=True), provider=self.provider,
                                                 model=payload['model']))
                    for choice in event.get('choices') or []:
                        reason = choice.get('finish_reason')
                        if reason is not None:
                            if reason != 'stop':
                                raise RuntimeError(f'{self.config.label} stream did not complete normally.')
                            finished = True
                        delta = (choice.get('delta') or {}).get('content')
                        if isinstance(delta, str) and delta:
                            yield delta
        if not (finished and done):
            raise RuntimeError(f'{self.config.label} stream ended before completion.')

    async def stream_text(self, *, messages, system="", max_tokens=512, on_usage=None):
        """Yield Responses SSE text deltas; cancellation closes the HTTP stream."""
        self._require_key()
        if self.provider != 'openai':
            async for delta in self._chat_stream(messages=messages, system=system,
                                                max_tokens=max_tokens, on_usage=on_usage):
                yield delta
            return
        model = os.getenv('OPENAI_MODEL', 'gpt-6-luna')
        payload = {'model':model, 'input':messages,
                   'instructions':system, 'max_output_tokens':max_tokens, 'store':False, 'stream':True}
        if model == 'gpt-6-luna':
            payload['reasoning'] = {'effort': os.getenv('OPENAI_REASONING_EFFORT', 'low')}
        complete = False
        async with http_client(timeout=90, transport=self.transport) as client:
            async with client.stream('POST',self.config.endpoint,
                    headers={'Authorization':f'Bearer {self.api_key}'}, json=payload) as response:
                if response.status_code != 200:
                    raise RuntimeError(f'OpenAI API HTTP {response.status_code}')
                async for line in response.aiter_lines():
                    if not line.startswith('data:'):
                        continue
                    raw=line[5:].strip()
                    if raw=='[DONE]':
                        continue
                    event=json.loads(raw)
                    kind=event.get('type')
                    if kind=='response.output_text.delta':
                        yield event.get('delta','')
                    elif kind=='response.completed':
                        complete=True
                        usage=event.get('response',{}).get('usage',{})
                        if on_usage:
                            on_usage(SimpleNamespace(usage=SimpleNamespace(input_tokens=usage.get('input_tokens',0),output_tokens=usage.get('output_tokens',0))))
                    elif kind in {'error','response.failed','response.incomplete'}:
                        raise RuntimeError('OpenAI stream did not complete.')
        if not complete:
            raise RuntimeError('OpenAI stream ended before completion.')

    async def create(self, *, messages, system="", max_tokens=512, model=None, json_schema=None, **kwargs):
        self._require_key()
        if self.provider != 'openai':
            payload = self._chat_payload(messages, system, max_tokens, model, json_schema)
            async with http_client(timeout=90, transport=self.transport) as client:
                response = await client.post(self.config.endpoint,
                    headers={'Authorization': f'Bearer {self.api_key}'}, json=payload)
                if response.status_code != 200:
                    raise RuntimeError(f'{self.config.label} API HTTP {response.status_code}; check key, model and API credit.')
                data = response.json()
            choices = data.get('choices') or []
            choice = choices[0] if choices else {}
            text = (choice.get('message') or {}).get('content')
            if choice.get('finish_reason') != 'stop' or not isinstance(text, str) or not text.strip():
                raise RuntimeError(f'{self.config.label} returned no complete text response.')
            return SimpleNamespace(content=[SimpleNamespace(text=text)], usage=self._usage(data, chat=True),
                                   provider=self.provider, model=payload['model'])
        inputs = self._inputs(messages)
        selected_model = model or os.getenv("OPENAI_MODEL", "gpt-6-luna")
        payload = {
            "model": selected_model,
            "input": inputs,
            "max_output_tokens": max(16, max_tokens),
            "store": False,
        }
        if selected_model == 'gpt-6-luna':
            payload['reasoning'] = {'effort': os.getenv('OPENAI_REASONING_EFFORT', 'low')}
        if system:
            payload["instructions"] = system
        if json_schema is not None:
            payload["text"] = {"format": {"type": "json_schema", "name": "pc_plan", "strict": True, "schema": json_schema}}
        async with http_client(timeout=90, transport=self.transport) as client:
            response = await client.post(self.config.endpoint,
                headers={"Authorization": f"Bearer {self.api_key}"}, json=payload)
            if response.status_code != 200:
                # Never propagate API keys or full request bodies into logs/UI.
                raise RuntimeError(f"OpenAI API HTTP {response.status_code}; check key, model and API credit.")
            data = response.json()
        text = "".join(part.get("text", "") for item in data.get("output", [])
                       if item.get("type") == "message" for part in item.get("content", [])
                       if part.get("type") == "output_text")
        if not text:
            raise RuntimeError("OpenAI returned no text; check the model and output token limit.")
        usage = data.get("usage") or {}
        return SimpleNamespace(content=[SimpleNamespace(text=text)], usage=SimpleNamespace(
            input_tokens=usage.get("input_tokens", 0), output_tokens=usage.get("output_tokens", 0)))
