from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions, status, viewsets
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from accounts.permissions import IsAdminOrEmployee
from accounts.views import ClinicTokenObtainPairView
from finance.services.exchange_rates import get_current_usd_to_toman_rate

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
from .serializers import (
    ContactMessageSerializer,
    SitePackageDashboardSerializer,
    SitePackagePriceOptionDashboardSerializer,
    SitePackageSerializer,
    SiteProductDashboardSerializer,
    SiteProductSerializer,
    SiteServiceDashboardSerializer,
    SiteServiceSerializer,
    SiteSettingsSerializer,
    TeamMemberSerializer,
    TestimonialSerializer,
    WebsitePriceSyncRunSerializer,
)


class PublicReadOnlyMixin:
    permission_classes = [permissions.AllowAny]


@extend_schema(tags=['Site Services'])
class SiteServiceViewSet(PublicReadOnlyMixin, viewsets.ReadOnlyModelViewSet):
    queryset = SiteService.objects.filter(is_active=True)
    serializer_class = SiteServiceSerializer
    lookup_field = 'slug'

    def get_queryset(self):
        queryset = super().get_queryset()
        category = self.request.query_params.get('category')
        if category:
            queryset = queryset.filter(category=category)
        return queryset


@extend_schema(tags=['Site Packages'])
class SitePackageViewSet(PublicReadOnlyMixin, viewsets.ReadOnlyModelViewSet):
    queryset = SitePackage.objects.filter(is_active=True).prefetch_related('services')
    serializer_class = SitePackageSerializer
    lookup_field = 'slug'


@extend_schema(tags=['Site Products'])
class SiteProductViewSet(PublicReadOnlyMixin, viewsets.ReadOnlyModelViewSet):
    queryset = SiteProduct.objects.filter(is_active=True)
    serializer_class = SiteProductSerializer
    lookup_field = 'slug'


class WebsitePriceDashboardMixin:
    permission_classes = [IsAdminOrEmployee]
    lookup_field = 'slug'
    http_method_names = ['get', 'patch', 'head', 'options']

    def partial_update(self, request, *args, **kwargs):
        rate = get_current_usd_to_toman_rate()
        if rate is None:
            return Response(
                {'detail': 'A valid exchange rate is required before changing website prices.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        instance = self.get_object()
        serializer = self.get_serializer(
            instance, data=request.data, partial=True,
            context={**self.get_serializer_context(), 'exchange_rate': rate},
        )
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)


@extend_schema(tags=['Website Dashboard - Services'])
class WebsiteServiceDashboardViewSet(WebsitePriceDashboardMixin, viewsets.ModelViewSet):
    queryset = SiteService.objects.all()
    serializer_class = SiteServiceDashboardSerializer


@extend_schema(tags=['Website Dashboard - Packages'])
class WebsitePackageDashboardViewSet(WebsitePriceDashboardMixin, viewsets.ModelViewSet):
    queryset = SitePackage.objects.all().prefetch_related('services')
    serializer_class = SitePackageDashboardSerializer


@extend_schema(tags=['Website Dashboard - Package Price Options'])
class WebsitePackagePriceOptionDashboardViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminOrEmployee]
    queryset = SitePackagePriceOption.objects.select_related('package').all()
    serializer_class = SitePackagePriceOptionDashboardSerializer
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    def _rate_context(self):
        rate = get_current_usd_to_toman_rate()
        if rate is None:
            return None, Response(
                {'detail': 'A valid exchange rate is required before changing website prices.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return rate, None

    def create(self, request, *args, **kwargs):
        rate, error = self._rate_context()
        if error:
            return error
        serializer = self.get_serializer(
            data=request.data,
            context={**self.get_serializer_context(), 'exchange_rate': rate},
        )
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        return Response(self.get_serializer(instance).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        rate, error = self._rate_context()
        if error:
            return error
        instance = self.get_object()
        serializer = self.get_serializer(
            instance, data=request.data, partial=True,
            context={**self.get_serializer_context(), 'exchange_rate': rate},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


@extend_schema(tags=['Website Dashboard - Settings'])
class WebsiteSettingsDashboardView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAdminOrEmployee]
    serializer_class = SiteSettingsSerializer

    def get_object(self):
        settings, _ = SiteSettings.objects.get_or_create(singleton_key='default')
        return settings


@extend_schema(tags=['Website Dashboard - Products'])
class WebsiteProductDashboardViewSet(WebsitePriceDashboardMixin, viewsets.ModelViewSet):
    queryset = SiteProduct.objects.all()
    serializer_class = SiteProductDashboardSerializer


@extend_schema(tags=['Website Dashboard - Sync'])
class WebsitePriceSyncStatusView(generics.RetrieveAPIView):
    permission_classes = [IsAdminOrEmployee]
    serializer_class = WebsitePriceSyncRunSerializer

    def get_object(self):
        return WebsitePriceSyncRun.objects.first()

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance is None:
            return Response({'detail': 'No website price synchronization has run yet.'}, status=status.HTTP_404_NOT_FOUND)
        return super().retrieve(request, *args, **kwargs)


@extend_schema(tags=['Website Dashboard - Login'])
class WebsiteDashboardLoginAPIView(ClinicTokenObtainPairView):
    """Website-dashboard login using the shared secure JWT cookie mechanism."""

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        # This dedicated browser login never exposes tokens in JSON, even if
        # the development setting enables body tokens for the general API.
        response.data.pop('access', None)
        response.data.pop('refresh', None)
        return response


@extend_schema(tags=['Site Team'])
class TeamMemberListView(PublicReadOnlyMixin, generics.ListAPIView):
    queryset = TeamMember.objects.filter(is_active=True)
    serializer_class = TeamMemberSerializer
    pagination_class = None


@extend_schema(tags=['Site Testimonials'])
class TestimonialListView(PublicReadOnlyMixin, generics.ListAPIView):
    queryset = Testimonial.objects.filter(is_active=True)
    serializer_class = TestimonialSerializer
    pagination_class = None


@extend_schema(tags=['Site Contact'])
class ContactMessageCreateView(generics.CreateAPIView):
    queryset = ContactMessage.objects.all()
    serializer_class = ContactMessageSerializer
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'contact'


__all__ = [
    'SiteServiceViewSet', 'SitePackageViewSet', 'SiteProductViewSet',
    'TeamMemberListView', 'TestimonialListView', 'ContactMessageCreateView',
    'WebsiteServiceDashboardViewSet', 'WebsitePackageDashboardViewSet',
    'WebsitePackagePriceOptionDashboardViewSet', 'WebsiteSettingsDashboardView',
    'WebsiteProductDashboardViewSet', 'WebsitePriceSyncStatusView',
    'WebsiteDashboardLoginAPIView',
]
