import logging
from math import ceil

from django.conf import settings as django_settings
from django.utils import timezone
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import generics, permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts.authentication import _CsrfChecker
from accounts.serializers import ClinicUserSerializer

from .authentication import (
    WebsiteDashboardAuthentication,
    clear_website_session_cookie,
    issue_website_session,
    session_from_request,
)
from .models import (
    ContactMessage,
    SitePackage,
    SitePackagePriceOption,
    SiteProduct,
    SiteService,
    SiteSettings,
    TeamMember,
    Testimonial,
    WebsiteManagerCredential,
    WebsitePriceSyncRun,
)
from .permissions import IsWebsiteManager
from .serializers import (
    ContactMessageDashboardSerializer,
    ContactMessageSerializer,
    SitePackageDashboardSerializer,
    SitePackagePriceOptionDashboardSerializer,
    SitePackageSerializer,
    SiteProductDashboardSerializer,
    SiteProductSerializer,
    SiteServiceDashboardSerializer,
    SiteServiceImageUploadSerializer,
    SiteServiceSerializer,
    SiteSettingsSerializer,
    TeamMemberDashboardSerializer,
    TeamMemberSerializer,
    TestimonialDashboardSerializer,
    TestimonialSerializer,
    WebsitePriceSyncRequestSerializer,
    WebsitePriceSyncRunSerializer,
    WebsitePriceSyncStatusSerializer,
)
from .services.image_storage import upload_service_image
from .services.pricing import get_website_dashboard_rate as get_current_usd_to_toman_rate
from .services.sync import WebsitePriceSyncAlreadyRunning, sync_website_prices
from .throttling import WebsiteDashboardThrottle, WebsitePublicReadThrottle

logger = logging.getLogger(__name__)


