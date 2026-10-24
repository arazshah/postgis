"""
رله NTRIP: مرورگر نمی‌تواند مستقیم به کستر وصل شود (TCP خام)، پس سرور بایت‌های RTCM را پخش می‌کند.

امنیت (SSRF): میزبان پیش از اتصال resolve می‌شود، فقط نشانی‌های عمومی پذیرفته می‌شوند و اتصال به همان IP
بررسی‌شده انجام می‌شود (نه دوباره به نام)، تا DNS-rebinding اثر نکند. ورودی‌های خط درخواست اعتبارسنجی می‌شوند.
منابع: سقف هم‌زمانی هر پردازش، یک نشست فعال برای هر کاربر، سقف زمان و حجم، و پایان خودکار بدون ضربان کلاینت.
"""
from __future__ import annotations

import base64
import ipaddress
import re
import socket
import ssl
import threading
import time

from django.conf import settings
from django.utils import timezone

HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
MOUNT_RE = re.compile(r"^[A-Za-z0-9_.\-]{0,40}$")
CRED_RE = re.compile(r"^[^\x00-\x1f\x7f:]{0,80}$")
HEADER_CAP = 8192
TABLE_CAP = 512 * 1024
GGA_RE = re.compile(r"^\$G[NPLAB]GGA,[\x20-\x7e]{10,100}\*[0-9A-Fa-f]{2}$")
_slots = threading.BoundedSemaphore(getattr(settings, "NTRIP_MAX_STREAMS_PER_PROCESS", 3))


class NtripError(Exception):
    """پیام فارسیِ قابل‌نمایش به کاربر."""


def validate_profile(host: str, port: int, mountpoint: str, username: str, password: str) -> None:
    if not HOST_RE.match(host or ""):
        raise NtripError("نشانی کستر معتبر نیست.")
    if not 1 <= int(port) <= 65535:
        raise NtripError("درگاه باید بین ۱ تا ۶۵۵۳۵ باشد.")
    if not MOUNT_RE.match(mountpoint or ""):
        raise NtripError("نام Mountpoint فقط حرف انگلیسی، رقم و . _ - می‌تواند باشد.")
    if not CRED_RE.match(username or "") or not CRED_RE.match(password or ""):
        raise NtripError("نام کاربری و گذرواژه نباید دو‌نقطه یا نویسه کنترلی داشته باشند.")


def resolve_public(host: str, port: int) -> tuple[int, str]:
    """اولین نشانی عمومی میزبان؛ اگر هر نشانی غیرعمومی باشد رد می‌شود."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise NtripError("نشانی کستر پیدا نشد.") from exc
    if not infos:
        raise NtripError("نشانی کستر پیدا نشد.")
    allow = getattr(settings, "NTRIP_ALLOW_PRIVATE", False)
    for _f, _t, _p, _c, sa in infos:
        ip = ipaddress.ip_address(sa[0].split("%")[0])
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not allow and not ip.is_global:
            raise NtripError("اتصال به نشانی‌های داخلی مجاز نیست.")
    fam, _t, _p, _c, sa = infos[0]
    return fam, sa[0]


def _request(host, port, mountpoint, username, password, gga=None) -> bytes:
    lines = [f"GET /{mountpoint} HTTP/1.1", f"Host: {host}:{port}", "Ntrip-Version: Ntrip/2.0",
             "User-Agent: NTRIP postgis.ir/1.0", "Connection: close"]
    if username or password:
        lines.append("Authorization: Basic " + base64.b64encode(f"{username}:{password}".encode()).decode())
    data = ("\r\n".join(lines) + "\r\n\r\n").encode()
    return data + (gga.encode() + b"\r\n" if gga else b"")


def _connect(host, port, tls, timeout):
    fam, ip = resolve_public(host, port)
    sock = socket.socket(fam, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((ip, port))
        if tls:
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
    except (OSError, ssl.SSLError) as exc:
        sock.close()
        raise NtripError("اتصال به کستر برقرار نشد.") from exc
    return sock


def _read_head(sock) -> tuple[str, bytes]:
    buf = b""
    while b"\r\n\r\n" not in buf and b"\n\n" not in buf:
        if len(buf) > HEADER_CAP:
            raise NtripError("پاسخ کستر نامعتبر است.")
        try:
            chunk = sock.recv(2048)
        except OSError as exc:
            raise NtripError("کستر پاسخ نداد.") from exc
        if not chunk:
            break
        buf += chunk
    sep = b"\r\n\r\n" if b"\r\n\r\n" in buf else b"\n\n"
    head, _, rest = buf.partition(sep)
    return head.decode("latin-1"), rest


def _check_status(head: str) -> str:
    first = head.split("\n", 1)[0].strip()
    if first.startswith("401") or " 401" in first:
        raise NtripError("نام کاربری یا گذرواژه کستر درست نیست.")
    if " 403" in first:
        raise NtripError("دسترسی به این Mountpoint مجاز نیست.")
    return first


def fetch_sourcetable(host, port, tls, username="", password="") -> list[dict]:
    validate_profile(host, port, "", username, password)
    sock = _connect(host, port, tls, timeout=8)
    try:
        sock.sendall(_request(host, port, "", username, password))
        head, rest = _read_head(sock)
        first = _check_status(head)
        if "200" not in first:
            raise NtripError("کستر فهرست Mountpoint را نداد.")
        body, deadline = rest, time.monotonic() + 10
        while b"ENDSOURCETABLE" not in body and len(body) < TABLE_CAP and time.monotonic() < deadline:
            try:
                chunk = sock.recv(8192)
            except OSError:
                break
            if not chunk:
                break
            body += chunk
    finally:
        sock.close()
    return parse_sourcetable(body.decode("latin-1"))


def _num(v):
    try:
        return float(v)
    except ValueError:
        return None


def parse_sourcetable(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        f = line.strip().split(";")
        if f[0] != "STR" or len(f) < 12:
            continue

        out.append({"mountpoint": f[1], "identifier": f[2], "format": f[3], "country": f[8],
                    "lat": _num(f[9]), "lon": _num(f[10]), "needs_gga": f[11] == "1"})
    return out[:500]


class Relay:
    """تکرارگر پاسخ جریانی؛ close() در هر حال سوکت و جایگاه هم‌زمانی را آزاد می‌کند."""

    def __init__(self, session, profile, password, sock, leftover, chunked):
        from .models import NtripSession
        self.M, self.s, self.profile, self.sock = NtripSession, session, profile, sock
        self.pending, self.chunked, self.buf = leftover, chunked, b""
        self.start = time.monotonic()
        self.last_poll = self.start
        self.seq = 0
        self.sent = 0
        self.done = False
        self.max_seconds = getattr(settings, "NTRIP_MAX_SECONDS", 4 * 3600)
        self.max_bytes = getattr(settings, "NTRIP_MAX_BYTES", 100 * 1024 * 1024)
        self.idle = getattr(settings, "NTRIP_IDLE_SECONDS", 45)
        sock.settimeout(1.0)

    def __iter__(self):
        return self

    def _decode(self, data: bytes) -> bytes:
        if not self.chunked:
            return data
        self.buf += data
        out = b""
        while True:
            nl = self.buf.find(b"\r\n")
            if nl < 0:
                break
            try:
                size = int(self.buf[:nl].split(b";")[0] or b"0", 16)
            except ValueError:
                self.done = True
                break
            if size == 0:
                self.done = True
                break
            if len(self.buf) < nl + 2 + size + 2:
                break
            out += self.buf[nl + 2:nl + 2 + size]
            self.buf = self.buf[nl + 2 + size + 2:]
        return out

    def _poll(self):
        row = self.M.objects.filter(pk=self.s).values("closed", "gga", "gga_seq", "last_seen").first()
        if not row or row["closed"] or (timezone.now() - row["last_seen"]).total_seconds() > self.idle:
            self.done = True
            return
        if row["gga_seq"] != self.seq and row["gga"]:
            self.seq = row["gga_seq"]
            try:
                self.sock.sendall(row["gga"].encode() + b"\r\n")
            except OSError:
                self.done = True

    def __next__(self):
        while not self.done:
            if self.pending:
                data, self.pending = self.pending, b""
            else:
                if time.monotonic() - self.start > self.max_seconds or self.sent > self.max_bytes:
                    break
                if time.monotonic() - self.last_poll >= 3:
                    self.last_poll = time.monotonic()
                    self._poll()
                    if self.done:
                        break
                try:
                    data = self.sock.recv(4096)
                except TimeoutError:
                    continue  # بایت خالی نمی‌فرستیم (در chunked پایان جریان می‌شود)؛ قطع کلاینت را ضربان تشخیص می‌دهد
                except OSError:
                    break
                if not data:
                    break
            out = self._decode(data)
            self.sent += len(out)
            if out:
                return out
        self.close()
        raise StopIteration

    def close(self):
        if getattr(self, "_closed", False):
            return
        self._closed = True
        self.done = True
        try:
            self.sock.close()
        except OSError:
            pass
        self.M.objects.filter(pk=self.s).update(closed=True, bytes_out=self.sent)
        _slots.release()


def open_relay(session, profile, password) -> Relay:
    """اتصال به کستر (خطاها همین‌جا و پیش از شروع پاسخ جریانی گزارش می‌شوند)."""
    if not _slots.acquire(blocking=False):
        raise NtripError("ظرفیت اتصال‌های هم‌زمان پر است؛ چند لحظه بعد دوباره تلاش کنید.")
    try:
        validate_profile(profile.host, profile.port, profile.mountpoint, profile.username, password)
        if not profile.mountpoint:
            raise NtripError("برای دریافت تصحیح، Mountpoint را انتخاب کنید.")
        sock = _connect(profile.host, profile.port, profile.tls, timeout=8)
        try:
            gga = session.gga if profile.send_gga and GGA_RE.match(session.gga or "") else None
            sock.sendall(_request(profile.host, profile.port, profile.mountpoint, profile.username, password, gga))
            head, rest = _read_head(sock)
            first = _check_status(head)
            if not (first.startswith("ICY 200") or " 200" in first) or "SOURCETABLE" in first.upper():
                raise NtripError("Mountpoint پیدا نشد یا کستر اتصال را نپذیرفت.")
            chunked = "transfer-encoding: chunked" in head.lower()
        except Exception:
            sock.close()
            raise
    except Exception:
        _slots.release()
        raise
    return Relay(session.pk, profile, password, sock, rest, chunked)
