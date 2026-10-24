"""
قرارداد رویدادها و مشخصات درایور گیرنده GNSS (نسخه ۱).

- هر رویداد: {"v": 1, "kind": ..., "data": {...}}؛ فیلد نامعلوم فرستاده نمی‌شود (هرگز صفر جعلی نه).
- هر درایور یک manifest دارد؛ هسته نسخه فعلی و یک نسخه قبل را می‌پذیرد.
"""
import math
import re

API_VERSION = 1
SUPPORTED_API = (API_VERSION, API_VERSION - 1)
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
TRANSPORTS = {"geolocation", "web-serial", "web-bluetooth", "web-usb", "bridge", "replay"}
CAPABILITIES = {"position", "accuracy", "satellites", "corrections_in", "battery", "tilt", "raw_log", "base_mode"}
LEVELS = {"builtin", "tested", "compatible", "experimental", "private"}
KINDS = {"position", "accuracy", "satellites", "status", "raw", "error"}


class ContractError(ValueError):
    def __init__(self, code: str, path: str, message: str = ""):
        super().__init__(f"{code} @ {path}: {message}" if message else f"{code} @ {path}")
        self.code, self.path = code, path


def _num(data, key, lo=None, hi=None, required=False, integer=False):
    if key not in data:
        if required:
            raise ContractError("required", key)
        return
    v = data[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)) or (isinstance(v, float) and not math.isfinite(v)):
        raise ContractError("type", key, "عدد لازم است")
    if integer and int(v) != v:
        raise ContractError("type", key, "عدد صحیح لازم است")
    if lo is not None and v < lo:
        raise ContractError("range", key, f"کمتر از {lo}")
    if hi is not None and v > hi:
        raise ContractError("range", key, f"بیشتر از {hi}")


def validate_event(ev: dict) -> dict:
    if not isinstance(ev, dict):
        raise ContractError("type", "$", "رویداد باید شیء باشد")
    if ev.get("v") not in SUPPORTED_API:
        raise ContractError("version", "v")
    kind, data = ev.get("kind"), ev.get("data")
    if kind not in KINDS:
        raise ContractError("kind", "kind")
    if not isinstance(data, dict):
        raise ContractError("type", "data")
    if kind == "position":
        _num(data, "lat", -90, 90, required=True)
        _num(data, "lon", -180, 180, required=True)
        _num(data, "h_ellip", -1000, 100000)
    elif kind == "accuracy":
        _num(data, "fix_quality", 0, 9, integer=True)
        _num(data, "sats_used", 0, integer=True)
        for k in ("hdop", "pdop", "vdop", "acc_h", "std_e", "std_n", "std_h", "corr_age_s"):
            _num(data, k, 0)
    elif kind == "satellites":
        sats = data.get("list")
        if not isinstance(sats, list):
            raise ContractError("type", "list")
        for i, s in enumerate(sats):
            if not isinstance(s, dict) or "prn" not in s:
                raise ContractError("shape", f"list[{i}]")
    elif kind == "status":
        _num(data, "battery_pct", 0, 100)
    elif kind == "error":
        if not isinstance(data.get("code"), str):
            raise ContractError("required", "code")
    return ev


def validate_manifest(m: dict) -> dict:
    if not isinstance(m, dict):
        raise ContractError("type", "$")
    if not isinstance(m.get("id"), str) or not ID_RE.match(m["id"]):
        raise ContractError("id", "id", "شناسه نامعتبر")
    if not isinstance(m.get("name"), str) or not m["name"].strip():
        raise ContractError("required", "name")
    if not isinstance(m.get("version"), str) or not SEMVER_RE.match(m["version"]):
        raise ContractError("version", "version", "semver لازم است")
    api = m.get("apiVersion")
    if isinstance(api, bool) or not isinstance(api, int):
        raise ContractError("type", "apiVersion")
    if api not in SUPPORTED_API:
        raise ContractError("unsupported", "apiVersion")
    tr = m.get("transport")
    if not isinstance(tr, list) or not tr or not set(tr) <= TRANSPORTS:
        raise ContractError("transport", "transport")
    caps = m.get("capabilities", [])
    if not isinstance(caps, list) or not set(caps) <= CAPABILITIES:
        raise ContractError("capabilities", "capabilities")
    if m.get("level", "private") not in LEVELS:
        raise ContractError("level", "level")
    serial = m.get("serial")
    if serial is not None:
        bauds = serial.get("baud") if isinstance(serial, dict) else None
        if not isinstance(bauds, list) or not all(isinstance(b, int) and b > 0 for b in bauds):
            raise ContractError("serial", "serial.baud")
    return m


# نگاشت رویداد به ستون‌های جدول points
def event_columns(position: dict, accuracy: dict | None = None) -> dict:
    """موقعیت و دقت لحظه‌ای را به ستون‌های استاندارد جدول نقاط تبدیل می‌کند؛ فیلد نامعلوم نمی‌آید."""
    acc = accuracy or {}
    out = {}
    mapping = {"fix_quality": "fix_quality", "sats_used": "sats", "hdop": "hdop", "pdop": "pdop", "acc_h": "acc_h",
               "std_e": "std_e", "std_n": "std_n", "std_h": "std_h", "corr_age_s": "corr_age"}
    for src, dst in mapping.items():
        if src in acc:
            out[dst] = acc[src]
    if "h_ellip" in position:
        out["h_ellip"] = position["h_ellip"]
    return out
