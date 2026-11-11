"""قرارداد ورود/خروج داده‌ی مکانی به فضای کار (GDAL): ورود یک لایه، اجرای ابزار GDAL و مقصد اتصال PostgreSQL.

بخش‌های دیگر (پرسش فارسی، کلاس درس، داده آماده) فقط از اینجا می‌خواهند؛ پیاده‌سازی را پلاگین پایگاه داده
با `set_provider` ثبت می‌کند. خطا = DataIOError با پیام فارسی.
"""
from __future__ import annotations

from pathlib import Path


class DataIOError(Exception):
    pass


class Provider:
    def import_layer(self, ws, path: Path, layer: dict, encoding: str | None) -> None:
        """layer: {name, table, srid, assign_srid, to4326, mode(create|overwrite|append), geom_type}"""
        raise NotImplementedError

    def run_gdal(self, tool: str, args: list[str], *, env: dict | None = None, timeout: int | None = None) -> str:
        """یکی از ابزارهای GDAL (مثلاً ogr2ogr) را اجرا می‌کند و خروجی متنی را برمی‌گرداند."""
        raise NotImplementedError

    def pg_target(self, ws):
        """مقصد ogr2ogr برای پایگاه فضای کار: شیء با `.conn` (رشته‌ی اتصال) و `.env` (محیط اجرا، شامل رمز)."""
        raise NotImplementedError


_provider: Provider | None = None


def set_provider(provider: Provider) -> None:
    global _provider
    _provider = provider


def provider() -> Provider:
    if _provider is None:
        raise DataIOError("ارائه‌دهنده‌ی ورود و خروج داده ثبت نشده است.")
    return _provider


def import_layer(ws, path: Path, layer: dict, encoding: str | None = None) -> None:
    provider().import_layer(ws, path, layer, encoding)


def run_gdal(tool: str, args: list[str], *, env: dict | None = None, timeout: int | None = None) -> str:
    return provider().run_gdal(tool, args, env=env, timeout=timeout)


def pg_target(ws):
    return provider().pg_target(ws)
