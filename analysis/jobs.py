"""handler کارهای پس‌زمینه‌ی تحلیل (ابزار آماده و پرسش فارسی) و متن اعلان آن‌ها؛ در plugin.py ثبت می‌شوند."""


def do_tool(job) -> None:
    from . import tools

    res = tools.run_job(job)
    job.message = f"جدول {res['table']} با {res['rows']:,} عارضه ساخته شد."


def do_ask(job) -> None:
    from . import ask

    job.message = ask.run(job)


def tool_subject(job):
    run = getattr(job, "tool_run", None)
    if run is None:
        return None
    from . import tools

    t = tools.TOOL_MAP.get(run.tool)
    return f"«{t.title if t else run.tool}»"


def ask_subject(job):
    q = getattr(job, "question", None)
    return f"«{q.text[:60]}»" if q else "پرسش فارسی"


def ask_notice(job, subject):
    """اعلان پایان پرسش فارسی بسته به نوع نتیجه (برنامه‌ی منتظر تأیید، بدون عارضه، پاسخ متنی)."""
    q = getattr(job, "question", None)
    if q is None:
        return None
    if q.result_kind == "plan":
        return {"level": "info", "title": "برنامهٔ تحلیل آمادهٔ تأیید است", "body": "برنامه را بررسی و تأیید کنید.",
                "action": "بررسی برنامه"}
    if q.result_kind == "empty":
        return {"level": "warning", "title": f"{subject}: هیچ عارضه‌ای پیدا نشد"}
    if q.result_kind == "answer":
        return {"title": f"{subject}: پاسخ آماده است"}
    return None
