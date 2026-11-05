"""زبانه‌بندی فرم‌های طولانی پنل مدیریت: هر fieldset با کلاس `ap-tab-<کلید>` به یک زبانه می‌رود."""


class TabbedAdminMixin:
    change_form_template = "admin/tabbed_form.html"
    tabs: list[tuple[str, str, str]] = []  # (کلید، عنوان، آیکون)

    def tab_status(self, request, obj) -> dict[str, tuple[str, str]]:
        """کلید زبانه ← (ok|warn|bad، متن کوتاه) برای نشان وضعیت کنار عنوان."""
        return {}

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        status = {} if add else self.tab_status(request, obj)
        context["ap_tabs"] = [
            {"key": k, "label": label, "icon": icon, "state": status.get(k, ("", ""))[0],
             "detail": status.get(k, ("", ""))[1]}
            for k, label, icon in self.tabs
        ]
        return super().render_change_form(request, context, add, change, form_url, obj)
