"""handler کارهای پس‌زمینه‌ی امکانات سازمانی؛ در plugin.py ثبت می‌شوند."""


def _run(fn_name: str, job) -> None:
    from . import services as ent

    job.message = getattr(ent, fn_name)(job)


def do_geoserver(job) -> None:
    _run("provision", job)


def do_raster(job) -> None:
    _run("process_raster", job)


def do_clone(job) -> None:
    _run("do_clone", job)


def tick_rasters_dir(now=None) -> None:
    from . import services as ent

    ent.cleanup_rasters_dir()
