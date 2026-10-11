import re

from django import forms

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
MAX_RECEIPT = 5 * 1024 * 1024


class ReceiptForm(forms.Form):
    receipt = forms.ImageField(label="تصویر رسید (اسکرین‌شات اپ بانک)",
                               help_text="JPG یا PNG، حداکثر ۵ مگابایت.")
    last4 = forms.CharField(label="۴ رقم آخر کارتی که از آن واریز کردید", max_length=8,
                            widget=forms.TextInput(attrs={"dir": "ltr", "inputmode": "numeric", "class": "mono"}))
    tracking = forms.CharField(label="شماره پیگیری / مرجع (اختیاری)", max_length=40, required=False,
                               widget=forms.TextInput(attrs={"dir": "ltr", "class": "mono"}))
    paid_time = forms.CharField(label="ساعت واریز (اختیاری)", max_length=40, required=False,
                                widget=forms.TextInput(attrs={"placeholder": "مثلاً ۱۴:۳۵"}))

    def clean_receipt(self):
        f = self.cleaned_data["receipt"]
        if f.size > MAX_RECEIPT:
            raise forms.ValidationError("حجم تصویر بیش از ۵ مگابایت است.")
        return f

    def clean_last4(self):
        v = re.sub(r"\D", "", self.cleaned_data["last4"].translate(_DIGITS))
        if len(v) != 4:
            raise forms.ValidationError("دقیقاً ۴ رقم وارد کنید.")
        return v

    def clean_tracking(self):
        return self.cleaned_data.get("tracking", "").translate(_DIGITS).strip()
