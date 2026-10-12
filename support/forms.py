from django import forms

from databases.models import Plan, UserDatabase

from .models import Ticket

MAX_FILE = 5 * 1024 * 1024
ALLOWED_EXT = {"png", "jpg", "jpeg", "webp", "pdf", "txt", "log", "sql", "csv", "zip"}


def clean_attachment(f):
    if not f:
        return f
    if f.size > MAX_FILE:
        raise forms.ValidationError("حجم فایل بیش از ۵ مگابایت است.")
    ext = f.name.rsplit(".", 1)[-1].lower() if "." in f.name else ""
    if ext not in ALLOWED_EXT:
        raise forms.ValidationError("فقط تصویر، PDF، متن، CSV، SQL یا ZIP قابل ارسال است.")
    return f


class NewTicketForm(forms.Form):
    category = forms.ChoiceField(label="دسته", choices=Ticket.Category.choices)
    subject = forms.CharField(label="موضوع", max_length=150)
    database = forms.ModelChoiceField(label="پایگاه داده مرتبط (اختیاری)", queryset=UserDatabase.objects.none(),
                                      required=False, empty_label="—")
    plan = forms.ModelChoiceField(label="پلن مورد نظر (اختیاری)", queryset=Plan.objects.none(), required=False,
                                  empty_label="—")
    body = forms.CharField(label="شرح درخواست", widget=forms.Textarea(attrs={"rows": 7}), max_length=5000)
    attachment = forms.FileField(label="پیوست (اختیاری)", required=False,
                                 help_text="تصویر خطا، PDF، لاگ یا فایل SQL؛ حداکثر ۵ مگابایت.")

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["database"].queryset = user.databases.exclude(status=UserDatabase.Status.DELETED)
        self.fields["plan"].queryset = Plan.objects.filter(is_public=True)
        self.fields["database"].label_from_instance = lambda d: d.db_name
        if not self.fields["database"].queryset.exists():
            del self.fields["database"]

    def clean_attachment(self):
        return clean_attachment(self.cleaned_data.get("attachment"))


class ReplyForm(forms.Form):
    body = forms.CharField(label="پاسخ شما", widget=forms.Textarea(attrs={"rows": 5}), max_length=5000)
    attachment = forms.FileField(label="پیوست (اختیاری)", required=False)

    def clean_attachment(self):
        return clean_attachment(self.cleaned_data.get("attachment"))
