"""handler کار پس‌زمینه‌ی ابزار تحلیل و نام آن در اعلان؛ در plugin.py ثبت می‌شوند."""


def do_tool(job) -> None:
    from . import engine

    res = engine.run_job(job)
    job.message = f"جدول {res['table']} با {res['rows']:,} عارضه ساخته شد."


def subject(job):
    run = getattr(job, "tool_run", None)
    if run is None:
        return None
    from . import sdk

    t = sdk.get(run.tool)
    return f"«{t.title if t else run.tool}»"
