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


class SiteServiceDashboardSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteService
        fields = ['id', 'name', 'slug', 'category', 'price', 'price_usd', 'source_category', 'is_from_price']
        read_only_fields = ['id', 'name', 'slug', 'category', 'price', 'source_category', 'is_from_price']

    def validate(self, attrs):
        if 'price_usd' not in attrs:
            raise serializers.ValidationError({'price_usd': 'This field is required for a price update.'})
        return attrs

    def update(self, instance, validated_data):
        instance.price_usd = validated_data.get('price_usd', instance.price_usd)
        instance.price = self.context['exchange_rate'] * instance.price_usd
        from .services.pricing import round_toman_up
        instance.price = round_toman_up(instance.price)
        instance.save(update_fields=['price_usd', 'price'])
        return instance


class SiteProductDashboardSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteProduct
        fields = ['id', 'name', 'slug', 'price', 'price_usd', 'source_url']
        read_only_fields = ['id', 'name', 'slug', 'price', 'source_url']

    def validate(self, attrs):
        if 'price_usd' not in attrs:
            raise serializers.ValidationError({'price_usd': 'This field is required for a price update.'})
        return attrs

    def update(self, instance, validated_data):
        instance.price_usd = validated_data.get('price_usd', instance.price_usd)
        from .services.pricing import toman_price_from_usd
        instance.price = toman_price_from_usd(instance.price_usd, self.context['exchange_rate'])
        instance.save(update_fields=['price_usd', 'price'])
        return instance


class SitePackageDashboardSerializer(serializers.ModelSerializer):
    services = SiteServiceMiniSerializer(many=True, read_only=True)
    price_options = SitePackagePriceOptionSerializer(many=True, read_only=True)
    discount_percent = serializers.IntegerField(read_only=True)

    class Meta:
        model = SitePackage
        fields = [
            'id', 'name', 'slug', 'price', 'price_usd',
            'original_price', 'original_price_usd', 'discount_percent', 'services', 'price_options',
        ]
        read_only_fields = [
            'id', 'name', 'slug', 'price', 'original_price', 'discount_percent', 'services',
        ]

    def validate(self, attrs):
        if not {'price_usd', 'original_price_usd'} & attrs.keys():
            raise serializers.ValidationError(
                {'price_usd': 'Provide price_usd or original_price_usd for a price update.'}
            )
        return attrs

    def update(self, instance, validated_data):
        from .services.pricing import toman_price_from_usd
        instance.price_usd = validated_data.get('price_usd', instance.price_usd)
        instance.price = toman_price_from_usd(instance.price_usd, self.context['exchange_rate'])
        if 'original_price_usd' in validated_data:
            instance.original_price_usd = validated_data['original_price_usd']
            instance.original_price = (
                toman_price_from_usd(instance.original_price_usd, self.context['exchange_rate'])
                if instance.original_price_usd is not None else None
            )
        instance.save(update_fields=['price_usd', 'price', 'original_price_usd', 'original_price'])
        return instance


class SitePackagePriceOptionDashboardSerializer(serializers.ModelSerializer):
    class Meta:
        model = SitePackagePriceOption
        fields = [
            'id', 'package', 'label', 'session_count', 'gift_session_count',
            'price', 'price_usd', 'source_url', 'sort_order', 'is_active',
        ]
        read_only_fields = ['id', 'price', 'source_url']

    def validate(self, attrs):
        if 'price_usd' not in attrs:
            raise serializers.ValidationError({'price_usd': 'This field is required for a price update.'})
        return attrs

    def update(self, instance, validated_data):
        from .services.pricing import toman_price_from_usd
        instance.price_usd = validated_data['price_usd']
        instance.price = toman_price_from_usd(instance.price_usd, self.context['exchange_rate'])
        for field in ('label', 'session_count', 'gift_session_count', 'sort_order', 'is_active'):
            if field in validated_data:
                setattr(instance, field, validated_data[field])
        instance.save()
        return instance

    def create(self, validated_data):
        from .services.pricing import toman_price_from_usd
        validated_data['price'] = toman_price_from_usd(
            validated_data['price_usd'], self.context['exchange_rate'],
        )
        return super().create(validated_data)


class SiteSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteSettings
        fields = [
            'id', 'address', 'phone_numbers', 'working_hours', 'about_title',
            'about_text', 'statistics', 'hero_image_url', 'about_image_url', 'updated_at',
        ]
        read_only_fields = ['id', 'updated_at']


class WebsitePriceSyncRunSerializer(serializers.ModelSerializer):
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
