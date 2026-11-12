"""نرمال‌سازی متن فارسی و شکستن نشانی (برای ژئوکدر؛ ADR-0009 مرحله‌ی ۵). بدون وابستگی؛ خالص و آزمون‌پذیر.

هدف «مقایسه‌ی پایدار» است نه زیبایی: ی/ي، ک/ك، آ/ا، ارقام فارسی/عربی/لاتین، اعراب، کشیده، نیم‌فاصله و فاصله‌های تکراری یکی می‌شوند.
"""
from __future__ import annotations

import re

_CHARS = str.maketrans({"ي": "ی", "ى": "ی", "ئ": "ی", "ك": "ک", "ة": "ه", "ۀ": "ه", "ە": "ه", "أ": "ا", "إ": "ا", "آ": "ا", "ؤ": "و",
                        "‌": " ", "ـ": "", "‍": "", "‎": "", "‏": "", "\xa0": " "})
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_MARKS = re.compile("[ً-ٰٟ]")  # اعراب و همزه‌ی بالا
_PUNCT = re.compile(r"[^\w\s]|_", re.UNICODE)
_SPACES = re.compile(r"\s+")
_ABBR = [(re.compile(r"(?<!\S)خ\s*\."), "خیابان "), (re.compile(r"(?<!\S)ک\s*\."), "کوچه "), (re.compile(r"(?<!\S)م\s*\."), "میدان "),
         (re.compile(r"(?<!\S)بل\s*\."), "بلوار "), (re.compile(r"(?<!\S)ب\s*\."), "بلوار "), (re.compile(r"(?<!\S)ش\s*\."), "شهرک ")]

#: نوع معبر (پس از نرمال‌سازی) ← نام استاندارد
STREET_TYPES = {"خیابان": "street", "بلوار": "street", "میدان": "square", "کوچه": "alley", "بن بست": "alley", "چهارراه": "square",
                "اتوبان": "highway", "بزرگراه": "highway", "جاده": "highway", "فلکه": "square", "کوی": "quarter", "شهرک": "quarter",
                "محله": "quarter", "پل": "bridge", "تقاطع": "square", "گذر": "alley", "بازارچه": "alley"}
#: عنوان‌هایی که در مقایسه‌ی «هسته‌ی نام» کنار گذاشته می‌شوند
TITLES = {"دکتر", "شهید", "شهدا", "امام", "استاد", "سردار", "حاج", "حاجی", "آیت", "اله", "الله", "علامه", "مرحوم", "سرهنگ", "سرلشکر",
          "سپهبد", "شهیده", "مهندس", "حضرت", "حجت", "السلام", "ع", "ره", "خیابان", "بلوار", "میدان", "کوچه", "اتوبان", "بزرگراه",
          "جاده", "فلکه", "کوی", "شهرک", "محله", "پل", "بن", "بست", "چهارراه", "تقاطع", "گذر", "بازارچه", "فرعی", "اصلی", "اول", "دوم"}
NOISE = {"ایران", "استان", "شهر", "شهرستان", "تهران ایران", "کدپستی", "کد", "پستی", "طبقه", "واحد", "ساختمان", "نبش", "روبروی", "جنب", "ضلع"}
_NUMBER = re.compile(r"(?:پلاک|پ)\s*[:.\-]?\s*(\d{1,5})", re.U)
_SPLIT = re.compile(r"[،,;\n\r\t|/\\]+|\s-\s")


def normalize(text: str) -> str:
    """رشته‌ی مقایسه: یکدست‌شده، بدون علامت، تک‌فاصله، با ارقام لاتین (ریزحروف لاتین هم)."""
    t = (text or "").translate(_CHARS)
    t = _MARKS.sub("", t).translate(_DIGITS).lower()
    for pat, rep in _ABBR:
        t = pat.sub(rep, t)
    return _SPACES.sub(" ", _PUNCT.sub(" ", t)).strip()


def tokens(text: str) -> list[str]:
    return normalize(text).split()


def core(text: str) -> str:
    """هسته‌ی نام: بدون نوع معبر و عنوان‌ها (مثلاً «خیابان دکتر شریعتی» ← «شریعتی»)؛ اگر چیزی نماند، خودِ نرمال‌شده."""
    t = [w for w in tokens(text) if w not in TITLES]
    return " ".join(t) or normalize(text)


def street_type(text: str) -> str:
    """نوع معبر اگر در متن آمده (نخستین)، وگرنه ''."""
    n = " " + normalize(text) + " "
    for k in sorted(STREET_TYPES, key=len, reverse=True):
        if f" {k} " in n:
            return k
    return ""


def parse_address(text: str) -> dict:
    """نشانی آزاد ← {parts, number, street, street_type, noise_removed}. فقط روش ابتکاری؛ هیچ‌چیز را «حدس‌زده» به‌عنوان قطعی نمی‌دهد.

    parts: بخش‌های جداشده با ویرگول/خط (نرمال‌شده، بدون نویز)؛ street: بخشی که نوع معبر دارد؛ number: پلاک.
    """
    raw = text or ""
    m = _NUMBER.search(normalize(raw).replace("پلاک", " پلاک ") if False else normalize(raw))
    number = m.group(1) if m else ""
    parts = []
    for p in _SPLIT.split(raw):
        n = normalize(p)
        n = _NUMBER.sub(" ", n)
        words = [w for w in n.split() if w not in NOISE]
        if words:
            parts.append(" ".join(words))
    street = next((p for p in parts if street_type(p)), "")
    return {"parts": parts, "number": number, "street": street, "street_type": street_type(street) if street else ""}
