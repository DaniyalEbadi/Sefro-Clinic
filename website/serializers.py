from decimal import Decimal

from rest_framework import serializers

from Sefro_Clinic.fields import ShamsiDateTimeField

from .models import (
    ContactMessage,
    SitePackage,
    SitePackagePriceOption,
    SiteProduct,
    SiteService,
    SiteSettings,
    TeamMember,
    Testimonial,
    WebsitePriceSyncRun,
)
from .services.pricing import round_toman_up, toman_price_from_usd, usd_price_from_toman


class SiteServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteService
        fields = [
            'id', 'name', 'slug', 'category', 'short_description',
            'description', 'price', 'price_usd', 'duration_label', 'image_url',
            'source_category', 'is_from_price', 'source_url',
        ]


class SiteServiceMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteService
        fields = ['id', 'name', 'slug']


class SitePackageSerializer(serializers.ModelSerializer):
    services = SiteServiceMiniSerializer(many=True, read_only=True)
    price_options = serializers.SerializerMethodField()
    discount_percent = serializers.IntegerField(read_only=True)

    class Meta:
        model = SitePackage
        fields = [
            'id', 'name', 'slug', 'tier', 'tagline', 'badge',
            'price', 'price_usd', 'original_price', 'original_price_usd', 'discount_percent',
            'free_service_count', 'services', 'price_options',
        ]

    def get_price_options(self, obj):
        return SitePackagePriceOptionSerializer(
            obj.price_options.filter(is_active=True), many=True,
        ).data


class SitePackagePriceOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = SitePackagePriceOption
        fields = [
            'id', 'package', 'label', 'session_count', 'gift_session_count',
            'price', 'price_usd', 'source_url', 'sort_order', 'is_active',
        ]


class SiteProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteProduct
        fields = [
            'id', 'name', 'slug', 'short_description', 'price', 'price_usd',
            'image_url', 'source_url',
        ]


class TomanPriceField(serializers.DecimalField):
    def __init__(self, **kwargs):
        super().__init__(
            max_digits=None, decimal_places=None, min_value=Decimal('0'),
            max_value=Decimal('999999999999'),
            required=False, **kwargs,
        )

    def to_representation(self, value):
        return format(value, '.2f') if value is not None else None


class WebsitePriceInputMixin:
    """Accept either currency for each price and store the matching pair."""

    price_pairs = (('price', 'price_usd'),)
    require_price_update = True

    def validate(self, attrs):
        attrs = super().validate(attrs)
        price_fields = {field for pair in self.price_pairs for field in pair}
        if self.require_price_update and not price_fields.intersection(attrs):
            raise serializers.ValidationError({'price': 'Provide a Toman price or a USD price.'})
        for toman_field, usd_field in self.price_pairs:
            if toman_field in attrs and usd_field in attrs:
                raise serializers.ValidationError({
                    toman_field: f'Provide either {toman_field} (Toman) or {usd_field} (USD), not both.',
                })
            if toman_field not in attrs and usd_field not in attrs:
                continue
            if attrs.get(toman_field, attrs.get(usd_field)) is None:
                attrs[toman_field] = attrs[usd_field] = None
                continue
            rate = self.context['exchange_rate']
            if toman_field in attrs:
                attrs[toman_field] = round_toman_up(attrs[toman_field])
                attrs[usd_field] = self.fields[usd_field].run_validation(
                    usd_price_from_toman(attrs[toman_field], rate),
                )
            else:
                attrs[toman_field] = toman_price_from_usd(attrs[usd_field], rate)
            field = self.Meta.model._meta.get_field(toman_field)
            maximum = Decimal(10) ** (field.max_digits - field.decimal_places) - 1
            if attrs[toman_field] > maximum:
                raise serializers.ValidationError({toman_field: f'Price must not exceed {maximum} Toman.'})
        return attrs


class SiteServiceDashboardSerializer(WebsitePriceInputMixin, serializers.ModelSerializer):
    require_price_update = False
    price = TomanPriceField(help_text='Toman price; rounded upward to a whole Toman. Send price OR price_usd.')

    class Meta:
        model = SiteService
        fields = [
            'id', 'name', 'slug', 'category', 'source_category', 'short_description',
            'description', 'price', 'price_usd', 'is_from_price', 'duration_label',
            'image_url', 'image_object_key', 'source_url', 'is_active', 'sort_order',
        ]
        read_only_fields = ['id', 'image_object_key']

    def validate(self, attrs):
        self.require_price_update = self.instance is None
        if self.instance is not None and 'slug' in attrs and attrs['slug'] != self.instance.slug:
            raise serializers.ValidationError({'slug': 'An existing catalog slug cannot be changed.'})
        return super().validate(attrs)

    def create(self, validated_data):
        validated_data['is_manually_managed'] = True
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if 'image_url' in validated_data and validated_data['image_url'] != instance.image_url:
            validated_data['image_object_key'] = ''
        validated_data['is_manually_managed'] = True
        return super().update(instance, validated_data)


class SiteServiceImageUploadSerializer(serializers.Serializer):
    image = serializers.ImageField(help_text='JPEG, PNG, or WebP; maximum 5 MB.')


