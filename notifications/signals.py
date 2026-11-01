from django.db.models.signals import post_save
from django.dispatch import receiver

from jobs.models import Job

from . import services


@receiver(post_save, sender=Job)
def job_finished(sender, instance, **kwargs):
    if instance.status in (Job.Status.DONE, Job.Status.FAILED):
        services.for_job(instance)
