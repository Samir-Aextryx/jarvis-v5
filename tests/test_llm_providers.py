import asyncio
import json
import os
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from jarvis.core.agent_settings import AgentSettings
from jarvis.integrations.credentials_vault import set_secure_key
from jarvis.integrations.llm_client import LLMClient
from jarvis.integrations.llm_providers import PROVIDERS, apply_provider_settings, provider_status, validate_model


@pytest.mark.parametrize('provider,key_name', [('openai', 'OPENAI_API_KEY'), ('gemini', 'GEMINI_API_KEY'), ('grok', 'XAI_API_KEY'),
                                              ('ollama', 'OLLAMA_API_KEY')])
def test_each_provider_reads_only_its_own_key(provider, key_name):
    with patch.dict(os.environ, {'LLM_PROVIDER': provider}), \
         patch('jarvis.integrations.llm_client.get_secure_key', return_value='own-key') as key:
        client = LLMClient()
    assert client.provider == provider
    assert client.api_key == 'own-key'
    key.assert_called_once_with(key_name)


@pytest.mark.parametrize('provider', ['gemini', 'grok', 'ollama'])
@pytest.mark.asyncio
async def test_text_images_json_schema_and_usage_match_provider_contract(provider):
    schema = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}},
              'required': ['ok'], 'additionalProperties': False}
    seen = []

    def respond(request):
        seen.append(request)
        assert str(request.url) == PROVIDERS[provider].endpoint
        assert request.headers['Authorization'] == 'Bearer provider-key'
        body = json.loads(request.content)
        assert body['messages'][0] == {'role': 'system', 'content': 'System instructions'}
        assert body['messages'][1]['content'][0] == {'type': 'text', 'text': 'Screenshot'}
        assert body['messages'][1]['content'][1]['image_url']['url'] == 'data:image/png;base64,YQ=='
        assert body['response_format']['json_schema']['schema'] == schema
        assert body['model'] == 'test-model'
        assert 'input' not in body and 'instructions' not in body and 'store' not in body
        if provider == 'grok':
            assert 'reasoning_effort' not in body
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"ok":true}'}, 'finish_reason': 'stop'}],
                                       'usage': {'prompt_tokens': 10, 'completion_tokens': 2}})

    client = LLMClient('provider-key', transport=httpx.MockTransport(respond), provider=provider)
    result = await client.create(system='System instructions', model='test-model', json_schema=schema,
        messages=[{'role': 'user', 'content': [{'type': 'text', 'text': 'Screenshot'},
                   {'type': 'image', 'source': {'media_type': 'image/png', 'data': 'YQ=='}}]}])
    assert json.loads(result.content[0].text) == {'ok': True}
    assert result.usage.input_tokens == 10 and result.usage.output_tokens == 2
    assert len(seen) == 1


@pytest.mark.parametrize('provider', ['gemini', 'grok', 'ollama'])
@pytest.mark.asyncio
async def test_stream_starts_immediately_and_normalizes_usage(provider):
    released = asyncio.Event()

    class SSE(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"Hello"},"finish_reason":null}]}\n\n'
            await released.wait()
            yield b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
            yield b'data: {"choices":[],"usage":{"prompt_tokens":4,"completion_tokens":2}}\n\n'
            yield b'data: [DONE]\n\n'

    def respond(request):
        assert str(request.url) == PROVIDERS[provider].endpoint
        assert json.loads(request.content)['stream_options'] == {'include_usage': True}
        return httpx.Response(200, stream=SSE())

    usage = []
    client = LLMClient('own-key', provider=provider, transport=httpx.MockTransport(respond))
    stream = client.stream_text(messages=[{'role': 'user', 'content': 'Hi'}], on_usage=usage.append)
    assert await asyncio.wait_for(anext(stream), 1) == 'Hello'
    assert not released.is_set()
    released.set()
    assert [delta async for delta in stream] == []
    assert usage[0].usage.input_tokens == 4
    assert usage[0].provider == provider


