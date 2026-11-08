"""ذخیره‌ی وضعیت کارها روی دیسک (فایل JSON کنار خروجی)؛ بدون دیتابیس تا نصب ساده بماند."""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

ID_RE = re.compile(r"^[0-9a-f]{32}$")


class Store:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.jobs, self.out, self.thumbs = (self.root / d for d in ("jobs", "out", "thumbs"))
        for d in (self.jobs, self.out, self.thumbs):
            d.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def path(self, job_id: str) -> Path:
        if not ID_RE.match(job_id):
            raise ValueError("شناسه نامعتبر")
        return self.jobs / f"{job_id}.json"

    def file(self, job_id: str) -> Path:
        if not ID_RE.match(job_id):
            raise ValueError("شناسه نامعتبر")
        return self.out / f"{job_id}.tif"

    def get(self, job_id: str) -> dict | None:
        try:
            return json.loads(self.path(job_id).read_text())
        except (FileNotFoundError, ValueError):
            return None

    def put(self, job: dict) -> None:
        with self._lock:
            p = self.path(job["id"])
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(job, ensure_ascii=False))
            tmp.replace(p)

    def update(self, job_id: str, **fields) -> dict:
        with self._lock:
            job = self.get(job_id) or {"id": job_id}
            job.update(fields, updated=int(time.time()))
            p = self.path(job_id)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(job, ensure_ascii=False))
            tmp.replace(p)
            return job

    def delete(self, job_id: str) -> None:
        self.file(job_id).unlink(missing_ok=True)
        self.file(job_id).with_suffix(".part.tif").unlink(missing_ok=True)
        self.path(job_id).unlink(missing_ok=True)

    def cleanup(self, keep_hours: float, now: float | None = None) -> int:
        """کار و فایل‌های قدیمی‌تر از مهلت را پاک می‌کند؛ دروازه چیزی نگه نمی‌دارد."""
        cutoff = (now or time.time()) - keep_hours * 3600
        n = 0
        for d in (self.jobs, self.out, self.thumbs):
            for f in d.iterdir():
                try:
                    if f.stat().st_mtime < cutoff:
                        f.unlink()
                        n += 1
                except OSError:
                    pass
        return n

    def disk_files(self) -> int:
        return sum(1 for _ in self.out.iterdir())

    def active(self) -> int:
        n = 0
        for f in self.jobs.glob("*.json"):
            try:
                if json.loads(f.read_text()).get("status") in ("queued", "running"):
                    n += 1
            except (OSError, ValueError):
                pass
        return n
