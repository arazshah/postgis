import os
from unittest import mock

from django.test import SimpleTestCase


class CoolifyDomainTests(SimpleTestCase):
    def test_domains_parsed_from_coolify_env(self):
        env = {"SERVICE_FQDN_WEB": "https://postgis.ir,https://postgis.araz.me:443/",
               "COOLIFY_URL": "http://www.postgis.ir"}
        with mock.patch.dict(os.environ, env, clear=False):
            import importlib

            import config.settings as s
            s = importlib.reload(s)
            for host in ("postgis.ir", "postgis.araz.me", "www.postgis.ir"):
                self.assertIn(host, s.ALLOWED_HOSTS)
                self.assertIn(f"https://{host}", s.CSRF_TRUSTED_ORIGINS)