@pytest.mark.parametrize('provider', ['gemini', 'grok', 'ollama'])
@pytest.mark.asyncio
async def test_cancel_closes_upstream_stream_and_no_more_tokens_arrive(provider):
    closed = asyncio.Event()

    class SSE(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
            await asyncio.Event().wait()

        async def aclose(self):
            closed.set()

    client = LLMClient('key', provider=provider,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=SSE())))
    stream = client.stream_text(messages=[{'role': 'user', 'content': 'Hi'}])
    assert await anext(stream) == 'Hello'
    waiting = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    assert closed.is_set()


@pytest.mark.parametrize('body', [
    'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n',
    'data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n\ndata: [DONE]\n\n',
    'data: {"error":{"message":"sensitive-data"}}\n\n',
    'data: [DONE]\n\n',
])
@pytest.mark.asyncio
async def test_incomplete_or_failed_stream_is_not_accepted_as_success(body):
    client = LLMClient('key', provider='gemini', transport=httpx.MockTransport(lambda _: httpx.Response(200, text=body)))
    with pytest.raises(RuntimeError) as error:
        _ = [part async for part in client.stream_text(messages=[{'role': 'user', 'content': 'Hi'}])]
    assert 'sensitive-data' not in str(error.value)


@pytest.mark.parametrize('provider', ['gemini', 'grok', 'ollama'])
@pytest.mark.parametrize('status', [401, 403, 429, 503, 307])
@pytest.mark.asyncio
async def test_provider_errors_are_safe_and_do_not_switch_provider(provider, status):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, text='own-key private data', headers={'Location': 'https://evil.example'})

    client = LLMClient('own-key', provider=provider, transport=httpx.MockTransport(respond))
    with pytest.raises(RuntimeError, match=f'HTTP {status}') as error:
        await client.create(messages=[{'role': 'user', 'content': 'Hi'}])
    assert 'own-key' not in str(error.value)
    assert len(calls) == 1 and str(calls[0].url) == PROVIDERS[provider].endpoint


@pytest.mark.asyncio
async def test_missing_provider_key_does_not_use_existing_openai_key():
    with patch('jarvis.integrations.llm_client.get_secure_key', return_value=''):
        client = LLMClient(provider='grok', transport=httpx.MockTransport(lambda _: pytest.fail('No request expected')))
    with pytest.raises(RuntimeError, match='Grok API key is missing'):
        await client.create(messages=[])


def test_persisted_selection_preserves_each_model_and_legacy_settings():
    with TemporaryDirectory() as root, patch.dict(os.environ):
        settings = AgentSettings(root)
        settings.save({'large_model': 'gpt-6-luna'})
        result = settings.save({'llm_provider': 'gemini', 'gemini_model': 'custom-gemini'})
        assert result['large_model'] == 'gpt-6-luna'
        assert result['ollama_model'] == 'deepseek-v4.1-flash'
        assert AgentSettings(root).get()['llm_provider'] == 'gemini'
        apply_provider_settings(result)
        assert LLMClient('test').provider == 'gemini'
        assert os.environ['GEMINI_MODEL'] == 'custom-gemini'
        with pytest.raises(ValueError):
            settings.save({'llm_provider': 'evil'})
        with pytest.raises(ValueError):
            settings.save({'grok_model': '../key-exfiltration'})


def test_presence_status_returns_no_credentials():
    with patch('jarvis.integrations.credentials_vault.get_secure_key', return_value='private-key'):
        status = provider_status()
    assert all(entry['configured'] for entry in status['providers'])
    assert 'private-key' not in json.dumps(status)


def test_provider_secret_save_failure_cannot_claim_persistence_or_set_environment():
    with patch.dict(os.environ, {}, clear=True), \
         patch('jarvis.integrations.credentials_vault.get_vault', return_value=None):
        with pytest.raises(RuntimeError, match='not saved'):
            set_secure_key('GEMINI_API_KEY', 'secret', require_persistence=True)
        assert 'GEMINI_API_KEY' not in os.environ
    vault = Mock()
    vault.set_password.side_effect = RuntimeError('private-secret')
    with patch('jarvis.integrations.credentials_vault.get_vault', return_value=vault):
        with pytest.raises(RuntimeError) as error:
            set_secure_key('XAI_API_KEY', 'private-secret', require_persistence=True)
    assert 'private-secret' not in str(error.value)


