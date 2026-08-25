from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from Sefro_Clinic.fields import ShamsiDateTimeField

from .models import ClinicUser


class ClinicUserSerializer(serializers.ModelSerializer):
    date_joined = ShamsiDateTimeField(read_only=True)

    class Meta:
        model = ClinicUser
        fields = ['id', 'username', 'role', 'date_joined']


class EmployeeCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = ClinicUser
        fields = ['id', 'username', 'password', 'first_name', 'last_name', 'phone_number']

    def validate_password(self, value):
        candidate = ClinicUser(username=self.initial_data.get('username', ''))
        validate_password(value, user=candidate)
        return value

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = ClinicUser(**validated_data, role=ClinicUser.Role.EMPLOYEE)
        user.set_password(password)
        user.save()
        return user


class EmployeeUpdateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = ClinicUser
        fields = ['id', 'username', 'password', 'first_name', 'last_name', 'phone_number']
        read_only_fields = ['id']

    def validate_password(self, value):
        candidate = ClinicUser(username=self.initial_data.get('username', getattr(self.instance, 'username', '')))
        validate_password(value, user=candidate)
        return value

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance
