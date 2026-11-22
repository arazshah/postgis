from django.db import models


class LiveTicket(models.Model):
    digest = models.CharField(max_length=64, unique=True)
    main_session = models.CharField(max_length=40)
    user_id = models.PositiveBigIntegerField()
    workspace_id = models.PositiveBigIntegerField()
    expires_at = models.DateTimeField(db_index=True)
