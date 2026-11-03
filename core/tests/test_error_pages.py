from django.test import RequestFactory, TestCase, override_settings
from django.views.defaults import server_error


@override_settings(ALLOWED_HOSTS=["testserver"])
class ErrorPageTests(TestCase):
    def test_404_is_persian_with_search_and_links(self):
        r = self.client.get("/no-such-page/")
        self.assertEqual(r.status_code, 404)
        html = r.content.decode()
        self.assertIn("این صفحه پیدا نشد", html)
        self.assertIn('action="/kb/search/"', html)
        self.assertIn('href="/kb/"', html)
        self.assertIn('content="noindex, nofollow"', html)

    def test_500_is_standalone_persian_page(self):
        r = server_error(RequestFactory().get("/"))
        self.assertEqual(r.status_code, 500)
        html = r.content.decode()
        self.assertIn("مشکلی در سرور پیش آمد", html)
        self.assertNotIn("{%", html)
