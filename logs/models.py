from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    class Action(models.TextChoices):
        CREATE = 'CREATE'
        UPDATE = 'UPDATE'
        DELETE = 'DELETE'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_logs')
    action = models.CharField(max_length=10, choices=Action.choices)
    model_name = models.CharField(max_length=255)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    object_repr = models.CharField(max_length=255, blank=True)
    changes = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'audit log'
        verbose_name_plural = 'audit logs'

    def __str__(self):
        return f'{self.user} {self.action} {self.model_name}#{self.object_id} at {self.timestamp}'
