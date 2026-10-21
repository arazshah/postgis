"""کلاینت کوچک سرویس سازگار با OpenAI (AvalAI و مشابه): embedding و گفتگو، بدون وابستگی اضافه."""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Iterator

from django.conf import settings

log = logging.getLogger(__name__)
EMBED_TIMEOUT = 30
CHAT_TIMEOUT = 60


class LLMError(Exception):
    """پیام فارسی و امن برای کاربر یا مدیر (بدون کلید یا بدنه خطای ارائه‌دهنده)."""


def _base(conf) -> str:
    base = (conf.assistant_base_url or "").strip().rstrip("/")
    if not (base.startswith("https://") or (settings.DEBUG and base.startswith("http://"))):
        raise LLMError("آدرس سرویس باید با https:// شروع شود.")
    return base


def _open(conf, path: str, payload: dict, timeout: int):
    key = conf.get_assistant_api_key()
    if not key:
        raise LLMError("کلید API دستیار تنظیم نشده است.")
    req = urllib.request.Request(
        f"{_base(conf)}{path}", data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "Accept": "application/json", "User-Agent": "geopaygah-assistant/1"})
    try:
        return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 — آدرس از تنظیمات مدیر و فقط https
    except urllib.error.HTTPError as exc:
        body = exc.read(500).decode("utf-8", "replace")
        log.warning("assistant upstream %s on %s: %s", exc.code, path, body)
        if exc.code in (401, 403):
            raise LLMError("کلید API پذیرفته نشد؛ کلید یا دسترسی مدل را در تنظیمات بررسی کنید.") from exc
        if exc.code == 404:
            raise LLMError("مدل یا آدرس سرویس پیدا نشد؛ نام مدل و آدرس را بررسی کنید.") from exc
        if exc.code == 429:
            raise LLMError("سرویس مدل زبانی موقتاً شلوغ است یا اعتبار حساب تمام شده است.") from exc
        raise LLMError(f"سرویس مدل زبانی خطا داد (کد {exc.code}).") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.warning("assistant upstream unreachable: %s", exc)
        raise LLMError("اتصال به سرویس مدل زبانی برقرار نشد.") from exc


def embed(conf, texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    with _open(conf, "/embeddings", {"model": conf.assistant_embedding_model, "input": texts}, EMBED_TIMEOUT) as r:
        try:
            data = json.load(r)["data"]
            data.sort(key=lambda d: d.get("index", 0))
            vecs = [d["embedding"] for d in data]
        except (ValueError, KeyError, TypeError) as exc:
            raise LLMError("پاسخ embedding از سرویس قابل فهم نبود.") from exc
    if len(vecs) != len(texts):
        raise LLMError("تعداد embeddingها با ورودی‌ها نمی‌خواند.")
    return vecs


def _chat_payload(conf, messages: list[dict], max_tokens: int | None, stream: bool) -> dict:
    return {"model": conf.assistant_chat_model, "messages": messages, "temperature": 0.2,
            "max_tokens": max_tokens or conf.assistant_max_tokens, "stream": stream}


def chat(conf, messages: list[dict], max_tokens: int | None = None) -> str:
    with _open(conf, "/chat/completions", _chat_payload(conf, messages, max_tokens, False), CHAT_TIMEOUT) as r:
        try:
            return json.load(r)["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError("پاسخ مدل قابل فهم نبود.") from exc


def chat_stream(conf, messages: list[dict], max_tokens: int | None = None) -> Iterator[str]:
    """تکه‌های متن پاسخ را به‌تدریج می‌دهد (SSE سازگار با OpenAI)."""
    with _open(conf, "/chat/completions", _chat_payload(conf, messages, max_tokens, True), CHAT_TIMEOUT) as r:
        try:
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    delta = json.loads(data)["choices"][0].get("delta", {}).get("content")
                except (ValueError, KeyError, IndexError, TypeError):
                    continue
                if delta:
                    yield delta
        except (TimeoutError, OSError) as exc:
            raise LLMError("ارتباط با سرویس مدل زبانی در میانه پاسخ قطع شد.") from exc


def ping(conf) -> dict:
    """آزمایش اتصال برای پنل مدیریت: یک embedding و یک پاسخ کوتاه."""
    vec = embed(conf, ["آزمایش"])[0]
    reply = chat(conf, [{"role": "user", "content": "فقط بنویس: آماده"}], max_tokens=20)
    return {"dims": len(vec), "reply": reply.strip()[:60]}
