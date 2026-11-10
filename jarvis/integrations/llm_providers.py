"""Fixed official endpoints and independent credentials for Jarvis's AI providers."""

import os
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    key_name: str
    model_variable: str
    default_model: str
    endpoint: str


PROVIDERS = {
    'openai': Provider('openai', 'OpenAI', 'OPENAI_API_KEY', 'OPENAI_MODEL',
                      'gpt-6-luna', 'https://api.openai.com/v1/responses'),
    'gemini': Provider('gemini', 'Gemini', 'GEMINI_API_KEY', 'GEMINI_MODEL',
                      'gemini-3.8-flash', 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions'),
    'grok': Provider('grok', 'Grok', 'XAI_API_KEY', 'GROK_MODEL',
                    'grok-4.7', 'https://api.x.ai/v1/chat/completions'),
    'ollama': Provider('ollama', 'Ollama Cloud', 'OLLAMA_API_KEY', 'OLLAMA_MODEL',
                      'deepseek-v4.1-flash', 'https://ollama.com/v1/chat/completions'),
}

PROVIDER_CHOICE_ERROR = 'Choose OpenAI, Gemini, Grok or Ollama Cloud as the AI provider.'


def provider_config(provider=None):
    """Resolve a supported provider; never silently fall back or change destination."""
    name = (provider if provider is not None else os.getenv('LLM_PROVIDER', 'openai')).strip().lower()
    if name not in PROVIDERS:
        raise ValueError(PROVIDER_CHOICE_ERROR)
    return PROVIDERS[name]


def provider_model(provider):
    """Keep each provider's configured model independent of the others."""
    config = provider_config(provider)
    return validate_model(os.getenv(config.model_variable, config.default_model))


def validate_model(model):
    # Ollama names a model version with a tag, e.g. deepseek-v4.1-flash:1017.
    if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,100}(?::[A-Za-z0-9._-]{1,50})?', model):
        raise ValueError('Enter a valid model identifier.')
    return model


def apply_provider_settings(settings):
    """Apply persisted non-secret choices at startup and after saving settings."""
    os.environ['LLM_PROVIDER'] = settings['llm_provider']
    os.environ['OPENAI_MODEL'] = settings['large_model']
    os.environ['GEMINI_MODEL'] = settings['gemini_model']
    os.environ['GROK_MODEL'] = settings['grok_model']
    os.environ['OLLAMA_MODEL'] = settings['ollama_model']
    os.environ['OPENAI_REASONING_EFFORT'] = settings['reasoning_effort']


def provider_status():
    """Return public model/key-presence metadata, never API keys."""
    from jarvis.integrations.credentials_vault import get_secure_key
    active = provider_config().id
    choices = [{'id': entry.id, 'name': entry.label,
                'model': provider_model(entry.id), 'configured': bool(get_secure_key(entry.key_name))}
               for entry in PROVIDERS.values()]
    selected = next(choice for choice in choices if choice['id'] == active)
    return {'provider': active, 'model': selected['model'], 'available': selected['configured'],
            'providers': choices}
