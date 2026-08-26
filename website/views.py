from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions, viewsets
from rest_framework.throttling import ScopedRateThrottle

from .models import (
    ContactMessage,
    SitePackage,
    SiteProduct,
    SiteService,
    TeamMember,
    Testimonial,
)
from .serializers import (
    ContactMessageSerializer,
    SitePackageSerializer,
    SiteProductSerializer,
    SiteServiceSerializer,
    TeamMemberSerializer,
    TestimonialSerializer,
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
]
