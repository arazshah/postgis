from django.test import SimpleTestCase

from kernel.runner import sandbox, scan


def run(src, params=None, **kw):
    return sandbox.run({"code/h.py": src}, "h", params or {}, **kw)


class ScanTests(SimpleTestCase):
    def test_clean_code_passes(self):
        self.assertEqual(scan.scan("import math\nfrom collections import Counter\ndef handle(ctx, p):\n    return math.sqrt(4)\n"), [])

    def test_dangerous_constructs_are_flagged(self):
        bad = ["import os", "import subprocess", "from os import path", "import socket", "from . import x", "import math.foo",
               "eval('1')", "exec('1')", "open('/etc/passwd')", "x = ().__class__", "__import__('os')", "getattr(1, 'a')",
               "global q", "x = [].__class__.__bases__", "async def f(): pass", "def f(:"]
        for src in bad:
            with self.subTest(src=src):
                self.assertTrue(scan.scan(src), src)

    def test_size_limit(self):
        self.assertTrue(scan.scan("x=1\n" * 50_000))


class SandboxTests(SimpleTestCase):
    def test_returns_value_and_uses_params(self):
        self.assertEqual(run("def handle(ctx, p):\n    return {'n': p['a'] * 2}", {"a": 21}), {"n": 42})

    def test_sql_bridge_and_log(self):
        calls, logs = [], []

        def sql(q, params):
            calls.append((q, params))
            return {"columns": ["n"], "rows": [[7]]}

        out = run("def handle(ctx, p):\n    r = ctx.sql('select 1', [1])\n    ctx.log('hi', r['rows'][0][0])\n    return r['rows']",
                  sql=sql, on_log=logs.append)
        self.assertEqual((out, calls, logs), ([[7]], [("select 1", [1])], ["hi 7"]))

    def test_sql_not_available_without_bridge(self):
        with self.assertRaisesRegex(sandbox.SandboxError, "دسترسی ندارد"):
            run("def handle(ctx, p):\n    return ctx.sql('select 1')")

    def test_forbidden_import_and_builtins_at_runtime(self):
        for src, msg in [("import os\ndef handle(c,p): return 1", "مجاز نیست"),
                         ("def handle(c,p):\n    return open('/etc/passwd').read()", "NameError"),
                         ("def handle(c,p):\n    return eval('1+1')", "NameError"),
                         ("def handle(c,p):\n    __import__('os')", "مجاز نیست")]:
            with self.subTest(src=src), self.assertRaisesRegex(sandbox.SandboxError, msg):
                run(src)

    def test_timeout_kills_infinite_loop(self):
        with self.assertRaisesRegex(sandbox.SandboxError, "زمان"):
            run("def handle(c,p):\n    while True:\n        pass", timeout=1.0, cpu_s=30)

    def test_cpu_limit(self):
        with self.assertRaises(sandbox.SandboxError):
            run("def handle(c,p):\n    while True:\n        pass", timeout=20.0, cpu_s=1)

    def test_memory_limit(self):
        with self.assertRaises(sandbox.SandboxError):
            run("def handle(c,p):\n    x = bytearray(900 * 1024 * 1024)\n    return len(x)", memory_mb=128)

    def test_missing_handle_and_exceptions_are_short(self):
        with self.assertRaisesRegex(sandbox.SandboxError, "handle"):
            run("x = 1")
        with self.assertRaisesRegex(sandbox.SandboxError, "ZeroDivisionError"):
            run("def handle(c,p):\n    return 1/0")
        with self.assertRaisesRegex(sandbox.SandboxError, "در بسته نیست"):
            sandbox.run({}, "nope", {})

    def test_result_size_cap_and_sql_call_cap(self):
        with self.assertRaisesRegex(sandbox.SandboxError, "بزرگ"):
            run("def handle(c,p):\n    return 'x' * (2 * 1024 * 1024)")
        with self.assertRaisesRegex(sandbox.SandboxError, "حداکثر"):
            run("def handle(c,p):\n    for i in range(30):\n        c.sql('select 1')\n    return 1",
                sql=lambda q, p: {"columns": [], "rows": []})