class PublicReadOnlyMixin:
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [WebsitePublicReadThrottle]


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
    authentication_classes = [WebsiteDashboardAuthentication]
    permission_classes = [IsWebsiteManager]
    throttle_classes = [WebsiteDashboardThrottle]
    lookup_field = 'slug'
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    def create(self, request, *args, **kwargs):
        rate = get_current_usd_to_toman_rate()
        if rate is None or not rate.is_finite() or rate <= 0:
            return Response(
                {'detail': 'A valid exchange rate is required before changing website prices.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        serializer = self.get_serializer(
            data=request.data, context={**self.get_serializer_context(), 'exchange_rate': rate},
        )
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        return Response(self.get_serializer(instance).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        description='Set a price using price (Toman) OR price_usd (USD). '
                    'Toman input is rounded upward to a whole Toman and converted to a precise USD base '
                    'for subsequent exchange-rate synchronization. Do not send both currencies for the same price. '
                    'Packages also accept original_price OR original_price_usd; null clears the original price.',
        examples=[
            OpenApiExample('Set price in Toman', value={'price': '1800000'}, request_only=True),
            OpenApiExample('Set price in USD', value={'price_usd': '10.50'}, request_only=True),
        ],
    )
    def partial_update(self, request, *args, **kwargs):
        context = self.get_serializer_context()
        if any(name in request.data for name in ('price', 'price_usd', 'original_price', 'original_price_usd')):
            rate = get_current_usd_to_toman_rate()
            if rate is None or not rate.is_finite() or rate <= 0:
                return Response(
                    {'detail': 'A valid exchange rate is required before changing website prices.'},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            context['exchange_rate'] = rate
        instance = self.get_object()
        serializer = self.get_serializer(
            instance, data=request.data, partial=True,
            context=context,
        )
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)


@extend_schema(tags=['Website Dashboard - Services'])
class WebsiteServiceDashboardViewSet(WebsitePriceDashboardMixin, viewsets.ModelViewSet):
    queryset = SiteService.objects.all()
    serializer_class = SiteServiceDashboardSerializer
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    def _price_context(self):
        rate = get_current_usd_to_toman_rate()
        if rate is None or not rate.is_finite() or rate <= 0:
            return None, Response(
                {'detail': 'A valid exchange rate is required before changing website prices.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return rate, None

    @extend_schema(description='Create a complete website service page. Send price (Toman) OR price_usd (USD).')
    def create(self, request, *args, **kwargs):
        rate, error = self._price_context()
        if error:
            return error
        serializer = self.get_serializer(
            data=request.data, context={**self.get_serializer_context(), 'exchange_rate': rate},
        )
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        return Response(self.get_serializer(instance).data, status=status.HTTP_201_CREATED)

    @extend_schema(description='Edit page text, image URL, visibility, or price. Price edits require a current exchange rate.')
    def partial_update(self, request, *args, **kwargs):
        context = self.get_serializer_context()
        if 'price' in request.data or 'price_usd' in request.data:
            rate, error = self._price_context()
            if error:
                return error
            context['exchange_rate'] = rate
        serializer = self.get_serializer(self.get_object(), data=request.data, partial=True, context=context)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @extend_schema(
        request=SiteServiceImageUploadSerializer,
        responses={200: SiteServiceDashboardSerializer},
        description='Upload the service hero image to farabaks3/baran-clinic/services/<slug>/. '
                    'Only the baran-clinic/ prefix should allow public reads for permanent URLs.',
    )
    @action(detail=True, methods=['post'], parser_classes=[MultiPartParser], url_path='image')
    def upload_image(self, request, *args, **kwargs):
        serializer = SiteServiceImageUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not request.FILES.get('image'):
            return Response({'image': ['Upload an image file.']}, status=status.HTTP_400_BAD_REQUEST)
        service = self.get_object()
        try:
            key, url = upload_service_image(service, request.FILES['image'])
        except RuntimeError:
            return Response({'detail': 'Website image storage is not configured.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except ValidationError:
            raise
        except Exception:
            logger.exception('Website service image upload failed')
            return Response({'detail': 'Website image upload failed.'}, status=status.HTTP_502_BAD_GATEWAY)
        service.image_object_key = key
        service.image_url = url
        service.is_manually_managed = True
        service.save(update_fields=['image_object_key', 'image_url', 'is_manually_managed'])
        return Response(self.get_serializer(service).data)


@extend_schema(tags=['Website Dashboard - Packages'])
class WebsitePackageDashboardViewSet(WebsitePriceDashboardMixin, viewsets.ModelViewSet):
    queryset = SitePackage.objects.all().prefetch_related('services')
    serializer_class = SitePackageDashboardSerializer


@extend_schema(tags=['Website Dashboard - Package Price Options'])
class WebsitePackagePriceOptionDashboardViewSet(viewsets.ModelViewSet):
    authentication_classes = [WebsiteDashboardAuthentication]
    permission_classes = [IsWebsiteManager]
    throttle_classes = [WebsiteDashboardThrottle]
    queryset = SitePackagePriceOption.objects.select_related('package').all()
    serializer_class = SitePackagePriceOptionDashboardSerializer
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    def _rate_context(self):
        rate = get_current_usd_to_toman_rate()
        if rate is None or not rate.is_finite() or rate <= 0:
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
        context = self.get_serializer_context()
        if 'price' in request.data or 'price_usd' in request.data:
            rate, error = self._rate_context()
            if error:
                return error
            context['exchange_rate'] = rate
        instance = self.get_object()
        serializer = self.get_serializer(
            instance, data=request.data, partial=True,
            context=context,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


@extend_schema(tags=['Website Dashboard - Settings'])
class WebsiteSettingsDashboardView(generics.RetrieveUpdateAPIView):
    authentication_classes = [WebsiteDashboardAuthentication]
    permission_classes = [IsWebsiteManager]
    throttle_classes = [WebsiteDashboardThrottle]
    serializer_class = SiteSettingsSerializer

    def get_object(self):
        settings, _ = SiteSettings.objects.get_or_create(singleton_key='default')
        return settings


@extend_schema(tags=['Site Settings'])
class SiteSettingsPublicView(generics.RetrieveAPIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [WebsitePublicReadThrottle]
    serializer_class = SiteSettingsSerializer

    def get_object(self):
        settings, _ = SiteSettings.objects.get_or_create(singleton_key='default')
        return settings


@extend_schema(tags=['Website Dashboard - Products'])
class WebsiteProductDashboardViewSet(WebsitePriceDashboardMixin, viewsets.ModelViewSet):
    queryset = SiteProduct.objects.all()
    serializer_class = SiteProductDashboardSerializer


@extend_schema(tags=['Website Dashboard - Sync'], responses=WebsitePriceSyncStatusSerializer)
class WebsitePriceSyncStatusView(generics.RetrieveAPIView):
    authentication_classes = [WebsiteDashboardAuthentication]
    permission_classes = [IsWebsiteManager]
    throttle_classes = [WebsiteDashboardThrottle]
    serializer_class = WebsitePriceSyncRunSerializer

    def get_object(self):
        return WebsitePriceSyncRun.objects.first()

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance is None:
            return Response({
                'id': None, 'status': 'never_run', 'provider': '', 'rate': None,
                'started_at': None, 'finished_at': None, 'updated_services': 0,
                'updated_packages': 0, 'updated_products': 0, 'error': '',
                'effective_rate': None, 'effective_rate_provider': '',
            })
        data = dict(self.get_serializer(instance).data)
        successful = WebsitePriceSyncRun.objects.filter(
            status=WebsitePriceSyncRun.Status.SUCCEEDED, rate__isnull=False,
        ).first()
        data['effective_rate'] = str(successful.rate) if successful else None
        data['effective_rate_provider'] = successful.provider if successful else ''
        return Response(data)


@extend_schema(
    tags=['Website Dashboard - Sync'],
    request=WebsitePriceSyncRequestSerializer,
    responses={200: WebsitePriceSyncRunSerializer},
)
class WebsitePriceSyncRunView(APIView):
    authentication_classes = [WebsiteDashboardAuthentication]
    permission_classes = [IsWebsiteManager]
    throttle_classes = [WebsiteDashboardThrottle]

    def post(self, request):
        serializer = WebsitePriceSyncRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        manual_rate = serializer.validated_data.get('rate')
        if manual_rate is None:
            latest = WebsitePriceSyncRun.objects.first()
            if latest and latest.finished_at:
                seconds_since_finish = (timezone.now() - latest.finished_at).total_seconds()
                if seconds_since_finish < 300:
                    response = dict(WebsitePriceSyncRunSerializer(latest).data)
                    response['cached'] = True
                    code = status.HTTP_200_OK if latest.status == WebsitePriceSyncRun.Status.SUCCEEDED else status.HTTP_503_SERVICE_UNAVAILABLE
                    return Response(response, status=code, headers={'Retry-After': str(ceil(300 - seconds_since_finish))})
        try:
            run = sync_website_prices(rate_override=manual_rate)
        except WebsitePriceSyncAlreadyRunning:
            return Response({'detail': 'A website price sync is already running.'}, status=status.HTTP_409_CONFLICT)
        except Exception:
            logger.exception('Website price synchronization failed')
            run = WebsitePriceSyncRun.objects.first()
            return Response(
                WebsitePriceSyncRunSerializer(run).data if run else {'detail': 'Website price sync failed.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        code = status.HTTP_200_OK if run.status == WebsitePriceSyncRun.Status.SUCCEEDED else status.HTTP_503_SERVICE_UNAVAILABLE
        response = dict(WebsitePriceSyncRunSerializer(run).data)
        response['cached'] = False
        return Response(response, status=code)


@extend_schema(tags=['Website Dashboard - Team'])
class WebsiteTeamDashboardViewSet(viewsets.ModelViewSet):
    authentication_classes = [WebsiteDashboardAuthentication]
    permission_classes = [IsWebsiteManager]
    throttle_classes = [WebsiteDashboardThrottle]
    queryset = TeamMember.objects.all()
    serializer_class = TeamMemberDashboardSerializer
    http_method_names = ['get', 'post', 'patch', 'head', 'options']


@extend_schema(tags=['Website Dashboard - Testimonials'])
class WebsiteTestimonialDashboardViewSet(viewsets.ModelViewSet):
    authentication_classes = [WebsiteDashboardAuthentication]
    permission_classes = [IsWebsiteManager]
    throttle_classes = [WebsiteDashboardThrottle]
    queryset = Testimonial.objects.all()
    serializer_class = TestimonialDashboardSerializer
    http_method_names = ['get', 'post', 'patch', 'head', 'options']


@extend_schema(tags=['Website Dashboard - Contacts'])
class WebsiteContactDashboardViewSet(viewsets.ReadOnlyModelViewSet):
    authentication_classes = [WebsiteDashboardAuthentication]
    permission_classes = [IsWebsiteManager]
    throttle_classes = [WebsiteDashboardThrottle]
    queryset = ContactMessage.objects.all()
    serializer_class = ContactMessageDashboardSerializer
    http_method_names = ['get', 'patch', 'head', 'options']

    def partial_update(self, request, *args, **kwargs):
        if set(request.data) != {'is_handled'}:
            raise ValidationError({'is_handled': 'Only is_handled may be changed.'})
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class WebsiteDashboardLoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)


@extend_schema(tags=['Website Dashboard - Login'], request=WebsiteDashboardLoginSerializer)
class WebsiteDashboardLoginAPIView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'website_login'

    def post(self, request):
        serializer = WebsiteDashboardLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        credential = WebsiteManagerCredential.objects.select_related('user').filter(
            username=serializer.validated_data['username'],
        ).first()
        if not credential or not credential.check_password(serializer.validated_data['password']):
            return Response({'detail': 'Invalid website credentials.'}, status=status.HTTP_401_UNAUTHORIZED)
        if not credential.is_active or not credential.user.is_active:
            return Response({'detail': 'Invalid website credentials.'}, status=status.HTTP_401_UNAUTHORIZED)
        response = Response({'detail': 'Logged in.'})
        issue_website_session(response, request, credential)
        return response


@extend_schema(tags=['Website Dashboard - Login'], responses=ClinicUserSerializer)
class WebsiteDashboardMeAPIView(APIView):
    authentication_classes = [WebsiteDashboardAuthentication]
    permission_classes = [IsWebsiteManager]
    throttle_classes = [WebsiteDashboardThrottle]

    def get(self, request):
        return Response(ClinicUserSerializer(request.user).data)


@extend_schema(tags=['Website Dashboard - Login'])
class WebsiteDashboardLogoutAPIView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = []

    def post(self, request):
        if request.COOKIES.get(django_settings.WEBSITE_DASHBOARD_COOKIE):
            checker = _CsrfChecker(lambda req: None)
            checker.process_request(request)
            if checker.process_view(request, None, (), {}):
                raise PermissionDenied('CSRF verification failed.')
        session = session_from_request(request)
        if session and session.revoked_at is None:
            session.revoked_at = timezone.now()
            session.save(update_fields=['revoked_at'])
        response = Response({'detail': 'Logged out.'})
        clear_website_session_cookie(response)
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
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'contact'


__all__ = [
    'SiteServiceViewSet', 'SitePackageViewSet', 'SiteProductViewSet',
    'TeamMemberListView', 'TestimonialListView', 'ContactMessageCreateView',
    'WebsiteServiceDashboardViewSet', 'WebsitePackageDashboardViewSet',
    'WebsitePackagePriceOptionDashboardViewSet', 'WebsiteSettingsDashboardView',
    'SiteSettingsPublicView',
    'WebsiteProductDashboardViewSet', 'WebsitePriceSyncStatusView',
    'WebsiteDashboardLoginAPIView',
]
