"""مدت واقعی هر ویدیو (ffprobe) را در Guide(...) فایل core/help.py می‌نویسد: python docs/help-video/sync_seconds.py"""
import re
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[2]
p = root / "core" / "help.py"
s = p.read_text(encoding="utf-8")
n = 0


def dur(slug):
    f = root / "static" / "help" / "video" / f"{slug}.mp4"
    if not f.is_file():
        return None
    try:
        out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                                      text=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        return None  # فایل نیمه‌کاره (در حال ساخت)
    return round(float(out))


def fix(m):
    global n
    slug = m.group(1)
    d = dur(slug)
    if d is None or d == int(m.group(3)):
        return m.group(0)
    n += 1
    return m.group(0).replace(f"{m.group(2)} {m.group(3)},", f"{m.group(2)} {d},", 1)


s = re.sub(r'Guide\(\n        "([a-z-]+)", "[^"]+",\n        "[^"]+",\n        ("[a-z]+",) (\d+),', fix, s)
p.write_text(s, encoding="utf-8")
print(n, "مدت به‌روز شد")
