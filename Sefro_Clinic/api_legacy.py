from django.urls import include, path

urlpatterns = [
    path(
        'api/',
        include([
            path('auth/', include('accounts.urls')),
            path('', include('customers.urls')),
            path('inventory/', include('inventory.urls')),
            path('finance/', include('finance.urls')),
            path('', include('logs.urls')),
        ]),
    ),
]
