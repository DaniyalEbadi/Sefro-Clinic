from django.urls import path

from .views import (
    ClinicTokenObtainPairView,
    ClinicTokenRefreshView,
    EmployeeCreateAPIView,
    EmployeeListAPIView,
    EmployeeRetrieveUpdateDestroyAPIView,
    LogoutAPIView,
    MeAPIView,
)


app_name = 'accounts'

urlpatterns = [
    path('token/', ClinicTokenObtainPairView.as_view(), name='token-obtain-pair'),
    path('token/refresh/', ClinicTokenRefreshView.as_view(), name='token-refresh'),
    path('logout/', LogoutAPIView.as_view(), name='logout'),
    path('me/', MeAPIView.as_view(), name='me'),
    path('employees/', EmployeeCreateAPIView.as_view(), name='employee-create'),
    path('employees/list/', EmployeeListAPIView.as_view(), name='employee-list'),
    path('employees/<int:pk>/', EmployeeRetrieveUpdateDestroyAPIView.as_view(), name='employee-detail'),
]
