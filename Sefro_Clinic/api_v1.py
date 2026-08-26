from django.urls import include, path

from accounts.urls import urlpatterns as account_urls
from customers.urls import urlpatterns as customer_urls
from logs.urls import urlpatterns as log_urls

urlpatterns = [
    path(
        'api/v1/',
        include([
            path('auth/', include(account_urls)),
            path('', include(customer_urls)),
            path('logs/', include(log_urls)),
        ]),
    ),
]
