import copy
import io

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from survey.gnss import contract, registry
from survey.models import GnssDriver

GOOD = {"id": "nmea-generic", "name": "x", "version": "1.0.0", "apiVersion": 1, "transport": ["web-serial"],
        "capabilities": ["position"], "level": "builtin"}


class ManifestTests(SimpleTestCase):
    def test_builtins_are_valid(self):
        ids = {m["id"] for m, _ in registry.builtin_manifests()}
        self.assertEqual(ids, {"nmea-generic", "phone-geolocation"})

    def test_bad_manifests_have_distinct_codes(self):
        cases = {
            "id": {"id": "Bad Id"},
            "required": {"name": ""},
            "version": {"version": "1.0"},
            "type": {"apiVersion": "1"},
            "unsupported": {"apiVersion": 7},
            "transport": {"transport": ["carrier-pigeon"]},
            "capabilities": {"capabilities": ["teleport"]},
            "level": {"level": "god"},
            "serial": {"serial": {"baud": ["fast"]}},
        }
        for code, patch in cases.items():
            m = copy.deepcopy(GOOD)
            m.update(patch)
            with self.assertRaises(contract.ContractError) as cm:
                contract.validate_manifest(m)
            self.assertEqual(cm.exception.code, code, patch)

    def test_previous_api_version_is_accepted(self):
        m = dict(GOOD, apiVersion=0)
        self.assertEqual(contract.validate_manifest(m)["apiVersion"], 0)


class EventTests(SimpleTestCase):
    def ev(self, kind, **data):
        return {"v": 1, "kind": kind, "data": data}

    def test_valid_events(self):
        contract.validate_event(self.ev("position", lat=35.7, lon=51.4, h_ellip=1190.2))
        contract.validate_event(self.ev("accuracy", fix_quality=4, sats_used=18, hdop=0.7, acc_h=0.02))
        contract.validate_event(self.ev("accuracy"))  # فیلد نامعلوم = غایب
        contract.validate_event(self.ev("satellites", list=[{"prn": 5, "snr": 40}]))
        contract.validate_event(self.ev("status", battery_pct=80))
        contract.validate_event(self.ev("error", code="lost", message="قطع شد"))

    def test_invalid_events(self):
        bad = [
            {"v": 2, "kind": "position", "data": {}},
            self.ev("nope"),
            self.ev("position", lat=91, lon=0),
            self.ev("position", lon=0),
            self.ev("accuracy", fix_quality=10),
            self.ev("accuracy", hdop=-1),
            self.ev("accuracy", sats_used=1.5),
            self.ev("accuracy", hdop=float("nan")),
            self.ev("accuracy", hdop=True),
            self.ev("satellites", list="x"),
            self.ev("status", battery_pct=101),
            self.ev("error"),
            "string",
        ]
        for ev in bad:
            with self.assertRaises(contract.ContractError, msg=ev):
                contract.validate_event(ev)

    def test_event_columns_never_invent_zero(self):
        cols = contract.event_columns({"lat": 1, "lon": 2}, {"fix_quality": 4, "sats_used": 12})
        self.assertEqual(cols, {"fix_quality": 4, "sats": 12})
        cols = contract.event_columns({"lat": 1, "lon": 2, "h_ellip": 10.5}, {"hdop": 0.9, "acc_h": 0.02})
        self.assertEqual(cols, {"h_ellip": 10.5, "hdop": 0.9, "acc_h": 0.02})


class RegistryTests(TestCase):
    def test_sync_is_idempotent(self):
        call_command("gnss_sync", stdout=io.StringIO())
        n = GnssDriver.objects.count()
        self.assertEqual(n, 2)
        call_command("gnss_sync", stdout=io.StringIO())
        self.assertEqual(GnssDriver.objects.count(), n)
