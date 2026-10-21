import io
import json
from unittest import mock, skipUnless

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase

from assistant import llm, service
from assistant.models import Usage
from core.models import SiteSettings
from kb import vectors
from kb.models import Article, ArticleChunk, Category, MissedQuery

User = get_user_model()
BODY = ("## اتصال به QGIS\n\nبرای اتصال QGIS به پایگاه داده از منوی Layer گزینه Add PostGIS Layers را بزنید و میزبان، "
        "پورت و نام کاربری را وارد کنید. حالت SSL را روی require بگذارید تا اتصال رمزنگاری شود و داده‌ها امن بمانند.\n\n"
        "## عیب‌یابی\n\nاگر اتصال برقرار نشد، رمز و پورت را دوباره بررسی کنید.")


def configure(**kw):
    conf = SiteSettings.get()
    conf.assistant_enabled = True
    conf.set_assistant_api_key("sk-test-1234567890")
    for k, v in kw.items():
        setattr(conf, k, v)
    conf.save()
    return conf


def make_article(slug="qgis-connect", title="چطور از QGIS به پایگاه داده وصل شوم؟", audience="public", body=BODY,
                 keywords="کیو جی آیس, اتصال"):
    cat, _ = Category.objects.get_or_create(slug="connect", defaults={"title": "اتصال"})
    return Article.objects.create(slug=slug, category=cat, title=title, summary="از منوی Layer اتصال PostGIS را بسازید.",
                                  body=body, audience=audience, keywords=keywords)


def events(response):
    raw = b"".join(response.streaming_content).decode()
    return [json.loads(p[5:]) for p in raw.split("\n\n") if p.startswith("data:")]


def post(client, url, data, **extra):
    return client.post(url, json.dumps(data), content_type="application/json", **extra)


class AssistantBase(TestCase):
    def setUp(self):
        self.conf = configure()
        self.art = make_article()
        self.client = Client()


class ConfigTests(AssistantBase):
    def test_disabled_without_key_or_switch(self):
        self.conf.assistant_enabled = False
        self.conf.save()
        self.assertEqual(self.client.get("/assistant/config/").json(), {"enabled": False})
        self.conf.assistant_enabled = True
        self.conf.assistant_api_key_encrypted = ""
        self.conf.save()
        self.assertFalse(self.client.get("/assistant/config/").json()["enabled"])

    def test_enabled_returns_csrf_and_page_suggestions(self):
        data = self.client.get("/assistant/config/", {"path": "/dashboard/3/backups/"}).json()
        self.assertTrue(data["enabled"])
        self.assertTrue(data["csrf"])
        self.assertIn("بکاپ", " ".join(data["suggestions"]))
        self.assertIn("no-store", self.client.get("/assistant/config/")["Cache-Control"])

    def test_guest_cap_zero_hides_for_guests_only(self):
        configure(assistant_guest_daily=0)
        self.assertFalse(self.client.get("/assistant/config/").json()["enabled"])
        user = User.objects.create_user("09121110001", full_name="کاربر")
        self.client.force_login(user)
        self.assertTrue(self.client.get("/assistant/config/").json()["enabled"])

    def test_widget_script_only_when_ready(self):
        self.assertContains(self.client.get("/kb/"), "js/assistant.js")
        self.conf.assistant_enabled = False
        self.conf.save()
        self.assertNotContains(self.client.get("/kb/"), "js/assistant.js")


class AskTests(AssistantBase):
    def ask(self, message="اتصال QGIS چطور است؟", **kw):
        return post(self.client, "/assistant/ask/", {"message": message, "path": "/kb/", **kw})

    def test_requires_csrf(self):
        strict = Client(enforce_csrf_checks=True)
        self.assertEqual(post(strict, "/assistant/ask/", {"message": "سلام دنیا"}).status_code, 403)

    def test_streams_answer_with_sources_and_logs_usage_without_text(self):
        with mock.patch.object(llm, "chat_stream", return_value=iter(["از منوی Layer ", "اتصال را بسازید [1]."])):
            evs = events(self.ask())
        kinds = [e["type"] for e in evs]
        self.assertEqual(kinds, ["delta", "delta", "sources", "done"])
        self.assertEqual("".join(e["t"] for e in evs if e["type"] == "delta"), "از منوی Layer اتصال را بسازید [1].")
        src = next(e for e in evs if e["type"] == "sources")["items"][0]
        self.assertTrue(src["url"].startswith("/kb/qgis-connect/"))
        usage = Usage.objects.get()
        self.assertEqual(usage.status, "ok")
        self.assertEqual(usage.sources, ["qgis-connect"])
        self.assertTrue(evs[-1]["answered"])
        stored = " ".join(str(v) for row in Usage.objects.values("path", "mode", "status", "sources", "actor")
                          for v in row.values())
        self.assertNotIn("QGIS", stored)
        self.assertNotIn("اتصال QGIS چطور است", stored)

    def test_prompt_contains_sources_and_page_but_not_site_secrets(self):
        with mock.patch.object(llm, "chat_stream", return_value=iter(["پاسخ [1]"])) as m:
            events(self.ask(title="صفحه آزمایشی"))
        system = m.call_args.args[1][0]["content"]
        self.assertIn("Add PostGIS Layers", system)
        self.assertIn("صفحه آزمایشی", system)
        self.assertNotIn("sk-test", json.dumps(m.call_args.args[1], ensure_ascii=False))
        self.assertEqual(m.call_args.args[1][-1], {"role": "user", "content": "اتصال QGIS چطور است؟"})

    def test_marker_split_across_chunks_means_no_answer(self):
        with mock.patch.object(llm, "chat_stream", return_value=iter(["[[NO", "_ANSWER", "]]"])):
            evs = events(self.ask())
        self.assertEqual([e["type"] for e in evs], ["noanswer", "done"])
        self.assertFalse(evs[-1]["answered"])
        self.assertEqual(Usage.objects.get().status, "no_answer")
        self.assertTrue(MissedQuery.objects.exists())
        self.assertEqual(evs[0]["suggest"][0]["url"], "/kb/qgis-connect/")

    def test_no_sources_skips_llm_call(self):
        with mock.patch.object(llm, "chat_stream") as m:
            evs = events(self.ask("زرافه‌ها چقدر غذا می‌خورند؟"))
        m.assert_not_called()
        self.assertEqual(evs[0]["type"], "noanswer")

    def test_llm_error_is_generic_for_guests_and_not_counted(self):
        with mock.patch.object(llm, "chat_stream", side_effect=llm.LLMError("کلید API پذیرفته نشد")):
            evs = events(self.ask())
        self.assertEqual(evs[-1]["type"], "error")
        self.assertNotIn("کلید", evs[-1]["text"])
        self.assertEqual(Usage.objects.get().status, "error")
        configure(assistant_guest_daily=1)
        with mock.patch.object(llm, "chat_stream", return_value=iter(["ok [1]"])):
            self.assertEqual(self.ask().status_code, 200)

    def test_staff_sees_provider_error(self):
        staff = User.objects.create_admin("staffer2", "Str0ng-Pass-2", superuser=False)
        self.client.force_login(staff)
        with mock.patch.object(llm, "chat_stream", side_effect=llm.LLMError("کلید API پذیرفته نشد")):
            evs = events(self.ask())
        self.assertIn("کلید API", evs[-1]["text"])

    def test_validation(self):
        self.assertEqual(self.ask("ا").status_code, 400)
        self.assertEqual(self.ask("ب" * 501).status_code, 400)
        self.assertEqual(self.client.post("/assistant/ask/", "not json", content_type="application/json").status_code, 400)
        self.assertEqual(self.client.get("/assistant/ask/").status_code, 405)

    def test_guest_and_global_limits(self):
        configure(assistant_guest_daily=1)
        with mock.patch.object(llm, "chat_stream", return_value=iter(["پاسخ [1]"])):
            events(self.ask())
        second = self.ask()
        self.assertEqual(second.status_code, 429)
        self.assertIn("وارد حساب", second.json()["error"])
        configure(assistant_guest_daily=50, assistant_global_daily=1)
        self.assertEqual(self.ask().status_code, 429)

    def test_disabled_returns_403(self):
        self.conf.assistant_enabled = False
        self.conf.save()
        self.assertEqual(self.ask().status_code, 403)

    def test_history_is_cleaned_and_limited(self):
        raw = [{"role": "system", "content": "x"}, {"role": "user", "content": "الف" * 900},
               {"role": "assistant", "content": 5}] + [{"role": "user", "content": f"پرسش {i}"} for i in range(20)]
        hist = service.clean_history(raw)
        self.assertLessEqual(len(hist), 8)
        self.assertTrue(all(h["role"] in ("user", "assistant") and len(h["content"]) <= 600 for h in hist))

    def test_path_outside_site_is_dropped(self):
        with mock.patch.object(llm, "chat_stream", return_value=iter(["پاسخ [1]"])):
            events(self.ask(path="//evil.example"))
        self.assertEqual(Usage.objects.get().path, "")


