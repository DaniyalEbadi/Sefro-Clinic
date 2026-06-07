from rest_framework import serializers

from .models import ClinicUser


class ClinicUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClinicUser
        fields = ['id', 'username', 'first_name', 'last_name', 'phone_number', 'role']


class EmployeeCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = ClinicUser
        fields = ['id', 'username', 'first_name', 'last_name', 'phone_number', 'password']

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
        fields = ['id', 'username', 'first_name', 'last_name', 'phone_number', 'password']
        read_only_fields = ['id']

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance
