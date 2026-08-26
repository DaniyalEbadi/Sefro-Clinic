from rest_framework import serializers

from .models import (
    ContactMessage,
    SitePackage,
    SiteProduct,
    SiteService,
    TeamMember,
    Testimonial,
)


class SiteServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteService
        fields = [
            'id', 'name', 'slug', 'category', 'short_description',
            'description', 'price', 'duration_label', 'image_url',
        ]


class SiteServiceMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteService
        fields = ['id', 'name', 'slug']


class SitePackageSerializer(serializers.ModelSerializer):
    services = SiteServiceMiniSerializer(many=True, read_only=True)
    discount_percent = serializers.IntegerField(read_only=True)

    class Meta:
        model = SitePackage
        fields = [
            'id', 'name', 'slug', 'tier', 'tagline', 'badge',
            'price', 'original_price', 'discount_percent',
            'free_service_count', 'services',
        ]


class SiteProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteProduct
        fields = ['id', 'name', 'slug', 'short_description', 'price', 'image_url']


class TeamMemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeamMember
        fields = ['id', 'name', 'role', 'bio', 'image_url']


class TestimonialSerializer(serializers.ModelSerializer):
    class Meta:
        model = Testimonial
        fields = ['id', 'customer_name', 'label', 'text']


class ContactMessageSerializer(serializers.ModelSerializer):
    phone = serializers.RegexField(
        regex=r'^09\d{9}$',
        error_messages={'invalid': 'شماره موبایل معتبر نیست. نمونه: 09121234567'},
    )

    class Meta:
        model = ContactMessage
        fields = ['id', 'full_name', 'phone', 'message', 'created_at']
        read_only_fields = ['id', 'created_at']
