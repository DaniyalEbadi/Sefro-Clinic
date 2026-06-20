from rest_framework import serializers

from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    username = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = ['id', 'user', 'username', 'action', 'model_name', 'object_id', 'object_repr', 'changes', 'timestamp']
        read_only_fields = fields

    def get_username(self, obj):
        return obj.user.username if obj.user else 'system'
