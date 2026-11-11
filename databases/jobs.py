"""handler کارهای پس‌زمینه‌ی بخش داده؛ در plugin.py ثبت می‌شوند."""


def do_find(job) -> None:
    """ذخیره‌ی نتیجه‌ی «یافتن عارضه» به‌صورت جدول ثابت یا نمای زنده."""
    from . import find_save
    from .explorer import Explorer
    from .find import Finder

    db = job.database
    ex = Explorer(db)
    job.set_progress(5, "بررسی شرط‌ها")
    plan = find_save.build(Finder(ex), job.params.get("spec"), job.params.get("opts"))
    res = find_save.create(db, ex, plan, step=job.set_progress)
    job.params = {**job.params, "result": res}
    what = "نمای زنده" if res["kind"] == "view" else "لایه"
    job.message = f"{what} {res['table']} با {res['rows']:,} عارضه ساخته شد."
