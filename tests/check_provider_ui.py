"""Local UI smoke check with fake keys, fake microphone and mocked APIs only."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    prefs = {'work_apps': ['Outlook'], 'fallback': True, 'automation': True, 'activity_log': True,
             'large_model': 'gpt-6-luna', 'gemini_model': 'gemini-3.8-flash', 'grok_model': 'grok-4.7',
             'llm_provider': 'openai', 'reasoning_effort': 'low', 'default_email': 'Gmail',
             'jev_configured': False, 'jev_status': 'Not Connected', 'jev_error': '', 'jev_error_code': 'JEV_KEY_MISSING'}
    keys = {'openai': True, 'gemini': False, 'grok': False}
    posts = []
    errors = []

    def llm_status():
        return {'provider': prefs['llm_provider'], 'model': prefs['gemini_model'],
                'available': keys[prefs['llm_provider']],
                'providers': [{'id': key, 'name': key, 'model': prefs['gemini_model'] if key == 'gemini' else prefs['grok_model'] if key == 'grok' else prefs['large_model'], 'configured': value}
                              for key, value in keys.items()]}

    def api(route):
        path = route.request.url.split('/api/', 1)[-1]
        body = route.request.post_data_json if route.request.method == 'POST' else None
        if body is not None:
            posts.append((path, body))
        if path == 'agent/settings':
            if body:
                prefs.update(body)
            result = prefs
        elif path in {'settings/llm', 'local-pc/status'}:
            result = llm_status()
        elif path == 'settings/keys':
            key = {'GEMINI_API_KEY': 'gemini', 'XAI_API_KEY': 'grok'}[body['key_name']]
            keys[key] = bool(body['key_value'])
            result = {'success': True}
        elif path == 'settings/test-llm':
            result = {'valid': True, 'provider': body['provider']}
        elif path == 'settings/status':
            result = {'codex_installed': False, 'calendar_accessible': True, 'mail_accessible': False,
                      'notes_accessible': True, 'memory_count': 0, 'task_count': 0, 'server_port': 8345,
                      'uptime_seconds': 1, 'env_keys_set': {'openai': True, 'fish_audio': True, 'fish_voice_id': True, 'user_name': 'Test'}}
        elif path == 'settings/preferences':
            result = {'user_name': 'Test', 'honorific': 'sir', 'stt_keywords': ''}
        elif path == 'agent/whatsapp-call/status':
            result = {'contact_saved': True, 'whatsapp_beta_installed': True, 'automatic_call_ready': False, 'reason': 'Test mode'}
        elif path == 'agent/phone-privacy/status':
            result = {'active': True}  # Physical microphone must remain closed.
        elif path == 'autonomy/jobs':
            result = {'jobs': []}
        else:
            result = {'items': [], 'services': [], 'configured': False, 'connected': False}
        route.fulfill(status=200, content_type='application/json', body=json.dumps(result))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1050, 'height': 800})
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script("localStorage.setItem('jarvis_auth_token', 'ui-test-only');")
        page.route('**/api/**', api)
        page.route('https://**/*', lambda route: route.abort())
        page.route_web_socket('**/*', lambda ws: ws.close())
        page.goto('http://127.0.0.1:18466/?dashboard=1')
        page.locator('#btn-menu').click()
        page.locator('#btn-settings').click()
        page.wait_for_function("document.getElementById('agent-provider')?.value === 'openai' && !document.getElementById('agent-save').disabled")
        assert page.locator('#agent-provider option').count() == 3
        page.locator('#input-gemini-key').fill('fake-gemini-test-key')
        page.locator('#save-gemini-key').click()
        page.wait_for_function("document.getElementById('gemini-key-status')?.textContent.includes('Key saved in Windows')")
        assert page.locator('#input-gemini-key').input_value() == ''
        page.locator('#agent-provider').select_option('gemini')
        page.locator('#agent-save').click()
        page.wait_for_function("document.getElementById('agent-status')?.textContent.includes('AI provider and settings saved')")
        assert prefs['llm_provider'] == 'gemini' and prefs['large_model'] == 'gpt-6-luna'
        page.locator('#test-gemini-key').click()
        page.wait_for_function("document.getElementById('gemini-key-status')?.textContent === 'Connection successful.'")
        page.locator('#remove-gemini-key').click()
        page.wait_for_function("document.getElementById('gemini-key-status')?.textContent === 'API key removed.'")
        assert not keys['gemini']
        assert any(path == 'settings/test-llm' and body['provider'] == 'gemini' for path, body in posts)
        page.locator('#agent-provider').scroll_into_view_if_needed()
        Path('.app-test').mkdir(exist_ok=True)
        page.screenshot(path='.app-test/provider-settings.png')
        assert not errors, errors
        browser.close()
    print('UI passed: provider choice, key saving/clearing, connection test and removal; no live services or microphone used.')


if __name__ == '__main__':
    main()
