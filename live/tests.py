from unittest import mock

from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from analysis.models import ToolRun
from databases import services
from databases.tests.test_services import BaseCase
from maps.models import WebMap

from .models import LiveTicket


class LiveTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.db = services.create_database(self.user, "livegis", "Abcdefgh123", [])
        self.client.force_login(self.user)

    def test_create_project_and_open(self):
        response = self.client.post(reverse("live:projects", args=[self.db.pk]), {"title": "نقشه من"})
        project = WebMap.objects.get(database=self.db)
        self.assertRedirects(response, reverse("live:studio", args=[self.db.pk, project.pk]),
                             fetch_redirect_response=False)
        with mock.patch("live.views.maps.spatial_tables", return_value=[]):
            response = self.client.get(reverse("live:studio", args=[self.db.pk, project.pk]))
        self.assertContains(response, "PostGIS")
        self.assertContains(response, "نقشه من")

    def test_unrelated_user_cannot_open_or_read(self):
        project = WebMap.objects.create(database=self.db, title="private")
        self.client.force_login(User.objects.create_user("09120000002"))
        for name, args in [("live:projects", [self.db.pk]), ("live:studio", [self.db.pk, project.pk]),
                           ("live:table", [self.db.pk])]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 404)
        self.assertEqual(self.client.post(reverse("live:tool", args=[self.db.pk]), {"key": "buffer"}).status_code, 404)

    def test_anonymous_redirected(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("live:index")).status_code, 302)

    def test_tool_uses_existing_queue(self):
        with mock.patch("tools.api.engine.validate", return_value="buffer_result"), \
                mock.patch("tools.api.engine.summarize", return_value="buffer"):
            url = reverse("live:tool", args=[self.db.pk])
            response = self.client.post(url, {"key": "buffer", "output": "buffer_result"})
            self.assertEqual(response.status_code, 200)
            run = ToolRun.objects.get(database=self.db)
            self.assertEqual(run.output_table, "buffer_result")
            self.assertEqual(self.client.get(response.json()["url"]).json()["status"], "queued")
            self.assertEqual(self.client.post(url, {"key": "buffer", "output": "buffer_result"}).status_code, 400)


@override_settings(LIVE_SSO_ENABLED=True, ALLOWED_HOSTS=["postgis.ir", "live.postgis.ir"],
                   LIVE_MAIN_ORIGIN="https://postgis.ir", LIVE_ORIGIN="https://live.postgis.ir")
class LiveSSOTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.db = services.create_database(self.user, "liveauth", "Abcdefgh123", [])
        self.client.force_login(self.user)
        self.live = Client(HTTP_HOST="live.postgis.ir")

    def issue(self):
        response = self.client.post(reverse("live:launch", args=[self.db.pk]),
                                    secure=True, HTTP_HOST="postgis.ir")
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers["Cache-Control"])
        return response.context["ticket"]

    def exchange(self, ticket, origin="https://postgis.ir"):
        return self.live.post(reverse("live:exchange"), {"ticket": ticket}, secure=True, HTTP_ORIGIN=origin)

    def test_direct_live_and_login_require_main(self):
        for path in ("/", "/live/", reverse("accounts:login"), "/dashboard/"):
            self.assertIn("/live/auth/login/", self.live.get(path, secure=True).url)
        self.assertEqual(self.client.get("/live/", secure=True, HTTP_HOST="postgis.ir").url,
                         "https://postgis.ir/dashboard/")

    def test_handoff_one_time_and_main_logout(self):
        ticket = self.issue()
        self.assertFalse(LiveTicket.objects.filter(digest=ticket).exists())
        response = self.exchange(ticket)
        self.assertEqual(response.url, reverse("live:projects", args=[self.db.pk]))
        self.assertEqual(self.live.get(response.url, secure=True).status_code, 200)
        second = Client(HTTP_HOST="live.postgis.ir")
        self.assertEqual(second.post(reverse("live:exchange"), {"ticket": ticket}, secure=True,
                                     HTTP_ORIGIN="https://postgis.ir").url, "https://postgis.ir/dashboard/")
        self.client.logout()
        self.assertIn("/live/auth/login/", self.live.get(response.url, secure=True).url)

    def test_wrong_origin_and_expired_ticket(self):
        ticket = self.issue()
        self.assertEqual(self.exchange(ticket, "https://example.org").status_code, 403)
        LiveTicket.objects.update(expires_at=timezone.now())
        self.assertEqual(self.exchange(ticket).url, "https://postgis.ir/dashboard/")

    def test_leave_does_not_end_parent_session(self):
        self.exchange(self.issue())
        self.assertEqual(self.live.post(reverse("live:leave"), secure=True).url, reverse("live:auth", args=["login"]))
        self.assertIn("/live/auth/login/", self.live.get("/live/", secure=True).url)
        self.assertEqual(self.client.get("/dashboard/", secure=True, HTTP_HOST="postgis.ir").status_code, 200)

    def test_launch_checks_workspace_and_csrf(self):
        other = User.objects.create_user("09120000003")
        self.client.force_login(other)
        self.assertEqual(self.client.post(reverse("live:launch", args=[self.db.pk]), secure=True,
                                          HTTP_HOST="postgis.ir").status_code, 404)
        csrf_client = Client(enforce_csrf_checks=True, HTTP_HOST="postgis.ir")
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(reverse("live:launch", args=[self.db.pk]), secure=True).status_code, 403)
