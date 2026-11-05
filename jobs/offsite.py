"""
نسخه‌ی دوم بکاپ‌ها در فضای ابری سازگار با S3 (مثلاً باکت پارس‌پک)، بیرون از سرور اصلی.

- هر بکاپ پیش از ارسال با AES-256-GCM (به‌صورت قطعه‌قطعه، بدون بار کردن کل فایل در حافظه) رمزنگاری می‌شود.
- کلید رمزنگاری از `CREDENTIALS_ENCRYPTION_KEY` (یا `SECRET_KEY`) مشتق می‌شود؛ یک نسخه از آن را بیرون از سرور نگه دارید.
  بدون آن کلید، فایل‌های فضای ابری باز نمی‌شوند (دستور `decrypt_backup` برای بازیابی دستی).
- اگر ارسال شکست بخورد، خود بکاپ شکست نمی‌خورد؛ خطا روی کار ثبت می‌شود و در دور بعدی worker دوباره تلاش می‌شود.
"""
from __future__ import annotations

import hashlib
import logging
import os
import struct
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.utils import timezone

from core.models import SiteSettings

log = logging.getLogger(__name__)

MAGIC = b"GPBK1\n"
CHUNK = 1024 * 1024  # ۱ مگابایت متن ساده در هر قطعه
SALT_LEN = 16
MAX_RETRY_PER_TICK = 5


class OffsiteError(Exception):
    pass


# ---------------------------------------------------------------------- رمزنگاری قطعه‌ای
def _master_secret() -> bytes:
    return (settings.CREDENTIALS_ENCRYPTION_KEY or settings.SECRET_KEY).encode()


def _derive_key(salt: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=b"geopaygah-offsite-backup").derive(_master_secret())


def key_fingerprint() -> str:
    """اثر انگشت کوتاه کلید فعلی؛ برای تطبیق با نسخه‌ی نگه‌داری‌شده بیرون از سرور (خود کلید هرگز نمایش داده نمی‌شود)."""
    return hashlib.sha256(b"fp:" + _derive_key(b"\0" * SALT_LEN)).hexdigest()[:10]


def _nonce(index: int) -> bytes:
    return index.to_bytes(12, "big")


def encrypt_file(src: Path, dst: Path) -> None:
    salt = os.urandom(SALT_LEN)
    aes = AESGCM(_derive_key(salt))
    header = MAGIC + salt
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        fout.write(header)
        index = 0
        block = fin.read(CHUNK)
        while True:
            nxt = fin.read(CHUNK)
            last = not nxt
            ct = aes.encrypt(_nonce(index), block, header + (b"L" if last else b"M"))
            fout.write(struct.pack(">I", len(ct)) + ct)
            if last:
                break
            block, index = nxt, index + 1


def decrypt_file(src: Path, dst: Path) -> None:
    """رمزگشایی؛ هر دست‌کاری، قطع‌شدن یا کلید نادرست با OffsiteError گزارش می‌شود."""
    from cryptography.exceptions import InvalidTag

    with open(src, "rb") as fin, open(dst, "wb") as fout:
        header = fin.read(len(MAGIC) + SALT_LEN)
        if len(header) != len(MAGIC) + SALT_LEN or not header.startswith(MAGIC):
            raise OffsiteError("قالب فایل بکاپ رمزنگاری‌شده شناخته نشد.")
        aes = AESGCM(_derive_key(header[len(MAGIC):]))
        index = 0
        raw_len = fin.read(4)
        while raw_len:
            if len(raw_len) != 4:
                raise OffsiteError("فایل بکاپ ناقص است.")
            (n,) = struct.unpack(">I", raw_len)
            ct = fin.read(n)
            nxt = fin.read(4)
            last = not nxt
            try:
                fout.write(aes.decrypt(_nonce(index), ct, header + (b"L" if last else b"M")))
            except InvalidTag as exc:
                raise OffsiteError("رمزگشایی بکاپ ممکن نیست؛ کلید رمزنگاری تغییر کرده یا فایل دست‌کاری/ناقص شده است.") from exc
            raw_len, index = nxt, index + 1
        if index == 0:
            raise OffsiteError("فایل بکاپ خالی است.")


# ---------------------------------------------------------------------- اتصال S3
def _client(conf: SiteSettings):
    import boto3
    from botocore.config import Config

    access, secret = conf.get_offsite_keys()
    if not (access and secret):
        raise OffsiteError("کلیدهای فضای ابری وارد نشده یا قابل خواندن نیست.")
    if not conf.offsite_endpoint.startswith("https://"):
        raise OffsiteError("نشانی سرویس فضای ابری باید با https:// شروع شود.")
    cfg = Config(signature_version="s3v4", s3={"addressing_style": "path"}, retries={"max_attempts": 4, "mode": "standard"},
                 connect_timeout=15, read_timeout=120, request_checksum_calculation="when_required",
                 response_checksum_validation="when_required")
    return boto3.client("s3", endpoint_url=conf.offsite_endpoint, aws_access_key_id=access, aws_secret_access_key=secret,
                        region_name=conf.offsite_region or "us-east-1", config=cfg)


def _object_key(conf: SiteSettings, job) -> str:
    prefix = (conf.offsite_prefix or "").strip("/ ")
    name = Path(job.file).name + (".enc" if conf.offsite_encrypt else "")
    return "/".join(p for p in (prefix, str(job.database_id), name) if p)


def _clean(exc: Exception) -> str:
    return (str(exc) or exc.__class__.__name__).replace("\n", " ")[:280]


