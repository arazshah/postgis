"""ثبت کد handler سطح ۲ هر پلاگین (منبع پایتون به‌صورت متن)؛ فقط داده است و اجرا در kernel.runner انجام می‌شود."""
from __future__ import annotations

from .plugins import registry

POINT = "runner.handler"


def register(plugin: str, name: str, source: str) -> None:
    registry.add(POINT, f"{plugin}:{name}", source, plugin=plugin, replace=True)


def get(plugin: str, name: str) -> str | None:
    return registry.get(POINT, f"{plugin}:{name}")


def files_for(plugin: str, name: str) -> dict[str, str]:
    src = get(plugin, name)
    return {f"code/{name}.py": src} if src is not None else {}
