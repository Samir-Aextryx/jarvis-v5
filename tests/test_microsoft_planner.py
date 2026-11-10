"""Exercise real HTTP client behaviour through httpx.MockTransport, without credentials."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs

import httpx
import pytest

from jarvis.integrations.microsoft_graph_auth import (
    PlannerAuthenticationError, PlannerConfigurationError, PlannerError,
    PlannerNotFoundError, PlannerPermissionError, PlannerProtocolError,
    PlannerRateLimitError,
)
from jarvis.integrations.microsoft_planner import PlannerClient, PlannerConfig


CONFIG = PlannerConfig(client_id='11111111-2222-3333-4444-555555555555', client_secret='test-secret')


def token_response(token='test-token', expires_in=3600):
    return httpx.Response(200, json={'access_token': token, 'token_type': 'Bearer', 'expires_in': expires_in})


def client_with(graph_handler, **kwargs):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.host == 'login.microsoftonline.com':
            assert request.method == 'POST'
            assert request.url.path == f'/{CONFIG.tenant_id}/oauth2/v2.0/token'
            values = parse_qs(request.content.decode())
            assert values['grant_type'] == ['client_credentials']
            assert values['scope'] == ['https://graph.microsoft.com/.default']
            return token_response('token-' + str(sum(call.url.host == 'login.microsoftonline.com' for call in calls)))
        assert request.url.host == 'graph.microsoft.com'
        assert request.method == 'GET', 'A Graph write must never be emitted'
        return graph_handler(request)

    return PlannerClient(CONFIG, transport=httpx.MockTransport(handler), **kwargs), calls


def test_summary_joins_buckets_tasks_details_and_checklist():
    def graph(request):
        if request.url.path.endswith('/buckets'):
            return httpx.Response(200, json={'value': [{'id': 'bucket-1', 'name': 'Meetings'}]})
        if request.url.path.endswith('/tasks'):
            return httpx.Response(200, json={'value': [
                {'id': 'task-1', 'title': 'Prepare meeting', 'bucketId': 'bucket-1',
                 'percentComplete': 50, 'dueDateTime': '2026-10-08T09:00:00Z',
                 'assignments': {'user-1': {'assignedDateTime': '2026-10-07T09:00:00Z'}}},
                {'id': 'task-2', 'title': 'Done', 'bucketId': 'deleted-bucket', 'percentComplete': 100},
            ]})
        return httpx.Response(200, json={'description': 'Bring notes',
            'checklist': {'a': {'title': 'Agenda', 'isChecked': True},
                          'b': {'title': 'Slides', 'isChecked': False}}})

    client, calls = client_with(graph)
    with client:
        summary = client.get_board_summary()
    assert summary['read_only'] and summary['content_is_untrusted']
    assert summary['task_count'] == 2
    task = summary['tasks'][0]
    assert task['bucket_name'] == 'Meetings'
    assert task['status'] == 'in_progress'
    assert task['due_date_time'] == '2026-10-08T09:00:00Z'
    assert task['description'] == 'Bring notes'
    assert task['checklist']['completed'] == 1
    assert task['checklist']['total'] == 2
    assert task['assignments'][0]['user_id'] == 'user-1'
    assert summary['tasks'][1]['bucket_name'] is None
    assert summary['tasks'][1]['status'] == 'completed'
    assert len(calls) == 5  # One token reused across four GETs.
    assert json.loads(json.dumps(summary)) == summary


def test_cached_token_expires_and_refreshes_with_monotonic_time():
    now = [0.0]
    client, calls = client_with(lambda _: httpx.Response(200, json={'value': []}), clock=lambda: now[0])
    with client:
        client.get_tasks()
        now[0] = 3539
        client.get_buckets()
        now[0] = 3540  # 3600 seconds minus the 60-second safety margin.
        client.get_tasks()
    assert sum(call.method == 'POST' for call in calls) == 2


def test_concurrent_requests_share_one_token_refresh():
    lock = threading.Lock()
    token_calls = []

    def handler(request):
        if request.method == 'POST':
            with lock:
                token_calls.append(request)
            return token_response()
        assert request.method == 'GET'
        return httpx.Response(200, json={'value': []})

    with PlannerClient(CONFIG, transport=httpx.MockTransport(handler)) as planner:
        with ThreadPoolExecutor(max_workers=8) as pool:
            assert list(pool.map(lambda _: planner.get_tasks(), range(20))) == [[]] * 20
    assert len(token_calls) == 1


def test_401_refreshes_once_and_replays_only_get():
    attempts = []

    def graph(request):
        attempts.append(request.headers['Authorization'])
        return httpx.Response(401 if len(attempts) == 1 else 200, json={'value': []})

    client, calls = client_with(graph)
    with client:
        assert client.get_tasks() == []
    assert attempts == ['Bearer token-1', 'Bearer token-2']
    assert len(calls) == 4


def test_repeated_401_cannot_loop():
    client, calls = client_with(lambda _: httpx.Response(401, json={'error': {'code': 'InvalidAuthenticationToken'}}))
    with client, pytest.raises(PlannerAuthenticationError) as error:
        client.get_tasks()
    assert error.value.status_code == 401
    assert len(calls) == 4


@pytest.mark.parametrize('status,error_type', [(403, PlannerPermissionError), (404, PlannerNotFoundError)])
def test_permissions_and_missing_plan_fail_without_retry(status, error_type):
    client, calls = client_with(lambda _: httpx.Response(status, json={'error': {'code': 'AccessDenied',
                                                                                  'message': 'sensitive server data'}}))
    with client, pytest.raises(error_type) as error:
        client.get_tasks()
    assert len(calls) == 2
    assert error.value.status_code == status
    assert 'sensitive' not in str(error.value)


def test_rate_limit_respects_retry_after_then_succeeds():
    sleeps = []
    graph_calls = []

    def graph(request):
        graph_calls.append(request)
        if len(graph_calls) == 1:
            return httpx.Response(429, headers={'Retry-After': '2'})
        return httpx.Response(200, json={'value': []})

    client, _ = client_with(graph, sleep=sleeps.append)
    with client:
        assert client.get_tasks() == []
    assert sleeps == [2.0]


def test_rate_limit_long_delay_is_reported_without_retrying_too_early():
    sleeps = []
    client, calls = client_with(lambda _: httpx.Response(429, headers={'Retry-After': '600'}), sleep=sleeps.append)
    with client, pytest.raises(PlannerRateLimitError) as error:
        client.get_tasks()
    assert error.value.retry_after == 600
    assert sleeps == []
    assert len(calls) == 2


@pytest.mark.parametrize('status', [429, 502, 503, 504])
def test_transient_retry_budget_is_bounded(status):
    sleeps = []
    client, calls = client_with(lambda _: httpx.Response(status, headers={'Retry-After': '0'}), sleep=sleeps.append)
    with client, pytest.raises(PlannerError):
        client.get_buckets()
    assert len(sleeps) == 2
    assert len(calls) == 4


def test_network_timeouts_retry_get_and_hide_request_headers():
    sleeps = []

    def graph(request):
        raise httpx.ReadTimeout('secret-token sensitive data', request=request)

    client, calls = client_with(graph, sleep=sleeps.append)
    with client, pytest.raises(PlannerError) as error:
        client.get_tasks()
    assert len(calls) == 4
    assert sleeps == [1, 2]
    assert 'secret-token' not in str(error.value)


def test_pagination_reads_all_pages_and_reuses_token():
    def graph(request):
        if request.url.query:
            return httpx.Response(200, json={'value': [{'id': 'task-2'}]})
        return httpx.Response(200, json={'value': [{'id': 'task-1'}],
            '@odata.nextLink': str(request.url) + '?$skiptoken=page2'})

    client, calls = client_with(graph)
    with client:
        assert [task['id'] for task in client.get_tasks()] == ['task-1', 'task-2']
    assert len(calls) == 3


@pytest.mark.parametrize('url', [
    'https://evil.example/v1.0/planner/plans/id/tasks',
    'http://graph.microsoft.com/v1.0/planner/plans/id/tasks',
    'https://graph.microsoft.com/v1.0/users',
    'https://graph.microsoft.com@evil.example/v1.0/users',
    'https://graph.microsoft.com:443/v1.0/users',
    'https://graph.microsoft.com/v1.0/planner/plans/id/tasks#ignored',
])
def test_pagination_cannot_exfiltrate_token_or_change_resource(url):
    client, calls = client_with(lambda _: httpx.Response(200, json={'value': [], '@odata.nextLink': url}))
    with client, pytest.raises(PlannerProtocolError):
        client.get_tasks()
    assert len(calls) == 2


def test_repeating_pagination_and_page_budget_raise_instead_of_truncating():
    client, _ = client_with(lambda request: httpx.Response(200, json={'value': [], '@odata.nextLink': str(request.url)}))
    with client, pytest.raises(PlannerProtocolError):
        client.get_tasks()
    client, calls = client_with(lambda request: httpx.Response(200, json={
        'value': [], '@odata.nextLink': str(request.url) + '?next=2'}), max_pages=1)
    with client, pytest.raises(PlannerProtocolError):
        client.get_tasks()
    assert len(calls) == 2


@pytest.mark.parametrize('body', [{'bad': []}, {'value': {}}, {'value': [1]}, []])
def test_invalid_collection_response_is_rejected(body):
    client, _ = client_with(lambda _: httpx.Response(200, json=body))
    with client, pytest.raises(PlannerProtocolError):
        client.get_tasks()


def test_detail_failure_never_returns_an_apparently_complete_summary():
    def graph(request):
        if request.url.path.endswith('/buckets'):
            return httpx.Response(200, json={'value': []})
        if request.url.path.endswith('/tasks'):
            return httpx.Response(200, json={'value': [{'id': 'task-1'}]})
        return httpx.Response(403)

    client, _ = client_with(graph)
    with client, pytest.raises(PlannerPermissionError):
        client.get_board_summary()


def test_invalid_task_id_rejected_before_any_request():
    client, calls = client_with(lambda _: httpx.Response(200, json={}))
    with client, pytest.raises(PlannerConfigurationError):
        client.get_task_details('../users?token=secret')
    assert not calls


def test_expired_secret_error_is_actionable_without_leaking_body():
    transport = httpx.MockTransport(lambda _: httpx.Response(400, json={
        'error': 'invalid_client', 'error_description': 'expired test-secret: private tenant detail'}))
    with PlannerClient(CONFIG, transport=transport) as client, pytest.raises(PlannerAuthenticationError) as error:
        client.get_buckets()
    assert error.value.code == 'invalid_client'
    assert 'secret expiry' in str(error.value)
    assert 'test-secret' not in str(error.value)


@pytest.mark.parametrize('expiry', [None, 'bad', 0, -1, 'nan', 'inf'])
def test_invalid_token_expiry_is_rejected(expiry):
    transport = httpx.MockTransport(lambda _: token_response(expires_in=expiry))
    with PlannerClient(CONFIG, transport=transport) as client, pytest.raises(PlannerProtocolError):
        client.get_tasks()


def test_env_loading_does_not_overwrite_process_credentials_or_expand_secret(tmp_path, monkeypatch):
    for name in ('CLIENT_ID', 'CLIENT_SECRET', 'PLAN_ID', 'TENANT_ID'):
        monkeypatch.delenv(name, raising=False)
    env = tmp_path / '.env'
    env.write_text(f'CLIENT_ID={CONFIG.client_id}\nCLIENT_SECRET=literal${{TOKEN}}\n', encoding='utf-8')
    loaded = PlannerConfig.from_env(env)
    assert loaded.client_secret == 'literal${TOKEN}'
    assert loaded.plan_id == CONFIG.plan_id
    monkeypatch.setenv('CLIENT_SECRET', 'process-secret')
    assert PlannerConfig.from_env(env).client_secret == 'process-secret'
    assert 'process-secret' not in repr(PlannerConfig.from_env(env))


def test_missing_credentials_or_env_file_fail_locally(tmp_path, monkeypatch):
    monkeypatch.delenv('CLIENT_ID', raising=False)
    monkeypatch.delenv('CLIENT_SECRET', raising=False)
    with pytest.raises(PlannerConfigurationError):
        PlannerConfig.from_env()
    with pytest.raises(PlannerConfigurationError):
        PlannerConfig.from_env(tmp_path / 'not-there.env')


def test_closed_client_cannot_authenticate_or_send_get():
    client, calls = client_with(lambda _: httpx.Response(200, json={'value': []}))
    client.close()
    client.close()
    with pytest.raises(PlannerError, match='closed'):
        client.get_tasks()
    assert not calls