@pytest.mark.asyncio
async def test_provider_settings_endpoints_require_auth_and_test_explicit_provider():
    import jarvis.server as server
    from jarvis.routers import system
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url='http://testserver') as http:
        assert (await http.get('/api/settings/llm')).status_code == 401
        assert (await http.post('/api/settings/test-llm', json={'provider': 'gemini'})).status_code == 401
        http.headers['Authorization'] = 'Bearer ' + server.JARVIS_AUTH_TOKEN
        with patch('jarvis.integrations.credentials_vault.get_secure_key', return_value='private-key'):
            status = await http.get('/api/settings/llm')
        assert 'private-key' not in status.text
        mock = Mock()
        mock.create = AsyncMock()
        with patch.object(server, 'LLMClient', return_value=mock) as factory:
            tested = await http.post('/api/settings/test-llm', json={'provider': 'gemini', 'key_value': 'gemini-test'})
        assert tested.json()['valid']
        factory.assert_called_once_with(api_key='gemini-test', provider='gemini')
        with patch.object(server, 'LLMClient', return_value=mock) as factory:
            await http.post('/api/settings/test-openai', json={'key_value': 'openai-test'})
        factory.assert_called_once_with(api_key='openai-test', provider='openai')
        assert (await http.post('/api/settings/test-llm', json={'provider': 'evil'})).status_code == 422
        assert (await http.post('/api/settings/keys', json={'key_name': 'XAI_API_KEY', 'key_value': 'secret\nENV=value'})).status_code == 400
        mock.create.side_effect = RuntimeError('private-key')
        with patch.object(server, 'LLMClient', return_value=mock):
            failed = await http.post('/api/settings/test-llm', json={'provider': 'grok'})
        assert not failed.json()['valid'] and 'private-key' not in failed.text


@pytest.mark.asyncio
async def test_english_speech_never_sends_openai_key_to_other_provider():
    from jarvis.voice import speech_language
    response = Mock()
    response.content = [Mock(text='A different English test response.')]
    mock = Mock()
    mock.messages.create = AsyncMock(return_value=response)
    with patch.dict(os.environ, {'LLM_PROVIDER': 'gemini'}), \
         patch.object(speech_language, 'LLMClient', return_value=mock) as factory:
        await speech_language.english_speech('Eine besondere deutsche Testantwort.', 'openai-only-key')
    factory.assert_called_once_with()


@pytest.mark.parametrize('effort,sent', [('none', 'none'), ('low', 'low'), ('medium', 'high'),
                                         ('high', 'high'), ('xhigh', 'max'), ('max', 'max')])
@pytest.mark.asyncio
async def test_ollama_sends_deepseek_flash_with_a_supported_thinking_level(effort, sent):
    def respond(request):
        assert str(request.url) == 'https://ollama.com/v1/chat/completions'
        body = json.loads(request.content)
        assert body['model'] == 'deepseek-v4.1-flash'
        assert body['reasoning_effort'] == sent
        return httpx.Response(200, json={'choices': [{'message': {'content': 'OK'}, 'finish_reason': 'stop'}]})

    with patch.dict(os.environ, {'OPENAI_REASONING_EFFORT': effort}):
        os.environ.pop('OLLAMA_MODEL', None)
        client = LLMClient('ollama-key', provider='ollama', transport=httpx.MockTransport(respond))
        assert (await client.create(messages=[{'role': 'user', 'content': 'Hi'}])).content[0].text == 'OK'


def test_model_ids_accept_one_ollama_tag_only():
    assert validate_model('deepseek-v4.1-flash:1017') == 'deepseek-v4.1-flash:1017'
    for bad in ('deepseek:a:b', 'deepseek:', ':1017', '../key-exfiltration', 'model name'):
        with pytest.raises(ValueError):
            validate_model(bad)
