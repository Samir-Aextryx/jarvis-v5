"""HTTP authentication boundary: bearer-only, public health, CORS preflight."""
import json
import re
import unittest

from fastapi.testclient import TestClient

import jarvis.server as server
from jarvis import __version__


class HttpAuthTests(unittest.TestCase):
    def test_health_is_public_and_reports_package_version(self):
        with TestClient(server.app) as client:
            response = client.get('/api/health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['name'], 'JARVIS')
        self.assertEqual(response.json()['version'], __version__)

    def test_protected_route_requires_bearer_header(self):
        with TestClient(server.app) as client:
            self.assertEqual(client.get('/api/agent/settings').status_code, 401)
            self.assertEqual(client.get('/api/agent/settings', headers={'Authorization': 'Bearer wrong'}).status_code, 401)

    def test_query_token_is_not_accepted(self):
        with TestClient(server.app) as client:
            response = client.get('/api/agent/settings', params={'token': server.JARVIS_AUTH_TOKEN})
        self.assertEqual(response.status_code, 401)

    def test_bearer_token_grants_access(self):
        with TestClient(server.app) as client:
            response = client.get('/api/agent/settings',
                                  headers={'Authorization': 'Bearer ' + server.JARVIS_AUTH_TOKEN})
        self.assertEqual(response.status_code, 200)

    def test_cors_preflight_is_not_rejected_as_unauthenticated(self):
        with TestClient(server.app) as client:
            response = client.options('/api/agent/settings', headers={
                'Origin': 'http://localhost:5173',
                'Access-Control-Request-Method': 'GET',
                'Access-Control-Request-Headers': 'authorization',
            })
        self.assertIn(response.status_code, (200, 204))
        self.assertEqual(response.headers.get('access-control-allow-origin'), 'http://localhost:5173')

    def test_dashboard_launch_code_is_single_use_and_not_the_token(self):
        headers = {'Authorization': 'Bearer ' + server.JARVIS_AUTH_TOKEN}
        with TestClient(server.app) as client:
            self.assertEqual(client.post('/api/dashboard/session').status_code, 401)
            created = client.post('/api/dashboard/session', headers=headers)
            self.assertEqual(created.status_code, 200)
            code = created.json()['code']
            self.assertNotEqual(code, server.JARVIS_AUTH_TOKEN)
            launch = client.get('/launch/' + code)
            self.assertEqual(launch.status_code, 200)
            # The page must not expose the long-lived vault token.
            self.assertNotIn(server.JARVIS_AUTH_TOKEN, launch.text)
            self.assertNotIn(server.JARVIS_AUTH_TOKEN, launch.request.url.path)
            match = re.search(r'jarvis_auth_token",\s*("(?:[^"\\]|\\.)*")', launch.text)
            self.assertIsNotNone(match)
            session_token = json.loads(match.group(1))
            self.assertNotEqual(session_token, server.JARVIS_AUTH_TOKEN)
            # The short-lived dashboard credential is enough for the API.
            authorized = client.get('/api/agent/settings',
                                    headers={'Authorization': 'Bearer ' + session_token})
            self.assertEqual(authorized.status_code, 200)
            self.assertEqual(client.get('/launch/' + code).status_code, 410)

    def test_expired_dashboard_session_is_rejected(self):
        token = server.create_session_token(ttl=0)
        self.assertFalse(server.verify_auth_token(token, server.JARVIS_AUTH_TOKEN))


if __name__ == '__main__':
    unittest.main()
