from rest_framework import serializers

from Sefro_Clinic.fields import ShamsiDateTimeField

from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    username = serializers.SerializerMethodField()
    timestamp = ShamsiDateTimeField(read_only=True)

    class Meta:
        model = AuditLog
        fields = ['id', 'user', 'username', 'action', 'model_name', 'object_id', 'object_repr', 'changes', 'timestamp']
        read_only_fields = fields

    def get_username(self, obj):
        return obj.user.username if obj.user else 'system'