def test_connection(conf: SiteSettings | None = None) -> str:
    """یک فایل کوچک می‌نویسد، می‌خواند و پاک می‌کند؛ پیام موفقیت یا OffsiteError."""
    conf = conf or SiteSettings.get()
    if not (conf.offsite_endpoint and conf.offsite_bucket):
        raise OffsiteError("نشانی سرویس و نام باکت را وارد و ذخیره کنید.")
    key = "/".join(p for p in ((conf.offsite_prefix or "").strip("/ "), f"_connection_test_{os.urandom(4).hex()}") if p)
    payload = b"geopaygah-offsite-test"
    try:
        s3 = _client(conf)
        s3.put_object(Bucket=conf.offsite_bucket, Key=key, Body=payload)
        got = s3.get_object(Bucket=conf.offsite_bucket, Key=key)["Body"].read()
        s3.delete_object(Bucket=conf.offsite_bucket, Key=key)
    except OffsiteError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise OffsiteError(f"اتصال به فضای ابری برقرار نشد: {_clean(exc)}") from exc
    if got != payload:
        raise OffsiteError("فایل آزمایشی درست برگشت داده نشد.")
    return "نوشتن، خواندن و پاک‌کردن در باکت درست کار می‌کند."


# ---------------------------------------------------------------------- کار با بکاپ‌ها
def upload_job(job) -> bool:
    """بکاپ انجام‌شده را به فضای ابری می‌فرستد. خطا را روی job ثبت می‌کند و False برمی‌گرداند؛ استثنا نمی‌دهد."""
    conf = SiteSettings.get()
    if not conf.offsite_ready or not job.path or not job.path.exists():
        return False
    tmp_path: Path | None = None
    try:
        src = job.path
        if conf.offsite_encrypt:
            fd, name = tempfile.mkstemp(prefix="offsite-", suffix=".enc", dir=str(Path(settings.BACKUP_ROOT)))
            os.close(fd)
            tmp_path = Path(name)
            encrypt_file(src, tmp_path)
            src = tmp_path
        key = _object_key(conf, job)
        _client(conf).upload_file(str(src), conf.offsite_bucket, key)
    except Exception as exc:  # noqa: BLE001
        log.warning("offsite upload failed for job %s: %s", job.pk, exc)
        job.offsite_error = _clean(exc)
        return False
    finally:
        if tmp_path:
            tmp_path.unlink(missing_ok=True)
    job.offsite_key, job.offsite_encrypted = key, conf.offsite_encrypt
    job.offsite_at, job.offsite_error = timezone.now(), ""
    return True


def ensure_local(job) -> Path | None:
    """مسیر فایل بکاپ روی دیسک؛ اگر نبود ولی نسخه‌ی ابری هست، دانلود و رمزگشایی می‌شود. None = در دسترس نیست."""
    if job.path and job.path.exists():
        return job.path
    if not (job.file and job.offsite_key):
        return None
    conf = SiteSettings.get()
    dst = job.path
    tmp_dir = Path(settings.BACKUP_ROOT)
    fd, name = tempfile.mkstemp(prefix="offsite-dl-", dir=str(tmp_dir))
    os.close(fd)
    tmp = Path(name)
    part = dst.with_suffix(".part")
    try:
        _client(conf).download_file(conf.offsite_bucket, job.offsite_key, str(tmp))
        dst.parent.mkdir(parents=True, exist_ok=True)
        if job.offsite_encrypted:
            decrypt_file(tmp, part)
        else:
            tmp.replace(part)
        part.replace(dst)
    except Exception as exc:  # noqa: BLE001
        log.warning("offsite download failed for job %s: %s", job.pk, exc)
        return None
    finally:
        tmp.unlink(missing_ok=True)
        part.unlink(missing_ok=True)
    return dst


def delete_remote(job) -> bool:
    """نسخه‌ی ابری را پاک می‌کند (نبودنش هم موفقیت است). نتیجه روی job اعمال می‌شود؛ ذخیره با فراخواننده است."""
    if not job.offsite_key:
        return True
    conf = SiteSettings.get()
    if not (conf.offsite_endpoint and conf.has_offsite_keys):
        return False
    try:
        _client(conf).delete_object(Bucket=conf.offsite_bucket, Key=job.offsite_key)
    except Exception as exc:  # noqa: BLE001
        log.warning("offsite delete failed for job %s: %s", job.pk, exc)
        return False
    job.offsite_key = ""
    return True


def purge_expired(limit: int = 20) -> int:
    """نسخه‌ی ابری بکاپ‌های منقضی‌شده را پاک می‌کند (هم‌زمان با پاک شدن فایل محلی طبق مدت نگهداری پلن)."""
    from .models import Job

    n = 0
    for job in Job.objects.filter(status=Job.Status.EXPIRED).exclude(offsite_key="")[:limit]:
        if delete_remote(job):
            job.save(update_fields=["offsite_key"])
            n += 1
    return n


def retry_pending(limit: int = MAX_RETRY_PER_TICK) -> int:
    """بکاپ‌های سالم سه روز اخیر که نسخه‌ی ابری ندارند (قطعی موقت یا فعال‌شدن بعدی) دوباره ارسال می‌شوند."""
    from datetime import timedelta

    from .models import Job

    conf = SiteSettings.get()
    if not conf.offsite_ready:
        return 0
    since = timezone.now() - timedelta(days=3)
    n = 0
    for job in Job.objects.filter(kind=Job.Kind.BACKUP, status=Job.Status.DONE, offsite_key="", created_at__gte=since,
                                  database__isnull=False).exclude(file="").order_by("-created_at")[:limit]:
        if upload_job(job):
            n += 1
        job.save(update_fields=["offsite_key", "offsite_encrypted", "offsite_at", "offsite_error"])
    return n
