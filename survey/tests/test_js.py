"""آزمون‌های جاوااسکریپت سمت مرورگر که بدون DOM اجرا می‌شوند (نیازمند node)."""
import shutil
import subprocess
import unittest
from pathlib import Path

from django.test import SimpleTestCase

JS = Path(__file__).resolve().parent / "js"


@unittest.skipUnless(shutil.which("node"), "node not installed")
class NodeTests(SimpleTestCase):
    def test_js_suites(self):
        for f in sorted(JS.glob("*.test.js")):
            r = subprocess.run(["node", str(f)], capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, f"{f.name}\n{r.stdout}\n{r.stderr}")

    def test_every_browser_script_parses(self):
        """خطای نحوی در Service Worker یا اسکریپت استودیو بی‌صدا کل کار آفلاین را می‌شکند."""
        for f in sorted((JS.parents[2] / "static" / "js" / "survey").glob("*.js")):
            r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, f"{f.name}\n{r.stderr}")