class AudienceTests(AssistantBase):
    def test_staff_only_article_never_retrieved_for_guest_or_member(self):
        make_article(slug="internal", title="رمز ادمین داخلی سرور", audience="staff",
                     body="## داخلی\n\nرمز ادمین سرور مشتریان و آدرس داخلی آن در این بخش آمده است.", keywords="رمز ادمین")
        guest, _ = service.retrieve(self.conf, None, "رمز ادمین سرور")
        self.assertNotIn("internal", [s.slug for s in guest])
        member = User.objects.create_user("09121110002", full_name="عضو")
        found, _ = service.retrieve(self.conf, member, "رمز ادمین سرور")
        self.assertNotIn("internal", [s.slug for s in found])
        staff = User.objects.create_admin("staffer", "Str0ng-Pass-1", superuser=False)
        found, _ = service.retrieve(self.conf, staff, "رمز ادمین سرور")
        self.assertIn("internal", [s.slug for s in found])

    def test_draft_not_retrieved(self):
        art = make_article(slug="draft-one", title="پیش‌نویس محرمانه نقشه", keywords="محرمانه")
        art.status = Article.Status.DRAFT
        art.save()
        found, _ = service.retrieve(self.conf, None, "پیش‌نویس محرمانه نقشه")
        self.assertNotIn("draft-one", [s.slug for s in found])


class FeedbackTests(AssistantBase):
    def test_feedback_requires_matching_token_and_actor(self):
        with mock.patch.object(llm, "chat_stream", return_value=iter(["پاسخ [1]"])):
            evs = events(post(self.client, "/assistant/ask/", {"message": "اتصال QGIS چطور است؟"}))
        done = evs[-1]
        bad = post(self.client, "/assistant/feedback/", {"id": done["id"], "token": "x", "helpful": True})
        self.assertFalse(bad.json()["ok"])
        other = post(Client(), "/assistant/feedback/", {"id": done["id"], "token": done["token"], "helpful": True},
                     REMOTE_ADDR="9.9.9.9")
        self.assertFalse(other.json()["ok"])
        ok = post(self.client, "/assistant/feedback/", {"id": done["id"], "token": done["token"], "helpful": False})
        self.assertTrue(ok.json()["ok"])
        self.assertIs(Usage.objects.get().helpful, False)
        self.assertEqual(post(self.client, "/assistant/feedback/", {"id": 1, "token": "t", "helpful": "yes"}).status_code, 400)