class SiteProductDashboardSerializer(WebsitePriceInputMixin, serializers.ModelSerializer):
    price = TomanPriceField(help_text='Toman price; rounded upward to a whole Toman. Send price OR price_usd.')

    class Meta:
        model = SiteProduct
        fields = [
            'id', 'name', 'slug', 'short_description', 'price', 'price_usd',
            'image_url', 'source_url', 'is_active', 'sort_order',
        ]
        read_only_fields = ['id']

    def validate(self, attrs):
        self.require_price_update = self.instance is None
        if self.instance is not None and 'slug' in attrs and attrs['slug'] != self.instance.slug:
            raise serializers.ValidationError({'slug': 'An existing catalog slug cannot be changed.'})
        return super().validate(attrs)

    def create(self, validated_data):
        validated_data['is_manually_managed'] = True
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data['is_manually_managed'] = True
        return super().update(instance, validated_data)


class SitePackageDashboardSerializer(WebsitePriceInputMixin, serializers.ModelSerializer):
    price_pairs = (('price', 'price_usd'), ('original_price', 'original_price_usd'))
    price = TomanPriceField(help_text='Current Toman price. Send price OR price_usd.')
    original_price = TomanPriceField(
        allow_null=True, help_text='Original Toman price; null removes it. Send original_price OR original_price_usd.',
    )
    services = SiteServiceMiniSerializer(many=True, read_only=True)
    service_ids = serializers.PrimaryKeyRelatedField(
        source='services', many=True, queryset=SiteService.objects.filter(is_active=True),
        required=False, write_only=True,
    )
    price_options = SitePackagePriceOptionSerializer(many=True, read_only=True)
    discount_percent = serializers.IntegerField(read_only=True)

    class Meta:
        model = SitePackage
        fields = [
            'id', 'name', 'slug', 'tier', 'tagline', 'badge', 'free_service_count',
            'price', 'price_usd', 'original_price', 'original_price_usd',
            'discount_percent', 'services', 'service_ids', 'price_options',
            'source_url', 'is_active', 'sort_order',
        ]
        read_only_fields = ['id', 'discount_percent', 'services', 'price_options']

    def validate(self, attrs):
        self.require_price_update = self.instance is None
        if self.instance is not None and 'slug' in attrs and attrs['slug'] != self.instance.slug:
            raise serializers.ValidationError({'slug': 'An existing catalog slug cannot be changed.'})
        return super().validate(attrs)

    def create(self, validated_data):
        validated_data['is_manually_managed'] = True
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data['is_manually_managed'] = True
        return super().update(instance, validated_data)


class SitePackagePriceOptionDashboardSerializer(WebsitePriceInputMixin, serializers.ModelSerializer):
    price = TomanPriceField(help_text='Toman price for this option. Send price OR price_usd.')
    class Meta:
        model = SitePackagePriceOption
        fields = [
            'id', 'package', 'label', 'session_count', 'gift_session_count',
            'price', 'price_usd', 'source_url', 'sort_order', 'is_active',
        ]
        read_only_fields = ['id', 'source_url']

    def validate(self, attrs):
        self.require_price_update = self.instance is None
        if self.instance is not None and 'package' in attrs and attrs['package'] != self.instance.package:
            raise serializers.ValidationError({'package': 'An existing price option cannot be moved to another package.'})
        return super().validate(attrs)

    def create(self, validated_data):
        instance = super().create(validated_data)
        SitePackage.objects.filter(pk=instance.package_id).update(is_manually_managed=True)
        return instance

    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)
        SitePackage.objects.filter(pk=instance.package_id).update(is_manually_managed=True)
        return instance


class SiteSettingsSerializer(serializers.ModelSerializer):
    updated_at = ShamsiDateTimeField(read_only=True)

    class Meta:
        model = SiteSettings
        fields = [
            'id', 'address', 'phone_numbers', 'working_hours', 'about_title',
            'about_text', 'statistics', 'hero_image_url', 'about_image_url', 'updated_at',
        ]
        read_only_fields = ['id', 'updated_at']

    def update(self, instance, validated_data):
        validated_data['is_manually_managed'] = True
        return super().update(instance, validated_data)


class WebsitePriceSyncRunSerializer(serializers.ModelSerializer):
    started_at = ShamsiDateTimeField(read_only=True)
    finished_at = ShamsiDateTimeField(read_only=True, allow_null=True)

    class Meta:
        model = WebsitePriceSyncRun
        fields = [
            'id', 'status', 'provider', 'rate', 'started_at', 'finished_at',
            'updated_services', 'updated_packages', 'updated_products', 'error',
        ]
        read_only_fields = fields


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
    created_at = ShamsiDateTimeField(read_only=True)

    class Meta:
        model = ContactMessage
        fields = ['id', 'full_name', 'phone', 'message', 'created_at']
        read_only_fields = ['id', 'created_at']


class TeamMemberDashboardSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeamMember
        fields = ['id', 'name', 'role', 'bio', 'image_url', 'is_active', 'sort_order']
        read_only_fields = ['id']

    def create(self, validated_data):
        validated_data['is_manually_managed'] = True
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data['is_manually_managed'] = True
        return super().update(instance, validated_data)


class TestimonialDashboardSerializer(serializers.ModelSerializer):
    class Meta:
        model = Testimonial
        fields = ['id', 'customer_name', 'label', 'text', 'is_active', 'sort_order']
        read_only_fields = ['id']

    def create(self, validated_data):
        validated_data['is_manually_managed'] = True
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data['is_manually_managed'] = True
        return super().update(instance, validated_data)


class ContactMessageDashboardSerializer(serializers.ModelSerializer):
    created_at = ShamsiDateTimeField(read_only=True)

    class Meta:
        model = ContactMessage
        fields = ['id', 'full_name', 'phone', 'message', 'created_at', 'is_handled']
        read_only_fields = ['id', 'full_name', 'phone', 'message', 'created_at']
