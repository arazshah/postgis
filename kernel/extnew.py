"""داربست پلاگین سطح ۳ (`manage.py ext_new <id> --name "…"`): پلاگینی می‌سازد که از `ext_check` و آزمون خودش می‌گذرد.

قالب‌ها رشته‌اند تا نصب نشدنی‌های خراب را نشود با آن‌ها ساخت؛ هرچه می‌سازد فقط SDK هسته (`kernel.*`) و مدل‌های مجاز را می‌شناسد.
بدون وابستگی به جنگو و هیچ اپی (منطق فایل‌نویسی؛ فرمان نازک است).
"""
from __future__ import annotations

import re
from pathlib import Path
from textwrap import dedent

ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
NAME_MAX = 60


class ScaffoldError(Exception):
    pass


def _files(pid: str, name: str) -> dict[str, str]:
    cls = "".join(p.capitalize() for p in pid.split("_")) + "Config"
    q = repr(name)
    return {
        "__init__.py": "",
        "apps.py": dedent(f'''\
            from django.apps import AppConfig


            class {cls}(AppConfig):
                name = "ext.{pid}"
                label = "x_{pid}"  # پیشوند جدول‌ها؛ تغییرش ممنوع است
                verbose_name = {q}
            '''),
        "plugin.py": dedent(f'''\
            """مانیفست پلاگین سطح ۳ «{name}» (docs/adr/0007)."""
            from kernel import nav, plugins, routes

            plugin = plugins.register("{pid}", {q}, kind="custom", tier=3, version="1.0.0")

            routes.add("ws_ext", "{pid}/", "ext.{pid}.views.index", "{pid}_index", plugin=plugin.id)
            routes.add("ws_ext", "{pid}/add/", "ext.{pid}.views.add", "{pid}_add", plugin=plugin.id)

            nav.ws_section("manage", {q}, "ws_ext:{pid}_index", "gauge", "viewer", plugin=plugin.id, order=90)
            '''),
        "models.py": dedent(f'''\
            from django.db import models


            class Note(models.Model):
                """نمونه: جدول `x_{pid}_note`. حذف پایگاه داده، یادداشت‌هایش را هم پاک می‌کند."""

                db = models.ForeignKey("databases.UserDatabase", on_delete=models.CASCADE, related_name="+")
                text = models.CharField(max_length=200)
                created_at = models.DateTimeField(auto_now_add=True)

                class Meta:
                    ordering = ["-created_at"]
            '''),
        "migrations/__init__.py": "",
        "migrations/0001_initial.py": dedent('''\
            from django.db import migrations, models
            import django.db.models.deletion


            class Migration(migrations.Migration):
                initial = True
                dependencies = [("databases", "0001_initial")]
                operations = [
                    migrations.CreateModel(
                        name="Note",
                        fields=[
                            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                            ("text", models.CharField(max_length=200)),
                            ("created_at", models.DateTimeField(auto_now_add=True)),
                            ("db", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+",
                                                     to="databases.userdatabase")),
                        ],
                        options={"ordering": ["-created_at"]},
                    ),
                ]
            '''),
        "views.py": dedent(f'''\
            from django.contrib import messages
            from django.contrib.auth.decorators import login_required
            from django.shortcuts import redirect, render
            from django.views.decorators.http import require_http_methods

            from kernel import workspace

            from .models import Note


            @login_required
            def index(request, pk):
                db = workspace.get(request, pk, "viewer")
                return render(request, "x_{pid}/index.html", {{"db": db, "notes": Note.objects.filter(db=db)[:50]}})


            @login_required
            @require_http_methods(["POST"])
            def add(request, pk):
                db = workspace.get(request, pk, "editor")
                text = request.POST.get("text", "").strip()[:200]
                if text:
                    Note.objects.create(db=db, text=text)
                else:
                    messages.error(request, "متن را بنویسید.")
                return redirect("ws_ext:{pid}_index", pk=db.pk)
            '''),
        f"templates/x_{pid}/index.html": dedent(f'''\
            {{% extends "databases/_ws.html" %}}
            {{% block title %}}{name} — {{{{ SITE_NAME }}}}{{% endblock %}}
            {{% block ws %}}
            <div class="wrap page">
              <div class="page-head"><div><h1>{name}</h1><p class="muted page-sub">پلاگین سطح ۳؛ این صفحه را با داربست ساخته‌اید.</p></div></div>
              <section class="card">
                <div class="ch"><h2>یادداشت‌ها</h2></div>
                {{% for n in notes %}}<p>{{{{ n.text }}}}</p>{{% empty %}}<p class="muted">هنوز یادداشتی نیست.</p>{{% endfor %}}
                <form method="post" action="{{% url 'ws_ext:{pid}_add' db.pk %}}">{{% csrf_token %}}
                  <input name="text" maxlength="200" required>
                  <button class="btn">افزودن</button>
                </form>
              </section>
            </div>
            {{% endblock %}}
            '''),
        "tests/__init__.py": "",
        "tests/test_basic.py": dedent(f'''\
            from django.test import TestCase

            from kernel.plugins import registry


            class BasicTests(TestCase):
                def test_registered_as_tier3(self):
                    p = registry.plugins["{pid}"]
                    self.assertEqual((p.tier, p.kind), (3, "custom"))

                def test_table_has_plugin_prefix(self):
                    from .. import models

                    self.assertEqual(models.Note._meta.db_table, "x_{pid}_note")
            '''),
        "README.md": f"# {name}\n\nپلاگین سطح ۳ (`ext/{pid}/`، docs/plugins/tier3.md).\n\n"
                     f"- بررسی: `python manage.py ext_check {pid}`\n- آزمون: `python manage.py test ext.{pid}`\n",
    }


def scaffold(root: Path, pid: str, name: str) -> list[Path]:
    """`root/<pid>` را می‌سازد (وجود داشته باشد خطا). فهرست فایل‌های ساخته‌شده را برمی‌گرداند."""
    if not ID_RE.fullmatch(pid):
        raise ScaffoldError("شناسه: حرف کوچک انگلیسی، عدد و _ (۲ تا ۴۱ نویسه، با حرف شروع شود).")
    name = (name or pid).strip()
    if not name or len(name) > NAME_MAX or any(c in name for c in "\n\r\\\"'{}%"):
        raise ScaffoldError(f"نام نمایشی: حداکثر {NAME_MAX} نویسه، بدون نقل‌قول، آکولاد و درصد.")
    target = root / pid
    if target.exists():
        raise ScaffoldError(f"{target} از قبل هست.")
    made = []
    for rel, text in _files(pid, name).items():
        f = target / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
        made.append(f)
    return made
