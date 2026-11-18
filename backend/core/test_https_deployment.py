from django.test import Client, TestCase, override_settings


@override_settings(SECURE_SSL_REDIRECT=True, SECURE_HSTS_SECONDS=86400,
                   SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True,
                   STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
                             'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class HTTPSDeploymentTests(TestCase):
    @override_settings(SECURE_PROXY_SSL_HEADER=None)
    def test_untrusted_forwarded_header_does_not_disable_redirect(self):
        response = self.client.get('/api/me/', HTTP_X_FORWARDED_PROTO='https')
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response['Location'], 'https://testserver/api/me/')
        # Container healthchecks stay meaningful on their private HTTP socket.
        self.assertEqual(self.client.get('/health/live/').status_code, 200)

    @override_settings(SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO', 'https'))
    def test_trusted_tls_api_is_not_redirected_and_has_hsts(self):
        response = self.client.get('/api/me/', HTTP_X_FORWARDED_PROTO='https')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response['Strict-Transport-Security'], 'max-age=86400')

    @override_settings(SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO', 'https'))
    def test_https_admin_csrf_uses_secure_origin_and_cookie(self):
        client = Client(enforce_csrf_checks=True, HTTP_HOST='testserver')
        response = client.get('/admin/login/', HTTP_X_FORWARDED_PROTO='https')
        self.assertEqual(response.status_code, 200)
        token = response.cookies['csrftoken'].value
        self.assertTrue(response.cookies['csrftoken']['secure'])
        payload = {'username': 'no-such-user@example.invalid', 'password': 'synthetic-bad-password', 'csrfmiddlewaretoken': token}
        valid = client.post('/admin/login/', payload, HTTP_X_FORWARDED_PROTO='https',
                            HTTP_ORIGIN='https://testserver', HTTP_REFERER='https://testserver/admin/login/')
        self.assertEqual(valid.status_code, 200, valid.content.decode())
        self.assertEqual(client.post('/admin/login/', payload, HTTP_X_FORWARDED_PROTO='https',
                                    HTTP_ORIGIN='https://evil.example', HTTP_REFERER='https://evil.example/').status_code, 403)
