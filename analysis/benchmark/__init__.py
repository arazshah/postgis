"""سنجش دقت پرسش فارسی: پرسش‌هایی با پاسخ درست روی دادهٔ نمونهٔ کلاس درس، بدون نیاز به پایگاه داده.

هر پرسش با همان مسیر محصول (`ask.analyze`) اجرا می‌شود و نتیجه (نوع و تعداد) با پاسخ درست مقایسه می‌شود؛
پاسخ درست را مستقل از s3geo و با shapely روی همان داده حساب کرده‌ایم.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAMPLE = HERE.parents[1] / "classroom" / "sample"
LAYER_NAMES = ("schools", "metro_stations", "parks")


def load_questions() -> list[dict]:
    return json.loads((HERE / "questions.json").read_text(encoding="utf-8"))


def load_layers() -> dict:
    return {n: json.loads((SAMPLE / f"{n}.geojson").read_text(encoding="utf-8")) for n in LAYER_NAMES}


def run(client, questions=None, layers=None, share_values: bool = True, on_row=None) -> list[dict]:
    from analysis import ask

    layers = layers or load_layers()
    rows = []
    for i, item in enumerate(questions or load_questions(), 1):
        t = time.time()
        row = {"n": i, "q": item["q"], "expected": item["expected"], "kind_expected": item["kind"]}
        try:
            out = ask.analyze(item["q"], layers, client, share_values)
            got = len(out.feats) if out.kind == "layer" else len(out.rows) if out.kind == "table" else 0
            row.update(kind=out.kind, got=got, attempts=out.attempts, error=out.error)
            row["ok"] = out.kind == item["kind"] and got == item["expected"]
        except Exception as exc:  # noqa: BLE001  خطای مدل زبانی یا اتصال، برای همین پرسش شکست است
            row.update(kind="error", got=0, attempts=0, error=str(exc)[:200], ok=False)
        row["seconds"] = round(time.time() - t, 1)
        rows.append(row)
        if on_row:
            on_row(row)
    return rows


def summary(rows: list[dict]) -> dict:
    n = len(rows) or 1
    ok = sum(r["ok"] for r in rows)
    return {"total": len(rows), "passed": ok, "accuracy": round(100 * ok / n),
            "first_try": sum(r["ok"] and r["attempts"] == 1 for r in rows),
            "repaired": sum(r["ok"] and r["attempts"] > 1 for r in rows),
            "avg_attempts": round(sum(r["attempts"] for r in rows) / n, 2)}
