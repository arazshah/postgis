"""قرارداد فضای کار: دسترسی از ارائه‌دهنده‌ی ثبت‌شده و سازگاری ثابت‌ها با پیاده‌سازی تیم."""
from types import SimpleNamespace
from unittest import mock

from django.http import Http404
from django.test import SimpleTestCase, TestCase

from kernel import workspace


class FakeProvider(workspace.Provider):
    def get(self, request, pk, need="owner", qs=None):
        if need == "owner":
            raise Http404
        return SimpleNamespace(pk=pk, need=need)

    def level(self, user, ws):
        return workspace.EDITOR

    def shared_with(self, user):
        return ["x"]

    def extra_role_name(self, ws, suffix):
        return f"r_{suffix}"


class DelegationTests(SimpleTestCase):
    def test_functions_delegate_to_the_registered_provider(self):
        with mock.patch.object(workspace, "_provider", FakeProvider()):
            self.assertEqual(workspace.get(None, 5, "viewer").need, "viewer")
            with self.assertRaises(Http404):
                workspace.get(None, 5)
            self.assertEqual(workspace.level(None, None), workspace.EDITOR)
            self.assertEqual(workspace.shared_with(None), ["x"])
            self.assertEqual(workspace.extra_role_name(None, "geo"), "r_geo")

    def test_missing_provider_is_a_clear_error(self):
        with mock.patch.object(workspace, "_provider", None):
            with self.assertRaises(workspace.WorkspaceError):
                workspace.level(None, None)

    def test_base_provider_is_abstract(self):
        with self.assertRaises(NotImplementedError):
            workspace.Provider().level(None, None)


class InstalledProviderTests(TestCase):
    def test_team_provider_is_registered_and_levels_match(self):
        from databases import team
        from databases.gateway import TeamProvider

        self.assertIsInstance(workspace.provider(), TeamProvider)
        self.assertEqual((workspace.VIEWER, workspace.EDITOR, workspace.OWNER), (team.VIEWER, team.EDITOR, team.OWNER))
        self.assertEqual(workspace.LEVELS, team.LEVELS)

    def test_anonymous_has_no_level_and_unknown_workspace_is_404(self):
        from django.contrib.auth.models import AnonymousUser
        from django.test import RequestFactory

        req = RequestFactory().get("/")
        req.user = AnonymousUser()
        self.assertEqual(workspace.level(req.user, SimpleNamespace(owner_id=1)), 0)
        with self.assertRaises(Http404):
            workspace.get(req, 999999, "viewer")
