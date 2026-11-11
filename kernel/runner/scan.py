"""بررسی ایستای کد سطح ۲ (AST): واردات فقط از فهرست سفید، بدون نام/ویژگی خطرناک.

این لایه‌ی **اول** است و جلوی خطای ساده و کد مشکوک را می‌گیرد؛ مرز امنیتی واقعی کانتینر بدون شبکه و بدون راز است
(docs/adr/0002، docs/plugins/tier2.md). ماژول بدون وابستگی به جنگو است تا داخل runner هم کار کند.
"""
from __future__ import annotations

import ast

ALLOWED_IMPORTS = frozenset({
    "math", "json", "statistics", "datetime", "itertools", "functools", "collections", "re", "decimal", "fractions",
    "typing", "dataclasses", "string", "textwrap", "heapq", "bisect", "random", "operator", "enum", "copy", "hashlib",
    "base64", "unicodedata", "zlib", "array", "numbers", "time", "calendar", "uuid"})
BANNED_NAMES = frozenset({"eval", "exec", "compile", "open", "input", "breakpoint", "__import__", "globals", "locals",
                          "vars", "getattr", "setattr", "delattr", "memoryview", "help", "exit", "quit"})
MAX_SOURCE = 100_000
MAX_NODES = 20_000


def scan(source: str, filename: str = "code") -> list[str]:
    """فهرست مشکل‌ها (فارسی، با شماره‌ی خط)؛ خالی = پاک."""
    if len(source) > MAX_SOURCE:
        return [f"{filename}: حجم کد بیش از حد مجاز است."]
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return [f"{filename}:{exc.lineno}: خطای نحوی: {exc.msg}"]
    except (ValueError, RecursionError):
        return [f"{filename}: کد قابل تجزیه نیست."]
    problems: list[str] = []
    count = 0
    for node in ast.walk(tree):
        count += 1
        if count > MAX_NODES:
            return problems + [f"{filename}: کد بیش از حد بزرگ است."]
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in ALLOWED_IMPORTS or "." in a.name:
                    problems.append(f"{filename}:{line}: واردکردن «{a.name}» مجاز نیست.")
        elif isinstance(node, ast.ImportFrom):
            if node.level or (node.module or "").split(".")[0] not in ALLOWED_IMPORTS or "." in (node.module or ""):
                problems.append(f"{filename}:{line}: واردکردن از «{'.' * node.level}{node.module or ''}» مجاز نیست.")
        elif isinstance(node, ast.Name) and (node.id in BANNED_NAMES or (node.id.startswith("__") and node.id.endswith("__"))):
            problems.append(f"{filename}:{line}: استفاده از «{node.id}» مجاز نیست.")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            problems.append(f"{filename}:{line}: دسترسی به ویژگی «{node.attr}» مجاز نیست.")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            problems.append(f"{filename}:{line}: global/nonlocal مجاز نیست.")
        elif isinstance(node, (ast.AsyncFunctionDef, ast.Await, ast.AsyncFor, ast.AsyncWith)):
            problems.append(f"{filename}:{line}: کد ناهم‌گام پشتیبانی نمی‌شود.")
    return problems
