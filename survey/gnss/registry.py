"""همگام‌سازی درایورهای داخلی (پوشه drivers/) با جدول GnssDriver."""
import hashlib
import json
from pathlib import Path

from . import contract

DRIVERS_DIR = Path(__file__).resolve().parent / "drivers"


def builtin_manifests() -> list[tuple[dict, str]]:
    out = []
    for path in sorted(DRIVERS_DIR.glob("*/manifest.json")):
        raw = path.read_bytes()
        manifest = contract.validate_manifest(json.loads(raw))
        if manifest["id"] != path.parent.name:
            raise contract.ContractError("id", "id", f"نام پوشه ({path.parent.name}) با شناسه یکی نیست")
        out.append((manifest, hashlib.sha256(raw).hexdigest()))
    return out


def sync() -> dict:
    from survey.models import GnssDriver

    created = updated = 0
    for manifest, digest in builtin_manifests():
        obj, was_created = GnssDriver.objects.get_or_create(
            driver_id=manifest["id"], version=manifest["version"],
            defaults={"api_version": manifest["apiVersion"], "manifest": manifest, "level": manifest["level"],
                      "bundle_hash": digest})
        if was_created:
            created += 1
        elif obj.bundle_hash != digest:
            obj.manifest, obj.api_version, obj.level, obj.bundle_hash = (
                manifest, manifest["apiVersion"], manifest["level"], digest)
            obj.save()
            updated += 1
    return {"created": created, "updated": updated}
