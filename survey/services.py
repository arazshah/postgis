"""ساخت و بایگانی پروژه‌های برداشت میدانی."""
import logging

import psycopg
from django.db import transaction
from django.utils import timezone
from psycopg import sql

from databases.explorer import Explorer, ExplorerError

from . import crs, ddl, presets
from .models import SurveyProject

log = logging.getLogger(__name__)


class SurveyError(Exception):
    """خطایی که پیامش مستقیم به کاربر نشان داده می‌شود."""


def active_projects(db):
    return SurveyProject.objects.filter(database=db, archived_at__isnull=True)


def quota_left(db) -> int:
    return max(db.plan.survey_projects - active_projects(db).count(), 0)


def create_project(db, user, name: str, srid, template: str = "blank") -> SurveyProject:
    name = (name or "").strip()
    if not name:
        raise SurveyError("نام پروژه را بنویسید.")
    if len(name) > 120:
        raise SurveyError("نام پروژه بیش از حد بلند است.")
    if template not in presets.TEMPLATES:
        raise SurveyError("قالب پروژه نامعتبر است.")
    if db.plan.survey_projects <= 0:
        raise SurveyError("پلن شما برداشت میدانی ندارد.")
    if quota_left(db) <= 0:
        raise SurveyError(f"سهمیه پروژه برداشت پلن شما ({db.plan.survey_projects}) پر شده است.")

    slug = ddl.new_slug()
    explorer = Explorer(db)
    try:
        with explorer.connect(read_only=False) as conn:
            try:
                srid = crs.validate_srid(srid, conn)
            except crs.CrsError as exc:
                raise SurveyError(str(exc)) from exc
            try:
                conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(db.role_name)))
                conn.execute(sql.SQL("SET LOCAL lock_timeout = '5s'"))
                ddl.create_schema(conn, slug, srid, template)
                conn.commit()
            except psycopg.Error as exc:
                conn.rollback()
                log.warning("survey ddl failed for %s: %s", db.pk, exc)
                raise SurveyError("ساخت پروژه در پایگاه داده شما ممکن نشد.") from exc
    except ExplorerError as exc:
        raise SurveyError(str(exc)) from exc

    try:
        with transaction.atomic():
            return SurveyProject.objects.create(database=db, slug=slug, name=name, srid=srid, template=template,
                                                created_by=user)
    except Exception:
        _drop_quietly(db, slug)
        raise


def _drop_quietly(db, slug: str) -> None:
    try:
        with Explorer(db).connect(read_only=False) as conn:
            conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(db.role_name)))
            ddl.drop_schema(conn, slug)
            conn.commit()
    except Exception:  # noqa: BLE001 - جبران بهترین‌تلاش؛ خطای اصلی مهم‌تر است
        log.exception("survey compensation failed for %s", slug)


def archive_project(project: SurveyProject) -> None:
    if project.archived_at is None:
        project.archived_at = timezone.now()
        project.save(update_fields=["archived_at"])
