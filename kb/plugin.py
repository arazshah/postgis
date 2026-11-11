"""مانیفست پلاگین «پایگاه دانش» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import nav, plugins

plugin = plugins.register("kb", "پایگاه دانش", kind="system")

nav.admin_item("support", "kb.article", None, plugin=plugin.id, order=20)
nav.admin_item("support", "kb.category", None, plugin=plugin.id, order=30)
nav.admin_item("support", "kb.missedquery", None, plugin=plugin.id, order=40)
nav.admin_item("support", "kb.feedback", None, plugin=plugin.id, order=50)
nav.admin_quick("مقاله‌ی تازه", "book", "admin:kb_article_add", plugin=plugin.id, order=30)