class LLMClientTests(TestCase):
    def setUp(self):
        self.conf = configure(assistant_base_url="https://api.avalai.ir/v1")

    def _resp(self, payload=None, lines=None):
        body = io.BytesIO(json.dumps(payload).encode() if payload is not None else b"".join(lines))
        cm = mock.MagicMock()
        cm.__enter__.return_value = body
        return cm

    def test_embed_orders_by_index_and_checks_count(self):
        data = {"data": [{"index": 1, "embedding": [2.0]}, {"index": 0, "embedding": [1.0]}]}
        with mock.patch.object(llm, "_open", return_value=self._resp(data)) as m:
            self.assertEqual(llm.embed(self.conf, ["a", "b"]), [[1.0], [2.0]])
        self.assertEqual(m.call_args.args[1], "/embeddings")
        with mock.patch.object(llm, "_open", return_value=self._resp({"data": [{"index": 0, "embedding": [1.0]}]})):
            with self.assertRaises(llm.LLMError):
                llm.embed(self.conf, ["a", "b"])

    def test_chat_stream_parses_sse(self):
        lines = [b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n', b"\n",
                 'data: {"choices":[{"delta":{"content":"سلام"}}]}\n'.encode(),
                 'data: {"choices":[{"delta":{"content":" دنیا"}}]}\n'.encode(), b"data: [DONE]\n"]
        with mock.patch.object(llm, "_open", return_value=self._resp(lines=lines)):
            self.assertEqual("".join(llm.chat_stream(self.conf, [])), "سلام دنیا")

    def test_http_scheme_rejected_and_key_required(self):
        self.conf.assistant_base_url = "http://insecure.example/v1"
        with self.assertRaises(llm.LLMError):
            llm._base(self.conf)
        self.conf.assistant_api_key_encrypted = ""
        self.conf.assistant_base_url = "https://x.example/v1"
        with self.assertRaises(llm.LLMError):
            llm._open(self.conf, "/embeddings", {}, 5)


class AdminSettingsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_admin("adm", "Str0ng-Admin-Pass")
        self.client.force_login(self.admin)

    def _form(self, **over):
        from core.admin import SiteSettingsForm

        conf = SiteSettings.get()
        data = {}
        for name, field in SiteSettingsForm(instance=conf).fields.items():
            val = SiteSettingsForm(instance=conf).initial.get(name, field.initial)
            if isinstance(val, bool):
                if val:
                    data[name] = "on"
            elif val is not None:
                data[name] = val
        data.update(over)
        return SiteSettingsForm(data, instance=conf)

    def test_key_encrypted_and_never_rendered(self):
        form = self._form(assistant_api_key="  sk-abc 123456  ", assistant_enabled="on")
        self.assertTrue(form.is_valid(), form.errors)
        obj = form.save()
        self.assertNotIn("sk-abc", obj.assistant_api_key_encrypted)
        self.assertEqual(obj.get_assistant_api_key(), "sk-abc123456")
        page = self.client.get("/manage/core/sitesettings/1/change/")
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "sk-abc123456")
        self.assertContains(page, "دستیار هوشمند")

    def test_empty_key_field_keeps_existing_and_clear_removes(self):
        conf = configure()
        form = self._form(assistant_api_key="")
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertTrue(SiteSettings.get().assistant_api_key_encrypted)
        form = self._form(clear_assistant_api_key="on")
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertFalse(SiteSettings.get().assistant_key_ready)
        self.assertFalse(conf.pk is None)

    def test_base_url_must_be_https(self):
        form = self._form(assistant_base_url="http://api.example/v1")
        self.assertFalse(form.is_valid())
        self.assertIn("assistant_base_url", form.errors)

    def test_test_and_embed_tools(self):
        configure()
        with mock.patch.object(llm, "ping", return_value={"dims": 1536, "reply": "آماده"}):
            r = self.client.get("/manage/core/sitesettings/assistant-test/", follow=True)
        self.assertContains(r, "1536")
        with mock.patch.object(llm, "ping", side_effect=llm.LLMError("کلید API پذیرفته نشد")):
            r = self.client.get("/manage/core/sitesettings/assistant-test/", follow=True)
        self.assertContains(r, "آزمایش ناموفق بود")
        with mock.patch.object(llm, "embed", side_effect=lambda conf, texts: [[0.1, 0.2, 0.3] for _ in texts]):
            r = self.client.get("/manage/core/sitesettings/assistant-embed/", follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "ناموفق")

    def test_usage_admin_lists(self):
        Usage.objects.create(actor="g:x", status="ok")
        self.assertEqual(self.client.get("/manage/assistant/usage/").status_code, 200)


