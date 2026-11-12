"""بررسی ایستای پلاگین سطح ۳ (`ext/<id>/`)، مرحله‌ی ۲ از docs/adr/0007. کدی را اجرا یا import نمی‌کند؛ فقط AST می‌خواند.

سه بخش: قرارداد ساختار (۱)، پویش کد (۴.۴) و مهاجرت افزایشی (۴.۵). هر یافته `Finding` با سطح است:
- `error`: ممنوع؛ `ext_check` شکست می‌خورد.
- `warn`: مورد «هشدار» که با `# ext: allow(<دلیل>)` روی همان خط (یا `# ext: privileged-migration` در فایل مهاجرت)
  پذیرفته شده است؛ فقط گزارش می‌شود تا بازبین ببیند. بدون علامت همان مورد `error` است.
ماژول بدون وابستگی به جنگو و هیچ اپی است.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
EXT_GROUPS = ("ext", "ws_ext")
ALLOW_RE = re.compile(r"#\s*ext:\s*allow\(\s*([^)\s][^)]*)\)")
PRIV_RE = re.compile(r"#\s*ext:\s*privileged-migration\b")

# ماژول/نام‌هایی که فقط با علامت و دلیل پذیرفته می‌شوند
WARN_MODULES = frozenset({"subprocess", "pickle", "ctypes", "socket", "marshal", "shelve"})
WARN_CALLS = frozenset({"eval", "exec", "system", "popen", "__import__"})
SIGNALS = frozenset({"pre_save", "post_save", "pre_delete", "post_delete", "m2m_changed", "pre_init", "post_init",
                     "class_prepared", "request_started", "request_finished", "got_request_exception"})
GLOBAL_SETTINGS = frozenset({"MIDDLEWARE", "AUTHENTICATION_BACKENDS", "TEMPLATES", "INSTALLED_APPS", "ROOT_URLCONF",
                             "AUTH_USER_MODEL", "DATABASES", "DATABASE_ROUTERS"})
SECRET_SETTINGS = frozenset({"SECRET_KEY", "CREDENTIALS_ENCRYPTION_KEY", "SECRET_KEY_FALLBACKS"})
SAFE_MIGRATION_OPS = frozenset({"CreateModel", "AddIndex", "AddConstraint", "AddField"})
FK_TARGETS_OK = frozenset({"databases.userdatabase", "accounts.user", "kernel.organization"})
FK_KINDS = frozenset({"ForeignKey", "OneToOneField"})
ON_DELETE_OK = frozenset({"CASCADE", "SET_NULL"})


@dataclass(frozen=True)
class Finding:
    level: str  # error | warn
    path: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"[{'خطا' if self.level == 'error' else 'هشدار'}] {self.path}:{self.line}: {self.message}"


def _last(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _const(node: ast.AST | None):
    return node.value if isinstance(node, ast.Constant) else None


def _kw(call: ast.Call, name: str) -> ast.AST | None:
    return next((k.value for k in call.keywords if k.arg == name), None)


class _Ctx:
    def __init__(self, plugin: str, rel: str, source: str):
        self.plugin, self.rel, self.lines = plugin, rel, source.splitlines()
        self.out: list[Finding] = []

    def line_text(self, n: int) -> str:
        return self.lines[n - 1] if 0 < n <= len(self.lines) else ""

    def error(self, line: int, msg: str) -> None:
        self.out.append(Finding("error", self.rel, line, msg))

    def warnable(self, line: int, msg: str) -> None:
        """مورد هشدار: با `# ext: allow(دلیل)` روی همان خط = هشدار، وگرنه خطا."""
        m = ALLOW_RE.search(self.line_text(line))
        if m:
            self.out.append(Finding("warn", self.rel, line, f"{msg} — پذیرفته‌شده با دلیل: {m.group(1).strip()}"))
        else:
            self.error(line, f"{msg}؛ فقط با «# ext: allow(<دلیل>)» روی همان خط پذیرفته می‌شود.")


# ---------------------------------------------------------------------- قرارداد ساختار (۱)
def _structure(root: Path, plugin: str) -> list[Finding]:
    out: list[Finding] = []
    if not ID_RE.fullmatch(plugin):
        return [Finding("error", plugin, 0, "نام پوشه شناسه‌ی معتبر پلاگین نیست (حرف کوچک، عدد و _؛ با حرف شروع شود).")]
    for name in ("apps.py", "plugin.py"):
        if not (root / name).is_file():
            out.append(Finding("error", f"{plugin}/{name}", 0, f"فایل {name} الزامی است."))
    if (root / "urls.py").exists():
        out.append(Finding("error", f"{plugin}/urls.py", 0, "urls.py سراسری مجاز نیست؛ مسیرها فقط با kernel.routes."))
    if (root / "apps.py").is_file():
        tree = _parse(root / "apps.py", out, plugin)
        if tree:
            label = name = None
            for n in ast.walk(tree):
                if isinstance(n, ast.ClassDef):
                    for s in n.body:
                        if isinstance(s, ast.Assign) and len(s.targets) == 1 and isinstance(s.targets[0], ast.Name):
                            if s.targets[0].id == "label":
                                label = _const(s.value)
                            elif s.targets[0].id == "name":
                                name = _const(s.value)
            if label != f"x_{plugin}":
                out.append(Finding("error", f"{plugin}/apps.py", 0, f"label باید دقیقاً «x_{plugin}» باشد (پیشوند جدول‌ها)."))
            if name != f"ext.{plugin}":
                out.append(Finding("error", f"{plugin}/apps.py", 0, f"name باید دقیقاً «ext.{plugin}» باشد."))
    if (root / "plugin.py").is_file():
        tree = _parse(root / "plugin.py", out, plugin)
        if tree:
            found = False
            for n in ast.walk(tree):
                if isinstance(n, ast.Call) and _last(n.func) == "register" and n.args and _const(n.args[0]) == plugin:
                    found = True
                    if _const(_kw(n, "tier")) != 3:
                        out.append(Finding("error", f"{plugin}/plugin.py", n.lineno, "ثبت پلاگین باید tier=3 داشته باشد."))
                    if _const(_kw(n, "kind")) == "system":
                        out.append(Finding("error", f"{plugin}/plugin.py", n.lineno, "پلاگین سطح ۳ نمی‌تواند سیستمی باشد."))
            if not found:
                out.append(Finding("error", f"{plugin}/plugin.py", 0, f"ثبت «register('{plugin}', …)» با شناسه‌ی هم‌نام پوشه پیدا نشد."))
    return out


def _parse(path: Path, out: list[Finding], plugin: str):
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, ValueError, UnicodeDecodeError) as exc:
        out.append(Finding("error", f"{plugin}/{path.name}", getattr(exc, "lineno", 0) or 0, f"فایل قابل تجزیه نیست: {exc}"))
        return None


# ---------------------------------------------------------------------- پویش کد (۴.۴)
def _scan_code(plugin: str, rel: str, source: str, tree: ast.AST) -> list[Finding]:
    c = _Ctx(plugin, rel, source)
    imported: set[str] = set()
    own_classes = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Import):
            for a in node.names:
                imported.add((a.asname or a.name).split(".")[0])
                if a.name.split(".")[0] in WARN_MODULES:
                    c.warnable(line, f"واردکردن «{a.name}»")
        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".")[0]
            for a in node.names:
                imported.add(a.asname or a.name)
            if mod in WARN_MODULES:
                c.warnable(line, f"واردکردن از «{node.module}»")
        elif isinstance(node, ast.Call):
            fn = _last(node.func)
            if fn in WARN_CALLS and not isinstance(node.func, ast.Attribute) or fn in ("system", "popen"):
                c.warnable(line, f"فراخوانی «{fn}»")
            if fn == "connect" and isinstance(node.func, ast.Attribute) and _last(node.func.value) in SIGNALS:
                sender = _kw(node, "sender")
                if not (isinstance(sender, ast.Name) and sender.id in own_classes):
                    c.error(line, "شنونده‌ی سیگنال روی مدل غیرخودی ممنوع است؛ از kernel.events استفاده کنید.")
            if fn == "receiver":
                sigs = [a for a in node.args if _last(a) in SIGNALS]
                sender = _kw(node, "sender")
                if sigs and not (isinstance(sender, ast.Name) and sender.id in own_classes):
                    c.error(line, "شنونده‌ی سیگنال روی مدل غیرخودی ممنوع است؛ از kernel.events استفاده کنید.")
            if fn == "cursor" and isinstance(node.func, ast.Attribute) and _last(node.func.value) in ("connection", "connections"):
                c.error(line, "cursor() خام روی پایگاه پنل ممنوع است؛ از kernel.tenantdb و مدل‌ها استفاده کنید.")
            if fn in ("setattr", "delattr") and node.args and isinstance(node.args[0], ast.Name) and node.args[0].id in imported:
                c.error(line, "تغییر شیء ماژول بیرونی (monkeypatch) ممنوع است.")
            if fn in ("append", "extend", "insert") and isinstance(node.func, ast.Attribute) and _last(node.func.value) in GLOBAL_SETTINGS:
                c.error(line, f"تغییر تنظیم سراسری «{_last(node.func.value)}» ممنوع است.")
        elif isinstance(node, ast.Attribute):
            if node.attr in SECRET_SETTINGS:
                c.error(line, f"خواندن «{node.attr}» ممنوع است.")
        elif isinstance(node, ast.Name) and node.id in SECRET_SETTINGS:
            c.error(line, f"خواندن «{node.id}» ممنوع است.")
        elif isinstance(node, ast.Subscript) and _const(node.slice) in SECRET_SETTINGS:
            c.error(line, f"خواندن «{_const(node.slice)}» ممنوع است.")
        elif isinstance(node, (ast.Assign, ast.AugAssign)):
            for t in node.targets if isinstance(node, ast.Assign) else [node.target]:
                if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id in imported and t.value.id != "self":
                    if t.value.id == "settings" and t.attr in GLOBAL_SETTINGS:
                        c.error(line, f"تغییر تنظیم سراسری «{t.attr}» ممنوع است.")
                    elif t.value.id != "settings":
                        c.error(line, f"انتساب روی ویژگی ماژول بیرونی «{t.value.id}.{t.attr}» (monkeypatch) ممنوع است.")
                if isinstance(t, ast.Name) and t.id in GLOBAL_SETTINGS and isinstance(node, ast.AugAssign):
                    c.error(line, f"تغییر تنظیم سراسری «{t.id}» ممنوع است.")
        elif isinstance(node, ast.ClassDef) and node.name == "Meta":
            for s in node.body:
                if isinstance(s, ast.Assign) and len(s.targets) == 1 and isinstance(s.targets[0], ast.Name):
                    k, v = s.targets[0].id, _const(s.value)
                    if k == "db_table":
                        c.error(s.lineno, "Meta.db_table ممنوع است (نام جدول را برچسب x_<id> می‌سازد).")
                    elif k == "managed" and v is False:
                        c.error(s.lineno, "managed = False ممنوع است.")
                    elif k == "proxy" and v is True:
                        c.error(s.lineno, "مدل proxy ممنوع است.")
        if isinstance(node, ast.Call) and _last(node.func) == "add" and _last(getattr(node.func, "value", node)) == "routes":
            _route(c, node, plugin)
        if isinstance(node, ast.Call) and _last(node.func) in FK_KINDS:
            _fk(c, node, plugin)
    return c.out


def _route(c: _Ctx, call: ast.Call, plugin: str) -> None:
    group = _const(call.args[0]) if call.args else None
    route = _const(call.args[1]) if len(call.args) > 1 else None
    if group is not None and group not in EXT_GROUPS:
        c.error(call.lineno, f"گروه مسیر «{group}» برای پلاگین سطح ۳ مجاز نیست (فقط ext و ws_ext).")
    if group in EXT_GROUPS and isinstance(route, str) and not route.startswith(f"{plugin}/"):
        c.error(call.lineno, f"مسیر باید با «{plugin}/» شروع شود.")


def _fk(c: _Ctx, call: ast.Call, plugin: str) -> None:
    target = _const(call.args[0]) if call.args else _const(_kw(call, "to"))
    raw = call.args[0] if call.args else _kw(call, "to")
    od = _kw(call, "on_delete") or (call.args[1] if len(call.args) > 1 else None)
    if od is None or _last(od) not in ON_DELETE_OK:
        c.error(call.lineno, "کلید خارجی فقط با on_delete=CASCADE یا SET_NULL مجاز است (PROTECT/DO_NOTHING هسته را می‌شکند).")
    if isinstance(target, str):
        low = target.lower()
        own = "." not in low or low.startswith((f"x_{plugin}.", "self"))
        if not own and low not in FK_TARGETS_OK:
            c.error(call.lineno, f"کلید خارجی به «{target}» مجاز نیست (فقط مدل خودی، UserDatabase، User و Organization).")
    elif isinstance(raw, ast.Attribute) and raw.attr == "AUTH_USER_MODEL":
        pass
    elif isinstance(raw, (ast.Name, ast.Attribute)):
        pass  # کلاس مدل خودی یا import‌شده؛ قرارداد import هدف را می‌گیرد
    else:
        c.error(call.lineno, "هدف کلید خارجی باید نام ثابت یا کلاس مدل باشد.")


# ---------------------------------------------------------------------- مهاجرت (۴.۵)
def _scan_migration(plugin: str, rel: str, source: str, tree: ast.AST) -> list[Finding]:
    c = _Ctx(plugin, rel, source)
    privileged = bool(PRIV_RE.search(source))
    ops = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "operations" for t in node.targets):
            if isinstance(node.value, (ast.List, ast.Tuple)):
                ops = [e for e in node.value.elts]
            else:
                c.error(node.lineno, "operations باید فهرست ثابت باشد.")
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "dependencies" for t in node.targets):
            if isinstance(node.value, (ast.List, ast.Tuple)):
                for d in node.value.elts:
                    app = _const(d.elts[0]) if isinstance(d, ast.Tuple) and d.elts else None
                    if app is not None and app not in (f"x_{plugin}", "databases", "accounts", "kernel"):
                        c.error(node.lineno, f"وابستگی مهاجرت به «{app}» مجاز نیست.")
    for op in ops:
        name = _last(op.func) if isinstance(op, ast.Call) else ""
        line = getattr(op, "lineno", 0)
        if name in SAFE_MIGRATION_OPS:
            if name == "AddField":
                f = _kw(op, "field") or (op.args[2] if len(op.args) > 2 else None)
                if isinstance(f, ast.Call) and _last(f.func) != "ManyToManyField" \
                        and not any(k.arg in ("null", "default") for k in f.keywords):
                    c.error(line, "AddField باید null=True یا default داشته باشد (جدول پر را قفل نکند).")
            if name == "CreateModel":
                opts = _kw(op, "options")
                if isinstance(opts, ast.Dict) and any(_const(k) in ("db_table", "managed", "proxy") for k in opts.keys):
                    c.error(line, "db_table/managed/proxy در مهاجرت ممنوع است.")
        else:
            msg = f"عملیات «{name or '؟'}» ممتاز است (حذف/تغییر/ناشناخته)"
            if privileged:
                c.out.append(Finding("warn", rel, line, f"{msg} — پذیرفته‌شده با # ext: privileged-migration؛ در PR جدا بازبینی شود."))
            else:
                c.error(line, f"{msg}؛ فقط با «# ext: privileged-migration» در فایل و PR جدا.")
    return c.out


# ---------------------------------------------------------------------- نقطه‌ی ورود
def check_plugin(path: Path) -> list[Finding]:
    """همه‌ی بررسی‌ها برای یک پوشه‌ی `ext/<id>`."""
    plugin = path.name
    out = _structure(path, plugin)
    if not ID_RE.fullmatch(plugin):
        return out
    for f in sorted(path.rglob("*.py")):
        rel = f"{plugin}/{f.relative_to(path)}"
        parts = f.relative_to(path).parts
        try:
            source = f.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=rel)
        except (SyntaxError, ValueError, UnicodeDecodeError) as exc:
            if f.name not in ("apps.py", "plugin.py"):  # آن دو را بخش ساختار گزارش کرده
                out.append(Finding("error", rel, getattr(exc, "lineno", 0) or 0, f"فایل قابل تجزیه نیست: {exc}"))
            continue
        if "tests" in parts or f.name.startswith("test_"):
            continue  # آزمون‌ها فقط باید قابل تجزیه باشند
        if "migrations" in parts and f.name != "__init__.py":
            out += _scan_migration(plugin, rel, source, tree)
        out += _scan_code(plugin, rel, source, tree)
    if not any(p.is_dir() and p.name == "tests" for p in path.iterdir()) and not any(path.glob("test*.py")):
        out.append(Finding("error", f"{plugin}/tests", 0, "دست‌کم یک آزمون الزامی است (پوشه‌ی tests/)."))
    return sorted(out, key=lambda f: (f.level != "error", f.path, f.line))


def check_all(root: Path, only: str | None = None) -> dict[str, list[Finding]]:
    dirs = [d for d in sorted(root.iterdir()) if d.is_dir() and not d.name.startswith(("_", ".")) and d.name != "__pycache__"] if root.is_dir() else []
    return {d.name: check_plugin(d) for d in dirs if only in (None, d.name)}
