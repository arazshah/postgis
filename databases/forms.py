import re

from django import forms

from .models import Extension, UserDatabase, validate_db_label

PASSWORD_RE = re.compile(r"^[A-Za-z0-9!@#%^*_\-+=.,:~]{10,64}$")
PASSWORD_HELP = "حداقل ۱۰ کاراکتر شامل حرف بزرگ، حرف کوچک و عدد. فقط حروف انگلیسی، عدد و نمادهای ساده."


def validate_db_password(value: str):
    if not PASSWORD_RE.match(value):
        raise forms.ValidationError(PASSWORD_HELP)
    if not (re.search(r"[a-z]", value) and re.search(r"[A-Z]", value) and re.search(r"\d", value)):
        raise forms.ValidationError("رمز باید حرف بزرگ، حرف کوچک و عدد داشته باشد.")


class ExtensionChoiceField(forms.ModelMultipleChoiceField):
    widget = forms.CheckboxSelectMultiple

    def label_from_instance(self, obj):
        return obj.title


class CreateDatabaseForm(forms.Form):
    label = forms.CharField(
        label="نام پایگاه داده", max_length=41, validators=[validate_db_label],
        widget=forms.TextInput(attrs={"dir": "ltr", "placeholder": "my_gis_project", "autocomplete": "off",
                                      "spellcheck": "false"}),
        help_text="حروف کوچک انگلیسی، عدد و _ ؛ با حرف شروع شود. همین نام، نام کاربری دیتابیس هم خواهد بود.")
    password = forms.CharField(
        label="رمز عبور دیتابیس", validators=[validate_db_password], help_text=PASSWORD_HELP,
        widget=forms.TextInput(attrs={"dir": "ltr", "autocomplete": "new-password", "spellcheck": "false",
                                      "class": "mono"}))
    extensions = ExtensionChoiceField(label="افزونه‌ها", queryset=Extension.objects.none(), required=False)

    def __init__(self, *args, plan=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = plan.extensions_qs() if plan else Extension.objects.filter(is_active=True)
        self.fields["extensions"].queryset = qs
        if not self.is_bound:
            self.initial["extensions"] = list(qs.filter(is_default=True))

    def clean_label(self):
        label = self.cleaned_data["label"].strip().lower()
        if UserDatabase.objects.filter(db_name=UserDatabase.build_identifier(label)).exists():
            raise forms.ValidationError("این نام قبلاً استفاده شده است؛ نام دیگری انتخاب کنید.")
        return label

    def clean_extensions(self):
        exts = list(self.cleaned_data.get("extensions") or [])
        names = {e.name for e in exts}
        needs_postgis = {"postgis_topology", "postgis_raster", "pgrouting", "postgis_sfcgal"}
        if names & needs_postgis and "postgis" not in names:
            pg = self.fields["extensions"].queryset.filter(name="postgis").first()
            if pg:
                exts.append(pg)  # وابستگی را خودکار اضافه می‌کنیم
        return exts


class PasswordResetForm(forms.Form):
    password = forms.CharField(
        label="رمز جدید", validators=[validate_db_password], help_text=PASSWORD_HELP,
        widget=forms.TextInput(attrs={"dir": "ltr", "autocomplete": "new-password", "class": "mono"}))


class DeleteConfirmForm(forms.Form):
    confirm = forms.CharField(label="برای تأیید، نام پایگاه داده را تایپ کنید",
                              widget=forms.TextInput(attrs={"dir": "ltr", "autocomplete": "off"}))

    def __init__(self, *args, expected: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.expected = expected

    def clean_confirm(self):
        if self.cleaned_data["confirm"].strip() != self.expected:
            raise forms.ValidationError("نام وارد‌شده مطابقت ندارد.")
        return self.cleaned_data["confirm"]


class AddExtensionForm(forms.Form):
    extension = forms.ModelChoiceField(queryset=Extension.objects.none(), label="افزونه")

    def __init__(self, *args, db: UserDatabase, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["extension"].queryset = db.plan.extensions_qs().exclude(pk__in=db.extensions.values("pk"))
        self.fields["extension"].label_from_instance = lambda o: o.title
        self.fields["extension"].empty_label = "یک افزونه انتخاب کنید"
