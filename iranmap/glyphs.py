"""
ساخت فایل‌های glyph (PBF با SDF) برای برچسب‌های نقشه برداری MapLibre از قلم وزیرمتن.

نقشه پایه برداری به جای تصویر، متن را در مرورگر می‌کشد و برای هر بازه ۲۵۶تایی یونیکد یک فایل
«<fontstack>/<start>-<end>.pbf» می‌خواهد. سرورهای عمومی glyph (مثل GitHub یا Mapbox) ممکن است از ایران
در دسترس نباشند؛ این دستور آن‌ها را یک بار از قلمی که خودمان داریم می‌سازد.

قالب: glyphs.proto مپ‌باکس (fontstack › glyph: id, bitmap, width, height, left, top, advance)،
اندازه ۲۴ پیکسل، حاشیه ۳، شعاع ۸ و cutoff ۰٫۲۵ (همان پیش‌فرض fontnik).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import distance_transform_edt

SIZE = 24
BUFFER = 3
RADIUS = 8
CUTOFF = 0.25
# لاتین، عربی/فارسی و شکل‌های نمایشی عربی (افزونه rtl-text متن را به این شکل‌ها تبدیل می‌کند)
RANGES = [0, 256, 512, 768, 1536, 1792, 2048, 8192, 64256, 64512, 64768, 65024]


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _key(field: int, wire: int) -> bytes:
    return _varint((field << 3) | wire)


def _uint(field: int, v: int) -> bytes:
    return _key(field, 0) + _varint(v)


def _sint(field: int, v: int) -> bytes:
    return _key(field, 0) + _varint((v << 1) ^ (v >> 31))


def _bytes(field: int, b: bytes) -> bytes:
    return _key(field, 2) + _varint(len(b)) + b


def _sdf(mask: np.ndarray) -> np.ndarray:
    inside = mask > 127
    if not inside.any():
        return np.zeros(mask.shape, np.uint8)
    d_out = distance_transform_edt(~inside)
    d_in = distance_transform_edt(inside)
    d = d_out - d_in
    v = 255 - 255 * (d / RADIUS + CUTOFF)
    return np.clip(v, 0, 255).astype(np.uint8)


def glyph_record(font: ImageFont.FreeTypeFont, code: int, ascent: int) -> bytes | None:
    ch = chr(code)
    try:
        if font.getmask(ch).getbbox() is None and not ch.isspace():
            return None
    except Exception:  # noqa: BLE001
        return None
    advance = int(round(font.getlength(ch)))
    box = font.getbbox(ch, anchor="ls")  # نسبت به خط پایه
    if ch.isspace() or box[2] <= box[0] or box[3] <= box[1]:
        return _uint(1, code) + _uint(3, 0) + _uint(4, 0) + _sint(5, 0) + _sint(6, -26) + _uint(7, advance)
    left, top, right, bottom = box
    w, h = right - left, bottom - top
    img = Image.new("L", (w + 2 * BUFFER, h + 2 * BUFFER), 0)
    ImageDraw.Draw(img).text((BUFFER - left, BUFFER - top), ch, font=font, fill=255, anchor="ls")
    sdf = _sdf(np.array(img))
    return (_uint(1, code) + _bytes(2, sdf.tobytes()) + _uint(3, w) + _uint(4, h) + _sint(5, left)
            + _sint(6, -top - ascent) + _uint(7, advance))


def build(font_path: str, fontstack: str, out_dir: Path) -> int:
    font = ImageFont.truetype(font_path, SIZE)
    ascent = 24  # MapLibre خط پایه را ۲۴ پیکسل زیر بالای جعبه فرض می‌کند
    folder = out_dir / fontstack
    folder.mkdir(parents=True, exist_ok=True)
    count = 0
    for start in range(0, 65536, 256):
        end = start + 255
        body = b""
        if start in RANGES:
            for code in range(start, end + 1):
                rec = glyph_record(font, code, ascent)
                if rec is not None:
                    body += _bytes(3, rec)
                    count += 1
        stack = _bytes(1, fontstack.encode()) + _bytes(2, f"{start}-{end}".encode()) + body
        (folder / f"{start}-{end}.pbf").write_bytes(_bytes(1, stack))
    return count