class MaintenanceTests(TestCase):
    def test_deletes_old_usage_and_skips_embedding_when_off(self):
        from datetime import timedelta

        from django.utils import timezone

        from assistant.services_maintenance import maintenance

        old = Usage.objects.create(actor="g:a")
        Usage.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=120))
        Usage.objects.create(actor="g:b")
        with mock.patch("kb.embedding.embed_pending") as m:
            out = maintenance()
        self.assertEqual(out["deleted"], 1)
        m.assert_not_called()
        configure()
        with mock.patch("kb.embedding.embed_pending", return_value={"embedded": 3, "remaining": 0, "error": ""}) as m:
            self.assertEqual(maintenance()["embedded"], 3)
        m.assert_called_once()


@skipUnless(connection.vendor == "postgresql", "فقط روی PostgreSQL")
class VectorTests(AssistantBase):
    def setUp(self):
        super().setUp()
        if not vectors.setup():
            self.skipTest("pgvector روی این پایگاه داده نیست")

    def test_store_nearest_pending_and_audience(self):
        other = make_article(slug="other", title="موضوع دیگر درباره بکاپ", body="## بکاپ\n\nبکاپ شبانه ساعت سه گرفته می‌شود و نگهداری می‌شود.")
        chunk_a = ArticleChunk.objects.filter(article=self.art).first()
        chunk_b = ArticleChunk.objects.filter(article=other).first()
        self.assertEqual(len(vectors.pending("m1")), ArticleChunk.objects.count())
        vectors.store(chunk_a.pk, [1, 0, 0], "m1")
        vectors.store(chunk_b.pk, [0, 1, 0], "m1")
        self.assertEqual(vectors.pending("m1"), [c.pk for c in ArticleChunk.objects.exclude(pk__in=[chunk_a.pk, chunk_b.pk])])
        self.assertEqual(vectors.nearest([0.9, 0.1, 0], "m1", [self.art.pk, other.pk], 2)[0][0], chunk_a.pk)
        self.assertEqual([c for c, _ in vectors.nearest([0.9, 0.1, 0], "m1", [other.pk], 2)], [chunk_b.pk])
        self.assertEqual(vectors.nearest([1, 0, 0], "other-model", [self.art.pk], 2), [])
        self.assertEqual(vectors.nearest([1, 0], "m1", [self.art.pk], 2), [])  # بُعد ناسازگار خطا نمی‌دهد

    def test_retrieve_uses_vector_hits_first(self):
        other = make_article(slug="other2", title="موضوع نامرتبط", body="## بکاپ\n\nبکاپ شبانه ساعت سه گرفته می‌شود و نگهداری می‌شود.")
        target = ArticleChunk.objects.filter(article=other).first()
        vectors.store(target.pk, [0, 0, 1], self.conf.assistant_embedding_model)
        with mock.patch.object(llm, "embed", return_value=[[0, 0, 1]]):
            sources, mode = service.retrieve(self.conf, None, "چطور وصل شوم")
        self.assertEqual(mode, "vector")
        self.assertEqual(sources[0].slug, "other2")


class SuggestionTests(TestCase):
    def test_defaults_and_rules(self):
        self.assertEqual(service.suggestions("/"), service._SUGGEST_DEFAULT)
        self.assertIn("SRID", service.suggestions("/dashboard/1/explore/")[0])
